# PostgreSQL Access & Operations

Practical guide to connecting to and operating the iWiki database. The **schema
itself** (tables, columns, indexes) is documented once in
[ARCHITECTURE.md § Data Model](ARCHITECTURE.md#data-model) — this file does not
duplicate it.

**At a glance:** PostgreSQL 16, image `pgvector/pgvector:pg16`, single required
extension **`vector`** (`pg_trgm` is **not** used). Vector index is **HNSW**;
full-text uses a **generated `tsvector` column** with a GIN index. DDL:
[`db/init.sql`](db/init.sql).

---

## Quick Reference

| Scenario | Command |
|----------|---------|
| Start everything | `docker compose up -d` |
| Start DB only (host dev) | `docker compose up -d db` |
| psql in the container | `docker compose exec db psql -U iwiki -d iwiki` |
| psql from the host | `psql postgresql://iwiki:<password>@localhost:5432/iwiki` |
| One-off SQL | `docker compose exec db psql -U iwiki -d iwiki -c "SELECT count(*) FROM chunks;"` |
| GUI (DBeaver/DataGrip) | Host `localhost`, port `5432`, db/user `iwiki`, password from `.env` |

Credentials come from `.env` (`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`).

---

## Connection Strings

```
# Tools / psql (libpq):
postgresql://<user>:<password>@<host>:5432/<db>

# Application services (async SQLAlchemy + asyncpg) — DATABASE_URL:
postgresql+asyncpg://<user>:<password>@<host>:5432/<db>
```
Host is `db` **inside** the Docker network, `localhost` from your machine.
docker-compose injects the in-network `DATABASE_URL` for the services; set the
`localhost` form in `.env` only when running services directly on the host.

---

## Connection Methods

### psql (container or host)
```bash
docker compose exec db psql -U iwiki -d iwiki      # inside the container
psql postgresql://iwiki:<password>@localhost:5432/iwiki   # from the host (needs psql installed)
```
Install psql on the host if needed: `brew install postgresql@16` (macOS) or
`sudo apt-get install postgresql-client-16` (Debian/Ubuntu).

### GUI tools (DBeaver, DataGrip, VS Code)
PostgreSQL connection: host `localhost`, port `5432`, database `iwiki`, user
`iwiki`, password from `.env`. Good for browsing `documents`/`chunks` and running
ad-hoc SQL.

### Python (async)
```python
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine("postgresql+asyncpg://iwiki:<password>@localhost:5432/iwiki")
    async with engine.begin() as conn:
        n = (await conn.execute(text("SELECT count(*) FROM chunks"))).scalar()
        print("chunks:", n)
    await engine.dispose()

asyncio.run(main())
```

---

## Verifying the Database

```sql
-- Extensions: only `vector` is required (no pg_trgm)
SELECT extname FROM pg_extension ORDER BY extname;

-- Row counts
SELECT count(*) FROM documents;
SELECT count(*) FROM chunks;

-- Embedding width — MUST equal the model output and EMBEDDING_DIM
SELECT vector_dims(embedding) FROM chunks LIMIT 1;

-- Indexes on chunks (expect HNSW on embedding + GIN on fts_vector)
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks';

-- Classification spread
SELECT product_hierarchy->>'product' AS product, count(*)
FROM documents GROUP BY 1 ORDER BY 2 DESC;

-- needs_review queue
SELECT count(*) FROM documents WHERE (product_hierarchy->>'needs_review')::bool;

-- Sync watermarks
SELECT source_type, last_synced_at, total_items_indexed, last_run_status FROM sync_state;

-- Product experts
SELECT product, component, source_document_count, updated_at FROM product_experts ORDER BY product;
```

Sanity-check retrieval directly:
```sql
-- Vector neighbours of an arbitrary chunk (HNSW, cosine distance)
SELECT id, 1 - (embedding <=> (SELECT embedding FROM chunks LIMIT 1)) AS similarity
FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1)
LIMIT 5;

-- Full-text leg
SELECT c.id, ts_rank_cd(c.fts_vector, plainto_tsquery('english', 'fatigue detection')) AS score
FROM chunks c
WHERE c.fts_vector @@ plainto_tsquery('english', 'fatigue detection')
ORDER BY score DESC LIMIT 10;
```

---

## Switching embedding dimension

The shipped schema is **`vector(768)`** (Ollama `nomic-embed-text`). To move to a
different width — e.g. OpenAI `text-embedding-3-small` (**1536**) — the model
output, `EMBEDDING_DIM`, and the column must all agree (see
[ARCHITECTURE.md § embedding-dimension contract](ARCHITECTURE.md#embedding-dimension-is-a-configuration-contract)).
Existing 768-dim vectors cannot be reinterpreted, so re-ingest after migrating.

```sql
-- 1. Resize the column (drops incompatible existing vectors' usability — plan a full re-sync)
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536);

-- 2. Rebuild the HNSW index for the new width
DROP INDEX IF EXISTS idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding ON chunks
  USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
```
Then set `EMBEDDING_MODEL`/`EMBEDDING_DIM` in `.env`, restart both services, and
run a **full sync** (`POST /api/v1/ingest/sync/full`) to regenerate embeddings.
For a clean slate instead, edit `vector(768)` in `db/init.sql` and recreate the
volume (`docker compose down -v && docker compose up -d`).

---

## Migrating an existing DB to halfvec + content_hash

The current schema stores embeddings as **`halfvec(768)`** (16-bit) instead of
`vector(768)` (32-bit). This halves index size and RAM with negligible recall loss
— the key lever for the 1–10M-chunk scale band. Fresh databases get this from
`db/init.sql` automatically. To migrate an **existing** database in place:

```sql
-- 0. Requires pgvector >= 0.7 (the pgvector/pgvector:pg16 image ships 0.8). Check:
SELECT extversion FROM pg_extension WHERE extname = 'vector';

-- 1. Add the content-hash column used to skip re-embedding unchanged documents.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_hash TEXT;

-- 2. Drop the HNSW index FIRST — a vector_cosine_ops index blocks the type change.
DROP INDEX IF EXISTS idx_chunks_embedding;

-- 3. Convert the embedding column to halfvec (existing values are cast in place).
ALTER TABLE chunks ALTER COLUMN embedding TYPE halfvec(768);

-- 4. Rebuild the HNSW index with the halfvec operator class and retuned params.
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding halfvec_cosine_ops) WITH (m = 24, ef_construction = 128);
```

Notes:
- The index **must** be dropped before the `ALTER COLUMN` — Postgres rejects the type
  change while a `vector_cosine_ops` index still references the column.
- `content_hash` backfills as `NULL`; the next sync repopulates it. Until then those
  documents are simply re-embedded once (no skip), which is harmless.
- Index rebuild can be slow on large tables — run it during a maintenance window, or
  use `CREATE INDEX CONCURRENTLY` (outside a transaction) to avoid blocking writes.
- To roll back: drop the index, `ALTER TABLE chunks ALTER COLUMN embedding TYPE
  vector(768);`, then recreate the index with `vector_cosine_ops`.

---

## HNSW Index Tuning

The vector index is HNSW (`m=16`, `ef_construction=64`) — it works from a single
row, unlike IVFFlat. Recall vs. latency is controlled at query time by
`hnsw.ef_search`; the query service sets it per request to
`max(40, SEARCH_CANDIDATE_LIMIT·2)`. To experiment manually:

```sql
SET hnsw.ef_search = 80;   -- higher = better recall, slower
-- …run a vector query…
REINDEX INDEX idx_chunks_embedding;   -- only if the index is bloated
```
Build-time knobs (`m`, `ef_construction`) require recreating the index as shown
above.

---

## Backup & Restore

```bash
# Logical dump (portable)
docker compose exec -T db pg_dump -U iwiki -d iwiki -Fc -f /tmp/iwiki.dump
docker compose cp db:/tmp/iwiki.dump ./iwiki.dump

# Restore
docker compose cp ./iwiki.dump db:/tmp/iwiki.dump
docker compose exec -T db pg_restore -U iwiki -d iwiki --clean --if-exists /tmp/iwiki.dump

# Whole data volume (binary, fastest full backup)
docker run --rm -v iwiki_pgdata:/data -v "$(pwd)":/backup ubuntu \
  tar cf /backup/pgdata.tar -C /data .
```
The vector index rebuilds automatically on restore of a logical dump.

---

## Troubleshooting

### `psql: could not connect to server`
DB not up or wrong port. `docker compose logs db | tail`, confirm `5432` is free
(`lsof -i :5432`), then `docker compose restart db` and wait for the health check.

### `password authentication failed`
`.env` `POSTGRES_PASSWORD` doesn't match the initialised volume. The password is
only applied on first init — to change it on an existing volume, reset:
`docker compose down -v && docker compose up -d db` (**wipes data**).

### `type "vector" does not exist`
Wrong image. Must be `pgvector/pgvector:pg16` (check `docker-compose.yml`).
`db/init.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;` on first boot only —
recreate the volume if it was initialised with a non-pgvector image.

### `expected N dimensions, not M` on insert
Embedding width ≠ column width. See [§ Switching embedding dimension](#switching-embedding-dimension).

### Disk full
`docker system df`; drop stale rows (e.g. `DELETE FROM documents WHERE source_type='jira';`
cascades to chunks) and `VACUUM (FULL) chunks;`, or grow the volume.

---

For end-to-end functional testing (sync, query, classification, experts) see
[TESTING.md](TESTING.md).
