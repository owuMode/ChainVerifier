<div align="center">

# ChainVerifier

**A modern pointer chain verifier and memory scanner for Windows.**

Find, verify and manage static pointer chains with a dark, professional interface.

[![Download](https://img.shields.io/badge/Download-Latest-blue?style=for-the-badge&logo=windows)](https://github.com/owuMode/ChainVerifier/releases/latest)
[![Website](https://img.shields.io/badge/Website-owumode.store-green?style=for-the-badge&logo=googlechrome)](https://owumode.store)
[![Telegram](https://img.shields.io/badge/Telegram-Join%20Chat-2CA5E0?style=for-the-badge&logo=telegram)](https://t.me/owumode_chat)
[![License](https://img.shields.io/badge/License-Free%20(Proprietary)-orange?style=for-the-badge)]()

</div>

---

##  About

**ChainVerifier** is a Windows tool for reverse engineers, game modders, and security researchers who work with pointer chains.

It lets you:

- **Verify** static pointer chains against any running process
- **Scan** memory with five different modes (AOB, Range, Unknown, String, Pointer)
- **Freeze** values in bulk
- **Manage** chains with a modern dark UI

Built with a **C++ backend** for speed and a **PyQt5 frontend** for a clean, professional interface.

---

##  Features

| Feature | Description |
|---------|-------------|
| **Chain Verification** | Add unlimited pointer chains and resolve them live. Batch verify millions of chains in under 1 second. Color-coded match / no-match / error results. |
| **5 Scanning Modes** | AOB pattern scan (with wildcards), range scan, unknown value scan, string scan (ASCII + UTF-16), and full pointer scan. Auto-detects 32-bit / 64-bit processes. |
| **Built-in Tools** | Bulk freeze manager with visual indicator, hex viewer/editor, Cheat Engine pointer map import (auto-detects format), Send-to-Chains shortcut. |
| **Custom Dark UI** | Modern dark theme with splash screen. Customizable fonts, colors, row height, panel visibility. Real-time value updates with highlight on change. |
| **C++ Performance** | Multi-threaded parallel scanning, chunked region scanning (1 MB chunks), adaptive threading. Battery Saver / Balanced / Performance / Extreme modes. |
| **Auto-Update** | Silent startup check notifies you when a newer version is available. One click to download. Windows native notifications with logo. |
| **Encrypted Save Files** | Chains saved as `.owu` files with XOR + SHA-256 checksum + zlib compression. Portable and tamper-resistant. Auto-save with backups. |
| **Undo / Redo + Hotkeys** | C++ ring buffer undo/redo and global hotkeys (`Ctrl+Alt+A` / `S` / `F` / `H`). Threaded file I/O keeps the UI responsive. |
| **Portable** | Download the ZIP, extract, and run. No installer. |

---

##  Download & Install

### Requirements

- **OS:** Windows 10 / 11 (64-bit)
- **RAM:** 4 GB minimum (8 GB recommended)
- **Storage:** 150 MB free space
- **Permissions:** Administrator (required for attaching to processes)
- **Display:** 1100 × 720 or higher

### Installation

1. **Download** the latest release:  
   [**ChainVerifier-v2.9.1.zip**](https://github.com/owuMode/ChainVerifier/releases/download/v2.9.1/ChainVerifier_v2.9.1-Windows-x64.zip)

2. **Extract** the ZIP to any folder of your choice.

3. **Run** `ChainVerifier.exe` as Administrator.

> **No Python installation required.** The EXE is fully self-contained.

---

##  How to Use

### Basic Workflow

1. **Launch** ChainVerifier as Administrator.
2. **Attach** to a running process (Tools → Attach to Process).
3. **Add** pointer chains (Chains Editor → Add).
4. **Verify** against a target address (enter the final address, click Verify).
5. **Scan** memory with any of the 5 modes (Scan menu).

### Hotkeys

| Hotkey | Action |
|--------|--------|
| `Ctrl+Alt+A` | Attach to Process |
| `Ctrl+Alt+S` | Verify Chains |
| `Ctrl+Alt+F` | Open Freeze Manager |
| `Ctrl+Alt+H` | Open Hex Viewer |

---

## ⚠️ Important Notes

- **Administrator required** — To read/write another process's memory, Windows requires admin privileges.
- **Antivirus** — Some AV tools flag any memory-editing tool as a false positive. The source code is public on GitHub. Add an exclusion if needed.
- **SmartScreen** — Because this build is unsigned, Windows SmartScreen may show a warning. Click **"More info" → "Run anyway"**.
- **Anti-Cheat** — Games protected by EAC, BattlEye, or Vanguard will block memory access. This is expected.

---

##  Changelog

### v2.9.1 (2026-10-11)

**Fixed**
- 32-bit & 64-bit support — now works with both architectures
- Faster startup — update check no longer freezes the interface
- Fixed pointer verification failing on 32-bit processes
- Fixed UI freeze during update check

**Changed**
- General stability improvements
- Improved build compatibility

### v2.0.0 (2026-09-28)

- Full C++ backend for pointer scanning and chain verification
- Batch verify — millions of chains in under 1 second
- Single portable EXE — no _internal folder required
- Custom dark-themed UI
- Bulk freeze with visual indicator
- Real-time value update with highlight on change
- Global hotkeys
- Auto-save with backups
- File logging with rotation
- Undo/redo with C++ ring buffer

### v1.0.0 (2026-09-23)

- Initial public release
- Chain verification with live value updates
- AOB, Range, Unknown, String, Pointer scans
- Freeze manager, Hex viewer/editor
- Cheat Engine .sqlite pointer map import

[**View full changelog →**](CHANGELOG.md)

---

## 🐞 Found a Bug?

Open an issue on [GitHub Issues](https://github.com/owuMode/ChainVerifier/issues) with:

- Windows version
- Steps to reproduce
- Screenshot (if applicable)

---

## 💬 Community

- **Telegram:** [t.me/owumode_chat](https://t.me/owumode_chat)
- **Website:** [owumode.store](https://owumode.store)

---

## 📜 License

**Free (Proprietary).** See the repository for details.

---

<div align="center">

**Made with ❤️ by OwuMode**

</div>
