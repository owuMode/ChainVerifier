# tests/unit/test_secrets.py
"""
DPAPI is Windows-only. This test is skipped elsewhere.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from security.secrets import Secrets, SecretsError


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="DPAPI is Windows-only",
)


def test_roundtrip(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    s.set("provider", "gemini", "AIzaTEST-not-a-real-key")
    assert s.get("provider", "gemini") == "AIzaTEST-not-a-real-key"


def test_overwrite(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    s.set("provider", "k", "one")
    s.set("provider", "k", "two")
    assert s.get("provider", "k") == "two"


def test_missing_returns_none(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    assert s.get("provider", "nope") is None


def test_delete(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    s.set("provider", "k", "v")
    s.delete("provider", "k")
    assert s.get("provider", "k") is None


def test_list_namespace(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    s.set("provider", "a", "1")
    s.set("provider", "b", "2")
    assert s.list("provider") == ["a", "b"]


def test_raw_file_is_not_plaintext(tmp_path: Path):
    root = tmp_path / "secrets"
    s = Secrets(root)
    s.set("provider", "k", "supersecretvalue")
    raw = (root / "provider" / "k.bin").read_bytes()
    assert b"supersecretvalue" not in raw


def test_invalid_namespace_rejected(tmp_path: Path):
    s = Secrets(tmp_path / "secrets")
    try:
        s.set("", "k", "v")
    except SecretsError:
        pass
    else:
        raise AssertionError("expected SecretsError for empty namespace")