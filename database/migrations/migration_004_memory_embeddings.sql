-- database/migrations/migration_004_memory_embeddings.sql
--
-- Adds vector-embedding support to memories.
--
-- Design:
--   * embedding is a BLOB of little-endian float32 values (numpy .tobytes()).
--   * embedding_provider + embedding_model identify what produced it,
--     so we never compare vectors from different models.
--   * embedding_dim lets us skip mismatched vectors cheaply.
--   * embedding_updated_at tracks when the vector was last (re)computed.
--
-- The old keyword search path stays intact. Vector search is additive.

ALTER TABLE memories ADD COLUMN embedding BLOB;
ALTER TABLE memories ADD COLUMN embedding_provider TEXT;
ALTER TABLE memories ADD COLUMN embedding_model TEXT;
ALTER TABLE memories ADD COLUMN embedding_dim INTEGER;
ALTER TABLE memories ADD COLUMN embedding_updated_at TEXT;

-- Fast lookup: "give me every memory that has an embedding from provider X"
CREATE INDEX IF NOT EXISTS idx_memories_embedding_provider
    ON memories(user_id, embedding_provider);