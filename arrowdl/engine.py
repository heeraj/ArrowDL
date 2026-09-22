"""Download engine orchestration and scheduler."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from arrowdl.config import ensure_category_dirs
from arrowdl.db import Database
from arrowdl.downloader import DownloadWorker, SpeedLimiter
from arrowdl.models import DownloadItem, DownloadStatus


MAX_ENGINE_RESTARTS = 3


def _parse_start_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


class DownloadEngine:
    """
    Polls DB every ~0.5s, starts downloads up to max_concurrent,
    promotes scheduled items when start_at is reached.
    Auto-requeues workers that die mid-download (bounded retries).
    """

    def __init__(self, db: Database) -> None:
        self.db = db
        self.limiter = SpeedLimiter()
        self._workers: dict[int, DownloadWorker] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._runtime: dict[int, dict] = {}
        self._paused_all = False

        settings = db.get_settings()
        self.limiter.set_global_limit(settings.global_speed_limit)
        ensure_category_dirs(
            settings.base_download_folder,
            {
                "Software": settings.category_software,
                "Docs": settings.category_docs,
                "Videos": settings.category_videos,
                "Other": settings.category_other,
            },
        )

    def start(self) -> None:
        # Recover: mark stuck 'downloading' as queued (auto-resume) if part exists,
        # else paused so user can resume.
        for item in self.db.list_downloads(status=DownloadStatus.DOWNLOADING.value):
            part = Path(item.save_path) / f"{item.filename}.arrowdl.part"
            if part.exists() and item.engine_retries < MAX_ENGINE_RESTARTS:
                self.db.update_download(
                    item.id,
                    status=DownloadStatus.QUEUED.value,
                    engine_retries=item.engine_retries + 1,
                )
            else:
                self.db.update_download(item.id, status=DownloadStatus.PAUSED.value)
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="arrowdl-engine")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for w in list(self._workers.values()):
                w.pause()
            workers = list(self._workers.values())
        for w in workers:
            w.join(timeout=2)
        if self._thread:
            self._thread.join(timeout=3)

    def reload_settings(self) -> None:
        s = self.db.get_settings()
        self.limiter.set_global_limit(s.global_speed_limit)
        ensure_category_dirs(
            s.base_download_folder,
            {
                "Software": s.category_software,
                "Docs": s.category_docs,
                "Videos": s.category_videos,
                "Other": s.category_other,
            },
        )

    def get_runtime(self, item_id: int) -> dict:
        with self._lock:
            base = {
                "speed": 0.0,
                "eta": None,
                "segments": 0,
                "active_segments": 0,
                "retries": 0,
            }
            base.update(self._runtime.get(item_id, {}))
            w = self._workers.get(item_id)
            if w:
                base["retries"] = w.retry_count
                base["segments"] = w.num_segments
                base["active_segments"] = w.active_segments
                if "speed" not in self._runtime.get(item_id, {}):
                    with w._lock:
                        base["speed"] = w._speed
            return base

    def add_download(self, item: DownloadItem) -> int:
        if item.start_at:
            dt = _parse_start_at(item.start_at)
            if dt and dt > datetime.now(timezone.utc):
                item.status = DownloadStatus.SCHEDULED.value
            else:
                item.status = DownloadStatus.QUEUED.value
                item.start_at = None
        else:
            item.status = DownloadStatus.QUEUED.value
        return self.db.add_download(item)

    def pause(self, item_id: int) -> None:
        with self._lock:
            w = self._workers.get(item_id)
            if w:
                w.pause()
        self.db.update_download(item_id, status=DownloadStatus.PAUSED.value)

    def resume(self, item_id: int) -> None:
        """Resume a paused/failed/cancelled item. No-op if completed or missing."""
        item = self.db.get_download(item_id)
        if not item:
            return
        # Critical: never treat completed as resumable (would feel like a restart).
        if item.status == DownloadStatus.COMPLETED.value:
            return
        if item.status == DownloadStatus.DOWNLOADING.value:
            # Already running — wake worker if paused mid-flight
            with self._lock:
                w = self._workers.get(item_id)
                if w:
                    w.resume()
            return
        if item.status in (
            DownloadStatus.PAUSED.value,
            DownloadStatus.FAILED.value,
            DownloadStatus.CANCELLED.value,
            DownloadStatus.QUEUED.value,
        ):
            if item.status != DownloadStatus.QUEUED.value:
                self.db.update_download(
                    item_id,
                    status=DownloadStatus.QUEUED.value,
                    error_message="",
                    engine_retries=0,
                )
        with self._lock:
            w = self._workers.get(item_id)
            if w:
                w.resume()

    def restart(self, item_id: int) -> None:
        """Delete part/meta/final file and re-queue from scratch (Re-download)."""
        item = self.db.get_download(item_id)
        if not item or item.id is None:
            return
        with self._lock:
            w = self._workers.pop(item_id, None)
        if w:
            try:
                w.cancel()
            except Exception:
                pass
            w.join(timeout=2)
        self._delete_files(item)
        self.limiter.remove_download(item_id)
        self.db.update_download(
            item_id,
            status=DownloadStatus.QUEUED.value,
            downloaded=0,
            total_size=0,
            error_message="",
            engine_retries=0,
            start_at=None,
        )
        with self._lock:
            self._runtime.pop(item_id, None)

    def set_item_speed_limit(self, item_id: int, bps: int) -> None:
        """Persist per-download speed limit and apply to live limiter."""
        bps = max(0, int(bps))
        self.db.update_download(item_id, speed_limit=bps)
        self.limiter.set_download_limit(item_id, bps)

    def cancel(self, item_id: int) -> None:
        with self._lock:
            w = self._workers.get(item_id)
            if w:
                w.cancel()
        self.db.update_download(item_id, status=DownloadStatus.CANCELLED.value)

    def pause_all(self) -> None:
        self._paused_all = True
        for item in self.db.list_downloads():
            if item.status in (
                DownloadStatus.DOWNLOADING.value,
                DownloadStatus.QUEUED.value,
            ):
                self.pause(item.id)

    def resume_all(self) -> None:
        self._paused_all = False
        for item in self.db.list_downloads():
            if item.status == DownloadStatus.PAUSED.value:
                self.resume(item.id)

    def delete(self, item_id: int, delete_files: bool = False) -> None:
        item = self.db.get_download(item_id)
        with self._lock:
            w = self._workers.pop(item_id, None)
        if w:
            w.cancel()
            w.join(timeout=2)
        if delete_files and item:
            self._delete_files(item)
        self.db.delete_download(item_id)
        with self._lock:
            self._runtime.pop(item_id, None)

    def _delete_files(self, item: DownloadItem) -> None:
        paths = [
            Path(item.save_path) / item.filename,
            Path(item.save_path) / f"{item.filename}.arrowdl.part",
            Path(item.save_path) / f"{item.filename}.arrowdl.meta",
        ]
        for p in paths:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:
                pass
            self._stop.wait(0.5)

    def _tick(self) -> None:
        if self._paused_all:
            return

        settings = self.db.get_settings()
        self.limiter.set_global_limit(settings.global_speed_limit)
        max_c = max(1, settings.max_concurrent)
        now = datetime.now(timezone.utc)

        for item in self.db.list_downloads(status=DownloadStatus.SCHEDULED.value):
            dt = _parse_start_at(item.start_at)
            if dt is None or dt <= now:
                self.db.update_download(
                    item.id, status=DownloadStatus.QUEUED.value, start_at=None
                )

        # Clean finished workers; auto-requeue if died while still downloading
        with self._lock:
            finished = [i for i, w in self._workers.items() if not w.is_alive()]
            for i in finished:
                self._workers.pop(i, None)
                self._maybe_requeue_dead(i)

        active = len(self._workers)
        slots = max_c - active
        if slots <= 0:
            return

        queued = self.db.list_downloads(status=DownloadStatus.QUEUED.value)
        queued.sort(key=lambda x: x.id or 0)
        for item in queued[:slots]:
            self._start_worker(item)

    def _maybe_requeue_dead(self, item_id: int) -> None:
        """If worker died but DB still says downloading and part incomplete, re-queue."""
        item = self.db.get_download(item_id)
        if not item:
            return
        if item.status != DownloadStatus.DOWNLOADING.value:
            return
        # Incomplete?
        incomplete = True
        if item.total_size > 0 and item.downloaded >= item.total_size:
            incomplete = False
        part = Path(item.save_path) / f"{item.filename}.arrowdl.part"
        if incomplete and item.engine_retries < MAX_ENGINE_RESTARTS:
            self.db.update_download(
                item_id,
                status=DownloadStatus.QUEUED.value,
                error_message="",
                engine_retries=item.engine_retries + 1,
            )
        elif incomplete:
            self.db.update_download(
                item_id,
                status=DownloadStatus.FAILED.value,
                error_message="Worker stopped unexpectedly (retries exhausted)",
            )

    def _start_worker(self, item: DownloadItem) -> None:
        if item.id is None:
            return
        with self._lock:
            if item.id in self._workers:
                return

        self.db.update_download(
            item.id, status=DownloadStatus.DOWNLOADING.value, error_message=""
        )

        def on_progress(downloaded: int, total: int, speed: float) -> None:
            eta = None
            if speed > 0 and total > downloaded:
                eta = (total - downloaded) / speed
            with self._lock:
                rt = self._runtime.setdefault(item.id, {})
                rt["speed"] = speed
                rt["eta"] = eta
                w = self._workers.get(item.id)
                if w:
                    rt["retries"] = w.retry_count
                    rt["segments"] = w.num_segments
                    rt["active_segments"] = w.active_segments
            self.db.update_download(
                item.id,
                downloaded=downloaded,
                total_size=total if total > 0 else item.total_size,
            )

        def on_status(status: str, error: str = "") -> None:
            mapping = {
                "downloading": DownloadStatus.DOWNLOADING.value,
                "completed": DownloadStatus.COMPLETED.value,
                "failed": DownloadStatus.FAILED.value,
                "cancelled": DownloadStatus.CANCELLED.value,
                "paused": DownloadStatus.PAUSED.value,
            }
            st = mapping.get(status, status)
            fields: dict = {"status": st, "error_message": error or ""}
            with self._lock:
                w = self._workers.get(item.id)
            if w and w.filename and w.filename != item.filename:
                fields["filename"] = w.filename
            if st == DownloadStatus.COMPLETED.value and w:
                with w._lock:
                    fields["downloaded"] = w._downloaded
                    if w._total > 0:
                        fields["total_size"] = w._total
                fields["engine_retries"] = 0
                with self._lock:
                    self._runtime[item.id] = {
                        "speed": 0.0,
                        "eta": None,
                        "segments": 0,
                        "active_segments": 0,
                        "retries": 0,
                    }
            self.db.update_download(item.id, **fields)

        worker = DownloadWorker(
            download_id=item.id,
            url=item.url,
            save_path=item.save_path,
            filename=item.filename,
            segments=item.segments,
            speed_limit=item.speed_limit,
            limiter=self.limiter,
            on_progress=on_progress,
            on_status=on_status,
        )
        with self._lock:
            self._workers[item.id] = worker
            self._runtime[item.id] = {
                "speed": 0.0,
                "eta": None,
                "segments": item.segments,
                "active_segments": 0,
                "retries": 0,
            }
        worker.start()
