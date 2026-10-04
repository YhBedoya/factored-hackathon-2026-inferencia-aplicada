"""S2 tests 6-8 (OTP exits, D25-D33): three wrong codes hand off (R2), the verify route
checks conversation ownership first (R13), and Cancel at a pipeline OTP pause. Routes are
called as functions with a stub `turn_host`; every turn runs on `ScriptedLLM`."""

import asyncio
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Response
from pydantic import BaseModel, ValidationError

import app.api.v1.auth as auth_module
import app.api.v1.conversations as conversations_module
from app.api.v1.auth import OtpVerifyRequest, verify_otp
from app.api.v1.conversations import PostMessageRequest, post_message
from app.core.config import get_settings
from app.core.llm import LLMError
from app.core.llm.registry import Step
from app.domains.conversation import store as conversation_store
from app.domains.conversation.agent.schema import AgentTurn
from app.domains.conversation.graph import run_turn
from app.domains.conversation.nodes.handoff_summary import HandoffSummaryDraft
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.store import ConversationRow
from app.domains.conversation.templates import get_template
from app.domains.identity import service as identity_service
from app.domains.identity.models import Session as IdentitySession
from app.domains.policy.registry import get_policies
from tests.conftest import AgentScript, ScriptedLLM, Session, make_session

_CUSTOMER = "CLI-TFSINGLE0002"
_CARD = "PRD-TFS2CRED0001"
_CODE = "123456"
_WRONG = "000000"


