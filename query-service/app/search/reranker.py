"""
Reranker — refines hybrid-search candidates before answer generation.

Two stages:

  1. Signal blend (always on, deterministic, cheap). For each candidate:
        blended = w_rrf*norm(rrf) + w_fresh*freshness
                + w_auth*authority + w_tax*taxonomy_match
     where the weights are normalised internally. ``rerank_score`` is set to
     this blended value and candidates are sorted by it.

  2. LLM rerank (optional, settings.rerank_llm_enabled). The top-N blended
     candidates are handed to the LLM, which returns an ordering. Parsing is
     strict: ANY malformed / missing response leaves the signal order intact,
     so retrieval never regresses and the stage is safe to run against stubs.

Returns the top_k SearchResults, reordered, each carrying ``rerank_score``
(the blended signal score; the final sequence order may be LLM-refined).
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone

from openai import APIError, AsyncOpenAI

from app.config import settings
from app.search.hybrid_search import SearchResult

logger = logging.getLogger(__name__)

_LLM_RERANK_MARKER = "You are a precise search result reranker."


def _authority(source_type: str) -> float:
    if source_type == "confluence":
        return settings.rerank_authority_confluence
    if source_type == "jira":
        return settings.rerank_authority_jira
    return settings.rerank_authority_default


def _freshness(source_updated_at: datetime | None) -> float:
    """Exponential decay by age; neutral 0.5 when the timestamp is unknown."""
    if source_updated_at is None:
        return 0.5
    now = datetime.now(timezone.utc)
    ts = source_updated_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
    half_life = max(1.0, settings.rerank_freshness_half_life_days)
    return 0.5 ** (age_days / half_life)


def _taxonomy_match(query_lower: str, hierarchy: dict) -> float:
    """Reward candidates whose product/feature/component is named in the query."""
    score = 0.0
    for key, weight in (("product", 0.6), ("feature", 0.8), ("component", 1.0)):
        value = hierarchy.get(key)
        if isinstance(value, str) and value and value.lower() in query_lower:
            score = max(score, weight)
    return score


def _blended_score(
    result: SearchResult, *, rrf_norm: float, query_lower: str
) -> float:
    w_rrf = settings.rerank_weight_rrf
    w_fresh = settings.rerank_weight_freshness
    w_auth = settings.rerank_weight_authority
    w_tax = settings.rerank_weight_taxonomy
    total = w_rrf + w_fresh + w_auth + w_tax
    if total <= 0:
        return rrf_norm

    blended = (
        w_rrf * rrf_norm
        + w_fresh * _freshness(result.source_updated_at)
        + w_auth * _authority(result.source_type)
        + w_tax * _taxonomy_match(query_lower, result.product_hierarchy)
    )
    return blended / total


async def rerank(
    query: str,
    candidates: list[SearchResult],
    *,
    top_k: int,
) -> list[SearchResult]:
    """Rerank hybrid-search candidates and return the best ``top_k``."""
    if not candidates or not settings.rerank_enabled:
        return candidates[:top_k]

    query_lower = query.lower()
    scores = [c.rrf_score for c in candidates]
    lo, hi = min(scores), max(scores)
    span = hi - lo

    scored: list[SearchResult] = []
    for c in candidates:
        rrf_norm = 1.0 if span == 0 else (c.rrf_score - lo) / span
        blended = _blended_score(c, rrf_norm=rrf_norm, query_lower=query_lower)
        scored.append(dataclasses.replace(c, rerank_score=round(blended, 6)))

    scored.sort(key=lambda r: r.rerank_score or 0.0, reverse=True)

    if settings.rerank_llm_enabled and len(scored) > 1:
        scored = await _llm_rerank(query, scored)

    logger.info(
        "[reranker] reranked %d candidates → top_k=%d (llm=%s)",
        len(candidates), top_k, settings.rerank_llm_enabled,
    )
    return scored[:top_k]


async def _llm_rerank(query: str, candidates: list[SearchResult]) -> list[SearchResult]:
    """Reorder the top-N candidates via the LLM. Falls back to input order on any error."""
    n = min(settings.rerank_llm_top_n, len(candidates))
    head, tail = candidates[:n], candidates[n:]

    listing = "\n".join(
        f"[{i}] {c.title} :: {c.content[:300]}" for i, c in enumerate(head)
    )
    prompt = (
        f"{_LLM_RERANK_MARKER}\n"
        f"Question: {query}\n\n"
        f"Candidates:\n{listing}\n\n"
        f"Return ONLY a JSON array of the candidate indices (0 to {n - 1}) ordered "
        "from most to least relevant to the question. Include every index exactly once. "
        'Example: [2,0,1]'
    )

    try:
        async with AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.ai_base_url) as client:
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=128,
            )
            raw = (response.choices[0].message.content or "").strip()
        order = _parse_order(raw, n)
    except (APIError, json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("[reranker] LLM rerank failed (%s) — keeping signal order", exc)
        return candidates

    if order is None:
        logger.info("[reranker] LLM rerank returned no usable order — keeping signal order")
        return candidates

    reordered = [head[i] for i in order]
    logger.debug("[reranker] LLM reordered top-%d candidates", n)
    return reordered + tail


def _parse_order(raw: str, n: int) -> list[int] | None:
    """Parse a JSON index array into a valid full permutation of range(n)."""
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, list):
        return None

    seen: set[int] = set()
    order: list[int] = []
    for item in parsed:
        if isinstance(item, bool):  # bool is an int subclass — reject explicitly
            continue
        if isinstance(item, int) and 0 <= item < n and item not in seen:
            seen.add(item)
            order.append(item)
    # Append any indices the model dropped, preserving the original order.
    for i in range(n):
        if i not in seen:
            order.append(i)
    return order if order else None
