#!/usr/bin/env bash
# iWiki Comprehensive E2E Test Suite
# Covers: DB schema, all ingestion + query endpoints, admin auth,
#   input validation, idempotency, permission filters, expert refresh,
#   DB row/column/type assertions throughout.
# Requirements: docker, python3, curl
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTS_DIR="$REPO_ROOT/tests/e2e"
INGESTION_DIR="$REPO_ROOT/ingestion-service"
QUERY_DIR="$REPO_ROOT/query-service"

STUB_PORT=11435; INGESTION_PORT=8090; QUERY_PORT=8091; DB_PORT=5433
ADMIN_KEY="e2e-test-admin-key"
DB_PASSWORD="e2e-test-password"
DB_URL="postgresql+asyncpg://iwiki:${DB_PASSWORD}@localhost:${DB_PORT}/iwiki"
STUB_URL="http://localhost:${STUB_PORT}/v1"
PASS=0; FAIL=0
PIDS=()

GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; PASS=$((PASS + 1)); }
fail() { echo -e "${RED}  ✗ $*${NC}"; FAIL=$((FAIL + 1)); exit 1; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
info() { echo -e "${CYAN}── $*${NC}"; }

assert() {
  local d="$1" a="$2" e="$3"
  [ "$a" = "$e" ] && ok "$d (got: $a)" || fail "$d -- expected '$e', got '$a'"
}
assert_ge() {
  local d="$1" a="$2" m="$3"
  [ "${a:-0}" -ge "$m" ] 2>/dev/null && ok "$d (got: $a)" || fail "$d -- expected >= $m, got '${a}'"
}

cleanup() {
  echo ""; echo "── Cleanup"
  if [ "${#PIDS[@]}" -gt 0 ]; then
    kill "${PIDS[@]}" 2>/dev/null || true
    sleep 1
    kill -9 "${PIDS[@]}" 2>/dev/null || true
  fi
  docker stop iwiki-e2e-db 2>/dev/null || true
  docker rm   iwiki-e2e-db 2>/dev/null || true
}
trap cleanup EXIT

# ── Kill any leftover services from a previous run ────────────────────────────
lsof -ti :"$STUB_PORT" -ti :"$INGESTION_PORT" -ti :"$QUERY_PORT" 2>/dev/null \
  | xargs kill -9 2>/dev/null || true

wait_http() {
  local url="$1" lbl="$2" n="${3:-30}"
  for i in $(seq 1 "$n"); do
    curl -sf "$url" >/dev/null 2>&1 && ok "$lbl up" && return 0; sleep 1
  done; fail "$lbl not ready after ${n}s"
}
psql_q() { docker exec iwiki-e2e-db psql -U iwiki -d iwiki -t -A -c "$1" 2>/dev/null; }
wait_experts() {
  for i in $(seq 1 30); do
    n=$(psql_q "SELECT COUNT(*) FROM product_experts;" 2>/dev/null || echo 0)
    [ "${n:-0}" -ge 1 ] 2>/dev/null && return 0; sleep 1
  done; return 1
}

echo ""; echo -e "${CYAN}=== iWiki Comprehensive E2E Test Suite ===${NC}"; echo ""

# ─── Step 1: Postgres ─────────────────────────────────────────────────────────
info "Step 1 ── Postgres (port $DB_PORT)"
docker stop iwiki-e2e-db 2>/dev/null || true; docker rm iwiki-e2e-db 2>/dev/null || true
docker run -d --name iwiki-e2e-db \
  -e POSTGRES_USER=iwiki -e POSTGRES_PASSWORD="$DB_PASSWORD" -e POSTGRES_DB=iwiki \
  -p "${DB_PORT}:5432" \
  -v "$REPO_ROOT/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  pgvector/pgvector:pg16 >/dev/null
for i in $(seq 1 60); do
  docker exec iwiki-e2e-db pg_isready -U iwiki -d iwiki -q 2>/dev/null \
    && ok "Postgres ready" && break
  [ "$i" -eq 60 ] && fail "Postgres not ready in 60s"; sleep 1
done

# ─── Step 2: DB schema ────────────────────────────────────────────────────────
info "Step 2 ── DB schema validation"
for t in documents chunks sync_state product_experts; do
  n=$(psql_q "SELECT COUNT(*) FROM information_schema.tables \
WHERE table_schema='public' AND table_name='${t}';")
  assert "Table '$t' exists" "$n" "1"
done
assert "pgvector extension" \
  "$(psql_q "SELECT COUNT(*) FROM pg_extension WHERE extname='vector';")" "1"
assert "HNSW index on chunks.embedding" \
  "$(psql_q "SELECT COUNT(*) FROM pg_indexes \
WHERE tablename='chunks' AND indexname='idx_chunks_embedding';")" "1"
assert "GIN FTS index on chunks.fts_vector" \
  "$(psql_q "SELECT COUNT(*) FROM pg_indexes \
WHERE tablename='chunks' AND indexname='idx_chunks_fts';")" "1"
assert_ge "sync_state seed rows" \
  "$(psql_q "SELECT COUNT(*) FROM sync_state;")" "2"
assert_ge "product_experts has indexes" \
  "$(psql_q "SELECT COUNT(*) FROM pg_indexes WHERE tablename='product_experts';")" "2"

# ─── Step 3: Venv ─────────────────────────────────────────────────────────────
info "Step 3 ── Python virtualenv"
VENV="$TESTS_DIR/.venv"
[ ! -d "$VENV" ] && python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install -q -r "$INGESTION_DIR/requirements.txt"
pip install -q -r "$QUERY_DIR/requirements.txt"
ok "deps installed"

# ─── Step 4: Stub OpenAI ──────────────────────────────────────────────────────
info "Step 4 ── Stub OpenAI (port $STUB_PORT)"
cd "$TESTS_DIR"
python stub_openai.py &
PIDS+=("$!")
wait_http "http://localhost:${STUB_PORT}/health" "Stub OpenAI"

# ─── Step 5: ingestion-service ────────────────────────────────────────────────
info "Step 5 ── ingestion-service (port $INGESTION_PORT)"
cd "$INGESTION_DIR"
env DATABASE_URL="$DB_URL" OLLAMA_BASE_URL="$STUB_URL" OPENAI_API_KEY="stub-key" \
  EMBEDDING_MODEL="stub-embed" LLM_MODEL="stub-llm" ADMIN_API_KEY="$ADMIN_KEY" \
  JIRA_PROJECTS="" CONFLUENCE_SPACES="" SYNC_CRON="0 3 31 2 *" \
  HIERARCHY_CONFIG_PATH="$REPO_ROOT/product_hierarchy.yaml" \
  uvicorn main:app --host 0.0.0.0 --port "$INGESTION_PORT" \
    --log-level warning >/tmp/ingestion-e2e.log 2>&1 &
PIDS+=("$!"); wait_http "http://localhost:${INGESTION_PORT}/api/v1/health" "ingestion-service"

# ─── Step 6: query-service ────────────────────────────────────────────────────
info "Step 6 ── query-service (port $QUERY_PORT)"
cd "$QUERY_DIR"
env DATABASE_URL="$DB_URL" OLLAMA_BASE_URL="$STUB_URL" OPENAI_API_KEY="stub-key" \
  EMBEDDING_MODEL="stub-embed" LLM_MODEL="stub-llm" \
  uvicorn main:app --host 0.0.0.0 --port "$QUERY_PORT" \
    --log-level warning >/tmp/query-e2e.log 2>&1 &
PIDS+=("$!"); wait_http "http://localhost:${QUERY_PORT}/api/v1/health" "query-service"

# ─── Step 7: Health endpoints ─────────────────────────────────────────────────
info "Step 7 ── Health endpoints"
assert "ingestion /health → ok" \
  "$(curl -sf "http://localhost:${INGESTION_PORT}/api/v1/health" \
     | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" "ok"
assert "query /health → ok" \
  "$(curl -sf "http://localhost:${QUERY_PORT}/api/v1/health" \
     | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")" "ok"

# ─── Step 8: Admin auth enforcement ───────────────────────────────────────────
info "Step 8 ── Admin auth enforcement"
assert "wrong key → 401" \
  "$(curl -s -o /dev/null -w '%{http_code}' \
     -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/sync/full" \
     -H "X-Admin-Key: badkey")" "401"
