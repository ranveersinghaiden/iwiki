# PostgreSQL Access & Local Development

Complete guide to accessing + managing Postgres for iWiki (local development and production).

---

## Quick Reference

| Scenario | Command | Port | Notes |
|----------|---------|------|-------|
| Docker Compose (all services) | `docker compose up -d` | 5432 | Easiest start |
| Docker Compose (Postgres only) | `docker compose up -d db` | 5432 | Isolated DB for local dev |
| Standalone Docker (local dev) | `docker run ... pgvector/pgvector:pg16` | 5432 | Manual container |
| psql CLI in container | `docker compose exec db psql -U iwiki -d iwiki` | — | Direct SQL access |
| psql CLI from host | `psql postgresql://iwiki:iwiki@localhost:5432/iwiki` | 5432 | Requires `psql` installed |
| DBeaver / DataGrip | `localhost:5432, user: iwiki, password: [from .env]` | 5432 | GUI tools |
| Python connection | `psycopg[asyncio]://iwiki:iwiki@localhost:5432/iwiki` | 5432 | See "Python Example" below |

---

## Setup Scenarios

### Scenario A: Everything via Docker Compose (Easiest)

All services + database in one command:

```bash
# 1. Configure secrets
cp .env.example .env
# Edit .env with credentials

# 2. Start all services (db, ingestion, query)
docker compose up -d

# 3. Verify Postgres is ready
docker compose logs db | grep "database system is ready"

# 4. Connect via psql (inside container)
docker compose exec db psql -U iwiki -d iwiki

# 5. Or connect from host via TCP
psql postgresql://iwiki:iwiki@localhost:5432/iwiki
```

**Pros:** 
- Single command
- Networking automatic
- Data persists in named volume `pgdata`

**Cons:**
- Services restart if code changes (use `--reload` in development)
- Less control over individual service lifecycle

---

### Scenario B: Postgres-Only via Docker Compose (Local Dev)

Run only DB in Docker, services locally:

```bash
# 1. Start Postgres only
docker compose up -d db

# 2. Wait for health check
until docker compose exec db pg_isready -U iwiki -d iwiki; do
  echo "Waiting for DB..."
  sleep 2
done
echo "DB ready!"

# 3. Set up ingestion-service
cd ingestion-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 4. Set up query-service
cd ../query-service
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 5. Connect to DB from host
psql postgresql://iwiki:iwiki@localhost:5432/iwiki
```

**Environment variables for local services:**

```bash
# .env (same file, both docker-compose and local scripts read it)
POSTGRES_USER=iwiki
POSTGRES_PASSWORD=iwiki
POSTGRES_DB=iwiki
DATABASE_URL=postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki
# ... other secrets
```

**Pros:**
- Hot reload on code changes
- Faster iteration
- DB isolated in Docker for easy reset

**Cons:**
- Requires Python local installation
- More setup steps

---

### Scenario C: Standalone Postgres Docker (Minimal)

Raw Docker run (no compose):

```bash
# 1. Create volume for persistence
docker volume create iwiki-pgdata

# 2. Run container
docker run -d \
  --name iwiki-postgres \
  --restart unless-stopped \
  -e POSTGRES_USER=iwiki \
  -e POSTGRES_PASSWORD=iwiki \
  -e POSTGRES_DB=iwiki \
  -p 5432:5432 \
  -v iwiki-pgdata:/var/lib/postgresql/data \
  -v "$(pwd)/db/init.sql:/docker-entrypoint-initdb.d/init.sql:ro" \
  pgvector/pgvector:pg16

# 3. Wait for startup
sleep 5

# 4. Connect via psql from host
psql postgresql://iwiki:iwiki@localhost:5432/iwiki

# 5. Clean up (preserve data)
docker stop iwiki-postgres

# 6. Resume later
docker start iwiki-postgres

# 7. Remove everything (wipe data)
docker rm -v iwiki-postgres
docker volume rm iwiki-pgdata
```

**Pros:**
- Total control
- No docker-compose config needed
- Easy to integrate into CI/CD

**Cons:**
- Manual networking (services must use `localhost:5432` inside same Docker network)
- More verbose

