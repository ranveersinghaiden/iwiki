# Manual Testing Guide — iWiki

Comprehensive procedures for testing ingestion pipeline, query RAG, and database behavior.

---

## Prerequisites

Ensure services running:

```bash
docker compose up -d
# or (local dev)
# Terminal 1: postgres docker run (see README "Local Development")
# Terminal 2: uvicorn main:app --port 8090 --reload (ingestion-service)
# Terminal 3: uvicorn main:app --port 8091 --reload (query-service)
```

Verify all services healthy:

```bash
curl http://localhost:8090/api/v1/ingest/status
curl http://localhost:8091/api/v1/health
```

Both should return 200.

---

## Manual Test Scenarios

### 1. Full Ingestion Sync

**Purpose:** Verify end-to-end pipeline (fetch → chunk → embed → classify → upsert).

**Steps:**

```bash
# Trigger full sync
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: your_strong_admin_key_here"

# Response: 202 Accepted (async)
# {
#   "status": "sync_started",
#   "request_id": "uuid-here",
#   "mode": "full"
# }
```

**Watch logs (live):**

```bash
docker compose logs -f ingestion-service
```

**Expected sequence in logs:**
1. `[INFO] Fetching Jira issues from projects: PROJ1, PROJ2`
2. `[INFO] Fetched N issues, M pages from Confluence`
3. `[INFO] Chunking N documents`
4. `[INFO] Embedding batch 1 of X`
5. `[INFO] Classifying N chunks against product hierarchy`
6. `[INFO] Upserting N chunks to database`
7. `[INFO] Full sync completed in Xs`

**Verify in Postgres:**

```bash
# Connect to DB
psql postgresql://iwiki:iwiki@localhost:5432/iwiki

# Count chunks ingested
SELECT COUNT(*) FROM chunks;

# View sample chunk metadata
SELECT id, source_type, source_id, product, feature, chunk_index, created_at 
FROM chunks LIMIT 5;

# Check vector dimension (should match EMBEDDING_DIM)
SELECT dimensions(embedding) FROM chunks LIMIT 1;
```

**Failure modes:**
- Logs show `[ERROR] Jira connection failed` → verify `JIRA_BASE_URL`, `JIRA_API_TOKEN`
- Logs show `[ERROR] Chunk count mismatch` → check input data not empty
- Logs show `[ERROR] pgvector dimension mismatch` → verify `EMBEDDING_DIM` matches model output

---

### 2. Incremental Sync

**Purpose:** Verify delta sync only processes updated items.

**Steps:**

```bash
# Note timestamp before sync
echo "Before: $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Trigger incremental sync
curl -X POST http://localhost:8090/api/v1/ingest/sync/incremental \
  -H "X-Admin-Key: your_strong_admin_key_here"

# Watch logs
docker compose logs -f ingestion-service | grep "incremental"
```

**Expected logs:**
```
[INFO] Starting incremental sync
[INFO] Last synced: 2026-06-15T10:30:00Z
[INFO] Fetching changes since last sync
[INFO] Found 3 updated issues, 1 updated page
```

**Verify in Postgres:**

```bash
-- Items updated after first sync
SELECT COUNT(*) FROM chunks WHERE updated_at > '2026-06-15T10:30:00Z';

-- Last sync timestamp recorded
SELECT last_sync_time FROM ingestion_metadata LIMIT 1;
```

**Test incremental cron (if enabled):**

```bash
# Edit .env: SYNC_CRON=*/5 * * * *  (every 5 minutes, for testing)
docker compose restart ingestion-service

# Wait 5+ minutes, check logs for auto-triggered sync
docker compose logs -f ingestion-service | grep "incremental"
```

---

### 3. Query RAG Pipeline

**Purpose:** Verify end-to-end question answering with vector search + hybrid ranking + LLM generation.

**Steps:**

```bash
# Test 1: Simple factual query
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How does payment gateway handle 3DS2?"
  }'
```