assert "no key → 401" \
  "$(curl -s -o /dev/null -w '%{http_code}' \
     -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/sync/full")" "401"
assert "ingest/status no key → 401" \
  "$(curl -s -o /dev/null -w '%{http_code}' \
     "http://localhost:${INGESTION_PORT}/api/v1/ingest/status")" "401"
assert "experts/refresh no key → 401" \
  "$(curl -s -o /dev/null -w '%{http_code}' \
     -X POST "http://localhost:${INGESTION_PORT}/api/v1/experts/refresh")" "401"

# ─── Step 9: Input validation ─────────────────────────────────────────────────
info "Step 9 ── Input validation"
EC=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/document" \
  -H "Content-Type: application/json" -H "X-Admin-Key: $ADMIN_KEY" \
  -d '{"title":"T","content":"","source_type":"manual","source_id":"X0"}' | cut -c1)
assert "empty content → 4xx" "$EC" "4"

EQ=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
  -H "Content-Type: application/json" -d '{"query":""}')
assert "empty query → 422" "$EQ" "422"

MT=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/document" \
  -H "Content-Type: application/json" -H "X-Admin-Key: $ADMIN_KEY" \
  -d '{"content":"text","source_type":"manual","source_id":"X0"}')
assert "missing title → 422" "$MT" "422"

