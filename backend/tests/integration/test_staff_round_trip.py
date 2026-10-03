"""D4-A A4 "Done when" over the HTTP API, plus R13 across actors.

The round trip: a customer asks for a person, the handoff row and the
`handoff_created` event appear, an agent claims, the agent's message reaches
the customer's stream, the customer's reply reaches the agent's stream with no
bot answer, the agent returns the conversation, and Cardy answers the
customer's next message without handing off again (the W3 proof: `return_to_
bot` clears the handoff state).

`TestClient` buffers a whole response, so an endless SSE stream can't be read
through it. `_EventTap` reads the same Redis channels the two stream routes
relay (`conv:<id>` and `handoff:*`), on its own thread and loop with its own
Redis client (the app's `get_redis()` is bound to the portal loop), and
`wait_for` is bounded. Each actor's cookies travel as explicit headers so one
`TestClient` (one portal loop) serves the customer and both agents.

See `docs/specs/d4-a-escalation-handoff-deploy.md` §"Test list".
"""

import asyncio
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import redis.asyncio as aioredis
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from app.core import events
from app.core.config import get_settings
from app.domains.conversation.nodes.compose import ComposeDraft
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult, NLUSlots
from app.domains.handoff.schemas import reference_for
from app.domains.identity.tokens import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from app.domains.localization.format import queue_label
from tests.conftest import ScriptedLLM
from tests.integration.conftest import ItAccount, ItStaff

_SINGLE_CUSTOMER_ID = "CLI-TFSINGLE0002"
_WAIT_SECONDS = 15.0

Headers = dict[str, str]
Event = tuple[str, Any]


class _EventTap:
    """Collects `(event, data)` pairs from Redis pub/sub on a background
    thread. Subscribed by the time the constructor returns.
    """

    def __init__(self, *, channel: str | None = None, pattern: str | None = None) -> None:
        self.events: list[Event] = []
        self._channel = channel
        self._pattern = pattern
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        assert self._ready.wait(5), "event tap failed to subscribe"

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._collect())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass

    async def _collect(self) -> None:
        client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
        pubsub = client.pubsub()
        try:
            if self._pattern is not None:
                await pubsub.psubscribe(self._pattern)
            else:
                assert self._channel is not None
                await pubsub.subscribe(self._channel)
            self._ready.set()
            async for event in events._events(pubsub):
                self.events.append(event)
        finally:
            await pubsub.aclose()
            await client.aclose()

    def mark(self) -> int:
        return len(self.events)

    def wait_for(self, predicate: Callable[[Event], bool], *, since: int = 0) -> Event:
        deadline = time.monotonic() + _WAIT_SECONDS
        while True:
            for event in self.events[since:]:
                if predicate(event):
                    return event
            if time.monotonic() > deadline:
                raise AssertionError(f"no matching event within {_WAIT_SECONDS}s: {self.events}")
            time.sleep(0.05)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(5)


@contextmanager
def _tap(*, channel: str | None = None, pattern: str | None = None) -> Iterator[_EventTap]:
    tap = _EventTap(channel=channel, pattern=pattern)
    try:
        yield tap
    finally:
        tap.close()


def _psycopg_dsn(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg://", "postgresql://")


def _headers(response_cookies: Any) -> Headers:
    """Explicit cookie + CSRF headers for one actor (module docstring)."""
    session, csrf = response_cookies[SESSION_COOKIE], response_cookies[CSRF_COOKIE]
    return {"Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}", CSRF_HEADER: csrf}


def _customer_login(client: TestClient, account: ItAccount) -> Headers:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "document_type": account.document_type,
            "document_number": account.document_number,
            "password": account.password,
        },
    )
    assert response.status_code == 200
    headers = _headers(response.cookies)
    client.cookies.clear()
    return headers


def _staff_login(client: TestClient, agent: ItStaff, *, password: str | None = None) -> Headers:
    response = client.post(
        "/api/v1/auth/staff/login",
        json={"username": agent.username, "password": password or agent.password},
    )
    assert response.status_code == 200
    headers = _headers(response.cookies)
    client.cookies.clear()
    return headers


def _handoff_rows(dsn: str, conversation_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT id, queue, reason, status FROM app.handoffs WHERE conversation_id = %s",
            (uuid.UUID(conversation_id),),
        ).fetchall()


