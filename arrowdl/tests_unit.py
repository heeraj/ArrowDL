"""Small offline unit checks (no network). Run: python -m arrowdl.tests_unit"""

from __future__ import annotations

import threading
import time

from arrowdl.downloader import (
    SpeedLimiter,
    backoff_delay,
    is_transient_error,
    should_retry_status,
)
from arrowdl.models import DownloadItem, DownloadStatus
from arrowdl.ui.list_helpers import COL_SPECS, col_anchors, col_widths, sort_unfinished_first
from arrowdl.utils import (
    compute_segments,
    filename_from_url,
    format_size,
    guess_category,
    sanitize_filename,
)


def test_sanitize() -> None:
    assert sanitize_filename("hello world.txt") == "hello world.txt"
    assert "/" not in sanitize_filename("a/b\\c:d*.txt")
    assert sanitize_filename("") == "download"
    assert sanitize_filename("CON.txt").startswith("_")


def test_segments() -> None:
    segs = compute_segments(1000, 4)
    assert len(segs) == 4
    assert segs[0][0] == 0
    assert segs[-1][1] == 999
    covered = 0
    prev_end = -1
    for s, e in segs:
        assert s == prev_end + 1
        covered += e - s + 1
        prev_end = e
    assert covered == 1000
    assert compute_segments(0, 4) == []
    assert compute_segments(5, 10)


def test_category_and_format() -> None:
    assert guess_category("setup.exe") == "Software"
    assert guess_category("readme.pdf") == "Docs"
    assert guess_category("movie.mkv") == "Videos"
    assert guess_category("data.bin") == "Other"
    assert format_size(2048)
    assert filename_from_url("https://example.com/files/app.zip?x=1") == "app.zip"


def test_col_specs_consistency() -> None:
    assert len(COL_SPECS) == 7
    widths = col_widths()
    anchors = col_anchors()
    assert len(widths) == len(COL_SPECS)
    assert len(anchors) == len(COL_SPECS)
    keys = [c[0] for c in COL_SPECS]
    assert keys == ["name", "size", "progress", "speed", "eta", "status", "category"]
    # Size/Speed/ETA right-aligned; Name/Status/Category left
    by_key = {c[0]: c for c in COL_SPECS}
    assert by_key["size"][3] == "e"
    assert by_key["speed"][3] == "e"
    assert by_key["eta"][3] == "e"
    assert by_key["name"][3] == "w"
    assert by_key["status"][3] == "w"
    assert by_key["category"][3] == "w"
    # Unique keys, positive widths
    assert len(set(keys)) == len(keys)
    assert all(w > 0 for w in widths)


def test_sort_unfinished_first() -> None:
    items = [
        DownloadItem(id=1, status=DownloadStatus.COMPLETED.value, filename="a"),
        DownloadItem(id=2, status=DownloadStatus.DOWNLOADING.value, filename="b"),
        DownloadItem(id=3, status=DownloadStatus.QUEUED.value, filename="c"),
        DownloadItem(id=4, status=DownloadStatus.CANCELLED.value, filename="d"),
        DownloadItem(id=5, status=DownloadStatus.FAILED.value, filename="e"),
        DownloadItem(id=6, status=DownloadStatus.PAUSED.value, filename="f"),
    ]
    sorted_items = sort_unfinished_first(items)
    statuses = [i.status for i in sorted_items]
    # All unfinished before finished
    finished_idx = next(
        i for i, s in enumerate(statuses) if s in ("completed", "cancelled")
    )
    assert all(s not in ("completed", "cancelled") for s in statuses[:finished_idx])
    assert statuses[0] == DownloadStatus.DOWNLOADING.value
    assert DownloadStatus.COMPLETED.value in statuses[finished_idx:]


def test_retry_helpers() -> None:
    assert backoff_delay(0) == 0.5
    assert backoff_delay(1) == 1.0
    assert backoff_delay(2) == 2.0
    assert backoff_delay(3) == 4.0
    assert backoff_delay(10) == 8.0  # capped
    assert should_retry_status(503)
    assert should_retry_status(429)
    assert not should_retry_status(404)
    assert is_transient_error(TimeoutError("timed out"))
    assert is_transient_error(ConnectionError("reset"))
    assert not is_transient_error(ValueError("bad"))


def test_speed_limiter_no_deadlock() -> None:
    """Limit smaller than chunk must not deadlock (capacity >= one chunk)."""
    lim = SpeedLimiter()
    lim.set_global_limit(2048)  # 2 KB/s — below chunk size
    lim.set_download_limit(1, 0)  # unlimited per-download

    done = threading.Event()

    def worker() -> None:
        # Chunks larger than limit — must still complete without hang
        for _ in range(2):
            lim.throttle(1, 8192)
        done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=20)
    assert done.is_set(), "SpeedLimiter deadlocked on large chunk"
    lim.remove_download(1)


def main() -> None:
    test_sanitize()
    test_segments()
    test_category_and_format()
    test_col_specs_consistency()
    test_sort_unfinished_first()
    test_retry_helpers()
    test_speed_limiter_no_deadlock()
    print("OK: all offline unit checks passed")


if __name__ == "__main__":
    main()
