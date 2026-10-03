# tools/registry/discovery.py
"""
Discovery — find and register every valid tool under `tools/`.

Discovery rules (spec §22):
  * Every directory under `tools/` that contains a manifest.yaml is a candidate.
  * Excluded: `tools/registry/`, `tools/__pycache__/`, anything starting with `_`.
  * A candidate must:
        1. have a valid manifest.yaml
        2. have a valid input schema (JSON object root)
        3. import its `tool.py` successfully
        4. expose a `TOOL` symbol that is a ToolContract instance
        5. declare a spec whose tool_id matches the manifest
  * A candidate failing any step is skipped with a logged reason.
    Discovery never raises to the caller.
"""

from __future__ import annotations

import importlib
import traceback
from pathlib import Path

from applog.logger import get_logger
from security.permissions import PermissionLevel
from tools.base import ToolResult
from tools.registry.registry import ToolContract, ToolRegistry, ToolSpec
from tools.registry.validator import (
    ToolValidationError,
    load_manifest,
    load_schema,
)

log = get_logger("tools.registry.discovery")


def discover_tools(tools_root: Path, registry: ToolRegistry) -> None:
    """
    Scan `tools_root` for tool packages and register every valid one.
    Registry is NOT sealed here — callers seal after discovery.
    """
    if not tools_root.is_dir():
        log.warning("tools root not found", extra={"path": str(tools_root)})
        return

    for child in sorted(tools_root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        if child.name in {"registry", "__pycache__"}:
            continue
        manifest_path = child / "manifest.yaml"
        if not manifest_path.exists():
            continue

        try:
            tool = _load_tool_package(child, manifest_path)
        except ToolValidationError as exc:
            log.warning(
                "tool rejected",
                extra={"path": str(child), "reason": str(exc)},
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            log.error(
                "tool load failed",
                extra={
                    "path": str(child),
                    "reason": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc(),
                },
            )
            continue

        try:
            registry.register(tool)
            log.info(
                "tool registered",
                extra={
                    "tool_id": tool.spec.tool_id,
                    "permission": tool.spec.permission_level.label(),
                },
            )
        except ValueError as exc:
            log.warning(
                "tool registration rejected",
                extra={"path": str(child), "reason": str(exc)},
            )


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _load_tool_package(tool_dir: Path, manifest_path: Path) -> ToolContract:
    manifest = load_manifest(manifest_path)

    schema = load_schema(tool_dir, str(manifest["input_schema_file"]))

    module_path = f"tools.{tool_dir.name}.tool"
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise ToolValidationError(
            f"could not import {module_path}: {type(exc).__name__}: {exc}"
        ) from exc

    tool = getattr(module, "TOOL", None)
    if tool is None:
        raise ToolValidationError(f"{module_path}: missing TOOL symbol")
    if not isinstance(tool, ToolContract):
        raise ToolValidationError(
            f"{module_path}: TOOL must implement ToolContract"
        )

    # Cross-check the manifest against the tool's own spec.
    manifest_permission = PermissionLevel.from_str(str(manifest["permission_level"]))
    if tool.spec.permission_level != manifest_permission:
        raise ToolValidationError(
            f"{tool_dir.name}: permission_level mismatch "
            f"(manifest={manifest_permission.label()}, spec={tool.spec.permission_level.label()})"
        )
    if tool.spec.tool_id != str(manifest["tool_id"]):
        raise ToolValidationError(
            f"{tool_dir.name}: tool_id mismatch "
            f"(manifest={manifest['tool_id']!r}, spec={tool.spec.tool_id!r})"
        )
    if tool.spec.input_schema != schema:
        raise ToolValidationError(
            f"{tool_dir.name}: input_schema in spec does not match schema.json"
        )

    return tool