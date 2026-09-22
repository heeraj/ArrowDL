"""Paths and default configuration for ArrowDL."""

from __future__ import annotations

import platform
from pathlib import Path

APP_NAME = "ArrowDL"
APP_VERSION = "1.0.0"

DEFAULT_SEGMENTS = 4
DEFAULT_MAX_CONCURRENT = 3
DEFAULT_GLOBAL_SPEED_LIMIT = 0  # unlimited
MIN_SEGMENTS = 1
MAX_SEGMENTS = 16

CATEGORY_SUBDIRS = {
    "Software": "Software",
    "Docs": "Docs",
    "Videos": "Videos",
    "Other": "Other",
}


def get_app_data_dir() -> Path:
    """Platform-specific app data directory for DB and settings."""
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        base = home / "AppData" / "Local" / APP_NAME
    else:
        # Linux / macOS smoke path
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_default_download_base() -> Path:
    """Default base folder: ~/Downloads/ArrowDL."""
    base = Path.home() / "Downloads" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    for sub in CATEGORY_SUBDIRS.values():
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def get_db_path() -> Path:
    return get_app_data_dir() / "arrowdl.db"


def ensure_category_dirs(base: Path | str, subdirs: dict[str, str] | None = None) -> None:
    base_path = Path(base)
    base_path.mkdir(parents=True, exist_ok=True)
    mapping = subdirs or CATEGORY_SUBDIRS
    for sub in mapping.values():
        (base_path / sub).mkdir(parents=True, exist_ok=True)
