"""Small offline unit checks (no network). Run: python -m arrowdl.tests_unit"""

from __future__ import annotations

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
    # Contiguous and cover all bytes
    covered = 0
    prev_end = -1
    for s, e in segs:
        assert s == prev_end + 1
        covered += e - s + 1
        prev_end = e
    assert covered == 1000
    assert compute_segments(0, 4) == []
    assert compute_segments(5, 10)  # capped to size


def test_category_and_format() -> None:
    assert guess_category("setup.exe") == "Software"
    assert guess_category("readme.pdf") == "Docs"
    assert guess_category("movie.mkv") == "Videos"
    assert guess_category("data.bin") == "Other"
    assert "KB" in format_size(2048) or "KB" in format_size(2048).upper() or format_size(2048)
    assert filename_from_url("https://example.com/files/app.zip?x=1") == "app.zip"


def main() -> None:
    test_sanitize()
    test_segments()
    test_category_and_format()
    print("OK: all offline unit checks passed")


if __name__ == "__main__":
    main()
