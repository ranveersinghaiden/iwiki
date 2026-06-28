# Manual Testing Guide — iWiki

End-to-end procedures for verifying the ingestion pipeline, query/RAG flow,
classification, and product experts. For setup see
[README.md](README.md#local-development); for DB queries see
[POSTGRES.md](POSTGRES.md); for design see [ARCHITECTURE.md](ARCHITECTURE.md).

Set a shell variable for the admin key used below:
```bash
ADMIN=your_strong_admin_key_here
```

---

## Prerequisites

Services running (Docker or host) and healthy:
```bash
docker compose up -d
curl http://localhost:8090/api/v1/health   # → {"status":"ok"}
curl http://localhost:8091/api/v1/health   # → {"status":"ok"}
```
Both health endpoints are **open** and return `{"status":"ok"}`. Per-source sync
state is **admin-gated**:
```bash
curl http://localhost:8090/api/v1/ingest/status -H "X-Admin-Key: $ADMIN"
```

---

## 1. Full Ingestion Sync

Verifies fetch → clean → chunk → embed → classify → upsert, then automatic
product-expert refresh.

```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/full -H "X-Admin-Key: $ADMIN"
# → 202 {"status":"accepted","sync_type":"full","triggered_at":"…"}
docker compose logs -f ingestion-service
```
**Expect:** fetch logs per source → chunk/embed → classify → upsert → finally
`[ExpertRefresher] refreshing N products`. Then verify in Postgres:
```sql
SELECT count(*) FROM documents;
SELECT count(*) FROM chunks;
SELECT vector_dims(embedding) FROM chunks LIMIT 1;        -- matches EMBEDDING_DIM
SELECT source_type, last_run_status, total_items_indexed FROM sync_state;
```
**Reference corpus:** a full EN-space sync yields **6,593 documents / 15,663
chunks** — see [§ Benchmarks](#benchmarks).

**Failure modes:**
- Inserts fail with a dimensions error → embedding width ≠ `halfvec(N)` column
  ([POSTGRES.md § Switching embedding dimension](POSTGRES.md#switching-embedding-dimension)).
- 0 documents → check Jira/Confluence credentials and that `JIRA_PROJECTS` /
  `CONFLUENCE_SPACES` are set.

---

## 2. Incremental Sync

Only items updated since the `sync_state` watermark are processed.

```bash
curl -X POST http://localhost:8090/api/v1/ingest/sync/incremental -H "X-Admin-Key: $ADMIN"
docker compose logs -f ingestion-service | grep -i "sync start\|sync done"
```
**Expect:** logs show `full=False watermark=<timestamp>` and a small processed
count. Automatic runs fire on `SYNC_CRON` (default hourly); to test the schedule,
set `SYNC_CRON=*/5 * * * *`, `docker compose restart ingestion-service`, and wait.

Verify the watermark advanced:
```sql
SELECT source_type, last_synced_at FROM sync_state;
```

### Delete reconciliation
Removes indexed docs that no longer exist at the source. Runs automatically on every
**full** sync, and on demand:
```bash
curl -X POST http://localhost:8090/api/v1/ingest/reconcile -H "X-Admin-Key: $ADMIN"  # → 202
```
**Safety guard:** if a source returns an **empty** id set (e.g. an API outage), its
reconciliation is **skipped** — nothing is deleted.

---

## 3. Direct Document Ingestion

Index one inline document through the full pipeline (handy without Jira/Confluence):
```bash
curl -X POST http://localhost:8090/api/v1/ingest/document \
  -H "X-Admin-Key: $ADMIN" -H "Content-Type: application/json" \
  -d '{
        "title": "Clarity Dashcam fatigue alerts",
        "content": "The Clarity Dashcam detects driver fatigue and raises in-cab alerts...",
        "source_type": "manual",
        "source_id": "TEST-001",
        "allowed_spaces": ["EN"]
      }'
# → 201 {"document_id":"…","source_id":"TEST-001","chunks_created":N,"classification":{...}}
```
The `classification` object in the response shows `product/feature/component`,
`method`, `confidence`, `needs_review`.

---

## 4. Query / RAG Pipeline

Verifies embed → hybrid (FTS + vector) → RRF → rerank → grounded answer.

```bash
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How does Clarity Dashcam detect fatigue?", "top_k": 8}'
```
**Expect:** `answer` text plus `sources[]` (each with `title`, `source_type`,
`source_id`, `source_url`, `product_hierarchy`, `relevance_score`),
`chunks_retrieved`, and `model_used`. When the index lacks relevant content the
answer should say so rather than fabricate.

**Reranking behaviour** (`reranker.py`): inspect logs for the reranker line.
```bash
docker compose logs query-service | grep -i "reranked"   # "reranked N candidates → top_k=… (llm=…)"
```
- `relevance_score` is the blended `rerank_score` when reranking ran (else raw RRF).
- The LLM rerank degrades gracefully: with an offline/unavailable LLM the signal
  order is kept and retrieval still returns results.
- Toggle with `RERANK_ENABLED` / `RERANK_LLM_ENABLED` and compare ordering.

**Permission filters:**
```bash
# Restrict to Confluence spaces
curl -X POST http://localhost:8091/api/v1/query -H "Content-Type: application/json" \
  -H "X-Allowed-Spaces: EN" -d '{"query":"fatigue detection"}'

# Restrict to one product
curl -X POST http://localhost:8091/api/v1/query -H "Content-Type: application/json" \
  -H "X-Product-Filter: Safety" -d '{"query":"how are alerts raised?"}'
```
**Expect:** every returned source respects the filter (matching space, or
`product_hierarchy.product == "Safety"`).

---

## 5. Classification Cascade

Verifies rule → semantic → LLM tagging (see
[ARCHITECTURE.md § Classification](ARCHITECTURE.md#classification--hybrid-3-stage-cascade)).

```sql
-- Spread by product + method
SELECT product_hierarchy->>'product'  AS product,
       product_hierarchy->>'method'   AS method,
       count(*)
FROM documents GROUP BY 1,2 ORDER BY 3 DESC;

-- Low-confidence items queued for review
SELECT source_id, product_hierarchy->>'product', product_hierarchy->>'confidence'
FROM documents WHERE (product_hierarchy->>'needs_review')::bool LIMIT 20;
```
**Expect:** a mix of `rule` and `semantic` methods; `llm`/`fallback` only on
ambiguous docs. After editing the taxonomy (`HIERARCHY_CONFIG_PATH` / the mounted
`product_hierarchy.yaml`), run a **full sync** to reclassify, then re-check.

---

## 6. Product Experts

Verifies post-sync synthesis and the query-service endpoints.

```bash
# Manual refresh (also runs automatically after every sync)
curl -X POST http://localhost:8090/api/v1/experts/refresh -H "X-Admin-Key: $ADMIN"   # → 202

# List all experts
curl http://localhost:8091/api/v1/experts

# One product (optional ?component=)
curl http://localhost:8091/api/v1/experts/Safety
```
**Expect:** one record per classified product (excluding `General`), each with
`description`, `compressed_context`, `upstream_dependencies`,
`downstream_affected`, and `source_document_count`. Unknown product → `404`.
```sql
SELECT product, component, source_document_count, updated_at FROM product_experts ORDER BY product;
```
> **Known issue (local Ollama):** with `llama3.2:3b` the synthesis prompt returns
> invalid JSON, so `product_experts` stays **empty** (`refreshed=0 failed=N`) and the
> `/experts` endpoints return `[]` / `404`. `hybrid_search` does **not** read this
> table, so retrieval is unaffected. Fix tracked in
> [ARCHITECTURE.md § Troubleshooting](ARCHITECTURE.md#troubleshooting).

---

## 7. Error Handling

```bash
# Wrong admin key → 401 (NOT 403)
curl -i -X POST http://localhost:8090/api/v1/ingest/sync/full -H "X-Admin-Key: wrong"

# Missing admin key → 401
curl -i -X POST http://localhost:8090/api/v1/experts/refresh

# Empty query → 422 (pydantic validation: min_length=1)
curl -i -X POST http://localhost:8091/api/v1/query -H "Content-Type: application/json" -d '{"query":""}'

# Over-length query → 422 (exceeds MAX_QUERY_LENGTH)

# DB down → query returns a 500 error envelope; restart with: docker compose start db
docker compose stop db
curl -i -X POST http://localhost:8091/api/v1/query -H "Content-Type: application/json" -d '{"query":"test"}'
docker compose start db
```
Unhandled exceptions are caught by a global handler returning
`{"error":"Internal server error"}` with HTTP 500.

---

## Benchmarks

Reference corpus: the full EROAD Confluence **`EN`** space — **6,593 documents /
15,663 chunks** (768-dim `halfvec`, HNSW `m=24, ef_construction=128`).

| Metric | Value | Notes |
|--------|-------|-------|
| Full EN ingest | 7,570 pages → 6,593 docs / 15,663 chunks | 0 failed; rest filtered (empty / no-chunk / non-current bodies) |
| Ingest throughput | ~0.86 → **1.47 docs/s** | After `INGEST_CONCURRENCY=5`; ceiling is Ollama serial embedding |
| Retrieval p50 | **≈ 5.9 ms** | Pure `hybrid_search` (pgvector HNSW + FTS + RRF), no LLM, 15.6k chunks |
| Retrieval p95 | **≈ 34 ms** | same |
| Warm embed + retrieve | **≈ 60 ms** | ~45 ms `nomic-embed-text` embed + ~16 ms retrieve; excludes LLM answer |

Retrieval timing covers `hybrid_search` only (vector + FTS + RRF), excluding
embedding and answer generation. The query service sets `hnsw.ef_search =
max(40, 2×SEARCH_CANDIDATE_LIMIT)` (= 200 at the default 100). Reproduce the DB-side
vector latency with psql timing (wrap in a txn so `SET LOCAL` applies):
```bash
docker compose exec db psql -U iwiki -d iwiki -c "\timing on" -c "
BEGIN;
SET LOCAL hnsw.ef_search = 200;
SELECT id FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks LIMIT 1)
LIMIT 8;
COMMIT;"
```
Embedding latency depends on the Ollama host; warm figures assume a resident
`nomic-embed-text` model.

---

## Cleanup & Reset

```bash
# Full reset (wipes DB volume; preserves .env)
docker compose down -v && docker compose up -d

# Restart services only (keep data)
docker compose restart ingestion-service query-service

# Clear one source (cascades to its chunks)
docker compose exec db psql -U iwiki -d iwiki \
  -c "DELETE FROM documents WHERE source_type='jira'; VACUUM (FULL) chunks;"
```

After a reset, re-run the [full sync](#1-full-ingestion-sync) to repopulate.
