"""D12 card-selection rules. Hand-built `CardSummary` lists, no FakeBank."""

from typing import Literal

from app.domains.cards.schemas import CardSummary
from app.domains.conversation.flows.card_select import (
    Ask,
    Fallback,
    NoCards,
    Selected,
    load_card_select_policy,
    select_card,
)

_POLICY = load_card_select_policy()


def _card(
    card_id: str,
    kind: Literal["credit", "debit"],
    last4: str,
    status: Literal["Active", "Blocked", "Suspended", "Closed"],
) -> CardSummary:
    return CardSummary(card_id=card_id, kind=kind, last4=last4, status=status, locked=False)


def test_eligibility_and_hints() -> None:
    # One eligible card (a Closed card sits alongside it) -> used directly,
    # and the Closed card never reaches the options.
    single = [
        _card("PRD-CRED0001", "credit", "6475", "Active"),
        _card("PRD-DEBT0002", "debit", "1203", "Closed"),
    ]
    outcome = select_card(single, hint=None, failures=0, policy=_POLICY, language="es")
    assert outcome == Selected(card_id="PRD-CRED0001")

    # Several eligible cards, no hint -> ask; the Closed card is excluded from
    # the options text.
    multi = [
        _card("PRD-CRED0001", "credit", "6475", "Active"),
        _card("PRD-DEBT0002", "debit", "1203", "Blocked"),
        _card("PRD-DEBT0003", "debit", "9001", "Closed"),
    ]
    ask = select_card(multi, hint=None, failures=0, policy=_POLICY, language="es")
    assert isinstance(ask, Ask)
    assert {c.card_id for c in ask.options} == {"PRD-CRED0001", "PRD-DEBT0002"}
    assert ask.card_options == "Crédito •••• 6475 · Activa\nDébito •••• 1203 · Bloqueada"
    assert ask.failures == 0

    # A "credit" hint resolves uniquely among several eligible cards.
    resolved_kind = select_card(multi, hint="credit", failures=0, policy=_POLICY, language="es")
    assert resolved_kind == Selected(card_id="PRD-CRED0001")

    # A "last4:NNNN" hint resolves uniquely too.
    resolved_last4 = select_card(
        multi, hint="last4:1203", failures=0, policy=_POLICY, language="es"
    )
    assert resolved_last4 == Selected(card_id="PRD-DEBT0002")

    # A hint matching only a Closed card still resolves to it (D12): the
    # eligibility filter never applies to hint resolution.
    resolved_closed = select_card(
        multi, hint="last4:9001", failures=0, policy=_POLICY, language="es"
    )
    assert resolved_closed == Selected(card_id="PRD-DEBT0003")

    # An ambiguous hint (two debit cards) asks again with failures + 1, then
    # a second ambiguous hint exhausts clarification -> fallback.
    two_debits = [
        _card("PRD-DEBT0002", "debit", "1203", "Blocked"),
        _card("PRD-DEBT0003", "debit", "9001", "Active"),
    ]
    first_try = select_card(two_debits, hint="debit", failures=0, policy=_POLICY, language="es")
    assert first_try == Ask(
        options=tuple(two_debits),
        card_options="Débito •••• 1203 · Bloqueada\nDébito •••• 9001 · Activa",
        failures=1,
    )
    second_try = select_card(two_debits, hint="debit", failures=1, policy=_POLICY, language="es")
    assert second_try == Fallback()

    # No hint and no eligible card at all (every card Closed) -> NoCards,
    # distinct from Fallback (clarification was never attempted).
    all_closed = [_card("PRD-DEBT0002", "debit", "1203", "Closed")]
    no_cards = select_card(all_closed, hint=None, failures=0, policy=_POLICY, language="es")
    assert no_cards == NoCards()


def test_r1_focus_hint_never_crosses_customer() -> None:
    mine = [
        _card("PRD-MINE0001", "credit", "6475", "Active"),
        _card("PRD-MINE0002", "debit", "1203", "Active"),
    ]
    # A focus id from another customer is not in this session's list -> picker,
    # no failure counted, and the foreign id never shows up.
    foreign = select_card(
        mine, hint="focus", failures=0, policy=_POLICY, language="es", focus_card_id="PRD-OTHER9999"
    )
    assert isinstance(foreign, Ask)
    assert foreign.failures == 0
    assert "PRD-OTHER9999" not in {c.card_id for c in foreign.options}

    # A focus id that is in the list resolves to it.
    own = select_card(
        mine, hint="focus", failures=0, policy=_POLICY, language="es", focus_card_id="PRD-MINE0002"
    )
    assert own == Selected(card_id="PRD-MINE0002")


def test_picker_labels_locked_active_card_as_locked() -> None:
    cards = [
        CardSummary(
            card_id="PRD-CRED0001", kind="credit", last4="4503", status="Active", locked=True
        ),
        _card("PRD-DEBT0002", "debit", "1203", "Active"),
    ]
    ask = select_card(cards, hint=None, failures=0, policy=_POLICY, language="es")
    assert isinstance(ask, Ask)
    assert "•••• 4503 · Bloqueada temporalmente" in ask.card_options
    assert "•••• 4503 · Activa" not in ask.card_options
