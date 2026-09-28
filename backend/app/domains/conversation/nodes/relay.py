"""Human mode: the bot stays silent while an agent owns the conversation (D7).

The customer's text is relayed by the API layer (`takeover.py`), not here, so
this node changes nothing. It exists so `_entry` has a place to send a
human-mode turn that ends at `finish` with no reply of its own.
"""

from typing import Any

from app.domains.conversation.graph import GraphState

__all__ = ["relay_to_agent"]


def relay_to_agent(state: GraphState) -> dict[str, Any]:
    """Code only, no LLM call and no tools."""
    return {}
