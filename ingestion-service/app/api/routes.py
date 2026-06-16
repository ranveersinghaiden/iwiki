"""Ingestion service API routes — all endpoints require X-Admin-Key header."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from app.config import settings
from app.db.database import AsyncSessionFactory
from app.db import repository
from app.db.repository import ChunkRecord
from app.pipeline.cleaner import clean_text
from app.pipeline.chunker import TextChunker
from app.pipeline.classifier import HierarchyClassifier
from app.pipeline.embedder import Embedder
from app.pipeline.expert_refresher import ProductExpertRefresher
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


# ── Request model for direct document ingestion ───────────────────────────────

class IngestDocumentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=1000)
    content: str = Field(..., min_length=1)
    source_type: str = Field(default="manual", pattern="^[a-z_]+$")
    source_id: str = Field(..., min_length=1, max_length=500)
    source_url: str | None = None
    metadata: dict = Field(default_factory=dict)
    allowed_spaces: list[str] = Field(default_factory=list)
    allowed_projects: list[str] = Field(default_factory=list)


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


# ── Product expert endpoints ──────────────────────────────────────────────────

@router.post("/experts/refresh", status_code=202, dependencies=[Depends(_require_admin)])
async def trigger_expert_refresh(background_tasks: BackgroundTasks) -> dict:
    """Manually trigger a refresh of all product expert records."""
    background_tasks.add_task(_run_expert_refresh)
    logger.info("[routes] expert refresh triggered")
    return {"status": "accepted", "triggered_at": datetime.now(timezone.utc).isoformat()}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── Background tasks ──────────────────────────────────────────────────────────

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


async def _run_expert_refresh() -> None:
    try:
        refresher = ProductExpertRefresher()
        results = await refresher.refresh_all()
        logger.info("[routes] expert refresh done experts=%d", len(results))
    except Exception as exc:
        logger.error("[routes] expert refresh failed: %s", exc, exc_info=exc)


# ── Direct document ingestion (testing + manual indexing) ─────────────────────

@router.post("/ingest/document", status_code=201, dependencies=[Depends(_require_admin)])
async def ingest_single_document(req: IngestDocumentRequest) -> dict:
    """
    Index a single raw document directly through the full pipeline.
    Useful for testing and for indexing documents not in Jira/Confluence.
    The content field should be plain text (not HTML).
    """
    chunker = TextChunker()
    embedder = Embedder()
    classifier = HierarchyClassifier()

    cleaned = clean_text(req.content)
    chunks = chunker.chunk(cleaned)
    if not chunks:
        raise HTTPException(status_code=422, detail="Document produced no chunks after cleaning")

    texts = [c.content for c in chunks]
    embeddings = await embedder.embed_batch(texts)
    classification = await classifier.classify(req.title, cleaned[:600])

    chunk_records = [
        ChunkRecord(
            chunk_index=c.chunk_index,
            content=c.content,
            embedding=embeddings[i],
            token_count=c.token_count,
            metadata={"source": req.source_type, "source_id": req.source_id},
        )
        for i, c in enumerate(chunks)
    ]

    async with AsyncSessionFactory() as session:
        doc_id = await repository.upsert_document_with_chunks(
            session,
            source_type=req.source_type,
            source_id=req.source_id,
            source_url=req.source_url,
            title=req.title,
            raw_content=req.content,
            cleaned_content=cleaned,
            doc_metadata=req.metadata,
            allowed_spaces=req.allowed_spaces,
            allowed_projects=req.allowed_projects,
            product_hierarchy=classification,
            source_updated_at=datetime.now(timezone.utc),
            chunks=chunk_records,
        )

    logger.info(
        "[routes] document indexed source_id=%s chunks=%d classification=%s",
        req.source_id, len(chunks), classification,
    )
    return {
        "document_id": str(doc_id),
        "source_id": req.source_id,
        "chunks_created": len(chunks),
        "classification": classification,
    }

