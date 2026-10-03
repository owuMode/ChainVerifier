# tests/integration/test_database_roundtrip.py
"""
Real round-trip test:
  open DB → migrations applied → write setting → write conversation + messages
  → close → reopen → verify everything is still there.
"""

from __future__ import annotations

from pathlib import Path

from database.manager import DatabaseManager
from database.repositories import (
    ConversationsRepository,
    MessagesRepository,
    SettingsRepository,
)


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_database_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "app.sqlite"

    # --- First open: migrate, write ---
    db = DatabaseManager(db_path=db_path, migrations_dir=_migrations_dir())
    db.open()

    settings = SettingsRepository(db)
    settings.set("agent.max_steps", 42)
    assert settings.get("agent.max_steps") == 42

    convs = ConversationsRepository(db)
    conv = convs.create(title="hello")
    assert conv.conversation_id

    msgs = MessagesRepository(db)
    msgs.append(conv.conversation_id, "user", "hi")
    msgs.append(conv.conversation_id, "assistant", "hello back", metadata={"model": "test"})

    db.close()

    # --- Reopen: verify persistence ---
    db2 = DatabaseManager(db_path=db_path, migrations_dir=_migrations_dir())
    db2.open()
    try:
        settings2 = SettingsRepository(db2)
        assert settings2.get("agent.max_steps") == 42

        convs2 = ConversationsRepository(db2)
        loaded = convs2.get(conv.conversation_id)
        assert loaded is not None
        assert loaded.title == "hello"

        msgs2 = MessagesRepository(db2)
        history = msgs2.list_for_conversation(conv.conversation_id)
        assert [m.role for m in history] == ["user", "assistant"]
        assert history[0].content == "hi"
        assert history[1].metadata == {"model": "test"}

        # Cascade check: deleting the conversation must remove its messages.
        convs2.delete(conv.conversation_id)
        assert msgs2.list_for_conversation(conv.conversation_id) == []
    finally:
        db2.close()


# ----------------------------------------------------------------------
# Explicit conversation_id tests (used by the GUI)
# ----------------------------------------------------------------------
def test_create_with_explicit_id(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        convs = ConversationsRepository(db)
        conv = convs.create(title="explicit", conversation_id="client-id-123")
        assert conv.conversation_id == "client-id-123"

        loaded = convs.get("client-id-123")
        assert loaded is not None
        assert loaded.title == "explicit"
    finally:
        db.close()


def test_create_without_id_still_generates_uuid(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        convs = ConversationsRepository(db)
        conv = convs.create(title="auto")
        # UUIDv4 has 36 chars, 4 dashes
        assert len(conv.conversation_id) == 36
        assert conv.conversation_id.count("-") == 4
    finally:
        db.close()


def test_exists(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        convs = ConversationsRepository(db)
        assert convs.exists("nope") is False

        convs.create(title="x", conversation_id="known-id")
        assert convs.exists("known-id") is True
    finally:
        db.close()


def test_duplicate_explicit_id_raises(tmp_path: Path) -> None:
    import sqlite3
    import pytest

    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        convs = ConversationsRepository(db)
        convs.create(title="first", conversation_id="dup-id")
        with pytest.raises(sqlite3.IntegrityError):
            convs.create(title="second", conversation_id="dup-id")
    finally:
        db.close()


def test_delete_all(tmp_path: Path) -> None:
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        convs = ConversationsRepository(db)
        msgs = MessagesRepository(db)

        a = convs.create(title="a")
        b = convs.create(title="b")
        msgs.append(a.conversation_id, "user", "hi a")
        msgs.append(b.conversation_id, "user", "hi b")

        deleted = convs.delete_all()
        assert deleted == 2
        assert convs.list_recent() == []
        # Cascade: messages are gone too
        assert msgs.list_for_conversation(a.conversation_id) == []
        assert msgs.list_for_conversation(b.conversation_id) == []
    finally:
        db.close()