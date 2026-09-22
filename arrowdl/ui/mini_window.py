"""Always-on-top mini progress window for a single download (v1.2)."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

import customtkinter as ctk

from arrowdl.config import get_app_data_dir
from arrowdl.models import DownloadStatus
from arrowdl.ui import theme
from arrowdl.utils import format_eta, format_eta_wallclock, format_speed, mbps_to_bps

if TYPE_CHECKING:
    from arrowdl.engine import DownloadEngine

# id -> MiniDownloadWindow
_OPEN: Dict[int, "MiniDownloadWindow"] = {}

_POS_FILE = "mini_positions.json"
_PULSE_COLORS = (theme.ACCENT, theme.ACCENT_HOVER, "#33e0d0", theme.ACCENT_DIM)


def _load_positions() -> dict:
    path = get_app_data_dir() / _POS_FILE
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_position(item_id: int, geometry: str) -> None:
    path = get_app_data_dir() / _POS_FILE
    try:
        data = _load_positions()
        data[str(item_id)] = geometry
        path.write_text(json.dumps(data, indent=0), encoding="utf-8")
    except Exception:
        pass


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
        self.geometry("360x168")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=theme.BG_DARK)
        self.protocol("WM_DELETE_WINDOW", self._close_only)

        self._pulse_on = False
        self._pulse_idx = 0
        self._pulse_after: Optional[str] = None
        self._limit_expanded = False
        self._seg_pills: list[ctk.CTkFrame] = []
        self._last_status = ""

        # Restore pinned position if known
        pos = _load_positions().get(str(item_id))
        if isinstance(pos, str) and "x" in pos:
            try:
                self.geometry(pos if pos.startswith("360") else f"360x168{pos[pos.find('+'):]}")
            except Exception:
                self.geometry("360x168")

        self.name_lbl = ctk.CTkLabel(
            self, text="…", font=theme.font(12, "bold"), text_color=theme.TEXT, anchor="w"
        )
        self.name_lbl.pack(fill="x", padx=12, pady=(8, 2))

        bar_row = ctk.CTkFrame(self, fg_color="transparent")
        bar_row.pack(fill="x", padx=12, pady=0)
        self.bar = ctk.CTkProgressBar(
            bar_row, width=250, height=10, progress_color=theme.ACCENT, fg_color=theme.BG_CARD
        )
        self.bar.pack(side="left")
        self.bar.set(0)
        self.pct_lbl = ctk.CTkLabel(
            bar_row, text="0%", width=48, anchor="e", text_color=theme.TEXT_DIM, font=theme.font(11)
        )
        self.pct_lbl.pack(side="left", padx=(6, 0))
        self.activity = ctk.CTkLabel(
            bar_row, text="●", width=14, text_color=theme.ACCENT_DIM, font=theme.font(10)
        )
        self.activity.pack(side="left")

        # Segment pills + Seg N/M
        seg_row = ctk.CTkFrame(self, fg_color="transparent", height=14)
        seg_row.pack(fill="x", padx=12, pady=(2, 0))
        seg_row.pack_propagate(False)
        self.seg_lbl = ctk.CTkLabel(
            seg_row, text="Seg —", width=56, anchor="w",
            text_color=theme.TEXT_DIM, font=theme.font(9),
        )
        self.seg_lbl.pack(side="left")
        self.seg_pills_frame = ctk.CTkFrame(seg_row, fg_color="transparent")
        self.seg_pills_frame.pack(side="left", fill="x", expand=True)

        self.meta_lbl = ctk.CTkLabel(
            self, text="", text_color=theme.TEXT_DIM, font=theme.font(10), anchor="w"
        )
        self.meta_lbl.pack(fill="x", padx=12, pady=(2, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=10, pady=(4, 0))

        self.pause_btn = ctk.CTkButton(
            btn_row,
            text="⏸ Pause",
            width=86,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            font=theme.font(11, "bold"),
            command=self._toggle_pause,
        )
        self.pause_btn.pack(side="left", padx=(0, 4))

        self.limit_btn = ctk.CTkButton(
            btn_row,
            text="⚡ Limit",
            width=70,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            font=theme.font(11),
            command=self._toggle_limit_row,
        )
        self.limit_btn.pack(side="left", padx=(0, 4))

        self.folder_btn = ctk.CTkButton(
            btn_row,
            text="📂",
            width=36,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self._open_folder,
        )
        self.folder_btn.pack(side="left", padx=(0, 4))

        self.copy_btn = ctk.CTkButton(
            btn_row,
            text="🔗",
            width=36,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self._copy_url,
        )
        self.copy_btn.pack(side="left", padx=(0, 4))

        self.stop_btn = ctk.CTkButton(
            btn_row,
            text="⏹",
            width=36,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            command=self._stop,
        )
        self.stop_btn.pack(side="left", padx=(0, 4))

        self.open_btn = ctk.CTkButton(
            btn_row,
            text="Open file",
            width=80,
            height=26,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#00332e",
            font=theme.font(11),
            command=self._open_file,
        )
        # packed when completed

        self.restart_btn = ctk.CTkButton(
            btn_row,
            text="↻ Restart",
            width=80,
            height=26,
            fg_color=theme.BG_HOVER,
            hover_color=theme.BG_CARD,
            font=theme.font(11),
            command=self._restart,
        )
        # packed when completed / failed

        # Speed limit chip row (hidden by default)
        self.limit_row = ctk.CTkFrame(self, fg_color=theme.BG_CARD, corner_radius=4, height=28)
        # not packed until expanded
        self._build_limit_chips()

        self.bind("<Configure>", self._on_configure)
        self.after(200, self._tick)

    def _build_limit_chips(self) -> None:
        for child in self.limit_row.winfo_children():
            child.destroy()
        chips = [("∞", 0), ("1", 1), ("2", 2), ("3", 3), ("4", 4), ("5", 5)]
        for label, mbps in chips:
            ctk.CTkButton(
                self.limit_row,
                text=label if mbps == 0 else f"{label}M",
                width=36,
                height=22,
                fg_color=theme.BG_HOVER,
                hover_color=theme.ACCENT_DIM,
                font=theme.font(10),
                command=lambda m=mbps: self._apply_limit_mbps(m),
            ).pack(side="left", padx=2, pady=2)
        self._custom_var = ctk.StringVar(value="")
        entry = ctk.CTkEntry(
            self.limit_row, textvariable=self._custom_var, width=40, height=22,
            placeholder_text="Mbps", font=theme.font(10),
        )
        entry.pack(side="left", padx=2, pady=2)
        ctk.CTkButton(
            self.limit_row,
            text="Set",
            width=36,
            height=22,
            fg_color=theme.ACCENT_DIM,
            hover_color=theme.ACCENT,
            font=theme.font(10),
            command=self._apply_custom_limit,
        ).pack(side="left", padx=2, pady=2)

    def _toggle_limit_row(self) -> None:
        self._limit_expanded = not self._limit_expanded
        if self._limit_expanded:
            self.limit_row.pack(fill="x", padx=10, pady=(2, 4))
            self.geometry("360x200")
        else:
            self.limit_row.pack_forget()
            self.geometry("360x168")

    def _apply_limit_mbps(self, mbps: float) -> None:
        bps = mbps_to_bps(mbps)
        self.engine.set_item_speed_limit(self.item_id, bps)
        self.limit_btn.configure(text="⚡ ∞" if bps == 0 else f"⚡ {int(mbps)}M")

    def _apply_custom_limit(self) -> None:
        raw = self._custom_var.get().strip()
        try:
            mbps = float(raw) if raw else 0.0
        except ValueError:
            return
        self._apply_limit_mbps(mbps)

    def _on_configure(self, _event=None) -> None:
        # Debounce-save geometry for pin-position QoL
        try:
            geo = self.geometry()
            self.after(400, lambda g=geo: _save_position(self.item_id, g))
        except Exception:
            pass

    def _close_only(self) -> None:
        self._stop_pulse()
        try:
            _save_position(self.item_id, self.geometry())
        except Exception:
            pass
        _OPEN.pop(self.item_id, None)
        self.destroy()

    def _toggle_pause(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        if item.status == DownloadStatus.COMPLETED.value:
            return
        if item.status == DownloadStatus.DOWNLOADING.value:
            self.engine.pause(self.item_id)
        elif item.status in (
            DownloadStatus.PAUSED.value,
            DownloadStatus.FAILED.value,
            DownloadStatus.QUEUED.value,
            DownloadStatus.CANCELLED.value,
        ):
            self.engine.resume(self.item_id)

    def _stop(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item or item.status == DownloadStatus.COMPLETED.value:
            return
        self.engine.cancel(self.item_id)

    def _restart(self) -> None:
        self.engine.restart(self.item_id)

    def _copy_url(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(item.url)
        except Exception:
            pass

    def _open_folder(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        path = Path(item.final_path)
        folder = path.parent if path.exists() else Path(item.save_path)
        self._reveal(folder, select_file=False)

    def _open_file(self) -> None:
        item = self.engine.db.get_download(self.item_id)
        if not item:
            return
        path = Path(item.final_path)
        if path.exists():
            self._reveal(path, select_file=True)

    def _reveal(self, path: Path, select_file: bool = False) -> None:
        try:
            system = platform.system()
            if system == "Windows":
                if select_file and path.is_file():
                    subprocess.run(["explorer", "/select,", str(path)], check=False)
                else:
                    os.startfile(str(path if path.is_dir() else path.parent))  # type: ignore[attr-defined]
            elif system == "Darwin":
                if select_file and path.is_file():
                    subprocess.run(["open", "-R", str(path)], check=False)
                else:
                    subprocess.run(["open", str(path if path.is_dir() else path.parent)], check=False)
            else:
                target = str(path if path.is_dir() else path.parent)
                subprocess.run(["xdg-open", target], check=False)
        except Exception:
            pass

    def _ensure_seg_pills(self, n: int) -> None:
        n = max(0, min(16, int(n)))
        if len(self._seg_pills) == n:
            return
        for p in self._seg_pills:
            try:
                p.destroy()
            except Exception:
                pass
        self._seg_pills = []
        for _ in range(n):
            pill = ctk.CTkFrame(
                self.seg_pills_frame, width=10, height=8, corner_radius=2,
                fg_color=theme.BG_HOVER,
            )
            pill.pack(side="left", padx=1)
            pill.pack_propagate(False)
            self._seg_pills.append(pill)

    def _update_seg_pills(self, total: int, active: int, status: str) -> None:
        self._ensure_seg_pills(total)
        if total <= 0:
            self.seg_lbl.configure(text="Seg —")
            return
        # Approximate done = total - active while downloading; all done when completed
        if status == DownloadStatus.COMPLETED.value:
            done = total
            active = 0
        elif status == DownloadStatus.DOWNLOADING.value:
            done = max(0, total - max(0, active))
        else:
            done = 0
            active = 0
        self.seg_lbl.configure(text=f"Seg {min(done + active, total)}/{total}")
        for i, pill in enumerate(self._seg_pills):
            if i < done:
                pill.configure(fg_color=theme.SUCCESS)
            elif i < done + active:
                pill.configure(fg_color=theme.ACCENT)
            else:
                pill.configure(fg_color=theme.BG_HOVER)

    def _start_pulse(self) -> None:
        if self._pulse_on:
            return
        self._pulse_on = True
        self._pulse_step()

    def _stop_pulse(self) -> None:
        self._pulse_on = False
        if self._pulse_after is not None:
            try:
                self.after_cancel(self._pulse_after)
            except Exception:
                pass
            self._pulse_after = None
        try:
            self.bar.configure(progress_color=theme.ACCENT)
            self.activity.configure(text_color=theme.ACCENT_DIM, text="●")
        except Exception:
            pass

    def _pulse_step(self) -> None:
        if not self._pulse_on or not self.winfo_exists():
            return
        color = _PULSE_COLORS[self._pulse_idx % len(_PULSE_COLORS)]
        self._pulse_idx += 1
        try:
            self.bar.configure(progress_color=color)
            self.activity.configure(
                text_color=color,
                text="●" if self._pulse_idx % 2 else "○",
            )
        except Exception:
            return
        self._pulse_after = self.after(280, self._pulse_step)

    def _set_completed_buttons(self, completed: bool, failed: bool = False) -> None:
        # Show/hide pause vs open/restart
        if completed:
            try:
                self.pause_btn.pack_forget()
            except Exception:
                pass
            try:
                self.stop_btn.pack_forget()
            except Exception:
                pass
            if not self.open_btn.winfo_ismapped():
                self.open_btn.pack(side="left", padx=(0, 4))
            if not self.restart_btn.winfo_ismapped():
                self.restart_btn.pack(side="left", padx=(0, 4))
        else:
            try:
                self.open_btn.pack_forget()
            except Exception:
                pass
            if failed:
                if not self.restart_btn.winfo_ismapped():
                    self.restart_btn.pack(side="left", padx=(0, 4))
            else:
                try:
                    self.restart_btn.pack_forget()
                except Exception:
                    pass
            if not self.pause_btn.winfo_ismapped():
                self.pause_btn.pack(side="left", padx=(0, 4), before=self.limit_btn)
            if not self.stop_btn.winfo_ismapped():
                self.stop_btn.pack(side="left", padx=(0, 4))

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
        segs = int(runtime.get("segments") or item.segments or 0)
        active = int(runtime.get("active_segments") or 0)
        if item.status != DownloadStatus.DOWNLOADING.value:
            speed = 0.0
            eta = None
            if item.status != DownloadStatus.COMPLETED.value:
                active = 0

        wall = format_eta_wallclock(eta)
        eta_txt = format_eta(eta)
        if wall:
            eta_txt = f"{eta_txt} ({wall})"
        lim = item.speed_limit
        lim_txt = ""
        if lim > 0:
            mbps = lim * 8 / 1_000_000
            lim_txt = f"  ·  lim {mbps:.1f}M"
            self.limit_btn.configure(text=f"⚡ {mbps:.0f}M")
        else:
            self.limit_btn.configure(text="⚡ Limit")

        self.meta_lbl.configure(
            text=f"{format_speed(speed)}  ·  ETA {eta_txt}  ·  {item.status}{lim_txt}"
        )
        self._update_seg_pills(segs, active, item.status)

        if item.status == DownloadStatus.DOWNLOADING.value:
            self.pause_btn.configure(text="⏸ Pause", state="normal")
            self._start_pulse()
            self._set_completed_buttons(False)
        elif item.status == DownloadStatus.COMPLETED.value:
            self._stop_pulse()
            self.bar.configure(progress_color=theme.SUCCESS)
            self._set_completed_buttons(True)
        elif item.status == DownloadStatus.FAILED.value:
            self._stop_pulse()
            self.pause_btn.configure(text="▶ Resume", state="normal")
            self._set_completed_buttons(False, failed=True)
        else:
            self._stop_pulse()
            self.pause_btn.configure(text="▶ Resume", state="normal")
            self._set_completed_buttons(False)

        self._last_status = item.status
        self.after(400, self._tick)
