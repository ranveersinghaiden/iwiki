"""
ProductExpertRefresher — synthesises a compressed context entry for each product.

After every sync, the pipeline calls refresh_all() which:
  1. Queries all distinct products present in indexed documents.
  2. For each product, fetches up to 50 recent documents.
  3. Sends all cleaned content to the LLM with a structured prompt.
  4. Persists the resulting expert (description, compressed_context,
     upstream_dependencies, downstream_affected) via the repository.

The generated expert records are consumed by:
  - query-service /api/v1/experts endpoint (human + agent queries)
  - AI agents that need product context for feature dev / test generation
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.db.database import AsyncSessionFactory
from app.db import repository

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a product knowledge synthesiser. "
    "Return ONLY a valid JSON object — no markdown, no code fences, no explanation."
)

_USER_PROMPT_TEMPLATE = """\
You are synthesising expert knowledge for the product: "{product}".

Below are excerpts from Jira tickets and Confluence pages tagged to this product.
Each excerpt is separated by ---

{content_block}

---

Based ONLY on the content above, produce a JSON object with exactly these keys:

{{
  "description": "<1-2 sentence plain-English summary of what this product does>",
  "compressed_context": "<dense paragraph (max 400 words) capturing key responsibilities, \
architecture, data flows, important design decisions, and known limitations of this product. \
This is used by AI agents to understand the product deeply.>",
  "upstream_dependencies": [
    {{"product": "<name>", "component": "<name or null>", "reason": "<one sentence why>"}}
  ],
  "downstream_affected": [
    {{"product": "<name>", "component": "<name or null>", "reason": "<one sentence why>"}}
  ]
}}

Rules:
- upstream_dependencies: products/components that this product DEPENDS ON (calls, reads from, requires).
- downstream_affected: products/components that DEPEND ON this product (will break if this changes).
- Use only products and dependencies you can infer from the content — do not hallucinate.
- Both arrays may be empty ([]) if there is insufficient evidence.
"""


@dataclass(frozen=True)
class ExpertResult:
    product: str
    component: str | None
    description: str
    compressed_context: str
    upstream_dependencies: list[dict[str, Any]]
    downstream_affected: list[dict[str, Any]]
    source_document_count: int


class ProductExpertRefresher:
    """Builds and persists product expert records after every ingestion sync."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,
        )
        self._model = settings.llm_model

    async def refresh_all(self) -> list[ExpertResult]:
        """Refresh expert records for every distinct product in the index."""
        async with AsyncSessionFactory() as session:
            products = await repository.get_distinct_products(session)

        logger.info("[ExpertRefresher] refreshing %d products", len(products))
        results: list[ExpertResult] = []

        for product in products:
            try:
                result = await self._refresh_product(product)
                results.append(result)
            except Exception as exc:
                logger.error(
                    "[ExpertRefresher] failed for product=%s: %s", product, exc, exc_info=exc
                )

        logger.info("[ExpertRefresher] done refreshed=%d failed=%d", len(results), len(products) - len(results))
        return results

    async def _refresh_product(self, product: str) -> ExpertResult:
        async with AsyncSessionFactory() as session:
            docs = await repository.get_documents_by_product(session, product, limit=50)

        if not docs:
            logger.warning("[ExpertRefresher] no docs found for product=%s", product)
            return ExpertResult(
                product=product,
                component=None,
                description=f"No indexed content found for {product}.",
                compressed_context="",
                upstream_dependencies=[],
                downstream_affected=[],
                source_document_count=0,
            )

        # Build content block — cap each doc at 800 chars to stay within token budget
        snippets = []
        for doc in docs:
            title = doc.get("title") or ""
            body = (doc.get("cleaned_content") or "")[:800]
            snippets.append(f"Title: {title}\n{body}")
        content_block = "\n---\n".join(snippets)

        prompt = _USER_PROMPT_TEMPLATE.format(product=product, content_block=content_block)

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0,
        )

        raw = (response.choices[0].message.content or "").strip()
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "[ExpertRefresher] LLM returned invalid JSON for product=%s: %s", product, exc, exc_info=exc
            )
            raise

        expert = ExpertResult(
            product=product,
            component=None,
            description=data.get("description", ""),
            compressed_context=data.get("compressed_context", ""),
            upstream_dependencies=data.get("upstream_dependencies", []),
            downstream_affected=data.get("downstream_affected", []),
            source_document_count=len(docs),
        )

        async with AsyncSessionFactory() as session:
            await repository.upsert_product_expert(
                session,
                product=expert.product,
                component=expert.component,
                description=expert.description,
                compressed_context=expert.compressed_context,
                upstream_dependencies=expert.upstream_dependencies,
                downstream_affected=expert.downstream_affected,
                source_document_count=expert.source_document_count,
            )

        logger.info(
            "[ExpertRefresher] product=%s docs=%d upstream=%d downstream=%d",
            product,
            len(docs),
            len(expert.upstream_dependencies),
            len(expert.downstream_affected),
        )
        return expert