---

## Connection Methods

### Method 1: psql CLI in Container

Interactive SQL shell:

```bash
# Via docker-compose
docker compose exec db psql -U iwiki -d iwiki

# Via standalone container
docker exec -it iwiki-postgres psql -U iwiki -d iwiki
```

Once connected:

```sql
-- List all tables
\dt

-- Describe chunks table
\d chunks

-- Count rows
SELECT COUNT(*) FROM chunks;

-- Exit
\q
```

### Method 2: psql CLI from Host

Requires `psql` binary installed locally:

```bash
# macOS (via Homebrew)
brew install postgresql@16

# Ubuntu/Debian
sudo apt-get install postgresql-client-16

# After install, connect
psql postgresql://iwiki:iwiki@localhost:5432/iwiki
```

**Connection string breakdown:**
```
postgresql://[user]:[password]@[host]:[port]/[database]
             iwiki  : iwiki     @ localhost : 5432    / iwiki
```

---

### Method 3: GUI Database Tools

#### DBeaver (Free, recommended for exploration)

1. Download: https://dbeaver.io/download/
2. Create connection:
   - Database type: PostgreSQL
   - Host: `localhost`
   - Port: `5432`
   - user: `iwiki`
   - password: `iwiki` (from .env)
   - Database: `iwiki`
3. Click "Test Connection" → OK
4. Explore tables, run SQL queries, export data

#### DataGrip (JetBrains, paid, integrates with IntelliJ)

1. File → New → Database
2. Select PostgreSQL
3. Fill connection details (same as above)
4. Click "Test Connection" → OK
5. Full IDE debugging + profiling

#### VS Code (free, SQL extension)

Install extension: `cweijan.vscode-postgresql-client`

1. Open Command Palette: Cmd+Shift+P
2. Type: "PostgreSQL: Add Connection"
3. Fill details (same as above)
4. SQL files now auto-complete + run with Cmd+Enter

---

### Method 4: Python Script

Connect programmatically:

```python
# requirements.txt
psycopg[asyncio]==3.2
sqlalchemy==2.0

# script.py
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    engine = create_async_engine(
        "postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki"
    )
    
    async with engine.begin() as conn:
        # Example query
        result = await conn.execute(text("SELECT COUNT(*) FROM chunks"))
        count = result.scalar()
        print(f"Total chunks: {count}")
    
    await engine.dispose()

asyncio.run(main())
```

Run:

```bash
cd /path/to/iwiki
python -m venv .venv && source .venv/bin/activate
pip install psycopg[asyncio] sqlalchemy
python script.py
```

---

### Method 5: Docker Compose Service

Run a temporary query container:

```bash
# Execute SQL and exit
docker compose run --rm db psql -U iwiki -d iwiki -c "SELECT COUNT(*) FROM chunks;"

# Or multiple commands
docker compose run --rm db psql -U iwiki -d iwiki << EOF
  SELECT COUNT(*) FROM chunks;
  SELECT product, COUNT(*) FROM chunks GROUP BY product;
  \q
EOF
```

---

## Common SQL Queries

### 1. Database Health

```sql
-- Connection info
SELECT version();
-- PostgreSQL 16.4 (pgvector 0.8.0)

-- Extension status
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
-- vector | 0.8.0

-- Database size
SELECT pg_size_pretty(pg_database_size('iwiki'));
```

### 2. Chunks Overview

```sql
-- Total chunks
SELECT COUNT(*) as total_chunks FROM chunks;

-- Chunks by source type
SELECT source_type, COUNT(*) 
FROM chunks 
GROUP BY source_type;

-- Chunks by product/feature
SELECT product, feature, COUNT() 
FROM chunks 
GROUP BY product, feature 
ORDER BY COUNT(*) DESC;

-- Recent chunks (last 1 hour)
SELECT source_id, title, created_at 
FROM chunks 
WHERE created_at > NOW() - INTERVAL '1 hour'
LIMIT 10;

-- Duplicate detection (same source_id with multiple versions)
SELECT source_id, COUNT(*) as versions
FROM chunks
GROUP BY source_id
HAVING COUNT(*) > 1;
```

