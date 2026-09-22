"""Utility helpers: sanitize, format, category guess, segment math."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import List, Tuple

from arrowdl.models import Category

SOFTWARE_EXTS = {".exe", ".msi", ".dmg", ".zip", ".7z", ".rar", ".deb", ".rpm", ".pkg", ".apk"}
DOCS_EXTS = {".pdf", ".doc", ".docx", ".txt", ".epub", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v"}

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """Remove illegal path characters and trim whitespace/dots."""
    if not name:
        return fallback
    # Strip URL query fragments if somehow present
    name = name.split("?")[0].split("#")[0]
    name = urllib.parse.unquote(name)
    name = _INVALID_CHARS.sub("_", name)
    name = name.strip(" .")
    if not name or name in (".", ".."):
        return fallback
    # Avoid Windows reserved names
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    stem = Path(name).stem.upper()
    if stem in reserved:
        name = f"_{name}"
    if len(name) > 200:
        p = Path(name)
        name = (p.stem[:180] + p.suffix) if p.suffix else name[:200]
    return name


def filename_from_url(url: str) -> str:
    """Extract a reasonable filename from a URL path."""
    try:
        parsed = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(parsed.path)
        name = Path(path).name
        return sanitize_filename(name) if name else "download"
    except Exception:
        return "download"


def filename_from_content_disposition(header: str | None) -> str | None:
    """Parse Content-Disposition for filename= or filename*=."""
    if not header:
        return None
    # filename*=UTF-8''encoded
    m = re.search(r"filename\*\s*=\s*([^']*)''([^;]+)", header, re.I)
    if m:
        return sanitize_filename(urllib.parse.unquote(m.group(2).strip().strip('"')))
    m = re.search(r'filename\s*=\s*"([^"]+)"', header, re.I)
    if m:
        return sanitize_filename(m.group(1))
    m = re.search(r"filename\s*=\s*([^;]+)", header, re.I)
    if m:
        return sanitize_filename(m.group(1).strip().strip('"'))
    return None


def guess_category(filename: str) -> str:
    """Guess category from file extension."""
    ext = Path(filename).suffix.lower()
    if ext in SOFTWARE_EXTS:
        return Category.SOFTWARE.value
    if ext in DOCS_EXTS:
        return Category.DOCS.value
    if ext in VIDEO_EXTS:
        return Category.VIDEOS.value
    return Category.OTHER.value


def format_size(num_bytes: int | float) -> str:
    """Human-readable byte size."""
    try:
        n = float(num_bytes)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    if i == 0:
        return f"{int(n)} {units[i]}"
    return f"{n:.1f} {units[i]}"


def format_speed(bps: float) -> str:
    if bps <= 0:
        return "—"
    return f"{format_size(bps)}/s"


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h {m}m"


def compute_segments(total_size: int, num_segments: int) -> List[Tuple[int, int]]:
    """
    Split [0, total_size) into num_segments inclusive ranges (start, end).
    end is inclusive for Range headers. Returns empty if total_size <= 0.
    """
    if total_size <= 0 or num_segments < 1:
        return []
    n = min(num_segments, total_size)
    base = total_size // n
    rem = total_size % n
    ranges: List[Tuple[int, int]] = []
    start = 0
    for i in range(n):
        length = base + (1 if i < rem else 0)
        end = start + length - 1
        ranges.append((start, end))
        start = end + 1
    return ranges


def part_path(save_path: str, filename: str) -> Path:
    return Path(save_path) / f"{filename}.arrowdl.part"


def meta_path(save_path: str, filename: str) -> Path:
    return Path(save_path) / f"{filename}.arrowdl.meta"
