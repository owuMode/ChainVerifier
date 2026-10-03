-- database/migrations/migration_005_caches.sql
--
-- Local caches to reduce API calls.
--
-- embedding_cache:    one row per unique text -> embedding vector (BLOB)
--                     used to avoid re-embedding identical queries.
-- classifier_cache:   one row per unique message -> classification JSON
--                     used to avoid re-classifying identical messages.

-- ------------------------------------------------------------------
-- Embedding cache
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_cache (
    cache_key        TEXT PRIMARY KEY,        -- sha256(text) hex
    text             TEXT NOT NULL,           -- original text (for debugging)
    embedding        BLOB NOT NULL,           -- float32 little-endian
    embedding_dim    INTEGER NOT NULL,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    last_used_at     TEXT,
    use_count        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_embedding_cache_used
    ON embedding_cache(last_used_at DESC);

-- ------------------------------------------------------------------
-- Classifier cache
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classifier_cache (
    cache_key        TEXT PRIMARY KEY,        -- sha256(normalized message)
    kind             TEXT NOT NULL,           -- 'chat' | 'task'
    confidence       REAL NOT NULL DEFAULT 0.0,
    reason           TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    last_used_at     TEXT,
    use_count        INTEGER NOT NULL DEFAULT 0
);