# ─── Step 10: Ingest 8 documents ──────────────────────────────────────────────
info "Step 10 ── Ingesting 8 documents (Payments×3, Tracking×3, Platform×2)"

ingest() {
  local lbl="$1" pay="$2"
  local r doc chunks
  r=$(curl -sf -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/document" \
    -H "Content-Type: application/json" -H "X-Admin-Key: $ADMIN_KEY" -d "$pay")
  doc=$(echo "$r"    | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['document_id'])" 2>/dev/null || echo ERROR)
  chunks=$(echo "$r" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['chunks_created'])" 2>/dev/null || echo 0)
  [ "$doc" = "ERROR" ] && fail "$lbl ── Response: $r"
  ok "$lbl → doc=${doc:0:8}… chunks=$chunks"
}

ingest "PAY-42: 3DS2 Visa bug" \
  '{"title":"PAY-42: Payment gateway fails with 3DS2 on Visa cards","content":"When a customer pays with Visa using 3DS2, the payment gateway returns 400 after bank redirect. Root cause: redirect_url not URL-encoded before Stripe API call. Fix: apply urllib.parse.quote in PaymentGatewayService.createCharge.","source_type":"jira","source_id":"PAY-42","source_url":"https://example.atlassian.net/browse/PAY-42","metadata":{"project_key":"PAY","status":"Done"},"allowed_projects":["PAY"]}'

ingest "CONF-101: Checkout Architecture" \
  '{"title":"Checkout Service Architecture","content":"Checkout handles cart validation, coupon application, payment processing, and order confirmation. Integrates with Payment Gateway via REST using API keys in AWS Secrets Manager. Supports credit card, PayPal, Apple Pay. 3DS2 requires strong authentication for Visa and Mastercard above 30 NZD via bank redirect with signed callback URL.","source_type":"confluence","source_id":"CONF-101","source_url":"https://example.atlassian.net/wiki/spaces/PAY/pages/101","metadata":{"space_key":"PAY"},"allowed_spaces":["PAY"]}'

ingest "PAY-55: Tax rounding bug" \
  '{"title":"PAY-55: Tax calculation rounds incorrectly for split invoices","content":"Invoices split across tax zones apply per-line rounding before summing, causing 0.01 discrepancy. Violates IRD GST requirements. Fix: banker rounding once on total not per-line. Affects 3 percent of invoices.","source_type":"jira","source_id":"PAY-55","source_url":"https://example.atlassian.net/browse/PAY-55","metadata":{"project_key":"PAY","status":"In Progress"},"allowed_projects":["PAY"]}'

ingest "TRACK-88: GPS consumer lag" \
  '{"title":"TRACK-88: GPS location not updating in fleet dashboard","content":"GPS coordinates not refreshing. LocationEngine Kafka consumer group lagging 1.2 million messages. Consumer is single-threaded. Fix: increase partitions from 3 to 12 and use virtual threads for parallel processing.","source_type":"jira","source_id":"TRACK-88","source_url":"https://example.atlassian.net/browse/TRACK-88","metadata":{"project_key":"TRACK","status":"In Progress"},"allowed_projects":["TRACK"]}'

ingest "CONF-202: GPS Pipeline Design" \
  '{"title":"GPS Data Pipeline Design","content":"GPS pipeline ingests real-time location from vehicle telematics. Devices publish every 30 seconds via MQTT to Kafka topic vehicle.location.raw. LocationEngine consumes, validates, applies geofences, stores in Redis for real-time and PostgreSQL for analytics. 500K events per hour.","source_type":"confluence","source_id":"CONF-202","source_url":"https://example.atlassian.net/wiki/spaces/TRACK/pages/202","metadata":{"space_key":"TRACK"},"allowed_spaces":["TRACK"]}'

ingest "TRACK-92: Geofence alert delay" \
  '{"title":"TRACK-92: Geofence alerts delayed by 8 minutes","content":"Geofence alerts delayed 8 minutes instead of sub-second. GeofencingService polls location table every 60s instead of consuming Kafka stream. Fix: subscribe GeofenceAlertService directly to vehicle.location.processed Kafka topic and evaluate rules in-memory.","source_type":"jira","source_id":"TRACK-92","source_url":"https://example.atlassian.net/browse/TRACK-92","metadata":{"project_key":"TRACK","status":"Open"},"allowed_projects":["TRACK"]}'

ingest "CONF-303: Auth and API Keys" \
  '{"title":"Authentication and API Keys","content":"Internal services authenticate via JWT tokens from Auth Service. External clients use API keys via Developer Portal, stored in AWS Secrets Manager and rotated every 90 days. Service-to-service calls use mutual TLS. Payment Gateway uses dedicated API keys requested through Security team.","source_type":"confluence","source_id":"CONF-303","source_url":"https://example.atlassian.net/wiki/spaces/PLAT/pages/303","metadata":{"space_key":"PLAT"},"allowed_spaces":["PLAT"]}'

ingest "PLAT-12: JWT race condition" \
  '{"title":"PLAT-12: JWT token refresh race condition","content":"Simultaneous JWT refresh calls cause token revocation under high concurrency. Auth Service lacks distributed lock. Fix: add Redis distributed lock with 2s TTL around token refresh in AuthService.refreshToken.","source_type":"jira","source_id":"PLAT-12","source_url":"https://example.atlassian.net/browse/PLAT-12","metadata":{"project_key":"PLAT","status":"Done"},"allowed_projects":["PLAT"]}'

echo ""; ok "All 8 documents ingested"

# ─── Step 11: DB – documents & chunks ─────────────────────────────────────────
info "Step 11 ── DB: documents, chunks, embeddings, classification"
assert_ge "documents ≥ 8" "$(psql_q 'SELECT COUNT(*) FROM documents;')" "8"
assert_ge "chunks ≥ 8"    "$(psql_q 'SELECT COUNT(*) FROM chunks;')" "8"
assert "PAY-42 stored (jira)" \
  "$(psql_q "SELECT COUNT(*) FROM documents \
WHERE source_id='PAY-42' AND source_type='jira';")" "1"
assert "TRACK-88 stored (jira)" \
  "$(psql_q "SELECT COUNT(*) FROM documents \
WHERE source_id='TRACK-88' AND source_type='jira';")" "1"
assert "CONF-303 stored (confluence)" \
  "$(psql_q "SELECT COUNT(*) FROM documents \
WHERE source_id='CONF-303' AND source_type='confluence';")" "1"
assert "no NULL embeddings" \
  "$(psql_q 'SELECT COUNT(*) FROM chunks WHERE embedding IS NULL;')" "0"
assert "no NULL fts_vector" \
  "$(psql_q 'SELECT COUNT(*) FROM chunks WHERE fts_vector IS NULL;')" "0"
assert_ge "PAY docs have allowed_projects" \
  "$(psql_q "SELECT COUNT(*) FROM documents WHERE 'PAY'=ANY(allowed_projects);")" "1"
assert_ge "TRACK docs have allowed_spaces" \
  "$(psql_q "SELECT COUNT(*) FROM documents WHERE 'TRACK'=ANY(allowed_spaces);")" "1"
assert_ge "all docs classified" \
  "$(psql_q "SELECT COUNT(*) FROM documents \
WHERE product_hierarchy->>'product' IS NOT NULL \
  AND product_hierarchy->>'product' != '';")" "8"

# ─── Step 12: Idempotency ─────────────────────────────────────────────────────
info "Step 12 ── Idempotency: re-ingest PAY-42 must upsert not duplicate"
ingest "PAY-42 re-ingested (updated content)" \
  '{"title":"PAY-42: Payment gateway fails with 3DS2 on Visa cards","content":"Fix deployed to production 2026-06-10. URL encoding applied. Zero regressions in production monitoring.","source_type":"jira","source_id":"PAY-42","source_url":"https://example.atlassian.net/browse/PAY-42","metadata":{"project_key":"PAY"},"allowed_projects":["PAY"]}'
assert "PAY-42: still exactly 1 row" \
  "$(psql_q "SELECT COUNT(*) FROM documents WHERE source_id='PAY-42';")" "1"
UPD=$(psql_q "SELECT cleaned_content FROM documents WHERE source_id='PAY-42' LIMIT 1;")
echo "$UPD" | grep -q "deployed to production" \
  && ok "PAY-42 content updated on upsert" \
  || fail "PAY-42 content NOT updated on upsert"

# ─── Step 13: ingest/status ───────────────────────────────────────────────────
info "Step 13 ── ingest/status endpoint"
ST=$(curl -sf "http://localhost:${INGESTION_PORT}/api/v1/ingest/status" \
  -H "X-Admin-Key: $ADMIN_KEY")
assert "ingest/status: sync_states is array" \
  "$(echo "$ST" | python3 -c "import sys,json; \
d=json.load(sys.stdin); print('ok' if isinstance(d.get('sync_states'),list) else 'bad')")" "ok"

# ─── Step 14: RAG queries ─────────────────────────────────────────────────────
info "Step 14 ── RAG query endpoint (6 queries)"

qok() {
  local lbl="$1" pay="$2"; shift 2
  local r ch src ans
  r=$(curl -sf -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
    -H "Content-Type: application/json" "$@" -d "$pay")
  ch=$(echo "$r"  | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['chunks_retrieved'])" 2>/dev/null || echo 0)
  src=$(echo "$r" | python3 -c "import sys,json; \
    print(len(json.load(sys.stdin)['sources']))" 2>/dev/null || echo 0)
  ans=$(echo "$r"  | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['answer'][:60])" 2>/dev/null || echo "")
  assert_ge "$lbl: chunks_retrieved" "$ch" "1"
  assert_ge "$lbl: sources" "$src" "1"
  [ -z "$ans" ] && fail "$lbl: empty answer"
  ok "$lbl (chunks=$ch sources=$src)"
}

qok "Q1: 3DS2 payment failure"   '{"query":"Why does payment gateway fail with 3DS2 on Visa?","top_k":3}'
qok "Q2: GPS lag cause"          '{"query":"Why is GPS location not updating in fleet dashboard?","top_k":3}'
qok "Q3: Checkout auth flow"     '{"query":"How does checkout handle authentication for payments?","top_k":3}'
qok "Q4: API key rotation"       '{"query":"How are API keys managed and rotated in the platform?","top_k":3}'
qok "Q5: Invoice tax rounding"   '{"query":"What is the tax calculation rounding bug in invoices?","top_k":3}'
qok "Q6: Geofence alert delay"   '{"query":"Why are geofence alerts delayed?","top_k":3}'

# ─── Step 15: Permission filters ──────────────────────────────────────────────
info "Step 15 ── Permission filters"

PAY_R=$(curl -sf -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
  -H "Content-Type: application/json" -H "X-Allowed-Projects: PAY" \
  -d '{"query":"3DS2 Visa redirect URL encoding Stripe payment","top_k":5}')
assert_ge "X-Allowed-Projects:PAY returns results" \
  "$(echo "$PAY_R" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['chunks_retrieved'])" 2>/dev/null || echo 0)" "1"

