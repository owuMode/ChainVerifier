# security/policies.py
"""
PolicyEngine — the sole authority that decides whether a tool request
is allowed to proceed.

The AI never touches this module. It only produces structured tool
requests; PolicyEngine decides:

    ALLOW              proceed without prompting the user
    REQUIRE_CONFIRM    prompt the user; only execute on explicit yes
    DENY               reject outright; no user override

Baseline rules:
    SAFE          → ALLOW
    LOW           → ALLOW
    MODERATE      → REQUIRE_CONFIRM
    HIGH          → REQUIRE_CONFIRM
    DESTRUCTIVE   → REQUIRE_CONFIRM (with user_override_allow path)

Additional rule hooks:
  * A tool may declare `denied: true` in its manifest → always DENY.
  * `user_override_allow=True` from the executor bypasses MODERATE/HIGH
    REQUIRE_CONFIRM to ALLOW (but NEVER bypasses DENY).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from security.permissions import PermissionLevel


class PolicyDecision(Enum):
    ALLOW = "allow"
    REQUIRE_CONFIRM = "require_confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyVerdict:
    decision: PolicyDecision
    reason: str

    def is_allowed(self) -> bool:
        return self.decision is PolicyDecision.ALLOW

    def is_denied(self) -> bool:
        return self.decision is PolicyDecision.DENY

    def needs_confirmation(self) -> bool:
        return self.decision is PolicyDecision.REQUIRE_CONFIRM


class PolicyEngine:
    """
    Stateless decision function. All inputs come from the caller.
    """

    def evaluate(
        self,
        *,
        permission_level: PermissionLevel,
        tool_id: str,
        manifest_denied: bool = False,
        dry_run: bool = False,
        user_override_allow: Optional[bool] = None,
    ) -> PolicyVerdict:
        # 1. Hard deny: tool marked as denied in its own manifest.
        if manifest_denied:
            return PolicyVerdict(
                PolicyDecision.DENY,
                f"tool {tool_id!r} is marked denied in its manifest",
            )

        # 2. Explicit user override (set by the permission flow).
        if user_override_allow is True:
            return PolicyVerdict(
                PolicyDecision.ALLOW,
                f"user granted permission for {tool_id!r}",
            )
        if user_override_allow is False:
            return PolicyVerdict(
                PolicyDecision.DENY,
                f"user denied permission for {tool_id!r}",
            )

        # 3. Dry-run downgrades confirmation requirements to allow,
        #    provided the tool actually honors dry-run (its responsibility).
        if dry_run and permission_level >= PermissionLevel.MODERATE:
            return PolicyVerdict(
                PolicyDecision.ALLOW,
                f"dry-run requested for {tool_id!r}",
            )

        # 4. DESTRUCTIVE — always REQUIRE_CONFIRM (unless overridden above).
        #    The executor will ask the user via the permission broker.
        if permission_level.is_destructive():
            return PolicyVerdict(
                PolicyDecision.REQUIRE_CONFIRM,
                f"DESTRUCTIVE tool {tool_id!r} requires explicit confirmation",
            )

        # 5. HIGH and MODERATE — REQUIRE_CONFIRM.
        if permission_level >= PermissionLevel.HIGH:
            return PolicyVerdict(
                PolicyDecision.REQUIRE_CONFIRM,
                f"{permission_level.label()} tool {tool_id!r} requires confirmation",
            )
        if permission_level >= PermissionLevel.MODERATE:
            return PolicyVerdict(
                PolicyDecision.REQUIRE_CONFIRM,
                f"{permission_level.label()} tool {tool_id!r} requires confirmation",
            )

        # SAFE and LOW fall through to ALLOW.
        return PolicyVerdict(
            PolicyDecision.ALLOW,
            f"{permission_level.label()} tool {tool_id!r} is permitted",
        )