"""Multi-segment HTTP(S) download worker with resume and speed limits."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from arrowdl.utils import (
    compute_segments,
    filename_from_content_disposition,
    filename_from_url,
    meta_path,
    part_path,
    sanitize_filename,
)


ProgressCallback = Callable[[int, int, float], None]  # downloaded, total, speed
StatusCallback = Callable[[str, str], None]  # status, error_message


class SpeedLimiter:
    """Thread-safe rate limiter (global + per-download).

    Uses a leaky/token bucket whose capacity is at least one chunk so large
    reads cannot deadlock when limit < chunk size.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global_limit = 0  # bytes/sec, 0 = unlimited
        self._global_tokens = 0.0
        self._global_last = time.monotonic()
        self._per: dict[int, dict] = {}  # download_id -> state

    def set_global_limit(self, bps: int) -> None:
        with self._lock:
            self._global_limit = max(0, int(bps))

    def set_download_limit(self, download_id: int, bps: int) -> None:
        with self._lock:
            if download_id not in self._per:
                self._per[download_id] = {
                    "limit": 0,
                    "tokens": 0.0,
                    "last": time.monotonic(),
                }
            self._per[download_id]["limit"] = max(0, int(bps))

    def remove_download(self, download_id: int) -> None:
        with self._lock:
            self._per.pop(download_id, None)

    @staticmethod
    def _consume(tokens: float, last: float, limit: int, nbytes: int, now: float) -> tuple[float, float, float]:
        """Return (new_tokens, new_last, wait_seconds)."""
        if limit <= 0:
            return tokens, last, 0.0
        capacity = max(float(limit) * 2.0, float(nbytes))  # >= one chunk
        elapsed = max(0.0, now - last)
        tokens = min(capacity, tokens + elapsed * limit)
        last = now
        if tokens >= nbytes:
            return tokens - nbytes, last, 0.0
        need = nbytes - tokens
        wait = need / limit
        # Keep tokens; after sleep the refill will cover the shortfall
        return tokens, last, wait

    def throttle(self, download_id: int, nbytes: int) -> None:
        """Block until nbytes are allowed under global + per-download limits."""
        if nbytes <= 0:
            return
        while True:
            wait = 0.0
            with self._lock:
                now = time.monotonic()
                self._global_tokens, self._global_last, w = self._consume(
                    self._global_tokens, self._global_last, self._global_limit, nbytes, now
                )
                wait = max(wait, w)
                st = self._per.get(download_id)
                if st is not None:
                    st["tokens"], st["last"], w2 = self._consume(
                        st["tokens"], st["last"], st["limit"], nbytes, now
                    )
                    wait = max(wait, w2)
            if wait <= 0:
                return
            time.sleep(min(wait, 0.5))


