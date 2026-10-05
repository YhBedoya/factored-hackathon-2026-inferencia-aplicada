"""D9-C T20, R5: the profile-form values live only in the vault. They never reach the LLM,
a UI event or the checkpoint; state holds the changed field names. Fake LLM only."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import run_turn
from tests.conftest import AgentScript, ScriptedLLM, make_session

_OTP = "000000"
_EMAIL = "zq7-form-secret@example.test"
_OCCUPATION = "Cartógrafa de glaciares 7QX"


def _turn(reply: str) -> AgentTurn:
    return AgentTurn(
        language="es",
        intents=["general_question"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply=reply,
    )


@pytest.mark.usefixtures("agent_on")
def test_profile_form_values_never_reach_llm_ui_or_checkpoint(fakebank_dir: Path) -> None:
    async def run() -> None:
        rounds: list[list[tuple[str, dict[str, Any]]]] = [
            [("propose_plan", {"steps": [{"action": "open", "kind": "credit"}]})]
        ]
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(rounds=rounds, finals=[_turn("Completa el formulario.")]),
                    AgentScript(rounds=[], finals=[_turn("Revisa tu solicitud.")]),
                ]
            }
        )
        session = make_session("CLI-TFMULTI00001", fakebank_dir, llm, otp_code=_OTP)
        graph, config = session.graph, session.config
        ui_seen: list[str] = []

        async def turn(text: str, **kwargs: Any) -> dict[str, Any]:
            await run_turn(graph, text, config=config, **kwargs)
            values = (await graph.aget_state(config)).values
            ui_seen.append(json.dumps([e.model_dump(mode="json") for e in values.get("ui") or []]))
            return values  # type: ignore[no-any-return]

        values = await turn("quiero una tarjeta de crédito nueva")
        assert values["pending"]["awaiting_slot"] == "profile_form"
        assert values["profile_changed_fields"] is None

        await session.overlay.vault.stage_form_values({"email": _EMAIL, "occupation": _OCCUPATION})
        calls_before = len(llm.calls)
        values = await turn("", resume="profile_form", form_changed_fields=["email", "occupation"])
        assert len(llm.calls) == calls_before  # the form turn is code only
        assert values["pending"]["awaiting_slot"] == "otp"

        assert session.gate.verify(_OTP)
        values = await turn("", resume="step_up")
        assert values["pending"]["node"] == "confirm"
        assert values["profile_changed_fields"] == ["email", "occupation"]

        secrets = (_EMAIL, _OCCUPATION)
        for call in llm.calls:
            texts = [call.system, call.user, *call.messages, *call.tool_results]
            assert not any(secret in text for text in texts for secret in secrets)
        assert not any(secret in blob for blob in ui_seen for secret in secrets)
        state_dump = json.dumps(values, default=str)
        assert not any(secret in state_dump for secret in secrets)

    asyncio.run(run())
