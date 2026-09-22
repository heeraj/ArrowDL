"""Delete confirmation dialog."""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from arrowdl.ui import theme


class DeleteDialog(ctk.CTkToplevel):
    """Returns choice via callback: 'list' | 'files' | None (cancel)."""

    def __init__(
        self,
        parent,
        filename: str,
        on_choice: Callable[[Optional[str]], None],
    ) -> None:
        super().__init__(parent)
        self.title("Delete Download")
        self.geometry("420x220")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_DARK)
        self.transient(parent)
        self.grab_set()
        self._on_choice = on_choice
        self._chosen = False

        ctk.CTkLabel(
            self,
            text=f"Remove “{filename}”?",
            font=theme.font(14, "bold"),
            text_color=theme.TEXT,
            wraplength=380,
        ).pack(padx=20, pady=(24, 8))
        ctk.CTkLabel(
            self,
            text="Choose how to remove this download.",
            text_color=theme.TEXT_DIM,
        ).pack(padx=20, pady=(0, 16))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=8)

        ctk.CTkButton(
            btn_frame,
            text="Remove from list only",
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=lambda: self._choose("list"),
        ).pack(fill="x", pady=4)
        ctk.CTkButton(
            btn_frame,
            text="Remove and delete file(s)",
            fg_color=theme.DANGER,
            hover_color="#c0392b",
            command=lambda: self._choose("files"),
        ).pack(fill="x", pady=4)
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            fg_color="transparent",
            border_width=1,
            border_color=theme.BG_HOVER,
            hover_color=theme.BG_HOVER,
            command=lambda: self._choose(None),
        ).pack(fill="x", pady=4)

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose(None))

    def _choose(self, choice: Optional[str]) -> None:
        if self._chosen:
            return
        self._chosen = True
        self._on_choice(choice)
        self.destroy()
