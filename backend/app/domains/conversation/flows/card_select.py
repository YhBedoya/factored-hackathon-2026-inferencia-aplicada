"""`card_select`, the shared sub-flow every card-scoped intent runs first.

Pure card-selection logic: no LLM call and no I/O besides reading the policy
YAML (D12, `02` §4.1). Card options are formatted here, never by the LLM
(R4), through `app.domains.localization`. Eligibility (which statuses are
offered when there's no hint) lives in `policies/card_select.yaml`, not as a
code constant (R8); a hint is still resolved over every card regardless of
eligibility, per D12.

This is the first policy-file loader in the repo, so it sets the pattern:
a frozen, `extra="forbid"` pydantic model whose required `provenance` and
`version` fields make a header-less file fail to load (R8).
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from app.domains.cards.schemas import CardSummary
from app.domains.conversation.fact_values import record
from app.domains.conversation.templates import TemplateKind, get_template
from app.domains.conversation.ui import CardPickerEvent, CardPickerPayload, PickerOption
from app.domains.localization import kind_label, mask_card, status_label

__all__ = [
    "Ask",
    "CardBlockPolicy",
    "CardSelectPolicy",
    "CardStatusPolicy",
    "Fallback",
    "NoCards",
    "ReplacementPolicy",
    "SelectOutcome",
    "Selected",
    "ask_which_card_text",
    "block_candidate_ids",
    "card_picker_event",
    "load_card_select_policy",
    "next_step_offer_kind",
    "select_card",
]

Language = Literal["es", "pt"]
CardStatus = Literal["Active", "Blocked", "Suspended", "Closed"]

# `backend/app/domains/conversation/flows/card_select.py` -> repo root is five
# parents up (flows, conversation, domains, app, backend).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_POLICY_PATH = _REPO_ROOT / "policies" / "card_select.yaml"


class CardStatusPolicy(BaseModel):
    """The `card_status` block of `policies/card_select.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible_statuses: list[CardStatus]


class CardBlockPolicy(BaseModel):
    """The `card_block` block: which cards the block picker lists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible_statuses: list[CardStatus]
    exclude_locked: bool


OriginKind = Literal["customer_block", "customer_lock", "bank_side", "suspended", "closed"]
OfferKind = Literal["replacement", "unlock", "human"]


class ReplacementPolicy(BaseModel):
    """The `replacement` block: which block origins make a card replaceable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible_origins: list[Literal["customer_block"]]


class CardSelectPolicy(BaseModel):
    """`policies/card_select.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no eligibility
    rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: Literal["team-generated-synthetic"]
    version: int
    card_status: CardStatusPolicy
    card_block: CardBlockPolicy
    replacement: ReplacementPolicy
    next_step_offer: dict[OriginKind, OfferKind]


class Selected(BaseModel):
    """Exactly one card resolved: either the only eligible card, or a hint match."""

    model_config = ConfigDict(frozen=True)

    card_id: str


class Ask(BaseModel):
    """Several cards still fit; the turn asks again and shows masked options."""

    model_config = ConfigDict(frozen=True)

    options: tuple[CardSummary, ...]
    """The eligible cards behind `card_options`, for the caller's own facts."""
    card_options: str
    """Newline-joined masked options, e.g. `"Crédito •••• 6475 · Activa"` (`02` §4.1)."""
    failures: int


class Fallback(BaseModel):
    """Clarification is exhausted (`clarification_failures` reached 2, D12/D15)."""

    model_config = ConfigDict(frozen=True)


class NoCards(BaseModel):
    """No hint, and no eligible card to pick from (all Closed, or none at all).

    Distinct from `Fallback`: clarification was never attempted, there's
    simply nothing to select or ask about. The caller decides the reply
    (T8/T10).
    """

    model_config = ConfigDict(frozen=True)


SelectOutcome = Selected | Ask | Fallback | NoCards

_MAX_CLARIFICATION_FAILURES = 2

AskAction = Literal["status", "balance", "block", "unlock", "replacement"]

_ASK_TEMPLATES: dict[AskAction, TemplateKind] = {
    "status": "ask_which_card_status",
    "balance": "ask_which_card_balance",
    "block": "ask_which_card_block",
    "unlock": "ask_which_card_unlock",
    "replacement": "ask_which_card_replacement",
}


def ask_which_card_text(action: AskAction, outcome: "Ask", language: Language) -> str:
    """The fixed "which card do you want to <action>?" question plus the
    masked options (D12, R4). A template, not a `compose` draft, so the
    question always names the action the customer asked for.
    """
    record(outcome.card_options)
    return get_template(_ASK_TEMPLATES[action], language).replace(
        "{card_options}", outcome.card_options
    )


def card_picker_event(outcome: Ask) -> CardPickerEvent:
    """`ui.card_picker` for an `Ask` outcome: one `PickerOption` per line of
    `outcome.card_options`, the masked options already formatted in code (D3, R4).
    """
    options = [PickerOption(label=label) for label in outcome.card_options.split("\n")]
    return CardPickerEvent(kind="card_picker", payload=CardPickerPayload(options=options))


