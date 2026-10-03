# native/bridge/native_bridge.py
"""
NativeBridge — the single Python-side access point to module.pyd
(spec §11, §12).

Design:
  * No other module imports `module` (the .pyd) directly.
  * NativeBridge detects the .pyd at a resolved path, loads it once,
    and exposes a small stable interface.
  * If the .pyd is missing or fails to load, NativeBridge reports
    unavailable. Callers must check `is_available()`.
  * Every native call returns a plain dict. Native code never raises
    across the boundary for expected failures.
  * NativeBridge does not import anything from providers, tools,
    security, or GUI. It is a leaf.

Layout assumption:
    native/module.pyd            (build output)
    native/bridge/native_bridge.py
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from applog.logger import get_logger

log = get_logger("native.bridge")


class NativeBridgeError(Exception):
    """Raised only for programming errors, never for native failures."""


class NativeBridge:
    """
    Thin, stable wrapper over `module.pyd`.

    Callers use:
        nb = NativeBridge(project_root)
        if nb.is_available():
            result = nb.notepad_basic.is_running()
    """

    def __init__(self, project_root: Path) -> None:
        self._project_root = Path(project_root)
        self._module: Optional[ModuleType] = None
        self._load_error: Optional[str] = None
        self._try_load()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        return self._module is not None

    def load_error(self) -> Optional[str]:
        return self._load_error

    def native_version(self) -> Optional[str]:
        if self._module is None:
            return None
        return getattr(self._module, "__native_version__", None)

    def capabilities(self) -> dict[str, bool]:
        if self._module is None:
            return {}
        caps = getattr(self._module, "CAPABILITIES", None)
        if caps is None:
            return {}
        # pybind11 exposes dict-like; coerce to plain dict.
        return {str(k): bool(v) for k, v in dict(caps).items()}

    def supports(self, capability: str) -> bool:
        return bool(self.capabilities().get(capability, False))

    # ------------------------------------------------------------------
    # Tool group accessors
    # ------------------------------------------------------------------
    @property
    def notepad_helpers(self):
        return self._require_submodule("notepad_helpers")

    @property
    def notepad_basic(self):
        return self._require_submodule("notepad_basic")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _try_load(self) -> None:
        native_dir = self._project_root / "native"
        if not native_dir.is_dir():
            self._load_error = f"native directory not found: {native_dir}"
            log.info("native module not loaded", extra={"reason": self._load_error})
            return

        pyd_candidates = [
            native_dir / "module.pyd",
            native_dir / "module.so",
            native_dir / "module.dylib",
        ]
        pyd = next((p for p in pyd_candidates if p.exists()), None)
        if pyd is None:
            self._load_error = f"no compiled module found under {native_dir}"
            log.info("native module not loaded", extra={"reason": self._load_error})
            return

        # Ensure `native/` is importable so `import module` finds the .pyd.
        native_dir_str = str(native_dir)
        if native_dir_str not in sys.path:
            sys.path.insert(0, native_dir_str)

        try:
            # If a stale module is already cached, refresh it.
            if "module" in sys.modules:
                importlib.reload(sys.modules["module"])
                module = sys.modules["module"]
            else:
                module = importlib.import_module("module")
        except Exception as exc:
            self._load_error = f"{type(exc).__name__}: {exc}"
            log.warning("native module failed to load", extra={"reason": self._load_error})
            return

        # Sanity check: the module must expose __native_version__.
        if not hasattr(module, "__native_version__"):
            self._load_error = "loaded module is missing __native_version__"
            log.warning("native module rejected", extra={"reason": self._load_error})
            return

        self._module = module
        log.info(
            "native module loaded",
            extra={
                "path": str(pyd),
                "native_version": getattr(module, "__native_version__", "unknown"),
            },
        )

    def _require_submodule(self, name: str):
        if self._module is None:
            raise NativeBridgeError(
                f"native module is not available: {self._load_error or 'unknown reason'}"
            )
        sub = getattr(self._module, name, None)
        if sub is None:
            raise NativeBridgeError(
                f"native module does not expose submodule {name!r}"
            )
        return sub