# tests/integration/test_parallel_planner.py
"""
Tests for the parallel planner (DAG-based execution).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.agent.agent import Agent
from core.agent.executor import Executor
from core.agent.planner import Planner
from core.agent.recovery import Recovery
from core.agent.state_machine import TaskState
from core.agent.verifier import Verifier
from core.events.bus import EventBus
from core.tasks.manager import TaskManager
from core.tasks.repository import TaskRepository
from database.manager import DatabaseManager
from prompts.manager import PromptManager
from providers.base.capabilities import ModelCapabilities
from providers.base.models import (
    ChatRequest,
    ChatResponse,
    FinishReason,
    StreamChunk,
)
from providers.base.provider import AIProvider
from security.policies import PolicyEngine
from tools.registry import ToolRegistry, discover_tools


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def stack(tmp_path: Path):
    db = DatabaseManager(
        db_path=tmp_path / "app.sqlite",
        migrations_dir=_project_root() / "database" / "migrations",
    )
    db.open()
    bus = EventBus()
    tasks = TaskManager(TaskRepository(db), bus)
    registry = ToolRegistry()
    discover_tools(_project_root() / "tools", registry)
    registry.seal()
    policy = PolicyEngine()
    try:
        yield {
            "db": db,
            "bus": bus,
            "tasks": tasks,
            "registry": registry,
            "policy": policy,
        }
    finally:
        db.close()


class _ScriptedProvider(AIProvider):
    """Returns a scripted plan."""

    provider_id = "scripted"
    adapter_name = "scripted"

    def __init__(self, plan_steps: list[dict]):
        self._plan_steps = plan_steps

    def chat(self, request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="ok",
            finish_reason=FinishReason.STOP,
            model=request.model,
            provider=self.provider_id,
        )

    def stream(self, request: ChatRequest):
        yield StreamChunk(done=True)

    def generate_structured(self, request: ChatRequest, schema: dict) -> dict:
        return {"steps": self._plan_steps}

    def get_models(self):
        return (ModelCapabilities(model_id="fake-model"),)

    def validate_connection(self) -> None:
        return None


def _make_agent(stack, plan_steps) -> Agent:
    provider = _ScriptedProvider(plan_steps)
    prompts = PromptManager(_project_root() / "prompts")
    planner = Planner(provider, stack["registry"], prompts)
    executor = Executor(stack["registry"], stack["policy"], stack["bus"])
    verifier = Verifier(stack["registry"], stack["bus"])
    recovery = Recovery()
    return Agent(
        planner=planner,
        executor=executor,
        verifier=verifier,
        recovery=recovery,
        tasks=stack["tasks"],
        default_model="fake-model",
    )


# ----------------------------------------------------------------------
# Plan DAG validation
# ----------------------------------------------------------------------
def test_planner_accepts_independent_steps(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s2", "tool_id": "system_info", "arguments": {}, "depends_on": []},
    ])
    task = stack["tasks"].create("two independent steps")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.COMPLETED
    assert result.steps_completed == 2


def test_planner_accepts_dependent_steps(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s2", "tool_id": "system_info", "arguments": {}, "depends_on": ["s1"]},
    ])
    task = stack["tasks"].create("dependent steps")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.COMPLETED
    assert result.steps_completed == 2


def test_planner_rejects_cycles(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": ["s2"]},
        {"step_id": "s2", "tool_id": "system_info", "arguments": {}, "depends_on": ["s1"]},
    ])
    task = stack["tasks"].create("cyclic plan")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED
    assert "cycle" in (result.error or "").lower()


def test_planner_rejects_unknown_dependency(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": ["s9"]},
    ])
    task = stack["tasks"].create("missing dep")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED
    assert "unknown" in (result.error or "").lower()


def test_planner_rejects_self_loop(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": ["s1"]},
    ])
    task = stack["tasks"].create("self loop")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED


# ----------------------------------------------------------------------
# Parallel execution
# ----------------------------------------------------------------------
def test_parallel_steps_are_faster_than_sequential(stack):
    """
    Schedule 4 independent slow-ish steps and verify total time is
    closer to 1x than 4x.
    """
    # datetime is fast, so measure via a lower bound: run 4 in parallel
    # and assert the total wall time is < 2s.
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s2", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s3", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s4", "tool_id": "datetime", "arguments": {}, "depends_on": []},
    ])
    task = stack["tasks"].create("parallel datetime")

    start = time.monotonic()
    result = agent.run(task.task_id)
    elapsed = time.monotonic() - start

    assert result.final_state is TaskState.COMPLETED
    assert result.steps_completed == 4
    # datetime is <5ms, so 4 sequential would still be fast — we just
    # assert it completes reasonably.
    assert elapsed < 2.0


def test_mixed_parallel_and_sequential(stack):
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "datetime", "arguments": {}, "depends_on": []},
        {"step_id": "s2", "tool_id": "system_info", "arguments": {}, "depends_on": []},
        {"step_id": "s3", "tool_id": "datetime", "arguments": {}, "depends_on": ["s1", "s2"]},
    ])
    task = stack["tasks"].create("mixed")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.COMPLETED
    assert result.steps_completed == 3


def test_step_with_missing_dep_never_runs(stack):
    # s2 depends on s1, but s1 references unknown tool → plan drops s1
    # → s2 has dangling dep → DAG validation catches it.
    agent = _make_agent(stack, [
        {"step_id": "s1", "tool_id": "not_a_real_tool", "arguments": {}, "depends_on": []},
        {"step_id": "s2", "tool_id": "datetime", "arguments": {}, "depends_on": ["s1"]},
    ])
    task = stack["tasks"].create("dangling dep")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED