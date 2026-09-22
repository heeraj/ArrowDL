# Changelog

All notable changes to ArrowDL are documented here.

## [1.2.0] — 2026-09-22

### Mini window, Resume vs Restart, drag-select

**Fixed**
- `engine.resume(id)` is a **no-op** when status is `completed` (Resume no longer restarts finished downloads)
- Main list ▶ Start / context Resume / mini Pause↔Resume only act on paused / failed / cancelled / queued
- Distinct **Restart (re-download)** path: deletes `.arrowdl.part` / `.arrowdl.meta` / final file, resets progress, re-queues

**Added**
- Mini window (~360×168): stronger Pause↔Resume, segment pills (`Seg N/M`), progress pulse while downloading, ⚡ Limit chips (Unlimited / 1–5 Mbps + custom), Open folder, Copy URL, Stop; on completed → Open file + Restart
- Mini window positions remembered per id (`mini_positions.json` in app data)
- Drag multi-select over list rows (paint/range); Ctrl+click and Shift+click unchanged
- Selection bar + context menu: **Restart** for completed/failed (never labeled Resume)
- Keyboard: Space pause/resume · Delete · Ctrl+A unfinished · Ctrl+R restart completed · Enter open mini
- Finish flash on row when a download completes
- Segment activity strip under main-list progress while downloading
- ETA wall-clock (“done ~3:42 PM”) alongside relative ETA
- Smart clipboard chip: “Add URL?” when an http(s) URL lands on the clipboard
- Settings: optional complete sound (Windows `winsound`, **off by default**)

**Deferred**
- Raw download throughput vs IDM (kept for a later sprint)

## [0.1.1] / v1.1 — 2026-09-22

### Stability & UI polish

**Fixed**
- Downloads no longer fail on a single network blip: per-segment and single-stream reads retry with exponential backoff (0.5s→8s, up to ~10 attempts), resuming Range from the current offset
- Meta (`.arrowdl.meta`) flushes more often (~every 2 MB or 2s) so resume survives crashes
- Engine auto-requeues a worker that dies while status is still `downloading` (bounded, max 3 engine restarts)
- List refresh no longer rebuilds every 500ms blindly — in-place progress/speed updates preserve multi-select

**Added**
- Compact minimalist layout (~1000×560): tighter toolbar (~40px), sidebar (~140px), row height ~30px
- Shared `COL_SPECS` so Size / Progress / Speed / ETA headers and cells stay aligned (right-align for Size/Speed/ETA)
- Multi-select: Ctrl+click toggle, Shift+click range; selection action bar (▶ Start, ⏸ Pause, ⏹ Stop, 🗑 Delete)
- Auto-arrange: unfinished downloads first when filter is All; thin “Completed” separator
- Mini download window (always-on-top): double-click downloading/paused, or right-click → Open mini window
- System tray (pystray + Pillow): close/minimize to tray; menu Show / Pause unfinished / Resume unfinished / Exit
- Settings: “Minimize / close to tray”
- Status bar shows Segments and Retries for the active download

**Known limitations**
- Tray may be unavailable on headless Linux CI (app falls back to quit-on-close)
- No browser extension / torrents yet

## [0.1.0-alpha] — 2026-09-22

### Early build — first public alpha

**Added**
- Multi-segment HTTP(S) downloads with resume (Range) and single-connection fallback
- Queue with max concurrent downloads
- Pause / resume / cancel (per item and all)
- Global and per-download speed limits
- Optional start-at scheduler
- Categories: Software, Docs, Videos, Other
- SQLite history and settings
- Dark customtkinter UI: main list, Add Download, Settings, delete-with-files prompt
- MIT license, Privacy Policy, Disclaimer

**Known limitations**
- No browser extension / click-to-capture yet (planned v2)
- No built-in video site extractors
- No system tray yet (v1.1)
- Windows `.exe` / Setup installer is early; prefer Python run if the packaged build misbehaves
- Not yet digitally signed — SmartScreen may warn on first run

**Install options**
1. Run from source (Python 3.11+) — most reliable for alpha
2. Portable / Setup build attached to the GitHub Release when available
