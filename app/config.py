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
    letter_model: str = "claude-sonnet-4-6"  # cover-letter drafting + fabrication check

    # Recency: shortlist ranking multiplies fit by a freshness weight in
    # [recency_floor, 1.0] that halves every recency_half_life_days. The floor keeps
    # decay gentle so a clearly-better older job still outranks a weak fresh one; a
    # missing post date is treated as neutral (weight 1.0). See app/ai/matching.py.
    recency_half_life_days: float = 30.0
    recency_floor: float = 0.85

    # Experience: shortlist multiplies fit by a soft penalty when a posting requires
    # more years than the user has (see app/ai/matching.py). Kept gentle and floored
    # so a strong stretch role still surfaces; a hard cutoff is a separate preference.
    experience_penalty_per_year: float = 0.06
    experience_floor: float = 0.6

    # Role-family classifier (app/ai/role_family.py): a job title is assigned to the
    # nearest role centroid only when the top cosine clears role_min_similarity and
    # beats the runner-up by role_min_margin; otherwise it stays unclassified (kept).
    role_min_similarity: float = 0.30
    role_min_margin: float = 0.02


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton so we parse the environment once."""
    return Settings()
