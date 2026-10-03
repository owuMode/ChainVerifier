# providers/__init__.py
"""
Providers package.

Kept lazy: the base interface is small, but the adapters pull in
HTTP machinery. Callers that only need the interface should not
pay for the adapters.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "AIProvider": ("providers.base.provider", "AIProvider"),
    "ProviderError": ("providers.base.provider", "ProviderError"),
    "ProviderAuthError": ("providers.base.provider", "ProviderAuthError"),
    "ProviderNetworkError": ("providers.base.provider", "ProviderNetworkError"),
    "ProviderResponseError": ("providers.base.provider", "ProviderResponseError"),
    "Capability": ("providers.base.capabilities", "Capability"),
    "ModelCapabilities": ("providers.base.capabilities", "ModelCapabilities"),
    "ChatMessage": ("providers.base.models", "ChatMessage"),
    "ChatRequest": ("providers.base.models", "ChatRequest"),
    "ChatResponse": ("providers.base.models", "ChatResponse"),
    "StreamChunk": ("providers.base.models", "StreamChunk"),
    "ToolCall": ("providers.base.models", "ToolCall"),
    "Role": ("providers.base.models", "Role"),
    "FinishReason": ("providers.base.models", "FinishReason"),
    "Usage": ("providers.base.models", "Usage"),
    "ProviderManager": ("providers.manager", "ProviderManager"),
    "NoActiveProviderError": ("providers.manager", "NoActiveProviderError"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'providers' has no attribute {name!r}")
    module_path, attr = target
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(_EXPORTS.keys())


__all__ = sorted(_EXPORTS.keys())