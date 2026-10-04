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
`transaction_list` carries the picker for `unrecognized_charge`'s candidate
transactions (`TxOption.label` is the code-formatted merchant/money/date/mask
string, D4-B D13) and for `decline_explain`'s single-pick offer (D5-B D2-D3):
`multi` tells the frontend which selection mode to render, so it never has to
infer it from `len(options)`. `handoff_banner` (D4-A) announces the transfer to a
person; on the fraud path it also carries the case ids
`disputes.create_claim` returned (D4-B D16). `mode` and `message` payloads
are the non-`ui` SSE events the runner publishes.
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
    "TransactionListEvent",
    "TransactionListPayload",
    "TxOption",
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
    # Agent plans are button-only and read "Acepto / No acepto" (D12).
    labels: Literal["confirm_cancel", "accept_decline"] = "confirm_cancel"


class OtpRequiredPayload(BaseModel):
    """`ui.otp_required` payload: the action waiting on step-up (D15).

    Every OTP pause sends `cancellable=true` (S2 D31): one modal, with Cancel.
    """

    model_config = ConfigDict(frozen=True)

    tool: str
    cancellable: bool = True


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
    card_id: str | None = None


class CardPickerPayload(BaseModel):
    """`ui.card_picker` payload: the masked card options an `Ask` built (D3)."""

    model_config = ConfigDict(frozen=True)

    options: list[PickerOption]
    multi: bool = False


class CardPickerEvent(BaseModel):
    """Push event: several cards still fit, so the turn also offers a picker (D3)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["card_picker"]
    payload: CardPickerPayload


class QuickRepliesPayload(BaseModel):
    """`ui.quick_replies` payload: a fixed slot's options (D4).

    `slot` is a closed literal, not a free string, because the frontend keys
    its rendering off it: `"block_kind"` is the lock-vs-block clarification,
    `"abstain"` ADR-026's closest action, and `"next_step"` (D5-B D7) is
    `decline_explain`'s self-service replacement offer -- tapping its one
    option sends the label as text, so NLU routes it as `replacement_request`.
    """

    model_config = ConfigDict(frozen=True)

    slot: Literal["block_kind", "abstain", "next_step"]
    options: list[PickerOption]


class QuickRepliesEvent(BaseModel):
    """Push event: a fixed-choice clarification also offers quick-reply chips (D4)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["quick_replies"]
    payload: QuickRepliesPayload


class TxOption(BaseModel):
    """One offered transaction: its id and its code-formatted label (R4, D13)."""

    model_config = ConfigDict(frozen=True)

    tx_id: str
    label: str


class TransactionListPayload(BaseModel):
    """`ui.transaction_list` payload: the candidates a flow offered (D4-B
    D12-D13; D5-B D2-D3). `multi` has no default -- each flow states its own
    selection mode rather than relying on one: `unrecognized_charge` always
    passes `True` (the customer can pick more than one), `decline_explain`
    always passes `False` (exactly one decline gets explained per turn).
    """

    model_config = ConfigDict(frozen=True)

    options: list[TxOption]
    multi: bool


class TransactionListEvent(BaseModel):
    """Push event: the pick step of `unrecognized_charge` (D7, D12)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["transaction_list"]
    payload: TransactionListPayload


class HandoffBannerPayload(BaseModel):
    """`ui.handoff_banner` payload: reference and queue label built in code (R4).

    `case_ids` lists the claims the conversation's verified
    `disputes.create_claim` results opened before the handoff (D4-B D16);
    it is empty for every other handoff.
    """

    model_config = ConfigDict(frozen=True)

    handoff_id: str
    reference: str
    queue: Queue
    queue_label: str
    case_ids: list[str] = Field(default_factory=list)


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
    | TransactionListEvent
    | HandoffBannerEvent,
    Field(discriminator="kind"),
]
