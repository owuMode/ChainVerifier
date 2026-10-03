# scripts/debug_tool.py
"""
Debug a single tool package. Prints the exact rejection reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    tool_name = sys.argv[1] if len(sys.argv) > 1 else "filesystem_read_many"
    tool_dir = _PROJECT_ROOT / "tools" / tool_name
    manifest = tool_dir / "manifest.yaml"

    print(f"Tool dir: {tool_dir}")
    print(f"Manifest: {manifest}")
    print(f"Exists:   {tool_dir.exists()}")
    print()

    try:
        from tools.registry.discovery import _load_tool_package
        _load_tool_package(tool_dir, manifest)
        print("OK: tool loaded successfully.")
        return 0
    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())