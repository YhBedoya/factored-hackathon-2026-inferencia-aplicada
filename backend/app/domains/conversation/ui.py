"""UI events the graph emits alongside `reply` (`04` §3, §7, D2-K).

`UIEvent` is a discriminated union of push payloads a flow appends to the
graph-local `ui` channel (`graph.py`, D16) so the frontend can render a
confirmation card or an OTP prompt without the LLM ever writing money, dates
or a card mask itself (R4): `ConfirmStepView.facts` carries only pre-formatted
`Fact`s built in code. `card_picker`, `transaction_list` and `handoff_banner`
are not defined here -- they arrive with the cards that emit them.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.conversation.state import Fact

__all__ = [
    "ConfirmEvent",
    "ConfirmPayload",
    "ConfirmStepView",
    "OtpRequiredEvent",
    "OtpRequiredPayload",
    "UIEvent",
]


class ConfirmStepView(BaseModel):
    """One plan step as shown to the customer before confirmation (`04` §7)."""

    model_config = ConfigDict(frozen=True)

    tool: str
    summary_key: str
    facts: list[Fact]


class ConfirmPayload(BaseModel):
    """`ui.confirm` payload: the plan's token and its steps (D15)."""

    model_config = ConfigDict(frozen=True)

    token_id: str
    steps: list[ConfirmStepView]


class OtpRequiredPayload(BaseModel):
    """`ui.otp_required` payload: the action waiting on step-up (D15)."""

    model_config = ConfigDict(frozen=True)

    tool: str


class ConfirmEvent(BaseModel):
    """Push event asking the customer to confirm or cancel a plan (D15)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["confirm"]
    payload: ConfirmPayload


class OtpRequiredEvent(BaseModel):
    """Push event asking the customer to complete step-up first (D15, ADR-027)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["otp_required"]
    payload: OtpRequiredPayload


UIEvent = Annotated[ConfirmEvent | OtpRequiredEvent, Field(discriminator="kind")]
