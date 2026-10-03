-- database/migrations/migration_007_provider_health.sql
--
-- Provider / model health tracking.
--
-- When a model returns 429/503/timeout/network, we mark it unhealthy
-- for a short cooldown period. While unhealthy, the router skips it
-- and goes to the next model.
--
-- When a provider returns 401/403 (auth error), we mark the whole
-- provider as invalid until the user changes the key.

CREATE TABLE IF NOT EXISTS provider_health (
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    status        TEXT NOT NULL,   -- 'ok' | 'cooldown' | 'invalid'
    reason        TEXT NOT NULL DEFAULT '',
    failed_until  TEXT,            -- ISO8601 UTC, null = no cooldown
    failure_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    last_error_at TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (provider, model)
);

CREATE INDEX IF NOT EXISTS idx_provider_health_status
    ON provider_health(status);