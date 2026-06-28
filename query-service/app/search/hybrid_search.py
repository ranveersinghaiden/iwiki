"""
Hybrid search: pgvector cosine similarity + Postgres FTS, fused with RRF.

RRF score = Σ 1/(k + rank_i)  where k=60.
Higher score → better match.

The query embedding is embedded as a SQL literal (not a bound parameter)
to avoid asyncpg prepared-statement type-inference issues with the <=> operator.
The vector contains only float literals from our own embedder — no user input.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_RRF_K = 60


@dataclass(frozen=True, slots=True)
class SearchResult:
    chunk_id: str
    content: str
    document_id: str
    rrf_score: float
    title: str
    source_url: str | None
    source_type: str
    source_id: str
    product_hierarchy: dict[str, Any]
    source_updated_at: datetime | None = None
    # Set by the reranker (blended signal score); falls back to rrf_score when unset.
    rerank_score: float | None = None


_HYBRID_SQL_TMPL = """
WITH vector_search AS (
    SELECT
        c.id                                            AS chunk_id,
        c.content,
        c.document_id,
        ROW_NUMBER() OVER (
            ORDER BY c.embedding <=> '{vec_literal}'::halfvec
        )                                               AS vector_rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE 1=1
    {where_clause}
    ORDER BY c.embedding <=> '{vec_literal}'::halfvec
    LIMIT :candidate_limit
),
fts_search AS (
    SELECT
        c.id                                            AS chunk_id,
        c.content,
        c.document_id,
        ROW_NUMBER() OVER (
            ORDER BY ts_rank_cd(c.fts_vector, plainto_tsquery('english', :query_text)) DESC
        )                                               AS fts_rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    WHERE c.fts_vector @@ plainto_tsquery('english', :query_text)
    {where_clause_fts}
    ORDER BY fts_rank
    LIMIT :candidate_limit
),
rrf_scores AS (
    SELECT
        COALESCE(v.chunk_id, f.chunk_id)                AS chunk_id,
        COALESCE(1.0 / ({k} + v.vector_rank), 0.0) +
        COALESCE(1.0 / ({k} + f.fts_rank),  0.0)       AS rrf_score
    FROM vector_search v
    FULL OUTER JOIN fts_search f ON v.chunk_id = f.chunk_id
)
SELECT
    r.chunk_id::text,
    c.content,
    c.document_id::text,
    r.rrf_score,
    d.title,
    d.source_url,
    d.source_type,
    d.source_id,
    d.product_hierarchy,
    d.source_updated_at
FROM rrf_scores r
JOIN chunks   c ON r.chunk_id   = c.id
JOIN documents d ON c.document_id = d.id
ORDER BY r.rrf_score DESC
LIMIT :top_k
"""


async def hybrid_search(
    session: AsyncSession,
    *,
    query_embedding: list[float],
    query_text: str,
    allowed_spaces: list[str] | None = None,
    allowed_projects: list[str] | None = None,
    product_filter: str | None = None,
    top_k: int | None = None,
) -> list[SearchResult]:
    """Run hybrid vector + FTS search, return RRF-ranked results."""

    where_parts: list[str] = []
    params: dict[str, Any] = {
        "query_text": query_text,
        "candidate_limit": settings.search_candidate_limit,
        "top_k": top_k or settings.top_k_results,
    }

    if allowed_spaces:
        where_parts.append("d.allowed_spaces && CAST(:allowed_spaces AS text[])")
        params["allowed_spaces"] = list(allowed_spaces)

    if allowed_projects:
        where_parts.append("d.allowed_projects && CAST(:allowed_projects AS text[])")
        params["allowed_projects"] = list(allowed_projects)

    if product_filter:
        where_parts.append("d.product_hierarchy->>'product' = :product_filter")
        params["product_filter"] = product_filter

    where_clause = ("AND " + " AND ".join(where_parts)) if where_parts else ""

    # Embed float array as a SQL literal — safe: only float digits, no user input
    vec_literal = "[" + ",".join(f"{v:.8f}" for v in query_embedding) + "]"

    sql = _HYBRID_SQL_TMPL.format(
        vec_literal=vec_literal,
        where_clause=where_clause,
        where_clause_fts=where_clause,
        k=_RRF_K,
    )

    logger.debug(
        "[hybrid_search] candidate_limit=%d filters=%d rrf_k=%d",
        settings.search_candidate_limit,
        len(where_parts),
        _RRF_K,
    )
    try:
        # Tune HNSW ef_search for quality vs speed. candidate_limit * 2 gives
        # a wider search beam than the default (40), ensuring small datasets are covered.
        await session.execute(
            text(f"SET LOCAL hnsw.ef_search = {max(40, settings.search_candidate_limit * 2)}")
        )
        result = await session.execute(text(sql), params)
        rows = result.fetchall()
    except Exception as exc:
        logger.error("[hybrid_search] SQL failed: %s", exc, exc_info=exc)
        return []

    logger.info("[hybrid_search] query=%r returned %d results", query_text[:80], len(rows))

    return [
        SearchResult(
            chunk_id=row[0],
            content=row[1],
            document_id=row[2],
            rrf_score=float(row[3]),
            title=row[4] or "",
            source_url=row[5],
            source_type=row[6],
            source_id=row[7],
            product_hierarchy=row[8] or {},
            source_updated_at=row[9],
        )
        for row in rows
    ]

