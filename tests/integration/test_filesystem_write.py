# tests/integration/test_filesystem_write.py
"""
Integration tests for the filesystem_write tool.

All tests use pytest's tmp_path so nothing touches the real user's
filesystem. Restricted-path and cross-volume checks are tested with
synthetic inputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.base import ToolRequest
from tools.filesystem_write.tool import TOOL


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _run(action: str, path: str, **kwargs):
    args = {"action": action, "path": path, **kwargs}
    return TOOL.execute(ToolRequest(tool_id="filesystem_write", arguments=args))


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------
def test_spec_is_destructive():
    assert TOOL.spec.permission_level.label() == "DESTRUCTIVE"
    assert TOOL.spec.denied is False


def test_schema_requires_action_and_path():
    schema = TOOL.spec.input_schema
    assert "action" in schema["required"]
    assert "path" in schema["required"]


# ----------------------------------------------------------------------
# write
# ----------------------------------------------------------------------
def test_write_creates_file(tmp_path: Path):
    target = tmp_path / "hello.txt"
    result = _run("write", str(target), content="hello world")
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "hello world"
    assert TOOL.verify(
        ToolRequest(tool_id="filesystem_write", arguments={}), result
    ) is True


def test_write_overwrites_with_backup(tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("first", encoding="utf-8")

    result = _run("write", str(target), content="second")
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "second"

    backup = Path(result.output["backup"])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "first"


def test_write_creates_parents(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c" / "deep.txt"
    result = _run("write", str(target), content="deep")
    assert result.ok is True
    assert target.is_file()


def test_write_rejects_directory_target(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    result = _run("write", str(folder), content="x")
    assert result.ok is False
    assert result.error_code == "not_a_file"


# ----------------------------------------------------------------------
# append
# ----------------------------------------------------------------------
def test_append_creates_file_if_missing(tmp_path: Path):
    target = tmp_path / "log.txt"
    result = _run("append", str(target), content="line1")
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "line1"


def test_append_adds_to_existing(tmp_path: Path):
    target = tmp_path / "log.txt"
    target.write_text("start", encoding="utf-8")
    result = _run("append", str(target), content="-more")
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "start-more"


# ----------------------------------------------------------------------
# delete
# ----------------------------------------------------------------------
def test_delete_file_creates_backup(tmp_path: Path):
    target = tmp_path / "remove_me.txt"
    target.write_text("bye", encoding="utf-8")

    result = _run("delete", str(target))
    assert result.ok is True
    assert not target.exists()

    backup = Path(result.output["backup"])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == "bye"


def test_delete_missing_file_fails(tmp_path: Path):
    result = _run("delete", str(tmp_path / "nope.txt"))
    assert result.ok is False
    assert result.error_code == "not_found"


def test_delete_folder_fails(tmp_path: Path):
    folder = tmp_path / "folder"
    folder.mkdir()
    result = _run("delete", str(folder))
    assert result.ok is False
    assert result.error_code == "not_a_file"


# ----------------------------------------------------------------------
# move
# ----------------------------------------------------------------------
def test_move_same_volume(tmp_path: Path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("payload", encoding="utf-8")

    result = _run("move", str(src), destination=str(dst))
    assert result.ok is True
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "payload"


def test_move_refuses_existing_destination(tmp_path: Path):
    src = tmp_path / "a.txt"
    dst = tmp_path / "b.txt"
    src.write_text("a", encoding="utf-8")
    dst.write_text("b", encoding="utf-8")

    result = _run("move", str(src), destination=str(dst))
    assert result.ok is False
    assert result.error_code == "destination_exists"


def test_move_missing_source_fails(tmp_path: Path):
    result = _run(
        "move",
        str(tmp_path / "ghost.txt"),
        destination=str(tmp_path / "target.txt"),
    )
    assert result.ok is False
    assert result.error_code == "not_found"


# ----------------------------------------------------------------------
# mkdir / rmdir
# ----------------------------------------------------------------------
def test_mkdir_creates_folder(tmp_path: Path):
    folder = tmp_path / "new_folder"
    result = _run("mkdir", str(folder))
    assert result.ok is True
    assert folder.is_dir()


def test_mkdir_existing_is_ok(tmp_path: Path):
    folder = tmp_path / "already"
    folder.mkdir()
    result = _run("mkdir", str(folder))
    assert result.ok is True
    assert result.output["created"] is False


def test_rmdir_removes_empty_folder(tmp_path: Path):
    folder = tmp_path / "empty"
    folder.mkdir()
    result = _run("rmdir", str(folder))
    assert result.ok is True
    assert not folder.exists()


def test_rmdir_refuses_non_empty(tmp_path: Path):
    folder = tmp_path / "full"
    folder.mkdir()
    (folder / "child.txt").write_text("x", encoding="utf-8")

    result = _run("rmdir", str(folder))
    assert result.ok is False
    assert result.error_code == "not_empty"


def test_rmdir_missing_folder_fails(tmp_path: Path):
    result = _run("rmdir", str(tmp_path / "ghost"))
    assert result.ok is False
    assert result.error_code == "not_found"


# ----------------------------------------------------------------------
# Restricted paths
# ----------------------------------------------------------------------
def test_restricted_path_is_refused():
    result = _run(
        "write",
        r"C:\Windows\System32\evil.dll",
        content="x",
    )
    assert result.ok is False
    assert result.error_code == "restricted_path"


def test_restricted_program_files_is_refused():
    result = _run(
        "write",
        r"C:\Program Files\evil.txt",
        content="x",
    )
    assert result.ok is False
    assert result.error_code == "restricted_path"


# ----------------------------------------------------------------------
# Unknown action
# ----------------------------------------------------------------------
def test_unknown_action_fails(tmp_path: Path):
    result = _run("explode", str(tmp_path / "x.txt"))
    assert result.ok is False
    assert result.error_code == "unsupported_action"


# ----------------------------------------------------------------------
# Rollback
# ----------------------------------------------------------------------
def test_rollback_restores_after_write(tmp_path: Path):
    target = tmp_path / "restore_me.txt"
    target.write_text("original", encoding="utf-8")

    result = _run("write", str(target), content="changed")
    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "changed"

    TOOL.rollback(
        ToolRequest(tool_id="filesystem_write", arguments={}), result
    )
    assert target.read_text(encoding="utf-8") == "original"


def test_rollback_restores_after_delete(tmp_path: Path):
    target = tmp_path / "bring_back.txt"
    target.write_text("alive", encoding="utf-8")

    result = _run("delete", str(target))
    assert result.ok is True
    assert not target.exists()

    TOOL.rollback(
        ToolRequest(tool_id="filesystem_write", arguments={}), result
    )
    assert target.read_text(encoding="utf-8") == "alive"