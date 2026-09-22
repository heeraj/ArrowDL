"""ArrowDL dark theme with cyan/teal accents — compact v1.1 metrics."""

from __future__ import annotations

import customtkinter as ctk

# Palette
BG_DARK = "#1a1d23"
BG_SIDEBAR = "#12141a"
BG_CARD = "#22262e"
BG_HOVER = "#2a2f3a"
BG_SELECTED = "#1a3330"
ACCENT = "#00b8a9"
ACCENT_HOVER = "#00d4c4"
ACCENT_DIM = "#007a70"
TEXT = "#e8eaed"
TEXT_DIM = "#9aa0a6"
DANGER = "#e74c3c"
SUCCESS = "#2ecc71"
WARNING = "#f39c12"

FONT_FAMILY = "Segoe UI"
FONT_SIZE = 12
FONT_SIZE_SMALL = 10
FONT_SIZE_TITLE = 14

# Compact layout
TOOLBAR_HEIGHT = 40
SIDEBAR_WIDTH = 140
ROW_HEIGHT = 30
HEADER_HEIGHT = 28
DEFAULT_GEOMETRY = "1000x560"
MIN_SIZE = (800, 440)


def apply_theme() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")


def font(size: int = FONT_SIZE, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)
