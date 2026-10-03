# tests/integration/test_openai_compatible_adapter.py
"""
Round-trip test against a local HTTP server that speaks the OpenAI
Chat Completions shape. No network, no API key required.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from providers.adapters.openai_compatible import OpenAICompatibleProvider
from providers.base.capabilities import Capability, ModelCapabilities
from providers.base.models import ChatMessage, ChatRequest, FinishReason, Role


# ----------------------------------------------------------------------
# Tiny OpenAI-shaped test server
# ----------------------------------------------------------------------
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return  # silence

    def do_GET(self) -> None:
        if self.path.endswith("/models"):
            body = json.dumps({"object": "list", "data": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if not self.path.endswith("/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        req = json.loads(raw)

        # Echo model + return a deterministic response
        response = {
            "id": "chatcmpl-test",
            "model": req.get("model", "unknown"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "pong",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 1,
                "total_tokens": 6,
            },
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()


def _provider(base_url: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        provider_id="local_test",
        base_url=base_url,
        api_key="test-key-not-real",
        models=(
            ModelCapabilities(
                model_id="test-model",
                capabilities=frozenset({
                    Capability.STREAMING,
                    Capability.TOOL_CALLING,
                    Capability.STRUCTURED_OUTPUT,
                }),
            ),
        ),
    )


def test_chat_round_trip(local_server: str):
    p = _provider(local_server)
    req = ChatRequest(
        model="test-model",
        messages=(ChatMessage(role=Role.USER, content="ping"),),
    )
    resp = p.chat(req)
    assert resp.content == "pong"
    assert resp.finish_reason is FinishReason.STOP
    assert resp.model == "test-model"
    assert resp.usage.total_tokens == 6


def test_validate_connection_ok(local_server: str):
    p = _provider(local_server)
    p.validate_connection()  # must not raise


def test_get_models_declares_capabilities(local_server: str):
    p = _provider(local_server)
    models = p.get_models()
    assert len(models) == 1
    assert models[0].has(Capability.STREAMING)
    assert p.supports(Capability.TOOL_CALLING, model="test-model")
    assert not p.supports(Capability.VISION, model="test-model")