# tests/unit/test_native_bridge.py
"""
NativeBridge tests.

These tests run on any machine:
  * If module.pyd is missing, they verify graceful fallback.
  * If module.pyd is present, they verify the bridge loaded it.
"""

from __future__ import annotations

from pathlib import Path

from native import NativeBridge, NativeBridgeError


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_bridge_constructs_without_pyd(tmp_path: Path):
    # tmp_path has no native/ folder.
    nb = NativeBridge(tmp_path)
    assert nb.is_available() is False
    assert nb.load_error() is not None
    assert nb.native_version() is None
    assert nb.capabilities() == {}


def test_bridge_missing_submodule_raises_when_unavailable(tmp_path: Path):
    nb = NativeBridge(tmp_path)
    try:
        _ = nb.notepad_basic
    except NativeBridgeError as exc:
        assert "not available" in str(exc)
    else:
        raise AssertionError("expected NativeBridgeError")


def test_bridge_reports_availability_on_project_root():
    # On the developer's machine, module.pyd may or may not exist.
    # We only assert the bridge's contract, not its state.
    nb = NativeBridge(_project_root())
    available = nb.is_available()
    if available:
        assert nb.native_version() is not None
        assert isinstance(nb.capabilities(), dict)
        # If loaded, notepad group must be exposed.
        assert hasattr(nb, "notepad_basic")
    else:
        assert nb.load_error() is not None


def test_bridge_supports_reflects_capabilities(tmp_path: Path):
    nb = NativeBridge(tmp_path)
    assert nb.supports("notepad.basic") is False