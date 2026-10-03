"""D1/D11: `card_info` and `card_block` read the card's state first and offer the
next step; a verified lock ends with the closing question (tests 6, 7, 11).

Fake LLM only; turns driven with `asyncio.run`, same shape as `test_block_flows.py`.
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.domains.cards.schemas import CardSummary
from app.domains.conversation.flows.card_select import (
    Ask,
    Selected,
    block_candidate_ids,
    load_card_select_policy,
    select_card,
)
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import Intent, NLUResult, NLUSlots
from app.domains.conversation.templates import Language, TemplateKind, template_variants
from app.domains.localization import status_label
from tests.conftest import ScriptedLLM, make_session

_DRAFT = {
    "es": ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} esta {status}."),
    "pt": ComposeDraft(text="Seu cartao {card_kind} {card_mask} esta {status}."),
}


def _nlu(language: Language, intent: Intent | None, **slots: Any) -> NLUResult:
    return NLUResult(
        language=language,
        intents=[intent] if intent else [],
        status="clear",
        slots=NLUSlots(**slots),
    )


def _has_variant(reply: str, kind: TemplateKind, language: Language, **values: str) -> bool:
    return any(v.format(**values) in reply for v in template_variants(kind, language))


async def _ui(session: Any) -> list[Any]:
    return (await session.graph.aget_state(session.config)).values["ui"]


@pytest.mark.parametrize("language", ["es", "pt"])
def test_focus_already_blocked_offers_replacement(fakebank_dir: Path, language: Language) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    _nlu(language, "card_status", card_hint="last4:6475"),
                    _nlu(language, "card_block", card_hint="focus"),
                ],
                "compose": [_DRAFT[language]],
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        session.overlay.blocked.add("PRD-TFM1CRED0001")

        await run_turn(session.graph, "estado de mi credito", config=session.config)
        reply, debug = await run_turn(session.graph, "quiero bloquearla", config=session.config)

        assert _has_variant(
            reply,
            "already_in_state",
            language,
            card_last4="6475",
            state=status_label("Blocked", language),
        )
        assert _has_variant(reply, "offer_replacement", language, card_last4="6475")
        assert debug.pending == "replacement.offer_replacement"
        assert "card_picker" not in debug.ui
        assert not any(
            e.kind == "quick_replies" and e.payload.slot == "block_kind" for e in await _ui(session)
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    ("customer", "locked", "hint", "kind", "pending"),
    [
        ("CLI-TFMULTI00001", True, "last4:6475", "offer_unlock", "card_unlock.offer_unlock"),
        ("CLI-TFBLOCKD0003", False, None, "offer_human", None),
        ("CLI-TFMULTI00001", False, "last4:9001", "offer_human", None),
    ],
    ids=["customer_lock", "bank_side", "closed"],
)
def test_status_offer_by_origin(
    fakebank_dir: Path,
    customer: str,
    locked: bool,
    hint: str | None,
    kind: TemplateKind,
    pending: str | None,
) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {"nlu": [_nlu("es", "card_status", card_hint=hint)], "compose": [_DRAFT["es"]]}
        )
        session = make_session(customer, fakebank_dir, llm)
        if locked:
            session.overlay.locked.add("PRD-TFM1CRED0001")

        reply, debug = await run_turn(session.graph, "estado de mi tarjeta", config=session.config)

        assert _has_variant(reply, kind, "es")
        assert debug.pending == pending
        if locked:
            # The status line and the unlock offer must agree: not "Activa".
            assert "Activa" not in reply
            assert "Bloqueada temporalmente" in reply
        chips = [e for e in await _ui(session) if e.kind == "quick_replies"]
        if kind == "offer_human":
            assert chips[0].payload.slot == "next_step"
            assert len(chips[0].payload.options) == 1
        else:
            assert not chips

    asyncio.run(run())


def test_closing_after_action_lock(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    _nlu("es", "card_block", card_hint="credit", block_kind="temporary_lock"),
                    _nlu("es", "affirm"),
                    _nlu("es", "thanks_close"),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)

        await run_turn(session.graph, "bloquea mi credito", config=session.config)
        reply, debug = await run_turn(session.graph, "si", config=session.config)

        assert "PRD-TFM1CRED0001" in session.overlay.locked
        assert any(v in reply for v in template_variants("closing_generic", "es"))
        assert debug.pending == "smalltalk.anything_else"
        chips = [e for e in await _ui(session) if e.kind == "quick_replies"]
        assert not [e for e in chips if e.payload.slot == "closing"]

        _reply, debug3 = await run_turn(session.graph, "no, gracias", config=session.config)
        assert "conversation_closed" in debug3.ui

    asyncio.run(run())


@pytest.mark.parametrize("language", ["es", "pt"])
def test_block_picker_lists_only_unlocked_active_cards(language: Language) -> None:
    cards = [
        CardSummary(card_id="A1", kind="credit", last4="1111", status="Active", locked=False),
        CardSummary(card_id="A2", kind="debit", last4="2222", status="Active", locked=False),
        CardSummary(card_id="L3", kind="debit", last4="3333", status="Active", locked=True),
        CardSummary(card_id="B4", kind="credit", last4="4444", status="Blocked", locked=False),
    ]
    policy = load_card_select_policy()
    outcome = select_card(
        cards, None, 0, policy, language, candidate_ids=block_candidate_ids(cards, policy)
    )
    assert isinstance(outcome, Ask)
    assert [c.card_id for c in outcome.options] == ["A1", "A2"]
    # A hint still resolves over every card (D12): naming the blocked one answers.
    named = select_card(
        cards, "last4:4444", 0, policy, language, candidate_ids=block_candidate_ids(cards, policy)
    )
    assert isinstance(named, Selected)
    assert named.card_id == "B4"


def test_block_single_eligible_card_skips_picker(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM({"nlu": [_nlu("es", "card_block")]})
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
        session.overlay.locked.add("PRD-TFM1CRED0001")

        reply, debug = await run_turn(
            session.graph, "quiero bloquear una tarjeta", config=session.config
        )

        assert debug.pending == "card_block.block_kind"
        assert "card_picker" not in debug.ui
        assert any(v in reply for v in template_variants("clarify_lock_vs_block", "es"))

    asyncio.run(run())


def test_block_no_eligible_card_closes(fakebank_dir: Path) -> None:
    async def run() -> None:
        llm = ScriptedLLM({"nlu": [_nlu("es", "card_block")]})
        session = make_session("CLI-TFBLOCKD0003", fakebank_dir, llm)

        reply, debug = await run_turn(
            session.graph, "quiero bloquear una tarjeta", config=session.config
        )

        assert _has_variant(reply, "block_none_eligible", "es")
        assert _has_variant(reply, "closing_generic", "es")
        assert debug.pending == "smalltalk.anything_else"
        chips = [e for e in await _ui(session) if e.kind == "quick_replies"]
        assert not [e for e in chips if e.payload.slot == "closing"]

    asyncio.run(run())
