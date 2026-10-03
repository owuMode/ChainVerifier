# tests/unit/test_permissions.py
from security.permissions import PermissionLevel


def test_ordering():
    assert PermissionLevel.SAFE < PermissionLevel.LOW
    assert PermissionLevel.LOW < PermissionLevel.MODERATE
    assert PermissionLevel.MODERATE < PermissionLevel.HIGH
    assert PermissionLevel.HIGH < PermissionLevel.DESTRUCTIVE


def test_from_str():
    assert PermissionLevel.from_str("safe") is PermissionLevel.SAFE
    assert PermissionLevel.from_str(" HIGH ") is PermissionLevel.HIGH


def test_from_str_invalid():
    try:
        PermissionLevel.from_str("nope")
    except ValueError as exc:
        assert "unknown permission level" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_confirmation_threshold():
    assert not PermissionLevel.SAFE.requires_confirmation()
    assert not PermissionLevel.LOW.requires_confirmation()
    assert PermissionLevel.MODERATE.requires_confirmation()
    assert PermissionLevel.HIGH.requires_confirmation()
    assert PermissionLevel.DESTRUCTIVE.requires_confirmation()


def test_write_classification():
    assert not PermissionLevel.SAFE.is_write()
    assert not PermissionLevel.LOW.is_write()
    assert PermissionLevel.MODERATE.is_write()


def test_destructive_classification():
    assert PermissionLevel.DESTRUCTIVE.is_destructive()
    assert not PermissionLevel.HIGH.is_destructive()