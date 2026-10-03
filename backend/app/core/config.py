"""Process-wide settings.

Values come from environment variables, falling back to the repo-root `.env`
file when present (never committed, see `.gitignore` / R10). No default here
is a real credential: an empty `.env` and no environment still import and
construct `Settings` cleanly, which is what lets CI and a bare dev machine
boot before secrets exist.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, get_args

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

__all__ = ["Fault", "Settings", "get_settings"]

# Defined here (re-exported by `core/faults.py`) because `Settings` parses it and
# `faults.py` imports this module, not the other way round.
Fault = Literal["bedrock_timeout", "cards_write_error", "readback_mismatch"]

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

    # D7-A: personas file for the simulator route, and the build's git SHA for
    # the timeline/report provenance ("unknown" outside an image build).
    personas_path: Path = Path("/app/eval/personas.yaml")
    git_sha: str = "unknown"

    # Reliability (D6-A). `FAULTS` is comma-separated and set on the command
    # line only; the guard in `main.py` refuses it under APP_ENV=prod.
    faults: Annotated[frozenset[Fault], NoDecode] = frozenset()
    llm_disabled: bool = False
    # Learned intent classifier bundle dir (ADR-032). The image sets
    # INTENT_MODEL_DIR to /app/ml/intent/models; this default is the repo path
    # the host-run eval backend uses.
    intent_model_dir: Path = Path(__file__).resolve().parents[3] / "ml" / "intent" / "models"
    tool_timeout_s: float = 3.0
    turn_cap_per_conversation: int = 40
    turn_cap_per_account_day: int = 150
    retry_max: int = 2
    retry_backoff_base_s: float = 0.5
    retry_backoff_cap_s: float = 2.0

    @field_validator("faults", mode="before")
    @classmethod
    def _parse_faults(cls, value: object) -> object:
        if isinstance(value, str):
            names = [part.strip() for part in value.split(",") if part.strip()]
            unknown = [n for n in names if n not in get_args(Fault)]
            if unknown:
                raise ValueError(f"unknown fault(s): {', '.join(unknown)}")
            return frozenset(names)
        return value


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide `Settings`, built once per process."""
    return Settings()
