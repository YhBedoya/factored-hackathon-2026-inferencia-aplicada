"""B1: `card_info` on `balance_due` -- credit, debit and inactive-customer
cases. See the spec's Test list rows for `test_card_info_flows.py`.

Same harness shape as `test_sandbox_conversations.py`'s `_config`: a
compiled graph, a fresh `ToolContext`/`FakeBank` over one TEST FIXTURE
customer, and a `ScriptedLLM` standing in for `nlu`/`compose` (no network,
no write tools needed for a read-only flow). Expected money/date/days text
is built with the same `app.domains.localization`/`policy.min_payment`
functions the flow itself calls, rather than hand-computed, so a test only
pins the wiring (which facts reach `compose`, and in what segment order),
never the formatting math T3/T4 already cover on their own.
"""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.domains.conversation.flows.card_select import load_card_select_policy
from app.domains.conversation.graph import build_graph, run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import Language, get_template
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.localization import (
    format_date,
    format_days,
    format_money,
    kind_label,
    local_today,
    mask_card,
    mxn_estimate,
    status_label,
)
from app.domains.localization.schemas import FxRate
from app.domains.policy.min_payment import load_min_payment_policy, min_payment, next_due_date
from tests.conftest import ScriptedLLM

Country = Literal["MX", "CO", "AR"]

_MIN_PAYMENT_POLICY = load_min_payment_policy()
# The exact USD->MXN row `daily_exchange_rates.csv` carries for 2026-03-12 (T1).
_MX_USD_MXN_FX = FxRate(
    source="USD", target="MXN", rate=Decimal("17.400000"), as_of=date(2026, 3, 12)
)


def _config(ctx: ToolContext, bank_tools: FakeBank, llm: ScriptedLLM, thread_id: str) -> Any:
    return {
        "configurable": {
            "thread_id": thread_id,
            "session": ctx,
            "bank_tools": bank_tools,
            "llm": llm,
        }
    }


def _due_date_text(country: Country) -> str:
    return format_date(next_due_date(local_today(country), _MIN_PAYMENT_POLICY))


def _card_id(bank_tools: FakeBank, kind: Literal["credit", "debit"]) -> str:
    cards = asyncio.run(bank_tools.list_cards())
    return next(c.card_id for c in cards if c.kind == kind)


