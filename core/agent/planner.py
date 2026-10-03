# core/agent/planner.py
"""
Planner — turns a goal into a structured DAG of steps (spec §29, §51).

Phase 3: reasoning + replan + max-steps guard for multi-file reads.

Cache policy: only SUCCESSFUL, NON-EMPTY plans are cached. Empty or
error plans are never cached, so a regenerate can retry a fresh
planner call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from applog.logger import get_logger
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError
from security.validation import validate
from tools.registry.registry import ToolRegistry

log = get_logger("core.agent.planner")


MAX_CONTEXT_MESSAGES = 10
MAX_CONTEXT_CHARS = 800
MAX_STEPS_HARD_CAP = 20
MAX_REASONING_CHARS = 2000


_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "maxLength": MAX_REASONING_CHARS},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_id": {"type": "string"},
                    "tool_id": {"type": "string", "minLength": 1},
                    "arguments": {"type": "object"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["tool_id", "arguments"],
            },
        },
    },
    "required": ["steps"],
}


@dataclass(frozen=True)
class PlanStep:
    step_id: str
    tool_id: str
    arguments: dict[str, Any]
    depends_on: tuple[str, ...] = ()
    rationale: str = ""


@dataclass
class Plan:
    steps: list[PlanStep] = field(default_factory=list)
    raw_model_output: str = ""
    error: str | None = None
    from_cache: bool = False
    reasoning: str = ""

    def is_empty(self) -> bool:
        return not self.steps

    def step_by_id(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None


class Planner:
    def __init__(
        self,
        provider: AIProvider,
        registry: ToolRegistry,
        prompts: PromptManager,
        *,
        memory_manager=None,
        cache=None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._prompts = prompts
        self._memory = memory_manager
        self._cache = cache
        self._system_prompt = self._prompts.get("agent/planner").text
        try:
            self._replan_system_prompt = self._prompts.get("agent/replanner").text
        except Exception:
            log.warning("replanner prompt missing, using planner prompt")
            self._replan_system_prompt = self._system_prompt

    # ------------------------------------------------------------------
    def plan(
        self,
        goal: str,
        model: str,
        *,
        context_messages: Optional[list[dict[str, str]]] = None,
    ) -> Plan:
        log.info(
            "planner: called",
            extra={
                "goal": goal[:100],
                "model": model,
                "context_messages": len(context_messages or []),
            },
        )

        cached = self._cache_get(goal, context_messages, model)
        if cached is not None:
            log.info("planner: cache hit")
            return cached

        enriched_goal = self._enrich_with_memory(goal)
        tools_summary = self._tools_for_prompt()
        prompt = _build_plan_prompt(
            enriched_goal,
            tools_summary,
            context_messages=context_messages,
        )

        raw = self._call_provider(
            system_prompt=self._system_prompt,
            user_prompt=prompt,
            context_messages=context_messages,
            model=model,
        )
        if raw is None:
            return Plan(error="planner: provider call failed")

        errors = validate(_PLAN_SCHEMA, raw)
        if errors:
            log.warning("planner: schema invalid: %s", "; ".join(errors[:3]))
            return Plan(
                raw_model_output=json.dumps(raw),
                error=f"schema errors: {errors[0]}",
            )

        reasoning = str(raw.get("reasoning", "")).strip()[:MAX_REASONING_CHARS]

        steps = _steps_from_raw(raw, self._registry)
        if steps is None:
            return Plan(
                raw_model_output=json.dumps(raw),
                error="DAG error: invalid step graph",
            )

        dag_error = _validate_dag(steps)
        if dag_error:
            log.warning("planner: DAG invalid: %s", dag_error)
            return Plan(
                steps=steps,
                raw_model_output=json.dumps(raw),
                error=f"DAG error: {dag_error}",
            )

        plan = Plan(
            steps=steps,
            raw_model_output=json.dumps(raw),
            reasoning=reasoning,
        )

        # Only cache successful, non-empty plans.
        # Empty plans are NEVER cached, so regenerating retries a
        # fresh LLM call.
        if not plan.is_empty():
            self._cache_put(goal, context_messages, model, raw)

        log.info(
            "planner: plan built",
            extra={
                "steps": len(steps),
                "independent": sum(1 for s in steps if not s.depends_on),
                "has_reasoning": bool(reasoning),
                "cached": not plan.is_empty(),
            },
        )
        return plan

    # ------------------------------------------------------------------
    def replan(
        self,
        *,
        goal: str,
        original_plan: Plan,
        completed_steps: list[dict[str, Any]],
        failed_step: dict[str, Any],
        model: str,
        context_messages: Optional[list[dict[str, str]]] = None,
    ) -> Plan:
        log.info(
            "replanner: called",
            extra={
                "goal": goal[:100],
                "completed_count": len(completed_steps),
                "failed_step": failed_step.get("step_id"),
            },
        )

        enriched_goal = self._enrich_with_memory(goal)
        tools_summary = self._tools_for_prompt()

        original_steps = [
            {
                "step_id": s.step_id,
                "tool_id": s.tool_id,
                "arguments": s.arguments,
                "depends_on": list(s.depends_on),
                "rationale": s.rationale,
            }
            for s in original_plan.steps
        ]

        payload: dict[str, Any] = {
            "goal": enriched_goal,
            "original_plan": {
                "reasoning": original_plan.reasoning,
                "steps": original_steps,
            },
            "completed_steps": completed_steps,
            "failed_step": failed_step,
            "available_tools": tools_summary,
            "output_format": {
                "reasoning": "string",
                "steps": [
                    {
                        "step_id": "s1",
                        "tool_id": "string",
                        "arguments": {},
                        "depends_on": [],
                        "rationale": "string",
                    }
                ],
            },
        }
        if context_messages:
            payload["recent_conversation"] = _compact_context(context_messages)

        prompt = json.dumps(payload, ensure_ascii=False, indent=2)

        raw = self._call_provider(
            system_prompt=self._replan_system_prompt,
            user_prompt=prompt,
            context_messages=context_messages,
            model=model,
        )
        if raw is None:
            return Plan(error="replanner: provider call failed")

        errors = validate(_PLAN_SCHEMA, raw)
        if errors:
            return Plan(
                raw_model_output=json.dumps(raw),
                error=f"schema errors: {errors[0]}",
            )

        reasoning = str(raw.get("reasoning", "")).strip()[:MAX_REASONING_CHARS]

        steps = _steps_from_raw(raw, self._registry)
        if steps is None:
            return Plan(
                raw_model_output=json.dumps(raw),
                error="DAG error: invalid step graph",
            )

        dag_error = _validate_dag(steps)
        if dag_error:
            return Plan(
                steps=steps,
                raw_model_output=json.dumps(raw),
                error=f"DAG error: {dag_error}",
            )

        log.info(
            "replanner: plan built",
            extra={"steps": len(steps), "has_reasoning": bool(reasoning)},
        )
        return Plan(
            steps=steps,
            raw_model_output=json.dumps(raw),
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    def _enrich_with_memory(self, goal: str) -> str:
        if self._memory is None:
            return goal
        try:
            block = self._memory.recall_block(goal)
            if block:
                log.info(
                    "planner: injected memory block",
                    extra={"chars": len(block)},
                )
                return f"{block}\n\n## Current goal\n{goal}"
        except Exception:
            log.exception("planner: memory injection failed")
        return goal

    # ------------------------------------------------------------------
    def _call_provider(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
    ) -> Optional[dict]:
        messages: list[ChatMessage] = [
            ChatMessage(role=Role.SYSTEM, content=system_prompt),
        ]
        if context_messages:
            for msg in context_messages[-MAX_CONTEXT_MESSAGES:]:
                role_raw = str(msg.get("role", "")).strip().lower()
                content = str(msg.get("content", "")).strip()
                if not content or role_raw not in ("user", "assistant"):
                    continue
                if len(content) > MAX_CONTEXT_CHARS:
                    content = content[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
                role = Role.USER if role_raw == "user" else Role.ASSISTANT
                messages.append(ChatMessage(role=role, content=content))

        messages.append(ChatMessage(role=Role.USER, content=user_prompt))

        request = ChatRequest(
            model=model,
            messages=tuple(messages),
            temperature=0.0,
        )

        try:
            log.info("planner: calling provider.generate_structured")
            raw = self._provider.generate_structured(request, _PLAN_SCHEMA)
            log.info(
                "planner: provider returned",
                extra={"raw_keys": list(raw.keys())},
            )
            return raw if isinstance(raw, dict) else None
        except ProviderError as exc:
            log.warning("planner: provider error: %s", exc)
            return None
        except Exception:
            log.exception("planner: unexpected error")
            return None

    # ------------------------------------------------------------------
    def _cache_get(
        self,
        goal: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
    ) -> Optional[Plan]:
        if self._cache is None:
            return None
        try:
            cached = self._cache.get(
                goal=goal,
                context_messages=context_messages,
                model=model,
            )
        except Exception:
            log.exception("planner: cache get failed")
            return None
        if cached is None:
            return None
        try:
            raw = cached.plan_dict
            steps = _steps_from_raw(raw, self._registry)
            if steps is None:
                return None
            # Never return a cached empty plan.
            if not steps:
                return None
            reasoning = str(raw.get("reasoning", "")).strip()[:MAX_REASONING_CHARS]
            return Plan(
                steps=steps,
                raw_model_output=json.dumps(raw),
                from_cache=True,
                reasoning=reasoning,
            )
        except Exception:
            log.exception("planner: cache deserialize failed")
            return None

    def _cache_put(
        self,
        goal: str,
        context_messages: Optional[list[dict[str, str]]],
        model: str,
        raw: dict,
    ) -> None:
        if self._cache is None:
            return
        # Never cache empty plans.
        raw_steps = raw.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            log.info("planner: not caching empty plan")
            return
        try:
            self._cache.put(
                goal=goal,
                context_messages=context_messages,
                model=model,
                plan_dict=raw,
            )
        except Exception:
            log.exception("planner: cache put failed")

    # ------------------------------------------------------------------
    def _tools_for_prompt(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for spec in self._registry.list_specs():
            out.append({
                "tool_id": spec.tool_id,
                "name": spec.name,
                "description": spec.description,
                "permission_level": spec.permission_level.label(),
                "input_schema": spec.input_schema,
            })
        return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _steps_from_raw(
    raw: dict, registry: ToolRegistry
) -> Optional[list[PlanStep]]:
    raw_steps = list(raw.get("steps", []))[:MAX_STEPS_HARD_CAP]
    steps: list[PlanStep] = []
    known_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        tool_id = str(raw_step.get("tool_id", "")).strip()
        if not registry.has(tool_id):
            log.warning("planner: unknown tool referenced: %s", tool_id)
            continue
        step_id = str(raw_step.get("step_id", "")).strip() or f"s{index + 1}"
        base_id = step_id
        counter = 1
        while step_id in known_ids:
            step_id = f"{base_id}_{counter}"
            counter += 1
        known_ids.add(step_id)
        raw_deps = raw_step.get("depends_on") or []
        if not isinstance(raw_deps, list):
            raw_deps = []
        depends_on = tuple(
            str(d).strip()
            for d in raw_deps
            if isinstance(d, str) and str(d).strip()
        )
        steps.append(
            PlanStep(
                step_id=step_id,
                tool_id=tool_id,
                arguments=dict(raw_step.get("arguments", {})),
                depends_on=depends_on,
                rationale=str(raw_step.get("rationale", "")),
            )
        )
    return steps


def _validate_dag(steps: list[PlanStep]) -> Optional[str]:
    if not steps:
        return None
    ids = {s.step_id for s in steps}
    for s in steps:
        for dep in s.depends_on:
            if dep == s.step_id:
                return f"step {s.step_id!r} depends on itself"
            if dep not in ids:
                return f"step {s.step_id!r} depends on unknown {dep!r}"
    graph: dict[str, list[str]] = {s.step_id: list(s.depends_on) for s in steps}
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {sid: WHITE for sid in ids}

    def dfs(node: str) -> bool:
        color[node] = GRAY
        for nxt in graph.get(node, []):
            if color[nxt] == GRAY:
                return True
            if color[nxt] == WHITE and dfs(nxt):
                return True
        color[node] = BLACK
        return False

    for sid in ids:
        if color[sid] == WHITE:
            if dfs(sid):
                return "plan contains a dependency cycle"
    return None


def _compact_context(
    context_messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    compact: list[dict[str, str]] = []
    for msg in context_messages[-MAX_CONTEXT_MESSAGES:]:
        role = str(msg.get("role", "")).strip().lower()
        content = str(msg.get("content", "")).strip()
        if not content or role not in ("user", "assistant"):
            continue
        if len(content) > MAX_CONTEXT_CHARS:
            content = content[: MAX_CONTEXT_CHARS - 1].rstrip() + "…"
        compact.append({"role": role, "content": content})
    return compact


def _build_plan_prompt(
    goal: str,
    tools_summary: list[dict[str, Any]],
    *,
    context_messages: Optional[list[dict[str, str]]] = None,
) -> str:
    payload: dict[str, Any] = {
        "goal": goal,
        "available_tools": tools_summary,
        "output_format": {
            "reasoning": "string",
            "steps": [
                {
                    "step_id": "s1",
                    "tool_id": "string",
                    "arguments": {},
                    "depends_on": [],
                    "rationale": "string",
                }
            ],
        },
    }
    if context_messages:
        compact = _compact_context(context_messages)
        if compact:
            payload["recent_conversation"] = compact
    return json.dumps(payload, ensure_ascii=False, indent=2)