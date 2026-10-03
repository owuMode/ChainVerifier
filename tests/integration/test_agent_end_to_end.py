# tests/integration/test_agent_end_to_end.py
"""
End-to-end agent test using a real tool and a fake provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.agent.agent import Agent
from core.agent.executor import Executor
from core.agent.planner import Planner
from core.agent.recovery import Recovery
from core.agent.verifier import Verifier
from core.agent.state_machine import TaskState
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


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


def _tools_root() -> Path:
    return Path(__file__).resolve().parents[2] / "tools"


def _prompts_root() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


@pytest.fixture
def stack(tmp_path: Path):
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    bus = EventBus()
    tasks = TaskManager(TaskRepository(db), bus)
    registry = ToolRegistry()
    discover_tools(_tools_root(), registry)
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
    """
    Returns a scripted JSON plan from generate_structured().
    """
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
    prompts = PromptManager(_prompts_root())
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
# Tests
# ----------------------------------------------------------------------
def test_happy_path_completes(stack):
    agent = _make_agent(stack, [
        {"tool_id": "datetime", "arguments": {}},
    ])
    task = stack["tasks"].create("run one step")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.COMPLETED
    assert result.steps_completed == 1

    reloaded = stack["tasks"].get(task.task_id)
    assert reloaded.status == TaskState.COMPLETED.value


def test_unknown_tool_in_plan_is_dropped(stack):
    agent = _make_agent(stack, [
        {"tool_id": "not_a_real_tool", "arguments": {}},
    ])
    task = stack["tasks"].create("run unknown tool")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED


def test_verification_failure_fails_task(stack):
    # filesystem (MODERATE) will be denied by default policy → FAILED.
    agent = _make_agent(stack, [
        {"tool_id": "filesystem", "arguments": {"action": "list", "path": "~/Desktop"}},
    ])
    task = stack["tasks"].create("bad args")
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED
    reloaded = stack["tasks"].get(task.task_id)
    assert reloaded.status == TaskState.FAILED.value


def test_cancellation_produces_cancelled_not_failed(stack):
    agent = _make_agent(stack, [
        {"tool_id": "datetime", "arguments": {}},
    ])
    task = stack["tasks"].create("will be cancelled")
    stack["tasks"].request_cancel(task.task_id)
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.CANCELLED

    reloaded = stack["tasks"].get(task.task_id)
    assert reloaded.status == TaskState.CANCELLED.value


def test_max_steps_enforced(stack):
    # Plan has 3 steps; task.max_steps = 1.
    agent = _make_agent(stack, [
        {"tool_id": "datetime", "arguments": {}},
        {"tool_id": "datetime", "arguments": {}},
        {"tool_id": "datetime", "arguments": {}},
    ])
    task = stack["tasks"].create("too many steps", max_steps=1)
    result = agent.run(task.task_id)
    assert result.final_state is TaskState.FAILED
    reloaded = stack["tasks"].get(task.task_id)
    assert "max_steps" in (reloaded.error or "")