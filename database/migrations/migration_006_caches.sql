-- database/migrations/migration_006_caches.sql
--
-- Planner + synthesizer caches.
--
-- Both caches are content-addressed: the key is a sha256 of the
-- relevant inputs. If the same inputs are seen again within the TTL
-- window, we skip the LLM call entirely.
--
-- Design:
--   * planner_cache:   key = sha256(goal + context_digest + model)
--   * synthesis_cache: key = sha256(goal + step_results_digest + model)
--   * TTL is enforced in application code, not here.
--   * Rows are cleaned by a background sweep (or a manual prune).

CREATE TABLE IF NOT EXISTS planner_cache (
    cache_key     TEXT PRIMARY KEY,
    goal          TEXT NOT NULL,
    context_json  TEXT NOT NULL DEFAULT '[]',
    plan_json     TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT NOT NULL,
    use_count     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_planner_cache_last_used
    ON planner_cache(last_used_at DESC);

CREATE TABLE IF NOT EXISTS synthesis_cache (
    cache_key     TEXT PRIMARY KEY,
    goal          TEXT NOT NULL,
    results_json  TEXT NOT NULL,
    text          TEXT NOT NULL,
    model         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    last_used_at  TEXT NOT NULL,
    use_count     INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_synthesis_cache_last_used
    ON synthesis_cache(last_used_at DESC);