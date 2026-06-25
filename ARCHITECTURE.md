# iWiki Architecture

RAG-based internal knowledge search platform. Hybrid vector + full-text search → LLM-generated answers with citations from Jira + Confluence.

---

## System Overview

```
┌─────────────────┐
│  Jira + Config  │
│  Confluence     │
└────────┬────────┘
         │ fetch (incremental via updated_at)
         ▼
┌──────────────────────────────────────────┐
│      ingestion-service (port 8090)       │
│  ┌────────────────────────────────────┐  │
│  │ 1. Fetch: Jira/Confluence API      │  │
│  │    - issues, pages, attachments    │  │
│  │    - track via last_sync watermark │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 2. Clean: HTML → text normalization│  │
│  │    - strip markup, fix encoding    │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 3. Chunk: semantic splitting       │  │
│  │    - preserve metadata (source_id) │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 4. Embed: OpenAI / Ollama / Azure  │  │
│  │    - batch endpoints, 1536 dims    │  │
│  │    - fallback to local Ollama      │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 5. Classify: product hierarchy     │  │
│  │    - rule/embed/LLM cascade        │  │
│  │    - assign product/feature        │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 6. Upsert: versioned chunks        │  │
│  │    - idempotent via (source_id+v)  │  │
│  └────────────────────────────────────┘  │
└──────────────────┬───────────────────────┘
                   │ chunks + metadata + vectors
                   ▼
        ┌──────────────────────┐
        │   PostgreSQL 16      │
        │  + pgvector ext      │
        │  (port 5432)         │
        │                      │
        │  - chunks table      │
        │  - ivfflat index     │
        │  - BM25 text index   │
        │  - metadata (source,  │
        │    product, feature) │
        └──────────────────────┘
                   ▲
                   │ RRF search (vector + FTS)
                   │
┌──────────────────────────────────────────┐
│      query-service (port 8091)           │
│  ┌────────────────────────────────────┐  │
│  │ 1. Embed query: OpenAI / Ollama    │  │
│  │    - same model as ingestion       │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 2. Hybrid search:                  │  │
│  │    a) Vector ANN via pgvector      │  │
│  │    b) BM25 full-text search        │  │
│  │    c) Fuse via Reciprocal Rank     │  │
│  │       Fusion (RRF)                 │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 3. Filter by permissions:          │  │
│  │    - X-Allowed-Spaces              │  │
│  │    - X-Allowed-Projects            │  │
│  │    - X-Product-Filter              │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 4. RAG: context-driven generation  │  │
│  │    - GPT-4o-mini or other LLM      │  │
│  │    - top-5 sources → prompt        │  │
│  │    - temperature=0.5 for grounding │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ 5. Format response:                │  │
│  │    - answer + citations            │  │
│  │    - relevance scores              │  │
│  │    - source URLs + metadata        │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
         ▲
         │ JSON REST
         │
    ┌────┴──────┐
    │   Client  │
    │  (webapp, │
    │   CLI)    │
    └───────────┘
```

---

## Data Model

### Chunks Table

Core table storing all ingested + indexed content:

```sql
CREATE TABLE chunks (
  -- PK & identity
  id                    UUID PRIMARY KEY,
  
  -- Source tracking
  source_type           VARCHAR(10),        -- 'jira' | 'confluence'
  source_id             VARCHAR(255),       -- 'PAY-123' | 'page:12345'
  source_url            TEXT,               -- full URL to Jira issue / Confluence page
  
  -- Document metadata
  title                 TEXT,               -- extracted from Jira title / Confluence heading
  chunk_text            TEXT NOT NULL,      -- actual content (semantic chunk)
  chunk_index           INT,                -- sequence within source (0, 1, 2...)
  
  -- Embedding vector (pgvector)
  embedding             vector(1536),       -- dense vector from embedding model
  
  -- Classification (by product_hierarchy.yaml)
  product               VARCHAR(100),       -- e.g. 'Payments', 'Reporting'
  feature               VARCHAR(100),       -- e.g. 'Checkout', 'Analytics'
  
  -- Temporal tracking
  created_at            TIMESTAMP,          -- when chunk was ingested
  updated_at            TIMESTAMP,          -- last updated from source
  source_updated_at     TIMESTAMP,          -- when source item was modified in Jira/Confluence
  
  -- Versioning & deduplication
  content_hash          VARCHAR(64),        -- SHA256 of chunk_text (detect duplicates)
  version               INT DEFAULT 1       -- increment on content change
);

-- Indexes for query performance
CREATE INDEX idx_chunks_source_id ON chunks(source_id);
CREATE INDEX idx_chunks_product_feature ON chunks(product, feature);
CREATE INDEX idx_chunks_updated_at ON chunks(updated_at);  -- incremental sync
CREATE INDEX idx_chunks_embedding ON chunks 
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_text_fts ON chunks 
  USING gin (to_tsvector('english', chunk_text));  -- BM25
```

