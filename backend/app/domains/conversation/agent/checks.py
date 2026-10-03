"""Code checks on the agent's turn: reply grounding, placeholder fill, claims (D19, D18, D16)."""

import re

from app.domains.conversation import fact_values
from app.domains.conversation.agent.refs import TurnRefs
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.nodes.compose import _PLACEHOLDER, draft_problem
from app.domains.conversation.templates import Language

__all__ = ["claims_problem", "fill_reply", "reply_problem"]


def reply_problem(turn: AgentTurn, refs: TurnRefs, language: Language) -> str | None:
    """Why the reply fails the compose grounding check; `None` when it passes (D19)."""
    return draft_problem(turn.reply, refs.keys(), language)


# The mask code emits is already "•••• 1234". Cardy sometimes writes its own bullets before
# the placeholder, which would show "•••• •••• 1234"; any bullets in front of a mask go.
_DOUBLE_MASK = re.compile(r"(?:•+\s*)+(?=•{4} \d{4})")


def fill_reply(reply: str, refs: TurnRefs) -> str:
    """Substitute every placeholder with its code-formatted value (R4).

    Call only after `reply_problem` passed, so every placeholder is a known reference.
    """
    used = [refs.value(name) for name in _PLACEHOLDER.findall(reply)]
    fact_values.record(*used)
    filled = _PLACEHOLDER.sub(lambda m: refs.value(m.group(1)), reply)
    return _DOUBLE_MASK.sub("", filled)


def claims_problem(turn: AgentTurn, verified: list[int]) -> str | None:
    """A reason when the steps the reply reports as done differ from the verified ones (D16)."""
    if sorted(set(turn.reported_done)) != sorted(set(verified)):
        return "reported_done no coincide con los pasos verificados"
    return None
