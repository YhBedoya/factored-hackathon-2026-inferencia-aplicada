"""The agent's final output for one turn, and its control exception (D16, D7)."""

from typing import Literal

from pydantic import BaseModel, model_validator

from app.domains.conversation.schemas import Intent

__all__ = ["MAX_ROUNDS", "AgentTurn", "PassToFlow"]

# Tool rounds the loop may spend before `LLMRoundCap` (D3).
MAX_ROUNDS = 6


class PassToFlow(Exception):
    """Raised by the `pass_to_flow` tool: the existing pipeline takes this turn (D7)."""


class AgentTurn(BaseModel):
    language: Literal["es", "pt", "mixed", "other"]
    intents: list[Intent]  # existing catalog, message order
    outcome: Literal["answered", "asked", "redirected"]
    awaiting_slot: Literal["card_hint", "block_kind", "criterion"] | None
    reported_done: list[int]  # plan step indexes the reply reports as done (D16)
    reply: str  # with {reference} placeholders only

    @model_validator(mode="after")
    def _slot_matches_outcome(self) -> "AgentTurn":
        if (self.outcome == "asked") != (self.awaiting_slot is not None):
            raise ValueError("awaiting_slot must be set exactly when outcome is 'asked'")
        return self
