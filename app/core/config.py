"""Application settings, loaded from environment variables (or a .env file).

Secrets (JWT key, LLM API keys) are only ever read from the environment and are
never logged. See `.env.example` for the full list.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Career Pivot Coach API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False

    # --- Database -----------------------------------------------------------
    # Async SQLAlchemy URL. PostgreSQL (asyncpg) is the primary target.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_coach"
    db_echo: bool = False

    # --- Auth ---------------------------------------------------------------
    jwt_secret_key: SecretStr = SecretStr("change-me-in-production-please-use-a-long-random-string")
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- LLM ----------------------------------------------------------------
    # "none" disables LLM calls entirely; every feature then uses its rule-based fallback.
    llm_provider: Literal["openai", "gemini", "none"] = "none"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 1

    # --- Uploads & limits ---------------------------------------------------
    max_resume_size_mb: float = 5.0
    max_resume_pages: int = 15
    max_document_chars: int = 30_000  # truncate very long resumes / JDs before sending to the LLM
    url_fetch_enabled: bool = True
    url_fetch_timeout_seconds: float = 10.0
    url_fetch_max_bytes: int = 2_000_000

    # --- Live job postings (all optional; without keys the curated seed postings are used) ---
    jsearch_api_key: SecretStr | None = None      # RapidAPI key for JSearch
    adzuna_app_id: str | None = None
    adzuna_app_key: SecretStr | None = None
    market_cache_hours: int = 24
    market_timeout_seconds: float = 15.0

    # --- Rate limiting (in-memory, per client IP / user) --------------------
    rate_limit_enabled: bool = True
    auth_rate_limit_per_minute: int = 20
    ai_rate_limit_per_minute: int = 30

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    @property
    def max_resume_bytes(self) -> int:
        return int(self.max_resume_size_mb * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
