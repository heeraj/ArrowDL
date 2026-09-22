# Privacy Policy — ArrowDL

**Effective date:** 22 September 2026  
**Product:** ArrowDL (early / pre-release builds)  
**Publisher:** heeraj (GitHub: [@heeraj](https://github.com/heeraj))  
**Contact:** Open an issue at https://github.com/heeraj/ArrowDL/issues

This policy describes how ArrowDL handles information. ArrowDL is designed as a **local-first** desktop download manager.

## 1. Summary

- ArrowDL runs on **your computer**.
- We do **not** operate ArrowDL cloud accounts.
- Early builds do **not** include analytics, advertising SDKs, or crash-reporting services that phone home.
- Download history and settings stay in a **local SQLite database** on your machine.
- Files you download are saved only where **you** choose (default: your Downloads/ArrowDL folders).

## 2. Information stored on your device

ArrowDL may store locally:

| Data | Purpose |
|------|---------|
| Download URLs, filenames, paths, sizes, status | Queue, resume, history |
| Settings (speed limits, segments, folders, schedule defaults) | App configuration |
| Temporary `.arrowdl.part` / `.arrowdl.meta` files | Multi-segment resume |

**Windows app data location:** `%USERPROFILE%\AppData\Local\ArrowDL`  
**Linux (dev):** `~/.local/share/ArrowDL`

You can delete this folder (and the app) to remove local app data. Deleting completed items can also remove downloaded files if you choose that option in the delete dialog.

## 3. Information we do not collect

Early builds do **not** intentionally collect or transmit:

- Name, email, or account credentials (ArrowDL has no login)
- Advertising IDs or marketing profiles
- Browsing history beyond URLs **you** paste or add into ArrowDL
- Payment information

## 4. Network activity

When you start a download, ArrowDL connects to the **servers hosting that file** (the URL you provided). Those third-party sites have their own privacy policies. ArrowDL does not control what remote servers log (IP address, User-Agent, etc.).

Checking for updates (if added in a later release) will be documented here before shipping.

## 5. Permissions (Windows)

ArrowDL may need permission to:

- Read/write files in folders you select
- Access the network for HTTP(S) downloads
- (Future) Optional “start with Windows” — only if you enable it

## 6. Children

ArrowDL is a general-purpose utility and is not directed at children under 13. Do not use it to download unlawful content.

## 7. Changes

We may update this policy as features change (for example if optional update checks or a browser extension are added). Material changes will be noted in the GitHub release notes and this file’s effective date.

## 8. Contact

Questions about privacy: https://github.com/heeraj/ArrowDL/issues