def _wait_for_handoff(dsn: str, conversation_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + _WAIT_SECONDS
    while True:
        rows = _handoff_rows(dsn, conversation_id)
        if rows:
            return rows[0]
        if time.monotonic() > deadline:
            raise AssertionError("no app.handoffs row")
        time.sleep(0.1)


def _is(name: str, **fields: Any) -> Callable[[Event], bool]:
    def predicate(event: Event) -> bool:
        return event[0] == name and all(event[1].get(k) == v for k, v in fields.items())

    return predicate


def _post_turn(client: TestClient, headers: Headers, conversation_id: str, text: str) -> str:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages", json={"text": text}, headers=headers
    )
    assert response.status_code in (200, 201, 202), response.text
    turn_id: str = response.json()["turn_id"]
    return turn_id


def _open_conversation(client: TestClient, headers: Headers) -> str:
    response = client.post("/api/v1/conversations", json={}, headers=headers)
    assert response.status_code == 201
    conversation_id: str = response.json()["conversation_id"]
    return conversation_id


def _human_request_nlu(language: str) -> NLUResult:
    return NLUResult(
        language=language,  # type: ignore[arg-type]
        intents=["human_request"],
        status="clear",
        slots=NLUSlots(),
    )


def test_handoff_claim_chat_return(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> None:
    dsn = _psycopg_dsn(it_db)
    agent = it_staff["atencion"]
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [
                _human_request_nlu("es"),
                NLUResult(language="es", intents=["card_status"], status="clear", slots=NLUSlots()),
            ],
            "handoff_summary": [
                HandoffSummaryDraft(request="El cliente pidió hablar con alguien.")
            ],
            "compose": [ComposeDraft(text="Tu tarjeta {card_kind} {card_mask} esta {status}.")],
        }
    )
    customer = _customer_login(app_client, it_accounts[_SINGLE_CUSTOMER_ID])
    conversation_id = _open_conversation(app_client, customer)
    staff = _staff_login(app_client, agent)

    with (
        _tap(channel=events.channel(uuid.UUID(conversation_id))) as conv,
        _tap(pattern="handoff:*") as inbox,
    ):
        # 1-2. The customer asks for a person: the row, the inbox event, the
        # transfer message and the human mode.
        _post_turn(app_client, customer, conversation_id, "Quiero hablar con una persona")
        row = _wait_for_handoff(dsn, conversation_id)
        assert row["queue"] == "atencion"
        assert row["reason"] == "human_request"
        assert row["status"] == "queued"
        inbox.wait_for(_is("handoff_created"))
        conv.wait_for(_is("done"))
        assert any(_is("message", role="bot")(e) for e in conv.events)
        handoff_id = str(row["id"])

        # 3. Claim: `mode{human, name}` reaches the customer.
        claim = app_client.post(f"/api/v1/staff/handoffs/{handoff_id}/claim", headers=staff)
        assert claim.status_code == 200, claim.text
        conv.wait_for(_is("mode", mode="human", agent_display_name=agent.display_name))

        # The claimant reads the transcript: the customer's ask and the
        # handoff bot row (whose ui_payload is a list) are both there.
        transcript = app_client.get(
            f"/api/v1/staff/conversations/{conversation_id}/messages", headers=staff
        )
        assert transcript.status_code == 200, transcript.text
        roles_texts = [(m["role"], m["text"]) for m in transcript.json()]
        assert ("customer", "Quiero hablar con una persona") in roles_texts
        assert any(role == "bot" and "HO-" in text for role, text in roles_texts)

        # 4. The agent's message reaches the customer's stream.
        sent = app_client.post(
            f"/api/v1/staff/conversations/{conversation_id}/messages",
            json={"text": "Hola, soy Laura, te ayudo."},
            headers=staff,
        )
        assert sent.status_code == 201, sent.text
        conv.wait_for(_is("message", role="agent", text="Hola, soy Laura, te ayudo."))

        # 5. The customer's message reaches the agent's stream, and no bot
        # message follows it.
        mark = conv.mark()
        _post_turn(app_client, customer, conversation_id, "Gracias, es por mi tarjeta")
        conv.wait_for(_is("message", role="customer"), since=mark)
        conv.wait_for(_is("done"), since=mark)
        assert not any(_is("message", role="bot")(e) for e in conv.events[mark:])

        # 6. Return: the system message and `mode{bot}`.
        mark = conv.mark()
        returned = app_client.post(f"/api/v1/staff/handoffs/{handoff_id}/return", headers=staff)
        assert returned.status_code == 200, returned.text
        conv.wait_for(_is("message", role="system"), since=mark)
        conv.wait_for(_is("mode", mode="bot"), since=mark)

        # 7. The next customer message gets a bot answer, no second handoff.
        mark = conv.mark()
        _post_turn(app_client, customer, conversation_id, "Cual es el estado de mi tarjeta?")
        conv.wait_for(_is("done"), since=mark)
        answer = conv.wait_for(_is("message", role="bot"), since=mark)
        assert "2222" in answer[1]["text"]
        assert not any(e[0] == "mode" and e[1].get("mode") == "human" for e in conv.events[mark:])

    rows = _handoff_rows(dsn, conversation_id)
    assert [r["status"] for r in rows] == ["returned"]


