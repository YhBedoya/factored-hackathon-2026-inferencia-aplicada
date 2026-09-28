"""A4 "Done when": a restart between turns loses nothing (D16).

Turn 1 leaves `card_select` pending ("which card?", `pending.awaiting_slot ==
"card_hint"`). The whole `TurnHost` -- pool, checkpointer, compiled graph --
is then closed and rebuilt from scratch, exactly as a process restart would,
before turn 2 ("la de credito") answers from the checkpoint and the
persisted messages. `ScriptedLLM` only, no network; `it_env` points the run
at the throwaway `latam_it_*` database (D19) with `BANK=postgres`, so
`registry.bank_tools_for` resolves to `PostgresBank` over the same fixture
customer `test_r1_postgres_tools.py` uses.

See `docs/specs/d2-a-login-read-tools-api.md` D13-D16, D21; §"Test list" ->
`test_restart.py`.
"""

import asyncio
from uuid import uuid4

from app.core import events
from app.core.config import get_settings
from app.domains.conversation import store
from app.domains.conversation.hosting import close_host, open_host
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.runner import start_turn
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.identity.models import Session
from tests.conftest import ScriptedLLM

_CUSTOMER_ID = "CLI-TFMULTI00001"  # owns two cards; see fixtures/fakebank/README.md


def test_restart_mid_conversation_continues(it_env: None) -> None:
    async def _run() -> None:
        conversation_id = await store.create_conversation(_CUSTOMER_ID, "es")
        session = Session(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER_ID, step_up_at=None
        )

        ask_nlu = NLUResult(
            language="es", intents=["card_status"], status="clear", slots=NLUSlots()
        )
        ask_draft = ComposeDraft(text="Cual tarjeta queres consultar?\n{card_options}")
        llm1 = ScriptedLLM({"nlu": [ask_nlu], "compose": [ask_draft]})

        host1 = await open_host(get_settings().database_url, llm1)
        try:
            seen1: list[tuple[str, object]] = []
            async with events.subscribe(conversation_id) as stream:
                turn_id = await start_turn(
                    host1,
                    session=session,
                    conversation_id=conversation_id,
                    text="hola, cual es el estado de mi tarjeta?",
                    trace_id="t-restart-1",
                )
                async for event, data in stream:
                    seen1.append((event, data))
                    if event == "done":
                        break

            kinds1 = [event for event, _ in seen1]
            assert "status" in kinds1
            debug_events1 = [data for event, data in seen1 if event == "debug"]
            assert debug_events1 and debug_events1[0]["route"] == "card_info"
            assert kinds1.index("status") < kinds1.index("message") < kinds1.index("debug")
            assert seen1[-1] == ("done", {"turn_id": str(turn_id)})
        finally:
            await close_host(host1)

        # Rebuild the whole host from scratch: pool, checkpointer, graph --
        # the D16 restart proof.
        answer_nlu = NLUResult(
            language="es",
            intents=["card_status"],
            status="clear",
            slots=NLUSlots(card_hint="credit"),
        )
        answer_draft = ComposeDraft(
            text=(
                "Tu tarjeta {card_kind} {card_mask} esta {status}. Vence el {expiry}. "
                "Limite {credit_limit}, disponible {available_credit}."
            )
        )
        llm2 = ScriptedLLM({"nlu": [answer_nlu], "compose": [answer_draft]})
        host2 = await open_host(get_settings().database_url, llm2)
        try:
            state = await host2.graph.aget_state(
                {"configurable": {"thread_id": str(conversation_id)}}
            )
            assert state.values["pending"]["awaiting_slot"] == "card_hint"

            seen2: list[tuple[str, object]] = []
            async with events.subscribe(conversation_id) as stream:
                await start_turn(
                    host2,
                    session=session,
                    conversation_id=conversation_id,
                    text="la de credito",
                    trace_id="t-restart-2",
                )
                async for event, data in stream:
                    seen2.append((event, data))
                    if event == "done":
                        break

            messages2 = [data for event, data in seen2 if event == "message"]
            assert messages2 and "6475" in messages2[0]["text"]
        finally:
            await close_host(host2)

        rows = await store.list_messages(conversation_id)
        assert [row.role for row in rows] == ["customer", "bot", "customer", "bot"]

    asyncio.run(_run())
