# Native module (`module.pyd`)

The AIProduct native layer is a single compiled pybind11 module:
`native/module.pyd`.

## Where it comes from

`module.pyd` is built in a separate Visual Studio 2026 Community
C++ project. That project contains all `.cpp` / `.h` sources for
every native tool group. This Python project only receives the
compiled artifact.

Source of truth for the native code: (point to wherever your VS
project lives — a separate repo, a sibling folder, etc.)

## Why it is not committed to git

- It is a Windows binary (`.pyd` = DLL with a Python-friendly name).
- It is tied to the exact Python version and architecture it was
  built against (3.11, x64 for this project).
- Rebuilding from source is the correct way to obtain it.

`.gitignore` therefore excludes it.

## What the Python project expects

- Path: `AIProduct/native/module.pyd`
- Python: 3.11, x64 (must match the interpreter that built it)
- pybind11: built against the pybind11 version pinned in
  `requirements-dev.txt`
- Exposed symbols: see `native/bridge/native_bridge.py` — the
  bridge documents every submodule and function it calls.

## How to build it (VS 2026 Community)

1. Open the native project in Visual Studio 2026 Community.
2. Configuration: Release | x64.
3. Verify project properties:
   - C/C++ → General → Additional Include Directories:
     - pybind11 include path (from `python -m pybind11 --includes`)
     - Python 3.11 include path (e.g. `C:\Program Files\Python311\include`)
   - C/C++ → Language → C++ Language Standard: `ISO C++17 Standard (/std:c++17)`
   - Linker → General → Output File: `$(OutDir)module.pyd`
   - Linker → Input → Additional Dependencies: `python311.lib` (match your Python version)
   - Linker → General → Additional Library Directories: Python 3.11 `libs` folder
4. Build (Ctrl+Shift+B).
5. Copy the resulting `module.pyd` to `AIProduct/native/module.pyd`.

## What happens if it is missing

The application still runs. `NativeBridge` reports unavailable at
bootstrap (a log line, not an error), and any native-requiring tool
call fails honestly with a clear message. Nothing crashes.

Log lines when present:

    ... | INFO | aiproduct.native.bridge | native module loaded   path=... version=0.1.0
    ... | INFO | aiproduct.bootstrap     | native bridge ready    native_version=0.1.0 capabilities=['notepad.basic', 'notepad.helpers']

Log lines when absent:

    ... | INFO | aiproduct.native.bridge | native module not loaded   reason=no compiled module found under ...
    ... | INFO | aiproduct.bootstrap     | native bridge not available reason=no compiled module found under ...

## Adding a new native tool group

1. In the VS project, add `<group>.h` + `<group>.cpp`.
2. In `module.cpp`, `#include "<group>.h"` and call `register_<group>(m);`
   inside `PYBIND11_MODULE`.
3. Add the group's capability flag to the `CAPABILITIES` dict in `module.cpp`.
4. Rebuild `module.pyd`.
5. Replace `AIProduct/native/module.pyd`.
6. Restart the app — no Python changes required for discovery. To
   actually use the new group, extend `NativeBridge` if needed and
   then add a tool.

## Verification

After pasting `module.pyd`, run:

    python -c "from native import NativeBridge; from pathlib import Path; nb = NativeBridge(Path('.').resolve()); print('available:', nb.is_available()); print('version:', nb.native_version()); print('caps:', nb.capabilities())"

Expected when present:

    available: True
    version: 0.1.0
    caps: {'notepad.helpers': True, 'notepad.basic': True}

Expected when absent:

    available: False
    version: None
    caps: {}

## Architecture rules (do not break)

- No Python file imports `module` directly. Everything goes through
  `NativeBridge`.
- No raw Win32 handles (HWND, HANDLE, HPROCESS) are returned to
  Python. Only counts, booleans, and opaque identifiers.
- No unrestricted shell execution, no `send_input`, no keyboard /
  mouse synthesis exposed from the native module in this phase.
- The native layer never makes policy decisions. Permission levels,
  policies, schema validation, and audit all live on the Python side.
  C++ only exposes bounded, structured operations.
- Every native function returns a `py::dict` with at least
  `{"ok": bool, "error_code": str, "error": str}`. Native code does
  not raise exceptions across the boundary for expected failures.