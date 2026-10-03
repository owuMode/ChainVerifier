# gui/web/classifier_worker.py
"""
ClassifierWorker — decide (chat | task | memory_command) off the UI thread.

Phase 3: emits the FULL classification as a JSON string so the bridge
can route memory commands without re-classifying.
"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QThread, Signal

from applog.logger import get_logger

log = get_logger("gui.web.classifier_worker")


class ClassifierWorker(QThread):
    """
    Runs Classifier.classify() and emits the full classification
    as a JSON string.
    """

    finishedOk = Signal(str)          # JSON payload
    finishedErr = Signal(str)

    def __init__(
        self,
        *,
        classifier,
        message: str,
        parent: Optional[QThread] = None,
    ) -> None:
        super().__init__(parent)
        self._classifier = classifier
        self._message = message

    # ------------------------------------------------------------------
    def run(self) -> None:
        if self._classifier is None:
            self.finishedOk.emit(json.dumps({
                "kind": "chat",
                "confidence": 0.0,
                "reason": "no classifier",
            }))
            return

        try:
            result = self._classifier.classify(self._message)
        except Exception:
            log.exception("ClassifierWorker: classify raised")
            self.finishedOk.emit(json.dumps({
                "kind": "chat",
                "confidence": 0.0,
                "reason": "classifier raised",
            }))
            return

        payload = {
            "kind": result.kind,
            "confidence": result.confidence,
            "reason": result.reason,
            "memory_action": getattr(result, "memory_action", ""),
            "memory_target": getattr(result, "memory_target", ""),
            "memory_new_value": getattr(result, "memory_new_value", ""),
        }
        log.info(
            "classifier decision",
            extra={
                "kind": result.kind,
                "confidence": result.confidence,
                "reason": result.reason,
            },
        )
        self.finishedOk.emit(json.dumps(payload, ensure_ascii=False))