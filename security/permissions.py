# security/permissions.py
"""
PermissionLevel — the risk classification every tool declares (spec §21, §24).

The AI cannot grant itself permission. The AI cannot skip a level.
The PermissionLevel a tool declares is fixed at registration time and
is enforced by PolicyEngine before any execution happens.

Levels, ordered low → high risk:

    SAFE          pure, reversible, no external side effects
    LOW           reads OS state, no mutation
    MODERATE      writes user files, launches apps, non-destructive
    HIGH          modifies system state, network actions with side effects
    DESTRUCTIVE   deletes data, executes arbitrary commands

Higher levels require stronger user authorization (see policies.py).
"""

from __future__ import annotations

from enum import IntEnum


class PermissionLevel(IntEnum):
    SAFE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    DESTRUCTIVE = 4

    # ---------------------------------------------------------------
    @classmethod
    def from_str(cls, value: str) -> "PermissionLevel":
        try:
            return cls[value.strip().upper()]
        except KeyError as exc:
            raise ValueError(f"unknown permission level: {value!r}") from exc

    def label(self) -> str:
        return self.name

    def requires_confirmation(self) -> bool:
        """
        Baseline: MODERATE and above require an explicit user confirm
        unless a policy override says otherwise (see PolicyEngine).
        """
        return self >= PermissionLevel.MODERATE

    def is_write(self) -> bool:
        return self >= PermissionLevel.MODERATE

    def is_destructive(self) -> bool:
        return self == PermissionLevel.DESTRUCTIVE