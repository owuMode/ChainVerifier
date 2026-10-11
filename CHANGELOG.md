# Changelog

All notable changes to **ChainVerifier** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v2.9.1] — 2026-10-11

### Fixed
- 32-bit & 64-bit support — now works with both architectures
- Faster startup — update check no longer freezes the interface
- Fixed pointer verification failing on 32-bit processes
- Fixed UI freeze during update check

### Changed
- General stability improvements
- Improved build compatibility

---

## [v2.0.0] — 2026-09-28

### Added
- Full C++ backend for pointer scanning and chain verification
- Batch verify — millions of chains in under 1 second
- Single portable EXE — no _internal folder required
- Custom dark-themed UI with modern design
- Bulk freeze with visual indicator
- Multi-select chains with bulk delete
- Real-time value update with highlight on change
- Global hotkeys (Ctrl+Alt+A / S / F / H)
- Custom splash screen
- Windows native notifications with logo
- Auto-save with backups
- File logging with rotation
- Sound notifications (Windows default)
- Taskbar flash on important events
- Undo/redo with C++ ring buffer
- Threaded file I/O (no UI freeze)
- Auto-detect 32-bit / 64-bit processes
- Chunked region scanning (1 MB chunks)
- Multi-threaded parallel scan
- Send to Chains button
- Static filter with `is_static` flag

### Fixed
- UTF-16 string scan false positives
- Atomic `max_results` enforcement
- Freeze int64 precision loss
- Negative offset UB in `follow_chain`
- Freeze dialog hang on stop
- Duplicate hotkey registration
- WNDPROC crash on hotkeys
- Notification UI block

---

## [v1.0.0] — 2026-09-23

### Added
- Initial public release
- Chain verification with live value updates
- AOB, Range, Unknown, String, Pointer scans
- Freeze manager, Hex viewer/editor
- Cheat Engine `.sqlite` pointer map import
- Fully customizable dark UI
- Auto-update check from GitHub
- Encrypted `.owu` save files

---

## Legend

- **Added** — new features
- **Changed** — changes in existing functionality
- **Deprecated** — soon-to-be removed features
- **Removed** — removed features
- **Fixed** — bug fixes
- **Security** — security-related changes

[Unreleased]: https://github.com/owuMode/ChainVerifier/compare/v2.9.1...HEAD
[v2.9.1]: https://github.com/owuMode/ChainVerifier/compare/v2.0.0...v2.9.1
[v2.0.0]: https://github.com/owuMode/ChainVerifier/compare/v1.0.0...v2.0.0
[v1.0.0]: https://github.com/owuMode/ChainVerifier/releases/tag/v1.0.0
