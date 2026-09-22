# ArrowDL

**Fast, simple multi-segment downloads for Windows.**

[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-v1.2-teal.svg)](CHANGELOG.md)
[![Downloads](https://img.shields.io/github/downloads/heeraj/ArrowDL/total.svg)](https://github.com/heeraj/ArrowDL/releases)

ArrowDL is a lightweight **IDM-style download manager**: split files into segments, queue jobs, limit speed, schedule starts, and keep history locally — without accounts or cloud lock-in.

> **v1.2.** Mini window + Resume/Restart fix + drag-select. Still expect polish. Read the [Disclaimer](DISCLAIMER.md) and [Privacy Policy](PRIVACY.md) before installing.

---

## Why ArrowDL?

| | |
|---|---|
| **Multi-segment** | Parallel HTTP ranges for faster transfers when the server allows it |
| **Queue + limits** | Cap concurrent jobs and bandwidth so your connection stays usable |
| **Scheduler** | Start big downloads later (overnight / off-peak) |
| **Categories** | Software, Docs, Videos, Other → tidy default folders |
| **Local-first** | SQLite on your PC — no login, no phone-home analytics in early builds |
| **Clear delete** | Remove from list only, or delete the file from disk too |

---

## Download (releases)

**Latest early build:** [Releases](https://github.com/heeraj/ArrowDL/releases)

| Package | Who it’s for |
|---------|----------------|
| **Setup.exe** (when published) | Normal Windows install |
| **Portable .zip** (when published) | No installer — unpack and run |
| **Source** | Developers / most reliable for alpha |

Windows may show a SmartScreen warning on unsigned early builds — that is expected until code signing is added. Prefer verifying the checksums on the Release page.

---

## Quick start (from source)

**Requirements:** Windows 10/11, Python 3.11+

```bat
git clone https://github.com/heeraj/ArrowDL.git
cd ArrowDL
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
run.bat
```

---


### Tips (v1.2)
- **Multi-select:** Click-drag to paint-select rows; Ctrl+click toggle, Shift+click range. Selection bar: Start / Restart / Pause / Stop / Delete.
- **Resume vs Restart:** Resume never restarts a completed file. Use **Restart** (or Ctrl+R) to re-download from scratch.
- **Mini window:** Double-click an active download (or Enter / right-click → Open mini window). Pause↔Resume, segment pills, ⚡ Limit chips, Open folder / Copy URL / Stop; completed shows Open file + Restart.
- **Shortcuts:** Space = pause/resume · Delete · Ctrl+A = select unfinished · Ctrl+R = restart completed · Enter = mini window.
- **Clipboard:** When you copy an http(s) URL, a small “Add URL?” chip appears.
- **Tray:** Closing the main window hides to the tray by default (Settings → Minimize / close to tray). Exit from the tray menu to quit and stop the engine.

## Features

### Available now (v1.1)
- Multi-segment HTTP(S) download + resume with retry/backoff on network blips
- Pause / resume / cancel (one, multi-select, or all)
- Global & per-download speed limit
- Queue with max concurrent downloads
- Schedule start time
- Categories & default folders
- Multi-select list + selection action bar; unfinished-first grouping
- Mini progress window (always-on-top) per download
- System tray: close to tray, pause/resume unfinished, Exit
- Delete list entry ± delete files on disk
- Compact dark customtkinter UI

### Coming later
- Browser extension (catch clicked links)
- Page media / video URL detection
- Start with Windows (setting saved; registry wiring later)
- Signed installer & auto-update

### Not planned for early versions
- Torrents
- Bypassing DRM / paywalled streams
- Built-in malware scanning (use your AV)

---

## Privacy & legal

- [Privacy Policy](PRIVACY.md) — local-first; no accounts in early builds  
- [Disclaimer](DISCLAIMER.md) — AS IS; you are responsible for what you download  
- [License](LICENSE) — MIT  
- [Changelog](CHANGELOG.md)

ArrowDL is an independent project and is **not** affiliated with Internet Download Manager (IDM) or Tonec Inc.

---

## Project layout

```
ArrowDL/
  README.md
  LICENSE
  PRIVACY.md
  DISCLAIMER.md
  CHANGELOG.md
  requirements.txt
  run.bat / run.sh
  docs/
  arrowdl/          # application package
```

App data (Windows): `%LOCALAPPDATA%\ArrowDL`  
Default downloads: `%USERPROFILE%\Downloads\ArrowDL\{Software,Docs,Videos,Other}`

---

## Contributing

Issues and PRs welcome: https://github.com/heeraj/ArrowDL/issues  

Please don’t submit site-specific DRM circumvention tools.

---

## Support the project

Star the repo, try an early build, and report bugs with OS version + steps to reproduce. That is the fastest path to a polished 1.0.