def block_candidate_ids(cards: list[CardSummary], policy: CardSelectPolicy) -> frozenset[str]:
    """The cards `card_block`'s picker may list (R8: the rule is in the policy)."""
    rule = policy.card_block
    return frozenset(
        c.card_id
        for c in cards
        if c.status in rule.eligible_statuses and not (rule.exclude_locked and c.locked)
    )


def load_card_select_policy(path: Path | None = None) -> CardSelectPolicy:
    """Load and validate `policies/card_select.yaml` (R8).

    `path` defaults to `<repo root>/policies/card_select.yaml`; tests may pass
    another path to check the rejection rule without touching the real file.
    """
    target = path if path is not None else _DEFAULT_POLICY_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    return CardSelectPolicy.model_validate(raw)


def _build_card_options(cards: tuple[CardSummary, ...], language: Language) -> str:
    """`"Crédito •••• 6475 · Activa"` per option, one per line (`02` §4.1)."""
    # A temporary lock isn't a product status: an Active+locked card gets the
    # "Locked" label, as `card_info` does, so the picker never says "Activa".
    lines = []
    for card in cards:
        status = "Locked" if card.locked and card.status == "Active" else card.status
        lines.append(
            f"{kind_label(card.kind, language)} {mask_card(card.last4)}"
            f" · {status_label(status, language)}"
        )
    return "\n".join(lines)


def next_step_offer_kind(
    policy: CardSelectPolicy,
    *,
    status: CardStatus,
    origin_kind: str,
) -> OfferKind | None:
    """Which next step to offer for a card (D1): status first, then block origin.

    Closed and Suspended cards go to a person whatever the origin; otherwise the
    origin picks the entry. An unknown origin (e.g. `none`) offers nothing.
    """
    if status == "Closed":
        return policy.next_step_offer["closed"]
    if status == "Suspended":
        return policy.next_step_offer["suspended"]
    if origin_kind == "customer_block":
        return policy.next_step_offer["customer_block"]
    if origin_kind == "customer_lock":
        return policy.next_step_offer["customer_lock"]
    if origin_kind == "bank_side":
        return policy.next_step_offer["bank_side"]
    return None


def _resolve_hint(cards: list[CardSummary], hint: str) -> CardSummary | None:
    """Resolve a slot hint over **every** card, Closed included (D12).

    Returns the single matching card, or `None` if the hint matches zero or
    more than one card (both count as "still ambiguous").
    """
    if hint == "credit":
        matches = [c for c in cards if c.kind == "credit"]
    elif hint == "debit":
        matches = [c for c in cards if c.kind == "debit"]
    elif hint.startswith("last4:"):
        last4 = hint.removeprefix("last4:")
        matches = [c for c in cards if c.last4 == last4]
    else:
        matches = []
    return matches[0] if len(matches) == 1 else None


def select_card(
    cards: list[CardSummary],
    hint: str | None,
    failures: int,
    policy: CardSelectPolicy,
    language: Language,
    *,
    focus_card_id: str | None = None,
    candidate_ids: frozenset[str] | None = None,
) -> SelectOutcome:
    """Pick a card, ask again, or give up, exactly per D12.

    `cards` is `cards.list_cards()`'s full result (every status). `failures`
    is the turn's `clarification_failures` coming in; `Ask.failures` and the
    `Fallback` case are what the caller writes back. `NoCards` is the no-hint,
    zero-eligible-cards case (all Closed, or no cards at all).

    `hint == "focus"` resolves to `focus_card_id` only if that id is in `cards`
    (R1: a foreign id never matches); otherwise it acts as no hint and counts no
    failure (D9). `candidate_ids` replaces the status eligibility for the no-hint
    branch only; a real hint still resolves over every card (D12).
    """
    if hint == "focus":
        if focus_card_id is not None and any(c.card_id == focus_card_id for c in cards):
            return Selected(card_id=focus_card_id)
        hint = None

    if candidate_ids is not None:
        eligible = tuple(c for c in cards if c.card_id in candidate_ids)
    else:
        eligible = tuple(c for c in cards if c.status in policy.card_status.eligible_statuses)

    if hint is not None:
        match = _resolve_hint(cards, hint)
        if match is not None:
            return Selected(card_id=match.card_id)
        new_failures = failures + 1
        if new_failures >= _MAX_CLARIFICATION_FAILURES:
            return Fallback()
        return Ask(
            options=eligible,
            card_options=_build_card_options(eligible, language),
            failures=new_failures,
        )

    if len(eligible) == 1:
        return Selected(card_id=eligible[0].card_id)

    if len(eligible) == 0:
        return NoCards()

    return Ask(
        options=eligible,
        card_options=_build_card_options(eligible, language),
        failures=failures,
    )
