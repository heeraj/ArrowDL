"""Settings dialog."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from arrowdl.config import ensure_category_dirs
from arrowdl.models import AppSettings
from arrowdl.ui import theme


class SettingsDialog(ctk.CTkToplevel):
    def __init__(
        self,
        parent,
        settings: AppSettings,
        on_save: Callable[[AppSettings], None],
    ) -> None:
        super().__init__(parent)
        self.title("Settings — ArrowDL")
        self.geometry("520x600")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()
        self._on_save = on_save

        pad = {"padx": 16, "pady": (10, 0)}

        def labeled_entry(label: str, var: ctk.StringVar, width: int = 200) -> None:
            ctk.CTkLabel(self, text=label, font=theme.font(weight="bold"), text_color=theme.TEXT).pack(
                anchor="w", **pad
            )
            ctk.CTkEntry(self, textvariable=var, width=width, fg_color=theme.BG_CARD).pack(
                anchor="w", padx=16, pady=(4, 0)
            )

        self.segments_var = ctk.StringVar(value=str(settings.default_segments))
        labeled_entry("Default segments (1–16)", self.segments_var, 100)

        self.concurrent_var = ctk.StringVar(value=str(settings.max_concurrent))
        labeled_entry("Max concurrent downloads", self.concurrent_var, 100)

        speed_kb = settings.global_speed_limit / 1024 if settings.global_speed_limit else 0
        self.speed_var = ctk.StringVar(value=str(int(speed_kb) if speed_kb == int(speed_kb) else speed_kb))
        labeled_entry("Global speed limit (KB/s, 0=unlimited)", self.speed_var, 120)

        ctk.CTkLabel(
            self, text="Base download folder", font=theme.font(weight="bold"), text_color=theme.TEXT
        ).pack(anchor="w", **pad)
        folder_row = ctk.CTkFrame(self, fg_color="transparent")
        folder_row.pack(fill="x", padx=16, pady=(4, 0))
        self.folder_var = ctk.StringVar(value=settings.base_download_folder)
        ctk.CTkEntry(folder_row, textvariable=self.folder_var, width=380, fg_color=theme.BG_CARD).pack(
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

        ctk.CTkLabel(
            self, text="Category subfolders", font=theme.font(weight="bold"), text_color=theme.TEXT
        ).pack(anchor="w", **pad)
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=16, pady=(4, 0))
        self.cat_software = ctk.StringVar(value=settings.category_software)
        self.cat_docs = ctk.StringVar(value=settings.category_docs)
        self.cat_videos = ctk.StringVar(value=settings.category_videos)
        self.cat_other = ctk.StringVar(value=settings.category_other)
        for i, (label, var) in enumerate(
            [
                ("Software", self.cat_software),
                ("Docs", self.cat_docs),
                ("Videos", self.cat_videos),
                ("Other", self.cat_other),
            ]
        ):
            ctk.CTkLabel(grid, text=label, text_color=theme.TEXT_DIM, width=80).grid(
                row=i, column=0, sticky="w", pady=2
            )
            ctk.CTkEntry(grid, textvariable=var, width=200, fg_color=theme.BG_CARD).grid(
                row=i, column=1, sticky="w", pady=2
            )

        self.start_win_var = ctk.BooleanVar(value=settings.start_with_windows)
        ctk.CTkCheckBox(
            self,
            text="Start with Windows (saved for later; registry not wired in v1)",
            variable=self.start_win_var,
            text_color=theme.TEXT_DIM,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
        ).pack(anchor="w", padx=16, pady=(16, 0))

        self.close_tray_var = ctk.BooleanVar(value=settings.close_to_tray)
        ctk.CTkCheckBox(
            self,
            text="Minimize / close to tray (Exit from tray quits)",
            variable=self.close_tray_var,
            text_color=theme.TEXT_DIM,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
        ).pack(anchor="w", padx=16, pady=(10, 0))

        self.sound_complete_var = ctk.BooleanVar(value=settings.sound_on_complete)
        ctk.CTkCheckBox(
            self,
            text="Play sound when a download completes (Windows only; off by default)",
            variable=self.sound_complete_var,
            text_color=theme.TEXT_DIM,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
        ).pack(anchor="w", padx=16, pady=(10, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=24)
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
            text="Save",
            width=100,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#00332e",
            command=self._save,
        ).pack(side="right")

    def _browse(self) -> None:
        path = filedialog.askdirectory(initialdir=self.folder_var.get())
        if path:
            self.folder_var.set(path)

    def _save(self) -> None:
        try:
            segments = max(1, min(16, int(self.segments_var.get())))
            concurrent = max(1, int(self.concurrent_var.get()))
            speed_kb = float(self.speed_var.get() or "0")
            speed = int(speed_kb * 1024) if speed_kb > 0 else 0
        except ValueError:
            messagebox.showerror("Settings", "Invalid numeric value.", parent=self)
            return
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showerror("Settings", "Base folder required.", parent=self)
            return
        s = AppSettings(
            default_segments=segments,
            max_concurrent=concurrent,
            global_speed_limit=speed,
            base_download_folder=folder,
            category_software=self.cat_software.get().strip() or "Software",
            category_docs=self.cat_docs.get().strip() or "Docs",
            category_videos=self.cat_videos.get().strip() or "Videos",
            category_other=self.cat_other.get().strip() or "Other",
            start_with_windows=bool(self.start_win_var.get()),
            close_to_tray=bool(self.close_tray_var.get()),
            sound_on_complete=bool(self.sound_complete_var.get()),
        )
        ensure_category_dirs(
            s.base_download_folder,
            {
                "Software": s.category_software,
                "Docs": s.category_docs,
                "Videos": s.category_videos,
                "Other": s.category_other,
            },
        )
        self._on_save(s)
        self.destroy()
