"""Token-based sliding-window text chunker using tiktoken."""
from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from app.config import settings

# cl100k_base tokeniser covers GPT-3.5/4 and embedding models
_ENCODING_NAME = "cl100k_base"


@dataclass(frozen=True, slots=True)
class Chunk:
    chunk_index: int
    content: str
    token_count: int


class TextChunker:
    def __init__(
        self,
        chunk_size: int = settings.chunk_size,
        overlap: int = settings.chunk_overlap,
    ) -> None:
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._enc = tiktoken.get_encoding(_ENCODING_NAME)

    def chunk(self, text: str) -> list[Chunk]:
        if not text:
            return []

        tokens = self._enc.encode(text)
        total = len(tokens)
        if total == 0:
            return []

        chunks: list[Chunk] = []
        idx = 0
        start = 0

        while start < total:
            end = min(start + self._chunk_size, total)
            chunk_tokens = tokens[start:end]
            content = self._enc.decode(chunk_tokens)
            chunks.append(Chunk(chunk_index=idx, content=content, token_count=len(chunk_tokens)))

            if end == total:
                break

            start += self._chunk_size - self._overlap
            idx += 1

        return chunks

