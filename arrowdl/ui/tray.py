"""System tray integration (pystray + Pillow). Degrades gracefully if unavailable."""

from __future__ import annotations

import io
import threading
from typing import Callable, Optional

TRAY_AVAILABLE = False
try:
    import pystray
    from PIL import Image, ImageDraw

    TRAY_AVAILABLE = True
except ImportError:
    pystray = None  # type: ignore
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore


def make_tray_icon(size: int = 64):
    """Generate a simple cyan arrow-down icon."""
    if not TRAY_AVAILABLE:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Teal circle background
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(0, 184, 169, 255),
    )
    # White downward arrow
    cx, cy = size // 2, size // 2
    arrow = [
        (cx, cy + 14),
        (cx - 12, cy),
        (cx - 5, cy),
        (cx - 5, cy - 14),
        (cx + 5, cy - 14),
        (cx + 5, cy),
        (cx + 12, cy),
    ]
    draw.polygon(arrow, fill=(255, 255, 255, 255))
    return img


class TrayController:
    """Background tray icon. Call stop() on quit."""

    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_pause_all: Callable[[], None],
        on_resume_all: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_show = on_show
        self._on_pause_all = on_pause_all
        self._on_resume_all = on_resume_all
        self._on_exit = on_exit
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._started = False

    @property
    def available(self) -> bool:
        return TRAY_AVAILABLE

    def start(self) -> bool:
        if not TRAY_AVAILABLE or self._started:
            return False
        icon_img = make_tray_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show ArrowDL", self._show, default=True),
            pystray.MenuItem("Pause unfinished", lambda: self._on_pause_all()),
            pystray.MenuItem("Resume unfinished", lambda: self._on_resume_all()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._exit),
        )
        self._icon = pystray.Icon("ArrowDL", icon_img, "ArrowDL", menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True, name="arrowdl-tray")
        self._thread.start()
        self._started = True
        return True

    def _show(self, icon=None, item=None) -> None:
        self._on_show()

    def _exit(self, icon=None, item=None) -> None:
        self._on_exit()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        self._started = False

    def notify(self, title: str, message: str) -> None:
        if self._icon is not None:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass
