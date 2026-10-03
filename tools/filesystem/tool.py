# tools/filesystem/tool.py
"""
filesystem — read-only access to files and folders.

Operations:
  * list — entries of a folder (name, type, size, mtime)
  * read — content of a text file (UTF-8, max 1 MB)

Path handling:
  * Accepts quoted paths ('"C:\\Users\\x"'), ~ expansion, %ENVVAR%,
    forward slashes, and bare folder aliases like "Desktop" or "temp".
  * Bare aliases expand against the user's home directory.
  * Path traversal (`..`) is rejected after normalization.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from security.permissions import PermissionLevel
from tools.base import ToolRequest, ToolResult
from tools.registry.registry import ToolContract, ToolSpec


MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_LISTING = 200
TEXT_PROBE_BYTES = 4096


_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "filesystem input",
    "description": "List a folder or read a text file. Read-only.",
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "read"],
            "description": "What to do. 'list' shows a folder's entries; 'read' returns a file's text.",
        },
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "Path to a folder (for 'list') or a file (for 'read'). Use ~/Desktop, ~/Documents, %USERPROFILE%\\Desktop, or the bare name Desktop.",
        },
    },
    "required": ["action", "path"],
    "additionalProperties": False,
}


_SPEC = ToolSpec(
    tool_id="filesystem",
    name="Filesystem",
    description=(
        "Lists a folder's contents, or reads a text file. "
        "Read-only. Path traversal blocked. 1 MB cap. "
        "Accepts ~/Desktop, ~/Documents, %USERPROFILE%\\Desktop, "
        "or the bare names Desktop / Documents / Downloads / temp."
    ),
    category="system",
    version="1.0.0",
    permission_level=PermissionLevel.MODERATE,
    capabilities=("read_only", "no_network", "restricted_paths"),
    denied=False,
    input_schema=_INPUT_SCHEMA,
    display_name="Accessed the filesystem",
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


class FilesystemTool(ToolContract):

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    # ------------------------------------------------------------------
    def execute(self, request: ToolRequest) -> ToolResult:
        action = str(request.arguments.get("action", "")).strip().lower()
        raw_path = str(request.arguments.get("path", "")).strip()

        if action not in ("list", "read"):
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

        if action == "list":
            return self._list(resolved)
        return self._read(resolved)

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

    # ------------------------------------------------------------------
    def _list(self, folder: Path) -> ToolResult:
        if not folder.exists():
            return ToolResult.failure(
                f"folder not found: {folder}",
                error_code="not_found",
            )
        if not folder.is_dir():
            return ToolResult.failure(
                f"not a folder: {folder}",
                error_code="not_a_directory",
            )

        try:
            entries = list(os.scandir(folder))
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {folder}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not read folder: {type(exc).__name__}",
                error_code="io_error",
            )

        entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

        items: list[dict[str, Any]] = []
        for entry in entries[:MAX_LISTING]:
            try:
                st = entry.stat(follow_symlinks=False)
                items.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir(follow_symlinks=False) else "file",
                    "size_bytes": int(st.st_size) if entry.is_file(follow_symlinks=False) else 0,
                    "modified": datetime.fromtimestamp(
                        st.st_mtime, tz=timezone.utc
                    ).isoformat(),
                })
            except Exception:
                items.append({
                    "name": entry.name,
                    "type": "unknown",
                    "size_bytes": 0,
                    "modified": "",
                })

        output = {
            "action": "list",
            "path": str(folder),
            "count": len(items),
            "total": len(entries),
            "truncated": len(entries) > MAX_LISTING,
            "entries": items,
            "marker": "FILESYSTEM_LIST_OK",
        }
        return ToolResult.success(output)

    def _read(self, file_path: Path) -> ToolResult:
        if not file_path.exists():
            return ToolResult.failure(
                f"file not found: {file_path}",
                error_code="not_found",
            )
        if not file_path.is_file():
            return ToolResult.failure(
                f"not a file: {file_path}",
                error_code="not_a_file",
            )

        try:
            size = file_path.stat().st_size
        except Exception as exc:
            return ToolResult.failure(
                f"could not stat file: {type(exc).__name__}",
                error_code="io_error",
            )

        if size > MAX_FILE_BYTES:
            return ToolResult.failure(
                f"file too large ({size} bytes, limit {MAX_FILE_BYTES})",
                error_code="file_too_large",
            )

        try:
            with file_path.open("rb") as fh:
                probe = fh.read(TEXT_PROBE_BYTES)
            if b"\x00" in probe:
                return ToolResult.failure(
                    "binary file; only text files are supported",
                    error_code="binary_file",
                )

            with file_path.open("r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {file_path}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not read file: {type(exc).__name__}",
                error_code="io_error",
            )

        output = {
            "action": "read",
            "path": str(file_path),
            "size_bytes": size,
            "content": content,
            "marker": "FILESYSTEM_READ_OK",
        }
        return ToolResult.success(output)

    # ------------------------------------------------------------------
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        if not result.ok:
            return False

        out = result.output
        action = out.get("action")
        path_str = out.get("path", "")

        try:
            path = Path(path_str)
        except Exception:
            return False

        if action == "list":
            if out.get("marker") != "FILESYSTEM_LIST_OK":
                return False
            try:
                names_now = sorted(e.name for e in os.scandir(path))
            except Exception:
                return False
            reported = sorted(item.get("name", "") for item in out.get("entries", []))
            if not all(name in names_now for name in reported):
                return False
            return True

        if action == "read":
            if out.get("marker") != "FILESYSTEM_READ_OK":
                return False
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    content_now = fh.read()
            except Exception:
                return False
            return content_now == out.get("content")

        return False

    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        return None


TOOL: ToolContract = FilesystemTool()