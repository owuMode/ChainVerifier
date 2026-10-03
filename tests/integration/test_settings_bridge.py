# tests/integration/test_settings_bridge.py
"""
Smoke tests for SettingsBridge.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield


@pytest.fixture
def bridge(tmp_path: Path):
    from config.configuration_service import ConfigurationService
    from sysinfo.path_manager import PathManager
    from sysinfo.platform_service import get_platform_service
    from sysinfo.storage_manager import StorageManager

    defaults = (
        Path(__file__).resolve().parents[2]
        / "config" / "defaults" / "defaults.yaml"
    )
    config = ConfigurationService(defaults)
    platform_service = get_platform_service()
    path_manager = PathManager(platform_service)
    storage = StorageManager(path_manager)

    from gui.web.settings_bridge import SettingsBridge
    return SettingsBridge(
        config=config,
        path_manager=path_manager,
        storage_manager=storage,
        platform_service=platform_service,
    )


def test_get_storage_info(bridge):
    raw = bridge.getStorageInfoJson()
    data = json.loads(raw)
    assert "current_root" in data
    assert "default_root" in data
    assert data["is_custom"] is False
    assert data["pending_root"] == ""
    assert data["restart_required"] is False


def test_validate_storage_path_ok(bridge, tmp_path):
    candidate = tmp_path / "custom_storage"
    candidate.mkdir()
    raw = bridge.validateStoragePath(str(candidate))
    data = json.loads(raw)
    assert data["ok"] is True


def test_validate_storage_path_relative_rejected(bridge):
    raw = bridge.validateStoragePath("relative/path")
    data = json.loads(raw)
    assert data["ok"] is False


def test_set_and_clear_custom_storage(bridge, tmp_path):
    custom = tmp_path / "custom_root"
    custom.mkdir()

    # Set
    ok = bridge.setCustomStorageRoot(str(custom))
    assert ok is True

    data = json.loads(bridge.getStorageInfoJson())
    assert data["pending_root"]
    assert data["restart_required"] is True

    # Clear
    ok = bridge.setCustomStorageRoot("")
    assert ok is True

    data = json.loads(bridge.getStorageInfoJson())
    assert data["pending_root"] == ""
    assert data["restart_required"] is False


def test_set_invalid_storage_rejected(bridge):
    # Relative path is rejected.
    assert bridge.setCustomStorageRoot("relative") is False


def test_get_about(bridge):
    raw = bridge.getAboutJson()
    data = json.loads(raw)
    assert data["app_name"] == "Rhea AI"
    assert data["app_version"]
    assert data["python_version"]
    assert "os_name" in data