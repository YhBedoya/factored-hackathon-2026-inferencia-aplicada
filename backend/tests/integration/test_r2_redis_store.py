"""A2 "Done when": `RedisConfirmationStore` against a real Redis (D8, `04`
§7). A reused or fully-consumed token, an expired one and a foreign owner
all raise `ConfirmationRequired` with the right reason, `is_open` reflects
only the owner's still-open plan, and a two-step plan rejects an
out-of-order `consume_step`.

See `docs/specs/d3-a-guardrails-write-path.md` D8; §"Test list" ->
`test_r2_redis_store.py`.
"""

import asyncio

import pytest

from app.core.errors import ConfirmationRequired
from app.core.redis import get_redis
from app.domains.policy.confirmation import PlanStep
from app.domains.policy.confirmation_redis import RedisConfirmationStore

_CUSTOMER_ID = "CLI-TFMULTI00001"
_OTHER_CUSTOMER_ID = "CLI-TFSINGLE0002"
_CONVERSATION_ID = "11111111-1111-1111-1111-111111111111"
_OTHER_CONVERSATION_ID = "22222222-2222-2222-2222-222222222222"


def test_reused_expired_foreign_tokens_rejected(it_env: None) -> None:
    async def _run() -> None:
        store = RedisConfirmationStore(_CUSTOMER_ID, _CONVERSATION_ID)

        # A fully consumed single-step token reused -> unknown_or_expired,
        # since the key is deleted after its last step.
        plan = await store.issue([PlanStep(tool="cards.lock_card", args={"card_id": "PRD-1"})])
        await store.consume_step(plan.token_id, "cards.lock_card", {"card_id": "PRD-1"})
        with pytest.raises(ConfirmationRequired) as excinfo:
            await store.consume_step(plan.token_id, "cards.lock_card", {"card_id": "PRD-1"})
        assert excinfo.value.reason == "unknown_or_expired"

        # Issued, then its TTL forced to zero -> unknown_or_expired.
        expired_plan = await store.issue(
            [PlanStep(tool="cards.lock_card", args={"card_id": "PRD-1"})]
        )
        await get_redis().expire(f"conf:{expired_plan.token_id}", 0)
        with pytest.raises(ConfirmationRequired) as excinfo:
            await store.consume_step(expired_plan.token_id, "cards.lock_card", {"card_id": "PRD-1"})
        assert excinfo.value.reason == "unknown_or_expired"

        # Another customer, and another conversation, both -> wrong_owner,
        # and is_open is False for both even though the plan exists.
        owner_plan = await store.issue(
            [PlanStep(tool="cards.lock_card", args={"card_id": "PRD-1"})]
        )
        foreign_customer_store = RedisConfirmationStore(_OTHER_CUSTOMER_ID, _CONVERSATION_ID)
        with pytest.raises(ConfirmationRequired) as excinfo:
            await foreign_customer_store.consume_step(
                owner_plan.token_id, "cards.lock_card", {"card_id": "PRD-1"}
            )
        assert excinfo.value.reason == "wrong_owner"
        assert await foreign_customer_store.is_open(owner_plan.token_id) is False

        foreign_conversation_store = RedisConfirmationStore(_CUSTOMER_ID, _OTHER_CONVERSATION_ID)
        with pytest.raises(ConfirmationRequired) as excinfo:
            await foreign_conversation_store.consume_step(
                owner_plan.token_id, "cards.lock_card", {"card_id": "PRD-1"}
            )
        assert excinfo.value.reason == "wrong_owner"
        assert await foreign_conversation_store.is_open(owner_plan.token_id) is False

        # The owner's own still-open plan reports open.
        assert await store.is_open(owner_plan.token_id) is True

        # A two-step plan consumed out of order -> step_mismatch.
        two_step_plan = await store.issue(
            [
                PlanStep(tool="cards.block_card", args={"card_id": "PRD-1", "reason": "lost"}),
                PlanStep(tool="cards.order_replacement", args={"card_id": "PRD-1"}),
            ]
        )
        with pytest.raises(ConfirmationRequired) as excinfo:
            await store.consume_step(
                two_step_plan.token_id, "cards.order_replacement", {"card_id": "PRD-1"}
            )
        assert excinfo.value.reason == "step_mismatch"

    asyncio.run(_run())
