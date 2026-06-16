"""
Token-based sliding-window text chunker.
Uses tiktoken when available (requires Rust); falls back to a word-based
approximation (avg 1.3 tokens/word) when tiktoken is not installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)

# ── optional tiktoken import ──────────────────────────────────────────────────
try:
    import tiktoken as _tiktoken

    _TIKTOKEN_AVAILABLE = True
    logger.debug("[chunker] tiktoken available — using BPE tokeniser")
except ImportError:
    _tiktoken = None  # type: ignore[assignment]
    _TIKTOKEN_AVAILABLE = False
    logger.warning("[chunker] tiktoken not available — using word-based approximation")

_ENCODING_NAME = "cl100k_base"
_TOKENS_PER_WORD = 1.3  # average for English prose


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
        if _TIKTOKEN_AVAILABLE:
            self._enc = _tiktoken.get_encoding(_ENCODING_NAME)
        else:
            self._enc = None

    def chunk(self, text: str) -> list[Chunk]:
        if not text:
            return []
        if self._enc is not None:
            return self._chunk_tiktoken(text)
        return self._chunk_words(text)

    # ── tiktoken path ─────────────────────────────────────────────────────────

    def _chunk_tiktoken(self, text: str) -> list[Chunk]:
        tokens = self._enc.encode(text)
        total = len(tokens)
        if total == 0:
            return []

        chunks: list[Chunk] = []
        start = 0
        idx = 0

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

    # ── word-based fallback ───────────────────────────────────────────────────

    def _chunk_words(self, text: str) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        # Convert token sizes to approximate word counts
        words_per_chunk = max(1, int(self._chunk_size / _TOKENS_PER_WORD))
        words_overlap = max(0, int(self._overlap / _TOKENS_PER_WORD))

        chunks: list[Chunk] = []
        start = 0
        idx = 0
        total = len(words)

        while start < total:
            end = min(start + words_per_chunk, total)
            content = " ".join(words[start:end])
            token_est = int((end - start) * _TOKENS_PER_WORD)
            chunks.append(Chunk(chunk_index=idx, content=content, token_count=token_est))
            if end == total:
                break
            start += words_per_chunk - words_overlap
            idx += 1

        return chunks



