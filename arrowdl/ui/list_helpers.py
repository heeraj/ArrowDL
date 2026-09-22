"""Shared download-list column specs and sort helpers (v1.2)."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from arrowdl.models import FINISHED_STATUSES, UNFINISHED_STATUSES, DownloadItem

# (key, header_label, width, anchor)
# Keep header and cells on the SAME width + anchor to avoid drift.
COL_SPECS: List[Tuple[str, str, int, str]] = [
    ("name", "Name", 240, "w"),
    ("size", "Size", 88, "e"),
    ("progress", "Progress", 120, "w"),  # bar+pct frame; fixed width
    ("speed", "Speed", 88, "e"),
    ("eta", "ETA", 96, "e"),
    ("status", "Status", 96, "w"),
    ("category", "Category", 80, "w"),
]

STATUS_SORT_ORDER = {
    "downloading": 0,
    "queued": 1,
    "paused": 2,
    "scheduled": 3,
    "failed": 4,
    "completed": 10,
    "cancelled": 11,
}


def col_widths() -> Tuple[int, ...]:
    return tuple(c[2] for c in COL_SPECS)


def col_anchors() -> Tuple[str, ...]:
    return tuple(c[3] for c in COL_SPECS)


def sort_unfinished_first(items: Sequence[DownloadItem]) -> List[DownloadItem]:
    """Unfinished (active/queued/paused/scheduled/failed) first, then completed/cancelled."""

    def key(it: DownloadItem):
        group = 0 if it.status in UNFINISHED_STATUSES else 1
        order = STATUS_SORT_ORDER.get(it.status, 5)
        return (group, order, -(it.id or 0))

    return sorted(items, key=key)


def split_completed_groups(
    items: Sequence[DownloadItem],
) -> Tuple[List[DownloadItem], List[DownloadItem]]:
    unfinished = [i for i in items if i.status in UNFINISHED_STATUSES]
    finished = [i for i in items if i.status in FINISHED_STATUSES]
    # Preserve relative order within groups via unfinished-first sort input
    unfinished = sort_unfinished_first(unfinished)
    finished = sorted(finished, key=lambda i: -(i.id or 0))
    return unfinished, finished
