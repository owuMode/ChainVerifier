# platform/storage_manager.py
"""
StorageManager — creates, validates, and migrates the on-disk layout (spec §4, §8).

Rules:
  * Directory creation is lazy and idempotent.
  * A custom storage root must be validated BEFORE any subsystem writes.
  * Migration sequence (spec §8):
        validate → permissions → space → create → (caller moves DB safely)
        → verify → update config → reopen → verify → cleanup old
    We expose `prepare_root()` and `validate_root()`; the actual data
    movement is orchestrated by the caller that owns the DB handle.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sysinfo.path_manager import PathManager


class StorageError(Exception):
    """Raised when a storage root cannot be validated or prepared."""


@dataclass(frozen=True)
class StorageCheckResult:
    ok: bool
    reason: str = ""


class StorageManager:
    def __init__(self, path_manager: PathManager) -> None:
        self._paths = path_manager
        self._initialized = False

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate_root(self, root: Path) -> StorageCheckResult:
        """
        Validate that `root` is a viable storage location.
        Does NOT create anything.
        """
        try:
            root = Path(root).expanduser()
        except Exception as exc:  # pragma: no cover - defensive
            return StorageCheckResult(False, f"invalid path: {exc}")

        # Must be absolute so behaviour is stable across cwd changes.
        if not root.is_absolute():
            return StorageCheckResult(False, "path must be absolute")

        # If it exists, it must be a writable directory.
        if root.exists():
            if not root.is_dir():
                return StorageCheckResult(False, "path exists but is not a directory")
            if not os.access(root, os.W_OK):
                return StorageCheckResult(False, "directory is not writable")
            return StorageCheckResult(True)

        # If it does not exist, the nearest existing parent must be writable.
        parent = root.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.exists() or not os.access(parent, os.W_OK):
            return StorageCheckResult(False, "parent directory is not writable")

        return StorageCheckResult(True)

    def free_space_bytes(self, root: Path) -> int:
        """Return free space at `root` (or its nearest existing ancestor)."""
        target = Path(root)
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
        return usage.free

    # ------------------------------------------------------------------
    # Preparation
    # ------------------------------------------------------------------
    def prepare_default(self) -> Path:
        """
        Create the default application-data tree. Idempotent.
        Returns the resolved root.
        """
        root = self._paths.root()
        check = self.validate_root(root)
        if not check.ok:
            raise StorageError(f"invalid storage root: {check.reason}")
        self._create_tree(root)
        self._initialized = True
        return root

    def prepare_custom(self, root: Path) -> Path:
        """
        Validate and materialize a custom storage root, then switch
        PathManager to it. Caller is responsible for actually moving
        existing user data (see spec §8 sequence).
        """
        check = self.validate_root(root)
        if not check.ok:
            raise StorageError(f"invalid custom root: {check.reason}")

        resolved = Path(root).expanduser().resolve()
        self._paths.set_custom_root(resolved)
        self._create_tree(resolved)
        self._initialized = True
        return resolved

    def is_initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _create_tree(root: Path) -> None:
        # Create only directories that are actually needed.
        # Lazy subsystem-level creation is still preferred at higher layers.
        for name in (
            "database",
            "logs",
            "cache",
            "temp",
            "models",
            "downloads",
            "backups",
            "runtime",
            "state",
        ):
            (root / name).mkdir(parents=True, exist_ok=True)