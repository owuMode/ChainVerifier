# tests/integration/test_memory_explicit.py
"""
Tests for explicit memory command parsing.
"""

from __future__ import annotations

import pytest


def test_parse_remember_english():
    from memory.explicit import ExplicitKind, parse

    cmd = parse("remember that I like coffee")
    assert cmd is not None
    assert cmd.kind is ExplicitKind.REMEMBER
    assert cmd.content == "I like coffee"


def test_parse_remember_hindi():
    from memory.explicit import ExplicitKind, parse

    cmd = parse("yaad rakhna mera naam Siyak hai")
    assert cmd is not None
    assert cmd.kind is ExplicitKind.REMEMBER
    assert "Siyak" in cmd.content


def test_parse_note():
    from memory.explicit import ExplicitKind, parse

    cmd = parse("note that I'm working on AIProduct")
    assert cmd is not None
    assert cmd.kind is ExplicitKind.REMEMBER
    assert "AIProduct" in cmd.content


def test_parse_forget():
    from memory.explicit import ExplicitKind, parse

    cmd = parse("forget that I like coffee")
    assert cmd is not None
    assert cmd.kind is ExplicitKind.FORGET
    assert cmd.content == "I like coffee"


def test_parse_list():
    from memory.explicit import ExplicitKind, parse

    assert parse("what do you remember?").kind is ExplicitKind.LIST
    assert parse("show my memories").kind is ExplicitKind.LIST
    assert parse("memories").kind is ExplicitKind.LIST


def test_parse_clear():
    from memory.explicit import ExplicitKind, parse

    assert parse("forget everything").kind is ExplicitKind.CLEAR
    assert parse("clear all memories").kind is ExplicitKind.CLEAR
    assert parse("bhool jao sab").kind is ExplicitKind.CLEAR


def test_parse_none_for_regular_message():
    from memory.explicit import parse

    assert parse("what time is it?") is None
    assert parse("hello") is None
    assert parse("") is None


def test_kind_inference():
    from memory.explicit import parse

    cmd = parse("remember my name is Siyak")
    assert cmd is not None
    assert cmd.memory_kind == "identity"

    cmd = parse("remember I prefer Hinglish")
    assert cmd is not None
    assert cmd.memory_kind == "preference"

    cmd = parse("remember I'm working on AIProduct")
    assert cmd is not None
    assert cmd.memory_kind == "goal"

    cmd = parse("remember I like pizza")
    assert cmd is not None
    assert cmd.memory_kind == "preference"