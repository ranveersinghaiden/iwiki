"""Embedding generator — OpenAI or Ollama (OpenAI-compatible API)."""
from __future__ import annotations

import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.ai_base_url,  # None → OpenAI default; set for Ollama
        )
        self._model = settings.embedding_model
        self._batch_size = settings.embedding_batch_size

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts in batches. Returns one vector per input text."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            # Truncate very long strings — embedding API has token limits
            batch = [t[:8000] for t in batch]
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
            )
            sorted_data = sorted(response.data, key=lambda d: d.index)
            all_embeddings.extend(item.embedding for item in sorted_data)
            logger.debug(
                "[Embedder] embedded batch %d-%d with model=%s",
                i,
                i + len(batch),
                self._model,
            )

        return all_embeddings

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

