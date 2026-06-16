#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# iWiki E2E data-flow test
# Tests: DB schema → ingestion pipeline → vector+FTS storage → hybrid search → RAG answer
#
# No real Jira/Confluence or OpenAI credentials needed.
# Uses stub OpenAI server + direct document injection.
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTS_DIR="$REPO_ROOT/tests/e2e"
INGESTION_DIR="$REPO_ROOT/ingestion-service"
QUERY_DIR="$REPO_ROOT/query-service"

STUB_PORT=11435
INGESTION_PORT=8090
QUERY_PORT=8091
DB_PORT=5433          # use 5433 for test to avoid clashing with local postgres

ADMIN_KEY="e2e-test-admin-key"
DB_PASSWORD="e2e-test-password"
DB_URL="postgresql+asyncpg://iwiki:${DB_PASSWORD}@localhost:${DB_PORT}/iwiki"
STUB_URL="http://localhost:${STUB_PORT}/v1"

# ── pids to clean up ──────────────────────────────────────────────────────────
PIDS=()     # initialise before set -u is applied to array reads

cleanup() {
    echo ""
    echo "── Cleanup ──────────────────────────────────────────────────────────────"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    echo "[cleanup] stopping test DB container..."
    docker stop iwiki-e2e-db 2>/dev/null || true
    docker rm   iwiki-e2e-db 2>/dev/null || true
    echo "[cleanup] done"
}
trap cleanup EXIT

# ── colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
fail() { echo -e "${RED}  ✗ $*${NC}"; exit 1; }
info() { echo -e "${CYAN}── $*${NC}"; }

wait_for_http() {
    local url="$1" label="$2" retries="${3:-30}"
    for i in $(seq 1 "$retries"); do
        if curl -sf "$url" > /dev/null 2>&1; then
            ok "$label is up"
            return 0
        fi
        sleep 1
    done
    fail "$label did not start within ${retries}s (url=$url)"
}

# ── Step 1: Start test Postgres ───────────────────────────────────────────────
info "Step 1 — Starting test Postgres (port $DB_PORT)"
# Remove stale container from a previous failed run if present
docker stop iwiki-e2e-db 2>/dev/null || true
docker rm   iwiki-e2e-db 2>/dev/null || true
docker run -d --name iwiki-e2e-db \
    -e POSTGRES_USER=iwiki \
    -e POSTGRES_PASSWORD="$DB_PASSWORD" \
    -e POSTGRES_DB=iwiki \
    -p "${DB_PORT}:5432" \
    -v "$REPO_ROOT/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
    pgvector/pgvector:pg16 > /dev/null

info "Waiting for Postgres to be ready..."
for i in $(seq 1 30); do
    if docker exec iwiki-e2e-db pg_isready -U iwiki -d iwiki -q 2>/dev/null; then
        ok "Postgres ready"
        break
    fi
    if [ "$i" -eq 30 ]; then fail "Postgres did not become ready in 30s"; fi
    sleep 1
done

# ── Step 2: Create shared virtualenv ─────────────────────────────────────────
info "Step 2 — Setting up Python virtual environment"
VENV_DIR="$TESTS_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

info "Installing ingestion-service dependencies..."
pip install -q -r "$INGESTION_DIR/requirements.txt"
info "Installing query-service dependencies..."
pip install -q -r "$QUERY_DIR/requirements.txt"
ok "Dependencies installed"

# ── Step 3: Start stub OpenAI server ─────────────────────────────────────────
info "Step 3 — Starting stub OpenAI server (port $STUB_PORT)"
cd "$TESTS_DIR"
python stub_openai.py &
PIDS+=("$!")
wait_for_http "http://localhost:${STUB_PORT}/health" "Stub OpenAI"

# ── Step 4: Start ingestion-service ──────────────────────────────────────────
info "Step 4 — Starting ingestion-service (port $INGESTION_PORT)"
cd "$INGESTION_DIR"
env \
    DATABASE_URL="$DB_URL" \
    OLLAMA_BASE_URL="$STUB_URL" \
    OPENAI_API_KEY="stub-key" \
    EMBEDDING_MODEL="stub-embedding" \
    LLM_MODEL="stub-llm" \
    ADMIN_API_KEY="$ADMIN_KEY" \
    JIRA_PROJECTS="" \
    CONFLUENCE_SPACES="" \
    SYNC_CRON="0 3 31 2 *" \
    HIERARCHY_CONFIG_PATH="$REPO_ROOT/product_hierarchy.yaml" \
    uvicorn main:app --host 0.0.0.0 --port "$INGESTION_PORT" \
        --log-level warning > /tmp/ingestion-e2e.log 2>&1 &
