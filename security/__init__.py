# security/__init__.py
"""
Security package.

Design rule (spec §96):
  This package must NEVER import `database`, `core`, `tools`, or `gui`
  at module-import time. If a security primitive needs the database,
  the caller injects it (see database/repositories/audit.py).

Exports are lazy so importing `security.redaction` from a low-level
module (e.g. database.repositories.audit) does not drag the whole
package — and cannot create import cycles.

Audit persistence is intentionally NOT exposed here. It lives in
`database.repositories.audit` because persistence belongs to the
database layer. Security owns the concept, database owns the table.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


# Map: exported name -> (module_path, attribute_name)
_EXPORTS: dict[str, tuple[str, str]] = {
    # permissions
    "PermissionLevel": ("security.permissions", "PermissionLevel"),
    # policies
    "PolicyEngine": ("security.policies", "PolicyEngine"),
    "PolicyDecision": ("security.policies", "PolicyDecision"),
    "PolicyVerdict": ("security.policies", "PolicyVerdict"),
    # validation
    "validate": ("security.validation", "validate"),
    "SchemaError": ("security.validation", "SchemaError"),
    # secrets
    "Secrets": ("security.secrets", "Secrets"),
    "SecretsError": ("security.secrets", "SecretsError"),
    # redaction (single implementation lives in applog)
    "REDACTED": ("security.redaction", "REDACTED"),
    "redact_mapping": ("security.redaction", "redact_mapping"),
    "redact_value": ("security.redaction", "redact_value"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'security' has no attribute {name!r}")
    module_path, attr = target
    module = import_module(module_path)
    value = getattr(module, attr)
    # Cache on the package so subsequent lookups bypass __getattr__.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_EXPORTS.keys())


__all__ = sorted(_EXPORTS.keys())