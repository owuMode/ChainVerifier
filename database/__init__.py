# database/__init__.py
"""
Database package.

Lazy re-exports. The repositories package imports back into
database.manager; eager imports here would create a subtle cycle
the moment anything in repositories needs security.* or core.*.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "DatabaseManager": ("database.manager", "DatabaseManager"),
    "DatabaseError": ("database.manager", "DatabaseError"),
    "SettingsRepository": ("database.repositories.settings", "SettingsRepository"),
    "ConversationsRepository": (
        "database.repositories.conversations",
        "ConversationsRepository",
    ),
    "Conversation": ("database.repositories.conversations", "Conversation"),
    "MessagesRepository": ("database.repositories.messages", "MessagesRepository"),
    "Message": ("database.repositories.messages", "Message"),
    "AuditRepository": ("database.repositories.audit", "AuditRepository"),
    "AuditEvent": ("database.repositories.audit", "AuditEvent"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'database' has no attribute {name!r}")
    module_path, attr = target
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_EXPORTS.keys())


__all__ = sorted(_EXPORTS.keys())