# applog/formatters.py
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from applog.redaction import redact_mapping, _redact_string


_RESERVED = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
})


class StructuredFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        for field in ("task_id", "session_id", "trace_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        extras: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            extras[key] = value
        if extras:
            payload["extra"] = redact_mapping(extras)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class HumanFormatter(logging.Formatter):
    _FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

    def __init__(self) -> None:
        super().__init__(fmt=self._FMT, datefmt="%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        record.msg = _redact_string(msg)
        record.args = ()
        return super().format(record)