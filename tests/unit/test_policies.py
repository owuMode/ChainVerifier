# tests/unit/test_policies.py
from security.permissions import PermissionLevel
from security.policies import PolicyDecision, PolicyEngine


def _engine():
    return PolicyEngine()


def test_safe_allowed():
    v = _engine().evaluate(permission_level=PermissionLevel.SAFE, tool_id="t")
    assert v.decision is PolicyDecision.ALLOW


def test_low_allowed():
    v = _engine().evaluate(permission_level=PermissionLevel.LOW, tool_id="t")
    assert v.decision is PolicyDecision.ALLOW


def test_moderate_requires_confirm():
    v = _engine().evaluate(permission_level=PermissionLevel.MODERATE, tool_id="t")
    assert v.decision is PolicyDecision.REQUIRE_CONFIRM


def test_high_requires_confirm():
    v = _engine().evaluate(permission_level=PermissionLevel.HIGH, tool_id="t")
    assert v.decision is PolicyDecision.REQUIRE_CONFIRM


def test_destructive_requires_confirm():
    # DESTRUCTIVE no longer hard-denies; it asks the user via the
    # permission broker. The executor calls the broker, which shows
    # a 2-step confirm UI for DESTRUCTIVE tools.
    v = _engine().evaluate(permission_level=PermissionLevel.DESTRUCTIVE, tool_id="t")
    assert v.decision is PolicyDecision.REQUIRE_CONFIRM


def test_manifest_denied_overrides_everything():
    v = _engine().evaluate(
        permission_level=PermissionLevel.SAFE,
        tool_id="t",
        manifest_denied=True,
    )
    assert v.decision is PolicyDecision.DENY


def test_user_override_allow():
    v = _engine().evaluate(
        permission_level=PermissionLevel.HIGH,
        tool_id="t",
        user_override_allow=True,
    )
    assert v.decision is PolicyDecision.ALLOW


def test_user_override_allow_bypasses_destructive():
    v = _engine().evaluate(
        permission_level=PermissionLevel.DESTRUCTIVE,
        tool_id="t",
        user_override_allow=True,
    )
    assert v.decision is PolicyDecision.ALLOW


def test_user_override_deny():
    v = _engine().evaluate(
        permission_level=PermissionLevel.SAFE,
        tool_id="t",
        user_override_allow=False,
    )
    assert v.decision is PolicyDecision.DENY


def test_dry_run_downgrades_moderate():
    v = _engine().evaluate(
        permission_level=PermissionLevel.MODERATE,
        tool_id="t",
        dry_run=True,
    )
    assert v.decision is PolicyDecision.ALLOW