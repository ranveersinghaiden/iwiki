"""
RAG answer generator.
Takes top-K SearchResult chunks → builds a context window → calls the LLM.
Returns a structured answer with inline citations.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.search.hybrid_search import SearchResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a helpful internal knowledge assistant.
Answer the user's question using ONLY the provided context excerpts from Jira and Confluence.
Rules:
- If the context does not contain enough information, say so clearly — do not hallucinate.
- Be concise and factual.
- At the end of your answer, include a "Sources" section listing each document you referenced.
- Format sources as: [N] Title — source_type/source_id (URL if available)
"""


@dataclass(frozen=True, slots=True)
class Source:
    title: str
    source_type: str
    source_id: str
    source_url: str | None
    product_hierarchy: dict[str, Any]
    rrf_score: float


@dataclass(frozen=True, slots=True)
class Answer:
    answer_text: str
    sources: list[Source]
    query: str
    chunks_used: int
    model_used: str


async def generate_answer(
    query: str,
    results: list[SearchResult],
) -> Answer:
    """Build a RAG context from results and return an LLM-generated answer with citations."""
    if not results:
        return Answer(
            answer_text="No relevant information found in the knowledge base for your query.",
            sources=[],
            query=query,
            chunks_used=0,
            model_used=settings.llm_model,
        )

    # Deduplicate sources (a document may contribute multiple chunks)
    seen_doc_ids: set[str] = set()
    sources: list[Source] = []
    context_parts: list[str] = []

    for i, r in enumerate(results, start=1):
        context_parts.append(f"[{i}] {r.title}\n{r.content}")
        if r.document_id not in seen_doc_ids:
            seen_doc_ids.add(r.document_id)
            sources.append(
                Source(
                    title=r.title,
                    source_type=r.source_type,
                    source_id=r.source_id,
                    source_url=r.source_url,
                    product_hierarchy=r.product_hierarchy,
                    rrf_score=r.rrf_score,
                )
            )

    context = "\n\n---\n\n".join(context_parts)

    user_message = (
        f"Context:\n\n{context}\n\n"
        f"Question: {query}"
    )

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.ai_base_url,
    )

    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
        max_tokens=1500,
    )

    answer_text = response.choices[0].message.content or "No answer generated."
    logger.info(
        "[answer_generator] query=%r sources=%d chunks=%d model=%s",
        query[:80],
        len(sources),
        len(results),
        settings.llm_model,
    )

    return Answer(
        answer_text=answer_text,
        sources=sources,
        query=query,
        chunks_used=len(results),
        model_used=settings.llm_model,
    )

