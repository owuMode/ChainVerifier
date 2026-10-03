-- database/migrations/migration_002_events.sql
--
-- Append-only audit / event trail (spec §45, §52, §109.32).
--
-- Rules:
--   * Rows are only inserted, never updated in place by the app.
--   * No secret material is stored here. Metadata goes in `payload`
--     AFTER redaction (security.redaction.redact_mapping).
--   * `event_type` mirrors the EventBus event names from spec §45.

CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    event_type   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    session_id   TEXT,
    task_id      TEXT,
    actor        TEXT NOT NULL DEFAULT 'system',  -- 'system' | 'user' | 'agent' | 'tool'
    payload      TEXT NOT NULL DEFAULT '{}'        -- JSON, redacted
);

CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_task       ON events(task_id);