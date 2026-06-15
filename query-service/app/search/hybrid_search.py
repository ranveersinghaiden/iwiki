"""
Hybrid search: pgvector cosine similarity + Postgres FTS, fused with RRF.

RRF score = Σ 1/(k + rank_i)  where k=60 (standard constant).
Higher score → better match.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_RRF_K = 60

# ── Search result ──────────────────────────────────────────────────────────────

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


# ── SQL query ─────────────────────────────────────────────────────────────────
# Uses CTEs to run vector + FTS searches independently then fuse with RRF.
# Permissions: allowed_spaces / allowed_projects / product_filter are applied
# in both legs before fusion to avoid surfacing forbidden chunks post-rank.

_HYBRID_SQL = """
WITH vector_search AS (
    SELECT
        c.id                                            AS chunk_id,
        c.content,
        c.document_id,
        ROW_NUMBER() OVER (
            ORDER BY c.embedding <=> :query_vec::vector
        )                                               AS vector_rank
    FROM chunks c
    JOIN documents d ON c.document_id = d.id
    {where_clause}
    ORDER BY c.embedding <=> :query_vec::vector
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
    d.product_hierarchy
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
        "query_vec": f"[{','.join(map(str, query_embedding))}]",
        "query_text": query_text,
        "candidate_limit": settings.search_candidate_limit,
        "top_k": top_k or settings.top_k_results,
    }

    if allowed_spaces:
        where_parts.append("d.allowed_spaces && :allowed_spaces::text[]")
        params["allowed_spaces"] = "{" + ",".join(allowed_spaces) + "}"

    if allowed_projects:
        where_parts.append("d.allowed_projects && :allowed_projects::text[]")
        params["allowed_projects"] = "{" + ",".join(allowed_projects) + "}"

    if product_filter:
        where_parts.append("d.product_hierarchy->>'product' = :product_filter")
        params["product_filter"] = product_filter

    where_clause = ("AND " + " AND ".join(where_parts)) if where_parts else ""
    # FTS leg: additional WHERE is added after the fts_vector @@ condition
    where_clause_fts = ("AND " + " AND ".join(where_parts)) if where_parts else ""

    sql = _HYBRID_SQL.format(
        where_clause=where_clause,
        where_clause_fts=where_clause_fts,
        k=_RRF_K,
    )

    result = await session.execute(text(sql), params)
    rows = result.fetchall()

    logger.debug("[hybrid_search] query=%r returned %d results", query_text[:80], len(rows))

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
        )
        for row in rows
    ]

