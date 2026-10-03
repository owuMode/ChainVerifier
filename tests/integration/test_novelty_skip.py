# tests/integration/test_novelty_skip.py
"""
Tests for the memory extraction novelty check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="module", autouse=True)
def _offscreen_qt():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield


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
def mgr(db):
    from memory.manager import MemoryManager
    from memory.repositories import MemoryRepository
    return MemoryManager(MemoryRepository(db))


class _CountingExtractor:
    def __init__(self):
        self.calls = 0

    def extract(self, *, messages, model, max_candidates=None):
        self.calls += 1
        return []


class _StubMessagesRepo:
    def __init__(self, messages):
        self._messages = messages

    def latest(self, conversation_id, limit=20):
        from dataclasses import dataclass

        @dataclass
        class _M:
            role: str
            content: str

        return [_M(role=r, content=c) for r, c in self._messages]


def test_novelty_skips_when_nothing_new(qt_app, mgr):
    """
    If the conversation only repeats known content, extraction is
    skipped (extractor.calls == 0).
    """
    from gui.web.memory_extract_worker import MemoryExtractWorker

    # Known memory
    mgr.remember("User likes coffee very much", kind="preference")

    extractor = _CountingExtractor()
    repo = _StubMessagesRepo([
        ("user", "I like coffee very much"),
        ("assistant", "Got it."),
    ])

    worker = MemoryExtractWorker(
        extractor=extractor,
        memory_manager=mgr,
        messages_repo=repo,
        conversation_id="test-conv",
        model="test",
    )
    worker._run_inner()

    assert extractor.calls == 0, "extractor should have been skipped"


def test_novelty_runs_when_new_content(qt_app, mgr):
    """
    If the conversation contains new tokens, extraction runs.
    """
    from gui.web.memory_extract_worker import MemoryExtractWorker

    mgr.remember("User likes coffee very much", kind="preference")

    extractor = _CountingExtractor()
    repo = _StubMessagesRepo([
        ("user", "I am working on a quantum computing project called Nebula"),
        ("assistant", "Interesting!"),
    ])

    worker = MemoryExtractWorker(
        extractor=extractor,
        memory_manager=mgr,
        messages_repo=repo,
        conversation_id="test-conv",
        model="test",
    )
    worker._run_inner()

    assert extractor.calls == 1, "extractor should have run"