### 3. Vector Index Health

```sql
-- Vector dimension (should match EMBEDDING_DIM from .env)
SELECT dimensions(embedding) as dim
FROM chunks LIMIT 1;

-- Index statistics (ivfflat performance)
SELECT 
  schemaname, tablename, indexname, idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE indexname = 'idx_chunks_embedding';

-- Reindex if necessary (repairs fragmented index)
REINDEX INDEX idx_chunks_embedding;
```

### 4. Full-Text Search Index (BM25)

```sql
-- Verify GIN index exists
SELECT 
  schemaname, tablename, indexname
FROM pg_stat_user_indexes
WHERE tablename = 'chunks' AND indexname LIKE '%fts%';

-- Test BM25 query
SELECT id, source_id, ts_rank(to_tsvector('english', chunk_text), query_tsquery) as score
FROM chunks, 
     plainto_tsquery('english', 'payment gateway') as query_tsquery('query')
WHERE to_tsvector('english', chunk_text) @@ query_tsquery
LIMIT 10;
```

### 5. Sync Metadata

```sql
-- Last sync time per source
SELECT source_type, last_sync_time, chunk_count, sync_duration_ms
FROM ingestion_metadata
ORDER BY last_sync_time DESC;

-- Items synced per hour (trending)
SELECT 
  DATE_TRUNC('hour', created_at) as hour,
  COUNT(*) as chunks_ingested
FROM chunks
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;
```

### 6. Search Quality

```sql
-- Sample hybrid search results (vector + BM25)
WITH query_vec AS (
  -- Simulate embedding of "payment 3DS" (replace with real vector)
  SELECT '[0.1, 0.2, ...]'::vector as vec
)
SELECT 
  id, source_id, 
  1 - (embedding <=> query_vec.vec) as cosine_score,
  ts_rank(to_tsvector('english', chunk_text), 'payment | 3DS'::tsquery) as bm25_score
FROM chunks, query_vec
ORDER BY cosine_score DESC
LIMIT 10;
```

---

## Maintenance

### Backup & Restore

#### Full Backup (Postgres dump)

```bash
# Backup to SQL file
docker compose exec db pg_dump -U iwiki -d iwiki --no-password > backup.sql

# View size
ls -lh backup.sql  # e.g., 250MB

# Restore from file
docker compose exec -T db psql -U iwiki -d iwiki < backup.sql
```

#### Backup with Vectors (binary format, faster)

```bash
# Binary backup (includes vector data efficiently)
docker compose exec db pg_dump -U iwiki -d iwiki --format=custom > backup.dump

# Restore
docker compose exec -T db pg_restore -U iwiki -d iwiki -1 backup.dump
```

#### Backup Docker Volume (entire DB + config)

```bash
# Create tarball of volume
docker run --rm -v iwiki_pgdata:/data -v "$(pwd)":/backup ubuntu:latest tar cf /backup/pgdata.tar -C /data .

# Restore to new volume
docker volume create iwiki-pgdata-restored
docker run --rm -v iwiki-pgdata-restored:/data -v "$(pwd)":/backup ubuntu:latest tar xf /backup/pgdata.tar -C /data
```

### Performance Tuning

#### 1. Increase Connection Pool

For multiple ingestion jobs:

```bash
# Edit docker-compose.yml or .env
POSTGRES_MAX_CONNECTIONS=100  # default 20

# Or via SQL (requires superuser restart)
ALTER SYSTEM SET max_connections = 100;
docker compose restart db
```

#### 2. Tune pgvector Index (ivfflat)

Faster search (less accurate):

```sql
-- Current index
DROP INDEX idx_chunks_embedding;

-- Recreate with aggressive settings
CREATE INDEX idx_chunks_embedding ON chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);  -- reduce from 100 for speed

-- Rebuild after many updates
REINDEX INDEX idx_chunks_embedding;
```

Cost-benefit:
- `lists = 50`: Faster (~5ms) but less accurate
- `lists = 100`: Balanced (8ms, good accuracy)
- `lists = 200`: Slower (~15ms) but highest precision

#### 3. Increase Shared Buffers (for large queries)

