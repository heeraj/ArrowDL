"""Main application window."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from arrowdl.engine import DownloadEngine
from arrowdl.models import Category, DownloadItem, DownloadStatus
from arrowdl.ui import theme
from arrowdl.ui.add_dialog import AddDownloadDialog
from arrowdl.ui.delete_dialog import DeleteDialog
from arrowdl.ui.settings_dialog import SettingsDialog
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

COLUMNS = ("Name", "Size", "Progress", "Speed", "ETA", "Status", "Category")
COL_WIDTHS = (220, 90, 100, 90, 80, 100, 90)


class MainWindow(ctk.CTk):
    def __init__(self, engine: DownloadEngine) -> None:
        super().__init__()
        theme.apply_theme()
        self.engine = engine
        self.db = engine.db
        self.title("ArrowDL")
        self.geometry("1100x640")
        self.minsize(900, 500)
        self.configure(fg_color=theme.BG_DARK)

        self._filter_status: Optional[str] = None
        self._filter_category: Optional[str] = None
        self._selected_id: Optional[int] = None
        self._row_ids: list[int] = []

        self._build()
        self.after(200, self._refresh)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self) -> None:
        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, height=48, corner_radius=0)
        toolbar.pack(fill="x", side="top")
        toolbar.pack_propagate(False)

        def tbtn(text: str, cmd, accent: bool = False) -> None:
            ctk.CTkButton(
                toolbar,
                text=text,
                width=100,
                height=32,
                fg_color=theme.ACCENT if accent else theme.BG_HOVER,
                hover_color=theme.ACCENT_HOVER if accent else theme.BG_CARD,
                text_color="#00332e" if accent else theme.TEXT,
                command=cmd,
            ).pack(side="left", padx=(8, 0), pady=8)

        tbtn("Add URL", self._add_download, accent=True)
        tbtn("Pause All", self.engine.pause_all)
        tbtn("Resume All", self.engine.resume_all)
        tbtn("Clear Done", self._clear_completed)
        tbtn("Settings", self._open_settings)

        ctk.CTkLabel(
            toolbar,
            text="ArrowDL",
            font=theme.font(theme.FONT_SIZE_TITLE, "bold"),
            text_color=theme.ACCENT,
        ).pack(side="right", padx=16)

        # Body
        body = ctk.CTkFrame(self, fg_color=theme.BG_DARK, corner_radius=0)
        body.pack(fill="both", expand=True)

        # Sidebar
        sidebar = ctk.CTkFrame(body, fg_color=theme.BG_SIDEBAR, width=160, corner_radius=0)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        ctk.CTkLabel(
            sidebar, text="Filters", font=theme.font(12, "bold"), text_color=theme.TEXT_DIM
        ).pack(anchor="w", padx=12, pady=(12, 4))

        self._filter_btns: list[ctk.CTkButton] = []
        for label, status, category in FILTERS:
            if status == "__sep__":
                ctk.CTkLabel(
                    sidebar, text=label, text_color=theme.TEXT_DIM, font=theme.font(10)
                ).pack(anchor="w", padx=12, pady=(12, 2))
                continue
            btn = ctk.CTkButton(
                sidebar,
                text=label,
                anchor="w",
                fg_color="transparent",
                hover_color=theme.BG_HOVER,
                text_color=theme.TEXT,
                height=28,
                command=lambda s=status, c=category, l=label: self._set_filter(s, c, l),
            )
            btn.pack(fill="x", padx=8, pady=1)
            self._filter_btns.append(btn)

        # Table area
        table_frame = ctk.CTkFrame(body, fg_color=theme.BG_DARK, corner_radius=0)
        table_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        # Header
        header = ctk.CTkFrame(table_frame, fg_color=theme.BG_CARD, height=32, corner_radius=4)
        header.pack(fill="x")
        header.pack_propagate(False)
        for col, w in zip(COLUMNS, COL_WIDTHS):
            ctk.CTkLabel(
                header,
                text=col,
                width=w,
                anchor="w",
                font=theme.font(11, "bold"),
                text_color=theme.TEXT_DIM,
            ).pack(side="left", padx=4)

        # Scrollable rows
        self.list_frame = ctk.CTkScrollableFrame(
            table_frame, fg_color=theme.BG_DARK, corner_radius=0
        )
        self.list_frame.pack(fill="both", expand=True, pady=(4, 0))

        # Context menu (tk)
        self._menu = tk.Menu(self, tearoff=0, bg=theme.BG_CARD, fg=theme.TEXT)
        self._menu.add_command(label="Open file", command=self._open_file)
        self._menu.add_command(label="Open folder", command=self._open_folder)
        self._menu.add_command(label="Copy URL", command=self._copy_url)
        self._menu.add_separator()
        self._menu.add_command(label="Pause", command=self._ctx_pause)
        self._menu.add_command(label="Resume", command=self._ctx_resume)
        self._menu.add_command(label="Cancel", command=self._ctx_cancel)
        self._menu.add_separator()
        self._menu.add_command(label="Delete", command=self._ctx_delete)

        # Status bar
        self.statusbar = ctk.CTkFrame(self, fg_color=theme.BG_CARD, height=28, corner_radius=0)
        self.statusbar.pack(fill="x", side="bottom")
        self.statusbar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(
            self.statusbar, text="", text_color=theme.TEXT_DIM, font=theme.font(11), anchor="w"
        )
        self.status_label.pack(side="left", padx=12)

    def _set_filter(self, status: Optional[str], category: Optional[str], label: str) -> None:
        self._filter_status = status
        self._filter_category = category
        self._refresh_rows()

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
        self._refresh_rows()

    def _open_settings(self) -> None:
        SettingsDialog(self, self.db.get_settings(), on_save=self._on_settings_saved)

    def _on_settings_saved(self, settings) -> None:
        self.db.save_settings(settings)
        self.engine.reload_settings()
        self._update_status_bar()

    def _clear_completed(self) -> None:
        n = self.db.clear_completed()
        self._refresh_rows()
        if n:
            messagebox.showinfo("Clear completed", f"Removed {n} completed item(s) from the list.")

    def _refresh(self) -> None:
        try:
            self._refresh_rows()
            self._update_status_bar()
        except Exception:
            pass
        if self.winfo_exists():
            self.after(500, self._refresh)

    def _refresh_rows(self) -> None:
        items = self.db.list_downloads(
            status=self._filter_status, category=self._filter_category
        )
        # Special: Queued filter also shows nothing else; All shows all
        for w in self.list_frame.winfo_children():
            w.destroy()
        self._row_ids = []

        for item in items:
            self._row_ids.append(item.id)
            self._make_row(item)

    def _make_row(self, item: DownloadItem) -> None:
        runtime = self.engine.get_runtime(item.id) if item.id else {}
        speed = runtime.get("speed", 0.0) or 0.0
        eta = runtime.get("eta")
        if item.status != DownloadStatus.DOWNLOADING.value:
            speed = 0.0
            eta = None

        row = ctk.CTkFrame(self.list_frame, fg_color=theme.BG_CARD, height=36, corner_radius=4)
        row.pack(fill="x", pady=2)
        row.pack_propagate(False)

        values = [
            item.filename or "—",
            format_size(item.total_size) if item.total_size else "—",
            f"{item.progress:.1f}%",
            format_speed(speed),
            format_eta(eta),
            item.status.capitalize(),
            item.category,
        ]
        for val, w in zip(values, COL_WIDTHS):
            lbl = ctk.CTkLabel(
                row, text=val, width=w, anchor="w", text_color=theme.TEXT, font=theme.font(12)
            )
            lbl.pack(side="left", padx=4)
            lbl.bind("<Button-1>", lambda e, i=item.id: self._select(i))
            lbl.bind("<Button-3>", lambda e, i=item.id: self._popup(e, i))
            lbl.bind("<Double-Button-1>", lambda e, i=item.id: self._open_file_id(i))

        row.bind("<Button-1>", lambda e, i=item.id: self._select(i))
        row.bind("<Button-3>", lambda e, i=item.id: self._popup(e, i))

        # Progress tint for downloading
        if item.status == DownloadStatus.DOWNLOADING.value:
            row.configure(fg_color=theme.BG_HOVER)
        elif item.status == DownloadStatus.COMPLETED.value:
            pass
        elif item.status == DownloadStatus.FAILED.value:
            row.configure(fg_color="#2a1a1a")

    def _select(self, item_id: int) -> None:
        self._selected_id = item_id

    def _popup(self, event, item_id: int) -> None:
        self._selected_id = item_id
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _selected_item(self) -> Optional[DownloadItem]:
        if self._selected_id is None:
            return None
        return self.db.get_download(self._selected_id)

    def _ctx_pause(self) -> None:
        if self._selected_id:
            self.engine.pause(self._selected_id)

    def _ctx_resume(self) -> None:
        if self._selected_id:
            self.engine.resume(self._selected_id)

    def _ctx_cancel(self) -> None:
        if self._selected_id:
            self.engine.cancel(self._selected_id)

    def _ctx_delete(self) -> None:
        item = self._selected_item()
        if not item:
            return
        DeleteDialog(self, item.filename, on_choice=self._on_delete_choice)

    def _on_delete_choice(self, choice: Optional[str]) -> None:
        if choice is None or self._selected_id is None:
            return
        self.engine.delete(self._selected_id, delete_files=(choice == "files"))
        self._selected_id = None
        self._refresh_rows()

    def _copy_url(self) -> None:
        item = self._selected_item()
        if not item:
            return
        self.clipboard_clear()
        self.clipboard_append(item.url)

    def _open_file(self) -> None:
        if self._selected_id:
            self._open_file_id(self._selected_id)

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
        self.status_label.configure(
            text=f"Global speed limit: {lim_txt}   |   Active: {active}   |   Queued: {queued}"
        )

    def _on_close(self) -> None:
        self.engine.stop()
        self.destroy()
