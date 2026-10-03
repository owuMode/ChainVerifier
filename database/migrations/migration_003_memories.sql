-- database/migrations/migration_003_memories.sql
--
-- Long-term memory storage (spec §41).
--
-- Design:
--   * One row = one memory (a fact, preference, identity, ...).
--   * user_id is reserved for future multi-user support; today it is
--     always 'default'.
--   * soft delete via archived_at (never lose history).
--   * expires_at allows time-limited memories ("remember for today").
--   * tags is a JSON array of lowercase keywords.
--   * metadata is a JSON object for arbitrary extra data.
--   * use_count and last_used_at are updated on retrieval.

CREATE TABLE IF NOT EXISTS memories (
    memory_id              TEXT PRIMARY KEY,
    user_id                TEXT NOT NULL DEFAULT 'default',
    kind                   TEXT NOT NULL,
    content                TEXT NOT NULL,
    summary                TEXT NOT NULL DEFAULT '',
    confidence             REAL NOT NULL DEFAULT 0.75,
    importance             INTEGER NOT NULL DEFAULT 3,
    source                 TEXT NOT NULL DEFAULT 'extracted',
    source_conversation_id TEXT,
    source_message_id      TEXT,
    tags                   TEXT NOT NULL DEFAULT '[]',
    expires_at             TEXT,
    archived_at            TEXT,
    use_count              INTEGER NOT NULL DEFAULT 0,
    last_used_at           TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    metadata               TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_user_kind
    ON memories(user_id, kind);

CREATE INDEX IF NOT EXISTS idx_memories_user_created
    ON memories(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_archived
    ON memories(archived_at);

CREATE INDEX IF NOT EXISTS idx_memories_expires
    ON memories(expires_at);