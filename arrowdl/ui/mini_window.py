"""Always-on-top mini progress window for a single download."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, Optional

import customtkinter as ctk

from arrowdl.models import DownloadStatus
from arrowdl.ui import theme
from arrowdl.utils import format_eta, format_speed

if TYPE_CHECKING:
    from arrowdl.engine import DownloadEngine

# id -> MiniDownloadWindow
_OPEN: Dict[int, "MiniDownloadWindow"] = {}


def open_mini_window(parent, engine: "DownloadEngine", item_id: int) -> "MiniDownloadWindow":
    existing = _OPEN.get(item_id)
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            _OPEN.pop(item_id, None)
    win = MiniDownloadWindow(parent, engine, item_id)
    _OPEN[item_id] = win
    return win


class MiniDownloadWindow(ctk.CTkToplevel):
    def __init__(self, parent, engine: "DownloadEngine", item_id: int) -> None:
        super().__init__(parent)
        self.engine = engine
        self.item_id = item_id
        self.title("ArrowDL")
        self.geometry("360x120")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=theme.BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._close_only)

        self.name_lbl = ctk.CTkLabel(
            self, text="…", font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.name_lbl.pack(fill="x", padx=12, pady=(10, 2))

        bar_row = ctk.CTkFrame(self, fg_color="transparent")
        bar_row.pack(fill="x", padx=12, pady=2)
        self.bar = ctk.CTkProgressBar(
            bar_row, width=260, height=10, progress_color=theme.ACCENT, fg_color=theme.BG_CARD
        )
        self.bar.pack(side="left")
        self.bar.set(0)
        self.pct_lbl = ctk.CTkLabel(
            bar_row, text="0%", width=48, anchor="e", text_color=theme.TEXT_DIM, font=theme.font(11)
        )
        self.pct_lbl.pack(side="left", padx=(8, 0))

        self.meta_lbl = ctk.CTkLabel(
            self, text="", text_color=theme.TEXT_DIM, font=theme.font(11), anchor="w"
        )
        self.meta_lbl.pack(fill="x", padx=12, pady=2)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(4, 8))
        self.pause_btn = ctk.CTkButton(
            btn_row,
            text="⏸ Pause",
            width=90,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self._toggle_pause,
        )
        self.pause_btn.pack(side="left")
        ctk.CTkButton(
            btn_row,
            text="📂 Folder",
            width=90,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self._open_folder,
        ).pack(side="left", padx=(8, 0))

        self.after(200, self._tick)

    def _close_only(self) -> None:
        _OPEN.pop(self.item_id, None)
        self.destroy()

    def _toggle_pause(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        if item.status == DownloadStatus.DOWNLOADING.value:
            self.engine.pause(self.item_id)
        elif item.status in (
            DownloadStatus.PAUSED.value,
            DownloadStatus.FAILED.value,
            DownloadStatus.QUEUED.value,
        ):
            self.engine.resume(self.item_id)

    def _open_folder(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        path = Path(item.final_path)
        folder = path.parent if path.exists() else Path(item.save_path)
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif system == "Darwin":
                subprocess.run(["open", str(folder)], check=False)
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception:
            pass

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        item = self.engine.db.get_download(self.item_id)
        if not item:
            self._close_only()
            return
        name = item.filename or "…"
        if len(name) > 42:
            name = name[:39] + "…"
        self.name_lbl.configure(text=name)
        pct = item.progress / 100.0
        self.bar.set(max(0.0, min(1.0, pct)))
        self.pct_lbl.configure(text=f"{item.progress:.0f}%")

        runtime = self.engine.get_runtime(item.id) if item.id else {}
        speed = runtime.get("speed", 0.0) or 0.0
        eta = runtime.get("eta")
        if item.status != DownloadStatus.DOWNLOADING.value:
            speed = 0.0
            eta = None
        self.meta_lbl.configure(
            text=f"{format_speed(speed)}  ·  ETA {format_eta(eta)}  ·  {item.status}"
        )
        if item.status == DownloadStatus.DOWNLOADING.value:
            self.pause_btn.configure(text="⏸ Pause")
        else:
            self.pause_btn.configure(text="▶ Resume")

        self.after(400, self._tick)
