"""Query-service read-only repository for product_experts."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_GET_ALL = text("""
    SELECT id, product, component, description, compressed_context,
           upstream_dependencies, downstream_affected, source_document_count,
           generated_at, updated_at
    FROM product_experts
    ORDER BY product, component NULLS FIRST
""")

_GET_ONE = text("""
    SELECT id, product, component, description, compressed_context,
           upstream_dependencies, downstream_affected, source_document_count,
           generated_at, updated_at
    FROM product_experts
    WHERE product = :product
      AND ((:component IS NULL AND component IS NULL) OR component = :component)
    LIMIT 1
""")

_GET_BY_PRODUCT_ANY_COMPONENT = text("""
    SELECT id, product, component, description, compressed_context,
           upstream_dependencies, downstream_affected, source_document_count,
           generated_at, updated_at
    FROM product_experts
    WHERE product = :product
    ORDER BY component NULLS FIRST
""")


async def list_experts(session: AsyncSession) -> list[dict[str, Any]]:
    """Return all product expert records."""
    result = await session.execute(_GET_ALL)
    return [dict(row._mapping) for row in result.fetchall()]


async def get_expert(
    session: AsyncSession, product: str, component: str | None = None
) -> dict[str, Any] | None:
    """Return a single expert by product (and optional component)."""
    result = await session.execute(_GET_ONE, {"product": product, "component": component})
    row = result.fetchone()
    return dict(row._mapping) if row else None


async def get_experts_for_product(
    session: AsyncSession, product: str
) -> list[dict[str, Any]]:
    """Return all expert records for a given product (product-level + all components)."""
    result = await session.execute(_GET_BY_PRODUCT_ANY_COMPONENT, {"product": product})
    return [dict(row._mapping) for row in result.fetchall()]

