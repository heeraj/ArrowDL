"""Add Download dialog."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from arrowdl.models import Category, DownloadItem
from arrowdl.ui import theme
from arrowdl.utils import filename_from_url, guess_category, sanitize_filename


class AddDownloadDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        default_segments: int,
        base_folder: str,
        category_subdirs: dict[str, str],
        on_submit: Callable[[DownloadItem], None],
    ) -> None:
        super().__init__(parent)
        self.title("Add Download — ArrowDL")
        self.geometry("560x480")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()

        self._on_submit = on_submit
        self._base_folder = base_folder
        self._category_subdirs = category_subdirs
        self._default_segments = default_segments

        pad = {"padx": 16, "pady": (8, 0)}

        ctk.CTkLabel(self, text="URL", font=theme.font(weight="bold"), text_color=theme.TEXT).pack(
            anchor="w", **pad
        )
        self.url_var = ctk.StringVar()
        self.url_entry = ctk.CTkEntry(
            self, textvariable=self.url_var, width=520, fg_color=theme.BG_CARD
        )
        self.url_entry.pack(anchor="w", padx=16, pady=(4, 0))
        self.url_var.trace_add("write", self._on_url_change)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(12, 0))
        ctk.CTkLabel(row, text="Filename", font=theme.font(weight="bold"), text_color=theme.TEXT).pack(
            anchor="w"
        )
        self.filename_var = ctk.StringVar(value="download")
        ctk.CTkEntry(row, textvariable=self.filename_var, width=520, fg_color=theme.BG_CARD).pack(
            anchor="w", pady=(4, 0)
        )

        ctk.CTkLabel(self, text="Save folder", font=theme.font(weight="bold"), text_color=theme.TEXT).pack(
            anchor="w", **pad
        )
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=16, pady=(4, 0))
        self.folder_var = ctk.StringVar()
        ctk.CTkEntry(folder_row, textvariable=self.folder_var, width=420, fg_color=theme.BG_CARD).pack(
            side="left"
        )
        ctk.CTkButton(
            folder_row,
            text="Browse",
            width=80,
            fg_color=theme.ACCENT_DIM,
            hover_color=theme.ACCENT,
            command=self._browse,
        ).pack(side="left", padx=(8, 0))

        opts = ctk.CTkFrame(self, fg_color="transparent")
        opts.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(opts, text="Category", text_color=theme.TEXT_DIM).grid(row=0, column=0, sticky="w")
        self.category_var = ctk.StringVar(value=Category.OTHER.value)
        self.category_menu = ctk.CTkOptionMenu(
            opts,
            variable=self.category_var,
            values=[c.value for c in Category],
            fg_color=theme.BG_CARD,
            button_color=theme.ACCENT_DIM,
            button_hover_color=theme.ACCENT,
            command=self._on_category_change,
            width=140,
        )
        self.category_menu.grid(row=1, column=0, sticky="w", padx=(0, 16))

        ctk.CTkLabel(opts, text="Segments (1–16)", text_color=theme.TEXT_DIM).grid(
            row=0, column=1, sticky="w"
        )
        self.segments_var = ctk.StringVar(value=str(default_segments))
        ctk.CTkEntry(opts, textvariable=self.segments_var, width=80, fg_color=theme.BG_CARD).grid(
            row=1, column=1, sticky="w", padx=(0, 16)
        )

        ctk.CTkLabel(opts, text="Speed limit (KB/s, 0=∞)", text_color=theme.TEXT_DIM).grid(
            row=0, column=2, sticky="w"
        )
        self.speed_var = ctk.StringVar(value="0")
        ctk.CTkEntry(opts, textvariable=self.speed_var, width=100, fg_color=theme.BG_CARD).grid(
            row=1, column=2, sticky="w"
        )

        ctk.CTkLabel(
            self, text="Schedule start (optional, YYYY-MM-DD HH:MM)", font=theme.font(weight="bold"), text_color=theme.TEXT
        ).pack(anchor="w", **pad)
        self.schedule_var = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.schedule_var, width=280, fg_color=theme.BG_CARD).pack(
            anchor="w", padx=16, pady=(4, 0)
        )

        self.status_label = ctk.CTkLabel(self, text="", text_color=theme.TEXT_DIM)
        self.status_label.pack(anchor="w", padx=16, pady=(8, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=20)
        ctk.CTkButton(
            btn_row,
            text="Cancel",
            width=100,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row,
            text="Download",
            width=120,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#00332e",
            command=self._submit,
        ).pack(side="right")

        self._on_category_change(self.category_var.get())
        self.after(50, self.url_entry.focus_set)

    def _browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.folder_var.get() or self._base_folder)
        if path:
            self.folder_var.set(path)

    def _on_category_change(self, value: str) -> None:
        sub = self._category_subdirs.get(value, value)
        self.folder_var.set(str(Path(self._base_folder) / sub))

    def _on_url_change(self, *_args) -> None:
        url = self.url_var.get().strip()
        if not url:
            return
        name = filename_from_url(url)
        self.filename_var.set(name)
        cat = guess_category(name)
        self.category_var.set(cat)
        self._on_category_change(cat)
        # Optional async probe
        self.status_label.configure(text="Resolving…")
        threading.Thread(target=self._probe, args=(url,), daemon=True).start()

    def _probe(self, url: str) -> None:
        try:
            from arrowdl.downloader import probe_url

            filename, size = probe_url(url)
            def apply() -> None:
                if self.url_var.get().strip() != url:
                    return
                if filename:
                    self.filename_var.set(filename)
                    cat = guess_category(filename)
                    self.category_var.set(cat)
                    self._on_category_change(cat)
                from arrowdl.utils import format_size
                self.status_label.configure(
                    text=f"Size: {format_size(size)}" if size else "Size: unknown"
                )
            self.after(0, apply)
        except Exception:
            self.after(0, lambda: self.status_label.configure(text=""))

    def _submit(self) -> None:
        url = self.url_var.get().strip()
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            messagebox.showerror("Invalid URL", "Enter a valid http(s) URL.", parent=self)
            return
        filename = sanitize_filename(self.filename_var.get().strip() or "download")
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Folder", "Choose a save folder.", parent=self)
            return
        try:
            segments = int(self.segments_var.get().strip())
            segments = max(1, min(16, segments))
        except ValueError:
            segments = self._default_segments
        try:
            speed_kb = float(self.speed_var.get().strip() or "0")
            speed_limit = int(speed_kb * 1024) if speed_kb > 0 else 0
        except ValueError:
            speed_limit = 0

        start_at = None
        sched = self.schedule_var.get().strip()
        if sched:
            try:
                dt = datetime.strptime(sched, "%Y-%m-%d %H:%M")
                start_at = dt.isoformat()
            except ValueError:
                messagebox.showerror(
                    "Schedule",
                    "Use format YYYY-MM-DD HH:MM (local time).",
                    parent=self,
                )
                return

        Path(folder).mkdir(parents=True, exist_ok=True)
        item = DownloadItem(
            url=url,
            filename=filename,
            save_path=folder,
            category=self.category_var.get(),
            segments=segments,
            speed_limit=speed_limit,
            start_at=start_at,
        )
        self._on_submit(item)
        self.destroy()
