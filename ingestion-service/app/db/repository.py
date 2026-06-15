"""
Repository — all DB writes for the ingestion pipeline.
Chunks are stored via raw SQL to avoid needing the pgvector SQLAlchemy extension;
embeddings are passed as text strings that PostgreSQL casts to vector automatically.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, SyncState

logger = logging.getLogger(__name__)

_CHUNK_UPSERT = text("""
    INSERT INTO chunks (id, document_id, chunk_index, content, embedding, token_count, metadata)
    VALUES (
        gen_random_uuid(),
        :document_id,
        :chunk_index,
        :content,
        :embedding::vector,
        :token_count,
        :metadata::jsonb
    )
    ON CONFLICT (document_id, chunk_index) DO UPDATE
        SET content     = EXCLUDED.content,
            embedding   = EXCLUDED.embedding,
            token_count = EXCLUDED.token_count,
            metadata    = EXCLUDED.metadata
""")

_DELETE_CHUNKS = text("DELETE FROM chunks WHERE document_id = :document_id")

_UPSERT_SYNC_STATE = text("""
    INSERT INTO sync_state (source_type, last_synced_at, total_items_indexed, last_run_status)
    VALUES (:source_type, :last_synced_at, :total_items_indexed, :last_run_status)
    ON CONFLICT (source_type) DO UPDATE
        SET last_synced_at      = EXCLUDED.last_synced_at,
            total_items_indexed = EXCLUDED.total_items_indexed,
            last_run_status     = EXCLUDED.last_run_status
""")

_GET_WATERMARK = text(
    "SELECT last_synced_at FROM sync_state WHERE source_type = :source_type"
)


@dataclass
class ChunkRecord:
    chunk_index: int
    content: str
    embedding: list[float]
    token_count: int
    metadata: dict[str, Any]


async def upsert_document_with_chunks(
    session: AsyncSession,
    *,
    source_type: str,
    source_id: str,
    source_url: str | None,
    title: str | None,
    raw_content: str | None,
    cleaned_content: str | None,
    doc_metadata: dict[str, Any],
    allowed_spaces: list[str],
    allowed_projects: list[str],
    product_hierarchy: dict[str, Any],
    source_updated_at: datetime | None,
    chunks: list[ChunkRecord],
) -> uuid.UUID:
    """Upsert a document and replace all its chunks atomically."""
    stmt = (
        pg_insert(Document)
        .values(
            source_type=source_type,
            source_id=source_id,
            source_url=source_url,
            title=title,
            raw_content=raw_content,
            cleaned_content=cleaned_content,
            metadata_=doc_metadata,
            allowed_spaces=allowed_spaces,
            allowed_projects=allowed_projects,
            product_hierarchy=product_hierarchy,
            source_updated_at=source_updated_at,
        )
        .on_conflict_do_update(
            constraint="uq_documents_source",
            set_={
                "source_url": source_url,
                "title": title,
                "raw_content": raw_content,
                "cleaned_content": cleaned_content,
                "metadata": doc_metadata,
                "allowed_spaces": allowed_spaces,
                "allowed_projects": allowed_projects,
                "product_hierarchy": product_hierarchy,
                "source_updated_at": source_updated_at,
                "indexed_at": datetime.now(timezone.utc),
            },
        )
        .returning(Document.id)
    )
    result = await session.execute(stmt)
    doc_id: uuid.UUID = result.scalar_one()

    # Replace chunks — delete old then insert fresh
    await session.execute(_DELETE_CHUNKS, {"document_id": doc_id})

    for chunk in chunks:
        vec_str = f"[{','.join(map(str, chunk.embedding))}]"
        await session.execute(
            _CHUNK_UPSERT,
            {
                "document_id": doc_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "embedding": vec_str,
                "token_count": chunk.token_count,
                "metadata": json.dumps(chunk.metadata),
            },
        )

    await session.commit()
    logger.debug("[Repository] upserted doc %s with %d chunks", doc_id, len(chunks))
    return doc_id


async def get_watermark(session: AsyncSession, source_type: str) -> datetime | None:
    result = await session.execute(_GET_WATERMARK, {"source_type": source_type})
    row = result.fetchone()
    return row[0] if row else None


async def update_sync_state(
    session: AsyncSession,
    *,
    source_type: str,
    last_synced_at: datetime,
    total_items_indexed: int,
    last_run_status: str,
) -> None:
    await session.execute(
        _UPSERT_SYNC_STATE,
        {
            "source_type": source_type,
            "last_synced_at": last_synced_at,
            "total_items_indexed": total_items_indexed,
            "last_run_status": last_run_status,
        },
    )
    await session.commit()


async def get_sync_states(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(
        text("SELECT source_type, last_synced_at, total_items_indexed, last_run_status FROM sync_state")
    )
    return [dict(row._mapping) for row in result.fetchall()]