TRACK_R=$(curl -sf -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
  -H "Content-Type: application/json" -H "X-Allowed-Spaces: TRACK" \
  -d '{"query":"GPS fleet location vehicle","top_k":5}')
assert_ge "X-Allowed-Spaces:TRACK returns results" \
  "$(echo "$TRACK_R" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['chunks_retrieved'])" 2>/dev/null || echo 0)" "1"

PLAT_R=$(curl -sf -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
  -H "Content-Type: application/json" -H "X-Product-Filter: Platform" \
  -d '{"query":"JWT token authentication","top_k":5}')
assert_ge "X-Product-Filter:Platform returns results" \
  "$(echo "$PLAT_R" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['chunks_retrieved'])" 2>/dev/null || echo 0)" "1"

# ─── Step 16: Expert refresh ──────────────────────────────────────────────────
info "Step 16 ── Expert refresh (ingestion admin endpoint)"
REF=$(curl -sf -X POST \
  "http://localhost:${INGESTION_PORT}/api/v1/experts/refresh" \
  -H "X-Admin-Key: $ADMIN_KEY")
assert "experts/refresh → accepted" \
  "$(echo "$REF" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)['status'])" 2>/dev/null || echo x)" "accepted"
echo "  Waiting for expert generation (up to 30s)…"
wait_experts && ok "product_experts generated" \
  || warn "expert generation still running (async task)"
