"""Application settings, loaded from environment / .env via pydantic-settings.

Secrets never live in code. Local dev reads `.env` (gitignored); production
injects real environment variables. See `.env.example` for the contract.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Smart Job Application Tracker"
    environment: str = "development"

    # Postgres + pgvector connection (SQLAlchemy URL).
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/jobtracker"

    # AI provider keys — unused in Phase 0, wired in later phases.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # AI model selection. Swappable via env so the pipeline is not pinned to one
    # provider/model (easier A/B once a golden set exists; nicer to reuse).
    # embedding_dimensions must match the pgvector column (1536); text-embedding-3
    # models can be truncated to it, so switching small<->large needs no migration.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    judge_model: str = "claude-haiku-4-5-20251001"

    # Recency: shortlist ranking multiplies fit by a freshness weight in
    # [recency_floor, 1.0] that halves every recency_half_life_days. The floor keeps
    # decay gentle so a clearly-better older job still outranks a weak fresh one; a
    # missing post date is treated as neutral (weight 1.0). See app/ai/matching.py.
    recency_half_life_days: float = 30.0
    recency_floor: float = 0.85


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton so we parse the environment once."""
    return Settings()
