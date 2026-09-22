"""SQLite persistence for downloads and settings."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from arrowdl.config import (
    DEFAULT_GLOBAL_SPEED_LIMIT,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_SEGMENTS,
    get_db_path,
    get_default_download_base,
)
from arrowdl.models import AppSettings, DownloadItem, DownloadStatus, default_close_to_tray


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Database:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else get_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    save_path TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Other',
                    status TEXT NOT NULL DEFAULT 'queued',
                    total_size INTEGER NOT NULL DEFAULT 0,
                    downloaded INTEGER NOT NULL DEFAULT 0,
                    segments INTEGER NOT NULL DEFAULT 4,
                    speed_limit INTEGER NOT NULL DEFAULT 0,
                    start_at TEXT,
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._conn.commit()
            self._migrate_columns()
            self._ensure_default_settings()

    def _migrate_columns(self) -> None:
        """Additive migrations for existing DBs."""
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(downloads)").fetchall()
        }
        if "engine_retries" not in cols:
            self._conn.execute(
                "ALTER TABLE downloads ADD COLUMN engine_retries INTEGER NOT NULL DEFAULT 0"
            )
            self._conn.commit()

    def _ensure_default_settings(self) -> None:
        defaults = {
            "default_segments": str(DEFAULT_SEGMENTS),
            "max_concurrent": str(DEFAULT_MAX_CONCURRENT),
            "global_speed_limit": str(DEFAULT_GLOBAL_SPEED_LIMIT),
            "base_download_folder": str(get_default_download_base()),
            "category_software": "Software",
            "category_docs": "Docs",
            "category_videos": "Videos",
            "category_other": "Other",
            "start_with_windows": "0",
            "close_to_tray": "1" if default_close_to_tray() else "0",
            "sound_on_complete": "0",
        }
        for k, v in defaults.items():
            cur = self._conn.execute("SELECT 1 FROM settings WHERE key=?", (k,))
            if cur.fetchone() is None:
                self._conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)", (k, v)
                )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── downloads ──────────────────────────────────────────────

    def _row_to_item(self, row: sqlite3.Row) -> DownloadItem:
        keys = row.keys()
        return DownloadItem(
            id=row["id"],
            url=row["url"],
            filename=row["filename"],
            save_path=row["save_path"],
            category=row["category"],
            status=row["status"],
            total_size=row["total_size"],
            downloaded=row["downloaded"],
            segments=row["segments"],
            speed_limit=row["speed_limit"],
            start_at=row["start_at"],
            error_message=row["error_message"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            engine_retries=int(row["engine_retries"]) if "engine_retries" in keys else 0,
        )

    def add_download(self, item: DownloadItem) -> int:
        now = _utcnow_iso()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO downloads (
                    url, filename, save_path, category, status,
                    total_size, downloaded, segments, speed_limit,
                    start_at, error_message, created_at, updated_at, engine_retries
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.url,
                    item.filename,
                    item.save_path,
                    item.category,
                    item.status,
                    item.total_size,
                    item.downloaded,
                    item.segments,
                    item.speed_limit,
                    item.start_at,
                    item.error_message,
                    now,
                    now,
                    item.engine_retries,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_download(self, item_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = _utcnow_iso()
        cols = ", ".join(f"{k}=?" for k in fields)
        values = list(fields.values()) + [item_id]
        with self._lock:
            self._conn.execute(
                f"UPDATE downloads SET {cols} WHERE id=?", values
            )
            self._conn.commit()

    def get_download(self, item_id: int) -> Optional[DownloadItem]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM downloads WHERE id=?", (item_id,)
            )
            row = cur.fetchone()
            return self._row_to_item(row) if row else None

    def list_downloads(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[DownloadItem]:
        sql = "SELECT * FROM downloads WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND status=?"
            params.append(status)
        if category:
            sql += " AND category=?"
            params.append(category)
        sql += " ORDER BY id DESC"
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [self._row_to_item(r) for r in cur.fetchall()]

    def delete_download(self, item_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM downloads WHERE id=?", (item_id,))
            self._conn.commit()

    def clear_completed(self) -> int:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM downloads WHERE status=?",
                (DownloadStatus.COMPLETED.value,),
            )
            self._conn.commit()
            return cur.rowcount

    def get_active_and_queued(self) -> tuple[int, int]:
        with self._lock:
            active = self._conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status=?",
                (DownloadStatus.DOWNLOADING.value,),
            ).fetchone()[0]
            queued = self._conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status IN (?, ?)",
                (DownloadStatus.QUEUED.value, DownloadStatus.SCHEDULED.value),
            ).fetchone()[0]
            return int(active), int(queued)

    # ── settings ───────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            cur = self._conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            )
            row = cur.fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )
            self._conn.commit()

    def get_settings(self) -> AppSettings:
        def _int(key: str, default: int) -> int:
            try:
                return int(self.get_setting(key, str(default)))
            except ValueError:
                return default

        close_default = "1" if default_close_to_tray() else "0"
        return AppSettings(
            default_segments=_int("default_segments", DEFAULT_SEGMENTS),
            max_concurrent=_int("max_concurrent", DEFAULT_MAX_CONCURRENT),
            global_speed_limit=_int("global_speed_limit", DEFAULT_GLOBAL_SPEED_LIMIT),
            base_download_folder=self.get_setting(
                "base_download_folder", str(get_default_download_base())
            ),
            category_software=self.get_setting("category_software", "Software"),
            category_docs=self.get_setting("category_docs", "Docs"),
            category_videos=self.get_setting("category_videos", "Videos"),
            category_other=self.get_setting("category_other", "Other"),
            start_with_windows=self.get_setting("start_with_windows", "0") == "1",
            close_to_tray=self.get_setting("close_to_tray", close_default) == "1",
            sound_on_complete=self.get_setting("sound_on_complete", "0") == "1",
        )

    def save_settings(self, s: AppSettings) -> None:
        mapping = {
            "default_segments": str(s.default_segments),
            "max_concurrent": str(s.max_concurrent),
            "global_speed_limit": str(s.global_speed_limit),
            "base_download_folder": s.base_download_folder,
            "category_software": s.category_software,
            "category_docs": s.category_docs,
            "category_videos": s.category_videos,
            "category_other": s.category_other,
            "start_with_windows": "1" if s.start_with_windows else "0",
            "close_to_tray": "1" if s.close_to_tray else "0",
            "sound_on_complete": "1" if s.sound_on_complete else "0",
        }
        for k, v in mapping.items():
            self.set_setting(k, v)
