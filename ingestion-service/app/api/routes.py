"""Ingestion service API routes — all endpoints require X-Admin-Key header."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings
from app.db.database import AsyncSessionFactory
from app.db import repository
from app.pipeline.ingestion_pipeline import IngestionPipeline

logger = logging.getLogger(__name__)

router = APIRouter()

_ADMIN_KEY_HEADER = APIKeyHeader(name="X-Admin-Key", auto_error=False)


async def _require_admin(api_key: str | None = Security(_ADMIN_KEY_HEADER)) -> None:
    """Dependency — reject request if admin key is missing or wrong."""
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin key not configured on server")
    if api_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key header")


# ── Sync trigger endpoints ────────────────────────────────────────────────────

@router.post("/ingest/sync/full", status_code=202, dependencies=[Depends(_require_admin)])
async def trigger_full_sync(background_tasks: BackgroundTasks) -> dict:
    """Trigger a full re-index of all configured Jira projects and Confluence spaces."""
    background_tasks.add_task(_run_sync, full_sync=True)
    logger.info("[routes] full sync triggered")
    return {"status": "accepted", "sync_type": "full", "triggered_at": datetime.now(timezone.utc).isoformat()}


@router.post("/ingest/sync/incremental", status_code=202, dependencies=[Depends(_require_admin)])
async def trigger_incremental_sync(background_tasks: BackgroundTasks) -> dict:
    """Trigger an incremental sync — only items updated since last sync watermark."""
    background_tasks.add_task(_run_sync, full_sync=False)
    logger.info("[routes] incremental sync triggered")
    return {"status": "accepted", "sync_type": "incremental", "triggered_at": datetime.now(timezone.utc).isoformat()}


# ── Status endpoint ───────────────────────────────────────────────────────────

@router.get("/ingest/status", dependencies=[Depends(_require_admin)])
async def sync_status() -> dict:
    """Return current sync state for all sources."""
    async with AsyncSessionFactory() as session:
        states = await repository.get_sync_states(session)
    return {"sync_states": states}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── Background task ───────────────────────────────────────────────────────────

async def _run_sync(full_sync: bool) -> None:
    try:
        pipeline = IngestionPipeline.build()
        results = await pipeline.run(full_sync=full_sync)
        for r in results:
            logger.info(
                "[routes] sync finished source=%s processed=%d failed=%d",
                r.source_type,
                r.items_processed,
                r.items_failed,
            )
    except Exception as exc:
        logger.error("[routes] sync failed: %s", exc, exc_info=exc)

