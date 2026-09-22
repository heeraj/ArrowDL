# Changelog

All notable changes to ArrowDL are documented here.

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