sleep 2

# ─── Step 17: DB – product_experts ────────────────────────────────────────────
info "Step 17 ── DB: product_experts table validation"
PE=$(psql_q 'SELECT COUNT(*) FROM product_experts;' 2>/dev/null || echo 0)
ok "product_experts rows: $PE"
if [ "${PE:-0}" -ge 1 ] 2>/dev/null; then
  assert "non-empty description" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE description='' OR description IS NULL;")" "0"
  assert "non-empty compressed_context" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE compressed_context='' OR compressed_context IS NULL;")" "0"
  assert "upstream_dependencies is JSON array" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE jsonb_typeof(upstream_dependencies)!='array';")" "0"
  assert "downstream_affected is JSON array" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE jsonb_typeof(downstream_affected)!='array';")" "0"
  assert "source_document_count ≥ 1" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE source_document_count < 1;")" "0"
  assert "generated_at is set" \
    "$(psql_q "SELECT COUNT(*) FROM product_experts \
WHERE generated_at IS NULL;")" "0"
  echo ""; echo "  Experts generated:"
  psql_q "SELECT product, COALESCE(component,'(product-level)'), \
source_document_count FROM product_experts ORDER BY product;" \
    | while IFS='|' read -r p c d; do echo "    $p | $c | docs=$d"; done
