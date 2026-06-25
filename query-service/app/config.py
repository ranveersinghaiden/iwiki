from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki"

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    llm_model: str = "gpt-4o-mini"
    ollama_base_url: Optional[str] = None

    # Hybrid search tuning
    # Number of candidates fetched from each of vector + FTS legs before RRF
    search_candidate_limit: int = 20
    # Final top-K chunks passed to the LLM as RAG context
    top_k_results: int = 8
    # Maximum characters in a user query
    max_query_length: int = 4096

    # ── Reranking ─────────────────────────────────────────────────────────────
    # Master switch for the signal-blend reranking stage.
    rerank_enabled: bool = True
    # Size of the candidate pool pulled from hybrid search before reranking.
    rerank_candidate_pool: int = 20
    # Blend weights (relative; normalised internally). RRF dominates by default.
    rerank_weight_rrf: float = 0.55
    rerank_weight_freshness: float = 0.15
    rerank_weight_authority: float = 0.15
    rerank_weight_taxonomy: float = 0.15
    # Half-life (days) for the freshness exponential decay.
    rerank_freshness_half_life_days: float = 180.0
    # Per-source authority weights (0-1).
    rerank_authority_confluence: float = 1.0
    rerank_authority_jira: float = 0.7
    rerank_authority_default: float = 0.6
    # Optional LLM rerank stage applied to the top-N blended candidates.
    rerank_llm_enabled: bool = True
    rerank_llm_top_n: int = 10

    @property
    def ai_base_url(self) -> Optional[str]:
        return self.ollama_base_url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

