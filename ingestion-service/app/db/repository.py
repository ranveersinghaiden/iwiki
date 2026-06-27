"""
Repository — all DB writes for the ingestion pipeline.
Chunks are stored via raw SQL to avoid needing the pgvector SQLAlchemy extension;
embeddings are passed as text strings that PostgreSQL casts to halfvec automatically.
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

from app.db.models import Document, ProductExpert, SyncState

logger = logging.getLogger(__name__)

_CHUNK_UPSERT = text("""
    INSERT INTO chunks (id, document_id, chunk_index, content, embedding, token_count, metadata)
    VALUES (
        gen_random_uuid(),
        :document_id,
        :chunk_index,
        :content,
        CAST(:embedding AS halfvec),
        :token_count,
        CAST(:metadata AS jsonb)
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

_GET_DOCUMENTS_BY_PRODUCT = text("""
    SELECT id, title, cleaned_content, product_hierarchy
    FROM documents
    WHERE product_hierarchy->>'product' = :product
    ORDER BY source_updated_at DESC NULLS LAST
    LIMIT :limit
""")

_DELETE_PRODUCT_EXPERT = text("""
    DELETE FROM product_experts
    WHERE product = :product
      AND ((CAST(:component AS text) IS NULL AND component IS NULL)
           OR component = CAST(:component AS text))
""")

_INSERT_PRODUCT_EXPERT = text("""
    INSERT INTO product_experts
        (product, component, description, compressed_context,
         upstream_dependencies, downstream_affected, source_document_count,
         generated_at, updated_at)
    VALUES
        (:product, :component, :description, :compressed_context,
         CAST(:upstream_dependencies AS jsonb), CAST(:downstream_affected AS jsonb),
         :source_document_count, NOW(), NOW())
""")

_GET_ALL_PRODUCT_EXPERTS = text("""
    SELECT id, product, component, description, compressed_context,
           upstream_dependencies, downstream_affected, source_document_count,
           generated_at, updated_at
    FROM product_experts
    ORDER BY product, component NULLS FIRST
""")

_GET_PRODUCT_EXPERT = text("""
    SELECT id, product, component, description, compressed_context,
           upstream_dependencies, downstream_affected, source_document_count,
           generated_at, updated_at
    FROM product_experts
    WHERE product = :product
      AND ((CAST(:component AS text) IS NULL AND component IS NULL)
           OR component = CAST(:component AS text))
    LIMIT 1
""")

_GET_DISTINCT_PRODUCTS = text("""
    SELECT DISTINCT product_hierarchy->>'product' AS product
    FROM documents
    WHERE product_hierarchy->>'product' IS NOT NULL
      AND product_hierarchy->>'product' != 'General'
""")

_GET_CONTENT_HASH = text("""
    SELECT content_hash FROM documents
    WHERE source_type = :source_type AND source_id = :source_id
""")

_LIST_SOURCE_IDS = text("""
    SELECT source_id FROM documents WHERE source_type = :source_type
""")


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
    content_hash: str | None = None,
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
            content_hash=content_hash,
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
                "content_hash": content_hash,
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


async def get_document_content_hash(
    session: AsyncSession, source_type: str, source_id: str
) -> str | None:
    """Return the stored content_hash for a document, or None if absent/unknown."""
    result = await session.execute(
        _GET_CONTENT_HASH, {"source_type": source_type, "source_id": source_id}
    )
    row = result.fetchone()
    return row[0] if row else None


async def list_source_ids(session: AsyncSession, source_type: str) -> set[str]:
    """Return the set of all source_ids currently indexed for a source type."""
    result = await session.execute(_LIST_SOURCE_IDS, {"source_type": source_type})
    return {row[0] for row in result.fetchall()}


async def delete_documents_by_source_ids(
    session: AsyncSession, source_type: str, source_ids: list[str]
) -> int:
    """Delete documents (chunks cascade) for the given source_ids. Returns count."""
    if not source_ids:
        return 0
    result = await session.execute(
        text(
            "DELETE FROM documents "
            "WHERE source_type = :source_type AND source_id = ANY(:source_ids)"
        ),
        {"source_type": source_type, "source_ids": list(source_ids)},
    )
    await session.commit()
    return result.rowcount or 0


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


async def get_documents_by_product(
    session: AsyncSession, product: str, limit: int = 50
) -> list[dict[str, Any]]:
    """Return cleaned_content + metadata for all documents in a given product."""
    result = await session.execute(
        _GET_DOCUMENTS_BY_PRODUCT,
        {"product": product, "limit": limit},
    )
    return [dict(row._mapping) for row in result.fetchall()]


async def get_distinct_products(session: AsyncSession) -> list[str]:
    """Return all distinct product names present in indexed documents."""
    result = await session.execute(_GET_DISTINCT_PRODUCTS)
    return [row[0] for row in result.fetchall() if row[0]]


async def upsert_product_expert(
    session: AsyncSession,
    *,
    product: str,
    component: str | None,
    description: str,
    compressed_context: str,
    upstream_dependencies: list[dict[str, Any]],
    downstream_affected: list[dict[str, Any]],
    source_document_count: int,
) -> None:
    """Delete-then-insert a product expert record (safe upsert for partial-index constraint)."""
    params: dict[str, Any] = {
        "product": product,
        "component": component,
        "description": description,
        "compressed_context": compressed_context,
        "upstream_dependencies": json.dumps(upstream_dependencies),
        "downstream_affected": json.dumps(downstream_affected),
        "source_document_count": source_document_count,
    }
    await session.execute(_DELETE_PRODUCT_EXPERT, {"product": product, "component": component})
    await session.execute(_INSERT_PRODUCT_EXPERT, params)
    await session.commit()
    logger.debug("[Repository] upserted expert product=%s component=%s", product, component)


async def get_all_product_experts(session: AsyncSession) -> list[dict[str, Any]]:
    result = await session.execute(_GET_ALL_PRODUCT_EXPERTS)
    return [dict(row._mapping) for row in result.fetchall()]


async def get_product_expert(
    session: AsyncSession, product: str, component: str | None = None
) -> dict[str, Any] | None:
    result = await session.execute(
        _GET_PRODUCT_EXPERT, {"product": product, "component": component}
    )
    row = result.fetchone()
    return dict(row._mapping) if row else None

