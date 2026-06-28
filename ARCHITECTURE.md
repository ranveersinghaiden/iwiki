# iWiki Architecture

**iWiki** is a Retrieval-Augmented Generation (RAG) knowledge-search platform. It
ingests **Confluence pages** and **Jira issues** into **Postgres + pgvector**,
classifies every document against a **product taxonomy**, and answers
natural-language questions with an LLM grounded in **hybrid retrieval**
(full-text + vector) plus **reranking**.

This is the **single authoritative architecture document**. Operational guides
link here for design/schema and do not duplicate it:

| Doc | Scope |
|-----|-------|
| **ARCHITECTURE.md** (this file) | System design, data model, pipelines, configuration behaviour, performance, security, troubleshooting |
| [README.md](README.md) | Quick start, full environment-variable reference, API reference, local development |
| [POSTGRES.md](POSTGRES.md) | Postgres access, connection methods, index/embedding-dimension operations, backup/restore |
| [TESTING.md](TESTING.md) | Manual end-to-end test procedures |

---

## System Overview

```
                 ┌──────────────────────────────────────────────────────────┐
   Confluence ──▶│ ingestion-service (8090)                                 │
   Jira       ──▶│   fetch → clean → chunk → embed → classify → upsert      │
                 │   after every sync: ProductExpertRefresher               │
                 │   APScheduler cron → incremental sync (SYNC_CRON)        │
                 └───────────────────────────┬──────────────────────────────┘
                                             │ writes
                                             ▼
                          ┌───────────────────────────────────┐
                          │ PostgreSQL 16 + pgvector (5432)    │
                          │ documents · chunks · sync_state    │
                          │ product_experts                    │
                          │ HNSW vector + GIN FTS indexes      │
                          └───────────────────┬───────────────┘
                                             │ reads
                 ┌───────────────────────────┴──────────────────────────────┐
   user query ─▶│ query-service (8091)                                      │
                │   embed → hybrid (FTS + vector) → RRF → rerank → RAG       │
                │   → answer + cited sources                                │
                │   /experts — synthesised product context for agents       │
                └──────────────────────────────────────────────────────────┘
```

| Service | Port | Role |
|---------|------|------|
| `ingestion-service` | 8090 | Fetch, clean, chunk, embed, classify, index; synthesise product experts; schedule incremental syncs |
| `query-service` | 8091 | Natural-language query → hybrid retrieval + rerank + RAG answer; serve product experts |
| `db` (pgvector/pgvector:pg16) | 5432 | Vector + full-text + metadata storage |
| `redis` (redis:7-alpine, optional) | 6379 | Query-service cache for embeddings + answers; fail-open |

**Stack:** Python 3.12 · FastAPI · async SQLAlchemy + asyncpg · PostgreSQL 16 +
pgvector · OpenAI-compatible client (OpenAI **or** local Ollama) · APScheduler.
Both services expose routes under `/api/v1` and share the same `.env`.

---

## AI Provider — OpenAI or local Ollama

