"""T7 selection gate tests (D3, D7 generalized to `decline_explain`'s
single-pick offer, `02` §4.3).

Test 4: drives `decline_explain` to its pick (`make_session`, a `merchant_text`
matching nothing narrows to zero, so D2's zero-match branch offers all 4
declines) with a real turn, then calls `post_message` directly -- a stub
`request.app.state.turn_host.graph = session.graph`, a `ConversationRow` for
the session's own conversation id, and `start_turn` monkeypatched to a
recorder -- and asserts `409 selection_invalid` for a non-offered id and for
two offered ids (D3: `decline_explain`'s offer is single-pick, `multi=False`),
with `start_turn` never called either time (R1: the gate runs before any turn
is scheduled).
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

import app.api.v1.conversations as conversations_module
from app.api.v1.conversations import PostMessageRequest, post_message
from app.domains.conversation.graph import TxSelection, run_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.store import ConversationRow
from app.domains.identity.models import Session as IdentitySession
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER = "CLI-TFDECLN00006"


def test_decline_pick_rejects_unoffered_and_multi_selection(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[Any, ...]] = []

    async def _recorder(*args: Any, **kwargs: Any) -> Any:
        calls.append((args, kwargs))
        return uuid4()

    monkeypatch.setattr(conversations_module, "start_turn", _recorder)

    async def run() -> None:
        llm = ScriptedLLM(
            {
                "nlu": [
                    NLUResult(
                        language="es",
                        intents=["decline_explain"],
                        status="clear",
                        slots=NLUSlots(merchant_text="Comercio Fantasma"),
                    )
                ]
            }
        )
        session = make_session(_CUSTOMER, fakebank_dir, llm)

        _reply, debug = await run_turn(
            session.graph,
            "por que se rechazo mi compra en Comercio Fantasma?",
            config=session.config,
        )
        assert debug.ui == ["transaction_list"]
        assert debug.pending == "decline_explain.transactions"

        state = await session.graph.aget_state(session.config)
        offered = state.values["decline"]["offered_tx_ids"]
        assert len(offered) == 4

        conversation_id = UUID(session.config["configurable"]["thread_id"])
        conversation = ConversationRow(
            id=conversation_id,
            customer_id=_CUSTOMER,
            language="es",
            mode="bot",
            status="open",
        )
        identity_session = IdentitySession(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER, step_up_at=None
        )
        turn_host = SimpleNamespace(graph=session.graph)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(turn_host=turn_host)))

        with pytest.raises(HTTPException) as unoffered_exc:
            await post_message(
                body=PostMessageRequest(selection=TxSelection(tx_ids=["TRX-DOES-NOT-EXIST"])),
                request=request,  # type: ignore[arg-type]
                session=identity_session,
                conversation=conversation,
            )
        assert unoffered_exc.value.status_code == 409
        assert unoffered_exc.value.detail == "selection_invalid"

        with pytest.raises(HTTPException) as multi_exc:
            await post_message(
                body=PostMessageRequest(selection=TxSelection(tx_ids=offered[:2])),
                request=request,  # type: ignore[arg-type]
                session=identity_session,
                conversation=conversation,
            )
        assert multi_exc.value.status_code == 409
        assert multi_exc.value.detail == "selection_invalid"

    asyncio.run(run())
    assert calls == []