def test_pt_handoff_happy_path(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> None:
    dsn = _psycopg_dsn(it_db)
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [_human_request_nlu("pt")],
            "handoff_summary": [
                HandoffSummaryDraft(request="O cliente pediu para falar com alguem.")
            ],
        }
    )
    customer = _customer_login(app_client, it_accounts[_SINGLE_CUSTOMER_ID])
    conversation_id = _open_conversation(app_client, customer)

    with _tap(channel=events.channel(uuid.UUID(conversation_id))) as conv:
        _post_turn(app_client, customer, conversation_id, "Quero falar com uma pessoa")
        conv.wait_for(_is("done"))
        row = _wait_for_handoff(dsn, conversation_id)
        text = conv.wait_for(_is("message", role="bot"))[1]["text"]

    assert row["queue"] == "atencion"
    assert queue_label("atencion", "pt") in text
    assert reference_for(row["id"]) in text
    assert "Te estoy transfiriendo" not in text


def test_staff_access_boundaries(
    app_client: TestClient,
    it_accounts: dict[str, ItAccount],
    it_staff: dict[str, ItStaff],
    it_db: str,
) -> None:
    dsn = _psycopg_dsn(it_db)
    agent_a, agent_b = it_staff["atencion"], it_staff["fraudes"]
    app_client.app.state.turn_host.llm = ScriptedLLM(
        {
            "nlu": [_human_request_nlu("es")],
            "handoff_summary": [
                HandoffSummaryDraft(request="El cliente pidió hablar con alguien.")
            ],
        }
    )
    customer = _customer_login(app_client, it_accounts[_SINGLE_CUSTOMER_ID])
    staff_a = _staff_login(app_client, agent_a)
    staff_b = _staff_login(app_client, agent_b)

    # Customer -> staff routes: 403.
    assert app_client.get("/api/v1/staff/handoffs", headers=customer).status_code == 403
    # Agent -> customer routes: 403.
    assert app_client.post("/api/v1/conversations", json={}, headers=staff_a).status_code == 403

    # Agent B on agent A's claimed conversation: 404 on messages and stream.
    conversation_id = _open_conversation(app_client, customer)
    with _tap(channel=events.channel(uuid.UUID(conversation_id))) as conv:
        _post_turn(app_client, customer, conversation_id, "Quiero hablar con una persona")
        conv.wait_for(_is("done"))
    handoff_id = _wait_for_handoff(dsn, conversation_id)["id"]
    claim = app_client.post(f"/api/v1/staff/handoffs/{handoff_id}/claim", headers=staff_a)
    assert claim.status_code == 200, claim.text
    base = f"/api/v1/staff/conversations/{conversation_id}"
    assert app_client.get(f"{base}/messages", headers=staff_b).status_code == 404
    assert app_client.get(f"{base}/stream", headers=staff_b).status_code == 404

    # Wrong staff password: 401.
    wrong = app_client.post(
        "/api/v1/auth/staff/login",
        json={"username": agent_a.username, "password": "not-the-password"},
    )
    assert wrong.status_code == 401
