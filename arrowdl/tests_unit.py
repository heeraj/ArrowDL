"""Small offline unit checks (no network). Run: python -m arrowdl.tests_unit"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from arrowdl.db import Database
from arrowdl.downloader import (
    SpeedLimiter,
    backoff_delay,
    is_transient_error,
    should_retry_status,
)
from arrowdl.engine import DownloadEngine
from arrowdl.models import DownloadItem, DownloadStatus
from arrowdl.ui.list_helpers import COL_SPECS, col_anchors, col_widths, sort_unfinished_first
from arrowdl.utils import (
    compute_segments,
    filename_from_url,
    format_eta_wallclock,
    format_size,
    guess_category,
    mbps_to_bps,
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


def test_mbps_to_bps() -> None:
    assert mbps_to_bps(0) == 0
    assert mbps_to_bps(-1) == 0
    assert mbps_to_bps(None) == 0
    assert mbps_to_bps(1) == 125_000  # 1e6/8
    assert mbps_to_bps(8) == 1_000_000
    assert mbps_to_bps(2.5) == int(2.5 * 1_000_000 / 8)


def test_format_eta_wallclock() -> None:
    assert format_eta_wallclock(None) == ""
    assert format_eta_wallclock(-1) == ""
    out = format_eta_wallclock(120)
    assert out.startswith("~")
    assert "M" in out or "A" in out or "P" in out  # AM/PM


def test_col_specs_consistency() -> None:
    assert len(COL_SPECS) == 7
    widths = col_widths()
    anchors = col_anchors()
    assert len(widths) == len(COL_SPECS)
    assert len(anchors) == len(COL_SPECS)
    keys = [c[0] for c in COL_SPECS]
    assert keys == ["name", "size", "progress", "speed", "eta", "status", "category"]
    by_key = {c[0]: c for c in COL_SPECS}
    assert by_key["size"][3] == "e"
    assert by_key["speed"][3] == "e"
    assert by_key["eta"][3] == "e"
    assert by_key["name"][3] == "w"
    assert by_key["status"][3] == "w"
    assert by_key["category"][3] == "w"
    assert len(set(keys)) == len(keys)
    assert all(w > 0 for w in widths)
    assert by_key["eta"][2] >= 72


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
    assert backoff_delay(10) == 8.0
    assert should_retry_status(503)
    assert should_retry_status(429)
    assert not should_retry_status(404)
    assert is_transient_error(TimeoutError("timed out"))
    assert is_transient_error(ConnectionError("reset"))
    assert not is_transient_error(ValueError("bad"))


def test_speed_limiter_no_deadlock() -> None:
    lim = SpeedLimiter()
    lim.set_global_limit(2048)
    lim.set_download_limit(1, 0)

    done = threading.Event()

    def worker() -> None:
        for _ in range(2):
            lim.throttle(1, 8192)
        done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=20)
    assert done.is_set(), "SpeedLimiter deadlocked on large chunk"
    lim.remove_download(1)


def test_resume_noop_on_completed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "t.db")
        engine = DownloadEngine(db)
        item = DownloadItem(
            url="https://example.com/f.bin",
            filename="f.bin",
            save_path=tmp,
            status=DownloadStatus.COMPLETED.value,
            downloaded=100,
            total_size=100,
        )
        iid = db.add_download(item)
        engine.resume(iid)
        after = db.get_download(iid)
        assert after is not None
        assert after.status == DownloadStatus.COMPLETED.value
        assert after.downloaded == 100
        engine.stop()
        db.close()


def test_restart_resets() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "t.db")
        engine = DownloadEngine(db)
        save = Path(tmp)
        fname = "g.bin"
        # Create fake final + part + meta
        (save / fname).write_bytes(b"hello")
        (save / f"{fname}.arrowdl.part").write_bytes(b"partial")
        (save / f"{fname}.arrowdl.meta").write_text("{}", encoding="utf-8")
        item = DownloadItem(
            url="https://example.com/g.bin",
            filename=fname,
            save_path=str(save),
            status=DownloadStatus.COMPLETED.value,
            downloaded=5,
            total_size=5,
            error_message="old",
            engine_retries=2,
        )
        iid = db.add_download(item)
        engine.restart(iid)
        after = db.get_download(iid)
        assert after is not None
        assert after.status == DownloadStatus.QUEUED.value
        assert after.downloaded == 0
        assert after.total_size == 0
        assert after.error_message == ""
        assert after.engine_retries == 0
        assert not (save / fname).exists()
        assert not (save / f"{fname}.arrowdl.part").exists()
        assert not (save / f"{fname}.arrowdl.meta").exists()
        engine.stop()
        db.close()


def main() -> None:
    test_sanitize()
    test_segments()
    test_category_and_format()
    test_mbps_to_bps()
    test_format_eta_wallclock()
    test_col_specs_consistency()
    test_sort_unfinished_first()
    test_retry_helpers()
    test_speed_limiter_no_deadlock()
    test_resume_noop_on_completed()
    test_restart_resets()
    print("OK: all offline unit checks passed")


if __name__ == "__main__":
    main()