PIDS+=("$!")
wait_for_http "http://localhost:${INGESTION_PORT}/api/v1/health" "ingestion-service"

# ── Step 5: Start query-service ───────────────────────────────────────────────
info "Step 5 — Starting query-service (port $QUERY_PORT)"
cd "$QUERY_DIR"
env \
    DATABASE_URL="$DB_URL" \
    OLLAMA_BASE_URL="$STUB_URL" \
    OPENAI_API_KEY="stub-key" \
    EMBEDDING_MODEL="stub-embedding" \
    LLM_MODEL="stub-llm" \
    uvicorn main:app --host 0.0.0.0 --port "$QUERY_PORT" \
        --log-level warning > /tmp/query-e2e.log 2>&1 &
PIDS+=("$!")
wait_for_http "http://localhost:${QUERY_PORT}/api/v1/health" "query-service"

# ── Step 6: Ingest test documents ────────────────────────────────────────────
info "Step 6 — Ingesting test documents via /api/v1/ingest/document"

ingest() {
    local label="$1" payload="$2"
    local resp
    resp=$(curl -sf -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/document" \
        -H "Content-Type: application/json" \
        -H "X-Admin-Key: $ADMIN_KEY" \
        -d "$payload")
    local doc_id chunks classification
    doc_id=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['document_id'])")
    chunks=$(echo  "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['chunks_created'])")
    classification=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['classification'])")
    ok "$label → doc_id=${doc_id:0:8}… chunks=$chunks classification=$classification"
}

ingest "Jira ticket: PAY-42" '{
    "title": "PAY-42: Payment gateway fails with 3DS2 on Visa cards",
    "content": "When a customer attempts to pay using a Visa card with 3DS2 authentication enabled, the payment gateway returns a 400 error. The issue occurs in the checkout flow after the bank redirect. Logs show the authentication callback URL is malformed. Root cause: the redirect_url is not being URL-encoded before being passed to the Stripe API. Fix: apply urllib.parse.quote() to the redirect_url parameter in PaymentGatewayService.createCharge().",
    "source_type": "jira",
    "source_id": "PAY-42",
    "source_url": "https://example.atlassian.net/browse/PAY-42",
    "metadata": {"project_key": "PAY", "status": "Done", "issue_type": "Bug"},
    "allowed_projects": ["PAY"]
}'

ingest "Confluence: Checkout Architecture" '{
    "title": "Checkout Service Architecture",
    "content": "The checkout service handles the complete purchase flow including cart validation, coupon application, payment processing, and order confirmation. It integrates with the Payment Gateway via REST API using API keys stored in AWS Secrets Manager. The service supports multiple payment methods: credit card, PayPal, and Apple Pay. For 3DS2 compliance, all Visa and Mastercard transactions above 30 NZD require strong customer authentication. The authentication flow uses a redirect to the card issuer bank and returns via a signed callback URL.",
    "source_type": "confluence",
    "source_id": "CONF-101",
    "source_url": "https://example.atlassian.net/wiki/spaces/PAY/pages/101",
    "metadata": {"space_key": "PAY", "author": "Jane Smith"},
    "allowed_spaces": ["PAY"]
}'

ingest "Jira ticket: TRACK-88" '{
    "title": "TRACK-88: GPS location not updating in fleet dashboard",
    "content": "Fleet managers report that vehicle GPS coordinates in the dashboard are not refreshing. Last known position timestamps are over 2 hours old for 40% of the fleet. Investigation shows the LocationEngine Kafka consumer group is lagging by 1.2 million messages. The consumer is single-threaded and cannot keep up with the volume during peak hours. Solution: increase consumer group partition count from 3 to 12 and enable parallel processing using virtual threads.",
    "source_type": "jira",
    "source_id": "TRACK-88",
    "source_url": "https://example.atlassian.net/browse/TRACK-88",
    "metadata": {"project_key": "TRACK", "status": "In Progress", "issue_type": "Bug"},
    "allowed_projects": ["TRACK"]
}'