### Ingestion Metadata Table

Tracks sync watermarks + state:

```sql
CREATE TABLE ingestion_metadata (
  id                       UUID PRIMARY KEY,
  source_type              VARCHAR(10),       -- 'jira' | 'confluence'
  last_sync_time           TIMESTAMP,         -- when last sync completed
  last_error               TEXT,              -- error message if sync failed
  item_count               INT,               -- documents fetched in last sync
  chunk_count              INT,               -- chunks generated in last sync
  sync_duration_ms         INT,               -- time taken (for monitoring)
  created_at               TIMESTAMP,
  updated_at               TIMESTAMP
);
```

---

## Ingestion Pipeline

### Flow: Fetch → Clean → Chunk → Embed → Classify → Upsert

#### 1. Fetch Phase

**Jira:**
- Query via JQL: recent issues updated since `last_sync_time`
- Extract: issue key, title, description, custom fields, attachments
- Pagination: handle large result sets (1000+ issues)
- Error handling: circuit breaker on API rate limit (429)

**Confluence:**
- Query via CQL: pages updated since `last_sync_time`
- Extract: page ID, title, body HTML, attachments, page hierarchy (space/parent)
- Pagination: depth-first traversal
- Error handling: retry on temporary failures

**Incremental vs. Full:**
- **Incremental:** Query `updated > last_sync_time` (hourly cron default)
- **Full:** scan all items, rebuild from scratch (useful after adding products)

#### 2. Clean Phase

Remove noise + normalize encoding:

