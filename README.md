# iWiki — Internal Knowledge Search Platform

RAG-based search over **Confluence + Jira**. Content is ingested into
**Postgres + pgvector**, classified against a **product taxonomy**, and answered
with an LLM over **hybrid retrieval (full-text + vector) with reranking** —
returning grounded answers with citations. Runs fully **local/offline with
Ollama**, or against **OpenAI**.

## Documentation

| Document | Purpose |
|----------|---------|
| **README.md** (this file) | Quick start, environment variables, API reference, local development |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Authoritative system design: data model, pipelines, classifier, reranker, product experts, configuration behaviour, security, troubleshooting |
| [POSTGRES.md](POSTGRES.md) | Postgres access, connection methods, index/embedding-dimension operations, backup/restore |
| [TESTING.md](TESTING.md) | Manual end-to-end test procedures |

---

## Architecture at a glance

```
Confluence / Jira
  → ingestion-service  (fetch → clean → chunk → embed → classify → upsert; refresh experts)
  → PostgreSQL + pgvector  (documents · chunks · sync_state · product_experts)
  ← query-service  (embed → hybrid FTS+vector → RRF → rerank → LLM RAG → answer + citations)
```

| Service | Port | Role |
|---------|------|------|
| `ingestion-service` | 8090 | Fetch, clean, chunk, embed, classify, index; synthesise product experts; schedule incremental syncs |
| `query-service` | 8091 | Natural-language query → retrieval + rerank + RAG answer; serve product experts |
| `db` (pgvector/pgvector:pg16) | 5432 | Vector + full-text + metadata storage |

Full design — including the 3-stage classifier and the reranker — is in
[ARCHITECTURE.md](ARCHITECTURE.md).

---

## Quick Start

### 1. Configure
```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, ADMIN_API_KEY, Jira/Confluence credentials,
# and choose an AI provider block (Ollama local or OpenAI).
```

**Choose your AI provider** (see [`.env.example`](.env.example) for both blocks):
- **Ollama (local, default)** — matches the shipped `halfvec(768)` schema. Pull
  the models first: `ollama pull nomic-embed-text && ollama pull llama3.2:3b`.
