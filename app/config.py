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


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton so we parse the environment once."""
    return Settings()
