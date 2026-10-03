# platform/platform_service.py
"""
PlatformService — runtime detection of Windows environment.

Responsibilities (spec §4):
  * Windows version / build / architecture
  * Runtime environment (Python, frozen vs. source)
  * Basic hardware capabilities
  * Well-known OS directories (delegated to PathManager)

This module NEVER builds application paths.
It only reports facts about the current machine.
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PlatformInfo:
    os_name: str              # "Windows"
    os_release: str           # "10", "11"
    os_version: str           # full build string
    architecture: str         # "AMD64", "ARM64", ...
    python_version: str
    python_implementation: str
    is_frozen: bool           # True if running from a frozen bundle
    executable: str           # sys.executable
    is_windows: bool


class PlatformService:
    """Stateless platform reporter. Safe to instantiate repeatedly."""

    def __init__(self) -> None:
        self._info = self._detect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def info(self) -> PlatformInfo:
        return self._info

    def is_windows(self) -> bool:
        return self._info.is_windows

    def is_64bit(self) -> bool:
        return "64" in self._info.architecture

    def local_appdata_dir(self) -> Path:
        """
        Dynamically resolve %LOCALAPPDATA%.
        Falls back to the user profile only when the env var is missing.
        Never hardcode a drive letter or username.
        """
        raw = os.environ.get("LOCALAPPDATA")
        if raw:
            return Path(raw)
        # Conservative fallback — still user-relative, not machine-hardcoded.
        return Path.home() / "AppData" / "Local"

    def roaming_appdata_dir(self) -> Path:
        raw = os.environ.get("APPDATA")
        if raw:
            return Path(raw)
        return Path.home() / "AppData" / "Roaming"

    def temp_dir(self) -> Path:
        raw = os.environ.get("TEMP") or os.environ.get("TMP")
        if raw:
            return Path(raw)
        return Path.home() / "AppData" / "Local" / "Temp"

    def user_home_dir(self) -> Path:
        return Path.home()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _detect() -> PlatformInfo:
        return PlatformInfo(
            os_name=platform.system(),
            os_release=platform.release(),
            os_version=platform.version(),
            architecture=platform.machine(),
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            is_frozen=bool(getattr(sys, "frozen", False)),
            executable=sys.executable,
            is_windows=platform.system().lower() == "windows",
        )


# ----------------------------------------------------------------------
# Process-wide singleton accessor (thin, no global mutable state)
# ----------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_platform_service() -> PlatformService:
    return PlatformService()