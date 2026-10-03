# providers/manager.py
"""
ProviderManager — registers and resolves provider adapters.

Phase 3: multi-provider support.

  * Every configured provider registers a factory at bootstrap.
  * The "active" provider is the user's choice (Settings).
  * Fallback routing lives in providers/routing/router.py.
"""

from __future__ import annotations

from typing import Callable, Optional

from applog.logger import get_logger
from providers.base.capabilities import Capability
from providers.base.provider import AIProvider, ProviderError

log = get_logger("providers.manager")


class NoActiveProviderError(ProviderError):
    def __init__(self, message: str = "no active provider configured") -> None:
        super().__init__(message, error_code="no_active_provider", retryable=False)


Factory = Callable[[], AIProvider]


class ProviderManager:
    def __init__(self) -> None:
        self._factories: dict[str, Factory] = {}
        self._instances: dict[str, AIProvider] = {}
        self._active_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(self, provider_id: str, factory: Factory) -> None:
        if provider_id in self._factories:
            raise ValueError(f"duplicate provider_id: {provider_id!r}")
        self._factories[provider_id] = factory
        log.info("provider registered", extra={"provider_id": provider_id})

    def unregister(self, provider_id: str) -> None:
        self._factories.pop(provider_id, None)
        inst = self._instances.pop(provider_id, None)
        if inst is not None:
            try:
                inst.close()
            except Exception:
                pass
        if self._active_id == provider_id:
            self._active_id = None

    def set_active(self, provider_id: Optional[str]) -> None:
        if provider_id is None:
            self._active_id = None
            return
        if provider_id not in self._factories:
            raise ValueError(f"unknown provider_id: {provider_id!r}")
        self._active_id = provider_id
        log.info("active provider set", extra={"provider_id": provider_id})

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def provider_ids(self) -> list[str]:
        return sorted(self._factories.keys())

    def active_id(self) -> Optional[str]:
        return self._active_id

    def active(self) -> AIProvider:
        if self._active_id is None:
            raise NoActiveProviderError()
        return self.get(self._active_id)

    def get(self, provider_id: str) -> AIProvider:
        inst = self._instances.get(provider_id)
        if inst is not None:
            return inst
        factory = self._factories.get(provider_id)
        if factory is None:
            raise ValueError(f"unknown provider_id: {provider_id!r}")
        inst = factory()
        self._instances[provider_id] = inst
        return inst

    # ------------------------------------------------------------------
    def supports(self, capability: Capability, model: Optional[str] = None) -> bool:
        try:
            return self.active().supports(capability, model=model)
        except NoActiveProviderError:
            return False

    # ------------------------------------------------------------------
    def close(self) -> None:
        for inst in self._instances.values():
            try:
                inst.close()
            except Exception:
                log.exception(
                    "provider close failed",
                    extra={"provider_id": inst.provider_id},
                )
        self._instances.clear()