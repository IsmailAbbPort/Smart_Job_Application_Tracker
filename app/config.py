"""Application settings, loaded from environment / .env via pydantic-settings.

Secrets never live in code. Local dev reads `.env` (gitignored); production
injects real environment variables. See `.env.example` for the contract.
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The source-visible dev default. Signing prod sessions with this is an account-
# takeover risk (anyone can forge a session cookie), so the validator below refuses
# to boot with it outside development.
INSECURE_JWT_DEFAULT = "dev-insecure-change-me-in-production-0123456789"
# environment values treated as a real, internet-facing deploy.
_PRODUCTION_ENVIRONMENTS = {"production", "prod", "staging"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Smart Job Application Tracker"
    environment: str = "development"

    # Error tracking. When SENTRY_DSN is set (prod), errors are reported to Sentry;
    # unset (local/tests) makes init a no-op. See app/main.py.
    sentry_dsn: str | None = None

    # Postgres + pgvector connection (SQLAlchemy URL).
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/jobtracker"

    # AI provider keys — unused in Phase 0, wired in later phases.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None

    # Auth: signs the session JWT stored in an httpOnly cookie. Override in prod via
    # env; the dev default is fine locally but must not be used on a real deploy
    # (enforced by _enforce_production_secrets below).
    jwt_secret: str = INSECURE_JWT_DEFAULT
    jwt_expire_days: int = 30
    # Set true in production (HTTPS) so the session cookie is marked Secure.
    cookie_secure: bool = False

    # Trust the X-Forwarded-For header for the guest rate-limit identity. Off by
    # default because the header is client-spoofable: a direct caller could forge a
    # fresh IP per request and evade the per-identity cap. Enable ONLY when the app
    # sits behind a proxy that overwrites the header (see app/ratelimit.py).
    trust_forwarded_for: bool = False

    # AI model selection. Swappable via env so the pipeline is not pinned to one
    # provider/model (easier A/B once a golden set exists; nicer to reuse).
    # embedding_dimensions must match the pgvector column (1536); text-embedding-3
    # models can be truncated to it, so switching small<->large needs no migration.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    judge_model: str = "claude-haiku-4-5-20251001"
    letter_model: str = "claude-sonnet-4-6"  # cover-letter drafting + revise pass
    # The fabrication audit is classification-shaped, so it can run on a cheaper model
    # than the draft; defaults to the draft model. A/B the trade via the eval harness.
    letter_audit_model: str = "claude-sonnet-4-6"

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

    # Rate limits on the paid AI endpoints, to protect the API budget (see
    # app/ratelimit.py). "per_day" is per identity (a signed-in user, or a guest's
    # IP), counted per calendar day. "global_per_month" is a hard monthly ceiling
    # across everyone, counted per calendar month (both UTC). The monthly caps are
    # sized to keep the worst-case Anthropic spend under ~$20/mo (judges are Haiku,
    # letters are two Sonnet calls each, so letters cost ~5x and get the tighter cap).
    # A 429 tells the user the cap and when it resets.
    rl_judge_per_day: int = 20
    rl_judge_global_per_month: int = 1200
    rl_letter_per_day: int = 8
    rl_letter_global_per_month: int = 150

    # Daily ingest scheduler (app/scheduler.py): ingest -> embed -> classify, run
    # once a day in-process so a single-container deploy keeps its corpus fresh with
    # no extra infrastructure. Disabled under tests. ingest_hour_utc is 0-23.
    ingest_schedule_enabled: bool = True
    ingest_hour_utc: int = 3
    ingest_embed_limit: int = 5000
    ingest_classify_limit: int = 6000

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        """Refuse to boot a real deploy with the insecure dev defaults.

        A production `environment` must carry a real JWT secret (else session cookies
        are forgeable) and mark the cookie Secure (HTTPS-only). Development/test keep
        the permissive defaults so local runs and the suite need no configuration.
        """
        if self.environment.strip().lower() in _PRODUCTION_ENVIRONMENTS:
            if not self.jwt_secret or self.jwt_secret == INSECURE_JWT_DEFAULT:
                raise ValueError(
                    "JWT_SECRET must be set to a strong, non-default value in production."
                )
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must be true in production (HTTPS).")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton so we parse the environment once."""
    return Settings()
