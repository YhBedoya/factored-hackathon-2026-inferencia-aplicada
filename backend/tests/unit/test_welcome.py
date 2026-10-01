"""R3 proofs for Cardy's welcome (landing-home-bienvenida D4, D5): two
consecutive welcomes never repeat a body, and a welcome stored in the
conversation leaves the first real turn untouched and its masked copy free of
the customer's first name (R5). Fake LLM, in-memory Redis and vault, no network.
"""

import asyncio
import random
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.domains.conversation import welcome
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.conversation.templates import WELCOME_BODIES, Language
from app.domains.conversation.tools.context import ToolContext
from app.domains.conversation.tools.fakebank import FakeBank
from app.domains.identity.models import Session
from app.domains.localization import format_date, kind_label, mask_card, status_label
from app.domains.safety.vault import InMemoryPiiVault
from tests.conftest import ScriptedLLM, make_session

_CUSTOMER_ID = "CLI-TFMULTI00001"
_FIRST_NAME = "Prueba"


class _RedisStub:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value


def _customer_session() -> Session:
    return Session(account_id=uuid4(), role="customer", customer_id=_CUSTOMER_ID, step_up_at=None)


def _patch_welcome(
    monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path, redis: _RedisStub, recorded: list[Any]
) -> None:
    async def add_message(conversation_id: UUID, turn_id: UUID, **kwargs: str) -> UUID:
        recorded.append(kwargs)
        return uuid4()

    async def session_profile(ctx: ToolContext) -> Any:
        return await FakeBank(ctx, fakebank_dir).get_profile()

    async def known_pii(ctx: ToolContext) -> Any:
        return await FakeBank(ctx, fakebank_dir).get_pii_profile()

    monkeypatch.setattr(welcome.store, "add_message", add_message)
    monkeypatch.setattr(welcome, "PostgresPiiVault", lambda conversation_id: InMemoryPiiVault())
    monkeypatch.setattr(welcome, "get_redis", lambda: redis)
    monkeypatch.setattr(welcome.registry, "session_profile", session_profile)
    monkeypatch.setattr(welcome.registry, "known_pii", known_pii)


def test_consecutive_welcomes_differ(monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path) -> None:
    redis = _RedisStub()
    recorded: list[Any] = []
    _patch_welcome(monkeypatch, fakebank_dir, redis, recorded)
    session = _customer_session()

    indexes = []
    for _ in range(20):
        asyncio.run(welcome.post_welcome(uuid4(), session=session, language="es"))
        indexes.append(int(redis.data[f"welcome:last:{_CUSTOMER_ID}"]))

    assert all(a != b for a, b in pairwise(indexes))
    assert welcome.pick_body(3, len(WELCOME_BODIES["es"]), random) != 3


@pytest.mark.parametrize(
    ("language", "user_text"),
    [("es", "cual es el estado de mi tarjeta de debito?"), ("pt", "qual o status do meu cartão?")],
)
def test_first_turn_after_welcome(
    language: Language, user_text: str, monkeypatch: pytest.MonkeyPatch, fakebank_dir: Path
) -> None:
    """The welcome and the first real turn share one conversation: the graph
    keeps its state in the checkpoint (not in the message list), so the turn
    must give the card-status reply and the stored messages read
    [bot welcome, customer, bot reply]. Persistence of the customer message and
    the reply goes through the same `store.add_message` seam the runner uses.
    """
    recorded: list[dict[str, Any]] = []
    _patch_welcome(monkeypatch, fakebank_dir, _RedisStub(), recorded)
    nlu = NLUResult(
        language=language,
        intents=["card_status"],
        status="clear",
        slots=NLUSlots(card_hint="last4:1203"),
    )
    llm = ScriptedLLM(
        {"nlu": [nlu], "compose": [ComposeDraft(text="{card_kind} {card_mask} {status} {expiry}")]}
    )
    session = make_session(_CUSTOMER_ID, fakebank_dir, llm)
    ctx = session.config["configurable"]["session"]

    text = asyncio.run(
        welcome.post_welcome(ctx.conversation_id, session=_customer_session(), language=language)
    )
    (message,) = recorded
    assert message["role"] == "bot"
    assert message["content"] == text
    assert any(body in text for body in WELCOME_BODIES[language])
    assert _FIRST_NAME in text
    assert _FIRST_NAME not in message["content_masked"]
    assert "⟨NAME_" in message["content_masked"]

    reply, debug = asyncio.run(run_turn(session.graph, user_text, config=session.config))
    asyncio.run(
        welcome.store.add_message(
            ctx.conversation_id,
            uuid4(),
            role="customer",
            content=user_text,
            content_masked=user_text,
        )
    )
    asyncio.run(
        welcome.store.add_message(
            ctx.conversation_id, uuid4(), role="bot", content=reply, content_masked=reply
        )
    )

    card = next(
        c
        for c in asyncio.run(FakeBank(ctx, fakebank_dir).list_cards())
        if c.kind == "debit" and c.last4 == "1203"
    )
    details = asyncio.run(FakeBank(ctx, fakebank_dir).get_card_details(card.card_id))
    assert details.expiration_date is not None
    expected = (
        f"{kind_label('debit', language)} {mask_card(details.last4)} "
        f"{status_label(details.status, language)} {format_date(details.expiration_date)}"
    )
    assert debug.route == "card_info"
    assert debug.language == language
    assert reply == expected
    assert [m["role"] for m in recorded] == ["bot", "customer", "bot"]