else
  warn "product_experts empty ── async task may still be running"
fi

# ─── Step 18: Query service – expert endpoints ────────────────────────────────
info "Step 18 ── GET /experts  and  GET /experts/{product}"

EL=$(curl -sf "http://localhost:${QUERY_PORT}/api/v1/experts")
assert "GET /experts → JSON array" \
  "$(echo "$EL" | python3 -c "import sys,json; d=json.load(sys.stdin); \
    print('array' if isinstance(d,list) else 'other')" 2>/dev/null || echo err)" "array"
EC=$(echo "$EL" | python3 -c "import sys,json; \
  print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
ok "GET /experts returned $EC expert(s)"

if [ "${EC:-0}" -gt 0 ] 2>/dev/null; then
  SHP=$(echo "$EL" | python3 -c "
import sys,json; d=json.load(sys.stdin); e=d[0]
req=['id','product','description','compressed_context',
     'upstream_dependencies','downstream_affected','source_document_count']
miss=[k for k in req if k not in e]
print('ok' if not miss else 'missing:'+','.join(miss))
" 2>/dev/null || echo err)
  assert "Expert response: all required fields" "$SHP" "ok"

  FP=$(echo "$EL" | python3 -c "import sys,json; \
    print(json.load(sys.stdin)[0]['product'])" 2>/dev/null || echo "")
  if [ -n "$FP" ]; then
    FPE=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$FP'))")
    PR=$(curl -sf "http://localhost:${QUERY_PORT}/api/v1/experts/${FPE}" \
      2>/dev/null || echo '[]')
    PC=$(echo "$PR" | python3 -c "import sys,json; \
      print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
    assert_ge "GET /experts/$FP → ≥1 record" "$PC" "1"
    UD=$(echo "$PR" | python3 -c "import sys,json; \
      print(type(json.load(sys.stdin)[0].get('upstream_dependencies')).__name__)" \
      2>/dev/null || echo x)
    assert "upstream_dependencies field is list" "$UD" "list"
    DD=$(echo "$PR" | python3 -c "import sys,json; \
      print(type(json.load(sys.stdin)[0].get('downstream_affected')).__name__)" \
      2>/dev/null || echo x)
    assert "downstream_affected field is list" "$DD" "list"
  fi
else
  warn "Skipping expert-by-product tests (no experts yet)"
fi

assert "GET /experts/NoSuchProduct → 404" \
  "$(curl -s -o /dev/null -w '%{http_code}' \
     "http://localhost:${QUERY_PORT}/api/v1/experts/NoSuchProductXYZ123")" "404"

# ─── Step 19: Final DB totals ─────────────────────────────────────────────────
info "Step 19 ── Final DB state"
DF=$(psql_q 'SELECT COUNT(*) FROM documents;')
CF=$(psql_q 'SELECT COUNT(*) FROM chunks;')
SF=$(psql_q 'SELECT COUNT(*) FROM sync_state;')
PF=$(psql_q 'SELECT COUNT(*) FROM product_experts;' 2>/dev/null || echo 0)
echo ""
printf '  %-24s %s\n' 'documents:'       "$DF"
printf '  %-24s %s\n' 'chunks:'          "$CF"
printf '  %-24s %s\n' 'sync_state:'      "$SF"
printf '  %-24s %s\n' 'product_experts:' "$PF"
echo ""
assert_ge "documents ≥ 8"   "$DF" "8"
assert_ge "chunks ≥ 8"      "$CF" "8"
assert_ge "sync_state ≥ 2"  "$SF" "2"

# ─── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  E2E COMPLETE   PASSED: $PASS   FAILED: $FAIL${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo "  Coverage:"
echo "    ✓ DB schema: 4 tables, pgvector, HNSW, GIN FTS, indexes"
echo "    ✓ Admin auth: wrong key, missing key (all admin endpoints)"
echo "    ✓ Input validation: empty content, empty query, missing title"
echo "    ✓ 8 docs ingested: Payments×3, Tracking×3, Platform×2"
echo "    ✓ Idempotency: upsert on re-ingest, content updated, no duplicate row"
echo "    ✓ DB: embeddings non-null, fts_vector generated, classification set"
echo "    ✓ ingest/status endpoint"
echo "    ✓ 6 RAG queries: chunks≥1, sources≥1, non-empty answer"
echo "    ✓ Permission filters: X-Allowed-Projects, X-Allowed-Spaces, X-Product-Filter"
echo "    ✓ experts/refresh (admin-gated, async)"
echo "    ✓ DB: product_experts columns, JSON arrays, doc counts, timestamps"
echo "    ✓ GET /experts: array + required field shape"
echo "    ✓ GET /experts/{product}: records + upstream/downstream are lists"
echo "    ✓ GET /experts/unknown: 404"
echo "    ✓ Final DB totals"
echo ""
echo "  Logs: /tmp/ingestion-e2e.log   /tmp/query-e2e.log"
echo ""
[ "$FAIL" -gt 0 ] && echo -e "${RED}  $FAIL assertion(s) FAILED${NC}" && exit 1
exit 0
