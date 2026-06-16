-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ─── documents ────────────────────────────────────────────────────────────────
-- One row per Jira ticket or Confluence page (source of truth link preserved).
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type         TEXT        NOT NULL CHECK (source_type IN ('jira', 'confluence')),
    source_id           TEXT        NOT NULL,
    source_url          TEXT,
    title               TEXT,
    raw_content         TEXT,
    cleaned_content     TEXT,
    -- author, labels, project key, space key, created_at, updated_at from source
    metadata            JSONB       NOT NULL DEFAULT '{}',
    -- arrays used for permission enforcement at query time
    allowed_spaces      TEXT[]      NOT NULL DEFAULT '{}',
    allowed_projects    TEXT[]      NOT NULL DEFAULT '{}',
    -- product hierarchy classification result
    product_hierarchy   JSONB       NOT NULL DEFAULT '{}',
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_updated_at   TIMESTAMPTZ,
    CONSTRAINT uq_documents_source UNIQUE (source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_source_type  ON documents (source_type);
CREATE INDEX IF NOT EXISTS idx_documents_spaces        ON documents USING GIN (allowed_spaces);
CREATE INDEX IF NOT EXISTS idx_documents_projects      ON documents USING GIN (allowed_projects);
CREATE INDEX IF NOT EXISTS idx_documents_hierarchy     ON documents USING GIN (product_hierarchy);
CREATE INDEX IF NOT EXISTS idx_documents_updated_at    ON documents (source_updated_at);

-- ─── chunks ───────────────────────────────────────────────────────────────────
-- Semantic chunks derived from documents. Holds the vector embedding + FTS index.
-- NOTE: embedding dimension must match EMBEDDING_DIM env var (default 1536).
--       If switching to a 768-dim model (e.g. nomic-embed-text), run:
--       ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id     UUID    NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    chunk_index     INT     NOT NULL,
    content         TEXT    NOT NULL,
    embedding       vector(1536),
    -- generated FTS column — no manual maintenance needed
    fts_vector      TSVECTOR GENERATED ALWAYS AS
                        (to_tsvector('english', coalesce(content, ''))) STORED,
    token_count     INT,
    metadata        JSONB   NOT NULL DEFAULT '{}',
    CONSTRAINT uq_chunks_doc_index UNIQUE (document_id, chunk_index)
);

-- HNSW index — no minimum-row requirement, works from 1 row up.
-- Faster build than IVFFlat for small-to-medium datasets.
-- m=16, ef_construction=64 are sensible defaults; tune ef_search at query time.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_fts       ON chunks USING GIN (fts_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id    ON chunks (document_id);

-- ─── sync_state ───────────────────────────────────────────────────────────────
-- Watermark table — one row per source type. Updated after every successful sync.
CREATE TABLE IF NOT EXISTS sync_state (
    source_type         TEXT        PRIMARY KEY,
    last_synced_at      TIMESTAMPTZ,
    total_items_indexed INT         NOT NULL DEFAULT 0,
    last_run_status     TEXT        NOT NULL DEFAULT 'never_run'
);

INSERT INTO sync_state (source_type) VALUES ('jira'), ('confluence')
ON CONFLICT DO NOTHING;

-- ─── product_experts ──────────────────────────────────────────────────────────
-- One row per product (or product+component). Synthesised by the ingestion
-- pipeline after every sync. Consumed by the query service and AI agents to
-- ground feature development and test generation in rich product context.
CREATE TABLE IF NOT EXISTS product_experts (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Classification keys — match product_hierarchy.yaml structure
    product                 TEXT        NOT NULL,
    component               TEXT,                           -- NULL = product-level expert
    -- Synthesised knowledge
    description             TEXT        NOT NULL DEFAULT '', -- 1-2 sentence human summary
    compressed_context      TEXT        NOT NULL DEFAULT '', -- LLM-synthesised dense context for agents
    -- Dependency graph
    -- Each entry: {"product": "...", "component": "...", "reason": "..."}
    upstream_dependencies   JSONB       NOT NULL DEFAULT '[]',
    downstream_affected     JSONB       NOT NULL DEFAULT '[]',
    -- Provenance
    source_document_count   INT         NOT NULL DEFAULT 0,
    generated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_product_experts UNIQUE (product, COALESCE(component, ''))
);

CREATE INDEX IF NOT EXISTS idx_experts_product   ON product_experts (product);
CREATE INDEX IF NOT EXISTS idx_experts_component ON product_experts (component)
    WHERE component IS NOT NULL;

