# tests/unit/test_validation.py
import pytest

from security.validation import SchemaError, validate


def test_object_required_and_types():
    schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "minLength": 1},
            "count": {"type": "integer", "minimum": 0},
        },
        "required": ["message"],
    }
    assert validate(schema, {"message": "hi", "count": 3}) == []
    errors = validate(schema, {"count": 3})
    assert any("missing required property 'message'" in e for e in errors)


def test_enum_and_pattern():
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["fast", "deep"]},
            "code": {"type": "string", "pattern": r"^[A-Z]{3}$"},
        },
    }
    assert validate(schema, {"mode": "fast", "code": "ABC"}) == []
    errors = validate(schema, {"mode": "other", "code": "abc"})
    assert any("not in enum" in e for e in errors)
    assert any("does not match pattern" in e for e in errors)


def test_additional_properties_rejected_when_disabled():
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "additionalProperties": False,
    }
    errors = validate(schema, {"a": 1, "b": 2})
    assert any("additional property 'b'" in e for e in errors)


def test_array_items():
    schema = {"type": "array", "items": {"type": "integer"}}
    assert validate(schema, [1, 2, 3]) == []
    errors = validate(schema, [1, "x"])
    assert any("expected integer" in e for e in errors)


def test_invalid_schema_type():
    with pytest.raises(SchemaError):
        validate({"type": "widget"}, None)