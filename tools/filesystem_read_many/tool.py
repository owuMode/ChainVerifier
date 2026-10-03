# tools/filesystem_read_many/tool.py
"""
filesystem_read_many — read every text file in a folder in one call.

Design:
  * Read-only. No writes, no deletes, no moves.
  * Skips binary files (null byte in the first KB).
  * Caps per-file size and total file count.
  * Path traversal blocked (same rules as `filesystem`).
  * Recursive is OFF by default — only direct children of the folder.
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


DEFAULT_MAX_FILES = 25
DEFAULT_MAX_FILE_BYTES = 256 * 1024   # 256 KB
TEXT_PROBE_BYTES = 4096
HARD_MAX_FILES = 200
HARD_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB


# NOTE: This schema MUST match `schema.json` byte-for-byte.
_INPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "filesystem_read_many input",
    "description": "Read every text file in a folder in a single call.",
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4096,
            "description": "Folder to read. Use ~/Desktop, ~/Documents, %USERPROFILE%\\Desktop, or the bare name Desktop."
        },
        "extensions": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 16},
            "description": "Optional whitelist of extensions, e.g. ['.py', '.md']. Case-insensitive. If empty, all text files are included."
        },
        "recursive": {
            "type": "boolean",
            "description": "If true, subfolders are scanned too. Default false."
        },
        "max_files": {
            "type": "integer",
            "minimum": 1,
            "maximum": 200,
            "description": "Maximum number of files to read. Default 25."
        },
        "max_file_bytes": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5242880,
            "description": "Maximum size per file in bytes. Default 262144 (256 KB)."
        }
    },
    "required": ["path"],
    "additionalProperties": False,
}


_SPEC = ToolSpec(
    tool_id="filesystem_read_many",
    name="Read Folder Contents",
    description=(
        "Reads all text files in a folder (or a filtered subset by "
        "extension). Skips binary files, caps each file size and the "
        "total number of files. Read-only."
    ),
    category="system",
    version="1.0.0",
    permission_level=PermissionLevel.MODERATE,
    capabilities=("read_only", "no_network", "restricted_paths", "batch_read"),
    denied=False,
    input_schema=_INPUT_SCHEMA,
    display_name="Read all files in a folder",
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

# Extensions we always consider binary.
_BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff",
    ".mp3", ".mp4", ".wav", ".flac", ".ogg", ".m4a", ".mov", ".avi", ".mkv",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".pyd", ".bin", ".o", ".obj", ".class",
    ".pdf", ".docx", ".xlsx", ".pptx", ".sqlite", ".db", ".pyc",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
})


class FilesystemReadManyTool(ToolContract):

    @property
    def spec(self) -> ToolSpec:
        return _SPEC

    # ------------------------------------------------------------------
    def execute(self, request: ToolRequest) -> ToolResult:
        raw_path = str(request.arguments.get("path", "")).strip()
        if not raw_path:
            return ToolResult.failure(
                "path is required",
                error_code="invalid_path",
            )

        extensions_arg = request.arguments.get("extensions") or []
        extensions = _normalize_extensions(extensions_arg)

        recursive = bool(request.arguments.get("recursive", False))

        try:
            max_files = int(request.arguments.get("max_files", DEFAULT_MAX_FILES))
        except (TypeError, ValueError):
            max_files = DEFAULT_MAX_FILES
        max_files = max(1, min(HARD_MAX_FILES, max_files))

        try:
            max_file_bytes = int(
                request.arguments.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)
            )
        except (TypeError, ValueError):
            max_file_bytes = DEFAULT_MAX_FILE_BYTES
        max_file_bytes = max(1, min(HARD_MAX_FILE_BYTES, max_file_bytes))

        folder = self._resolve(raw_path)
        if folder is None:
            return ToolResult.failure(
                f"could not resolve path: {raw_path!r}",
                error_code="invalid_path",
            )
        if self._is_restricted(folder):
            return ToolResult.failure(
                f"refusing to read restricted path: {folder}",
                error_code="restricted_path",
            )
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

        # Discover files.
        try:
            candidates = self._discover(
                folder, recursive=recursive, extensions=extensions,
            )
        except PermissionError:
            return ToolResult.failure(
                f"permission denied: {folder}",
                error_code="permission_denied",
            )
        except Exception as exc:
            return ToolResult.failure(
                f"could not scan folder: {type(exc).__name__}",
                error_code="io_error",
            )

        total_found = len(candidates)
        candidates = candidates[:max_files]

        entries: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        for path in candidates:
            try:
                size = path.stat().st_size
            except Exception:
                skipped.append({"path": str(path), "reason": "stat_error"})
                continue

            if size > max_file_bytes:
                skipped.append({"path": str(path), "reason": "file_too_large"})
                continue

            ext = path.suffix.lower()
            if ext in _BINARY_EXTENSIONS:
                skipped.append({"path": str(path), "reason": "binary_extension"})
                continue

            try:
                with path.open("rb") as fh:
                    probe = fh.read(TEXT_PROBE_BYTES)
                if b"\x00" in probe:
                    skipped.append({"path": str(path), "reason": "binary_content"})
                    continue
            except Exception:
                skipped.append({"path": str(path), "reason": "read_probe_failed"})
                continue

            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
            except Exception:
                skipped.append({"path": str(path), "reason": "read_failed"})
                continue

            try:
                mtime = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat()
            except Exception:
                mtime = ""

            entries.append({
                "path": str(path),
                "name": path.name,
                "ext": ext,
                "size_bytes": size,
                "modified": mtime,
                "content": content,
            })

        output = {
            "action": "read_many",
            "path": str(folder),
            "total_found": total_found,
            "read_count": len(entries),
            "truncated": total_found > max_files,
            "entries": entries,
            "skipped": skipped,
            "marker": "FILESYSTEM_READ_MANY_OK",
        }
        return ToolResult.success(output)

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
        restricted = (
            r"C:\Windows",
            r"C:\Program Files",
            r"C:\Program Files (x86)",
            r"C:\ProgramData",
            r"C:\$Recycle.Bin",
            r"C:\System Volume Information",
        )
        try:
            s = str(path).lower()
        except Exception:
            return False
        for root in restricted:
            if s == root.lower() or s.startswith(root.lower() + os.sep):
                return True
        return False

    # ------------------------------------------------------------------
    def _discover(
        self,
        folder: Path,
        *,
        recursive: bool,
        extensions: set[str],
    ) -> list[Path]:
        out: list[Path] = []

        if recursive:
            for root, _dirs, files in os.walk(folder):
                for name in files:
                    p = Path(root) / name
                    if extensions and p.suffix.lower() not in extensions:
                        continue
                    out.append(p)
        else:
            try:
                for entry in os.scandir(folder):
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    p = Path(entry.path)
                    if extensions and p.suffix.lower() not in extensions:
                        continue
                    out.append(p)
            except PermissionError:
                raise

        out.sort(key=lambda p: (p.suffix.lower(), p.name.lower()))
        return out

    # ------------------------------------------------------------------
    def verify(self, request: ToolRequest, result: ToolResult) -> bool:
        if not result.ok:
            return False

        out = result.output
        if out.get("marker") != "FILESYSTEM_READ_MANY_OK":
            return False

        entries = out.get("entries") or []
        if not isinstance(entries, list):
            return False

        # For every entry, confirm the file still exists and the
        # reported content matches a fresh read.
        for entry in entries:
            try:
                path = Path(entry.get("path", ""))
            except Exception:
                return False
            if not path.is_file():
                return False
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    fresh = fh.read()
            except Exception:
                return False
            if fresh != entry.get("content"):
                return False

        return True

    def rollback(self, request: ToolRequest, result: ToolResult) -> None:
        return None


# ----------------------------------------------------------------------
def _normalize_extensions(raw: Any) -> set[str]:
    if not raw:
        return set()
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        s = str(item).strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        out.add(s)
    return out


TOOL: ToolContract = FilesystemReadManyTool()