- Strip HTML tags, convert entities (`&amp;` → `&`)
- Remove embedded images metadata (keep only descriptions)
- Normalize line breaks, collapse multiple spaces
- Detect & preserve code blocks (don't tokenize)
- Fix encoding issues (UTF-8 with replacement chars)

#### 3. Chunk Phase

Split documents into semantic chunks:

- **Strategy:** recursive token counter (sliding window)
- **Target chunk size:** 512 tokens (≈ 2KB text)
- **Overlap:** 50 tokens (preserve context across boundaries)
- **Preserve metadata:** source_id, title, chunk_index attached to each chunk
- **Batching:** 256 chunks per embedding batch

#### 4. Embed Phase

Convert text → dense vectors (1536-dim or custom):

- **Default model:** OpenAI `text-embedding-3-small`
- **Fallback:** Local Ollama (set `OLLAMA_BASE_URL`)
- **Attributes:**
  - Model cost: ~$0.02 per 1M tokens (OpenAI)
  - Latency: ~100ms per 256 chunks
  - Dimension: 1536 (configurable via `EMBEDDING_DIM` + DB schema change)
- **Batch strategy:** send 256 chunks per request (balance speed + cost)
- **Retries:** exponential backoff on rate limits

#### 5. Classify Phase

Assign `{product, feature, component}` plus a `confidence` and `method`, using a
cheapest-first cascade (stops at the first confident stage):

1. **Rule** — keyword/alias hits derived from `product_hierarchy.yaml`
   (deterministic, free, no network). Accepts when the keyword score clears
   `CLASSIFICATION_RULE_MIN_SCORE`.
2. **Semantic** — embedding cosine similarity of the document against each node
   label; accepts above `CLASSIFICATION_SEMANTIC_THRESHOLD`. One embed call,
   node-label embeddings are cached.
3. **LLM** — full LLM classification for ambiguous/low-signal docs; the result
   is validated against the taxonomy (a feature must belong to its product, a
   component to its feature).

```yaml
products:
  - name: "Payments"
    features:
      - name: "Checkout"
        aliases: ["payment flow"]   # optional — boosts rule recall
        keywords: ["3DS", "checkout"]
```

- Fallback: `product: "General"`, `feature: "Uncategorized"` if nothing fits.
- Every result records a `confidence` (0-1) and a `needs_review` flag
  (`confidence < CLASSIFICATION_REVIEW_THRESHOLD`) so low-confidence docs can be
  triaged instead of silently trusted.

#### 6. Upsert Phase

Store chunks idempotently to Postgres:

- **Deduplication key:** `(source_id, version, content_hash)`
- **Upsert logic:** if chunk exists + hash matches → skip; else → insert with new version
- **Concurrency:** connection pool (10 connections) prevents DB saturation
- **Rollback:** if any upsert fails → log + continue (dead letter queueing in future)

**Pseudo-code:**
```python
for chunk_batch in batches(chunks, size=256):
  for chunk in chunk_batch:
    existing = db.query_one(
      """SELECT version, content_hash FROM chunks 
         WHERE source_id = %s ORDER BY version DESC LIMIT 1""",
      chunk.source_id
    )
    if existing and existing.content_hash == chunk.content_hash:
      # No change, skip
      continue
    
    db.upsert("""
      INSERT INTO chunks (id, source_id, ..., version, content_hash)
      VALUES (...)
      ON CONFLICT (source_id, version) 
      DO UPDATE SET updated_at = NOW()
    """)
```

---

## Query Pipeline

### Flow: Embed Query → Hybrid Search → Filter → RAG → Format

#### 1. Embed Query

Convert user question → vector:

- Same model + dimension as ingestion
- Single query embedding (not batched)
- Cached for identical queries (5-min TTL)
- Latency: ~50ms

#### 2. Hybrid Search (RRF)

Two parallel searches fused by score:

**Vector Search (ANN):**
```sql
SELECT id, source_id, chunk_text, 
  1 - (embedding <=> query_embedding::vector) as cosine_sim
FROM chunks
ORDER BY embedding <=> query_embedding::vector
LIMIT 100;  -- retrieve top-100 for re-ranking
```
- Index: `ivfflat` (approximate nearest neighbors)
- Speed: <10ms for 100K+ vectors
- Note: trades accuracy for speed (intentional for UX)

**Full-Text Search (BM25):**
```sql
SELECT id, source_id, chunk_text,
  ts_rank(to_tsvector('english', chunk_text), query_tsquery) as bm25_score
FROM chunks
WHERE to_tsvector('english', chunk_text) @@ query_tsquery
LIMIT 100;
```
- Index: GIN (fast for text queries)
- Speed: <50ms for 100K+ chunks
- Exact term matching (robust to OCR errors vs. vectors)

**Fusion (RRF):**
```python
# Assign rank in each list (1-based)
vector_rank = {doc_id: rank for rank, doc_id in enumerate(vector_results, 1)}
bm25_rank = {doc_id: rank for rank, doc_id in enumerate(bm25_results, 1)}

# RRF score = 1/(rank_v + 1) + 1/(rank_bm25 + 1)
rrf_scores = {}
for doc_id in set(vector_rank.keys()) | set(bm25_rank.keys()):
  rrf_scores[doc_id] = 1/(vector_rank.get(doc_id, 1000) + 1) + \
                       1/(bm25_rank.get(doc_id, 1000) + 1)

# Re-rank by RRF, return top-5
top_5 = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:5]
```

**Why RRF?**
- Vectors excel at semantic similarity (e.g., "payment handling" ≈ "checkout")
- BM25 excels at exact terms (e.g., "3DS2", "API key")
- Fusing both → robust to query phrasing variations

#### 2.5 Reranking

A candidate pool (`RERANK_CANDIDATE_POOL`, default 20) is fetched from hybrid
search, then re-scored before the top-`k` reaches the RAG step:

- **Signal blend** (always on) — weighted sum of normalized RRF score,
  freshness (exponential decay, `RERANK_FRESHNESS_HALF_LIFE_DAYS`), source
  authority (Confluence > Jira > default), and taxonomy match vs the query.
  Weights are configurable (`RERANK_WEIGHT_*`).
- **LLM rerank** (optional, `RERANK_LLM_ENABLED`) — reorders the top
  `RERANK_LLM_TOP_N` via the chat model. Degrades gracefully: any parse/transport
  failure falls back to the signal-blend order, so retrieval never hard-fails.

The chosen `rerank_score` replaces `rrf_score` as the surfaced `relevance_score`.

#### 3. Permission Filtering

Apply request headers before RAG:

- `X-Allowed-Spaces`: only chunks from specified Confluence spaces
- `X-Allowed-Projects`: only chunks from specified Jira projects
- `X-Product-Filter`: only chunks matching single product

**Applied at search time:**
```sql
SELECT ... WHERE chunk_text ... AND
  (space IS NULL OR space = ANY(%s))  -- X-Allowed-Spaces
  AND (project IS NULL OR project = ANY(%s))  -- X-Allowed-Projects
  AND (product IS NULL OR product = %s)  -- X-Product-Filter
```

#### 4. RAG (Retrieval-Augmented Generation)

Generate answer grounded in retrieved sources:

**Prompt template:**
```
You are an internal knowledge assistant for our company.

User Question:
{query}

Below are relevant sources from our Jira and Confluence:

{sources_formatted}

Based ONLY on the above sources, answer the user's question.
If the sources don't contain enough information, say: "I don't have enough information in our knowledge base to answer that."

Answer:
```

**LLM call:**
- Model: `gpt-4o-mini` (cost ~$0.15 per 1M tokens; cheaper + faster than gpt-4)
- Temperature: 0.5 (balance creativity + groundedness)
- Max tokens: 1000 (prevent runaway responses)
- Timeout: 10s (fail-safe for stuck calls)

**Response format:**
```json
{
  "answer": "According to the Payments documentation, ...",
  "sources": [
    {
      "title": "[PAY-123] 3DS2 implementation",
      "source_type": "jira",
      "source_id": "PAY-123",
      "source_url": "https://...",
      "product_hierarchy": {"product": "Payments", "feature": "Checkout"},
      "relevance_score": 0.0321  // from RRF
    },
    ...
  ],
  "query": "How does payment gateway handle 3DS2?",
  "chunks_retrieved": 5,
  "model_used": "gpt-4o-mini"
}
```

---

## Configuration

### Environment Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `iwiki` | DB user |
| `POSTGRES_PASSWORD` | *(secret)* | DB password |
| `POSTGRES_DB` | `iwiki` | DB name |
| `JIRA_BASE_URL` | `https://company.atlassian.net` | Jira instance URL |
| `JIRA_USER_EMAIL` | `robot@company.com` | Jira API user |
| `JIRA_API_TOKEN` | *(secret)* | Jira API token |
| `JIRA_PROJECTS` | `PAY,REP,INFRA` | Projects to ingest |
| `CONFLUENCE_BASE_URL` | `https://company.atlassian.net` | Confluence URL |
| `CONFLUENCE_API_TOKEN` | *(secret)* | Confluence API token |
| `CONFLUENCE_SPACES` | `INTERNAL,DOCS` | Spaces to ingest |
| `OPENAI_API_KEY` | *(secret)* | OpenAI API key |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model name |
| `EMBEDDING_DIM` | `1536` | Vector dimension |
| `LLM_MODEL` | `gpt-4o-mini` | LLM model for RAG |
| `ADMIN_API_KEY` | *(secret)* | Secret for admin endpoints |
| `SYNC_CRON` | `0 * * * *` | Incremental sync schedule (cron) |
| `OLLAMA_BASE_URL` | `http://ollama:11434/v1` | Local Ollama instance (optional) |

### Product Hierarchy

File: `product_hierarchy.yaml`

```yaml
products:
  - name: "Payments"
    features:
      - name: "Checkout"
        keywords: ["checkout", "payment flow", "cart"]
      - name: "3DS"
        keywords: ["3DS2", "strong authentication"]
  - name: "Reporting"
    features:
      - name: "Analytics"
        keywords: ["analytics", "dashboard", "metrics"]
```

Ingestion service loads at startup → re-trigger full sync after edits.

---

## Performance Characteristics

### Ingestion

| Phase | Throughput | Latency | Notes |
|-------|-----------|---------|-------|
| Fetch | 500 issues/min | — | API-limited by Jira/Confluence rate limits |
| Clean + Chunk | 10K chunks/min | — | CPU-bound (Python) |
| Embed | 1K chunks/min | 100ms per 256 chunks | API-limited by OpenAI rate limit (3.5K RPM on free tier) |
| Classify | 100K chunks/min | — | CPU-bound (text matching) |
| Upsert | 5K chunks/min | — | DB-limited by connection pool |
| **Total (E2E)** | ~300 chunks/min | **5-10s per 100 docs** | Embedding is bottleneck |

### Query

| Operation | Latency | Notes |
|-----------|---------|-------|
| Embed query | ~50ms | Single vector |
| Vector search (100K vectors) | ~8ms | pgvector ivfflat |
| BM25 search (100K chunks) | ~40ms | Postgres GIN index |
| RRF fusion | <1ms | In-memory ranking |
| LLM call (RAG) | 2-5s | API call to OpenAI |
| **Total (E2E)** | **2.1-5.1s** | LLM dominates; can be cached per (query, response_tokens) |

### Database

| Metric | Value | Notes |
|--------|-------|-------|
| Max chunks (recommended) | 1M | With 1536-dim vectors = ~6GB storage |
| Index size (ivfflat @ 1M) | ~2GB | Efficient ANN index |
| Incremental sync (100 changes) | ~2s | Depends on embedding batch size |
| Query vector retrieval | <10ms | Even with cold cache |
| Connection pool | 10 connections | Tuned for 3 services (ingestion, query, background tasks) |

---

## Deployment Architecture

### Docker Compose (All-in-one)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./db/init.sql:/docker-entrypoint-initdb.d/init.sql
    # Postgres runs in container, data persists
  
  ingestion-service:
    # Python FastAPI, async handlers
    depends_on: db (via healthcheck)
    env_file: .env
    # Mounts product_hierarchy.yaml (read-only)
  
  query-service:
    # Python FastAPI, async handlers
    depends_on: db (via healthcheck)
    env_file: .env
```

**Scaling concerns:**
- **Ingestion:** single instance (cron-triggered, not event-driven)
- **Query:** can run multiple instances behind load balancer
- **Postgres:** single instance (no replication yet)

### Local Development (without Docker)

```bash
# Terminal 1 — Postgres
docker run -p 5432:5432 ... pgvector/pgvector:pg16

# Terminal 2 — ingestion-service
cd ingestion-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8090 --reload

# Terminal 3 — query-service
cd query-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8091 --reload
```

---

## Security Considerations

### API Authentication

- **Ingestion endpoints:** `X-Admin-Key` header (secret, environment-based)
  - Prevents unauthorized syncs
  - Checked at ingestion-service runtime
- **Query endpoints:** public (no auth), but permission headers allowed
  - Filters results by space/project/product
  - Intended for internal use (if deployed, restrict network access)

### Secrets Management

- All credentials → `.env` file (git-ignored)
- Evaluated at container startup → environment variables
- Never logged (stripped from error messages)
- Example: `OPENAI_API_KEY`, `JIRA_API_TOKEN`, `POSTGRES_PASSWORD`

### Data Privacy

- Chunks stored plaintext in Postgres (for BM25 indexing)
- Vectors opaque to human inspection (useful feature for privacy!)
- No redaction of sensitive data at ingestion time (future enhancement: PII detection)
- Query results include source URLs (rely on Jira/Confluence permission models)

---

## Troubleshooting

### Verification: Health Checks

Before troubleshooting, verify all services are running:

```bash
curl http://localhost:8090/api/v1/ingest/status
curl http://localhost:8091/api/v1/health
# Both should return 200 + healthy status
```

### Issue: "No sources returned" (empty search results)

**Cause:** Vector search failed to retrieve chunks (empty DB, index corrupted, or dimension mismatch).
- Check: At least 10 chunks in DB: `SELECT COUNT(*) FROM chunks;`
- Check: Embedding dimension matches schema: `SELECT dimensions(embedding) FROM chunks LIMIT 1;` should equal `EMBEDDING_DIM` from `.env`
- Fix: Reindex if corrupted: `REINDEX INDEX idx_chunks_embedding;`

### Issue: "Slow queries (>5s)"

**Cause:** Either LLM timeout or DB query slow.
- Check: LLM model overloaded (check OpenAI status page)
- Check: Vector search slow — check pgvector index health: `SELECT idx_scan, idx_tup_fetch FROM pg_stat_user_indexes WHERE indexname = 'idx_chunks_embedding';`
- Tuning: Reduce pgvector `lists` parameter (faster, less accurate): `DROP INDEX idx_chunks_embedding; CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);`

### Issue: "Embedding API 429 (rate limit)"

**Cause:** Batch size too large or API quota exceeded.
- Reduce: `EMBEDDING_BATCH_SIZE` from 256 to 128 in `.env`
- Or: Request quota increase from OpenAI
- Or: Switch to Ollama (local): set `OLLAMA_BASE_URL=http://localhost:11434/v1`

