"""Shared singleton AsyncOpenAI client for the query service.

A single client reuses one HTTP connection pool across embedding, reranking and
answer generation instead of opening (and leaking) a new pool on every request —
which matters under sustained query load. The client is created lazily and closed
on application shutdown via :func:`aclose_client`.
"""
from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Return the process-wide AsyncOpenAI client, creating it on first use."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,
        )
    return _client


async def aclose_client() -> None:
    """Close the shared client and drop the reference (called on shutdown)."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
