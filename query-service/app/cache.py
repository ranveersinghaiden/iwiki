"""Redis-backed cache for the query service.

Two things are cached:

* **Query embeddings** — deterministic per (model, text), so a long TTL is safe and
  saves an embedding API round-trip on repeated questions.
* **Full answers** — keyed by the query *and the caller's permission scope* so a
  cached answer can never leak content the requester is not allowed to see.

The cache is **fail-open**: a missing ``redis_url``, a disabled flag, or *any* Redis
error degrades to a normal cache miss. The query path must never break because the
cache is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Imported lazily so the service still starts if redis isn't installed.
try:  # pragma: no cover - import guard
    from redis.asyncio import Redis
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - redis optional
    Redis = None  # type: ignore[assignment, misc]
    RedisError = Exception  # type: ignore[assignment, misc]

_redis: "Optional[Redis]" = None


def _enabled() -> bool:
    return bool(settings.cache_enabled and settings.redis_url and Redis is not None)


def get_redis() -> "Optional[Redis]":
    """Return the shared Redis client, or None when caching is unavailable."""
    global _redis
    if not _enabled():
        return None
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
        logger.info("[cache] Redis cache enabled url=%s", settings.redis_url)
    return _redis


async def aclose_redis() -> None:
    """Close the shared Redis client on shutdown."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception as exc:  # noqa: BLE001 - best effort on shutdown
            logger.debug("[cache] error closing redis: %s", exc)
        _redis = None


def _digest(*parts: Any) -> str:
    raw = "\x1f".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def embedding_key(model: str, text: str) -> str:
    return f"qa:cache:emb:{_digest(model, text)}"


def answer_key(
    query: str,
    top_k: int,
    allowed_spaces: list[str] | None,
    allowed_projects: list[str] | None,
    product_filter: str | None,
) -> str:
    # Permission scope is part of the key → no cross-tenant answer leakage.
    return "qa:cache:ans:" + _digest(
        query,
        top_k,
        sorted(allowed_spaces or []),
        sorted(allowed_projects or []),
        product_filter,
    )


async def get_json(key: str) -> Any | None:
    """Return the cached JSON value for a key, or None on miss/error."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except (RedisError, OSError) as exc:
        logger.debug("[cache] get failed key=%s: %s", key, exc)
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_json(key: str, value: Any, ttl: int) -> None:
    """Store a JSON-serialisable value under a key with a TTL. Never raises."""
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except (RedisError, OSError, TypeError, ValueError) as exc:
        logger.debug("[cache] set failed key=%s: %s", key, exc)
