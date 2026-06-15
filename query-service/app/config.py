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

    @property
    def ai_base_url(self) -> Optional[str]:
        return self.ollama_base_url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

