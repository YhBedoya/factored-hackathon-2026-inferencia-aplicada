"""Process-wide settings.

Values come from environment variables, falling back to the repo-root `.env`
file when present (never committed, see `.gitignore` / R10). No default here
is a real credential: an empty `.env` and no environment still import and
construct `Settings` cleanly, which is what lets CI and a bare dev machine
boot before secrets exist.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    demo_otp_code: str = ""  # ADR-008; never committed, shared with judges by email

    app_env: Literal["dev", "eval", "prod"] = "dev"
    bank: Literal["fake", "postgres"] = "postgres"
    # Empty here is not a real credential (see module docstring): the refusal
    # on an empty secret happens at app start, not in this model (D21).
    jwt_secret: str = ""
    identity_hmac_key: str = ""
    credentials_seed: str = ""
    pii_vault_key: str = ""  # Fernet key (D21); vault rows and message content need it
    agent_system: Literal["proposed", "baseline"] = "proposed"  # baseline only under APP_ENV=eval
    session_ttl_minutes: int = 60
    login_max_failures: int = 5
    login_window_seconds: int = 900


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings`, built once per process."""
    return Settings()
