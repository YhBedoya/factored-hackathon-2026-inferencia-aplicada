"""R1 (`customer_id` comes only from the session) contract tests.

See `docs/specs/d1-k3-contracts.md` §"Test list" and
`docs/specs/d2-k-write-contracts.md` §"Test list". T4 (D2-K) appends
`test_no_customer_id_on_write_side` to this file.
"""

import inspect

import pytest
from pydantic import ValidationError

from app.domains.conversation.graph import ConfirmationDecision
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.state import bind_once
from app.domains.conversation.tools import BankReadTools, BankWriteTools, ConfirmedWriteTools
from app.domains.identity.step_up import StepUpGate
from app.domains.policy.confirmation import ConfirmationStore, PlanStep
from app.domains.transactions.schemas import TxFilter


def test_customer_id_is_write_once() -> None:
    """`bind_once` accepts the first bind and repeats, rejects a change (D4)."""
    assert bind_once("", "C1") == "C1"
    assert bind_once(None, "C1") == "C1"
    assert bind_once("C1", "C1") == "C1"
    with pytest.raises(ValueError, match="R1"):
        bind_once("C1", "C2")


def test_no_customer_id_reaches_tools_or_nlu() -> None:
    """R1 at the contract level (`04` §1, D1, D2)."""
    method_names = {
        name
        for name, _ in inspect.getmembers(BankReadTools, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert method_names >= {"get_profile", "list_cards", "get_card_details", "search_transactions"}
    for name in method_names:
        params = inspect.signature(getattr(BankReadTools, name)).parameters
        assert "customer_id" not in params
        assert "ctx" not in params

    assert "customer_id" not in TxFilter.model_fields
    assert "customer_id" not in NLUResult.model_fields
    assert "customer_id" not in NLUSlots.model_fields

    valid = {"language": "es", "intents": ["card_status"], "status": "clear"}
    assert NLUResult.model_validate(valid)
    with pytest.raises(ValidationError):
        NLUResult.model_validate({**valid, "customer_id": "X"})


def test_no_customer_id_on_write_side() -> None:
    """R1 on the write side (D3-D5, D14): no public method of `BankWriteTools`,
    `ConfirmedWriteTools`, `ConfirmationStore` or `StepUpGate` takes
    `customer_id` or `ctx`, and no plan/decision model carries `customer_id`.
    """
    expected_methods = {
        BankWriteTools: {
            "get_block_origin",
            "lock_card",
            "unlock_card",
            "block_card",
            "order_replacement",
        },
        ConfirmedWriteTools: {
            "issue_plan",
            "cancel_plan",
            "is_step_up_valid",
            "get_block_origin",
            "lock_card",
            "unlock_card",
            "block_card",
            "order_replacement",
        },
        ConfirmationStore: {"issue", "consume_step", "cancel"},
        StepUpGate: {"is_step_up_valid"},
    }
    for cls, names in expected_methods.items():
        method_names = {
            name
            for name, _ in inspect.getmembers(cls, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert method_names >= names
        for name in method_names:
            params = inspect.signature(getattr(cls, name)).parameters
            assert "customer_id" not in params
            assert "ctx" not in params

    assert "customer_id" not in PlanStep.model_fields
    assert "customer_id" not in ConfirmationDecision.model_fields
