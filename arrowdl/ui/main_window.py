"""Main application window — compact multi-select UI (v1.1)."""

from __future__ import annotations

import os
import platform
import subprocess
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
from arrowdl.utils import format_eta, format_size, format_speed


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
        self._anchor_id: Optional[int] = None  # for shift-range
        self._row_ids: List[int] = []
        self._row_widgets: Dict[int, dict] = {}  # id -> widget refs
        self._last_id_order: List[int] = []
        self._quitting = False
        self._tray: Optional[TrayController] = None

        self._build()
        self._init_tray()
        self.after(200, self._refresh)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── build ──────────────────────────────────────────────────

    def _build(self) -> None:
        # Toolbar
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
        # Secondary / overflow-style
        tbtn("Pause All", self.engine.pause_all, width=78)
        tbtn("Resume All", self.engine.resume_all, width=86)
        tbtn("⚙ Settings", self._open_settings, width=100)

        ctk.CTkLabel(
            toolbar,
            text="ArrowDL",
            font=theme.font(theme.FONT_SIZE_TITLE, "bold"),
            text_color=theme.ACCENT,
        ).pack(side="right", padx=12)

        # Selection action bar (hidden when empty)
        self.sel_bar = ctk.CTkFrame(self, fg_color=theme.BG_SIDEBAR, height=34, corner_radius=0)
        self.sel_bar.pack(fill="x", side="top")
        self.sel_bar.pack_propagate(False)
        self.sel_count_lbl = ctk.CTkLabel(
            self.sel_bar, text="0 selected", text_color=theme.TEXT_DIM, font=theme.font(11)
        )
        self.sel_count_lbl.pack(side="left", padx=10)

        def sbtn(text: str, cmd) -> None:
            ctk.CTkButton(
                self.sel_bar,
                text=text,
                width=70,
                height=26,
                fg_color=theme.BG_HOVER,
                hover_color=theme.BG_CARD,
                font=theme.font(11),
                command=cmd,
            ).pack(side="left", padx=3, pady=4)

        sbtn("▶ Start", self._sel_resume)
        sbtn("⏸ Pause", self._sel_pause)
        sbtn("⏹ Stop", self._sel_cancel)
        sbtn("🗑 Delete", self._sel_delete)
        self._hide_sel_bar()

        # Body
        body = ctk.CTkFrame(self, fg_color=theme.BG_DARK, corner_radius=0)
        body.pack(fill="both", expand=True)

        # Sidebar
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

        # Table area
        table_frame = ctk.CTkFrame(body, fg_color=theme.BG_DARK, corner_radius=0)
        table_frame.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        # Header — uses COL_SPECS
        header = ctk.CTkFrame(
            table_frame, fg_color=theme.BG_CARD, height=theme.HEADER_HEIGHT, corner_radius=4
        )
        header.pack(fill="x")
        header.pack_propagate(False)
        for _key, label, width, anchor in COL_SPECS:
            ctk.CTkLabel(
                header,
                text=label,
                width=width,
                anchor=anchor,
                font=theme.font(10, "bold"),
                text_color=theme.TEXT_DIM,
            ).pack(side="left", padx=2)

        self.list_frame = ctk.CTkScrollableFrame(
            table_frame, fg_color=theme.BG_DARK, corner_radius=0
        )
        self.list_frame.pack(fill="both", expand=True, pady=(2, 0))

        # Context menu
        self._menu = tk.Menu(self, tearoff=0, bg=theme.BG_CARD, fg=theme.TEXT)
        self._menu.add_command(label="Open file", command=self._open_file)
        self._menu.add_command(label="Open folder", command=self._open_folder)
        self._menu.add_command(label="Open mini window", command=self._open_mini)
        self._menu.add_command(label="Copy URL", command=self._copy_url)
        self._menu.add_separator()
        self._menu.add_command(label="Pause", command=self._ctx_pause)
        self._menu.add_command(label="Resume", command=self._ctx_resume)
        self._menu.add_command(label="Cancel", command=self._ctx_cancel)
        self._menu.add_separator()
        self._menu.add_command(label="Delete", command=self._ctx_delete)

        # Status bar
        self.statusbar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, height=24, corner_radius=0)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            self.statusbar, text="", text_color=theme.TEXT_DIM, font=theme.font(10), anchor="w"
        )
        self.status_label.pack(side="left", padx=10)

    def _hide_sel_bar(self) -> None:
        self.sel_bar.pack_forget()

    def _show_sel_bar(self) -> None:
        # Re-pack below toolbar (before body). Use before= if needed — pack order:
        # re-pack after toolbar by forgetting all and... simpler: just pack and lift.
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

    def _add_download(self) -> None:
        s = self.db.get_settings()
        AddDownloadDialog(
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
        self._selected_ids -= {
            i for i in self._selected_ids
            if (it := self.db.get_download(i)) is None
            or it.status == DownloadStatus.COMPLETED.value
        }
        # clear_completed already deleted them
        self._refresh_rows(force=True)
        if n:
            messagebox.showinfo("Clear completed", f"Removed {n} completed item(s) from the list.")

    # ── refresh (in-place when possible) ───────────────────────

    def _refresh(self) -> None:
        try:
            self._refresh_rows(force=False)
            self._update_status_bar()
        except Exception:
            pass
        if self.winfo_exists() and not self._quitting:
            self.after(500, self._refresh)

    def _ordered_items(self) -> List[DownloadItem]:
        items = self.db.list_downloads(
            status=self._filter_status, category=self._filter_category
        )
        # Auto-arrange completed when All / no status filter
        if self._filter_status is None:
            unfinished, finished = split_completed_groups(items)
            # Also include any odd statuses
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

        # In-place update
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

        row = ctk.CTkFrame(
            self.list_frame, fg_color=theme.BG_CARD, height=theme.ROW_HEIGHT, corner_radius=3
        )
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        refs: dict = {"row": row, "labels": {}, "bar": None, "pct": None}

        for key, _label, width, anchor in COL_SPECS:
            if key == "progress":
                frame = ctk.CTkFrame(row, fg_color="transparent", width=width, height=theme.ROW_HEIGHT)
                frame.pack(side="left", padx=2)
                frame.pack_propagate(False)
                bar = ctk.CTkProgressBar(
                    frame, width=max(40, width - 42), height=8,
                    progress_color=theme.ACCENT, fg_color=theme.BG_HOVER,
                )
                bar.place(x=0, y=11)
                bar.set(max(0.0, min(1.0, item.progress / 100.0)))
                pct = ctk.CTkLabel(
                    frame, text=f"{item.progress:.0f}%", width=40, anchor="e",
                    text_color=theme.TEXT_DIM, font=theme.font(10),
                )
                pct.place(x=width - 42, y=4)
                refs["bar"] = bar
                refs["pct"] = pct
                for w in (frame, bar, pct):
                    self._bind_row_events(w, item.id)
            else:
                text = self._cell_text(key, item, speed, eta)
                lbl = ctk.CTkLabel(
                    row, text=text, width=width, anchor=anchor,
                    text_color=theme.TEXT, font=theme.font(11),
                )
                lbl.pack(side="left", padx=2)
                refs["labels"][key] = lbl
                self._bind_row_events(lbl, item.id)

        self._bind_row_events(row, item.id)
        self._row_widgets[item.id] = refs
        self._style_row(item.id, item.status)

    def _cell_text(self, key: str, item: DownloadItem, speed: float, eta) -> str:
        if key == "name":
            name = item.filename or "—"
            return name if len(name) <= 36 else name[:33] + "…"
        if key == "size":
            return format_size(item.total_size) if item.total_size else "—"
        if key == "speed":
            return format_speed(speed)
        if key == "eta":
            return format_eta(eta)
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
        if refs["pct"] is not None:
            refs["pct"].configure(text=f"{item.progress:.0f}%")
        self._style_row(item.id, item.status)

    def _style_row(self, item_id: int, status: str) -> None:
        refs = self._row_widgets.get(item_id)
        if not refs:
            return
        row = refs["row"]
        if item_id in self._selected_ids:
            row.configure(fg_color=theme.BG_SELECTED, border_width=1, border_color=theme.ACCENT)
        elif status == DownloadStatus.DOWNLOADING.value:
            row.configure(fg_color=theme.BG_HOVER, border_width=0)
        elif status == DownloadStatus.FAILED.value:
            row.configure(fg_color="#2a1a1a", border_width=0)
        else:
            row.configure(fg_color=theme.BG_CARD, border_width=0)

    def _apply_selection_styles(self) -> None:
        for iid, refs in self._row_widgets.items():
            item = self.db.get_download(iid)
            st = item.status if item else ""
            self._style_row(iid, st)

    def _bind_row_events(self, widget, item_id: int) -> None:
        widget.bind("<Button-1>", lambda e, i=item_id: self._on_click(e, i))
        widget.bind("<Button-3>", lambda e, i=item_id: self._popup(e, i))
        widget.bind("<Double-Button-1>", lambda e, i=item_id: self._on_double(i))
        # Ctrl equivalents on Linux often use Control
        widget.bind("<Control-Button-1>", lambda e, i=item_id: self._on_click(e, i))

    # ── selection ──────────────────────────────────────────────

    def _on_click(self, event, item_id: int) -> None:
        ctrl = bool(event.state & 0x0004)  # Control
        shift = bool(event.state & 0x0001)  # Shift
        # macOS Command as ctrl-like
        if event.state & 0x0008:  # Mod1 / Command on some platforms
            ctrl = True

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
        else:
            self._selected_ids = {item_id}
            self._anchor_id = item_id

        self._apply_selection_styles()
        self._update_sel_bar()

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
        ):
            open_mini_window(self, self.engine, item_id)
        elif item.status == DownloadStatus.COMPLETED.value:
            self._open_file_id(item_id)

    # ── bulk / context actions ─────────────────────────────────

    def _sel_pause(self) -> None:
        for iid in list(self._selected_ids):
            self.engine.pause(iid)

    def _sel_resume(self) -> None:
        for iid in list(self._selected_ids):
            self.engine.resume(iid)

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
        # Segments / retries for first active download
        seg_txt = ""
        for item in self.db.list_downloads(status=DownloadStatus.DOWNLOADING.value):
            rt = self.engine.get_runtime(item.id)
            segs = rt.get("segments") or item.segments
            retries = rt.get("retries", 0)
            seg_txt = f"   |   Segments: {segs}   |   Retries: {retries}"
            break
        self.status_label.configure(
            text=(
                f"Limit: {lim_txt}   |   Active: {active}   |   Queued: {queued}{seg_txt}"
            )
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