iWiki talks to **one OpenAI-compatible API** for both embeddings and chat
completions. The same code path serves either backend; only configuration
changes (see [README.md § Environment Variables](README.md#environment-variables)).

| Mode | Base URL | Embedding model | Chat model | Embedding dim |
|------|----------|-----------------|------------|---------------|
| **Ollama (local/offline)** — default | `http://localhost:11434/v1` (`OLLAMA_BASE_URL`) | `nomic-embed-text` | `llama3.2:3b` | **768** |
| **OpenAI (cloud)** | default OpenAI endpoint | `text-embedding-3-small` | `gpt-4o-mini` | **1536** |

`OLLAMA_BASE_URL` set → all calls route to Ollama; unset → calls go to OpenAI.
When running services in Docker against Ollama on the host, use
`http://host.docker.internal:11434/v1`.

### Embedding dimension is a configuration contract

⚠️ The embedding width is **not** auto-detected. Three things must agree:

```
embedding model output dim  ==  EMBEDDING_DIM  ==  chunks.embedding halfvec(N)
```

- `EMBEDDING_DIM` is **advisory** — it documents intent and is **not** read to
  size the column or validate vectors. The binding constraints are the model's
  actual output and the `halfvec(N)` column in [`db/init.sql`](db/init.sql).
- The **shipped schema is `halfvec(768)`**, matching Ollama `nomic-embed-text`.
  This is the out-of-the-box working configuration.
- To use **OpenAI 1536-dim** embeddings you must set `EMBEDDING_DIM=1536` **and**
  migrate the column: `ALTER TABLE chunks ALTER COLUMN embedding TYPE halfvec(1536);`
  then rebuild the HNSW index. See [POSTGRES.md § Switching embedding dimension](POSTGRES.md#switching-embedding-dimension).
- A mismatch (e.g. 1536-dim vectors into a `halfvec(768)` column) makes every
  chunk insert fail during ingestion.

---

## Data Model

PostgreSQL 16 with the **`vector`** extension (the only required extension —
`pg_trgm` was previously enabled but unused and has been removed). Full DDL:
[`db/init.sql`](db/init.sql).

### `documents` — one row per Jira issue or Confluence page

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | `gen_random_uuid()` |
| `source_type` | `TEXT` | `jira` \| `confluence` (CHECK) |
| `source_id` | `TEXT` | Issue key / page id; **unique with `source_type`** |
| `source_url` | `TEXT` | Deep link back to the source |
| `title` | `TEXT` | |
| `raw_content` | `TEXT` | Original (HTML for Confluence) |
| `cleaned_content` | `TEXT` | Normalised text/markdown |
| `metadata` | `JSONB` | Author, labels, project/space key, timestamps, etc. |
| `allowed_spaces` | `TEXT[]` | Confluence space keys — query-time permission filter |
| `allowed_projects` | `TEXT[]` | Jira project keys — query-time permission filter |
| `product_hierarchy` | `JSONB` | Classification result (see below) |
| `indexed_at` | `TIMESTAMPTZ` | |
| `source_updated_at` | `TIMESTAMPTZ` | Source's last-modified — drives freshness + incremental sync |
| `content_hash` | `TEXT` | SHA-256 of cleaned content; lets **incremental** sync skip re-embed/reclassify when unchanged |

Indexes: `source_type`; GIN on `allowed_spaces`, `allowed_projects`,
`product_hierarchy`; btree on `source_updated_at`.

**`product_hierarchy` JSONB shape** (no schema migration — all classification
lives in this column):

```json
{
  "product": "Safety",
  "feature": "Video Telematics",
  "component": "Clarity Dashcam",
  "method": "semantic",      // rule | semantic | llm | fallback
  "confidence": 0.82,        // 0.0–1.0
  "needs_review": false      // true when confidence < CLASSIFICATION_REVIEW_THRESHOLD
}
```

### `chunks` — semantic chunks with embedding + full-text vector

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | |
| `document_id` | `UUID` FK | → `documents(id)` `ON DELETE CASCADE` |
| `chunk_index` | `INT` | **unique with `document_id`** |
| `content` | `TEXT` | Chunk text |
| `embedding` | `halfvec(768)` | Must match `EMBEDDING_DIM` + model output |
| `fts_vector` | `TSVECTOR` | **Generated** `to_tsvector('english', content)`, `STORED` — no manual maintenance |
| `token_count` | `INT` | |
| `metadata` | `JSONB` | `{source, issue_key/space_key, …}` |

Indexes:
- **HNSW** on `embedding` (`halfvec_cosine_ops`, `m=24`, `ef_construction=128`) —
  works from a single row (no IVFFlat list/training requirement); `ef_search`
  is tuned per query.
- **GIN** on `fts_vector` (full-text search).
- btree on `document_id`.

> Embeddings are stored as **`halfvec`** (16-bit floats) — half the bytes and a
> smaller HNSW index than `vector`, with negligible recall loss at 768-dim. Requires
> **pgvector ≥ 0.7** (the `pgvector/pgvector:pg16` image ships 0.8).

### `sync_state` — incremental-sync watermarks

One row per source type (`jira`, `confluence`, seeded at init): `last_synced_at`,
`total_items_indexed`, `last_run_status` (`never_run` \| `success` \| `partial`).
Read to compute incremental deltas; written after each sync.

### `product_experts` — synthesised per-product knowledge

| Column | Type | Notes |
|--------|------|-------|
| `id` | `UUID` PK | |
| `product` | `TEXT` | Taxonomy product name |
| `component` | `TEXT` NULL | `NULL` = product-level expert (current refresher only emits product-level) |
| `description` | `TEXT` | 1–2 sentence summary |
| `compressed_context` | `TEXT` | Dense LLM-synthesised context (≤ ~400 words) for agents |
| `upstream_dependencies` | `JSONB` | `[{product, component, reason}]` — what this product depends on |
| `downstream_affected` | `JSONB` | `[{product, component, reason}]` — what depends on this product |
| `source_document_count` | `INT` | Provenance |
| `generated_at` / `updated_at` | `TIMESTAMPTZ` | |

Uniqueness is enforced by **two partial unique indexes** (a single COALESCE
constraint is not valid SQL): one on `(product) WHERE component IS NULL`, one on
`(product, component) WHERE component IS NOT NULL`.

---

## Ingestion Pipeline

Orchestrator: [`ingestion_pipeline.py`](ingestion-service/app/pipeline/ingestion_pipeline.py).
Per document:

```
fetch → clean → chunk → embed (batched) → classify (cascade) → upsert (atomic)
```

Run modes (`IngestionPipeline.run(full_sync)`):
- **Full sync** — re-index everything (no watermark). Use after taxonomy or
  embedding-model changes.
- **Incremental sync** — only items with `source_updated_at` newer than the
  `sync_state` watermark. Runs automatically on the `SYNC_CRON` schedule
  (APScheduler, default hourly) and can be triggered manually.

After **all** sources finish, the pipeline always runs the
**ProductExpertRefresher** (failures are logged, never abort the sync).

| Phase | Implementation | Detail |
|-------|----------------|--------|
| **Fetch** | `jira_client.py`, `confluence_client.py` | Paged REST. Each item carries `source_url` and its permission scope (`allowed_projects` for Jira, `allowed_spaces` for Confluence). |
| **Clean** | `cleaner.py` | Confluence HTML → markdown via `markdownify`; Jira text normalised; whitespace collapsed. `bleach` strips unsafe tags. |
| **Chunk** | `chunker.py` | Token-based sliding window (`CHUNK_SIZE`=512, `CHUNK_OVERLAP`=64) using `tiktoken` (`cl100k_base`) when installed; otherwise a word-based approximation (~1.3 tokens/word). |
| **Embed** | `embedder.py` | Batches of `EMBEDDING_BATCH_SIZE` (32) via the configured provider; inputs truncated to 8000 chars. |
| **Classify** | `classifier.py` | 3-stage cascade (below) → writes `product_hierarchy`. |
| **Upsert** | `repository.py` | `documents` upserted on `(source_type, source_id)`; chunks **fully replaced** per document (delete + re-insert) so re-syncs are idempotent. Embeddings passed as text and cast to `halfvec`. |

A direct-ingest endpoint (`POST /api/v1/ingest/document`) runs the same pipeline
on a single inline document — useful for testing and indexing content outside
Jira/Confluence.

### Incremental skip, pagination, concurrency & deletion

- **Content-hash skip.** Each document stores a `content_hash` (SHA-256 of cleaned
  content). On **incremental** sync an unchanged hash skips embed + classify + upsert
  entirely; **full** sync always re-embeds and reclassifies (so taxonomy edits apply).
- **Confluence pagination.** The Confluence v1 `/rest/api/content` endpoint paginates
  by `start=` **offset** (its `_links.next` carries `start=N`, *not* a cursor). The
  client increments `start` by the page size until no `_links.next` appears, so the
  whole space is fetched — not just the first page (~50 pages).
- **Concurrency.** Confluence pages are processed in concurrent windows of
  `INGEST_CONCURRENCY` (5) via `asyncio.gather`, each page on its own DB session;
  Jira stays serial. Throughput is bounded by serial Ollama embedding (~1.5 docs/s).
- **Delete reconciliation.** After a **full** sync (and on demand via `POST
  /api/v1/ingest/reconcile`) the pipeline deletes indexed docs whose `source_id` is no
  longer returned by the source. **Safety guard:** if a source returns an empty id set
  (e.g. an API failure), that source is skipped — nothing is deleted.

---

## Classification — hybrid 3-stage cascade

[`classifier.py`](ingestion-service/app/pipeline/classifier.py) tags every
document to a `product → feature → component` node using a **cheapest-first
cascade**. It stops at the first stage that produces a confident match.

| Stage | Method tag | How | Trigger / threshold |
|-------|-----------|-----|---------------------|
| **1. Rule** | `rule` | Keyword/alias hits against taxonomy-node keywords; title matches weighted higher than body; deeper nodes win ties | Score ≥ `CLASSIFICATION_RULE_MIN_SCORE` (3.0). Confidence `min(0.95, 0.5 + 0.07·score)` |
| **2. Semantic** | `semantic` | Cosine similarity of the doc embedding vs. cached node-label embeddings (one per node) | Runs only when rules miss and `CLASSIFICATION_SEMANTIC_FALLBACK` is on; cosine ≥ `CLASSIFICATION_SEMANTIC_THRESHOLD` (0.45) |
| **3. LLM** | `llm` | LLM picks a node; output validated/repaired against the taxonomy | Only when stages 1–2 are inconclusive. Confidence 0.7 (valid) / 0.5; `General` capped at 0.3 |
| **Fallback** | `fallback` | `General / Uncategorized / null`, confidence 0.0 | When the LLM result is unusable |

Hierarchy consistency is enforced (a chosen feature must belong to the chosen
product, a component to the chosen feature). Any result with
`confidence < CLASSIFICATION_REVIEW_THRESHOLD` (0.5) is flagged
`needs_review: true` for triage rather than being silently trusted.

### Taxonomy source

Loaded at startup from the YAML at `HIERARCHY_CONFIG_PATH` (default
`product_hierarchy.yaml`, mounted read-only into the ingestion container).
Structure is `products → features → components`, each node optionally adding
`aliases`/`keywords` to boost rule recall:

```yaml
products:
  - name: Safety
    features:
      - name: Video Telematics
        components:
          - name: Clarity Dashcam
            keywords: [Clarity, dashcam, video-safety]
```

The committed EROAD taxonomy (`product_hierarchy.eroad.yaml`) is generated from
the product map at `.agents/knowledge/product-map.json`. Swap taxonomies by
pointing `HIERARCHY_CONFIG_PATH` at a different file (or replacing the mounted
file), then run a **full sync** to reclassify.

---

## Query Pipeline

Entry point: `POST /api/v1/query` →
[`query-service/app/api/routes.py`](query-service/app/api/routes.py).

```
parse + validate query
  → embed query (same provider/model as ingestion)
  → hybrid retrieval:  BM25/FTS  +  vector similarity
  → merge with Reciprocal Rank Fusion (RRF, k=60)
  → rerank: signal blend  [+ optional LLM rerank]
  → RAG: LLM answer grounded ONLY in retrieved chunks
  → return answer + cited sources
```

### 1. Hybrid retrieval + RRF
[`hybrid_search.py`](query-service/app/search/hybrid_search.py) runs two legs in
one SQL statement, each limited to `SEARCH_CANDIDATE_LIMIT` (100):

- **Vector** — `embedding <=> :query::halfvec` cosine distance over the HNSW
  index. `hnsw.ef_search` is set per query to `max(40, candidate_limit·2)` (= 200 at
  the default candidate limit of 100).
- **Full-text (BM25-style)** — `ts_rank_cd(fts_vector, plainto_tsquery('english', …))`.

Results are fused with **Reciprocal Rank Fusion**:
`RRF = Σ 1/(k + rank_leg)`, `k = 60`, via a `FULL OUTER JOIN` so a chunk found by
either leg contributes. The candidate pool returned is
`max(top_k, RERANK_CANDIDATE_POOL)` so the reranker has room to work.

### 2. Permission filtering (applied inside the SQL)
Optional request headers narrow results before ranking:

| Header | Effect |
|--------|--------|
| `X-Allowed-Spaces` | Keep only docs whose `allowed_spaces` overlaps (`&&`) the list |
| `X-Allowed-Projects` | Keep only docs whose `allowed_projects` overlaps the list |
| `X-Product-Filter` | Keep only docs where `product_hierarchy->>'product'` equals the value |

Absent headers → no filtering (all results eligible). This is an MVP,
header-trust model; see [§ Security](#security-considerations).

### 3. Reranking
[`reranker.py`](query-service/app/search/reranker.py) refines the candidate pool
(enabled by `RERANK_ENABLED`):

1. **Signal blend** (always on, deterministic, cheap). Per candidate:
   `blended = w_rrf·norm(rrf) + w_fresh·freshness + w_auth·authority + w_tax·taxonomy_match`,
   weights normalised internally.
   - `norm(rrf)` — min-max normalised fusion score.
   - `freshness` — exponential decay on `source_updated_at`, half-life
     `RERANK_FRESHNESS_HALF_LIFE_DAYS` (180); neutral 0.5 when unknown.
   - `authority` — per source type (`RERANK_AUTHORITY_*`: Confluence 1.0,
     Jira 0.7, default 0.6).
   - `taxonomy_match` — reward when the query names the candidate's
     product/feature/component (component weighted highest).

   Weights are configurable via `RERANK_WEIGHT_*` (defaults: RRF 0.55,
   freshness/authority/taxonomy 0.15 each — RRF dominates).
2. **Optional LLM rerank** (`RERANK_LLM_ENABLED`). The top
   `RERANK_LLM_TOP_N` (10) blended candidates are reordered by the LLM. Parsing
   is strict and **gracefully degrading**: any malformed/missing response leaves
   the signal order intact, so retrieval never regresses (safe against stubs/offline).

The reranker returns the caller's `top_k`, each carrying a `rerank_score`.

### 4. RAG answer generation
[`answer_generator.py`](query-service/app/rag/answer_generator.py) builds a
context window from the reranked chunks, dedupes sources by `document_id`, and
asks the LLM to answer **using only the provided context** (explicitly told to
say so when context is insufficient — no hallucination) with an inline `Sources`
section.

### Response shape
```json
{
  "answer": "…grounded answer with [N] citations…",
  "sources": [
    {
      "title": "…",
      "source_type": "confluence",
      "source_id": "12345",
      "source_url": "https://…",
      "product_hierarchy": { "product": "Safety", "feature": "…", "component": "…" },
      "relevance_score": 0.83
    }
  ],
  "query": "…",
  "chunks_retrieved": 8,
  "model_used": "llama3.2:3b"
}
```
`relevance_score` is the `rerank_score` when reranking ran, otherwise the raw
RRF score.

### Caching (Redis, optional)

[`cache.py`](query-service/app/cache.py) wraps the query path with a Redis cache
(`REDIS_URL`; blank disables it). Two entry types:

- **Query embedding** — keyed by model + text; TTL `CACHE_EMBEDDING_TTL` (24 h).
- **Answer** — keyed by query, `top_k`, **and the permission scope**
  (`allowed_spaces` / `allowed_projects` / `product_filter`); TTL `CACHE_ANSWER_TTL`
  (1 h). Including the scope in the key means cached answers **never cross access
  boundaries**.

The cache is **fail-open**: any Redis error (or a blank `REDIS_URL`) is treated as a
miss, so the query path still works. The client is a singleton, closed on shutdown.

---

## Product Experts

After every sync, [`expert_refresher.py`](ingestion-service/app/pipeline/expert_refresher.py)
synthesises one `product_experts` row per distinct classified product (excluding
`General`):

1. Find distinct products in `documents`.
2. Fetch up to 50 recent docs per product (each capped at 800 chars).
3. Prompt the LLM for strict JSON: `description`, `compressed_context`,
   `upstream_dependencies`, `downstream_affected`.
4. Upsert via the repository. The product/component uniqueness uses an explicit
   `CAST(:component AS text)` so the `NULL` (product-level) case is type-correct.

Current output is **product-level** (`component` is `NULL`); the schema and
query API already support component-level experts for future use.

**Triggers:** automatic post-sync, or manual
`POST /api/v1/experts/refresh` (admin-gated).
**Consumers:** `GET /api/v1/experts` and `GET /api/v1/experts/{product}` in the
query service — used by humans and by AI agents to ground feature development and
test generation in rich product context (compressed context + dependency graph).

> **Note:** synthesis requires strict-JSON LLM output; `llama3.2:3b` often fails it,
> leaving `product_experts` empty. Retrieval does **not** use this table — see
> [§ Troubleshooting](#troubleshooting).

---

## Configuration

The **complete environment-variable reference** lives in
[README.md § Environment Variables](README.md#environment-variables); the literal
annotated list with both provider blocks is [`.env.example`](.env.example). This
section explains the **behavioural knobs** and their effects:

| Area | Variables | Effect |
|------|-----------|--------|
| AI provider | `OLLAMA_BASE_URL`, `OPENAI_API_KEY`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `LLM_MODEL` | Selects backend + models. `EMBEDDING_DIM` must match the `halfvec(N)` column (see [§ contract](#embedding-dimension-is-a-configuration-contract)). |
| Chunking | `CHUNK_SIZE`, `CHUNK_OVERLAP`, `EMBEDDING_BATCH_SIZE` | Chunk granularity and embedding throughput. |
| Scheduling | `SYNC_CRON` | Cron for automatic incremental sync (5-part expression). |
| Classifier | `CLASSIFICATION_RULE_MIN_SCORE`, `CLASSIFICATION_SEMANTIC_FALLBACK`, `CLASSIFICATION_SEMANTIC_THRESHOLD`, `CLASSIFICATION_REVIEW_THRESHOLD` | Cascade thresholds + review flagging. Lower thresholds = more matches, more false positives. |
| Retrieval | `SEARCH_CANDIDATE_LIMIT`, `TOP_K_RESULTS`, `MAX_QUERY_LENGTH` | Candidate breadth, context size, input guard. |
| Reranking | `RERANK_ENABLED`, `RERANK_CANDIDATE_POOL`, `RERANK_WEIGHT_*`, `RERANK_FRESHNESS_HALF_LIFE_DAYS`, `RERANK_AUTHORITY_*`, `RERANK_LLM_ENABLED`, `RERANK_LLM_TOP_N` | Signal-blend behaviour + optional LLM rerank. |
| Sync & dedupe | `INGEST_CONCURRENCY`, `RECONCILE_ON_FULL_SYNC` | Confluence page concurrency; delete-reconciliation on full sync (empty-id-set safe-guard). Incremental sync also skips unchanged docs via `content_hash`. |
| Caching | `REDIS_URL`, `CACHE_ENABLED`, `CACHE_EMBEDDING_TTL`, `CACHE_ANSWER_TTL` | Query-service Redis cache for embeddings + answers; blank `REDIS_URL` disables, fail-open. Answer keys include the permission scope. |
| Auth | `ADMIN_API_KEY` | Gates all ingestion mutating endpoints. |

---

## Performance Characteristics

| Area | Characteristic |
|------|----------------|
| Vector index | HNSW (`m=24`, `ef_construction=128`); per-query `ef_search = max(40, candidate_limit·2)`. Tune up for recall, down for latency. |
| Hybrid query | Single SQL round-trip; both legs capped at `SEARCH_CANDIDATE_LIMIT`; fused in-DB. |
| Embeddings | Batched (`EMBEDDING_BATCH_SIZE`); dominant cost in ingestion. Local Ollama removes network/cost limits but is CPU/GPU-bound. |
| LLM calls | Per query: 1 embedding + 1 answer (+1 optional rerank). Per ingested doc: 1 embed batch + ≤1 classify LLM call (only ambiguous docs reach stage 3). Per product per sync: 1 expert-synthesis call. |
| Idempotency | Re-sync replaces a document's chunks wholesale; safe to re-run. |
| Resilience | LLM rerank and expert refresh degrade gracefully; a failed document/sync leg is logged and counted, not fatal. |

**Measured (reference corpus — full EN space, 6,593 docs / 15,663 chunks):** hybrid
retrieval p50 ≈ 5.9 ms / p95 ≈ 34 ms (no LLM); warm embed + retrieve ≈ 60 ms; ingest
throughput ~0.86 → 1.47 docs/s with `INGEST_CONCURRENCY=5` (ceiling = serial Ollama
embedding). Full table + reproduction: [TESTING.md § Benchmarks](TESTING.md#benchmarks).

---

## Deployment Architecture

### Docker Compose (recommended)
[`docker-compose.yml`](docker-compose.yml) runs `db`, `ingestion-service`, and
`query-service`. The DB image is `pgvector/pgvector:pg16`; `db/init.sql` runs on
first boot; `product_hierarchy.yaml` is mounted read-only into the ingestion
container; both services wait on the DB health check and read `.env`.
Quick start: [README.md § Quick Start](README.md#quick-start).

### Local development (without Docker)
Run Postgres in Docker and the two services with `uvicorn --reload` on the host.
Step-by-step: [README.md § Local Development](README.md#local-development) and
[POSTGRES.md](POSTGRES.md).

---

## Security Considerations

- **Admin auth.** All ingestion mutating endpoints (`/ingest/*`,
  `/experts/refresh`, `/ingest/status`) require the `X-Admin-Key` header to equal
  `ADMIN_API_KEY`. Wrong/missing key → **401**; unset server key → **503**.
- **Permission model (MVP).** Query permission headers (`X-Allowed-Spaces`,
  `X-Allowed-Projects`, `X-Product-Filter`) are **trusted as supplied** — there
  is no auth on the query service yet. Enforce real identity at an upstream
  gateway/proxy before exposing it. Filtering is applied server-side in SQL
  against `documents.allowed_spaces` / `allowed_projects`.
- **Secrets.** Provided via `.env` (gitignored). Never commit real tokens;
  [`.env.example`](.env.example) contains placeholders only. For local Ollama,
  `OPENAI_API_KEY` may be any non-empty dummy.
- **Data privacy.** Source content is stored in Postgres and sent to the
  configured LLM. **Ollama keeps everything on-prem/offline**; OpenAI sends
  content to OpenAI. Choose the provider per your data-handling requirements.
- **Injection safety.** The query embedding is serialised as a float-only SQL
  literal (no user text); user text reaches SQL only through bound parameters and
  `plainto_tsquery`.

---

## Troubleshooting

### Health checks
```bash
curl http://localhost:8090/api/v1/health      # ingestion → {"status":"ok"}
curl http://localhost:8091/api/v1/health       # query     → {"status":"ok"}
```
Sync state (admin-gated): `GET /api/v1/ingest/status` with `X-Admin-Key`.

### Issue: chunk inserts fail / "expected N dimensions"
**Cause:** embedding-model output dim ≠ `chunks.embedding halfvec(N)`.
Align the model, `EMBEDDING_DIM`, and the column — see
[§ embedding-dimension contract](#embedding-dimension-is-a-configuration-contract)
and [POSTGRES.md § Switching embedding dimension](POSTGRES.md#switching-embedding-dimension).

### Issue: query returns no sources
Likely empty index (run a full sync), an over-narrow permission/product filter,
or both retrieval legs missing. Verify with the queries in
[TESTING.md](TESTING.md) and [POSTGRES.md](POSTGRES.md).

### Issue: 401 from an ingestion endpoint
Wrong or missing `X-Admin-Key` (a server with no `ADMIN_API_KEY` returns 503).

### Issue: everything classifies as `General/Uncategorized`
Taxonomy not loaded or too sparse. Confirm `HIERARCHY_CONFIG_PATH` resolves
inside the container and add `keywords`/`aliases` to nodes, then full-sync.

### Issue: classifications/answers look stale after editing the taxonomy
Classification is computed at ingest time. Trigger a **full sync** to reclassify;
expert records refresh automatically afterward.

### Issue: only ~50 Confluence pages ingested
**Cause:** the Confluence v1 content endpoint paginates by `start=` **offset**, not a
cursor. The client must follow `_links.next` by incrementing `start`
(`confluence_client._fetch_space_pages`). A full EN sync fetches ~7,570 pages, not 50.

### Issue: `product_experts` empty / `/experts` returns nothing
**Cause:** expert synthesis needs strict-JSON LLM output; `llama3.2:3b` frequently
returns invalid JSON (`refreshed=0 failed=N`). Retrieval is unaffected —
`hybrid_search` does not read this table. Fix: request JSON-mode output (Ollama
`format=json`) or use an OpenAI chat model.

---

## Verified end-to-end

The pipeline was validated against the full EROAD Confluence space **`EN`**:
7,570 pages processed (0 failed) → **6,593 documents / 15,663 chunks** (768-dim
`halfvec`) → classified **625 rule + 5,968 semantic** across **3 products**
(Tracking, Platform, Payments). Hybrid retrieval runs p50 ≈ 5.9 ms / p95 ≈ 34 ms over
15.6k chunks ([TESTING.md § Benchmarks](TESTING.md#benchmarks)). Product-expert
synthesis currently yields 0 records on `llama3.2:3b` (see [§ Troubleshooting](#troubleshooting)).
