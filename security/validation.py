# security/validation.py
"""
JSON Schema validator — small, in-house, dependency-free.

We deliberately do NOT pull in `jsonschema` yet:
  * tool schemas are simple (object with typed properties + required)
  * we want predictable, audit-friendly behaviour
  * a future migration to `jsonschema` is possible without changing callers

Supported keywords:
    type            "object" | "array" | "string" | "integer" | "number" | "boolean" | "null"
    properties      dict of name -> subschema (for "object")
    required        list of property names (for "object")
    items           subschema (for "array")
    enum            list of allowed values
    minimum         number lower bound (inclusive)
    maximum         number upper bound (inclusive)
    minLength       string minimum length
    maxLength       string maximum length
    pattern         regex for strings
    additionalProperties  bool, default True (match JSON Schema default)

Anything not in this list is silently ignored — tool schemas should
stick to the supported subset. The validator returns a list of human
error strings; empty list = valid.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


class SchemaError(Exception):
    """Raised when the schema itself is malformed (not the data)."""


def validate(schema: dict, data: Any) -> list[str]:
    """
    Return a list of human-readable validation errors. Empty list = valid.
    Raises SchemaError only when the schema itself is unusable.
    """
    errors: list[str] = []
    _validate_node(schema, data, path="$", errors=errors)
    return errors


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------
def _validate_node(schema: Any, data: Any, *, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {path} must be an object")

    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(expected_type, data):
        errors.append(f"{path}: expected {expected_type}, got {_type_name(data)}")
        return

    if "enum" in schema:
        if data not in schema["enum"]:
            errors.append(f"{path}: value {data!r} not in enum {schema['enum']!r}")

    if isinstance(data, str):
        _validate_string(schema, data, path, errors)
    elif isinstance(data, bool):
        pass  # bool is a subclass of int in Python; handle separately
    elif isinstance(data, (int, float)):
        _validate_number(schema, data, path, errors)

    if isinstance(data, dict):
        _validate_object(schema, data, path, errors)
    elif isinstance(data, list):
        _validate_array(schema, data, path, errors)


def _validate_string(schema: dict, data: str, path: str, errors: list[str]) -> None:
    if "minLength" in schema and len(data) < schema["minLength"]:
        errors.append(f"{path}: length {len(data)} < minLength {schema['minLength']}")
    if "maxLength" in schema and len(data) > schema["maxLength"]:
        errors.append(f"{path}: length {len(data)} > maxLength {schema['maxLength']}")
    if "pattern" in schema:
        try:
            if re.search(schema["pattern"], data) is None:
                errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
        except re.error as exc:
            raise SchemaError(f"invalid pattern at {path}: {exc}") from exc


def _validate_number(schema: dict, data: float, path: str, errors: list[str]) -> None:
    if "minimum" in schema and data < schema["minimum"]:
        errors.append(f"{path}: {data} < minimum {schema['minimum']}")
    if "maximum" in schema and data > schema["maximum"]:
        errors.append(f"{path}: {data} > maximum {schema['maximum']}")


def _validate_object(schema: dict, data: dict, path: str, errors: list[str]) -> None:
    props: dict = schema.get("properties", {})
    required: Iterable[str] = schema.get("required", [])
    additional_allowed: bool = schema.get("additionalProperties", True)

    for name in required:
        if name not in data:
            errors.append(f"{path}: missing required property {name!r}")

    for name, value in data.items():
        child_path = f"{path}.{name}"
        if name in props:
            _validate_node(props[name], value, path=child_path, errors=errors)
        elif not additional_allowed:
            errors.append(f"{path}: additional property {name!r} not allowed")


def _validate_array(schema: dict, data: list, path: str, errors: list[str]) -> None:
    items_schema = schema.get("items")
    if items_schema is None:
        return
    for index, item in enumerate(data):
        _validate_node(items_schema, item, path=f"{path}[{index}]", errors=errors)


# ----------------------------------------------------------------------
# Type helpers
# ----------------------------------------------------------------------
def _matches_type(expected: str, data: Any) -> bool:
    if expected == "object":
        return isinstance(data, dict)
    if expected == "array":
        return isinstance(data, list)
    if expected == "string":
        return isinstance(data, str)
    if expected == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if expected == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if expected == "boolean":
        return isinstance(data, bool)
    if expected == "null":
        return data is None
    raise SchemaError(f"unsupported type in schema: {expected!r}")


def _type_name(data: Any) -> str:
    if data is None:
        return "null"
    if isinstance(data, bool):
        return "boolean"
    if isinstance(data, int):
        return "integer"
    if isinstance(data, float):
        return "number"
    if isinstance(data, str):
        return "string"
    if isinstance(data, list):
        return "array"
    if isinstance(data, dict):
        return "object"
    return type(data).__name__