```bash
# docker-compose.yml: add environment block to db service
environment:
  POSTGRES_INIT_ARGS: "-c shared_buffers=512MB -c effective_cache_size=2GB"

# Restart required
docker compose restart db
```

#### 4. Monitor Query Performance

```sql
-- Enable query logging
ALTER DATABASE iwiki SET log_min_duration_statement = 1000;  -- log queries >1s

-- View slow queries in logs
docker compose logs db | grep "duration: [0-9]{4,}"

-- Kill slow query (by PID)
SELECT pid, query, query_start FROM pg_stat_activity WHERE query ~ 'SELECT';
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid = 12345;
```

---

## Troubleshooting

### Issue: "psql: could not connect to server"

**Cause:** Postgres not running or wrong port.

```bash
# Check if running
docker compose logs db | tail -20

# Check port
netstat -an | grep 5432  # or: lsof -i :5432

# Restart
docker compose restart db

# Wait for health check
until docker compose exec db pg_isready -U iwiki; do sleep 1; done
```

### Issue: "password authentication failed"

**Cause:** Wrong password or .env not loaded.

```bash
# Verify .env value matches docker-compose
echo $POSTGRES_PASSWORD

# Check if password was changed
docker compose config | grep POSTGRES_PASSWORD

# Reset container (wipes data!)
docker compose down -v
docker compose up -d db
```

### Issue: "pgvector extension not found"

**Cause:** Wrong Docker image (must use `pgvector/pgvector`).

```bash
# Check image in docker-compose.yml
grep image docker-compose.yml  # must be pgvector/pgvector:pg16

# Recreate with correct image
docker compose down
docker compose up -d db
```

### Issue: "disk space full"

**Cause:** Data volume filled (vectors are large).

```bash
# Check volume size
docker volume inspect iwiki_pgdata | grep Mountpoint
du -sh /var/lib/docker/volumes/iwiki_pgdata/_data

# Delete old chunks (if safe)
docker compose exec db psql -U iwiki -d iwiki -c \
  "DELETE FROM chunks WHERE created_at < NOW() - INTERVAL '30 days'; VACUUM FULL;"

# Or expand volume (requires recreation)
docker compose down -v
# Recreate with larger disk
```

---

## Local Dev Workflow

Complete step-by-step for Mac/Linux:

```bash
# 1. Clone repo + enter directory
git clone https://github.com/company/iwiki.git && cd iwiki

# 2. Create .env from template
cp .env.example .env

# 3. Edit .env (fill in secrets)
# Important: POSTGRES_PASSWORD, JIRA_API_TOKEN, OPENAI_API_KEY, etc.
nano .env

# 4. Start only Postgres (in Docker)
docker compose up -d db

# 5. Wait for DB
until docker compose exec db pg_isready -U iwiki -d iwiki > /dev/null 2>&1; do echo "Waiting..."; sleep 2; done

# 6. Verify connection from host
psql postgresql://iwiki:iwiki@localhost:5432/iwiki -c "SELECT COUNT(*) FROM chunks;"

# 7. Set up ingestion-service
cd ingestion-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 8. Set up query-service (separate terminal)
cd query-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 9. Run ingestion (Terminal 2)
cd ingestion-service
source .venv/bin/activate
uvicorn main:app --port 8090 --reload

# 10. Run query (Terminal 3)
cd query-service
source .venv/bin/activate
uvicorn main:app --port 8091 --reload

# 11. Run tests
docker compose exec db psql -U iwiki -d iwiki -c "SELECT COUNT(*) FROM chunks;"

# 12. Manual query test
curl http://localhost:8091/api/v1/health
curl -X POST http://localhost:8091/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "test"}'
```

---

## Connection Strings Reference

### PostgreSQL URI Formats

**Standard (from Python/Node):**
```
postgresql://iwiki:iwiki@localhost:5432/iwiki
postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki  # async (Python)
```

**From Docker (services inside compose):**
```
postgresql://iwiki:iwiki@db:5432/iwiki  # container DNS name
```

**Connection Parameters (advanced):**
```
postgresql://iwiki:iwiki@localhost:5432/iwiki?sslmode=disable&connect_timeout=5
```

---


