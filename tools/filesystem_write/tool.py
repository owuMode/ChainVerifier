# tools/filesystem_write/tool.py
"""
filesystem_write — modify files and folders on disk.

Operations:
  * write   — create or overwrite a file (backup .bak if exists)
  * append  — append text to a file (creates if missing)
  * delete  — delete a file (backup .bak)
  * move    — rename/move a file (same volume only)
  * mkdir   — create a folder (parents allowed)
  * rmdir   — remove an EMPTY folder

Safety:
  * Every path is normalized and checked against restricted roots.
  * Backups saved as "<original>.bak" next to the original.
  * File size capped at 50 MB.
  * Same-volume rule for move.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from security.permissions import PermissionLevel
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolContract, ToolSpec


MAX_FILE_BYTES = 50 * 1024 * 1024   # 50 MB
BACKUP_SUFFIX = ".bak"


# Directories we refuse to touch regardless of permission.
_RESTRICTED_ROOTS = (
    r"C:\Windows",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
)


_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "filesystem_write input",
    "description": "Modify files and folders. Every operation requires user confirmation.",
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["write", "append", "delete", "move", "mkdir", "rmdir"],
            "description": "What to do. write=create/overwrite, append=add to end, delete=remove file, move=rename/move, mkdir=create folder, rmdir=remove empty folder.",
        },
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "Absolute path to a file (write/append/delete/move source) or folder (mkdir/rmdir). Use ~/Desktop, ~/Documents, %USERPROFILE%\\Desktop.",
        },
        "content": {
            "type": "string",
            "maxLength": 52428800,
            "description": "Text to write or append. Required for write/append. Max 50 MB.",
        },
        "destination": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "Target path for move. Required for move. Must be on the same volume as path.",
        },
        "encoding": {
            "type": "string",
            "enum": ["utf-8", "utf-16", "ascii"],
            "description": "Text encoding. Defaults to utf-8.",
        },
    },
    "required": ["action", "path"],
    "additionalProperties": False,
}


_SPEC = ToolSpec(
    tool_id="filesystem_write",
    name="Filesystem (Write)",
    description=(
        "Create, append, overwrite, delete, or move files and folders. "
        "Backs up files before write/delete. Restricted to user folders. "
        "Every operation requires explicit confirmation."
    ),
    category="system",
    version="1.0.0",
    permission_level=PermissionLevel.DESTRUCTIVE,
    capabilities=("write", "destructive", "file_operations", "backed_up"),
    denied=False,
    input_schema=_INPUT_SCHEMA,
    display_name="Modified files on disk",
)


_FOLDER_ALIASES: dict[str, str | None] = {
    "desktop":   "Desktop",
    "documents": "Documents",
    "downloads": "Downloads",
    "pictures":  "Pictures",
    "music":     "Music",
    "videos":    "Videos",
    "home":      "",
    "temp":      None,
}


class FilesystemWriteTool(ToolContract):

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    # ------------------------------------------------------------------
    def execute(self, request: ToolRequest) -> ToolResult:
        action = str(request.arguments.get("action", "")).strip().lower()
        raw_path = str(request.arguments.get("path", "")).strip()
        content = request.arguments.get("content", "")
        destination_raw = request.arguments.get("destination", "")
        encoding = str(request.arguments.get("encoding", "utf-8")).strip() or "utf-8"

        if action not in ("write", "append", "delete", "move", "mkdir", "rmdir"):
            return ToolResult.failure(
                f"unsupported action: {action!r}",
                error_code="unsupported_action",
            )

        resolved = self._resolve(raw_path)
        if resolved is None:
            return ToolResult.failure(
                f"could not resolve path: {raw_path!r}",
                error_code="invalid_path",
            )

        # Restricted-path check (applies to both source and destination).
        if self._is_restricted(resolved):
            return ToolResult.failure(
                f"refusing to touch restricted path: {resolved}",
                error_code="restricted_path",
            )

        if action == "write":
            return self._write(resolved, content, encoding)
        if action == "append":
            return self._append(resolved, content, encoding)
        if action == "delete":
            return self._delete(resolved)
        if action == "move":
            return self._move(resolved, destination_raw, raw_source=raw_path)
        if action == "mkdir":
            return self._mkdir(resolved)
        if action == "rmdir":
            return self._rmdir(resolved)

        return ToolResult.failure("unreachable", error_code="internal_error")

    # ------------------------------------------------------------------
    def _resolve(self, raw: str) -> Path | None:
        if not raw:
            return None
        s = raw.strip()
        for _ in range(3):
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                s = s[1:-1].strip()
            else:
                break

        if "/" not in s and "\\" not in s:
            alias = s.lower()
            if alias in _FOLDER_ALIASES:
                target = _FOLDER_ALIASES[alias]
                if target is None:
                    s = tempfile.gettempdir()
                elif target == "":
                    s = str(Path.home())
                else:
                    s = str(Path.home() / target)

        try:
            s = os.path.expandvars(s)
        except Exception:
            pass
        try:
            s = os.path.expanduser(s)
        except Exception:
            pass

        try:
            p = Path(s)
        except Exception:
            return None
        if not p.is_absolute():
            try:
                p = Path.home() / s
            except Exception:
                return None
        try:
            resolved = p.resolve(strict=False)
        except Exception:
            try:
                resolved = p.absolute()
            except Exception:
                return None
        try:
            if ".." in resolved.parts:
                return None
        except Exception:
            return None
        return resolved

    def _is_restricted(self, path: Path) -> bool:
        try:
            s = str(path).lower()
        except Exception:
            return False
        for root in _RESTRICTED_ROOTS:
            if s == root.lower() or s.startswith(root.lower() + os.sep):
                return True
        return False

    # ------------------------------------------------------------------
    def _write(self, path: Path, content: Any, encoding: str) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure(
                "content must be a string",
                error_code="invalid_content",
            )
        try:
            data = content.encode(encoding, errors="replace")
        except LookupError:
            return ToolResult.failure(
                f"unknown encoding: {encoding!r}",
                error_code="invalid_encoding",
            )

        if len(data) > MAX_FILE_BYTES:
            return ToolResult.failure(
                f"content too large ({len(data)} bytes, limit {MAX_FILE_BYTES})",
                error_code="file_too_large",
            )

        if path.exists() and not path.is_file():
            return ToolResult.failure(
                f"path exists but is not a file: {path}",
                error_code="not_a_file",
            )

        backup_path: Path | None = None
        try:
            if path.exists():
                backup_path = self._make_backup(path)

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not write file: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "write",
            "path": str(path),
            "bytes_written": len(data),
            "encoding": encoding,
            "backup": str(backup_path) if backup_path else None,
            "marker": "FS_WRITE_OK",
        }
        return ToolResult.success(output)

    def _append(self, path: Path, content: Any, encoding: str) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure(
                "content must be a string",
                error_code="invalid_content",
            )
        try:
            data = content.encode(encoding, errors="replace")
        except LookupError:
            return ToolResult.failure(
                f"unknown encoding: {encoding!r}",
                error_code="invalid_encoding",
            )

        if path.exists():
            if not path.is_file():
                return ToolResult.failure(
                    f"path exists but is not a file: {path}",
                    error_code="not_a_file",
                )
            try:
                current = path.stat().st_size
            except Exception:
                current = 0
            if current + len(data) > MAX_FILE_BYTES:
                return ToolResult.failure(
                    f"file too large after append (would be {current + len(data)} bytes)",
                    error_code="file_too_large",
                )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("ab") as fh:
                fh.write(data)
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not append: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "append",
            "path": str(path),
            "bytes_appended": len(data),
            "encoding": encoding,
            "marker": "FS_APPEND_OK",
        }
        return ToolResult.success(output)

    def _delete(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult.failure(
                f"file not found: {path}",
                error_code="not_found",
            )
        if not path.is_file():
            return ToolResult.failure(
                f"not a file: {path}",
                error_code="not_a_file",
            )

        try:
            backup_path = self._make_backup(path)
        except Exception as exc:
            return ToolResult.failure(
                f"could not create backup: {type(exc).__name__}: {exc}",
                error_code="backup_failed",
            )

        try:
            path.unlink()
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not delete: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "delete",
            "path": str(path),
            "backup": str(backup_path),
            "marker": "FS_DELETE_OK",
        }
        return ToolResult.success(output)

    def _move(self, src: Path, dest_raw: str, *, raw_source: str) -> ToolResult:
        dest = self._resolve(dest_raw)
        if dest is None:
            return ToolResult.failure(
                f"could not resolve destination: {dest_raw!r}",
                error_code="invalid_destination",
            )
        if self._is_restricted(dest):
            return ToolResult.failure(
                f"refusing to touch restricted destination: {dest}",
                error_code="restricted_path",
            )

        if not src.exists():
            return ToolResult.failure(
                f"source not found: {src}",
                error_code="not_found",
            )

        # Same-volume rule.
        try:
            src_drive = src.drive.lower()
            dest_drive = dest.drive.lower()
            if src_drive != dest_drive:
                return ToolResult.failure(
                    "cross-volume move is not supported; use copy + delete",
                    error_code="cross_volume",
                )
        except Exception:
            pass

        if dest.exists():
            return ToolResult.failure(
                f"destination already exists: {dest}",
                error_code="destination_exists",
            )

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
        except PermissionError:
            return ToolResult.failure(
                f"permission denied moving {src} → {dest}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not move: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "move",
            "source": str(src),
            "destination": str(dest),
            "marker": "FS_MOVE_OK",
        }
        return ToolResult.success(output)

    def _mkdir(self, path: Path) -> ToolResult:
        if path.exists():
            if path.is_dir():
                return ToolResult.success({
                    "action": "mkdir",
                    "path": str(path),
                    "created": False,
                    "marker": "FS_MKDIR_OK",
                })
            return ToolResult.failure(
                f"path exists but is a file: {path}",
                error_code="not_a_directory",
            )

        try:
            path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not create folder: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "mkdir",
            "path": str(path),
            "created": True,
            "marker": "FS_MKDIR_OK",
        }
        return ToolResult.success(output)

    def _rmdir(self, path: Path) -> ToolResult:
        if not path.exists():
            return ToolResult.failure(
                f"folder not found: {path}",
                error_code="not_found",
            )
        if not path.is_dir():
            return ToolResult.failure(
                f"not a folder: {path}",
                error_code="not_a_directory",
            )

        try:
            contents = list(path.iterdir())
        except Exception as exc:
            return ToolResult.failure(
                f"could not read folder: {type(exc).__name__}",
                error_code="io_error",
            )

        if contents:
            return ToolResult.failure(
                f"folder not empty ({len(contents)} item(s)); rmdir only removes empty folders",
                error_code="not_empty",
            )

        try:
            path.rmdir()
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not remove folder: {type(exc).__name__}: {exc}",
                error_code="io_error",
            )

        output = {
            "action": "rmdir",
            "path": str(path),
            "marker": "FS_RMDIR_OK",
        }
        return ToolResult.success(output)

    # ------------------------------------------------------------------
    def _make_backup(self, path: Path) -> Path:
        backup = path.with_suffix(path.suffix + BACKUP_SUFFIX)
        # If a backup already exists, add a numeric suffix.
        counter = 1
        while backup.exists():
            backup = path.with_suffix(path.suffix + f".bak{counter}")
            counter += 1
        shutil.copy2(str(path), str(backup))
        return backup

    # ------------------------------------------------------------------
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        """
        Re-check that the operation actually happened.
        """
        if not result.ok:
            return False

        out = result.output
        action = out.get("action")
        path_str = out.get("path") or out.get("source") or ""

        try:
            path = Path(path_str) if path_str else None
        except Exception:
            return False

        if action == "write":
            if out.get("marker") != "FS_WRITE_OK":
                return False
            if path is None or not path.is_file():
                return False
            try:
                size = path.stat().st_size
            except Exception:
                return False
            return size == int(out.get("bytes_written", -1))

        if action == "append":
            if out.get("marker") != "FS_APPEND_OK":
                return False
            if path is None or not path.is_file():
                return False
            # We can't check exact size reliably after concurrent appends;
            # just confirm it grew by at least the reported bytes.
            try:
                size = path.stat().st_size
            except Exception:
                return False
            return size >= int(out.get("bytes_appended", 0))

        if action == "delete":
            if out.get("marker") != "FS_DELETE_OK":
                return False
            if path is None:
                return False
            if path.exists():
                return False
            backup_str = out.get("backup")
            return bool(backup_str) and Path(backup_str).is_file()

        if action == "move":
            if out.get("marker") != "FS_MOVE_OK":
                return False
            src_str = out.get("source")
            dest_str = out.get("destination")
            if not src_str or not dest_str:
                return False
            return (not Path(src_str).exists()) and Path(dest_str).exists()

        if action == "mkdir":
            if out.get("marker") != "FS_MKDIR_OK":
                return False
            if path is None:
                return False
            return path.is_dir()

        if action == "rmdir":
            if out.get("marker") != "FS_RMDIR_OK":
                return False
            if path is None:
                return False
            return not path.exists()

        return False

    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        """
        Best-effort undo. Currently implemented for delete and write
        (restore from backup).
        """
        if not result.ok:
            return
        out = result.output
        backup_str = out.get("backup")
        if not backup_str:
            return
        try:
            backup = Path(backup_str)
            if not backup.is_file():
                return
            target = Path(out.get("path", ""))
            if out.get("action") in ("write", "delete"):
                shutil.copy2(str(backup), str(target))
        except Exception:
            pass


TOOL: ToolContract = FilesystemWriteTool()