@pytest.mark.parametrize(
    ("language", "customer_id", "card_hint", "country", "currency", "with_fx", "dpd"),
    [
        ("es", "CLI-TFMULTI00001", "credit", "MX", "USD", True, 0),
        ("pt", "CLI-TFSINGLE0002", None, "CO", "COP", False, 0),
        ("pt", "CLI-TFPASTD00005", None, "AR", "ARS", False, 30),
        ("es", "CLI-TFMULTI00001", None, "MX", "USD", True, 0),
        ("pt", "CLI-TFMULTI00001", None, "MX", "USD", True, 0),
    ],
    ids=["es-mx-fx", "pt-co", "pt-ar-dpd", "es-mx-ask", "pt-mx-ask"],
)
def test_credit_balance_due(
    fakebank_dir: Path,
    language: Language,
    customer_id: str,
    card_hint: str | None,
    country: Country,
    currency: str,
    with_fx: bool,
    dpd: int,
) -> None:
    """B1, step 2: balance, due date, synthetic min payment, available
    credit, the MXN estimate for an MX/USD card, and the `payment_overdue`
    bucket when `days_past_due > 0` (D5, D18).

    The `-ask` cases give no hint on a multi-card customer, so turn 1 is an
    `Ask` that also emits `ui.card_picker` (D3): the test checks its labels
    against the same `kind_label`/`mask_card`/`status_label` code
    `card_select._build_card_options` uses, then turn 2 posts the credit
    option's label as ordinary text (D5) to reach the same balance reply the
    hinted case above already proves.
    """
    ctx = ToolContext(
        customer_id=customer_id,
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    draft_text = "{current_balance} / {due_date} / {min_payment} / {available_credit}"
    if dpd:
        draft_text += " / {payment_overdue}"

    if card_hint is None and customer_id == "CLI-TFMULTI00001":
        nlus = [
            NLUResult(language=language, intents=["balance_due"], status="clear", slots=NLUSlots()),
            NLUResult(
                language=language, intents=[], status="clear", slots=NLUSlots(card_hint="credit")
            ),
        ]
    else:
        nlus = [
            NLUResult(
                language=language,
                intents=["balance_due"],
                status="clear",
                slots=NLUSlots(card_hint=card_hint),
            )
        ]
    llm = ScriptedLLM({"nlu": nlus, "compose": [ComposeDraft(text=draft_text)]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, f"t-balance-{customer_id}-{language}-{card_hint}")

    if len(nlus) == 2:
        _reply1, debug1 = asyncio.run(run_turn(graph, "cuanto debo?", config=config))
        assert debug1.ui == ["card_picker"]

        cards = asyncio.run(bank_tools.list_cards())
        policy = load_card_select_policy()
        eligible = [c for c in cards if c.status in policy.card_status.eligible_statuses]
        expected_labels = [
            f"{kind_label(c.kind, language)} {mask_card(c.last4)}"
            f" · {status_label(c.status, language)}"
            for c in eligible
        ]
        state = asyncio.run(graph.aget_state(config))
        picker = state.values["ui"][0]
        assert [option.label for option in picker.payload.options] == expected_labels

        credit_index = next(i for i, c in enumerate(eligible) if c.kind == "credit")
        reply, debug = asyncio.run(run_turn(graph, expected_labels[credit_index], config=config))
    else:
        reply, debug = asyncio.run(run_turn(graph, "cuanto debo?", config=config))
    assert debug.route == "card_info"

    details = asyncio.run(bank_tools.get_card_details(_card_id(bank_tools, "credit")))
    balance = details.current_balance
    assert balance is not None
    expected_min_payment = min_payment(balance, currency, _MIN_PAYMENT_POLICY)
    available = details.available_credit
    assert available is not None

    balance_text = format_money(balance, currency, country)
    min_payment_text = format_money(expected_min_payment, currency, country)
    available_text = format_money(available, currency, country)
    if with_fx:
        balance_text += " " + mxn_estimate(balance, _MX_USD_MXN_FX, language)
        min_payment_text += " " + mxn_estimate(expected_min_payment, _MX_USD_MXN_FX, language)
        available_text += " " + mxn_estimate(available, _MX_USD_MXN_FX, language)

    expected = f"{balance_text} / {_due_date_text(country)} / {min_payment_text} / {available_text}"
    if dpd:
        expected += " / " + format_days(dpd, language)
    expected += "\n\n" + get_template("synthetic_footnote", language)
    assert reply == expected

    # `currency`/`fx_rate`/`fx_as_of` never reach the LLM as placeholders (R6).
    compose_call = next(c for c in llm.calls if c.step == "compose")
    for hidden in ("currency", "fx_rate", "fx_as_of", "read_only_note"):
        assert hidden not in compose_call.user


@pytest.mark.parametrize("language", ["es", "pt"])
def test_debit_balance(fakebank_dir: Path, language: Language) -> None:
    """B1, ADR-032: `balance_due` on a debit card -- its available balance
    through the `debit_balance` goal; never a credit-only money fact.
    """
    ctx = ToolContext(
        customer_id="CLI-TFMULTI00001",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    # `CLI-TFMULTI00001` has two debit cards (one Closed), so a plain
    # `debit` hint stays ambiguous; `last4` picks the Active one.
    nlu = NLUResult(
        language=language,
        intents=["balance_due"],
        status="clear",
        slots=NLUSlots(card_hint="last4:1203"),
    )
    draft = ComposeDraft(text="{card_kind} {card_mask} {available_balance}")
    llm = ScriptedLLM({"nlu": [nlu], "compose": [draft]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, f"t-debit-balance-{language}")

    reply, debug = asyncio.run(run_turn(graph, "cuanto saldo tengo en mi debito?", config=config))
    assert debug.route == "card_info"

    details = asyncio.run(bank_tools.get_card_details(_card_id(bank_tools, "debit")))
    assert details.current_balance is not None
    balance_text = format_money(details.current_balance, "USD", "MX")
    balance_text += " " + mxn_estimate(details.current_balance, _MX_USD_MXN_FX, language)
    assert reply == f"{kind_label('debit', language)} {mask_card(details.last4)} {balance_text}"

    compose_call = next(c for c in llm.calls if c.step == "compose")
    assert "debit_balance" in compose_call.user
    for leaked in ("current_balance", "min_payment", "available_credit", "due_date", "currency"):
        assert leaked not in compose_call.user


@pytest.mark.parametrize("language", ["es", "pt"])
def test_inactive_customer_read_only(fakebank_dir: Path, language: Language) -> None:
    """B1, ADR-021: a customer who isn't Active gets a `read_only_note`
    segment on top of the normal balance reply.
    """
    ctx = ToolContext(
        customer_id="CLI-TFINACT00004",
        conversation_id=uuid4(),
        actor="customer",
        policy_version="unversioned",
        trace_id="test-trace",
    )
    bank_tools = FakeBank(ctx, fakebank_dir)
    nlu = NLUResult(language=language, intents=["balance_due"], status="clear", slots=NLUSlots())
    draft = ComposeDraft(text="{current_balance} / {due_date} / {min_payment}")
    llm = ScriptedLLM({"nlu": [nlu], "compose": [draft]})
    graph = build_graph(MemorySaver())
    config = _config(ctx, bank_tools, llm, f"t-inactive-read-only-{language}")

    reply, debug = asyncio.run(run_turn(graph, "cuanto debo?", config=config))
    assert debug.route == "card_info"

    details = asyncio.run(bank_tools.get_card_details(_card_id(bank_tools, "credit")))
    balance = details.current_balance
    assert balance is not None
    expected_min_payment = min_payment(balance, "COP", _MIN_PAYMENT_POLICY)
    expected = (
        f"{format_money(balance, 'COP', 'CO')} / {_due_date_text('CO')} / "
        f"{format_money(expected_min_payment, 'COP', 'CO')}"
        f"\n\n{get_template('synthetic_footnote', language)}"
        f"\n\n{get_template('read_only_note', language)}"
    )
    assert reply == expected
