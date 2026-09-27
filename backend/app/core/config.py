"""Process-wide settings.

Values come from environment variables, falling back to the repo-root `.env`
file when present (never committed, see `.gitignore` / R10). No default here
is a real credential: an empty `.env` and no environment still import and
construct `Settings` cleanly, which is what lets CI and a bare dev machine
boot before secrets exist.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Settings", "get_settings"]

# `backend/app/core/config.py` -> repo root is three parents up.
_REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Typed settings, read once and cached via `get_settings()`."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/latam_app"
    golden_database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/latam_golden"
    redis_url: str = "redis://localhost:6379/0"
    otel_exporter_otlp_endpoint: str = ""  # empty = tracing off (D5 exporters land later)
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings`, built once per process."""
    return Settings()
