# providers/routing/router.py
"""
Model router with per-provider model fallback.

Design:
  * The user's ACTIVE provider comes first.
  * The remaining providers with a valid API key follow, in the
    order defined by `providers.priority`.
  * Within a provider, models are tried in the configured order.
  * A model that recently failed (429/503/timeout) is skipped during
    its cooldown.
  * A provider that returned 401/403 is skipped entirely until the
    user changes its key.

This module never makes HTTP calls itself. It only decides what to
try. The actual call + health recording is done by a thin wrapper
class `ResilientProvider` which implements the AIProvider interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from applog.logger import get_logger
from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.provider import AIProvider

log = get_logger("providers.routing")


@dataclass(frozen=True)
class RouteDecision:
    provider_id: str
    provider: AIProvider
    model: str
    capabilities: ModelCapabilities


class ModelRouter:
    """
    Pure decision layer. Callers may use `list_candidates()` to walk
    the chain themselves, or use `ResilientProvider` for the full
    fallback wrapper.
    """

    def __init__(
        self,
        *,
        provider_manager,
        config,
        health=None,
    ) -> None:
        self._providers = provider_manager
        self._config = config
        self._health = health

    # ------------------------------------------------------------------
    def list_candidates(self) -> list[RouteDecision]:
        """
        Return every (provider, model) pair that is currently worth
        trying, in priority order.

        The first item is the primary candidate. The last item is the
        final fallback.
        """
        chain = self._build_provider_chain()
        out: list[RouteDecision] = []
        for provider_id in chain:
            try:
                provider = self._providers.get(provider_id)
            except Exception:
                continue
            models = self._models_for(provider_id, provider)
            for model in models:
                if self._health is not None:
                    if not self._health.provider_is_valid(provider_id):
                        log.info(
                            "router: skipping invalid provider",
                            extra={"provider": provider_id},
                        )
                        break  # skip all models for this provider
                    if not self._health.is_available(provider_id, model):
                        log.info(
                            "router: skipping unhealthy model",
                            extra={"provider": provider_id, "model": model},
                        )
                        continue
                caps = self._caps_for(provider, model)
                if caps is None:
                    continue
                out.append(
                    RouteDecision(
                        provider_id=provider_id,
                        provider=provider,
                        model=model,
                        capabilities=caps,
                    )
                )
        return out

    # ------------------------------------------------------------------
    def primary(self) -> Optional[RouteDecision]:
        candidates = self.list_candidates()
        return candidates[0] if candidates else None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _build_provider_chain(self) -> list[str]:
        active = None
        try:
            active = self._config.get("providers.active") if self._config else None
        except Exception:
            active = None

        configured_priority = []
        try:
            raw = self._config.get("providers.priority") if self._config else None
            if isinstance(raw, list):
                configured_priority = [str(x).strip() for x in raw if str(x).strip()]
        except Exception:
            configured_priority = []

        # Everything registered in the ProviderManager.
        try:
            registered = set(self._providers.provider_ids())
        except Exception:
            registered = set()

        # Only providers that have an API key.
        valid: set[str] = set()
        try:
            if self._config is not None:
                for pid in registered:
                    # The presence of a key is checked elsewhere; we use
                    # the fact that bootstrap only registers providers
                    # with keys. If a key is removed, the provider is
                    # unregistered.
                    valid.add(pid)
            else:
                valid = registered
        except Exception:
            valid = registered

        chain: list[str] = []
        # 1. Active provider first.
        if active and active in valid:
            chain.append(str(active))
        # 2. Configured priority order.
        for pid in configured_priority:
            if pid in valid and pid not in chain:
                chain.append(pid)
        # 3. Any other registered providers.
        for pid in sorted(valid):
            if pid not in chain:
                chain.append(pid)

        return chain

    def _models_for(self, provider_id: str, provider: AIProvider) -> list[str]:
        # 1. Try config.
        try:
            raw = (
                self._config.get(f"providers.models.{provider_id}")
                if self._config is not None
                else None
            )
            if isinstance(raw, list) and raw:
                # Filter to models the provider actually declares.
                declared = {m.model_id for m in provider.get_models()}
                out = [str(m).strip() for m in raw if str(m).strip() in declared]
                if out:
                    return out
        except Exception:
            pass
        # 2. Fall back to whatever the provider declares.
        return [m.model_id for m in provider.get_models()]

    def _caps_for(
        self, provider: AIProvider, model: str
    ) -> Optional[ModelCapabilities]:
        for m in provider.get_models():
            if m.model_id == model:
                return m
        return None