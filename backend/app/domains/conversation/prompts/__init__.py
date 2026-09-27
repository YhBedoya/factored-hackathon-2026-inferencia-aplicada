"""Loader for versioned prompt files (`docs/specs/d1-b-agent-sandbox.md` "Contracts").

Prompts are plain Markdown, one file per `(name, version)`, named
`<name>@v<version>.md`. Any wording change bumps the version -- a new file,
never an in-place edit -- so `PromptRef.label` in the `llm.call` log line
always points at the exact text a call used (R7). The file text itself is
never logged.
"""

from pathlib import Path

from app.core.llm import PromptRef

__all__ = ["load_prompt"]

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(ref: PromptRef) -> str:
    """Read `prompts/<name>@v<version>.md` for `ref` (e.g. `nlu@v1.md`)."""
    path = _PROMPTS_DIR / f"{ref.label}.md"
    return path.read_text(encoding="utf-8")
