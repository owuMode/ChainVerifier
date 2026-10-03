# providers/presets.py
"""
Provider presets — the catalog of providers Rhea ships with.

Model IDs are stored WITHOUT the "models/" prefix in the UI. The
Gemini adapter adds the prefix on the wire (Gemini requires it) and
strips it from responses.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelPreset:
    key: str
    name: str
    description: str
    default: bool = False


@dataclass(frozen=True)
class ProviderPreset:
    key: str
    name: str
    adapter: str
    base_url: str
    docs_url: str
    models: tuple[ModelPreset, ...] = field(default_factory=tuple)

    @property
    def default_model(self) -> ModelPreset:
        for m in self.models:
            if m.default:
                return m
        return self.models[0]


PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="openai",
        name="OpenAI",
        adapter="openai_compatible",
        base_url="https://api.openai.com/v1",
        docs_url="https://platform.openai.com/api-keys",
        models=(
            ModelPreset("gpt-4o-mini", "GPT-4o mini", "Fast, cheap", default=True),
            ModelPreset("gpt-4o", "GPT-4o", "Flagship model"),
            ModelPreset("gpt-4-turbo", "GPT-4 Turbo", "Long-context"),
            ModelPreset("gpt-4.1", "GPT-4.1", "Newer flagship"),
            ModelPreset("gpt-4.1-mini", "GPT-4.1 mini", "Fast"),
            ModelPreset("o1", "o1", "Reasoning"),
            ModelPreset("o1-mini", "o1-mini", "Faster reasoning"),
        ),
    ),
    ProviderPreset(
        key="gemini",
        name="Google Gemini",
        adapter="openai_compatible",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        docs_url="https://aistudio.google.com/app/apikey",
        models=(
            ModelPreset("gemini-3.8-flash", "Gemini 3.8 Flash", "Latest flagship", default=True),
            ModelPreset("gemini-3.7-flash", "Gemini 3.7 Flash", "Recent"),
            ModelPreset("gemini-3.6-flash", "Gemini 3.6 Flash", "Recent"),
            ModelPreset("gemini-3.5-flash", "Gemini 3.5 Flash", "Stable"),
            ModelPreset("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite", "Cheap"),
            ModelPreset("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite", "Cheap"),
            ModelPreset("gemini-3.1-pro-preview", "Gemini 3.1 Pro (preview)", "Preview, strongest"),
            ModelPreset("gemini-3-flash-preview", "Gemini 3 Flash (preview)", "Preview"),
            ModelPreset("gemini-2.5-flash", "Gemini 2.5 Flash", "Verified"),
            ModelPreset("gemini-2.5-pro", "Gemini 2.5 Pro", "Verified"),
            ModelPreset("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "Verified"),
            ModelPreset("gemini-flash-latest", "Gemini Flash (latest)", "Auto-updating alias"),
            ModelPreset("gemini-pro-latest", "Gemini Pro (latest)", "Auto-updating alias"),
        ),
    ),
    ProviderPreset(
        key="deepseek",
        name="DeepSeek",
        adapter="openai_compatible",
        base_url="https://api.deepseek.com/v1",
        docs_url="https://platform.deepseek.com/api_keys",
        models=(
            ModelPreset("deepseek-chat", "DeepSeek Chat", "General", default=True),
            ModelPreset("deepseek-reasoner", "DeepSeek Reasoner", "Chain-of-thought"),
        ),
    ),
    ProviderPreset(
        key="groq",
        name="Groq",
        adapter="openai_compatible",
        base_url="https://api.groq.com/openai/v1",
        docs_url="https://console.groq.com/keys",
        models=(
            ModelPreset("llama-3.3-70b-versatile", "Llama 3.3 70B", "Fast, versatile", default=True),
            ModelPreset("llama-3.1-8b-instant", "Llama 3.1 8B", "Very fast"),
            ModelPreset("mixtral-8x7b-32768", "Mixtral 8x7B", "Long context"),
            ModelPreset("qwen-2.5-32b", "Qwen 2.5 32B", "Qwen"),
        ),
    ),
    ProviderPreset(
        key="openrouter",
        name="OpenRouter",
        adapter="openai_compatible",
        base_url="https://openrouter.ai/api/v1",
        docs_url="https://openrouter.ai/keys",
        models=(
            ModelPreset("openai/gpt-4o-mini", "GPT-4o mini", "OpenAI via OR", default=True),
            ModelPreset("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", "Anthropic"),
            ModelPreset("google/gemini-2.5-flash", "Gemini 2.5 Flash", "Google"),
            ModelPreset("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", "Meta"),
            ModelPreset("deepseek/deepseek-chat", "DeepSeek Chat", "DeepSeek"),
        ),
    ),
    ProviderPreset(
        key="custom",
        name="Custom (OpenAI-compatible)",
        adapter="openai_compatible",
        base_url="",
        docs_url="",
        models=(),
    ),
)


def by_key(key: str) -> ProviderPreset | None:
    for p in PRESETS:
        if p.key == key:
            return p
    return None


def provider_keys() -> list[str]:
    return [p.key for p in PRESETS]