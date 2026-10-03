# gui/web/provider_factory.py
"""
Small helper to build a concrete provider instance for a given preset
key. Used by ProviderBridge.testConnection and by the AppController
when wiring the chat service.

Kept separate so the bridge and the controller share one code path.
"""

from __future__ import annotations

from typing import Optional

from providers.adapters.openai_compatible import OpenAICompatibleProvider
from providers.base.capabilities import Capability, ModelCapabilities
from providers.presets import by_key


def build_provider_for_key(
    key: str,
    *,
    config,
    secrets,
) -> OpenAICompatibleProvider:
    """
    Build a provider for `key` using config + secrets.

    Raises ValueError if the preset is unknown or the API key is missing.
    """
    preset = by_key(key)
    if preset is None:
        raise ValueError(f"unknown provider preset: {key!r}")

    api_key = secrets.get("provider", key) or ""
    if not api_key:
        raise ValueError(f"no API key configured for {preset.name}")

    base_url = str(
        config.get(f"providers.{key}.base_url") or preset.base_url
    )
    default_model = str(
        config.get(f"providers.{key}.default_model")
        or preset.default_model.key
    )

    models = (
        ModelCapabilities(
            model_id=default_model,
            capabilities=frozenset({
                Capability.STREAMING,
                Capability.TOOL_CALLING,
                Capability.STRUCTURED_OUTPUT,
            }),
            context_window=128_000,
            max_output_tokens=4_096,
        ),
    )

    return OpenAICompatibleProvider(
        provider_id=key,
        base_url=base_url,
        api_key=api_key,
        models=models,
    )