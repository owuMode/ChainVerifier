# providers/adapters/openai_compatible/adapter.py
"""
OpenAI-compatible adapter.

Retries on 503/429 with short backoff (total added latency ≤ 2s).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Iterator, Optional

from applog.logger import get_logger
from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    FinishReason,
    Role,
    StreamChunk,
    ToolCall,
    Usage,
)
from providers.base.provider import (
    AIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderNetworkError,
    ProviderResponseError,
)

log = get_logger("providers.openai_compatible")

_DEFAULT_TIMEOUT = 60.0
# Only ONE retry per call; the multi-model fallback handles the rest.
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_S = (0.5, 1.5)


class OpenAICompatibleProvider(AIProvider):
    adapter_name = "openai_compatible"

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        api_key: str,
        models: tuple[ModelCapabilities, ...],
        timeout_s: float = _DEFAULT_TIMEOUT,
        default_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.provider_id = provider_id
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._models = models
        self._timeout_s = timeout_s
        self._extra_headers = dict(default_headers or {})
        self._needs_models_prefix = (
            "generativelanguage.googleapis.com" in self._base_url
        )

    # ------------------------------------------------------------------
    def chat(self, request: ChatRequest) -> ChatResponse:
        body = self._build_body(request, stream=False)
        data = self._post_json_with_retry("/chat/completions", body)
        return self._parse_chat_response(data)

    # ------------------------------------------------------------------
    def stream(self, request: ChatRequest) -> Iterator[StreamChunk]:
        body = self._build_body(request, stream=True)
        url = self._url("/chat/completions")
        headers = self._headers()

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={**headers, "Accept": "text/event-stream"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        yield StreamChunk(done=True)
                        return
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        log.warning("stream: malformed chunk skipped")
                        continue
                    yield self._parse_stream_chunk(chunk)
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise ProviderNetworkError(f"network error: {exc.reason}") from exc

    # ------------------------------------------------------------------
    def generate_structured(self, request: ChatRequest, schema: dict) -> dict:
        body = self._build_body(request, stream=False)
        body["response_format"] = {"type": "json_object"}

        data = self._post_json_with_retry("/chat/completions", body)
        resp = self._parse_chat_response(data)

        try:
            parsed = json.loads(resp.content)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"structured output is not JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise ProviderResponseError("structured output is not a JSON object")
        return parsed

    # ------------------------------------------------------------------
    def embed(
        self,
        texts: tuple[str, ...],
        *,
        model: str | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()

        effective_model = model or self._default_embedding_model()
        if not effective_model:
            raise ProviderResponseError(
                "no embedding model configured for this provider",
                retryable=False,
            )

        model_on_wire = effective_model
        if self._needs_models_prefix and not model_on_wire.startswith("models/"):
            model_on_wire = f"models/{model_on_wire}"

        body = {"model": model_on_wire, "input": list(texts)}
        data = self._post_json_with_retry("/embeddings", body)

        rows = data.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ProviderResponseError("malformed embeddings response", retryable=False)

        by_index: dict[int, tuple[float, ...]] = {}
        for row in rows:
            try:
                idx = int(row.get("index", 0))
                vec = tuple(float(x) for x in row["embedding"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ProviderResponseError(f"bad embedding row: {exc}", retryable=False)
            by_index[idx] = vec

        if len(by_index) != len(texts):
            raise ProviderResponseError("embeddings response has missing indices", retryable=False)

        return tuple(by_index[i] for i in range(len(texts)))

    def _default_embedding_model(self) -> str | None:
        url = self._base_url.lower()
        if "generativelanguage.googleapis.com" in url:
            return "gemini-embedding-001"
        if "api.openai.com" in url:
            return "text-embedding-3-small"
        if "api.deepseek.com" in url:
            return None
        if "api.groq.com" in url:
            return None
        if "openrouter.ai" in url:
            return "openai/text-embedding-3-small"
        return None

    # ------------------------------------------------------------------
    def get_models(self) -> tuple[ModelCapabilities, ...]:
        return self._models

    def validate_connection(self) -> None:
        url = self._url("/models")
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                if resp.status != 200:
                    raise ProviderResponseError(f"unexpected status {resp.status} from {url}")
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise ProviderNetworkError(f"network error: {exc.reason}") from exc

    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            **self._extra_headers,
        }

    def _post_json_with_retry(self, path: str, body: dict) -> dict:
        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return self._post_json(path, body)
            except ProviderResponseError as exc:
                msg = str(exc).lower()
                if "http 429" in msg or "http 503" in msg:
                    last_exc = exc
                    if attempt < _RETRY_ATTEMPTS:
                        delay = _RETRY_BACKOFF_S[attempt - 1]
                        log.warning(
                            "server busy, retrying",
                            extra={"attempt": attempt, "delay_s": delay},
                        )
                        time.sleep(delay)
                        continue
                raise
            except ProviderNetworkError as exc:
                last_exc = exc
                if attempt < _RETRY_ATTEMPTS and getattr(exc, "retryable", True):
                    delay = _RETRY_BACKOFF_S[attempt - 1]
                    log.warning(
                        "network error, retrying",
                        extra={"attempt": attempt, "delay_s": delay},
                    )
                    time.sleep(delay)
                    continue
                raise

        if last_exc is not None:
            raise last_exc
        raise ProviderResponseError("retry loop exited without result")

    def _post_json(self, path: str, body: dict) -> dict:
        url = self._url(path)
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            self._raise_http_error(exc)
        except urllib.error.URLError as exc:
            raise ProviderNetworkError(f"network error: {exc.reason}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"response is not JSON: {exc}") from exc

    def _raise_http_error(self, exc: urllib.error.HTTPError) -> None:
        status = exc.code
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        snippet = err_body[:500]

        if status in (401, 403):
            raise ProviderAuthError(f"authentication failed ({status}): {snippet}")
        if status == 404:
            raise ProviderResponseError(f"http 404: model not found: {snippet}")
        if status == 429:
            raise ProviderResponseError(f"http 429: rate limit: {snippet}")
        if status in (502, 503, 504):
            raise ProviderResponseError(f"http {status}: {snippet}")
        if 500 <= status < 600:
            raise ProviderNetworkError(f"server error {status}: {snippet}")
        raise ProviderResponseError(f"http {status}: {snippet}")

    # ------------------------------------------------------------------
    def _build_body(self, request: ChatRequest, *, stream: bool) -> dict:
        model = request.model
        if self._needs_models_prefix and not model.startswith("models/"):
            model = f"models/{model}"

        body: dict[str, Any] = {
            "model": model,
            "messages": [self._encode_message(m) for m in request.messages],
            "temperature": request.temperature,
            "stream": stream,
        }
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        if request.tools:
            body["tools"] = list(request.tools)
        return body

    @staticmethod
    def _encode_message(message: ChatMessage) -> dict:
        out: dict[str, Any] = {"role": message.role.value}
        if message.role is Role.TOOL:
            out["content"] = message.content
            if message.tool_call_id:
                out["tool_call_id"] = message.tool_call_id
            if message.name:
                out["name"] = message.name
            return out
        if message.tool_calls:
            out["content"] = message.content or None
            out["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_id,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in message.tool_calls
            ]
        else:
            out["content"] = message.content
        return out

    @staticmethod
    def _parse_chat_response(data: dict) -> ChatResponse:
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError(f"malformed chat response: {exc}") from exc

        message = choice.get("message", {})
        content = message.get("content") or ""
        tool_calls_raw = message.get("tool_calls") or []

        tool_calls: list[ToolCall] = []
        for tc in tool_calls_raw:
            try:
                fn = tc.get("function", {})
                args_raw = fn.get("arguments", "{}")
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
                tool_calls.append(
                    ToolCall(
                        call_id=str(tc.get("id") or ""),
                        tool_id=str(fn.get("name") or ""),
                        arguments=args if isinstance(args, dict) else {},
                    )
                )
            except json.JSONDecodeError:
                continue

        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
            total_tokens=int(usage_raw.get("total_tokens") or 0),
        )

        returned_model = str(data.get("model") or "")
        if returned_model.startswith("models/"):
            returned_model = returned_model[len("models/"):]

        return ChatResponse(
            content=content,
            finish_reason=_map_finish_reason(choice.get("finish_reason")),
            tool_calls=tuple(tool_calls),
            usage=usage,
            model=returned_model,
            provider="openai_compatible",
            raw_metadata={},
        )

    @staticmethod
    def _parse_stream_chunk(chunk: dict) -> StreamChunk:
        try:
            choice = chunk["choices"][0]
        except (KeyError, IndexError, TypeError):
            return StreamChunk()

        delta = choice.get("delta") or {}
        text = delta.get("content") or ""
        finish_raw = choice.get("finish_reason")
        finish = _map_finish_reason(finish_raw) if finish_raw else None

        return StreamChunk(
            delta_text=text,
            tool_call_delta=delta.get("tool_calls"),
            finish_reason=finish,
            done=False,
        )


def _map_finish_reason(value: Optional[str]) -> FinishReason:
    if not value:
        return FinishReason.UNKNOWN
    mapping = {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALLS,
        "function_call": FinishReason.TOOL_CALLS,
        "content_filter": FinishReason.CONTENT_FILTER,
    }
    return mapping.get(value, FinishReason.UNKNOWN)