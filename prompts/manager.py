# prompts/manager.py
"""
PromptManager — the single source for prompt text (spec §51).

Design:
  * Prompts live as Markdown files under prompts/.
  * No hardcoded multi-line prompt strings in Python.
  * Loaded once at bootstrap, cached in memory.
  * Missing prompt = fatal for the file that requested it. Callers
    decide whether that is a startup error or a runtime error.
  * Versioning: a prompt may have sibling files like
    `<name>@<version>.md`. The loader resolves the latest version
    unless a specific version is requested. The convention is
    documented in prompts/versions/README.md.

The manager never modifies a prompt file. Editing prompts is a
deliberate act of the developer, done in source control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from applog.logger import get_logger

log = get_logger("prompts.manager")


# Matches: planner.md, planner@v2.md, planner@2024-06-01.md
_VERSIONED_RE = re.compile(r"^(?P<base>[^@]+)@(?P<version>.+)\.md$")


class PromptNotFoundError(FileNotFoundError):
    """Raised when a requested prompt does not exist."""


@dataclass(frozen=True)
class Prompt:
    """A loaded prompt with metadata."""
    name: str            # e.g. "agent/planner"
    version: str         # "latest" or the explicit version string
    path: Path
    text: str

    def __str__(self) -> str:  # convenience
        return self.text


class PromptManager:
    def __init__(self, prompts_root: Path) -> None:
        if not prompts_root.is_dir():
            raise PromptNotFoundError(f"prompts root not found: {prompts_root}")
        self._root = prompts_root
        self._cache: dict[tuple[str, str], Prompt] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, name: str, version: Optional[str] = None) -> Prompt:
        """
        Load a prompt by dotted or slash name.

        Examples:
            manager.get("system/system")
            manager.get("agent/planner")
            manager.get("agent/planner", version="v2")

        A missing file raises PromptNotFoundError.
        """
        clean_name = name.replace(".", "/").strip("/")
        resolved_version = version or "latest"
        key = (clean_name, resolved_version)

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        path = self._resolve_path(clean_name, version)
        text = path.read_text(encoding="utf-8")

        prompt = Prompt(
            name=clean_name,
            version=resolved_version,
            path=path,
            text=text,
        )
        self._cache[key] = prompt
        log.info(
            "prompt loaded",
            extra={"prompt": clean_name, "version": resolved_version},
        )
        return prompt

    def exists(self, name: str, version: Optional[str] = None) -> bool:
        try:
            self._resolve_path(name.replace(".", "/").strip("/"), version)
            return True
        except PromptNotFoundError:
            return False

    def list_versions(self, name: str) -> list[str]:
        """
        Return available versions for a prompt base name, e.g.
        ["latest", "v1", "v2"] sorted with "latest" first.

        "latest" is always returned first if any version exists.
        """
        clean_name = name.replace(".", "/").strip("/")
        folder = self._root / Path(clean_name).parent
        base = Path(clean_name).name
        if not folder.is_dir():
            return []

        versions: list[str] = []
        # Plain file → "latest"
        if (folder / f"{base}.md").exists():
            versions.append("latest")
        # Versioned files
        for path in sorted(folder.glob(f"{base}@*.md")):
            match = _VERSIONED_RE.match(path.name)
            if match and match.group("base") == base:
                versions.append(match.group("version"))
        return versions

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_path(self, clean_name: str, version: Optional[str]) -> Path:
        folder = self._root / Path(clean_name).parent
        base = Path(clean_name).name

        if version is None or version == "latest":
            # Prefer the unversioned file (the "current" one).
            candidate = folder / f"{base}.md"
            if candidate.exists():
                return candidate
            # Fallback: highest explicit version by filename.
            versioned = sorted(folder.glob(f"{base}@*.md"))
            if versioned:
                return versioned[-1]
            raise PromptNotFoundError(
                f"prompt not found: {clean_name} (looked under {folder})"
            )

        candidate = folder / f"{base}@{version}.md"
        if candidate.exists():
            return candidate
        raise PromptNotFoundError(
            f"prompt version not found: {clean_name}@{version}"
        )