"""
Query service API routes.

POST /api/v1/query        — natural language search (rate-limited by input size)
GET  /api/v1/health       — open health check

Permission model (MVP — header-based):
  X-Allowed-Spaces:   comma-separated Confluence space keys user can access
  X-Allowed-Projects: comma-separated Jira project keys user can access
  X-Product-Filter:   optional product name to restrict results to one product
  If headers are absent → no permission filtering (all results returned).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings
from app.db.database import AsyncSessionFactory
from app.rag.answer_generator import Answer, Source, generate_answer
from app.search.embedder import QueryEmbedder
from app.search.hybrid_search import hybrid_search

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Request / Response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=settings.max_query_length)
    top_k: int = Field(default=settings.top_k_results, ge=1, le=20)


class SourceResponse(BaseModel):
    title: str
    source_type: str
    source_id: str
    source_url: str | None
    product_hierarchy: dict[str, Any]
    relevance_score: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    query: str
    chunks_retrieved: int
    model_used: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def query_knowledge_base(
    request: QueryRequest,
    x_allowed_spaces: str | None = Header(default=None),
    x_allowed_projects: str | None = Header(default=None),
    x_product_filter: str | None = Header(default=None),
) -> QueryResponse:
    """
    Answer a plain-language question using the indexed Jira + Confluence knowledge base.
    Returns a human-readable answer with source citations.
    """
    allowed_spaces = _parse_header_list(x_allowed_spaces)
    allowed_projects = _parse_header_list(x_allowed_projects)

    embedder = QueryEmbedder()
    query_vec = await embedder.embed(request.query)

    async with AsyncSessionFactory() as session:
        results = await hybrid_search(
            session,
            query_embedding=query_vec,
            query_text=request.query,
            allowed_spaces=allowed_spaces,
            allowed_projects=allowed_projects,
            product_filter=x_product_filter,
            top_k=request.top_k,
        )

    answer: Answer = await generate_answer(request.query, results)

    logger.info(
        "[routes] query answered query=%r sources=%d",
        request.query[:80],
        len(answer.sources),
    )

    return QueryResponse(
        answer=answer.answer_text,
        sources=[_source_to_response(s) for s in answer.sources],
        query=answer.query,
        chunks_retrieved=answer.chunks_used,
        model_used=answer.model_used,
    )


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_header_list(header: str | None) -> list[str] | None:
    if not header:
        return None
    return [item.strip() for item in header.split(",") if item.strip()]


def _source_to_response(s: Source) -> SourceResponse:
    return SourceResponse(
        title=s.title,
        source_type=s.source_type,
        source_id=s.source_id,
        source_url=s.source_url,
        product_hierarchy=s.product_hierarchy,
        relevance_score=round(s.rrf_score, 4),
    )

