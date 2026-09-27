"""Provider-agnostic LLM access. See `docs/specs/d1-b-agent-sandbox.md` §"Contracts".

Only this package imports an LLM SDK (`langchain_anthropic`, `langchain_aws`);
the import-linter contract enforces it (`06` §2, R7).
"""

from app.core.llm.client import LLMClient, get_llm_client
from app.core.llm.errors import LLMError, LLMInvalidOutput, LLMUnavailable
from app.core.llm.registry import MODEL_REGISTRY, TEMPERATURE, PromptRef, Provider, Step
from app.core.llm.settings import LLMSettings
from app.core.llm.tracing import trace_llm_call

__all__ = [
    "MODEL_REGISTRY",
    "TEMPERATURE",
    "LLMClient",
    "LLMError",
    "LLMInvalidOutput",
    "LLMSettings",
    "LLMUnavailable",
    "PromptRef",
    "Provider",
    "Step",
    "get_llm_client",
    "trace_llm_call",
]
