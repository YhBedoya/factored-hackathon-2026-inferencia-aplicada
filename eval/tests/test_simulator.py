"""Tests 1-2 (spec `d6-b-simulator-ui-hardening.md` §"Test list"): the
simulator's R5 masking and its four D6 stop conditions, against an
`httpx.MockTransport` and a fake `LLMClient` -- never a real server or a
real model. No `pytest-asyncio` (matches the scripted driver's tests): each
test drives its own coroutine with `asyncio.run(...)`.
"""

import asyncio
import itertools
import json
from typing import Any

import httpx
import pytest

from eval.scenarios.schema import Case, LabelsBlock, SetupBlock, Turn
from eval.simulator import SimAction, run_case_simulated

_PERSONA = "CLI-TESTSIM0001"
_BASE_URL = "http://test"
_DISPLAY_NAME = "Ana"
_OTP_CODE = "0000"

_DONE = 'event: done\ndata: {"turn_id": "11111111-1111-1111-1111-111111111111"}\n\n'


def _case() -> Case:
    return Case(
        seed_id="sim-01",
        intent="card_block",
        category="normal_resolution",
        persona=_PERSONA,
        goal="bloquear la tarjeta temporalmente",
        fact_sheet={"last4": "5772"},
        setup=SetupBlock(),
        labels=LabelsBlock(
            expected_intents=["card_block"],
            expected_outcome="resolved",
            required_tools=["cards.block_card"],
            forbidden_tools=[],
            eligible_for_automation=True,
        ),
        case_id="sim-01.s",
        language_variant="es-CO",
        expected_language="es",
        source="seed",
        turns=[Turn(say="Hola, quiero bloquear mi tarjeta.")],
        reviewer=None,
        reviewed_at=None,
    )


def _identity_json() -> dict[str, str]:
    return {
        "role": "customer",
        "login_hint": _PERSONA,
        "display_name": _DISPLAY_NAME,
        "country": "CO",
        "customer_status": "Active",
    }


def _sse(*frames: str) -> bytes:
    return (": connected\n\n" + "".join(frames)).encode()


def _bot_message(text: str) -> str:
    return f'event: message\ndata: {{"role": "bot", "text": "{text}", "sources": []}}\n\n'


class _FakeLLM:
    """Records every `structured(...)` call and replays a scripted queue of
    `SimAction`s. Raises if called more times than the test expects, rather
    than letting a `StopIteration` escape the coroutine."""

    def __init__(self, actions: Any) -> None:
        self._actions = iter(actions)
        self.calls: list[dict[str, str]] = []

    async def structured(
        self, *, step: str, prompt: Any, system: str, user: str, schema: Any
    ) -> Any:
        self.calls.append({"step": step, "system": system, "user": user})
        try:
            return next(self._actions)
        except StopIteration as exc:
            raise AssertionError("simulator called the LLM more times than expected") from exc


def _make_handler(stream_bodies: list[bytes], otp_calls: list[dict[str, Any]]):
    stream_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/test-idp/sessions":
            return httpx.Response(
                200, json=_identity_json(), headers=[("set-cookie", "csrf_token=csrf-abc; Path=/")]
            )
        if path == "/api/v1/auth/me":
            return httpx.Response(200, json=_identity_json())
        if path == "/api/v1/conversations":
            return httpx.Response(201, json={"conversation_id": "conv-1"})
        if path.endswith("/stream"):
            body = stream_bodies[stream_calls["n"]]
            stream_calls["n"] += 1
            return httpx.Response(
                200, content=body, headers=[("content-type", "text/event-stream")]
            )
        if path == "/api/v1/auth/otp/verify":
            otp_calls.append(json.loads(request.content))
            return httpx.Response(200, json={"customer_id": _PERSONA})
        if path.endswith("/messages"):
            return httpx.Response(202, json={"turn_id": "22222222-2222-2222-2222-222222222222"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


def _run(stream_bodies: list[bytes], fake_llm: _FakeLLM, otp_calls: list[dict[str, Any]]) -> Any:
    handler = _make_handler(stream_bodies, otp_calls)
    case = _case()

    async def _go() -> Any:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url=_BASE_URL) as client:
            return await run_case_simulated(
                case, base_url=_BASE_URL, otp_code=_OTP_CODE, client=client, llm=fake_llm
            )

    return asyncio.run(_go())


def test_bot_text_is_masked_before_prompt() -> None:
    """R5: the bot's turn-1 reply carries the persona's `display_name`; it
    must reach the fake LLM only as `⟨NAME_1⟩`, inside a fence, with the raw
    name in neither `system` nor `user`."""

    stream_bodies = [_sse(_bot_message(f"Hola {_DISPLAY_NAME}, ¿en qué te ayudo?"), _DONE)]
    fake_llm = _FakeLLM([SimAction(kind="stop", stop_reason="goal")])

    transcript = _run(stream_bodies, fake_llm, [])

    assert transcript.ended_by == "done"
    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    assert _DISPLAY_NAME not in call["system"]
    assert _DISPLAY_NAME not in call["user"]
    assert "⟨NAME_1⟩" in call["user"]
    assert "```" in call["user"]


@pytest.mark.parametrize("scenario", ["goal", "handoff_banner", "max_turns", "otp"])
def test_stop_conditions(scenario: str) -> None:
    """D6: `stop(goal)` -> `done`, a `ui.handoff_banner` -> `handoff`, a
    fake that never stops -> `max_turns` at 12, and an `otp` action sends
    the harness code (never model text)."""

    otp_calls: list[dict[str, Any]] = []

    if scenario == "goal":
        stream_bodies = [_sse(_bot_message("hola"), _DONE)]
        fake_llm = _FakeLLM([SimAction(kind="stop", stop_reason="goal")])
    elif scenario == "handoff_banner":
        stream_bodies = [
            _sse(
                'event: ui\ndata: {"kind": "handoff_banner", "payload": '
                '{"handoff_id": "h1", "reference": "HO-1", "queue": "q", '
                '"queue_label": "Cola"}}\n\n',
                _DONE,
            )
        ]
        fake_llm = _FakeLLM([])
    elif scenario == "max_turns":
        stream_bodies = [_sse(_bot_message("sigo"), _DONE) for _ in range(12)]
        fake_llm = _FakeLLM(itertools.repeat(SimAction(kind="say", text="sigo aquí")))
    else:  # otp
        stream_bodies = [
            _sse(_bot_message("hola, te envío un código"), _DONE),
            _sse(_bot_message("listo"), _DONE),
        ]
        fake_llm = _FakeLLM(
            [
                SimAction(kind="otp", text="9999"),  # model text must never be sent as the code
                SimAction(kind="stop", stop_reason="goal"),
            ]
        )

    transcript = _run(stream_bodies, fake_llm, otp_calls)

    if scenario == "goal":
        assert transcript.ended_by == "done"
        assert transcript.stop_reason == "goal"
    elif scenario == "handoff_banner":
        assert transcript.ended_by == "handoff"
        assert fake_llm.calls == []
    elif scenario == "max_turns":
        assert transcript.ended_by == "max_turns"
        assert len(transcript.turns) == 12
    else:
        assert otp_calls == [{"code": _OTP_CODE}]
        assert transcript.ended_by == "done"
