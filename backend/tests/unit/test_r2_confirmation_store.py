"""R2/R8/D2: the confirmation store's plan semantics and the `tools.yaml`
step-up rule. No FakeBank, no LLM."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.errors import ConfirmationRequired
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_memory import InMemoryConfirmationStore
from app.domains.policy.escalation import load_escalation_policy
from app.domains.policy.tools_policy import load_tools_policy, step_up_rule

_TOOLS_POLICY = load_tools_policy()


def test_tools_yaml_step_up_rule() -> None:
    rule = step_up_rule(_TOOLS_POLICY)

    # Unlock always needs step-up, regardless of args.
    assert rule("cards.unlock_card", {"card_id": "PRD-1"}) is True

    # Replacement needs step-up only when the address changed (D4).
    assert rule("cards.order_replacement", {"card_id": "PRD-1", "address_ref": "on_file"}) is False
    assert rule("cards.order_replacement", {"card_id": "PRD-1", "address_ref": "⟨ADDR_1⟩"}) is True

    # Lock and (temporary) block never need step-up.
    assert rule("cards.lock_card", {"card_id": "PRD-1"}) is False
    assert rule("cards.block_card", {"card_id": "PRD-1", "reason": "lost_or_stolen"}) is False


def test_headerless_policies_fail_to_load(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]

    tools_no_provenance = tmp_path / "tools.yaml"
    tools_text = (repo_root / "policies" / "tools.yaml").read_text(encoding="utf-8")
    tools_no_provenance.write_text(
        "\n".join(line for line in tools_text.splitlines() if not line.startswith("provenance"))
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_tools_policy(tools_no_provenance)

    escalation_no_provenance = tmp_path / "escalation.yaml"
    escalation_text = (repo_root / "policies" / "escalation.yaml").read_text(encoding="utf-8")
    escalation_no_provenance.write_text(
        "\n".join(
            line for line in escalation_text.splitlines() if not line.startswith("provenance")
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_escalation_policy(escalation_no_provenance)


def test_memory_store_enforces_plan_semantics() -> None:
    async def run() -> None:
        clock_state = [datetime(2026, 3, 12, 12, 0, tzinfo=UTC)]

        def clock() -> datetime:
            return clock_state[0]

        shared_plans = {}
        store = InMemoryConfirmationStore("CLI-1", "CONV-1", clock=clock, plans=shared_plans)

        lock_step = PlanStep(tool="cards.lock_card", args={"card_id": "PRD-1"})
        block_step = PlanStep(
            tool="cards.block_card", args={"card_id": "PRD-1", "reason": "lost_or_stolen"}
        )
        plan = await store.issue([lock_step, block_step])

        # Reordered: the second step can't jump the queue (also a wrong-tool mismatch).
        with pytest.raises(ConfirmationRequired) as exc:
            await store.consume_step(plan.token_id, block_step.tool, block_step.args)
        assert exc.value.reason == "step_mismatch"

        # Same tool, wrong args at the cursor.
        with pytest.raises(ConfirmationRequired) as exc:
            await store.consume_step(plan.token_id, lock_step.tool, {"card_id": "PRD-OTHER"})
        assert exc.value.reason == "step_mismatch"

        # Another customer, same conversation: wrong_owner.
        other_customer = InMemoryConfirmationStore(
            "CLI-2", "CONV-1", clock=clock, plans=shared_plans
        )
        with pytest.raises(ConfirmationRequired) as exc:
            await other_customer.consume_step(plan.token_id, lock_step.tool, lock_step.args)
        assert exc.value.reason == "wrong_owner"

        # Same customer, another conversation: wrong_owner.
        other_conversation = InMemoryConfirmationStore(
            "CLI-1", "CONV-2", clock=clock, plans=shared_plans
        )
        with pytest.raises(ConfirmationRequired) as exc:
            await other_conversation.consume_step(plan.token_id, lock_step.tool, lock_step.args)
        assert exc.value.reason == "wrong_owner"

        # Consume both steps, in order.
        assert await store.consume_step(plan.token_id, lock_step.tool, lock_step.args) == 0
        assert await store.consume_step(plan.token_id, block_step.tool, block_step.args) == 1

        # Key gone after the last step.
        assert plan.token_id not in shared_plans

        # Reused token: a fully consumed plan can't be replayed.
        with pytest.raises(ConfirmationRequired) as exc:
            await store.consume_step(plan.token_id, block_step.tool, block_step.args)
        assert exc.value.reason == "unknown_or_expired"

        # Expired token (injected clock past the 5-minute TTL).
        expiring_plan = await store.issue([lock_step])
        clock_state[0] = clock_state[0] + timedelta(minutes=5, seconds=1)
        with pytest.raises(ConfirmationRequired) as exc:
            await store.consume_step(expiring_plan.token_id, lock_step.tool, lock_step.args)
        assert exc.value.reason == "unknown_or_expired"

    asyncio.run(run())
