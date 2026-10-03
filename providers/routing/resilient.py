# providers/routing/resilient.py
"""
ResilientProvider — an AIProvider wrapper that walks the router's
candidate chain until one succeeds.

Used by chat, planner, synthesizer, classifier, and memory extraction
so they all benefit from model fallback without any code changes.
"""

from __future__ import annotations

from typing import Iterator, Optional

from applog.logger import get_logger
from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import ChatRequest, ChatResponse, StreamChunk
from providers.base.provider import (
    AIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderResponseError,
)

log = get_logger("providers.resilient")


# How long a model stays in cooldown after a retryable failure.
COOLDOWN_RETRYABLE_S = 60
# How long a model stays in cooldown after a "model not found" error.
COOLDOWN_NOT_FOUND_S = 600


class ResilientProvider(AIProvider):
    """
    Wraps multiple concrete providers behind a single AIProvider
    interface. On every call it walks the router's candidate list and
    returns the first successful response.

    If all candidates fail, raises ProviderError with a clear message.
    """

    adapter_name = "resilient"

    def __init__(
        self,
        *,
        router,
        health=None,
        provider_id: str = "resilient",
    ) -> None:
        self._router = router
        self._health = health
        self.provider_id = provider_id
        # Track which provider/model handled the last successful call
        # so callers (e.g. tests, status bridge) can see it.
        self.last_provider_id: Optional[str] = None
        self.last_model: Optional[str] = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def get_models(self) -> tuple[ModelCapabilities, ...]:
        seen: list[ModelCapabilities] = []
        for dec in self._router.list_candidates():
            if dec.capabilities not in seen:
                seen.append(dec.capabilities)
        return tuple(seen)

    def supports(
        self, capability: Capability, model: Optional[str] = None
    ) -> bool:
        for dec in self._router.list_candidates():
            if model is not None and dec.model != model:
                continue
            if dec.capabilities.has(capability):
                return True
        return False

    def validate_connection(self) -> None:
        """Raise if no candidate is usable."""
        if not self._router.list_candidates():
            raise ProviderError(
                "no usable provider configured",
                error_code="no_active_provider",
                retryable=False,
            )

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------
    def chat(self, request: ChatRequest) -> ChatResponse:
        errors: list[str] = []
        for dec in self._router.list_candidates():
            try:
                resp = dec.provider.chat(self._replace_model(request, dec.model))
            except ProviderAuthError as exc:
                self._mark_auth_error(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: auth error")
                continue
            except ProviderResponseError as exc:
                if self._is_model_not_found(exc):
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_NOT_FOUND_S,
                    )
                    errors.append(f"{dec.provider_id}/{dec.model}: model not found")
                    continue
                if self._is_retryable_response(exc):
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_RETRYABLE_S,
                    )
                    errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                    continue
                # Permanent response error → next candidate.
                self._mark_cooldown(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue
            except ProviderNetworkError as exc:
                self._mark_cooldown(
                    dec.provider_id, dec.model, exc,
                    cooldown_s=COOLDOWN_RETRYABLE_S,
                )
                errors.append(f"{dec.provider_id}/{dec.model}: network")
                continue
            except ProviderError as exc:
                # Unknown provider error → cooldown + next.
                self._mark_cooldown(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue

            self._mark_success(dec.provider_id, dec.model)
            self.last_provider_id = dec.provider_id
            self.last_model = dec.model
            return resp

        # All candidates failed.
        raise ProviderError(
            "all providers unavailable: " + ("; ".join(errors[:3]) or "no candidates"),
            error_code="all_providers_failed",
            retryable=True,
        )

    # ------------------------------------------------------------------
    # stream
    # ------------------------------------------------------------------
    def stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        """
        Streaming fallback: we walk candidates until one starts
        emitting bytes. If a candidate fails BEFORE emitting anything
        we move on. If it fails AFTER emitting, we surface the error
        (can't retry mid-stream cleanly).
        """
        errors: list[str] = []
        for dec in self._router.list_candidates():
            emitted_anything = False
            try:
                for chunk in dec.provider.stream(self._replace_model(request, dec.model)):
                    emitted_anything = True
                    yield chunk
                # Stream completed cleanly.
                self._mark_success(dec.provider_id, dec.model)
                self.last_provider_id = dec.provider_id
                self.last_model = dec.model
                return
            except ProviderAuthError as exc:
                if emitted_anything:
                    raise
                self._mark_auth_error(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: auth error")
                continue
            except ProviderResponseError as exc:
                if emitted_anything:
                    raise
                if self._is_model_not_found(exc):
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_NOT_FOUND_S,
                    )
                else:
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_RETRYABLE_S,
                    )
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue
            except ProviderNetworkError as exc:
                if emitted_anything:
                    raise
                self._mark_cooldown(
                    dec.provider_id, dec.model, exc,
                    cooldown_s=COOLDOWN_RETRYABLE_S,
                )
                errors.append(f"{dec.provider_id}/{dec.model}: network")
                continue
            except ProviderError as exc:
                if emitted_anything:
                    raise
                self._mark_cooldown(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue

        raise ProviderError(
            "all providers unavailable (stream): "
            + ("; ".join(errors[:3]) or "no candidates"),
            error_code="all_providers_failed",
            retryable=True,
        )

    # ------------------------------------------------------------------
    # generate_structured
    # ------------------------------------------------------------------
    def generate_structured(self, request: ChatRequest, schema: dict) -> dict:
        errors: list[str] = []
        for dec in self._router.list_candidates():
            try:
                out = dec.provider.generate_structured(
                    self._replace_model(request, dec.model), schema
                )
            except ProviderAuthError as exc:
                self._mark_auth_error(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: auth error")
                continue
            except ProviderResponseError as exc:
                if self._is_model_not_found(exc):
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_NOT_FOUND_S,
                    )
                else:
                    self._mark_cooldown(
                        dec.provider_id, dec.model, exc,
                        cooldown_s=COOLDOWN_RETRYABLE_S,
                    )
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue
            except ProviderNetworkError as exc:
                self._mark_cooldown(
                    dec.provider_id, dec.model, exc,
                    cooldown_s=COOLDOWN_RETRYABLE_S,
                )
                errors.append(f"{dec.provider_id}/{dec.model}: network")
                continue
            except ProviderError as exc:
                self._mark_cooldown(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}/{dec.model}: {exc}")
                continue

            self._mark_success(dec.provider_id, dec.model)
            self.last_provider_id = dec.provider_id
            self.last_model = dec.model
            return out

        raise ProviderError(
            "all providers unavailable (structured): "
            + ("; ".join(errors[:3]) or "no candidates"),
            error_code="all_providers_failed",
            retryable=True,
        )

    # ------------------------------------------------------------------
    # embed (best-effort; not all providers support it)
    # ------------------------------------------------------------------
    def embed(
        self, texts: tuple[str, ...], *, model: Optional[str] = None
    ) -> tuple[tuple[float, ...], ...]:
        errors: list[str] = []
        for dec in self._router.list_candidates():
            try:
                return dec.provider.embed(texts, model=model)
            except NotImplementedError:
                errors.append(f"{dec.provider_id}: no embeddings")
                continue
            except ProviderError as exc:
                if getattr(exc, "error_code", "") == "embeddings_unsupported":
                    errors.append(f"{dec.provider_id}: no embeddings")
                    continue
                self._mark_cooldown(dec.provider_id, dec.model, exc)
                errors.append(f"{dec.provider_id}: {exc}")
                continue
            except Exception as exc:
                errors.append(f"{dec.provider_id}: {type(exc).__name__}")
                continue

        raise ProviderError(
            "no provider supports embeddings: " + ("; ".join(errors[:3]) or "none"),
            error_code="embeddings_unsupported",
            retryable=False,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _replace_model(request: ChatRequest, model: str) -> ChatRequest:
        if request.model == model:
            return request
        return ChatRequest(
            model=model,
            messages=request.messages,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            tools=request.tools,
            stream=request.stream,
            metadata=request.metadata,
        )

    def _mark_success(self, provider_id: str, model: str) -> None:
        if self._health is not None:
            self._health.record_success(provider_id, model)

    def _mark_cooldown(
        self,
        provider_id: str,
        model: str,
        exc: Exception,
        *,
        cooldown_s: int = COOLDOWN_RETRYABLE_S,
    ) -> None:
        if self._health is None:
            return
        try:
            self._health.record_failure(
                provider_id, model,
                reason=str(exc),
                cooldown_s=cooldown_s,
            )
        except Exception:
            log.exception("resilient: record_failure failed")

    def _mark_auth_error(
        self, provider_id: str, model: str, exc: Exception
    ) -> None:
        if self._health is None:
            return
        try:
            self._health.record_auth_error(provider_id)
        except Exception:
            log.exception("resilient: record_auth_error failed")

    @staticmethod
    def _is_model_not_found(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "http 404" in msg or "model not found" in msg

    @staticmethod
    def _is_retryable_response(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "http 429" in msg
            or "http 503" in msg
            or "http 502" in msg
            or "http 504" in msg
            or "rate limit" in msg
            or "unavailable" in msg
        )