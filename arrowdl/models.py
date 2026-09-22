"""Data models and enums for ArrowDL."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


class Category(str, Enum):
    SOFTWARE = "Software"
    DOCS = "Docs"
    VIDEOS = "Videos"
    OTHER = "Other"


# Unfinished statuses shown above completed group when filter is All
UNFINISHED_STATUSES = (
    DownloadStatus.DOWNLOADING.value,
    DownloadStatus.QUEUED.value,
    DownloadStatus.PAUSED.value,
    DownloadStatus.SCHEDULED.value,
    DownloadStatus.FAILED.value,
)

FINISHED_STATUSES = (
    DownloadStatus.COMPLETED.value,
    DownloadStatus.CANCELLED.value,
)


@dataclass
class DownloadItem:
    id: Optional[int] = None
    url: str = ""
    filename: str = ""
    save_path: str = ""
    category: str = Category.OTHER.value
    status: str = DownloadStatus.QUEUED.value
    total_size: int = 0
    downloaded: int = 0
    segments: int = 4
    speed_limit: int = 0  # 0 = unlimited (bytes/sec)
    start_at: Optional[str] = None  # ISO datetime string or None
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""
    engine_retries: int = 0
    # Runtime-only fields
    speed: float = 0.0
    eta_seconds: Optional[float] = None

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(100.0, (self.downloaded / self.total_size) * 100.0)

    @property
    def final_path(self) -> str:
        return str(Path(self.save_path) / self.filename)


def default_close_to_tray() -> bool:
    """Default True on Windows; True elsewhere when tray is available."""
    return True


@dataclass
class AppSettings:
    default_segments: int = 4
    max_concurrent: int = 3
    global_speed_limit: int = 0  # 0 = unlimited
    base_download_folder: str = ""
    category_software: str = "Software"
    category_docs: str = "Docs"
    category_videos: str = "Videos"
    category_other: str = "Other"
    start_with_windows: bool = False
    close_to_tray: bool = True
