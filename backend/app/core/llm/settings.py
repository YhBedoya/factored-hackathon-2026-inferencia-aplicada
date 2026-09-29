"""LLM provider settings.

See `docs/specs/d1-b-agent-sandbox.md` §"Contracts" -> `app/core/llm/` (D3). A1's
settings nest or import `LLMSettings` at merge; until then it stands alone.
"""

from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LLMSettings"]


class LLMSettings(BaseSettings):
    """Provider choice, credentials and the R11/R7 call-shape knobs.

    Field names double as env var names (pydantic-settings matches case-
    insensitively), so `llm_provider` reads `LLM_PROVIDER`, and so on.
    """

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"
    anthropic_api_key: SecretStr | None = None
    # Eval-only: the `paraphrase` step (ADR-030). Never used by a served step.
    openai_api_key: SecretStr | None = None
    aws_region: str | None = None
    aws_profile: str | None = None
    langfuse_host: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    timeout_s: float = 20.0
    max_retries: int = 2