**Expected response:**
```json
{
  "answer": "According to the Payments documentation, 3DS2...",
  "sources": [
    {
      "title": "[PAY-123] 3DS2 implementation",
      "source_type": "jira",
      "source_id": "PAY-123",
      "source_url": "https://...",
      "product_hierarchy": {
        "product": "Payments",
        "feature": "Checkout"
      },
      "relevance_score": 0.0321,
      "chunk_text": "3DS2 enables dynamic authentication..."
    }
  ],
  "query": "How does payment gateway handle 3DS2?",
  "chunks_retrieved": 5,
  "model_used": "gpt-4o-mini"
}
```

**Test 2: Query with permission filters (space restriction):**

```bash
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-Allowed-Spaces: SPACE1,SPACE2" \
  -d '{
    "query": "How does payment gateway handle 3DS2?"
  }'
```

**Expected:** Response includes sources only from SPACE1, SPACE2.

**Test 3: Query with product filter:**

```bash
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-Product-Filter: Payments" \
  -d '{
    "query": "How does the system handle errors?"
  }'
```

**Expected:** All sources have `product_hierarchy.product == "Payments"`.

**Verify in Postgres (hybrid search internals):**

```bash
-- Check RRF scoring (combined vector + BM25)
SELECT 
  id, 
  source_id, 
  ts_rank(to_tsvector(chunk_text), query) as bm25_score,
  1 - (embedding <=> query_embedding::vector) as cosine_score
FROM chunks
LIMIT 10;

-- Check citation metadata
SELECT source_type, source_id, COUNT(*) 
FROM chunks 
GROUP BY source_type, source_id 
LIMIT 10;
```

**Failure modes:**
- No sources returned → vector search failed; check pgvector index health
- Wrong sources returned → RRF ranking misconfigured
- LLM doesn't use sources → check LLM model context window
- Slow response (>5s) → check pgvector index `lists` parameter, consider tuning

---

### 4. Product Hierarchy Classification

**Purpose:** Verify documents classified correctly against `product_hierarchy.yaml`.

**Steps:**

```bash
# View current hierarchy
cat product_hierarchy.yaml

# Manually upsert test chunk (triggers classification)
psql postgresql://iwiki:iwiki@localhost:5432/iwiki << EOF
INSERT INTO chunks (source_type, source_id, chunk_text, created_at, updated_at)
VALUES (
  'jira',
  'TEST-001',
  'This is about the Payment Gateway feature in Checkout',
  NOW(),
  NOW()
);
EOF

# Trigger ingestion to classify
curl -X POST http://localhost:8090/api/v1/ingest/sync/incremental \
  -H "X-Admin-Key: your_strong_admin_key_here"

# Verify classification
psql postgresql://iwiki:iwiki@localhost:5432/iwiki -c \
  "SELECT source_id, product, feature FROM chunks WHERE source_id = 'TEST-001';"
```

**Expected:** `product = "Payments", feature = "Checkout"`.

**Modify hierarchy and re-sync:**

```bash
# Edit product_hierarchy.yaml (e.g., add new feature)
vim product_hierarchy.yaml

# Re-trigger full sync to reclassify all
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: your_strong_admin_key_here"

# Verify all chunks reclassified
docker compose logs -f ingestion-service | grep "product_hierarchy"
```

---

### 5. Embedding Model Switching

**Purpose:** Verify system works with different embedding models + dimensions.

**Steps:**

```bash
# Current config
grep EMBEDDING_ .env

# Switch to Ollama local model (768-dim)
# .env changes:
# EMBEDDING_MODEL=nomic-embed-text
# EMBEDDING_DIM=768
# OLLAMA_BASE_URL=http://localhost:11434/v1

# Update DB column
psql postgresql://iwiki:iwiki@localhost:5432/iwiki << EOF
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);
DROP INDEX idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding ON chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
EOF

# Restart services
docker compose restart ingestion-service query-service

# Re-ingest (full sync with new model)
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: your_strong_admin_key_here"

# Verify dimension
psql postgresql://iwiki:iwiki@localhost:5432/iwiki -c \
  "SELECT dimensions(embedding) FROM chunks LIMIT 1;"
```