### Issue: "Jira/Confluence connection failed"

**During ingestion logs:**
```bash
docker compose logs -f ingestion-service | grep ERROR
```
- Logs show `[ERROR] Jira connection failed` → verify `JIRA_BASE_URL`, `JIRA_USER_EMAIL`, `JIRA_API_TOKEN` are correct
- Logs show `[ERROR] Confluence connection failed` → verify `CONFLUENCE_BASE_URL`, `CONFLUENCE_API_TOKEN`
- Logs show `401 Unauthorized` → token expired or revoked (refresh in Atlassian account settings)

### Issue: "pgvector dimension mismatch"

**During ingestion:**
```
[ERROR] pgvector dimension mismatch: expected 1536, got 768
```
- Fix: Update DB column before ingesting with new model:
```sql
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);
DROP INDEX idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding ON chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

### Issue: "psql: could not connect to server"

**Cause:** Postgres not running or wrong port.
```bash
# Check if running
docker compose logs db | tail -5

# Check port binding
lsof -i :5432

# Restart
docker compose restart db
# Wait for health
until docker compose exec db pg_isready -U iwiki -d iwiki > /dev/null 2>&1; do sleep 1; done
```

### Issue: "Invalid admin key" (403 Forbidden)

**On sync requests:**
```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: wrong_key"
# Expected: 403 Forbidden
```
- Fix: Verify `ADMIN_API_KEY` in `.env` matches header `X-Admin-Key`

### Debugging: Enable Verbose Logging

```yaml
# docker-compose.yml — add to services
ingestion-service:
  environment:
    LOG_LEVEL: DEBUG

query-service:
  environment:
    LOG_LEVEL: DEBUG
```

Then restart and check logs:
```bash
docker compose restart ingestion-service query-service
docker compose logs -f ingestion-service | grep DEBUG
```

### Debugging: Inspect Database Directly

```bash
# Connect to psql
docker compose exec db psql -U iwiki -d iwiki

# Inside psql:
\dt                          -- list all tables
\d chunks                    -- describe chunks schema
\d+ idx_chunks_embedding     -- inspect vector index details
SELECT COUNT(*) FROM chunks; -- total chunks
SELECT * FROM pg_stat_user_indexes LIMIT 5;  -- index usage stats
```

---

## Future Enhancements

1. **Event-driven ingestion:** Jira/Confluence webhooks → real-time updates
2. **Reranking:** cross-encoder / learning-to-rank to replace the current
   signal-blend + LLM reranker (needs labeled click/feedback data)
3. **Streaming responses:** LLM output → chunked HTTP
4. **Caching layer:** Redis cache for common queries
5. **Analytics:** track query performance + user satisfaction
6. **PII detection:** redact sensitive data at ingestion
7. **Multi-language support:** embeddings + search in multiple languages


