"""Embedder for query-service — same config as ingestion-service."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class QueryEmbedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,
        )
        self._model = settings.embedding_model

    async def embed(self, text: str) -> list[float]:
        text = text[:8000]
        response = await self._client.embeddings.create(
            model=self._model,
            input=[text],
        )
        logger.debug("[QueryEmbedder] embedded query len=%d", len(text))
        return response.data[0].embedding