class _FakeLimiter:
    """Dict counter with the `LoginLimiter` shape (no Redis)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def get_failures(self, key: str) -> int:
        return self.counts.get(key, 0)

    async def record_failure(self, key: str, *, window_seconds: int) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1

    async def reset(self, key: str) -> None:
        self.counts.pop(key, None)


class _Harness:
    def __init__(self, session: Session, owner: str = _CUSTOMER) -> None:
        self.session = session
        self.limiter = _FakeLimiter()
        self.started: list[dict[str, Any]] = []
        self.identity = IdentitySession(
            account_id=uuid4(), role="customer", customer_id=_CUSTOMER, step_up_at=None
        )
        self.conversation = ConversationRow(
            id=UUID(session.config["configurable"]["thread_id"]),
            customer_id=owner,
            language="es",
            mode="bot",
            status="open",
        )
        turn_host = SimpleNamespace(graph=session.graph)
        self.request: Any = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(turn_host=turn_host))
        )

    @property
    def count(self) -> int:
        return sum(self.limiter.counts.values())

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _recorder(*args: Any, **kwargs: Any) -> UUID:
            self.started.append(kwargs)
            return uuid4()

        async def _noop(*args: Any, **kwargs: Any) -> None:
            return None

        async def _get_conversation(conversation_id: UUID) -> ConversationRow:
            return self.conversation

        monkeypatch.setattr(auth_module, "start_turn", _recorder)
        monkeypatch.setattr(conversations_module, "start_turn", _recorder)
        monkeypatch.setattr(conversations_module, "_check_turn_caps", _noop)
        monkeypatch.setattr(conversations_module, "_count_turn", _noop)
        monkeypatch.setattr(conversation_store, "get_conversation", _get_conversation)
        monkeypatch.setattr(identity_service, "_default_limiter", self.limiter)

    async def verify(self, code: str) -> Any:
        return await verify_otp(
            req=OtpVerifyRequest(code=code, conversation_id=self.conversation.id),
            request=self.request,
            response=Response(),
            session=self.identity,
        )

    async def post(self, **body: Any) -> Any:
        return await post_message(
            body=PostMessageRequest(**body),
            request=self.request,
            session=self.identity,
            conversation=self.conversation,
        )


@pytest.fixture(autouse=True)
def _demo_code(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DEMO_OTP_CODE", _CODE)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _agent_turn() -> AgentTurn:
    return AgentTurn(
        language="es",
        intents=["card_unlock"],
        outcome="answered",
        awaiting_slot=None,
        reported_done=[],
        reply="Necesito verificar tu identidad.",
    )


_Outputs = dict[Step, Sequence[BaseModel | LLMError | AgentScript]]


def _pipeline_llm(extra: _Outputs | None = None) -> ScriptedLLM:
    nlu = [NLUResult(language="es", intents=["card_unlock"], status="clear")]
    return ScriptedLLM({"nlu": nlu, **(extra or {})})


@pytest.mark.parametrize("system", ["agent", "pipeline"])
def test_r2_third_wrong_code_hands_off(
    system: str,
    fakebank_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    drafts: _Outputs = {
        "handoff_summary": [
            HandoffSummaryDraft(
                request="Código OTP errado {failed_codes} vezes; ação não executada.",
                asked="Pediu para desbloquear o cartão.",
                did="Pediu o código de verificação; {failed_codes} códigos errados.",
                unfinished="O desbloqueio não foi executado.",
            )
        ]
    }
    if system == "agent":
        request.getfixturevalue("agent_on")
        llm = ScriptedLLM(
            {
                "agent": [
                    AgentScript(
                        rounds=[
                            [("card_status", {})],
                            [("propose_plan", {"steps": [{"action": "unlock", "card": "c1"}]})],
                        ],
                        finals=[_agent_turn()],
                    )
                ],
                **drafts,
            }
        )
        first_text = "desbloquea mi tarjeta"
    else:
        monkeypatch.setenv("AGENT_ENABLED", "false")
        get_settings.cache_clear()
        llm = _pipeline_llm(drafts)
        first_text = "quiero desbloquear mi tarjeta"

    async def run() -> None:
        session = make_session(_CUSTOMER, fakebank_dir, llm, otp_code=_CODE, write_audit=True)
        session.overlay.locked.add(_CARD)
        h = _Harness(session)
        h.install(monkeypatch)

        await run_turn(session.graph, first_text, config=session.config)
        for _ in range(2):
            with pytest.raises(HTTPException) as exc:
                await h.verify(_WRONG)
            assert exc.value.status_code == 401 and exc.value.detail == "otp_invalid"
        assert h.started == []

        with pytest.raises(HTTPException) as exc:
            await h.verify(_WRONG)
        assert exc.value.status_code == 429 and exc.value.detail == "otp_handoff"
        assert len(h.started) == 1 and h.started[0]["resume"] == "step_up_failed"

        reply, _ = await run_turn(session.graph, "", config=session.config, resume="step_up_failed")
        values = (await session.graph.aget_state(session.config)).values

        created = session.handoff_tools.created[-1]
        assert (created.reason, created.queue, created.priority) == (
            "step_up_failed",
            "fraudes",
            "high",
        )
        failed = get_template("step_up_failed_handoff", "es")
        transfer_prefix = get_template("handoff_transfer", "es").split("{queue_label}")[0]
        assert reply.startswith(failed)
        assert transfer_prefix in reply[len(failed) :]
        assert values["intent_segments"]
        assert all(s["status"] == "handoff" for s in values["intent_segments"])
        assert all(s["intent"] == "card_unlock" for s in values["intent_segments"])
        assert not values.get("pending")
        assert values["mode"] == "human"
        events = [t for t, _ in session.audit.events]
        assert "confirmation_issued" not in events and "confirmation_used" not in events
        assert session.overlay.locked == {_CARD}
        assert h.count == 0
        summary_user = next(c.user for c in llm.calls if c.step == "handoff_summary")
        assert "{failed_codes}" in summary_user and "NO se ejecutó" in summary_user
        assert str(get_policies().tools.step_up_max_failures) in created.request

    asyncio.run(run())


def test_r13_otp_conversation_must_be_owned(
    fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        session = make_session(_CUSTOMER, fakebank_dir, _pipeline_llm(), otp_code=_CODE)
        h = _Harness(session, owner="CLI-SOMEONEELSE")
        h.install(monkeypatch)
        key = f"rl:otp:{h.identity.account_id}"
        h.limiter.counts[key] = 1

        with pytest.raises(HTTPException) as exc:
            await h.verify(_WRONG)
        assert exc.value.status_code == 404 and exc.value.detail == "not_found"
        assert h.started == []
        assert h.limiter.counts[key] == 1

    asyncio.run(run())
    with pytest.raises(ValidationError):
        PostMessageRequest(resume="step_up_failed")  # type: ignore[arg-type]


def test_pipeline_otp_cancel(fakebank_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ENABLED", "false")
    get_settings.cache_clear()

    async def run() -> None:
        llm = _pipeline_llm()
        session = make_session(_CUSTOMER, fakebank_dir, llm, otp_code=_CODE, write_audit=True)
        session.overlay.locked.add(_CARD)
        h = _Harness(session)
        h.install(monkeypatch)

        await run_turn(session.graph, "quiero desbloquear mi tarjeta", config=session.config)
        await h.post(resume="step_up_cancel")
        assert len(h.started) == 1 and h.started[0]["resume"] == "step_up_cancel"

        calls_before = len(llm.calls)
        reply, _ = await run_turn(session.graph, "", config=session.config, resume="step_up_cancel")
        values = (await session.graph.aget_state(session.config)).values
        assert reply == get_template("action_cancelled", "es")
        assert not values.get("pending")
        assert [(s["intent"], s["status"]) for s in values["intent_segments"]] == [
            ("card_unlock", "cancelled")
        ]
        assert len(llm.calls) == calls_before
        assert "confirmation_used" not in [t for t, _ in session.audit.events]
        assert session.overlay.locked == {_CARD}

        with pytest.raises(HTTPException) as exc:
            await h.post(resume="step_up_cancel")
        assert exc.value.status_code == 409 and exc.value.detail == "cancel_invalid"

    asyncio.run(run())
