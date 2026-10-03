# providers/base/provider.py
"""
AIProvider — the one interface Agent Core depends on (spec §14).

Agent Core must never import a specific adapter. It asks the
ProviderManager for the active AIProvider and calls methods on it.

Adapters implement:
    chat()                — one-shot response
    stream()              — iterator of StreamChunk
    generate_structured() — request JSON output, parse to dict
    get_models()          — declared models + capabilities
    validate_connection() — auth + reachability check
    supports()            — capability check
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Iterator

from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import ChatRequest, ChatResponse, StreamChunk


class ProviderError(Exception):
    """Base class for provider-originated errors."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "provider_error",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable


class ProviderAuthError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, error_code="auth_error", retryable=False)


class ProviderNetworkError(ProviderError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message, error_code="network_error", retryable=retryable)


class ProviderResponseError(ProviderError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message, error_code="response_error", retryable=retryable)


class AIProvider(ABC):
    """
    Contract every provider adapter must satisfy.

    `provider_id` is the user-facing identifier chosen at
    configuration time (e.g. "openai_compatible_main").
    `adapter_name` is the implementation family (e.g. "openai_compatible").
    """

    provider_id: str
    adapter_name: str

    # ------------------------------------------------------------------
    # Core calls
    # ------------------------------------------------------------------
    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        ...

    @abstractmethod
    def stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        ...

    @abstractmethod
    def generate_structured(
        self,
        request: ChatRequest,
        schema: dict,
    ) -> dict:
        ...

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @abstractmethod
    def get_models(self) -> tuple[ModelCapabilities, ...]:
        ...

    @abstractmethod
    def validate_connection(self) -> None:
        """Raise a ProviderError subclass on failure. Return None on success."""
        ...

    def supports(self, capability: Capability, model: str | None = None) -> bool:
        """
        Return True if the given (or active) model declares the capability.
        Adapters may override for dynamic detection.
        """
        models = self.get_models()
        if not models:
            return False
        if model is None:
            return any(m.has(capability) for m in models)
        for m in models:
            if m.model_id == model:
                return m.has(capability)
        return False

    # ------------------------------------------------------------------
    # Embeddings (optional — not every provider supports them)
    # ------------------------------------------------------------------
    def embed(self, texts: tuple[str, ...], *, model: str | None = None) -> tuple[tuple[float, ...], ...]:
        """
        Return one embedding vector per input text.

        Adapters that do not support embeddings should raise
        ProviderError with error_code="embeddings_unsupported".
        """
        raise ProviderError(
            "this provider does not support embeddings",
            error_code="embeddings_unsupported",
            retryable=False,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        """Optional cleanup. Default: no-op."""
        return None