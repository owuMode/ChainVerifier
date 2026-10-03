# tests/integration/test_audit_roundtrip.py
from pathlib import Path

from database.manager import DatabaseManager
from database.repositories import AuditRepository


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "database" / "migrations"


def test_audit_append_and_redact(tmp_path: Path):
    db = DatabaseManager(db_path=tmp_path / "app.sqlite", migrations_dir=_migrations_dir())
    db.open()
    try:
        audit = AuditRepository(db)
        event = audit.append(
            "TOOL_REQUESTED",
            actor="agent",
            payload={"tool_id": "test_tool", "api_key": "AIzaSECRET-xyz"},
        )
        assert event.payload["tool_id"] == "test_tool"
        # key was redacted because it's in the sensitive-key set
        assert event.payload["api_key"] == "***REDACTED***"

        recent = audit.recent(limit=10)
        assert any(e.event_id == event.event_id for e in recent)
    finally:
        db.close()