class DownloadWorker:
    """
    Downloads a single file with optional multi-segment Range requests.
    Writes to `.arrowdl.part` and `.arrowdl.meta` for resume, then renames.
    """

    def __init__(
        self,
        download_id: int,
        url: str,
        save_path: str,
        filename: str,
        segments: int,
        speed_limit: int,
        limiter: SpeedLimiter,
        on_progress: Optional[ProgressCallback] = None,
        on_status: Optional[StatusCallback] = None,
        timeout: float = 30.0,
    ) -> None:
        self.download_id = download_id
        self.url = url
        self.save_path = save_path
        self.filename = filename
        self.segments = max(1, min(16, segments))
        self.speed_limit = speed_limit
        self.limiter = limiter
        self.on_progress = on_progress
        self.on_status = on_status
        self.timeout = timeout

        self._pause = threading.Event()
        self._pause.set()  # set = running
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._downloaded = 0
        self._total = 0
        self._speed = 0.0
        self._lock = threading.Lock()

    def start(self) -> None:
        self.limiter.set_download_limit(self.download_id, self.speed_limit)
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"dl-{self.download_id}")
        self._thread.start()

    def pause(self) -> None:
        self._pause.clear()

    def resume(self) -> None:
        self._pause.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.set()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def join(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _wait_if_paused(self) -> bool:
        """Return False if cancelled while waiting."""
        while not self._pause.is_set():
            if self._cancel.is_set():
                return False
            time.sleep(0.1)
        return not self._cancel.is_set()

    def _emit_progress(self) -> None:
        if self.on_progress:
            with self._lock:
                d, t, s = self._downloaded, self._total, self._speed
            try:
                self.on_progress(d, t, s)
            except Exception:
                pass

    def _emit_status(self, status: str, error: str = "") -> None:
        if self.on_status:
            try:
                self.on_status(status, error)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            self._emit_status("downloading")
            self._do_download()
        except Exception as exc:
            if self._cancel.is_set():
                self._emit_status("cancelled")
            else:
                self._emit_status("failed", str(exc))
        finally:
            self.limiter.remove_download(self.download_id)

    def _probe(self, client: httpx.Client) -> tuple[int, bool, str]:
        """Return (content_length, accept_ranges, resolved_filename)."""
        filename = self.filename
        total = 0
        accept_ranges = False

        try:
            head = client.head(self.url, follow_redirects=True)
            if head.status_code < 400:
                cl = head.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total = int(cl)
                ar = head.headers.get("Accept-Ranges", "").lower()
                accept_ranges = ar == "bytes"
                cd = filename_from_content_disposition(
                    head.headers.get("Content-Disposition")
                )
                if cd and (not self.filename or self.filename == "download"):
                    filename = cd
        except Exception:
            pass

        if total <= 0 or not filename or filename == "download":
            # Fallback GET with stream to read headers
            with client.stream("GET", self.url, follow_redirects=True) as resp:
                resp.raise_for_status()
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total = int(cl)
                ar = resp.headers.get("Accept-Ranges", "").lower()
                if ar == "bytes":
                    accept_ranges = True
                cd = filename_from_content_disposition(
                    resp.headers.get("Content-Disposition")
                )
                if cd and (not filename or filename == "download"):
                    filename = cd
                if not filename or filename == "download":
                    filename = filename_from_url(str(resp.url))
                # Don't consume body — we'll re-request
                # (stream context exit closes connection)

        filename = sanitize_filename(filename or filename_from_url(self.url))
        return total, accept_ranges, filename

    def _load_meta(self, mpath: Path) -> Optional[dict]:
        if not mpath.exists():
            return None
        try:
            return json.loads(mpath.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _save_meta(self, mpath: Path, meta: dict) -> None:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        tmp = mpath.with_suffix(mpath.suffix + ".tmp")
        tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        tmp.replace(mpath)

    def _do_download(self) -> None:
        Path(self.save_path).mkdir(parents=True, exist_ok=True)
        limits = httpx.Limits(max_connections=self.segments + 2, max_keepalive_connections=self.segments)
        with httpx.Client(timeout=self.timeout, follow_redirects=True, limits=limits) as client:
            total, accept_ranges, filename = self._probe(client)
            self.filename = filename
            self._total = total

            ppath = part_path(self.save_path, filename)
            mpath = meta_path(self.save_path, filename)
            final = Path(self.save_path) / filename

            use_multi = accept_ranges and total > 0 and self.segments > 1

            if use_multi:
                ok = self._download_multi(client, total, ppath, mpath)
            else:
                ok = self._download_single(client, total, ppath, mpath)

            if self._cancel.is_set():
                self._emit_status("cancelled")
                return

            if not ok:
                return  # status already emitted (failed/paused handled elsewhere)

            # Assemble / rename
            if not ppath.exists():
                self._emit_status("failed", "Part file missing after download")
                return

            if final.exists():
                final.unlink()
            ppath.replace(final)
            if mpath.exists():
                mpath.unlink()

            try:
                size = final.stat().st_size
                with self._lock:
                    self._downloaded = size
                    if self._total <= 0:
                        self._total = size
            except OSError:
                pass
            self._emit_progress()
            self._emit_status("completed")

    def _download_single(
        self,
        client: httpx.Client,
        total: int,
        ppath: Path,
        mpath: Path,
    ) -> bool:
        """Single-connection download with optional resume via Range."""
        existing = 0
        if ppath.exists():
            existing = ppath.stat().st_size

        headers = {}
        mode = "wb"
        if existing > 0 and total > 0 and existing < total:
            headers["Range"] = f"bytes={existing}-"
            mode = "ab"
        elif existing > 0 and total > 0 and existing >= total:
            with self._lock:
                self._downloaded = existing
                self._total = total
            self._emit_progress()
            return True
        else:
            existing = 0

        with self._lock:
            self._downloaded = existing
            self._total = total

        speed_window: list[tuple[float, int]] = []
        try:
            with client.stream("GET", self.url, headers=headers, follow_redirects=True) as resp:
                if resp.status_code == 416:
                    # Range not satisfiable — restart
                    existing = 0
                    mode = "wb"
                    headers = {}
                    with client.stream("GET", self.url, follow_redirects=True) as resp2:
                        return self._consume_stream(resp2, ppath, "wb", 0, total, mpath, single=True)
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()
                # If we asked for Range but got 200, restart from 0
                if headers.get("Range") and resp.status_code == 200:
                    existing = 0
                    mode = "wb"
                return self._consume_stream(resp, ppath, mode, existing, total, mpath, single=True)
        except Exception as exc:
            if self._cancel.is_set():
                return False
            self._emit_status("failed", str(exc))
            return False

    def _consume_stream(
        self,
        resp: httpx.Response,
        ppath: Path,
        mode: str,
        already: int,
        total: int,
        mpath: Path,
        single: bool = False,
        seg_index: int | None = None,
        seg_end: int | None = None,
        seg_progress: dict | None = None,
        seg_lock: threading.Lock | None = None,
    ) -> bool:
        chunk_size = 64 * 1024
        downloaded_here = already
        last_meta = time.monotonic()
        last_speed_t = time.monotonic()
        last_speed_b = downloaded_here
        window_bytes = 0
        window_t0 = time.monotonic()

        ppath.parent.mkdir(parents=True, exist_ok=True)
        with open(ppath, mode) as f:
            for chunk in resp.iter_bytes(chunk_size):
                if self._cancel.is_set():
                    return False
                if not self._wait_if_paused():
                    return False

                if not chunk:
                    continue

                self.limiter.throttle(self.download_id, len(chunk))
                f.write(chunk)
                downloaded_here += len(chunk)
                window_bytes += len(chunk)

                now = time.monotonic()
                elapsed = now - window_t0
                if elapsed >= 0.4:
                    speed = window_bytes / elapsed if elapsed > 0 else 0.0
                    window_bytes = 0
                    window_t0 = now
                    with self._lock:
                        self._speed = speed
                        if single:
                            self._downloaded = downloaded_here
                            if total > 0:
                                self._total = total
                    self._emit_progress()

                # Periodic meta for single
                if single and now - last_meta >= 1.0:
                    self._save_meta(
                        mpath,
                        {
                            "url": self.url,
                            "filename": self.filename,
                            "total": total,
                            "mode": "single",
                            "downloaded": downloaded_here,
                        },
                    )
                    last_meta = now

                if seg_progress is not None and seg_index is not None and seg_lock is not None:
                    with seg_lock:
                        seg_progress[seg_index] = downloaded_here - already + (
                            # store absolute written for this segment from start of range
                            # actually: store current absolute offset position
                        )
                        # Better: store bytes written in this segment session + initial offset
                    # Simpler approach handled in multi wrapper

                if seg_end is not None and downloaded_here > seg_end + 1:
                    break

        if single:
            with self._lock:
                self._downloaded = downloaded_here
            self._emit_progress()
            self._save_meta(
                mpath,
                {
                    "url": self.url,
                    "filename": self.filename,
                    "total": total,
                    "mode": "single",
                    "downloaded": downloaded_here,
                },
            )
        return True

    def _download_multi(
        self,
        client: httpx.Client,
        total: int,
        ppath: Path,
        mpath: Path,
    ) -> bool:
        ranges = compute_segments(total, self.segments)
        n = len(ranges)
        meta = self._load_meta(mpath)
        seg_done = [0] * n  # bytes completed per segment (relative to range start)

        if meta and meta.get("mode") == "multi" and meta.get("total") == total and meta.get("url") == self.url:
            prev = meta.get("segments", [])
            if len(prev) == n:
                for i, s in enumerate(prev):
                    seg_done[i] = int(s.get("done", 0))

        # Pre-allocate part file
        if not ppath.exists() or ppath.stat().st_size != total:
            ppath.parent.mkdir(parents=True, exist_ok=True)
            with open(ppath, "wb") as f:
                f.truncate(total)

        seg_lock = threading.Lock()
        errors: list[str] = []
        cancelled = threading.Event()

        def segment_worker(idx: int, start: int, end: int) -> None:
            done = seg_done[idx]
            abs_start = start + done
            if abs_start > end:
                return
            headers = {"Range": f"bytes={abs_start}-{end}"}
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as seg_client:
                    with seg_client.stream("GET", self.url, headers=headers) as resp:
                        if resp.status_code not in (200, 206):
                            # Fall back signal
                            raise RuntimeError(f"Segment {idx} HTTP {resp.status_code}")
                        if resp.status_code == 200:
                            # Server ignored Range — abort multi
                            raise RuntimeError("Server ignored Range; falling back")

                        chunk_size = 64 * 1024
                        pos = abs_start
                        window_bytes = 0
                        window_t0 = time.monotonic()

                        with open(ppath, "r+b") as f:
                            f.seek(pos)
                            for chunk in resp.iter_bytes(chunk_size):
                                if self._cancel.is_set() or cancelled.is_set():
                                    cancelled.set()
                                    return
                                if not self._wait_if_paused():
                                    cancelled.set()
                                    return
                                if not chunk:
                                    continue
                                # Don't write past end
                                remaining = end - pos + 1
                                if remaining <= 0:
                                    break
                                if len(chunk) > remaining:
                                    chunk = chunk[:remaining]

                                self.limiter.throttle(self.download_id, len(chunk))
                                f.write(chunk)
                                pos += len(chunk)
                                done_now = pos - start
                                with seg_lock:
                                    seg_done[idx] = done_now
                                window_bytes += len(chunk)

                                now = time.monotonic()
                                elapsed = now - window_t0
                                if elapsed >= 0.4:
                                    speed = window_bytes / elapsed
                                    window_bytes = 0
                                    window_t0 = now
                                    with self._lock:
                                        self._speed = speed
                                        self._downloaded = sum(seg_done)
                                        self._total = total
                                    self._emit_progress()

                        with seg_lock:
                            seg_done[idx] = end - start + 1
            except Exception as exc:
                with seg_lock:
                    errors.append(str(exc))
                cancelled.set()

        threads = []
        for i, (s, e) in enumerate(ranges):
            t = threading.Thread(target=segment_worker, args=(i, s, e), daemon=True)
            threads.append(t)
            t.start()

        # Progress / meta saver while segments run
        while any(t.is_alive() for t in threads):
            if self._cancel.is_set():
                cancelled.set()
            with self._lock:
                self._downloaded = sum(seg_done)
                self._total = total
            self._emit_progress()
            self._save_meta(
                mpath,
                {
                    "url": self.url,
                    "filename": self.filename,
                    "total": total,
                    "mode": "multi",
                    "segments": [
                        {"start": ranges[i][0], "end": ranges[i][1], "done": seg_done[i]}
                        for i in range(n)
                    ],
                },
            )
            time.sleep(0.5)

        for t in threads:
            t.join(timeout=1)

        if self._cancel.is_set() or cancelled.is_set():
            if errors and not self._cancel.is_set():
                # Check if we should fall back to single
                if any("ignored Range" in e or "falling back" in e for e in errors):
                    return self._download_single(client, total, ppath, mpath)
                self._emit_status("failed", "; ".join(errors[:3]))
                return False
            return False

        if errors:
            self._emit_status("failed", "; ".join(errors[:3]))
            return False

        with self._lock:
            self._downloaded = total
            self._total = total
        self._emit_progress()
        return True


def probe_url(url: str, timeout: float = 15.0) -> tuple[str, int]:
    """Return (filename, content_length) for Add Download dialog."""
    filename = filename_from_url(url)
    total = 0
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            try:
                head = client.head(url)
                if head.status_code < 400:
                    cd = filename_from_content_disposition(
                        head.headers.get("Content-Disposition")
                    )
                    if cd:
                        filename = cd
                    cl = head.headers.get("Content-Length")
                    if cl and cl.isdigit():
                        total = int(cl)
                    return filename, total
            except Exception:
                pass
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                cd = filename_from_content_disposition(
                    resp.headers.get("Content-Disposition")
                )
                if cd:
                    filename = cd
                else:
                    filename = filename_from_url(str(resp.url))
                cl = resp.headers.get("Content-Length")
                if cl and cl.isdigit():
                    total = int(cl)
    except Exception:
        pass
    return sanitize_filename(filename), total