- **OpenAI** — set `EMBEDDING_MODEL=text-embedding-3-small`, `EMBEDDING_DIM=1536`,
  and migrate the embedding column to `halfvec(1536)` (see
  [POSTGRES.md](POSTGRES.md#switching-embedding-dimension)). The embedding
  dimension **must** match the DB column — see
  [ARCHITECTURE.md § embedding-dimension contract](ARCHITECTURE.md#embedding-dimension-is-a-configuration-contract).

### 2. Start everything
```bash
docker compose up -d
```

### 3. Run the initial full sync (admin-gated)
```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: your_strong_admin_key_here"
# → 202 {"status":"accepted","sync_type":"full","triggered_at":"…"}
```
Watch progress: `docker compose logs -f ingestion-service`. Product-expert
synthesis runs automatically when the sync completes (best-effort — see
[ARCHITECTURE.md § Troubleshooting](ARCHITECTURE.md#troubleshooting)).

### 4. Ask a question
```bash
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How does Clarity Dashcam handle fatigue detection?", "top_k": 8}'
```
```json
{
  "answer": "…grounded answer with [N] citations…",
  "sources": [
    { "title": "…", "source_type": "confluence", "source_id": "12345",
      "source_url": "https://…",
      "product_hierarchy": { "product": "Safety", "feature": "Video Telematics", "component": "Clarity Dashcam" },
      "relevance_score": 0.83 }
  ],
  "query": "…",
  "chunks_retrieved": 8,
  "model_used": "llama3.2:3b"
}
```

---

## Environment Variables

This is the **complete reference**. The literal annotated file with both provider
blocks is [`.env.example`](.env.example); for how these knobs affect behaviour
see [ARCHITECTURE.md § Configuration](ARCHITECTURE.md#configuration). `case_sensitive`
is off, so names may be set in any case; UPPER_SNAKE shown by convention.

### PostgreSQL & services
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_USER` | optional | `iwiki` | DB user (docker-compose) |
| `POSTGRES_PASSWORD` | ✅ | — | DB password (docker-compose) |
| `POSTGRES_DB` | optional | `iwiki` | DB name (docker-compose) |
| `POSTGRES_PORT` | optional | `5432` | Published DB port |
| `DATABASE_URL` | ✅ | `…@localhost:5432/iwiki` | Async DSN (`postgresql+asyncpg://…`). **docker-compose overrides this to host `db`**; set localhost for host-run services |
| `INGESTION_PORT` / `QUERY_PORT` | optional | `8090` / `8091` | Published service ports |

### Admin auth
| Variable | Required | Description |
|----------|----------|-------------|
| `ADMIN_API_KEY` | ✅ | Secret for the `X-Admin-Key` header on all ingestion mutating endpoints. Blank → those endpoints return 503 |

### Sources — Jira & Confluence
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JIRA_BASE_URL` | ✅* | — | `https://your-org.atlassian.net` |
| `JIRA_USER_EMAIL` | ✅* | — | Atlassian account email |
| `JIRA_API_TOKEN` | ✅* | — | Jira API token |
| `JIRA_PROJECTS` | ✅* | — | Comma-separated project keys; blank skips Jira |
| `JIRA_PAGE_SIZE` | optional | `100` | Results per Jira page request |
| `CONFLUENCE_BASE_URL` | ✅* | — | Usually same host as Jira |
| `CONFLUENCE_API_TOKEN` | ✅* | — | Confluence API token |
| `CONFLUENCE_SPACES` | ✅* | — | Comma-separated space keys; blank skips Confluence |
| `CONFLUENCE_PAGE_SIZE` | optional | `50` | Results per Confluence page request (raise to ~100 for faster bulk ingest) |

\* Required only for the source you intend to index.

### AI provider (set ONE block — see [`.env.example`](.env.example))
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | ✅ | — | OpenAI key, or any non-empty dummy for Ollama |
| `OLLAMA_BASE_URL` | optional | unset | Set → route to local Ollama (`http://localhost:11434/v1`; Docker: `http://host.docker.internal:11434/v1`). Unset → OpenAI |
| `EMBEDDING_MODEL` | optional | `text-embedding-3-small` | `nomic-embed-text` (768) for Ollama; `text-embedding-3-small` (1536) for OpenAI |
| `EMBEDDING_DIM` | optional | `1536` | **Advisory.** Must equal the model output **and** `chunks.embedding halfvec(N)` (shipped: 768). Changing it alone does nothing — also `ALTER` the column |
| `LLM_MODEL` | optional | `gpt-4o-mini` | Chat model for classify/answer/rerank (`llama3.2:3b` for Ollama) |

> The shipped schema is `halfvec(768)` (Ollama `nomic-embed-text`). For OpenAI
> 1536-dim embeddings, migrate the column — see [POSTGRES.md](POSTGRES.md#switching-embedding-dimension).

### Ingestion tuning
| Variable | Default | Description |
|----------|---------|-------------|
| `CHUNK_SIZE` | `512` | Tokens per chunk |
| `CHUNK_OVERLAP` | `64` | Token overlap between chunks |
| `EMBEDDING_BATCH_SIZE` | `32` | Texts per embedding API call |
| `INGEST_CONCURRENCY` | `5` | Source docs processed concurrently per sync (Confluence pages are windowed; Jira stays serial) |
| `SYNC_CRON` | `0 * * * *` | 5-part cron for automatic incremental sync (default hourly) |
| `RECONCILE_ON_FULL_SYNC` | `true` | On full sync, delete docs removed at the source; skipped if a source returns an empty id set |

### Classification (taxonomy + cascade)
| Variable | Default | Description |
|----------|---------|-------------|
| `HIERARCHY_CONFIG_PATH` | `product_hierarchy.yaml` | Taxonomy YAML the classifier loads (mounted into the ingestion container) |
| `CLASSIFICATION_RULE_MIN_SCORE` | `3.0` | Min keyword score for the rule stage |
| `CLASSIFICATION_SEMANTIC_FALLBACK` | `true` | Run the embedding-similarity stage when rules miss |
| `CLASSIFICATION_SEMANTIC_THRESHOLD` | `0.45` | Min cosine similarity to accept a semantic match |
| `CLASSIFICATION_REVIEW_THRESHOLD` | `0.5` | Below this confidence → `needs_review` |

### Retrieval & reranking (query-service)
| Variable | Default | Description |
|----------|---------|-------------|
| `SEARCH_CANDIDATE_LIMIT` | `100` | Candidates pulled from each of the vector + FTS legs; also sets `hnsw.ef_search = max(40, 2×limit)` |
| `TOP_K_RESULTS` | `8` | Default chunks passed to the LLM (request `top_k` overrides, 1–20) |
| `MAX_QUERY_LENGTH` | `4096` | Max characters in a user query |
| `RERANK_ENABLED` | `true` | Master switch for the signal-blend rerank |
| `RERANK_CANDIDATE_POOL` | `50` | Pool size pulled before reranking |
| `RERANK_WEIGHT_RRF` | `0.55` | Weight: normalised RRF fusion score |
| `RERANK_WEIGHT_FRESHNESS` | `0.15` | Weight: recency decay |
| `RERANK_WEIGHT_AUTHORITY` | `0.15` | Weight: source authority |
| `RERANK_WEIGHT_TAXONOMY` | `0.15` | Weight: query↔taxonomy match |
| `RERANK_FRESHNESS_HALF_LIFE_DAYS` | `180` | Freshness exponential-decay half-life |
| `RERANK_AUTHORITY_CONFLUENCE` | `1.0` | Authority weight for Confluence |
| `RERANK_AUTHORITY_JIRA` | `0.7` | Authority weight for Jira |
| `RERANK_AUTHORITY_DEFAULT` | `0.6` | Authority weight for other sources |
| `RERANK_LLM_ENABLED` | `true` | Optional LLM rerank of the top-N (degrades gracefully) |
| `RERANK_LLM_TOP_N` | `10` | How many blended candidates the LLM reranks |

### Redis cache (query-service)
Caches query embeddings and full answers. **Fail-open**: if Redis is unreachable or `REDIS_URL` is blank, the query path still works (cache treated as a miss).
| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | compose: `redis://redis:6379/0` | Cache DSN. **Blank disables caching** (code default is blank; docker-compose and `.env.example` set it) |
| `CACHE_ENABLED` | `true` | Master switch for the cache |
| `CACHE_EMBEDDING_TTL` | `86400` | Query-embedding TTL (seconds; deterministic → long) |
| `CACHE_ANSWER_TTL` | `3600` | Answer TTL (seconds). Answer keys include the permission scope, so cached answers never cross access boundaries |
| `REDIS_PORT` | `6379` | Published Redis port (docker-compose) |

---

## API Reference

Both services serve under `/api/v1`. Interactive docs: `/docs` on each port.

### Ingestion service (`:8090`) — mutating endpoints require `X-Admin-Key`
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/ingest/sync/full` | admin | Full re-index of all configured sources → `202` |
| `POST` | `/api/v1/ingest/sync/incremental` | admin | Sync only items updated since the watermark → `202` |
| `POST` | `/api/v1/ingest/reconcile` | admin | Delete indexed docs no longer present at the source (empty-id-set safe-guard) → `202` |
| `POST` | `/api/v1/ingest/document` | admin | Index one inline document through the full pipeline → `201` |
| `POST` | `/api/v1/experts/refresh` | admin | Re-synthesise all product experts → `202` |
| `GET` | `/api/v1/ingest/status` | admin | Per-source sync state (`sync_states`) |
| `GET` | `/api/v1/health` | open | `{"status":"ok"}` |

Wrong/missing admin key → **401**; server with no `ADMIN_API_KEY` → **503**.

### Query service (`:8091`)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/query` | Ask a question → answer + cited sources |
| `GET` | `/api/v1/experts` | List all product experts |
| `GET` | `/api/v1/experts/{product}` | Expert(s) for a product (optional `?component=`); `404` if none |
| `GET` | `/api/v1/health` | `{"status":"ok"}` |

**`POST /api/v1/query`** body: `{"query": "<text>", "top_k": <1-20, default 8>}`.
Optional permission headers (trusted as supplied — enforce identity upstream):

| Header | Example | Effect |
|--------|---------|--------|
| `X-Allowed-Spaces` | `EN,DEV` | Restrict to those Confluence spaces |
| `X-Allowed-Projects` | `PROJ1,PROJ2` | Restrict to those Jira projects |
| `X-Product-Filter` | `Safety` | Restrict to one product (from the hierarchy) |

Response fields: `answer`, `sources[]` (`title`, `source_type`, `source_id`,
`source_url`, `product_hierarchy`, `relevance_score`), `query`,
`chunks_retrieved`, `model_used`.

---

## Product Hierarchy

Every document is classified to `product → feature → component` via a 3-stage
cascade (rule → semantic → LLM) — see
[ARCHITECTURE.md § Classification](ARCHITECTURE.md#classification--hybrid-3-stage-cascade).

- Default sample taxonomy: [`product_hierarchy.yaml`](product_hierarchy.yaml).
- Committed EROAD taxonomy: [`product_hierarchy.eroad.yaml`](product_hierarchy.eroad.yaml)
  (generated from `.agents/knowledge/product-map.json`).

Point `HIERARCHY_CONFIG_PATH` at the file you want (or replace the file mounted
by docker-compose), then run a **full sync** to reclassify everything.

---

## Local Development

Run Postgres in Docker and the services on the host with hot reload. Detailed
Postgres setup/connection options are in [POSTGRES.md](POSTGRES.md).

```bash
# 1. Start Postgres only
docker compose up -d db
until docker compose exec db pg_isready -U iwiki -d iwiki >/dev/null 2>&1; do sleep 1; done

# 2. In .env, point DATABASE_URL at localhost:
#    DATABASE_URL=postgresql+asyncpg://iwiki:<password>@localhost:5432/iwiki

# 3. ingestion-service (terminal A)
cd ingestion-service && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8090 --reload

# 4. query-service (terminal B)
cd query-service && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8091 --reload
```

> `tiktoken` is optional (needs Rust); without it the chunker falls back to a
> word-based approximation. Everything else is pure-Python.

> Redis is optional for local query-service runs — the cache fails open. To enable
> it: `docker compose up -d redis` and set `REDIS_URL=redis://localhost:6379/0`.

For manual test procedures (sync, query, classification, experts, error cases),
see [TESTING.md](TESTING.md).

---

## Verified end-to-end

Validated against the full EROAD Confluence space **`EN`**: 7,570 pages processed
(0 failed) → **6,593 documents / 15,663 chunks** (768-dim `halfvec`); classified
625 rule + 5,968 semantic across 3 products (Tracking, Platform, Payments). Hybrid
retrieval (pgvector HNSW + FTS, no LLM) runs p50 ≈ 6 ms / p95 ≈ 34 ms over 15.6k
chunks — see [TESTING.md § Benchmarks](TESTING.md#benchmarks). Product-expert
synthesis currently yields 0 records on `llama3.2:3b` — see
[ARCHITECTURE.md § Troubleshooting](ARCHITECTURE.md#troubleshooting).
