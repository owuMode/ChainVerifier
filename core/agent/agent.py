# core/agent/agent.py
"""
Agent — the orchestrator (spec §1, §27, §29, §30, §33).

Phase 3: reasoning + replan + parallel + streaming synthesis +
non-blocking drain (fast cancel).
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional, Union

from applog.logger import get_logger
from core.agent.executor import Executor, StepOutcome
from core.agent.planner import Plan, Planner, PlanStep
from core.agent.policies import AgentLimits, AgentPolicy
from core.agent.recovery import Recovery, RecoveryAction
from core.agent.state_machine import TaskState
from core.agent.synthesizer import StepResult, Synthesizer
from core.agent.verifier import Verifier

if TYPE_CHECKING:
    from core.tasks.manager import TaskManager
    from core.tasks.models import Task

log = get_logger("core.agent")


_PLANNER_CONTEXT_LIMIT = 10
MAX_PARALLEL_STEPS = 4
MAX_REPLANS_PER_TASK = 2
# Non-blocking poll interval for futures.
_DRAIN_TIMEOUT_S = 0.5


class _StepSignal(str, Enum):
    RETRY = "retry"


_StepOutcome = Union[None, _StepSignal, TaskState]


@dataclass
class AgentRunResult:
    task_id: str
    final_state: TaskState
    steps_completed: int
    error: Optional[str] = None
    final_message: Optional[str] = None


@dataclass
class _StepExecution:
    step: PlanStep
    index: int
    success: bool
    step_result: Optional[StepResult] = None
    error: Optional[str] = None
    error_code: Optional[str] = None


@dataclass
class _Success:
    task_id: str
    results: list[StepResult]
    completed_payloads: list[dict]


@dataclass
class _Failure:
    task_id: str
    failure: Optional[_StepExecution]
    completed_results: list[StepResult]
    completed_payloads: list[dict]
    error: str
    cancelled: bool = False


class Agent:
    def __init__(
        self,
        *,
        planner: Planner,
        executor: Executor,
        verifier: Verifier,
        recovery: Recovery,
        tasks: "TaskManager",
        default_model: str,
        synthesizer: Optional[Synthesizer] = None,
        messages_repo=None,
    ) -> None:
        self._planner = planner
        self._executor = executor
        self._verifier = verifier
        self._recovery = recovery
        self._tasks = tasks
        self._default_model = default_model
        self._synthesizer = synthesizer
        self._messages_repo = messages_repo

    # ------------------------------------------------------------------
    def run(self, task_id: str) -> AgentRunResult:
        log.info("agent: run() entered", extra={"task_id": task_id})

        task = self._tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task_id: {task_id!r}")

        if task.is_terminal():
            return AgentRunResult(
                task_id=task_id,
                final_state=TaskState(task.status),
                steps_completed=task.current_step,
                error=task.error,
            )

        if task.cancel_requested:
            return self._finish_cancelled(task)

        limits = AgentLimits.from_task(task)
        start_time = time.monotonic()

        self._transition(task_id, TaskState.UNDERSTANDING)
        self._transition(task_id, TaskState.PLANNING)
        task = self._tasks.get(task_id)

        if task.cancel_requested:
            return self._finish_cancelled(task)

        context = self._load_planner_context(task)

        plan = self._planner.plan(
            task.goal,
            self._default_model,
            context_messages=context,
        )
        log.info(
            "agent: plan built",
            extra={
                "task_id": task_id,
                "steps": len(plan.steps),
                "error": plan.error,
                "context_messages": len(context),
                "has_reasoning": bool(plan.reasoning),
            },
        )

        if plan.error:
            return self._fail(task, plan.error)

        if plan.is_empty():
            reason = "planner returned an empty plan"
            msg = (
                f"I couldn't act on that request: {reason}. "
                f"Try rephrasing, or configure a different model in Settings."
            )
            return self._fail(task, msg)

        self._store_plan(task, plan)
        if plan.reasoning:
            self._publish_plan_reasoning(task_id, plan.reasoning, replan=False)

        completed_results: list[StepResult] = []
        completed_payloads: list[dict] = []
        replans_so_far = 0
        current_plan = plan

        while True:
            loop_result = self._execute_plan(
                task_id, current_plan, start_time, limits
            )

            if isinstance(loop_result, _Success):
                completed_results.extend(loop_result.results)
                completed_payloads.extend(loop_result.completed_payloads)
                break

            failure_result: _Failure = loop_result
            completed_results.extend(failure_result.completed_results)
            completed_payloads.extend(failure_result.completed_payloads)

            current_task = self._tasks.get(task_id)
            if current_task is None:
                return AgentRunResult(
                    task_id=task_id,
                    final_state=TaskState.FAILED,
                    steps_completed=len(completed_results),
                    error="task disappeared",
                    final_message="task disappeared",
                )

            if failure_result.cancelled or current_task.cancel_requested:
                return self._finish_cancelled(current_task)

            if failure_result.failure is None:
                return self._fail(current_task, failure_result.error)

            last_failure = failure_result.failure

            decision = self._recovery.decide(
                task=current_task,
                error_code=last_failure.error_code,
                error_message=last_failure.error,
                replans_so_far=replans_so_far,
            )
            log.info(
                "agent: recovery decision",
                extra={
                    "task_id": task_id,
                    "action": decision.action.value,
                    "reason": decision.reason,
                },
            )

            if decision.action is not RecoveryAction.REPLAN:
                return self._fail(
                    current_task,
                    last_failure.error or decision.reason,
                )

            if replans_so_far >= MAX_REPLANS_PER_TASK:
                return self._fail(
                    current_task,
                    f"replan budget exhausted "
                    f"({replans_so_far}/{MAX_REPLANS_PER_TASK}); "
                    f"last error: {last_failure.error}",
                )

            replans_so_far += 1

            try:
                self._transition(task_id, TaskState.RECOVERING)
                self._transition(task_id, TaskState.PLANNING)
            except Exception:
                log.exception("could not transition for replan")
                return self._fail(
                    current_task,
                    f"state transition for replan failed; "
                    f"last error: {last_failure.error}",
                )

            new_plan = self._planner.replan(
                goal=current_task.goal,
                original_plan=current_plan,
                completed_steps=completed_payloads,
                failed_step={
                    "step_id": last_failure.step.step_id,
                    "tool_id": last_failure.step.tool_id,
                    "arguments": last_failure.step.arguments,
                    "error": last_failure.error,
                    "error_code": last_failure.error_code,
                },
                model=self._default_model,
                context_messages=context,
            )
            log.info(
                "agent: replan built",
                extra={
                    "task_id": task_id,
                    "steps": len(new_plan.steps),
                    "error": new_plan.error,
                    "replans_so_far": replans_so_far,
                },
            )

            if new_plan.error or new_plan.is_empty():
                return self._fail(
                    current_task,
                    new_plan.error or "replanner returned an empty plan",
                )

            current_plan = new_plan
            self._store_plan(current_task, new_plan)
            if new_plan.reasoning:
                self._publish_plan_reasoning(
                    task_id, new_plan.reasoning, replan=True
                )

        task = self._tasks.get(task_id)
        if task is None:
            return AgentRunResult(
                task_id, TaskState.FAILED,
                len(completed_results), "task disappeared",
            )

        if task.cancel_requested:
            return self._finish_cancelled(task)

        if TaskState(task.status) is not TaskState.VERIFYING:
            return self._fail(
                task,
                f"unexpected state {task.status} at completion; "
                f"expected VERIFYING",
            )

        self._transition(task_id, TaskState.COMPLETED)

        final_msg = self._synthesize_answer_streaming(
            task_id, task, completed_results
        )

        return AgentRunResult(
            task_id=task_id,
            final_state=TaskState.COMPLETED,
            steps_completed=len(completed_results),
            final_message=final_msg,
        )

    # ------------------------------------------------------------------
    def _store_plan(self, task: "Task", plan: Plan) -> None:
        task.plan = [
            {
                "step_id": s.step_id,
                "tool_id": s.tool_id,
                "arguments": s.arguments,
                "depends_on": list(s.depends_on),
                "rationale": s.rationale,
            }
            for s in plan.steps
        ]
        try:
            self._tasks.update_plan(task)
        except Exception:
            log.exception("could not persist plan")

    def _publish_plan_reasoning(
        self, task_id: str, reasoning: str, *, replan: bool
    ) -> None:
        try:
            bus = getattr(self._executor, "_bus", None)
            if bus is None:
                return
            from core.events.events import EventType
            bus.publish(
                EventType.TASK_UPDATED,
                task_id=task_id,
                actor="agent",
                payload={
                    "reasoning": reasoning,
                    "replan": bool(replan),
                },
            )
        except Exception:
            log.exception("could not publish plan reasoning")

    def _publish_synthesis_chunk(self, task_id: str, text: str) -> None:
        try:
            bus = getattr(self._executor, "_bus", None)
            if bus is None:
                return
            from core.events.events import EventType
            bus.publish(
                EventType.SYNTHESIS_CHUNK,
                task_id=task_id,
                actor="agent",
                payload={"chunk": text},
            )
        except Exception:
            log.exception("could not publish synthesis chunk")

    # ------------------------------------------------------------------
    def _load_planner_context(self, task: "Task") -> list[dict[str, str]]:
        if self._messages_repo is None or not task.conversation_id:
            return []
        try:
            msgs = self._messages_repo.latest(
                task.conversation_id, limit=_PLANNER_CONTEXT_LIMIT
            )
        except Exception:
            log.exception("agent: failed to load planner context")
            return []
        out: list[dict[str, str]] = []
        for m in msgs:
            try:
                role = str(getattr(m, "role", "")).strip().lower()
                content = str(getattr(m, "content", "") or "").strip()
            except Exception:
                continue
            if not content or role not in ("user", "assistant"):
                continue
            out.append({"role": role, "content": content})
        return out

    # ------------------------------------------------------------------
    def _execute_plan(
        self,
        task_id: str,
        plan: Plan,
        start_time: float,
        limits: AgentLimits,
    ) -> Union[_Success, _Failure]:
        self._ensure_executing(task_id)

        step_index: dict[str, int] = {
            s.step_id: i for i, s in enumerate(plan.steps)
        }

        completed: dict[str, StepResult] = {}
        results: list[StepResult] = []
        completed_payloads: list[dict] = []
        scheduled: set[str] = set()
        done: set[str] = set()
        failure: Optional[_StepExecution] = None

        cancel_event = threading.Event()
        max_workers = min(MAX_PARALLEL_STEPS, max(1, len(plan.steps)))

        with ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="agent-step"
        ) as pool:
            pending: dict[Future, PlanStep] = {}

            while True:
                task = self._tasks.get(task_id)
                if task is None:
                    cancel_event.set()
                    for fut in pending:
                        fut.cancel()
                    return _Failure(
                        task_id=task_id,
                        failure=None,
                        completed_results=results,
                        completed_payloads=completed_payloads,
                        error="task disappeared",
                    )
                if task.cancel_requested:
                    cancel_event.set()
                    for fut in pending:
                        fut.cancel()
                    return _Failure(
                        task_id=task_id,
                        failure=None,
                        completed_results=results,
                        completed_payloads=completed_payloads,
                        error="cancelled",
                        cancelled=True,
                    )

                if not AgentPolicy.can_start_step(task):
                    cancel_event.set()
                    for fut in pending:
                        fut.cancel()
                    return _Failure(
                        task_id=task_id,
                        failure=None,
                        completed_results=results,
                        completed_payloads=completed_payloads,
                        error=f"max_steps reached ({task.max_steps})",
                    )

                if self._time_exceeded(
                    start_time, limits.max_execution_time_s
                ):
                    cancel_event.set()
                    for fut in pending:
                        fut.cancel()
                    return _Failure(
                        task_id=task_id,
                        failure=None,
                        completed_results=results,
                        completed_payloads=completed_payloads,
                        error="max_execution_time_s exceeded",
                    )

                ready = self._ready_steps(plan, completed, scheduled)
                for step in ready:
                    scheduled.add(step.step_id)
                    fut = pool.submit(
                        self._run_one_step,
                        task_id=task_id,
                        step=step,
                        step_index=step_index[step.step_id],
                        cancel_event=cancel_event,
                    )
                    pending[fut] = step

                if not pending:
                    remaining = [
                        s for s in plan.steps if s.step_id not in done
                    ]
                    if not remaining:
                        break
                    return _Failure(
                        task_id=task_id,
                        failure=None,
                        completed_results=results,
                        completed_payloads=completed_payloads,
                        error=f"plan stalled: unreachable steps "
                              f"{[s.step_id for s in remaining]}",
                    )

                done_futures = _drain_done(pending.keys())

                # Even if no future finished in this tick, keep looping
                # so we can react to cancel events.
                if not done_futures:
                    continue

                for fut in done_futures:
                    step = pending.pop(fut, None)
                    if step is None:
                        continue
                    done.add(step.step_id)

                    current = self._tasks.get(task_id)
                    if current is None or current.cancel_requested:
                        cancel_event.set()
                        for other in pending:
                            other.cancel()
                        return _Failure(
                            task_id=task_id,
                            failure=None,
                            completed_results=results,
                            completed_payloads=completed_payloads,
                            error=(
                                "task disappeared" if current is None
                                else "cancelled"
                            ),
                            cancelled=current is not None,
                        )

                    try:
                        exec_result: _StepExecution = fut.result()
                    except Exception as exc:
                        log.exception(
                            "agent: step thread raised",
                            extra={"step_id": step.step_id},
                        )
                        exec_result = _StepExecution(
                            step=step,
                            index=step_index[step.step_id],
                            success=False,
                            error=f"{type(exc).__name__}: {exc}",
                            error_code="step_exception",
                        )

                    if exec_result.success and exec_result.step_result is not None:
                        completed[step.step_id] = exec_result.step_result
                        results.append(exec_result.step_result)
                        completed_payloads.append({
                            "step_id": step.step_id,
                            "tool_id": step.tool_id,
                            "arguments": step.arguments,
                            "output": exec_result.step_result.output,
                        })
                        cur = self._tasks.get(task_id)
                        if cur is not None:
                            cur.current_step = min(
                                cur.current_step + 1, cur.max_steps
                            )
                            self._tasks.update_plan(cur)
                    else:
                        if failure is None:
                            failure = exec_result
                        cancel_event.set()
                        for other in pending:
                            other.cancel()
                        for other in list(pending.keys()):
                            try:
                                other.result(timeout=3)
                            except Exception:
                                pass
                        pending.clear()
                        break

                if failure is not None:
                    break

        if failure is not None:
            return _Failure(
                task_id=task_id,
                failure=failure,
                completed_results=results,
                completed_payloads=completed_payloads,
                error=failure.error or "step failed",
            )

        self._finalize_success_state(task_id)
        return _Success(
            task_id=task_id,
            results=results,
            completed_payloads=completed_payloads,
        )

    # ------------------------------------------------------------------
    def _ensure_executing(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        state = TaskState(task.status)
        if state is TaskState.PLANNING:
            self._transition(task_id, TaskState.EXECUTING)

    def _finalize_success_state(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        state = TaskState(task.status)
        if state is TaskState.EXECUTING:
            self._transition(task_id, TaskState.OBSERVING)
            self._transition(task_id, TaskState.VERIFYING)
        elif state is TaskState.OBSERVING:
            self._transition(task_id, TaskState.VERIFYING)

    # ------------------------------------------------------------------
    def _ready_steps(
        self,
        plan: Plan,
        completed: dict[str, StepResult],
        scheduled: set[str],
    ) -> list[PlanStep]:
        ready: list[PlanStep] = []
        for step in plan.steps:
            if step.step_id in scheduled:
                continue
            if all(dep in completed for dep in step.depends_on):
                ready.append(step)
        return ready

    # ------------------------------------------------------------------
    def _run_one_step(
        self,
        *,
        task_id: str,
        step: PlanStep,
        step_index: int,
        cancel_event: threading.Event,
    ) -> _StepExecution:
        if cancel_event.is_set():
            return _StepExecution(
                step=step, index=step_index, success=False,
                error="cancelled before start",
                error_code="cancelled",
            )

        task = self._tasks.get(task_id)
        if task is None:
            return _StepExecution(
                step=step, index=step_index, success=False,
                error="task disappeared", error_code="task_gone",
            )

        log.info(
            "agent: → EXECUTING (parallel)",
            extra={
                "task_id": task_id,
                "step_id": step.step_id,
                "step_index": step_index,
                "tool_id": step.tool_id,
            },
        )

        try:
            outcome: StepOutcome = self._executor.execute_step(
                tool_id=step.tool_id,
                arguments=step.arguments,
                task_id=task_id,
                session_id=task.conversation_id,
                step_index=step_index,
            )
        except Exception as exc:
            log.exception("agent: executor raised", extra={"step_id": step.step_id})
            return _StepExecution(
                step=step, index=step_index, success=False,
                error=f"{type(exc).__name__}: {exc}",
                error_code="executor_exception",
            )

        if cancel_event.is_set():
            return _StepExecution(
                step=step, index=step_index, success=False,
                error="cancelled during execution",
                error_code="cancelled",
            )

        if not outcome.ok:
            return _StepExecution(
                step=step, index=step_index, success=False,
                error=outcome.error or "tool failed",
                error_code=outcome.error_code or "tool_failed",
            )

        assert outcome.request is not None
        assert outcome.result is not None

        try:
            verification = self._verifier.verify(
                tool_id=step.tool_id,
                request=outcome.request,
                result=outcome.result,
                task_id=task_id,
                session_id=task.conversation_id,
            )
        except Exception as exc:
            log.exception("agent: verifier raised", extra={"step_id": step.step_id})
            return _StepExecution(
                step=step, index=step_index, success=False,
                error=f"verifier: {type(exc).__name__}",
                error_code="verifier_exception",
            )

        if not verification.verified:
            return _StepExecution(
                step=step, index=step_index, success=False,
                error=verification.reason or "verification failed",
                error_code="verification_failed",
            )

        step_result = StepResult(
            tool_id=step.tool_id,
            arguments=dict(step.arguments),
            output=dict(outcome.result.output) if outcome.result.output else {},
            verified=True,
        )
        return _StepExecution(
            step=step, index=step_index, success=True, step_result=step_result,
        )

    # ------------------------------------------------------------------
    def _synthesize_answer_streaming(
        self,
        task_id: str,
        task: "Task",
        step_results: list[StepResult],
    ) -> str:
        if not step_results:
            text = "Done — but there was nothing to report."
            self._publish_synthesis_chunk(task_id, text)
            return text

        if self._synthesizer is None:
            text = self._compose_fallback(step_results)
            self._publish_synthesis_chunk(task_id, text)
            return text

        accumulated: list[str] = []
        try:
            for chunk in self._synthesizer.synthesize_stream(
                goal=task.goal,
                step_results=step_results,
                model=self._default_model,
            ):
                if not chunk:
                    continue
                accumulated.append(chunk)
                self._publish_synthesis_chunk(task_id, chunk)
        except Exception:
            log.exception("agent: streaming synthesis raised")
            text = self._compose_fallback(step_results)
            self._publish_synthesis_chunk(task_id, text)
            return text

        full = "".join(accumulated).strip()
        if not full:
            full = self._compose_fallback(step_results)
            self._publish_synthesis_chunk(task_id, full)
        return full

    def _compose_fallback(self, step_results: list[StepResult]) -> str:
        if len(step_results) == 1:
            r = step_results[0]
            return (
                f"Done. I ran the {r.tool_id} tool and verified the result. "
                f"(See the tool card for the output.)"
            )
        tools = ", ".join(r.tool_id for r in step_results)
        return (
            f"Done. I ran {len(step_results)} step(s) — {tools} — and "
            f"verified every result. (See the tool cards for the output.)"
        )

    # ------------------------------------------------------------------
    def _time_exceeded(self, start_time: float, limit_s: int) -> bool:
        return (time.monotonic() - start_time) > limit_s

    def _transition(self, task_id: str, target: TaskState) -> None:
        self._tasks.transition(task_id, target)

    def _fail(self, task: "Task", reason: str) -> AgentRunResult:
        log.warning(
            "agent: FAILED",
            extra={"task_id": task.task_id, "reason": reason},
        )
        current = self._tasks.get(task.task_id)
        if current is not None:
            state = TaskState(current.status)
            if state in (TaskState.EXECUTING, TaskState.OBSERVING):
                try:
                    self._transition(task.task_id, TaskState.RECOVERING)
                except Exception:
                    pass
        try:
            self._tasks.transition(task.task_id, TaskState.FAILED, error=reason)
        except Exception:
            log.exception("could not transition to FAILED")
        return AgentRunResult(
            task_id=task.task_id,
            final_state=TaskState.FAILED,
            steps_completed=task.current_step,
            error=reason,
            final_message=reason,
        )

    def _finish_cancelled(self, task: "Task") -> AgentRunResult:
        log.info("agent: CANCELLED", extra={"task_id": task.task_id})
        try:
            self._tasks.transition(task.task_id, TaskState.CANCELLED)
        except Exception:
            log.exception("could not transition to CANCELLED")
        return AgentRunResult(
            task_id=task.task_id,
            final_state=TaskState.CANCELLED,
            steps_completed=task.current_step,
            final_message="Task cancelled.",
        )


# ----------------------------------------------------------------------
def _drain_done(futures, timeout_s: float = _DRAIN_TIMEOUT_S) -> list[Future]:
    """
    Non-blocking poll.

    Returns every future that has already completed. Waits at most
    `timeout_s` for at least one new completion, then returns whatever
    is ready (possibly []).
    """
    futures = list(futures)
    if not futures:
        return []
    try:
        done_iter = as_completed(futures, timeout=timeout_s)
        first = next(done_iter)
    except Exception:
        return []
    done: list[Future] = [first]
    for fut in futures:
        if fut is first:
            continue
        if fut.done():
            done.append(fut)
    return done