# tests/integration/test_agent_caches.py
"""
Tests for the planner and synthesizer caches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.agent.cache import PlanCache, SynthesisCache
from database.manager import DatabaseManager


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def db(tmp_path: Path):
    database = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_project_root() / "database" / "migrations",
    )
    database.open()
    try:
        yield database
    finally:
        database.close()


# ----------------------------------------------------------------------
# PlanCache
# ----------------------------------------------------------------------
def test_plan_cache_roundtrip(db):
    cache = PlanCache(db, ttl_seconds=3600)
    plan = {"steps": [{"tool_id": "datetime", "arguments": {}}]}

    cache.put(
        goal="test",
        context_messages=[],
        model="m1",
        plan_dict=plan,
    )
    hit = cache.get(goal="test", context_messages=[], model="m1")
    assert hit is not None
    assert hit.plan_dict == plan


def test_plan_cache_different_context_misses(db):
    cache = PlanCache(db, ttl_seconds=3600)
    cache.put(
        goal="test",
        context_messages=[{"role": "user", "content": "hi"}],
        model="m1",
        plan_dict={"steps": []},
    )
    hit = cache.get(goal="test", context_messages=[], model="m1")
    assert hit is None


def test_plan_cache_different_model_misses(db):
    cache = PlanCache(db, ttl_seconds=3600)
    cache.put(
        goal="test", context_messages=[], model="m1",
        plan_dict={"steps": []},
    )
    hit = cache.get(goal="test", context_messages=[], model="m2")
    assert hit is None


def test_plan_cache_ttl_zero_disables(db):
    cache = PlanCache(db, ttl_seconds=0)
    cache.put(
        goal="test", context_messages=[], model="m1",
        plan_dict={"steps": []},
    )
    assert cache.get(goal="test", context_messages=[], model="m1") is None


def test_plan_cache_increments_use_count(db):
    cache = PlanCache(db, ttl_seconds=3600)
    cache.put(
        goal="g", context_messages=[], model="m1",
        plan_dict={"steps": []},
    )
    cache.get(goal="g", context_messages=[], model="m1")
    cache.get(goal="g", context_messages=[], model="m1")
    row = db.connection.execute(
        "SELECT use_count FROM planner_cache;"
    ).fetchone()
    assert row["use_count"] >= 2


# ----------------------------------------------------------------------
# SynthesisCache
# ----------------------------------------------------------------------
def test_synth_cache_roundtrip(db):
    cache = SynthesisCache(db, ttl_seconds=3600)
    results = [{"tool_id": "datetime", "output": {"date": "x"}}]

    cache.put(
        goal="test",
        step_results_digest=results,
        model="m1",
        text="Answer",
    )
    hit = cache.get(
        goal="test",
        step_results_digest=results,
        model="m1",
    )
    assert hit is not None
    assert hit.text == "Answer"


def test_synth_cache_empty_text_not_stored(db):
    cache = SynthesisCache(db, ttl_seconds=3600)
    cache.put(
        goal="test",
        step_results_digest=[],
        model="m1",
        text="",
    )
    assert cache.get(
        goal="test", step_results_digest=[], model="m1"
    ) is None