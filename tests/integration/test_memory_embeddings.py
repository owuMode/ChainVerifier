# tests/integration/test_memory_embeddings.py
"""
Tests for the embedding-aware memory subsystem.
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


# ----------------------------------------------------------------------
# Blob round-trip
# ----------------------------------------------------------------------
def test_blob_roundtrip():
    from memory.embeddings import from_blob, to_blob

    v = (0.1, 0.2, 0.3, 0.4)
    blob = to_blob(v)
    assert isinstance(blob, bytes)

    arr = from_blob(blob, dim=4)
    assert arr.shape == (4,)
    for a, b in zip(arr, v):
        assert abs(float(a) - b) < 1e-6


def test_cosine_similarity():
    from memory.embeddings import cosine_similarity
    import numpy as np

    a = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    c = np.array([0.0, 1.0, 0.0], dtype=np.float32)

    assert abs(cosine_similarity(a, b) - 1.0) < 1e-6
    assert abs(cosine_similarity(a, c)) < 1e-6


# ----------------------------------------------------------------------
# Repository — embedding storage
# ----------------------------------------------------------------------
def test_repo_set_and_read_embedding(repo):
    from memory.repositories import Memory

    m = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="hello world"))
    repo.set_embedding(m.memory_id, values=(0.1, 0.2, 0.3), provider="gemini", model="text-embedding-004")

    loaded = repo.get(m.memory_id)
    assert loaded.has_embedding()
    assert loaded.embedding_provider == "gemini"
    assert loaded.embedding_model == "text-embedding-004"
    assert loaded.embedding_dim == 3

    vec = loaded.vector()
    assert vec is not None
    assert vec.shape == (3,)


def test_repo_list_with_embedding(repo):
    from memory.repositories import Memory

    a = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="one"))
    b = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="two"))
    c = repo.create(Memory(memory_id="", user_id="default", kind="fact", content="three"))

    repo.set_embedding(a.memory_id, values=(1.0, 0.0), provider="gemini", model="x")
    repo.set_embedding(b.memory_id, values=(0.0, 1.0), provider="gemini", model="x")
    # c has no embedding

    with_emb = repo.list_with_embedding(provider="gemini")
    assert len(with_emb) == 2
    assert {m.memory_id for m in with_emb} == {a.memory_id, b.memory_id}

    # Different provider → nothing
    assert repo.list_with_embedding(provider="openai") == []


# ----------------------------------------------------------------------
# Manager — hybrid recall
# ----------------------------------------------------------------------
class _FakeEmbeddingService:
    """
    Deterministic toy embedding: a 3-dim vector derived from keywords
    in the text.
    """

    def __init__(self):
        self.calls = 0

    def is_available(self):
        return True

    def embed_text(self, text):
        from memory.embeddings import EmbeddedVector
        v = self._vector_for(text)
        return EmbeddedVector(values=v, provider="fake", model="fake-3d", dim=3)

    def embed_texts(self, texts):
        return [self.embed_text(t) for t in texts]

    @staticmethod
    def _vector_for(text):
        t = (text or "").lower()
        if "coffee" in t:
            return (1.0, 0.0, 0.0)
        if "hinglish" in t or "language" in t or "reply" in t:
            return (0.0, 1.0, 0.0)
        if "name" in t or "siyak" in t:
            return (0.0, 0.0, 1.0)
        return (0.5, 0.5, 0.5)


@pytest.fixture
def mgr(repo):
    from memory.manager import MemoryManager
    return MemoryManager(repo, embedding_service=_FakeEmbeddingService())


def test_manager_stores_embedding_on_remember(mgr):
    m = mgr.remember("User likes coffee", kind="preference")
    assert m is not None
    loaded = mgr.get(m.memory_id)
    assert loaded.has_embedding()
    assert loaded.embedding_provider == "fake"


def test_manager_hybrid_recall_uses_vector(mgr):
    mgr.remember("User likes coffee", kind="preference")
    mgr.remember("User prefers Hinglish replies", kind="preference")
    mgr.remember("User's name is Siyak", kind="identity")

    # Query that shares no keywords with "coffee" but should hit vector.
    hits = mgr.recall_ranked("coffee", top_k=3)
    assert len(hits) >= 1
    assert hits[0].memory.content.lower().startswith("user likes coffee")


def test_manager_recall_works_without_embedder(repo):
    from memory.manager import MemoryManager

    plain_mgr = MemoryManager(repo)  # no embedding service
    plain_mgr.remember("User likes coffee", kind="preference")

    hits = plain_mgr.recall("coffee")
    assert len(hits) >= 1
    assert "coffee" in hits[0].content.lower()