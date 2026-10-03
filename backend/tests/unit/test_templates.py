"""Template variants (naturalidad-cardy D12, D13): tests 13 and 8."""

import re
from typing import get_args

from app.domains.conversation.flows.card_select import Ask, AskAction, ask_which_card_text
from app.domains.conversation.templates import (
    Language,
    TemplateKind,
    template_variants,
)

_LANGUAGES: tuple[Language, ...] = ("es", "pt")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")

_VARIED: tuple[TemplateKind, ...] = (
    "ask_which_card_status",
    "ask_which_card_balance",
    "ask_which_card_block",
    "ask_which_card_unlock",
    "ask_which_card_replacement",
    "ask_which_card_dispute",
    "ask_which_card_decline",
    "decline_pick_ask",
    "tx_search_pick_ask",
    "tx_explain_pick_ask",
    "dispute_transactions_prompt",
    "clarify_lock_vs_block",
    "action_confirm",
    "action_done",
    "action_done_noref",
    "action_cancelled",
    "already_in_state",
    "offer_replacement",
    "offer_unlock",
    "offer_human",
    "replacement_declined",
    "replacement_not_eligible",
    "replacement_needs_block",
    "new_card_not_available",
    "closing_suggest_transaction_search",
    "closing_suggest_unrecognized_charge",
    "closing_generic",
    "greeting_again",
    "greeting_again_plain",
    "abstain_fallback",
    "anything_else",
    "ask_what_else",
    "farewell",
    "fallback",
    "tool_error",
    "failure_handoff",
    "failure_handoff_after_action",
    "clarification_exhausted",
    "nothing_pending",
    "pending_reminder",
    "injection_suspected",
    "unsupported_intent",
    "escalation_handoff",
    "no_cards",
)


def test_every_varied_kind_has_three_clean_variants() -> None:
    """Test 13: at least 3 variants per language, no digit, one placeholder set."""
    placeholder_sets: dict[TemplateKind, set[frozenset[str]]] = {}
    for kind in _VARIED:
        for language in _LANGUAGES:
            variants = template_variants(kind, language)
            assert len(variants) >= 3, (kind, language)
            for text in variants:
                assert not re.search(r"\d", _PLACEHOLDER.sub("", text)), (kind, language, text)
                placeholder_sets.setdefault(kind, set()).add(frozenset(_PLACEHOLDER.findall(text)))
        assert len(placeholder_sets[kind]) == 1, kind


def test_no_ask_which_card_variant_carries_the_options() -> None:
    """Test 8 (R3): the card options never come from a template; the picker shows them."""
    kinds: list[TemplateKind] = [
        k for k in get_args(TemplateKind) if k.startswith("ask_which_card_")
    ]
    kinds += [
        "decline_pick_ask",
        "tx_search_pick_ask",
        "tx_explain_pick_ask",
        "dispute_transactions_prompt",
    ]
    for kind in kinds:
        for language in _LANGUAGES:
            for text in template_variants(kind, language):
                assert "{card_options}" not in text, (kind, language)

    options = "Crédito •••• 6475 · Activa\nDébito •••• 1203 · Activa"
    ask = Ask(options=(), card_options=options, failures=0)
    for action in get_args(AskAction):
        for language in _LANGUAGES:
            text = ask_which_card_text(action, ask, language)
            assert all(line not in text for line in options.split("\n")), (action, language)


def test_no_procedural_closing_in_templates() -> None:
    """personalidad-cardy: no variant of any kind announces the conversation as over."""
    for kind in get_args(TemplateKind):
        for language in _LANGUAGES:
            for text in template_variants(kind, language):
                lowered = text.lower()
                assert "terminada" not in lowered, (kind, language)
                assert "encerrar a conversa" not in lowered, (kind, language)
