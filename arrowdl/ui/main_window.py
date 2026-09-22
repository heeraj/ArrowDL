"""Main application window — compact multi-select UI (v1.2)."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Dict, List, Optional, Set

import customtkinter as ctk

from arrowdl.engine import DownloadEngine
from arrowdl.models import Category, DownloadItem, DownloadStatus
from arrowdl.ui import theme
from arrowdl.ui.add_dialog import AddDownloadDialog
from arrowdl.ui.delete_dialog import DeleteDialog
from arrowdl.ui.list_helpers import COL_SPECS, sort_unfinished_first, split_completed_groups
from arrowdl.ui.mini_window import open_mini_window
from arrowdl.ui.settings_dialog import SettingsDialog
from arrowdl.ui.tray import TRAY_AVAILABLE, TrayController
from arrowdl.utils import format_eta, format_eta_wallclock, format_size, format_speed

_URL_RE = re.compile(r"^https?://\S+$", re.I)

# Slightly taller ETA for wall-clock; keep shared COL_SPECS widths but override ETA display
_ETA_COL_WIDTH = 96


FILTERS = [
    ("All", None, None),
    ("Downloading", DownloadStatus.DOWNLOADING.value, None),
    ("Queued", DownloadStatus.QUEUED.value, None),
    ("Completed", DownloadStatus.COMPLETED.value, None),
    ("Scheduled", DownloadStatus.SCHEDULED.value, None),
    ("Paused", DownloadStatus.PAUSED.value, None),
    ("Failed", DownloadStatus.FAILED.value, None),
    ("— Categories —", "__sep__", None),
    ("Software", None, Category.SOFTWARE.value),
    ("Docs", None, Category.DOCS.value),
    ("Videos", None, Category.VIDEOS.value),
    ("Other", None, Category.OTHER.value),
]

_RESUMABLE = (
    DownloadStatus.PAUSED.value,
    DownloadStatus.FAILED.value,
    DownloadStatus.CANCELLED.value,
    DownloadStatus.QUEUED.value,
)


class MainWindow(ctk.CTk):
    def __init__(self, engine: DownloadEngine) -> None:
        super().__init__()
        theme.apply_theme()
        self.engine = engine
        self.db = engine.db
        self.title("ArrowDL")
        self.geometry(theme.DEFAULT_GEOMETRY)
        self.minsize(*theme.MIN_SIZE)
        self.configure(fg_color=theme.BG_DARK)

        self._filter_status: Optional[str] = None
        self._filter_category: Optional[str] = None
        self._selected_ids: Set[int] = set()
        self._anchor_id: Optional[int] = None
        self._row_ids: List[int] = []
        self._row_widgets: Dict[int, dict] = {}
        self._last_id_order: List[int] = []
        self._quitting = False
        self._tray: Optional[TrayController] = None

        # Drag multi-select
        self._drag_active = False
        self._drag_anchor: Optional[int] = None
        self._drag_ctrl = False
        self._drag_base: Set[int] = set()

        # Finish flash / status tracking
        self._prev_status: Dict[int, str] = {}
        self._flash_until: Dict[int, float] = {}

        # Clipboard watch
        self._clip_last = ""
        self._clip_toast: Optional[ctk.CTkFrame] = None
        self._clip_pending_url = ""

        self._build()
        self._init_tray()
        self._bind_shortcuts()
        self.after(200, self._refresh)
        self.after(1500, self._poll_clipboard)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── build ──────────────────────────────────────────────────

    def _build(self) -> None:
        toolbar = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, height=theme.TOOLBAR_HEIGHT, corner_radius=0
        )
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        def tbtn(text: str, cmd, accent: bool = False, width: int = 88) -> ctk.CTkButton:
            b = ctk.CTkButton(
                toolbar,
                text=text,
                width=width,
                height=28,
                fg_color=theme.ACCENT if accent else theme.BG_HOVER,
                hover_color=theme.ACCENT_HOVER if accent else theme.BG_CARD,
                text_color="#00332e" if accent else theme.TEXT,
                font=theme.font(11),
                command=cmd,
            )
            b.pack(side="left", padx=(6, 0), pady=6)
            return b

        tbtn("Add URL", self._add_download, accent=True, width=80)
        tbtn("Clear Done", self._clear_completed, width=84)
        tbtn("Pause All", self.engine.pause_all, width=78)
        tbtn("Resume All", self.engine.resume_all, width=86)
        tbtn("⚙ Settings", self._open_settings, width=100)

        ctk.CTkLabel(
            toolbar,
            text="ArrowDL",
            font=theme.font(theme.FONT_SIZE_TITLE, "bold"),
            text_color=theme.ACCENT,
        ).pack(side="right", padx=12)

        # Selection action bar
        self.sel_bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, height=34, corner_radius=0)
        self.sel_bar.pack(fill="x", side="top")
        self.sel_bar.pack_propagate(False)
        self.sel_count_lbl = ctk.CTkLabel(
            self.sel_bar, text="0 selected", text_color=theme.TEXT_DIM, font=theme.font(11)
        )
        self.sel_count_lbl.pack(side="left", padx=10)

        def sbtn(text: str, cmd, width: int = 70) -> ctk.CTkButton:
            b = ctk.CTkButton(
                self.sel_bar,
                text=text,
                width=width,
                height=26,
                fg_color=theme.BG_HOVER,
                hover_color=theme.BG_CARD,
                font=theme.font(11),
                command=cmd,
            )
            b.pack(side="left", padx=3, pady=4)
            return b

        self._sel_start_btn = sbtn("▶ Start", self._sel_resume)
        self._sel_restart_btn = sbtn("↻ Restart", self._sel_restart, width=80)
        sbtn("⏸ Pause", self._sel_pause)
        sbtn("⏹ Stop", self._sel_cancel)
        sbtn("🗑 Delete", self._sel_delete)
        self._hide_sel_bar()

        body = ctk.CTkFrame(self, fg_color=theme.BG_DARK, corner_radius=0)
        body.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(
            body, fg_color=theme.BG_SIDEBAR, width=theme.SIDEBAR_WIDTH, corner_radius=0
        )
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar, text="Filters", font=theme.font(11, "bold"), text_color=theme.TEXT_DIM
        ).pack(anchor="w", padx=10, pady=(8, 2))

        self._filter_btns: list[ctk.CTkButton] = []
        for label, status, category in FILTERS:
            if status == "__sep__":
                ctk.CTkLabel(
                    sidebar, text=label, text_color=theme.TEXT_DIM, font=theme.font(9)
                ).pack(anchor="w", padx=10, pady=(8, 1))
                continue
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=theme.BG_HOVER,
                text_color=theme.TEXT,
                height=24,
                font=theme.font(11),
                command=lambda s=status, c=category, l=label: self._set_filter(s, c, l),
            )
            btn.pack(fill="x", padx=6, pady=0)
            self._filter_btns.append(btn)

        table_frame = ctk.CTkFrame(body, fg_color=theme.BG_DARK, corner_radius=0)
        table_frame.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        header = ctk.CTkFrame(
            table_frame, fg_color=theme.BG_CARD, height=theme.HEADER_HEIGHT, corner_radius=4
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        for key, label, width, anchor in COL_SPECS:
            w = _ETA_COL_WIDTH if key == "eta" else width
            ctk.CTkLabel(
                header,
                text=label,
                width=w,
                anchor=anchor,
                font=theme.font(10, "bold"),
                text_color=theme.TEXT_DIM,
            ).pack(side="left", padx=2)

        self.list_frame = ctk.CTkScrollableFrame(
            table_frame, fg_color=theme.BG_DARK, corner_radius=0
        )
        self.list_frame.pack(fill="both", expand=True, pady=(2, 0))

        self._menu = tk.Menu(self, tearoff=0, bg=theme.BG_CARD, fg=theme.TEXT)
        self._menu.add_command(label="Open file", command=self._open_file)
        self._menu.add_command(label="Open folder", command=self._open_folder)
        self._menu.add_command(label="Open mini window", command=self._open_mini)
        self._menu.add_command(label="Copy URL", command=self._copy_url)
        self._menu.add_separator()
        self._menu.add_command(label="Pause", command=self._ctx_pause)
        self._menu.add_command(label="Resume", command=self._ctx_resume)
        self._menu.add_command(label="Restart (re-download)", command=self._ctx_restart)
        self._menu.add_command(label="Cancel", command=self._ctx_cancel)
        self._menu.add_separator()
        self._menu.add_command(label="Delete", command=self._ctx_delete)

        self.statusbar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, height=24, corner_radius=0)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            self.statusbar, text="", text_color=theme.TEXT_DIM, font=theme.font(10), anchor="w"
        )
        self.status_label.pack(side="left", padx=10)
        self.seg_status_lbl = ctk.CTkLabel(
            self.statusbar, text="", text_color=theme.TEXT_DIM, font=theme.font(10), anchor="e"
        )
        self.seg_status_lbl.pack(side="right", padx=10)

    def _bind_shortcuts(self) -> None:
        self.bind("<space>", self._shortcut_pause_resume)
        self.bind("<Delete>", lambda e: self._sel_delete())
        self.bind("<Control-a>", self._shortcut_select_unfinished)
        self.bind("<Control-A>", self._shortcut_select_unfinished)
        self.bind("<Control-r>", self._shortcut_restart)
        self.bind("<Control-R>", self._shortcut_restart)
        self.bind("<Return>", self._shortcut_open_mini)
        # Focus root so keys work
        self.focus_set()

    def _hide_sel_bar(self) -> None:
        self.sel_bar.pack_forget()

    def _show_sel_bar(self) -> None:
        if not self.sel_bar.winfo_ismapped():
            self.sel_bar.pack(fill="x", side="top", after=self.winfo_children()[0])

    def _update_sel_bar(self) -> None:
        n = len(self._selected_ids)
        if n == 0:
            self._hide_sel_bar()
            return
        self.sel_count_lbl.configure(text=f"{n} selected")
        self._show_sel_bar()

    # ── tray ───────────────────────────────────────────────────

    def _init_tray(self) -> None:
        if not TRAY_AVAILABLE:
            return
        self._tray = TrayController(
            on_show=self._tray_show,
            on_pause_all=self.engine.pause_all,
            on_resume_all=self.engine.resume_all,
            on_exit=self._quit_app,
        )
        try:
            self._tray.start()
        except Exception:
            self._tray = None

    def _tray_show(self) -> None:
        def _do() -> None:
            self.deiconify()
            self.lift()
            self.focus_force()

        self.after(0, _do)

    # ── filters / add / settings ───────────────────────────────

    def _set_filter(self, status: Optional[str], category: Optional[str], label: str) -> None:
        self._filter_status = status
        self._filter_category = category
        self._refresh_rows(force=True)

    def _add_download(self, prefill_url: str = "") -> None:
        s = self.db.get_settings()
        dlg = AddDownloadDialog(
            self,
            default_segments=s.default_segments,
            base_folder=s.base_download_folder,
            category_subdirs={
                "Software": s.category_software,
                "Docs": s.category_docs,
                "Videos": s.category_videos,
                "Other": s.category_other,
            },
            on_submit=self._on_add,
        )
        if prefill_url:
            try:
                if hasattr(dlg, "url_var"):
                    dlg.url_var.set(prefill_url)
                elif hasattr(dlg, "url_entry"):
                    dlg.url_entry.delete(0, "end")
                    dlg.url_entry.insert(0, prefill_url)
            except Exception:
                pass

    def _on_add(self, item: DownloadItem) -> None:
        self.engine.add_download(item)
        self._refresh_rows(force=True)

    def _open_settings(self) -> None:
        SettingsDialog(self, self.db.get_settings(), on_save=self._on_settings_saved)

    def _on_settings_saved(self, settings) -> None:
        self.db.save_settings(settings)
        self.engine.reload_settings()
        self._update_status_bar()

    def _clear_completed(self) -> None:
        n = self.db.clear_completed()
        self._selected_ids = {
            i for i in self._selected_ids
            if (it := self.db.get_download(i)) is not None
            and it.status != DownloadStatus.COMPLETED.value
        }
        self._refresh_rows(force=True)
        if n:
            messagebox.showinfo("Clear completed", f"Removed {n} completed item(s) from the list.")

    # ── clipboard toast ────────────────────────────────────────

    def _poll_clipboard(self) -> None:
        if self._quitting or not self.winfo_exists():
            return
        try:
            # Only when focused / mapped (tray-alive still polls lightly)
            raw = ""
            try:
                raw = self.clipboard_get().strip()
            except Exception:
                raw = ""
            if raw and raw != self._clip_last and _URL_RE.match(raw):
                # Skip if already in list
                existing = {d.url for d in self.db.list_downloads()}
                if raw not in existing:
                    self._clip_pending_url = raw
                    self._show_clip_toast(raw)
            if raw:
                self._clip_last = raw
        except Exception:
            pass
        if self.winfo_exists() and not self._quitting:
            self.after(1800, self._poll_clipboard)

    def _show_clip_toast(self, url: str) -> None:
        if self._clip_toast is not None:
            try:
                self._clip_toast.destroy()
            except Exception:
                pass
        toast = ctk.CTkFrame(self, fg_color=theme.BG_HOVER, corner_radius=8, border_width=1,
                             border_color=theme.ACCENT)
        short = url if len(url) <= 48 else url[:45] + "…"
        ctk.CTkLabel(
            toast, text=f"Add URL?  {short}", text_color=theme.TEXT, font=theme.font(11)
        ).pack(side="left", padx=(10, 6), pady=6)
        ctk.CTkButton(
            toast, text="Add", width=50, height=24, fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER, text_color="#00332e",
            command=lambda: self._accept_clip_url(),
        ).pack(side="left", padx=2, pady=4)
        ctk.CTkButton(
            toast, text="✕", width=28, height=24, fg_color=theme.BG_CARD,
            hover_color=theme.BG_DARK, command=lambda: self._dismiss_clip_toast(),
        ).pack(side="left", padx=(2, 8), pady=4)
        toast.place(relx=0.5, rely=0.92, anchor="s")
        self._clip_toast = toast
        self.after(8000, self._dismiss_clip_toast)

    def _accept_clip_url(self) -> None:
        url = self._clip_pending_url
        self._dismiss_clip_toast()
        if url:
            self._add_download(prefill_url=url)

    def _dismiss_clip_toast(self) -> None:
        if self._clip_toast is not None:
            try:
                self._clip_toast.destroy()
            except Exception:
                pass
            self._clip_toast = None

    # ── refresh ────────────────────────────────────────────────

    def _refresh(self) -> None:
        try:
            self._refresh_rows(force=False)
            self._update_status_bar()
            self._check_finish_events()
        except Exception:
            pass
        if self.winfo_exists() and not self._quitting:
            self.after(500, self._refresh)

    def _check_finish_events(self) -> None:
        """Detect newly completed items → finish flash + optional sound."""
        now = time.monotonic()
        for item in self.db.list_downloads():
            if item.id is None:
                continue
            prev = self._prev_status.get(item.id)
            if (
                prev is not None
                and prev != DownloadStatus.COMPLETED.value
                and item.status == DownloadStatus.COMPLETED.value
            ):
                self._flash_until[item.id] = now + 1.2
                self._play_complete_sound()
                self._style_row(item.id, item.status)
            self._prev_status[item.id] = item.status
        # Clear expired flashes
        expired = [i for i, t in self._flash_until.items() if t <= now]
        for i in expired:
            self._flash_until.pop(i, None)
            it = self.db.get_download(i)
            if it:
                self._style_row(i, it.status)

    def _play_complete_sound(self) -> None:
        try:
            if not self.db.get_settings().sound_on_complete:
                return
            if platform.system() != "Windows":
                return
            import winsound  # type: ignore

            winsound.MessageBeep(winsound.MB_OK)
        except Exception:
            pass

    def _ordered_items(self) -> List[DownloadItem]:
        items = self.db.list_downloads(
            status=self._filter_status, category=self._filter_category
        )
        if self._filter_status is None:
            unfinished, finished = split_completed_groups(items)
            known = {i.id for i in unfinished + finished}
            extras = [i for i in items if i.id not in known]
            return unfinished + extras + finished
        return items

    def _refresh_rows(self, force: bool = False) -> None:
        items = self._ordered_items()
        id_order = [i.id for i in items if i.id is not None]

        need_rebuild = force or id_order != self._last_id_order or set(id_order) != set(
            self._row_widgets.keys()
        )

        if need_rebuild:
            for w in self.list_frame.winfo_children():
                w.destroy()
            self._row_widgets.clear()
            self._row_ids = []
            self._last_id_order = list(id_order)

            show_sep = self._filter_status is None
            seen_finished = False
            for item in items:
                if item.id is None:
                    continue
                if show_sep and item.status in (
                    DownloadStatus.COMPLETED.value,
                    DownloadStatus.CANCELLED.value,
                ):
                    if not seen_finished:
                        seen_finished = True
                        sep = ctk.CTkLabel(
                            self.list_frame,
                            text="—— Completed ——",
                            text_color=theme.TEXT_DIM,
                            font=theme.font(9),
                            anchor="w",
                        )
                        sep.pack(fill="x", pady=(6, 2), padx=4)
                self._row_ids.append(item.id)
                self._make_row(item)
            self._apply_selection_styles()
            self._update_sel_bar()
            return

        for item in items:
            if item.id is None or item.id not in self._row_widgets:
                continue
            self._update_row(item)

    def _make_row(self, item: DownloadItem) -> None:
        runtime = self.engine.get_runtime(item.id) if item.id else {}
        speed = runtime.get("speed", 0.0) or 0.0
        eta = runtime.get("eta")
        if item.status != DownloadStatus.DOWNLOADING.value:
            speed = 0.0
            eta = None

        row_h = theme.ROW_HEIGHT + 6  # room for segment strip
        row = ctk.CTkFrame(
            self.list_frame, fg_color=theme.BG_CARD, height=row_h, corner_radius=3
        )
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        refs: dict = {"row": row, "labels": {}, "bar": None, "pct": None, "seg_pills": []}

        for key, _label, width, anchor in COL_SPECS:
            w = _ETA_COL_WIDTH if key == "eta" else width
            if key == "progress":
                frame = ctk.CTkFrame(row, fg_color="transparent", width=w, height=row_h)
                frame.pack(side="left", padx=2)
                frame.pack_propagate(False)
                bar = ctk.CTkProgressBar(
                    frame, width=max(40, w - 42), height=7,
                    progress_color=theme.ACCENT, fg_color=theme.BG_HOVER,
                )
                bar.place(x=0, y=6)
                bar.set(max(0.0, min(1.0, item.progress / 100.0)))
                pct = ctk.CTkLabel(
                    frame, text=f"{item.progress:.0f}%", width=40, anchor="e",
                    text_color=theme.TEXT_DIM, font=theme.font(10),
                )
                pct.place(x=w - 42, y=2)
                # Tiny segment strip under bar
                strip = ctk.CTkFrame(frame, fg_color="transparent", height=8)
                strip.place(x=0, y=18)
                refs["bar"] = bar
                refs["pct"] = pct
                refs["seg_strip"] = strip
                refs["seg_pills"] = []
                self._rebuild_seg_strip(refs, item, runtime)
                for ww in (frame, bar, pct, strip):
                    self._bind_row_events(ww, item.id)
            else:
                text = self._cell_text(key, item, speed, eta)
                lbl = ctk.CTkLabel(
                    row, text=text, width=w, anchor=anchor,
                    text_color=theme.TEXT, font=theme.font(11),
                )
                lbl.pack(side="left", padx=2)
                refs["labels"][key] = lbl
                self._bind_row_events(lbl, item.id)

        self._bind_row_events(row, item.id)
        self._row_widgets[item.id] = refs
        self._style_row(item.id, item.status)

    def _rebuild_seg_strip(self, refs: dict, item: DownloadItem, runtime: dict) -> None:
        strip = refs.get("seg_strip")
        if strip is None:
            return
        for p in refs.get("seg_pills") or []:
            try:
                p.destroy()
            except Exception:
                pass
        pills = []
        total = int(runtime.get("segments") or item.segments or 0)
        active = int(runtime.get("active_segments") or 0)
        if item.status != DownloadStatus.DOWNLOADING.value or total <= 0:
            refs["seg_pills"] = []
            return
        done = max(0, total - max(0, active))
        for i in range(min(total, 16)):
            if i < done:
                color = theme.SUCCESS
            elif i < done + active:
                color = theme.ACCENT
            else:
                color = theme.BG_HOVER
            pill = ctk.CTkFrame(strip, width=8, height=5, corner_radius=1, fg_color=color)
            pill.pack(side="left", padx=1)
            pill.pack_propagate(False)
            pills.append(pill)
            self._bind_row_events(pill, item.id)
        refs["seg_pills"] = pills

    def _cell_text(self, key: str, item: DownloadItem, speed: float, eta) -> str:
        if key == "name":
            name = item.filename or "—"
            return name if len(name) <= 36 else name[:33] + "…"
        if key == "size":
            return format_size(item.total_size) if item.total_size else "—"
        if key == "speed":
            return format_speed(speed)
        if key == "eta":
            base = format_eta(eta)
            wall = format_eta_wallclock(eta)
            if wall and item.status == DownloadStatus.DOWNLOADING.value:
                return f"{base} {wall}"
            return base
        if key == "status":
            return item.status.capitalize()
        if key == "category":
            return item.category
        return ""

    def _update_row(self, item: DownloadItem) -> None:
        refs = self._row_widgets.get(item.id)
        if not refs:
            return
        runtime = self.engine.get_runtime(item.id) if item.id else {}
        speed = runtime.get("speed", 0.0) or 0.0
        eta = runtime.get("eta")
        if item.status != DownloadStatus.DOWNLOADING.value:
            speed = 0.0
            eta = None
        for key, lbl in refs["labels"].items():
            lbl.configure(text=self._cell_text(key, item, speed, eta))
        if refs["bar"] is not None:
            refs["bar"].set(max(0.0, min(1.0, item.progress / 100.0)))
            if item.status == DownloadStatus.COMPLETED.value:
                refs["bar"].configure(progress_color=theme.SUCCESS)
            elif item.id in self._flash_until:
                refs["bar"].configure(progress_color=theme.ACCENT_HOVER)
            else:
                refs["bar"].configure(progress_color=theme.ACCENT)
        if refs["pct"] is not None:
            refs["pct"].configure(text=f"{item.progress:.0f}%")
        self._rebuild_seg_strip(refs, item, runtime)
        self._style_row(item.id, item.status)

    def _style_row(self, item_id: int, status: str) -> None:
        refs = self._row_widgets.get(item_id)
        if not refs:
            return
        row = refs["row"]
        now = time.monotonic()
        flashing = item_id in self._flash_until and self._flash_until[item_id] > now
        if flashing:
            row.configure(fg_color="#1a4a40", border_width=2, border_color=theme.ACCENT_HOVER)
        elif item_id in self._selected_ids:
            row.configure(fg_color=theme.BG_SELECTED, border_width=1, border_color=theme.ACCENT)
        elif status == DownloadStatus.DOWNLOADING.value:
            row.configure(fg_color=theme.BG_HOVER, border_width=0)
        elif status == DownloadStatus.FAILED.value:
            row.configure(fg_color="#2a1a1a", border_width=0)
        else:
            row.configure(fg_color=theme.BG_CARD, border_width=0)

    def _apply_selection_styles(self) -> None:
        for iid in self._row_widgets:
            item = self.db.get_download(iid)
            st = item.status if item else ""
            self._style_row(iid, st)

    def _bind_row_events(self, widget, item_id: int) -> None:
        widget.bind("<ButtonPress-1>", lambda e, i=item_id: self._on_press(e, i))
        widget.bind("<B1-Motion>", lambda e, i=item_id: self._on_drag(e, i))
        widget.bind("<ButtonRelease-1>", lambda e, i=item_id: self._on_release(e, i))
        widget.bind("<Button-3>", lambda e, i=item_id: self._popup(e, i))
        widget.bind("<Double-Button-1>", lambda e, i=item_id: self._on_double(i))
        widget.bind("<Control-Button-1>", lambda e, i=item_id: self._on_press(e, i))

    # ── selection (click + drag paint/range) ───────────────────

    def _mods(self, event) -> tuple[bool, bool]:
        ctrl = bool(event.state & 0x0004) or bool(event.state & 0x0008)
        shift = bool(event.state & 0x0001)
        return ctrl, shift

    def _on_press(self, event, item_id: int) -> None:
        ctrl, shift = self._mods(event)
        self._drag_active = True
        self._drag_ctrl = ctrl
        self._drag_anchor = item_id
        self._drag_base = set(self._selected_ids) if ctrl else set()

        if shift and self._anchor_id is not None and self._anchor_id in self._row_ids:
            try:
                a = self._row_ids.index(self._anchor_id)
                b = self._row_ids.index(item_id)
            except ValueError:
                self._selected_ids = {item_id}
                self._anchor_id = item_id
            else:
                lo, hi = min(a, b), max(a, b)
                self._selected_ids = set(self._row_ids[lo : hi + 1])
        elif ctrl:
            if item_id in self._selected_ids:
                self._selected_ids.discard(item_id)
            else:
                self._selected_ids.add(item_id)
            self._anchor_id = item_id
            self._drag_base = set(self._selected_ids)
        else:
            self._selected_ids = {item_id}
            self._anchor_id = item_id

        self._apply_selection_styles()
        self._update_sel_bar()

    def _row_id_at_y(self, root_y: int) -> Optional[int]:
        for iid in self._row_ids:
            refs = self._row_widgets.get(iid)
            if not refs:
                continue
            row = refs["row"]
            try:
                y = row.winfo_rooty()
                h = row.winfo_height()
                if y <= root_y <= y + h:
                    return iid
            except Exception:
                continue
        return None

    def _on_drag(self, event, item_id: int) -> None:
        if not self._drag_active:
            return
        cur = self._row_id_at_y(event.y_root)
        if cur is None:
            cur = item_id
        anchor = self._drag_anchor or self._anchor_id
        if anchor is None or anchor not in self._row_ids or cur not in self._row_ids:
            return
        try:
            a = self._row_ids.index(anchor)
            b = self._row_ids.index(cur)
        except ValueError:
            return
        lo, hi = min(a, b), max(a, b)
        ranged = set(self._row_ids[lo : hi + 1])
        if self._drag_ctrl:
            self._selected_ids = self._drag_base | ranged
        else:
            self._selected_ids = ranged
        self._apply_selection_styles()
        self._update_sel_bar()

    def _on_release(self, event, item_id: int) -> None:
        self._drag_active = False
        if self._drag_anchor is not None:
            self._anchor_id = self._drag_anchor

    def _popup(self, event, item_id: int) -> None:
        if item_id not in self._selected_ids:
            self._selected_ids = {item_id}
            self._anchor_id = item_id
            self._apply_selection_styles()
            self._update_sel_bar()
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _primary_selected(self) -> Optional[int]:
        if self._anchor_id in self._selected_ids:
            return self._anchor_id
        return next(iter(self._selected_ids), None)

    def _selected_item(self) -> Optional[DownloadItem]:
        iid = self._primary_selected()
        if iid is None:
            return None
        return self.db.get_download(iid)

    def _on_double(self, item_id: int) -> None:
        item = self.db.get_download(item_id)
        if not item:
            return
        if item.status in (
            DownloadStatus.DOWNLOADING.value,
            DownloadStatus.PAUSED.value,
            DownloadStatus.QUEUED.value,
            DownloadStatus.FAILED.value,
        ):
            open_mini_window(self, self.engine, item_id)
        elif item.status == DownloadStatus.COMPLETED.value:
            self._open_file_id(item_id)

    # ── shortcuts ──────────────────────────────────────────────

    def _shortcut_pause_resume(self, _event=None) -> None:
        for iid in list(self._selected_ids):
            item = self.db.get_download(iid)
            if not item:
                continue
            if item.status == DownloadStatus.DOWNLOADING.value:
                self.engine.pause(iid)
            elif item.status in _RESUMABLE:
                self.engine.resume(iid)
            # completed: ignore

    def _shortcut_select_unfinished(self, _event=None) -> str:
        ids = []
        for iid in self._row_ids:
            item = self.db.get_download(iid)
            if item and item.status not in (
                DownloadStatus.COMPLETED.value,
                DownloadStatus.CANCELLED.value,
            ):
                ids.append(iid)
        self._selected_ids = set(ids)
        if ids:
            self._anchor_id = ids[0]
        self._apply_selection_styles()
        self._update_sel_bar()
        return "break"

    def _shortcut_restart(self, _event=None) -> str:
        self._sel_restart(confirm=False)
        return "break"

    def _shortcut_open_mini(self, _event=None) -> None:
        iid = self._primary_selected()
        if iid:
            open_mini_window(self, self.engine, iid)

    # ── bulk / context actions ─────────────────────────────────

    def _sel_pause(self) -> None:
        for iid in list(self._selected_ids):
            self.engine.pause(iid)

    def _sel_resume(self) -> None:
        """Start/Resume only for resumable statuses — never completed."""
        for iid in list(self._selected_ids):
            item = self.db.get_download(iid)
            if not item:
                continue
            if item.status == DownloadStatus.COMPLETED.value:
                continue
            if item.status in _RESUMABLE:
                self.engine.resume(iid)

    def _sel_restart(self, confirm: bool = True) -> None:
        ids = []
        for iid in list(self._selected_ids):
            item = self.db.get_download(iid)
            if not item:
                continue
            if item.status in (
                DownloadStatus.COMPLETED.value,
                DownloadStatus.FAILED.value,
                DownloadStatus.CANCELLED.value,
            ):
                ids.append(iid)
        if not ids:
            return
        if confirm:
            n = len(ids)
            ok = messagebox.askyesno(
                "Restart download",
                f"Re-download {n} item(s)? Existing file and partial data will be deleted.",
            )
            if not ok:
                return
        for iid in ids:
            self.engine.restart(iid)
        self._refresh_rows(force=True)

    def _sel_cancel(self) -> None:
        for iid in list(self._selected_ids):
            self.engine.cancel(iid)

    def _sel_delete(self) -> None:
        ids = list(self._selected_ids)
        if not ids:
            return
        name = "selected items" if len(ids) > 1 else (
            (self.db.get_download(ids[0]).filename if self.db.get_download(ids[0]) else "item")
        )
        self._pending_delete_ids = ids
        DeleteDialog(self, name, on_choice=self._on_delete_choice_multi)

    def _on_delete_choice_multi(self, choice: Optional[str]) -> None:
        ids = getattr(self, "_pending_delete_ids", [])
        if choice is None:
            return
        for iid in ids:
            self.engine.delete(iid, delete_files=(choice == "files"))
            self._selected_ids.discard(iid)
            self._row_widgets.pop(iid, None)
        self._pending_delete_ids = []
        self._refresh_rows(force=True)

    def _ctx_pause(self) -> None:
        self._sel_pause()

    def _ctx_resume(self) -> None:
        self._sel_resume()

    def _ctx_restart(self) -> None:
        self._sel_restart(confirm=True)

    def _ctx_cancel(self) -> None:
        self._sel_cancel()

    def _ctx_delete(self) -> None:
        self._sel_delete()

    def _open_mini(self) -> None:
        iid = self._primary_selected()
        if iid:
            open_mini_window(self, self.engine, iid)

    def _copy_url(self) -> None:
        item = self._selected_item()
        if not item:
            return
        self.clipboard_clear()
        self.clipboard_append(item.url)

    def _open_file(self) -> None:
        iid = self._primary_selected()
        if iid:
            self._open_file_id(iid)

    def _open_file_id(self, item_id: int) -> None:
        item = self.db.get_download(item_id)
        if not item:
            return
        path = Path(item.final_path)
        if not path.exists():
            messagebox.showwarning("Open file", f"File not found:\n{path}")
            return
        self._reveal(path, folder=False)

    def _open_folder(self) -> None:
        item = self._selected_item()
        if not item:
            return
        path = Path(item.final_path)
        folder = path.parent if path.exists() else Path(item.save_path)
        self._reveal(folder, folder=True)

    def _reveal(self, path: Path, folder: bool = False) -> None:
        try:
            system = platform.system()
            if system == "Windows":
                if folder:
                    os.startfile(str(path))  # type: ignore[attr-defined]
                else:
                    subprocess.run(["explorer", "/select,", str(path)], check=False)
            elif system == "Darwin":
                if folder:
                    subprocess.run(["open", str(path)], check=False)
                else:
                    subprocess.run(["open", "-R", str(path)], check=False)
            else:
                target = str(path if folder or path.is_dir() else path.parent)
                subprocess.run(["xdg-open", target], check=False)
        except Exception as exc:
            messagebox.showerror("Open", str(exc))

    def _update_status_bar(self) -> None:
        s = self.db.get_settings()
        active, queued = self.db.get_active_and_queued()
        lim = s.global_speed_limit
        lim_txt = format_speed(lim) if lim > 0 else "unlimited"
        seg_txt = ""
        # Prefer selected downloading item for segment detail
        focus = self._selected_item()
        target = None
        if focus and focus.status == DownloadStatus.DOWNLOADING.value:
            target = focus
        else:
            for item in self.db.list_downloads(status=DownloadStatus.DOWNLOADING.value):
                target = item
                break
        if target and target.id:
            rt = self.engine.get_runtime(target.id)
            segs = rt.get("segments") or target.segments
            active_s = rt.get("active_segments", 0)
            retries = rt.get("retries", 0)
            seg_txt = f"Seg {active_s}/{segs}  ·  Retries: {retries}"
            self.seg_status_lbl.configure(text=seg_txt)
        else:
            self.seg_status_lbl.configure(text="")
        self.status_label.configure(
            text=f"Limit: {lim_txt}   |   Active: {active}   |   Queued: {queued}"
        )

    # ── close / quit ───────────────────────────────────────────

    def _on_close(self) -> None:
        settings = self.db.get_settings()
        if settings.close_to_tray and self._tray and self._tray.available and not self._quitting:
            self.withdraw()
            return
        self._quit_app()

    def _quit_app(self) -> None:
        if self._quitting:
            return
        self._quitting = True

        def _do() -> None:
            if self._tray:
                self._tray.stop()
            self.engine.stop()
            self.destroy()

        try:
            self.after(0, _do)
        except Exception:
            _do()
