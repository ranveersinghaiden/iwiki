# iWiki — Internal Knowledge Search Platform

RAG-based search over Jira + Confluence.  
Hybrid vector + FTS search → LLM-generated answers with citations.

---

## Documentation

| Document | Purpose |
|----------|---------|
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | System design, data model, pipeline flows, performance, deployment, and troubleshooting guide |
| **[README.md](README.md)** | (This file) Quick start, environment variables, API reference, local development setup |

> **Archived:** [TESTING.md](TESTING.md) and [POSTGRES.md](POSTGRES.md) content consolidated into ARCHITECTURE.md § Troubleshooting and README.md § Local Development.

---

## Architecture

```
Jira / Confluence
  → ingestion-service (fetch → clean → chunk → embed → classify → upsert)
  → PostgreSQL + pgvector
  ← query-service (embed query → hybrid search → RRF → LLM RAG → answer + citations)
```

| Service | Port | Role |
|---------|------|------|
| `ingestion-service` | 8090 | Fetch, chunk, embed, index |
| `query-service` | 8091 | Natural-language query + RAG answer |
| `db` (Postgres 16 + pgvector) | 5432 | Vector + FTS + metadata storage |

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env — fill in all credentials
```

### 2. Start everything

```bash
docker compose up -d
```

### 3. Run full initial sync

```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
     -H "X-Admin-Key: your_strong_admin_key_here"
```

Watch logs: `docker compose logs -f ingestion-service`

### 4. Query

```bash
curl -X POST http://localhost:8091/api/v1/query \
     -H "Content-Type: application/json" \
     -d '{"query": "How does the payment gateway handle 3DS2?"}'
```

Response:
```json
{
  "answer": "According to the Payments documentation...",
  "sources": [
    {
      "title": "[PAY-123] 3DS2 implementation",
      "source_type": "jira",
      "source_id": "PAY-123",
      "source_url": "https://your-org.atlassian.net/browse/PAY-123",
      "product_hierarchy": {"product": "Payments", "feature": "Checkout"},
      "relevance_score": 0.0321
    }
  ],
  "query": "How does the payment gateway handle 3DS2?",
  "chunks_retrieved": 5,
  "model_used": "gpt-4o-mini"
}
```

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_PASSWORD` | ✅ | Postgres password |
| `JIRA_BASE_URL` | ✅ | `https://your-org.atlassian.net` |
| `JIRA_USER_EMAIL` | ✅ | Jira account email |
| `JIRA_API_TOKEN` | ✅ | Jira API token (Atlassian account settings) |
| `JIRA_PROJECTS` | ✅ | Comma-separated project keys, e.g. `PROJ1,PROJ2` |
| `CONFLUENCE_BASE_URL` | ✅ | Usually same as `JIRA_BASE_URL` |
| `CONFLUENCE_API_TOKEN` | ✅ | Confluence API token |
| `CONFLUENCE_SPACES` | ✅ | Comma-separated space keys |
| `OPENAI_API_KEY` | ✅ | OpenAI API key (or leave blank if using Ollama) |
| `ADMIN_API_KEY` | ✅ | Secret key for admin endpoints |
| `EMBEDDING_MODEL` | optional | Default: `text-embedding-3-small` (1536 dim) |
| `EMBEDDING_DIM` | optional | Default: `1536` — must match model output dim |
| `LLM_MODEL` | optional | Default: `gpt-4o-mini` |
| `OLLAMA_BASE_URL` | optional | Set to use local Ollama, e.g. `http://ollama:11434/v1` |
| `SYNC_CRON` | optional | Default: `0 * * * *` (every hour) |

---

## Using a Different Embedding Model

If you switch to a **768-dimension** model (e.g. `nomic-embed-text` via Ollama):

1. Set `EMBEDDING_MODEL=nomic-embed-text` and `EMBEDDING_DIM=768` in `.env`
2. Update the DB column before first sync:

```sql
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);
DROP INDEX idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding ON chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## Ingestion API (requires `X-Admin-Key` header)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/ingest/sync/full` | Full re-index of all sources |
| `POST` | `/api/v1/ingest/sync/incremental` | Sync only items updated since last run |
| `GET` | `/api/v1/ingest/status` | Show sync state + watermarks |

---

## Query API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/query` | Ask a question, get answer + citations |
| `GET` | `/api/v1/health` | Health check |

### Optional query headers (permission filtering)

| Header | Example | Effect |
|--------|---------|--------|
| `X-Allowed-Spaces` | `SPACE1,SPACE2` | Restrict to Confluence spaces |
| `X-Allowed-Projects` | `PROJ1,PROJ2` | Restrict to Jira projects |
| `X-Product-Filter` | `Payments` | Restrict to one product (from hierarchy) |

---

## Product Hierarchy

Edit `product_hierarchy.yaml` to match your product structure before first sync.  
The ingestion service mounts this file at `/app/product_hierarchy.yaml` in Docker.  
After editing, re-trigger a full sync to reclassify all documents.

---

## Incremental Sync

Incremental sync runs automatically on the `SYNC_CRON` schedule (default: hourly).  
It fetches only items with `updated_at > last_synced_at` from each source.  
Trigger manually:

```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/incremental \
     -H "X-Admin-Key: your_admin_key"
```

---

## Local Development (without Docker)

Three terminals:

```bash
# Terminal 1 — Postgres (or: docker compose up -d db)
docker run -p 5432:5432 \
  -e POSTGRES_USER=iwiki -e POSTGRES_PASSWORD=iwiki -e POSTGRES_DB=iwiki \
  -v $(pwd)/db/init.sql:/docker-entrypoint-initdb.d/init.sql \
  pgvector/pgvector:pg16

# Terminal 2 — ingestion-service
cd ingestion-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env  # edit credentials
uvicorn main:app --port 8090 --reload

# Terminal 3 — query-service
cd query-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --port 8091 --reload
```

### Database Connection Methods

| Scenario | Command | Notes |
|----------|---------|-------|
| Postgres in Docker (compose) | `docker compose up -d db` | Easiest for local dev |
| Postgres standalone | `docker run ... pgvector/pgvector:pg16` | Full control, more manual setup |
| psql CLI (from container) | `docker compose exec db psql -U iwiki -d iwiki` | Direct SQL access |
| psql CLI (from host) | `psql postgresql://iwiki:iwiki@localhost:5432/iwiki` | Requires `psql` installed locally |
| GUI tools (DBeaver, DataGrip) | Connect to `localhost:5432` user `iwiki` password `iwiki` | Visual exploration |

### Postgres Connection String

```
postgresql://[user]:[password]@[host]:[port]/[database]
postgresql://iwiki:iwiki@localhost:5432/iwiki
```

For async Python (FastAPI):
```
postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki
```

### Quick Database Checks

```bash
# Connect to Postgres
docker compose exec db psql -U iwiki -d iwiki

# Inside psql:
SELECT COUNT(*) FROM chunks;                    -- total chunks
SELECT dimensions(embedding) FROM chunks LIMIT 1;  -- verify vector dim (should match EMBEDDING_DIM)
SELECT * FROM pg_stat_user_indexes LIMIT 5;    -- index health
\q  -- exit
```

**Full setup walkthrough:** See [ARCHITECTURE.md](ARCHITECTURE.md) § Deployment Architecture

**Complete POSTGRES.md reference (backup/restore, tuning, connection methods, troubleshooting):** See archived [POSTGRES.md](POSTGRES.md)

