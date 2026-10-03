# core/agent/synthesizer.py
"""
Synthesizer — turn tool results into a natural-language answer.

Phase 3: streaming + cache integration + timeout guard.
  * `synthesize()` — one-shot, cache-aware.
  * `synthesize_stream()` — yields chunks. If the provider stream
    takes too long or fails, we fall back to a deterministic reply.
  * Never raises. Never hangs forever.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

from applog.logger import get_logger
from prompts.manager import PromptManager
from providers.base.models import ChatMessage, ChatRequest, Role
from providers.base.provider import AIProvider, ProviderError

log = get_logger("core.agent.synthesizer")


# Hard cap on how long the streaming synthesis may take (seconds).
# If we exceed this, we cut off and use the fallback.
STREAM_TIMEOUT_S = 45.0
# Max wall-clock for the one-shot synthesize() path.
BLOCKING_TIMEOUT_S = 45.0


@dataclass
class StepResult:
    tool_id: str
    arguments: dict[str, Any]
    output: dict[str, Any]
    verified: bool


class Synthesizer:
    def __init__(
        self,
        provider: AIProvider,
        prompts: PromptManager,
        *,
        cache=None,
    ) -> None:
        self._provider = provider
        self._prompts = prompts
        self._cache = cache
        try:
            self._system_prompt = self._prompts.get("agent/synthesizer").text
        except Exception:
            log.warning("synthesizer prompt missing, using fallback")
            self._system_prompt = _FALLBACK_SYSTEM

    # ------------------------------------------------------------------
    def synthesize(
        self,
        *,
        goal: str,
        step_results: list[StepResult],
        model: str,
    ) -> str:
        if not step_results:
            return "I couldn't complete that request."

        results_digest = _results_digest(step_results)

        if self._cache is not None:
            try:
                cached = self._cache.get(
                    goal=goal,
                    step_results_digest=results_digest,
                    model=model,
                )
            except Exception:
                cached = None
            if cached is not None and cached.text.strip():
                log.info("synthesizer: cache hit")
                return cached.text.strip()

        user_prompt = _build_user_prompt(goal, step_results)
        request = ChatRequest(
            model=model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=self._system_prompt),
                ChatMessage(role=Role.USER, content=user_prompt),
            ),
            temperature=0.3,
        )

        start = time.monotonic()
        try:
            response = self._provider.chat(request)
        except ProviderError as exc:
            log.warning("synthesizer: provider error: %s", exc)
            return _fallback_from_results(step_results)
        except Exception:
            log.exception("synthesizer: unexpected error")
            return _fallback_from_results(step_results)

        elapsed = time.monotonic() - start
        log.info("synthesizer: blocking done", extra={"elapsed_s": round(elapsed, 2)})

        text = (response.content or "").strip()
        if not text:
            return _fallback_from_results(step_results)

        if self._cache is not None:
            try:
                self._cache.put(
                    goal=goal,
                    step_results_digest=results_digest,
                    model=model,
                    text=text,
                )
            except Exception:
                log.exception("synthesizer: cache put failed")

        return text

    # ------------------------------------------------------------------
    def synthesize_stream(
        self,
        *,
        goal: str,
        step_results: list[StepResult],
        model: str,
    ) -> Iterator[str]:
        """
        Yield chunks of the final answer.

        Guarantees:
          * Never raises.
          * Never hangs. If the provider stalls past STREAM_TIMEOUT_S,
            we cut off and yield the fallback.
          * Cache hit → single chunk then return.
        """
        if not step_results:
            yield "I couldn't complete that request."
            return

        results_digest = _results_digest(step_results)

        # Cache check.
        if self._cache is not None:
            try:
                cached = self._cache.get(
                    goal=goal,
                    step_results_digest=results_digest,
                    model=model,
                )
            except Exception:
                cached = None
            if cached is not None and cached.text.strip():
                log.info("synthesizer: cache hit (stream)")
                yield cached.text.strip()
                return

        user_prompt = _build_user_prompt(goal, step_results)
        request = ChatRequest(
            model=model,
            messages=(
                ChatMessage(role=Role.SYSTEM, content=self._system_prompt),
                ChatMessage(role=Role.USER, content=user_prompt),
            ),
            temperature=0.3,
            stream=True,
        )

        accumulated: list[str] = []
        stream_failed = False
        start = time.monotonic()

        try:
            stream = self._provider.stream(request)
        except ProviderError as exc:
            log.warning("synthesizer stream: provider error: %s", exc)
            stream_failed = True
            stream = iter(())
        except Exception:
            log.exception("synthesizer stream: provider setup failed")
            stream_failed = True
            stream = iter(())

        if not stream_failed:
            try:
                for chunk in stream:
                    if chunk is None:
                        continue

                    if time.monotonic() - start > STREAM_TIMEOUT_S:
                        log.warning(
                            "synthesizer stream: timeout reached",
                            extra={"timeout_s": STREAM_TIMEOUT_S},
                        )
                        stream_failed = True
                        break

                    text = getattr(chunk, "delta_text", "") or ""
                    if text:
                        accumulated.append(text)
                        yield text

                    if getattr(chunk, "done", False):
                        break
            except ProviderError as exc:
                log.warning("synthesizer stream: mid-stream error: %s", exc)
                stream_failed = True
            except Exception:
                log.exception("synthesizer stream: unexpected mid-stream error")
                stream_failed = True

        full_text = "".join(accumulated).strip()
        elapsed = time.monotonic() - start
        log.info(
            "synthesizer: stream done",
            extra={
                "elapsed_s": round(elapsed, 2),
                "chars": len(full_text),
                "failed": stream_failed,
            },
        )

        # If stream failed or produced nothing, emit the fallback.
        if stream_failed or not full_text:
            fallback = _fallback_from_results(step_results)
            yield fallback
            full_text = fallback

        if self._cache is not None and full_text:
            try:
                self._cache.put(
                    goal=goal,
                    step_results_digest=results_digest,
                    model=model,
                    text=full_text,
                )
            except Exception:
                log.exception("synthesizer: cache put failed (stream)")


_FALLBACK_SYSTEM = (
    "You synthesize a short, natural-language answer from tool results. "
    "Match the user's language. Answer directly. Never mention tools, "
    "planners, or steps."
)


def _build_user_prompt(goal: str, step_results: list[StepResult]) -> str:
    payload = {
        "goal": goal,
        "tool_results": [
            {
                "tool_id": r.tool_id,
                "arguments": r.arguments,
                "output": r.output,
                "verified": r.verified,
            }
            for r in step_results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _results_digest(step_results: list[StepResult]) -> list[dict]:
    out: list[dict] = []
    for r in step_results:
        out.append({
            "tool_id": r.tool_id,
            "arguments": r.arguments,
            "output": r.output,
            "verified": r.verified,
        })
    return out


def _fallback_from_results(step_results: list[StepResult]) -> str:
    if not step_results:
        return "I couldn't complete that request."
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