"""UI events the graph emits alongside `reply` (`04` §3, §7, D2-K).

`UIEvent` is a discriminated union of push payloads a flow appends to the
graph-local `ui` channel (`graph.py`, D16) so the frontend can render a
confirmation card or an OTP prompt without the LLM ever writing money, dates
or a card mask itself (R4): `ConfirmStepView.facts` carries only pre-formatted
`Fact`s built in code. `conversation_closed` tells the caller the customer said goodbye and the
conversation ended (the API marks it closed; the next message needs a new
conversation). `card_picker` carries the masked card options an `Ask` outcome
already built (`flows/card_select.py`'s `card_picker_event`, D3); `quick_replies`
carries the fixed lock-vs-block labels `card_block` emits while clarifying
(D4). Both `PickerOption.label`s are formatted in code, never by the LLM (R4).
`handoff_banner` (D4-A) announces the transfer to a person. `mode` and
`message` payloads are the non-`ui` SSE events the runner publishes. `transaction_list`
is not defined here -- it arrives with the card that emits it.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.conversation.state import Fact
from app.domains.localization.format import Queue

__all__ = [
    "CardPickerEvent",
    "CardPickerPayload",
    "ConfirmEvent",
    "ConfirmPayload",
    "ConfirmStepView",
    "ConversationClosedEvent",
    "ConversationClosedPayload",
    "HandoffBannerEvent",
    "HandoffBannerPayload",
    "MessagePayload",
    "ModePayload",
    "OtpRequiredEvent",
    "OtpRequiredPayload",
    "PickerOption",
    "QuickRepliesEvent",
    "QuickRepliesPayload",
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


class ConversationClosedPayload(BaseModel):
    """`ui.conversation_closed` payload: nothing to carry, the kind is the signal."""

    model_config = ConfigDict(frozen=True)


class ConversationClosedEvent(BaseModel):
    """Push event: the customer closed the conversation after `anything_else`."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["conversation_closed"]
    payload: ConversationClosedPayload = ConversationClosedPayload()


class PickerOption(BaseModel):
    """One clickable option: its code-formatted label, nothing else (R4)."""

    model_config = ConfigDict(frozen=True)

    label: str


class CardPickerPayload(BaseModel):
    """`ui.card_picker` payload: the masked card options an `Ask` built (D3)."""

    model_config = ConfigDict(frozen=True)

    options: list[PickerOption]


class CardPickerEvent(BaseModel):
    """Push event: several cards still fit, so the turn also offers a picker (D3)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["card_picker"]
    payload: CardPickerPayload


class QuickRepliesPayload(BaseModel):
    """`ui.quick_replies` payload: a fixed slot's options (D4).

    `slot` is a closed literal, not a free string, because the frontend keys
    its rendering off it (today only the lock-vs-block clarification).
    """

    model_config = ConfigDict(frozen=True)

    slot: Literal["block_kind", "abstain"]
    options: list[PickerOption]


class QuickRepliesEvent(BaseModel):
    """Push event: a fixed-choice clarification also offers quick-reply chips (D4)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["quick_replies"]
    payload: QuickRepliesPayload


class HandoffBannerPayload(BaseModel):
    """`ui.handoff_banner` payload: reference and queue label built in code (R4)."""

    model_config = ConfigDict(frozen=True)

    handoff_id: str
    reference: str
    queue: Queue
    queue_label: str


class HandoffBannerEvent(BaseModel):
    """Push event: the conversation was handed to a person."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["handoff_banner"]
    payload: HandoffBannerPayload


class ModePayload(BaseModel):
    """`mode` SSE payload: who answers (`agent_display_name` once claimed)."""

    model_config = ConfigDict(frozen=True)

    mode: Literal["bot", "human"]
    agent_display_name: str | None


class MessagePayload(BaseModel):
    """`message` SSE payload; `customer` is published only in human mode."""

    model_config = ConfigDict(frozen=True)

    role: Literal["bot", "customer", "agent", "system"]
    text: str
    sources: list[str]
    agent_display_name: str | None = None


UIEvent = Annotated[
    ConfirmEvent
    | OtpRequiredEvent
    | ConversationClosedEvent
    | CardPickerEvent
    | QuickRepliesEvent
    | HandoffBannerEvent,
    Field(discriminator="kind"),
]