ingest "Confluence: GPS Data Pipeline" '{
    "title": "GPS Data Pipeline Design",
    "content": "The GPS data pipeline ingests real-time location updates from vehicle telematics devices. Each device publishes a location event every 30 seconds via MQTT. The MQTT broker forwards events to Apache Kafka topic vehicle.location.raw. The LocationEngine service consumes this topic, validates coordinates, applies geofence rules, and stores the processed location in Redis for real-time queries and PostgreSQL for historical analytics. The pipeline processes approximately 500,000 events per hour across the fleet.",
    "source_type": "confluence",
    "source_id": "CONF-202",
    "source_url": "https://example.atlassian.net/wiki/spaces/TRACK/pages/202",
    "metadata": {"space_key": "TRACK", "author": "Bob Jones"},
    "allowed_spaces": ["TRACK"]
}'

ingest "Confluence: Platform Auth Guide" '{
    "title": "Authentication and API Keys",
    "content": "All internal services authenticate using JWT tokens issued by the Auth Service. External API clients use API keys managed via the Developer Portal. API keys are stored encrypted in AWS Secrets Manager and rotated every 90 days. Service-to-service calls use mutual TLS with certificates issued by the internal CA. The Payment Gateway uses dedicated API keys that are separate from general platform keys and must be requested through the Security team.",
    "source_type": "confluence",
    "source_id": "CONF-303",
    "source_url": "https://example.atlassian.net/wiki/spaces/PLAT/pages/303",
    "metadata": {"space_key": "PLAT", "author": "Security Team"},
    "allowed_spaces": ["PLAT"]
}'

echo ""
info "Step 7 — Querying the knowledge base"

run_query() {
    local label="$1" query="$2"
    echo ""
    echo "  Query: \"$query\""
    local resp
    resp=$(curl -sf -X POST "http://localhost:${QUERY_PORT}/api/v1/query" \
        -H "Content-Type: application/json" \
        -d "{\"query\": \"$query\", \"top_k\": 3}")

    local answer sources chunks model
    answer=$(echo  "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['answer'][:200])")
    sources=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d['sources']))")
    chunks=$(echo  "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['chunks_retrieved'])")
    model=$(echo   "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['model_used'])")
    src_list=$(echo "$resp" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for s in d['sources']:
    print(f\"    [{s['source_type']}] {s['source_id']} — {s['title'][:60]}\")
")

    ok "$label"
    echo "    Answer (first 200 chars): $answer"
    echo "    Sources returned: $sources  |  Chunks retrieved: $chunks  |  Model: $model"
    echo "$src_list"

    # Assertions
    if [ "$chunks" -lt 1 ]; then
        fail "$label: expected at least 1 chunk retrieved, got $chunks"
    fi
    if [ "$sources" -lt 1 ]; then
        fail "$label: expected at least 1 source, got $sources"
    fi
    if [ -z "$answer" ]; then
        fail "$label: answer was empty"
    fi
}

run_query "Q1: 3DS2 payment issue" \
    "Why does the payment gateway fail with 3DS2 on Visa cards?"

run_query "Q2: GPS not updating" \
    "Why is GPS location not updating in the fleet dashboard?"

run_query "Q3: Checkout authentication" \
    "How does the checkout service handle authentication for payments?"

run_query "Q4: API key management" \
    "How are API keys managed and rotated in the platform?"

# ── Step 8: Verify ingest status ──────────────────────────────────────────────
echo ""
info "Step 8 — Checking ingest /status endpoint"
STATUS=$(curl -sf "http://localhost:${INGESTION_PORT}/api/v1/ingest/status" \
    -H "X-Admin-Key: $ADMIN_KEY")
echo "  Sync states: $(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d)")"
ok "Status endpoint reachable"

# ── Step 9: Verify admin auth is enforced ─────────────────────────────────────
echo ""
info "Step 9 — Verify admin endpoint rejects bad key"
BAD_RESP=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/sync/full" \
    -H "X-Admin-Key: wrong-key")
if [ "$BAD_RESP" = "401" ]; then
    ok "Admin endpoint correctly rejected wrong key (HTTP 401)"
else
    fail "Expected HTTP 401 for bad admin key, got $BAD_RESP"
fi

NO_KEY_RESP=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "http://localhost:${INGESTION_PORT}/api/v1/ingest/sync/full")
if [ "$NO_KEY_RESP" = "401" ]; then
    ok "Admin endpoint correctly rejected missing key (HTTP 401)"
else
    fail "Expected HTTP 401 for missing admin key, got $NO_KEY_RESP"
fi

# ── All tests passed ──────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ALL E2E TESTS PASSED ✓${NC}"
echo -e "${GREEN}  5 documents ingested  |  4 queries answered  |  auth enforced${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════${NC}"
echo ""
echo "  Logs:"
echo "    ingestion-service: /tmp/ingestion-e2e.log"
echo "    query-service:     /tmp/query-e2e.log"

