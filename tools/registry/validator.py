# tools/registry/validator.py
"""
Manifest and schema validation (spec §21, §22).

Runs during discovery, before a tool is registered:
  * manifest.yaml is present, well-formed, and has required fields
  * the declared permission level is valid
  * the JSON schema file exists and is a well-formed object schema
  * the tool package exposes the required `TOOL` symbol (ToolContract)

Any failure here means the tool is rejected and logged. Never partially
loaded.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from applog.logger import get_logger
from security.permissions import PermissionLevel

log = get_logger("tools.registry.validator")


_REQUIRED_MANIFEST_FIELDS = (
    "tool_id",
    "name",
    "description",
    "category",
    "version",
    "permission_level",
    "input_schema_file",
)


class ToolValidationError(Exception):
    """Raised when a tool's manifest or schema is unusable."""


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    """
    Load and minimally validate a manifest.yaml. Raises on any failure.
    """
    if not manifest_path.exists():
        raise ToolValidationError(f"manifest not found: {manifest_path}")

    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ToolValidationError(
            "PyYAML is required to load tool manifests. Add `PyYAML` to requirements.txt."
        ) from exc

    with manifest_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    if not isinstance(data, Mapping):
        raise ToolValidationError(f"{manifest_path.name}: root must be a mapping")

    for field in _REQUIRED_MANIFEST_FIELDS:
        if field not in data:
            raise ToolValidationError(f"{manifest_path.name}: missing required field {field!r}")

    # Permission level
    try:
        PermissionLevel.from_str(str(data["permission_level"]))
    except ValueError as exc:
        raise ToolValidationError(
            f"{manifest_path.name}: invalid permission_level {data['permission_level']!r}"
        ) from exc

    # Capabilities (optional, must be a list of strings if present)
    caps = data.get("capabilities", [])
    if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
        raise ToolValidationError(
            f"{manifest_path.name}: capabilities must be a list of strings"
        )

    return dict(data)


def load_schema(tool_dir: Path, schema_filename: str) -> dict[str, Any]:
    """
    Load and minimally validate the tool's input JSON schema.
    Raises on any failure.
    """
    import json

    schema_path = tool_dir / schema_filename
    if not schema_path.exists():
        raise ToolValidationError(f"schema not found: {schema_path}")

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolValidationError(f"{schema_path.name}: invalid JSON ({exc})") from exc

    if not isinstance(schema, dict):
        raise ToolValidationError(f"{schema_path.name}: root must be an object")

    if schema.get("type") != "object":
        raise ToolValidationError(
            f"{schema_path.name}: root type must be 'object' (tool input is a dict)"
        )

    return schema