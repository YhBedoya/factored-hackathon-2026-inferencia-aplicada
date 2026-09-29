"""Test 6 (B2 Done-when, unit half): the driver's request sequence, event
collection and `ended_by` against an `httpx.MockTransport` scripting SSE
per turn -- never a real server. No `pytest-asyncio` here (matches the
backend convention): each test drives its own coroutine with
`asyncio.run(...)`.
"""

import asyncio
from collections.abc import Callable

import httpx

from eval.driver import Transcript, run_case
from eval.scenarios.schema import Case, LabelsBlock, SetupBlock, Turn

_PERSONA = "CLI-TESTDRIVER01"
_BASE_URL = "http://test"


def _case(*, turns: list[Turn], setup: SetupBlock | None = None) -> Case:
    return Case(
        seed_id="drv-01",
        intent="decline_explain",
        category="normal_resolution",
        persona=_PERSONA,
        goal="test goal",
        fact_sheet={},
        setup=setup or SetupBlock(),
        labels=LabelsBlock(
            expected_intents=["decline_explain"],
            expected_outcome="resolved",
            required_tools=["transactions.explain_decline"],
            forbidden_tools=[],
            eligible_for_automation=True,
        ),
        case_id="drv-01.s",
        language_variant="es-MX",
        expected_language="es",
        source="seed",
        turns=turns,
        reviewer=None,
        reviewed_at=None,
    )


def _sse(*frames: str) -> bytes:
    return (": connected\n\n" + "".join(frames)).encode()


def _frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


def _run(case: Case, transport: httpx.MockTransport) -> Transcript:
    async def _go() -> Transcript:
        async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
            return await run_case(case, base_url=_BASE_URL, otp_code="0000", client=client)

    return asyncio.run(_go())


def _scripted_handler(call_log: list[str]) -> Callable[[httpx.Request], httpx.Response]:
    """A handler that scripts one SSE body per `GET .../stream` call, in
    order, for the `say -> confirm -> otp -> select` sequence this test's
    case plays, and appends `"METHOD path"` to `call_log` for every request.
    """

    _done_frame = _frame("done", '{"turn_id": "11111111-1111-1111-1111-111111111111"}')
    stream_bodies = [
        # turn 1 (say): the bot offers a confirmation, then done.
        _sse(
            _frame("ui", '{"kind": "confirm", "payload": {"token_id": "tok-1", "steps": []}}'),
            _done_frame,
        ),
        # turn 2 (confirm): a plain reply, then done.
        _sse(_frame("message", '{"role": "bot", "text": "listo", "sources": []}'), _done_frame),
        # turn 3 (otp resume): the bot offers a transaction list, then done.
        _sse(
            _frame(
                "ui",
                '{"kind": "transaction_list", '
                '"payload": {"options": [{"tx_id": "TX-1", "label": "x"}], "multi": true}}',
            ),
            _done_frame,
        ),
        # turn 4 (select): plain done, nothing else.
        _sse(_done_frame),
    ]
    stream_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_log.append(f"{request.method} {request.url.path}")
        path = request.url.path
        if path == "/api/v1/test-idp/sessions":
            return httpx.Response(
                200,
                json={"customer_id": _PERSONA},
                headers=[("set-cookie", "csrf_token=csrf-abc; Path=/")],
            )
        if path == "/api/v1/conversations":
            return httpx.Response(201, json={"conversation_id": "conv-1"})
        if path.endswith("/stream"):
            body = stream_bodies[stream_calls["n"]]
            stream_calls["n"] += 1
            headers = [("content-type", "text/event-stream")]
            return httpx.Response(200, content=body, headers=headers)
        if path == "/api/v1/auth/otp/verify":
            return httpx.Response(200, json={"customer_id": _PERSONA})
        if path.endswith("/confirmations/tok-1") or path.endswith("/messages"):
            return httpx.Response(202, json={"turn_id": "22222222-2222-2222-2222-222222222222"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def test_plays_say_confirm_otp_select() -> None:
    call_log: list[str] = []
    handler = _scripted_handler(call_log)
    case = _case(
        turns=[
            Turn(say="¿por qué me rechazaron la compra?"),
            Turn(confirm=True),
            Turn(otp=True),
            Turn(select=["TX-1"]),
        ]
    )

    transcript = _run(case, httpx.MockTransport(handler))

    assert transcript.ended_by == "done"
    assert transcript.conversation_id == "conv-1"
    assert [turn.input.kind for turn in transcript.turns] == ["say", "confirm", "otp", "select"]
    assert transcript.turns[0].events[0].data["payload"]["token_id"] == "tok-1"
    assert transcript.turns[3].http_status == 202
    assert call_log == [
        "POST /api/v1/test-idp/sessions",
        "POST /api/v1/conversations",
        "GET /api/v1/conversations/conv-1/stream",
        "POST /api/v1/conversations/conv-1/messages",
        "GET /api/v1/conversations/conv-1/stream",
        "POST /api/v1/conversations/conv-1/confirmations/tok-1",
        "POST /api/v1/auth/otp/verify",
        "GET /api/v1/conversations/conv-1/stream",
        "POST /api/v1/conversations/conv-1/messages",
        "GET /api/v1/conversations/conv-1/stream",
        "POST /api/v1/conversations/conv-1/messages",
    ]


def test_faults_not_runnable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a not_runnable case must make zero HTTP calls")

    case = _case(turns=[Turn(say="hola")], setup=SetupBlock(faults=["bedrock_timeout"]))

    transcript = _run(case, httpx.MockTransport(handler))

    assert transcript.ended_by == "not_runnable"
    assert transcript.conversation_id is None
    assert transcript.turns == []


def test_stream_read_timeout_ends_transcript_with_error() -> None:
    """A bug fix regression: `httpx.ReadTimeout` (what a real client's
    per-request timeout raises, distinct from `asyncio.TimeoutError`) must
    be caught the same way the 60 s watchdog is, not escape `run_case` and
    abort the whole batch."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/test-idp/sessions":
            return httpx.Response(
                200,
                json={"customer_id": _PERSONA},
                headers=[("set-cookie", "csrf_token=csrf-abc; Path=/")],
            )
        if request.url.path == "/api/v1/conversations":
            return httpx.Response(201, json={"conversation_id": "conv-1"})
        if request.url.path.endswith("/stream"):
            raise httpx.ReadTimeout("simulated read timeout", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    case = _case(turns=[Turn(say="hola")])

    transcript = _run(case, httpx.MockTransport(handler))

    assert transcript.ended_by == "error"
