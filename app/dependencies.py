# app/dependencies.py
"""
Dependency container — explicit composition root (spec §89).

Design:
  * Deliberately simple and explicit — no hidden globals, no magic injection.
  * Every wired service is a typed attribute.
  * Populated only by `bootstrap.py`. Nothing else constructs it.
  * `_extras` exists so later phases can attach services (event bus,
    task manager, provider manager, tool registry, agent, native bridge)
    without modifying this dataclass each time. If a service becomes
    a first-class citizen, promote it to a typed field.

Import cycle avoidance:
  * `DatabaseManager` is imported under TYPE_CHECKING only. At runtime the
    field is populated by bootstrap. This keeps `app.dependencies`
    dependency-light and importable from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from config.configuration_service import ConfigurationService
from sysinfo.path_manager import PathManager
from sysinfo.platform_service import PlatformService
from sysinfo.storage_manager import StorageManager

if TYPE_CHECKING:
    from database.manager import DatabaseManager


@dataclass
class AppContext:
    """
    Live composition of the current application instance.

    Fields set at bootstrap time (Step 1 + Step 2):
        platform, paths, storage, config, database, logger_ready

    Fields populated by later steps via `put(...)`:
        event_bus, task_manager, provider_manager, tool_registry,
        permission_manager, policy_engine, secrets, audit,
        native_bridge, agent, main_window
    """

    # --- Core (Step 1) ---
    platform: PlatformService
    paths: PathManager
    storage: StorageManager
    config: ConfigurationService
    logger_ready: bool = False

    # --- Persistence (Step 2) ---
    database: Optional["DatabaseManager"] = None

    # --- Everything else, added incrementally ---
    _extras: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Generic slot accessors for later phases.
    # Prefer typed fields when a service is first-class; use these only
    # as a bridge while the architecture is being built up.
    # ------------------------------------------------------------------
    def put(self, name: str, value: object) -> None:
        """Attach a named service to the context. Idempotent overwrite."""
        self._extras[name] = value

    def get(self, name: str) -> object:
        """Retrieve an attached service. Raises KeyError if missing."""
        return self._extras[name]

    def has(self, name: str) -> bool:
        return name in self._extras