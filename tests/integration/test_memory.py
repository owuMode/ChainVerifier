# tests/integration/test_memory.py
"""
Smoke tests for the memory subsystem.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


@pytest.fixture
def db(tmp_path: Path):
    from database.manager import DatabaseManager

    database = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_migrations_dir(),
    )
    database.open()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def repo(db):
    from memory.repositories import MemoryRepository
    return MemoryRepository(db)


@pytest.fixture
def mgr(repo):
    from memory.manager import MemoryManager
    return MemoryManager(repo)


# ----------------------------------------------------------------------
# Repository
# ----------------------------------------------------------------------
def test_repository_create_and_get(repo):
    from memory.repositories import Memory

    m = Memory(
        memory_id="",
        user_id="default",
        kind="identity",
        content="User's name is Siyak",
        importance=5,
        source="explicit",
    )
    stored = repo.create(m)
    assert stored.memory_id
    assert stored.kind == "identity"

    loaded = repo.get(stored.memory_id)
    assert loaded is not None
    assert loaded.content == "User's name is Siyak"
    assert loaded.importance == 5


def test_repository_rejects_bad_kind(repo):
    from memory.repositories import Memory

    m = Memory(memory_id="", user_id="default", kind="nonsense", content="x")
    with pytest.raises(ValueError):
        repo.create(m)


def test_repository_soft_delete(repo):
    from memory.repositories import Memory

    m = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="hello world"))
    assert repo.count() == 1

    repo.archive(m.memory_id)
    assert repo.count() == 0
    assert repo.count(include_archived=True) == 1

    loaded = repo.get(m.memory_id)
    assert loaded.is_archived() is True

    repo.unarchive(m.memory_id)
    assert repo.count() == 1


def test_repository_search_keyword(repo):
    from memory.repositories import Memory

    repo.create(Memory(memory_id="", user_id="default", kind="identity",
                       content="User's name is Siyak"))
    repo.create(Memory(memory_id="", user_id="default", kind="preference",
                       content="User prefers Hinglish responses"))

    hits = repo.search_keyword("name")
    assert len(hits) == 1
    assert "Siyak" in hits[0].content

    hits = repo.search_keyword("hinglish")
    assert len(hits) == 1
    assert "Hinglish" in hits[0].content

    hits = repo.search_keyword("totally unrelated")
    assert hits == []


def test_repository_usage_touch(repo):
    from memory.repositories import Memory

    m = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="x is y"))
    assert m.use_count == 0

    repo.touch_usage([m.memory_id])
    loaded = repo.get(m.memory_id)
    assert loaded.use_count == 1
    assert loaded.last_used_at is not None


# ----------------------------------------------------------------------
# Manager — remember
# ----------------------------------------------------------------------
def test_manager_remember(mgr):
    m = mgr.remember("User's name is Siyak", kind="identity", importance=5)
    assert m is not None
    assert m.content == "User's name is Siyak"
    assert m.kind == "identity"
    assert mgr.count() == 1


def test_manager_rejects_too_short(mgr):
    m = mgr.remember("hi", kind="fact")
    assert m is None
    assert mgr.count() == 0


def test_manager_rejects_low_confidence(mgr):
    m = mgr.remember("Something irrelevant perhaps", kind="fact", confidence=0.1)
    assert m is None


def test_manager_dedupes_exact_content(mgr):
    a = mgr.remember("User prefers Hinglish responses", kind="preference")
    b = mgr.remember("User prefers Hinglish responses", kind="preference")
    assert a is not None
    assert b is None
    assert mgr.count() == 1


def test_manager_dedupe_can_be_disabled(mgr):
    a = mgr.remember("User prefers Hinglish responses", kind="preference")
    b = mgr.remember("User prefers Hinglish responses", kind="preference", dedupe=False)
    assert a is not None
    assert b is not None
    assert mgr.count() == 2


# ----------------------------------------------------------------------
# Manager — recall
# ----------------------------------------------------------------------
def test_manager_recall(mgr):
    mgr.remember("User's name is Siyak", kind="identity", importance=5)
    mgr.remember("User lives in India", kind="identity", importance=4)
    mgr.remember("User prefers dark mode", kind="preference", importance=3)

    hits = mgr.recall("what is the user's name")
    assert len(hits) >= 1
    assert any("Siyak" in h.content for h in hits)


def test_manager_recall_increments_usage(mgr):
    m = mgr.remember("User's name is Siyak", kind="identity", importance=5)
    assert m is not None
    mgr.recall("name")
    loaded = mgr.get(m.memory_id)
    assert loaded.use_count >= 1


def test_manager_recall_empty_query_returns_empty(mgr):
    mgr.remember("User's name is Siyak", kind="identity")
    assert mgr.recall("") == []


# ----------------------------------------------------------------------
# Manager — forget / restore
# ----------------------------------------------------------------------
def test_manager_forget_and_restore(mgr):
    m = mgr.remember("User's name is Siyak", kind="identity")
    assert mgr.count() == 1

    assert mgr.forget(m.memory_id) is True
    assert mgr.count() == 0

    assert mgr.restore(m.memory_id) is True
    assert mgr.count() == 1


def test_manager_forget_all(mgr):
    for i in range(3):
        mgr.remember(f"Fact number {i} about the user", kind="fact")
    assert mgr.count() == 3

    n = mgr.forget_all()
    assert n == 3
    assert mgr.count() == 0


# ----------------------------------------------------------------------
# Policies
# ----------------------------------------------------------------------
def test_policy_rejects_short_content():
    from memory.policies import is_worth_storing
    assert is_worth_storing(content="hi", confidence=0.9) is False
    assert is_worth_storing(content="this is fine", confidence=0.9) is True


def test_policy_rejects_low_confidence():
    from memory.policies import is_worth_storing
    assert is_worth_storing(content="something useful", confidence=0.1) is False
    assert is_worth_storing(content="something useful", confidence=0.6) is True


def test_should_extract():
    from memory.policies import should_extract
    assert should_extract(message_count=0) is False
    assert should_extract(message_count=1) is False
    assert should_extract(message_count=2) is True