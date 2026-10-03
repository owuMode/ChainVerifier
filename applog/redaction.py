# applog/redaction.py
from __future__ import annotations

import re
from typing import Any, Mapping, MutableMapping


_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey",
    "authorization", "auth",
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "id_token",
    "secret", "client_secret",
    "credential", "credentials",
    "private_key", "session_key",
    "cookie", "set-cookie",
})

_PATTERNS = (
    re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{16,}\b"),
    re.compile(r"\b[a-f0-9]{40,}\b"),
)

REDACTED = "***REDACTED***"


def _redact_string(value: str) -> str:
    out = value
    for pattern in _PATTERNS:
        out = pattern.sub(REDACTED, out)
    return out


def redact_value(key: str, value: Any) -> Any:
    if key and key.lower() in _SENSITIVE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value("", item) for item in value)
    return value


def redact_mapping(data: Mapping[str, Any]) -> dict:
    out: MutableMapping[str, Any] = {}
    for key, value in data.items():
        out[key] = redact_value(str(key), value)
    return dict(out)