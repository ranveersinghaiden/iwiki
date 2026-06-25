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

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://iwiki:iwiki@localhost:5432/iwiki"

    # ── Jira ──────────────────────────────────────────────────────────────────
    jira_base_url: str = ""
    jira_user_email: str = ""
    jira_api_token: str = ""
    # Comma-separated project keys, e.g. "PROJ1,PROJ2"
    jira_projects: str = ""
    # Max results per Jira page request
    jira_page_size: int = 100

    # ── Confluence ────────────────────────────────────────────────────────────
    confluence_base_url: str = ""
    confluence_api_token: str = ""
    # Comma-separated space keys
    confluence_spaces: str = ""
    confluence_page_size: int = 50

    # ── AI ────────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    llm_model: str = "gpt-4o-mini"
    # Set to Ollama base URL to use local models instead of OpenAI
    ollama_base_url: Optional[str] = None

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_api_key: str = ""

    # ── Ingestion tuning ──────────────────────────────────────────────────────
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_batch_size: int = 32
    # 5-part cron expression: minute hour day month day_of_week
    sync_cron: str = "0 * * * *"

    # ── Hierarchy ─────────────────────────────────────────────────────────────
    hierarchy_config_path: str = "product_hierarchy.yaml"

    # ── Classification cascade (rule → semantic → LLM) ────────────────────────
    # Minimum keyword score for the deterministic rule stage to accept a match.
    classification_rule_min_score: float = 3.0
    # Run the embedding-similarity stage when rules are inconclusive.
    classification_semantic_fallback: bool = True
    # Minimum cosine similarity for the semantic stage to accept a node match.
    classification_semantic_threshold: float = 0.45
    # Results below this confidence are flagged needs_review for triage.
    classification_review_threshold: float = 0.5

    @property
    def jira_project_list(self) -> list[str]:
        return [p.strip() for p in self.jira_projects.split(",") if p.strip()]

    @property
    def confluence_space_list(self) -> list[str]:
        return [s.strip() for s in self.confluence_spaces.split(",") if s.strip()]

    @property
    def ai_base_url(self) -> Optional[str]:
        """Return Ollama base URL if configured, otherwise None (→ OpenAI default)."""
        return self.ollama_base_url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