**Expected:** Dimension changes from 1536 → 768.

---

### 6. Concurrency & Load Testing

**Purpose:** Verify system handles concurrent queries + incremental syncs.

**Steps:**

```bash
# Terminal 1: Run 10 concurrent queries
for i in {1..10}; do
  curl -X POST http://localhost:8091/api/v1/query \
    -H "Content-Type: application/json" \
    -d "{\"query\": \"Query number $i\"}" &
done
wait

# Terminal 2: Check response times in logs
docker compose logs -f query-service | grep "query_time_ms"
```

**Expected:** All queries complete <5s; no connection pool exhaustion errors.

```bash
# Stress test: rapid full syncs (should queue requests)
for i in {1..3}; do
  curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
    -H "X-Admin-Key: your_strong_admin_key_here" &
done

# Check ingestion service handles gracefully
docker compose logs ingestion-service | grep "queue\|lock\|conflict"
```

---

### 7. Error Handling

**Purpose:** Verify graceful degradation under error conditions.

**Test 1: Invalid admin key**

```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/full \
  -H "X-Admin-Key: wrong_key"
# Expected: 403 Forbidden
```

**Test 2: Database unavailable**

```bash
# Stop DB
docker compose stop db

# Try query
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'

# Expected: 503 Service Unavailable (circuit breaker engaged)

# Restart DB
docker compose start db
```

**Test 3: Invalid query (empty string)**

```bash
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": ""}'

# Expected: 400 Bad Request (or auto-handles gracefully)
```

---

## Health Check Endpoints

Quick status verification:

```bash
# Ingestion service status + watermarks
curl http://localhost:8090/api/v1/ingest/status

# Query service health
curl http://localhost:8091/api/v1/health

# Expected response:
# {"status": "healthy", "database": "ok", "embedding_service": "ok"}
```

---

## Performance Baselines

Record these metrics during manual testing:

| Metric | Target | Command |
|--------|--------|---------|
| Full sync (100 docs) | <30s | Time full sync completion |
| Incremental sync | <5s | Time incremental sync |
| Query latency (p95) | <2s | Use `curl ... \| jq .response_time_ms` |
| Embedding batch (256 chunks @ 768-dim) | <10s | Check ingestion logs |
| Vector search (retrieval only) | <100ms | Postgres query profile |

---

## Debugging Tips

**Enable verbose logging in docker-compose:**

```yaml
# Add to ingestion-service & query-service
environment:
  LOG_LEVEL: DEBUG
```

**Inspect database directly:**

```bash
# Connect via terminal
docker compose exec db psql -U iwiki -d iwiki

# Inside psql:
\d chunks              -- describe chunks table
\d+ idx_chunks_embedding -- inspect pgvector index
SELECT * FROM pg_stat_user_indexes LIMIT 5;  -- index usage stats
```

**Check vector search quality:**

```sql
-- Sample vector similarity search
SELECT id, source_id, 
  1 - (embedding <=> (SELECT embedding FROM chunks LIMIT 1)::vector) as similarity
FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1)::vector
LIMIT 5;
```

**Monitor resource usage:**

```bash
# CPU/memory per service
docker compose stats

# Network I/O
docker compose exec db iostat -x 1 5
```

---

## Cleanup & Reset

**Full reset (preserves secrets in .env):**

```bash
# Stop all
docker compose down -v

# Remove cached models/embeddings
rm -rf ingestion-service/.cache query-service/.cache

# Restart
docker compose up -d
```

**Partial reset (keep Postgres data):**

```bash
docker compose restart ingestion-service query-service
```

**Cherry-pick reset (delete specific tables):**

```bash
docker compose exec db psql -U iwiki -d iwiki << EOF
DELETE FROM chunks WHERE source_type = 'jira';  -- clear Jira only
VACUUM FULL chunks;  -- reclaim space
EOF
```

---


