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
from app.domains.localization import kind_label, mask_card, status_label

__all__ = [
    "Ask",
    "CardSelectPolicy",
    "CardStatusPolicy",
    "Fallback",
    "NoCards",
    "SelectOutcome",
    "Selected",
    "load_card_select_policy",
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


class CardSelectPolicy(BaseModel):
    """`policies/card_select.yaml`, validated (`04` §5, R8).

    `provenance` and `version` have no default, so a file missing either one
    fails `model_validate` instead of silently running with no eligibility
    rule.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance: str
    version: int
    card_status: CardStatusPolicy


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
    lines = [
        f"{kind_label(card.kind, language)} {mask_card(card.last4)}"
        f" · {status_label(card.status, language)}"
        for card in cards
    ]
    return "\n".join(lines)


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
) -> SelectOutcome:
    """Pick a card, ask again, or give up, exactly per D12.

    `cards` is `cards.list_cards()`'s full result (every status). `failures`
    is the turn's `clarification_failures` coming in; `Ask.failures` and the
    `Fallback` case are what the caller writes back. `NoCards` is the no-hint,
    zero-eligible-cards case (all Closed, or no cards at all).
    """
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
