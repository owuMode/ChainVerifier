-- database/migrations/migration_001_initial.sql
--
-- Initial schema. Only tables required by the current phase are created.
-- Future tables (memories, task_steps, tool_calls, api_key_metadata, ...)
-- arrive in later migrations so growth is safe and traceable.
--
-- Conventions:
--   * Every table has an explicit PRIMARY KEY.
--   * Timestamps are ISO-8601 UTC strings (TEXT).
--   * Foreign keys are enforced at the connection level (PRAGMA foreign_keys=ON).
--   * No secret material is ever stored here (spec §9, §109.7, §109.27).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- Schema version bookkeeping
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT    NOT NULL,
    name        TEXT    NOT NULL
);

-- ---------------------------------------------------------------
-- Settings — authoritative store for ConfigurationService overrides
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,               -- JSON-encoded
    updated_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------
-- Conversations and messages
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id  TEXT PRIMARY KEY,
    title            TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    archived         INTEGER NOT NULL DEFAULT 0,   -- 0 / 1
    metadata         TEXT NOT NULL DEFAULT '{}'    -- JSON
);

CREATE INDEX IF NOT EXISTS idx_conversations_updated_at
    ON conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    message_id       TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    role             TEXT NOT NULL,                -- 'system' | 'user' | 'assistant' | 'tool'
    content          TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}',   -- JSON (tool_calls, model, usage, ...)
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
    ON messages(conversation_id, created_at);

-- ---------------------------------------------------------------
-- Tasks — goal / state / limits (spec §28)
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    task_id              TEXT PRIMARY KEY,
    conversation_id      TEXT,                     -- nullable: standalone tasks allowed
    status               TEXT NOT NULL,            -- state machine value
    goal                 TEXT NOT NULL,
    plan                 TEXT NOT NULL DEFAULT '[]',  -- JSON
    current_step         INTEGER NOT NULL DEFAULT 0,
    result               TEXT,
    error                TEXT,
    retry_count          INTEGER NOT NULL DEFAULT 0,
    max_retries          INTEGER NOT NULL DEFAULT 3,
    max_steps            INTEGER NOT NULL DEFAULT 25,
    max_model_calls      INTEGER NOT NULL DEFAULT 40,
    max_execution_time_s INTEGER NOT NULL DEFAULT 600,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    started_at           TEXT,
    completed_at         TEXT,
    cancel_requested     INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id)
        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at DESC);

-- ---------------------------------------------------------------
-- Providers — user's configured provider accounts (metadata only)
-- NOTE: API keys live in Windows Credential Storage, not here (spec §9).
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS providers (
    provider_id      TEXT PRIMARY KEY,
    adapter          TEXT NOT NULL,             -- 'gemini' | 'openai' | 'openai_compatible' | ...
    label            TEXT NOT NULL,
    base_url         TEXT,                      -- for openai_compatible
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    metadata         TEXT NOT NULL DEFAULT '{}' -- JSON: capability overrides, etc.
);

CREATE INDEX IF NOT EXISTS idx_providers_enabled ON providers(enabled);