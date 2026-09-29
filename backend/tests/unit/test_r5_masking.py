"""R5 second line (D10): the mask handed to Langfuse redacts PII. No network."""

import asyncio
from pathlib import Path

from app.core.llm.tracing import langfuse_mask
from app.domains.conversation.graph import run_turn
from app.domains.conversation.masking import mask_user_text
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import ScriptedLLM, make_session


def test_langfuse_mask_redacts() -> None:
    masked = langfuse_mask(
        data={"input": ["mi tarjeta 4111 1111 1111 1111", "a@b.com"], "n": 3},
    )
    assert masked == {"input": ["mi tarjeta ⟨CARD⟩", "⟨EMAIL⟩"], "n": 3}


def test_nlu_sees_only_tokens(fakebank_dir: Path) -> None:
    """R5, D3, D4: a typed PAN, email, phone, the customer's document number and
    first name reach neither the LLM nor the checkpoint as raw values."""
    raws = [
        "4111 1111 1111 1111",
        "ana@example.com",
        "+525512345678",
        "DOC-TF0000001",
        "Prueba",
    ]
    text = f"Hola soy Prueba, doc {raws[3]}, mi tarjeta {raws[0]}, {raws[1]}, {raws[2]}"
    nlu = NLUResult(language="es", intents=["general_question"], status="clear")
    llm = ScriptedLLM({"nlu": [nlu], "compose": [ComposeDraft(text="Hola")]})
    session = make_session("CLI-TFMULTI00001", fakebank_dir, llm)
    vault = InMemoryPiiVault()
    session.config["configurable"]["vault"] = vault  # type: ignore[index]
    bank_tools = session.config["configurable"]["bank_tools"]  # type: ignore[index]

    async def turn() -> None:
        masked = await mask_user_text(text, bank_tools=bank_tools, vault=vault)
        await run_turn(session.graph, masked, config=session.config)

    asyncio.run(turn())

    assert llm.calls
    for call in llm.calls:
        assert "⟨" in call.user
        for raw in raws:
            assert raw not in call.user
    state = asyncio.run(session.graph.aget_state(session.config))
    user_text = state.values["user_text"]
    assert "⟨" in user_text
    for raw in raws:
        assert raw not in user_text
