"""Embedder for query-service — same config as ingestion-service."""
from __future__ import annotations

import logging

from app.config import settings
from app.llm import get_client

logger = logging.getLogger(__name__)


class QueryEmbedder:
    def __init__(self) -> None:
        self._model = settings.embedding_model

    async def embed(self, text: str) -> list[float]:
        text = text[:8000]
        response = await get_client().embeddings.create(
            model=self._model,
            input=[text],
        )
        logger.debug("[QueryEmbedder] embedded query len=%d", len(text))
        return response.data[0].embedding

