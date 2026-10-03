# gui/web/settings_bridge.py
"""
SettingsBridge — Python <-> JS boundary for the Settings page.

Responsibilities:
  * Report current storage path and whether it is custom.
  * Persist a new custom storage root (applies on restart).
  * Report app/platform info for the About section.
  * Open a native folder picker dialog.

Design:
  * Storage changes are durable (config), applied on next start.
  * No data migration happens here. That is a separate concern
    (StorageManager.migrate in a later phase).
  * The bridge never touches the DB directly — it delegates to
    config, PathManager, and PlatformService.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFileDialog, QApplication

from applog.logger import get_logger

log = get_logger("gui.web.settings_bridge")


class SettingsBridge(QObject):
    """
    Registered with QWebChannel as `settingsbridge`.
    """

    # Emitted when the storage path is changed in config.
    storageChanged = Signal(str)

    def __init__(
        self,
        *,
        config,
        path_manager,
        storage_manager,
        platform_service,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._path_manager = path_manager
        self._storage_manager = storage_manager
        self._platform = platform_service

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    @Slot(result=str)
    def getStorageInfoJson(self) -> str:
        """
        Return current storage info as a JSON string:
          {
            "current_root": "...",
            "is_custom": false,
            "default_root": "...",
            "pending_root": "" or "...",
            "restart_required": true|false
          }
        """
        try:
            current_root = str(self._path_manager.root())
            default_root = str(self._path_manager.default_root())
            is_custom = bool(self._path_manager.is_custom())

            pending = self._config.get("storage.custom_root")
            pending_str = str(pending) if pending else ""

            restart_required = bool(
                pending_str and pending_str != current_root
            )

            payload = {
                "current_root": current_root,
                "default_root": default_root,
                "is_custom": is_custom,
                "pending_root": pending_str,
                "restart_required": restart_required,
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            log.exception("getStorageInfoJson failed")
            return "{}"

    @Slot(result=str)
    def pickFolder(self) -> str:
        """
        Open a native folder picker. Returns the chosen path, or "" if
        the user cancelled.
        """
        try:
            app = QApplication.instance()
            initial = str(self._path_manager.root())

            chosen = QFileDialog.getExistingDirectory(
                None,
                "Choose storage folder",
                initial,
                QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
            )
            if not chosen:
                return ""
            return str(Path(chosen).resolve())
        except Exception:
            log.exception("pickFolder failed")
            return ""

    @Slot(str, result=str)
    def validateStoragePath(self, path: str) -> str:
        """
        Validate a candidate storage path.

        Returns JSON:
          {"ok": true, "reason": ""}
          {"ok": false, "reason": "..."}
        """
        try:
            candidate = Path(str(path)).expanduser()
        except Exception as exc:
            return json.dumps({"ok": False, "reason": f"Invalid path: {exc}"})

        try:
            result = self._storage_manager.validate_root(candidate)
        except Exception as exc:
            log.exception("validate_root raised")
            return json.dumps({"ok": False, "reason": f"{type(exc).__name__}"})

        return json.dumps({
            "ok": bool(result.ok),
            "reason": result.reason or "",
        })

    @Slot(str, result=bool)
    def setCustomStorageRoot(self, path: str) -> bool:
        """
        Save a new custom storage root in config.

        The path is validated first. The change takes effect on the
        next application start. Passing "" clears the custom root and
        reverts to the default location.
        """
        path = str(path).strip()

        if not path:
            try:
                self._config.set("storage.custom_root", "")
            except Exception:
                log.exception("could not clear storage.custom_root")
                return False
            self.storageChanged.emit("")
            log.info("custom storage root cleared")
            return True

        try:
            candidate = Path(path).expanduser()
        except Exception:
            log.exception("invalid path for custom storage")
            return False

        try:
            result = self._storage_manager.validate_root(candidate)
        except Exception:
            log.exception("validate_root raised")
            return False

        if not result.ok:
            log.warning(
                "custom storage root rejected",
                extra={"path": str(candidate), "reason": result.reason},
            )
            return False

        resolved = str(candidate.resolve())

        try:
            self._config.set("storage.custom_root", resolved)
        except Exception:
            log.exception("could not set storage.custom_root")
            return False

        self.storageChanged.emit(resolved)
        log.info(
            "custom storage root saved (restart to apply)",
            extra={"path": resolved},
        )
        return True

    # ------------------------------------------------------------------
    # About
    # ------------------------------------------------------------------
    @Slot(result=str)
    def getAboutJson(self) -> str:
        """
        Return app + platform info for the About section.
        """
        try:
            info = self._platform.info
            payload = {
                "app_name": "Rhea AI",
                "app_version": "1.0.0",
                "python_version": info.python_version,
                "python_implementation": info.python_implementation,
                "os_name": info.os_name,
                "os_release": info.os_release,
                "os_version": info.os_version,
                "architecture": info.architecture,
                "is_windows": info.is_windows,
                "frozen": info.is_frozen,
                "executable": info.executable,
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            log.exception("getAboutJson failed")
            return "{}"