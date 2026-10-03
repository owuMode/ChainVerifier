# config/configuration_service.py
"""
ConfigurationService — single authoritative source for settings.

Layers (later wins):
  1. defaults.yaml
  2. SQLite settings table (via SettingsRepository)
  3. in-memory session overrides

Changes are written through to SQLite when a repository is attached.
"""

from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from applog.logger import get_logger

log = get_logger("config")


class ConfigurationError(Exception):
    pass


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ConfigurationError(
            "PyYAML is required to load defaults.yaml."
        ) from exc
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, Mapping):
        raise ConfigurationError(f"{path} must contain a mapping at the root")
    return data


class ConfigurationService:
    """
    Thread-safe settings facade.

    Callers use dotted keys:
        cfg.get("agent.max_steps")            -> 25
        cfg.set("agent.max_steps", 50)
        cfg.on_change("agent.max_steps", fn)
    """

    def __init__(self, defaults_path: Path) -> None:
        self._lock = threading.RLock()
        self._defaults_path = defaults_path
        self._defaults: dict[str, Any] = {}
        self._overrides: dict[str, Any] = {}
        self._listeners: list[tuple[str, Callable[[str, Any, Any], None]]] = []
        self._settings_repo = None  # attached later by bootstrap
        self._load_defaults()

    # ------------------------------------------------------------------
    def attach_settings_repository(self, repo) -> None:
        """
        Attach a SettingsRepository (database.repositories.settings).
        After this, every set() call is persisted to SQLite and every
        get() consults SQLite first.
        """
        self._settings_repo = repo
        # Load any persisted overrides into memory now.
        try:
            stored = repo.all()
        except Exception:
            log.exception("failed to load persisted settings")
            stored = {}
        with self._lock:
            for key, value in stored.items():
                self._overrides[key] = value
        log.info("settings repository attached", extra={"count": len(stored)})

    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
            return self._get_from(self._defaults, key, default)

    def get_section(self, section: str) -> dict[str, Any]:
        with self._lock:
            section_defaults = self._defaults.get(section, {})
            merged = copy.deepcopy(section_defaults) if isinstance(section_defaults, dict) else {}
            for key, value in self._overrides.items():
                if key.startswith(section + "."):
                    _set_dotted(merged, key[len(section) + 1:], value)
            return merged

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            old = self.get(key)
            if old == value:
                return
            self._overrides[key] = value
            # Persist to SQLite
            if self._settings_repo is not None:
                try:
                    self._settings_repo.set(key, value)
                except Exception:
                    log.exception("failed to persist setting", extra={"key": key})
            self._notify(key, old, value)

    def set_many(self, values: Mapping[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value)

    def clear_override(self, key: str) -> None:
        with self._lock:
            if key in self._overrides:
                old = self._overrides.pop(key)
                if self._settings_repo is not None:
                    try:
                        self._settings_repo.delete(key)
                    except Exception:
                        log.exception("failed to delete setting", extra={"key": key})
                new = self.get(key)
                self._notify(key, old, new)

    def on_change(self, key: str, callback: Callable[[str, Any, Any], None]) -> None:
        self._listeners.append((key, callback))

    # ------------------------------------------------------------------
    def _load_defaults(self) -> None:
        if not self._defaults_path.exists():
            raise ConfigurationError(f"defaults file not found: {self._defaults_path}")
        self._defaults = dict(_load_yaml(self._defaults_path))
        log.info("defaults loaded", extra={"path": str(self._defaults_path)})

    @staticmethod
    def _get_from(tree: Mapping[str, Any], dotted: str, default: Any) -> Any:
        node: Any = tree
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                return default
            node = node[part]
        return node

    def _notify(self, key: str, old: Any, new: Any) -> None:
        for listen_key, callback in list(self._listeners):
            if listen_key == key:
                try:
                    callback(key, old, new)
                except Exception:
                    log.exception("settings listener failed", extra={"key": key})


def _set_dotted(tree: dict[str, Any], dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    node = tree
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value