# platform/path_manager.py
"""
PathManager — the single authority for filesystem locations (spec §3, §4, §5, §6).

Rules:
  * No other module may build application paths.
  * Every path is resolved dynamically per user, per machine.
  * Nothing here is hardcoded to a drive letter, username, or install dir.

Directory layout under the resolved app-data root:

    <AppDataRoot>/
        database/
        logs/
        cache/
        temp/
        models/
        downloads/
        backups/
        runtime/
        state/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sysinfo.platform_service import PlatformService


# The application identity string. Changing this changes the on-disk root.
# This is NOT a machine-specific path — it is a stable product identifier.
_APP_DIR_NAME = "AIProduct"


@dataclass(frozen=True)
class Paths:
    root: Path
    database_dir: Path
    logs_dir: Path
    cache_dir: Path
    temp_dir: Path
    models_dir: Path
    downloads_dir: Path
    backups_dir: Path
    runtime_dir: Path
    state_dir: Path


class PathManager:
    """
    Resolves all application-owned paths.

    Custom storage roots are supported via `set_custom_root()` — but they
    must be applied BEFORE any subsystem resolves a path (StorageManager
    enforces this ordering — see storage_manager.py).
    """

    def __init__(self, platform_service: PlatformService) -> None:
        self._platform = platform_service
        self._custom_root: Optional[Path] = None
        self._cached: Optional[Paths] = None

    # ------------------------------------------------------------------
    # Root resolution
    # ------------------------------------------------------------------
    def default_root(self) -> Path:
        """
        Automatic per-user root. Does not require user input.
        Uses %LOCALAPPDATA%\\AIProduct on Windows.
        """
        return self._platform.local_appdata_dir() / _APP_DIR_NAME

    def root(self) -> Path:
        return self._custom_root or self.default_root()

    def set_custom_root(self, path: Path) -> None:
        """
        Set an explicit storage root. Must be called before any path is
        materialized; StorageManager enforces this contract.
        """
        resolved = Path(path).expanduser().resolve()
        self._custom_root = resolved
        self._cached = None

    def clear_custom_root(self) -> None:
        self._custom_root = None
        self._cached = None

    def is_custom(self) -> bool:
        return self._custom_root is not None

    # ------------------------------------------------------------------
    # Materialized paths
    # ------------------------------------------------------------------
    def paths(self) -> Paths:
        if self._cached is None:
            root = self.root()
            self._cached = Paths(
                root=root,
                database_dir=root / "database",
                logs_dir=root / "logs",
                cache_dir=root / "cache",
                temp_dir=root / "temp",
                models_dir=root / "models",
                downloads_dir=root / "downloads",
                backups_dir=root / "backups",
                runtime_dir=root / "runtime",
                state_dir=root / "state",
            )
        return self._cached

    # Convenience accessors ------------------------------------------------
    def database_file(self) -> Path:
        return self.paths().database_dir / "app.sqlite"

    def log_file(self, name: str = "app.log") -> Path:
        return self.paths().logs_dir / name

    def cache_file(self, name: str) -> Path:
        return self.paths().cache_dir / name