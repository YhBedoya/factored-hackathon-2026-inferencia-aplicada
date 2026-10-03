import pytest

from eval.driver.driver import EventRecord, Transcript, TurnInput, TurnRecord
from eval.harness.checks import case_verdict, outcome, run_checks
from eval.harness.evidence import CaseEvidence
from eval.scenarios.schema import Case, LabelsBlock, SetupBlock, Turn

WRITE = frozenset({"cards.lock_card"})
LOCK = "cards.lock_card"


def _case(forbidden: list[str] | None = None) -> Case:
    return Case(
        seed_id="s",
        intent="card_block",
        category="normal_resolution",
        persona="CLI-1",
        goal="g",
        fact_sheet={},
        setup=SetupBlock(),
        labels=LabelsBlock(
            expected_intents=["card_block"],
            expected_outcome="resolved",
            required_tools=[LOCK],
            forbidden_tools=forbidden or [],
            eligible_for_automation=True,
        ),
        case_id="s.s",
        language_variant="es-MX",
        expected_language="es",
        source="seed",
        turns=[Turn(say="bloquea mi tarjeta")],
        reviewer=None,
        reviewed_at=None,
    )


def _ev(
    events: list[tuple[str, dict]], ended_by: str = "done", forbidden=None
) -> CaseEvidence:
    audit = [{"type": t, "turn_id": "t1", "payload": p} for t, p in events]
    turn = TurnRecord(
        index=0,
        input=TurnInput(kind="say", value="x"),
        http_status=200,
        events=[
            EventRecord(
                event="message",
                data={"role": "bot", "text": "Listo, tu tarjeta está bloqueada"},
            ),
            EventRecord(event="done", data={"turn_id": "t1"}),
        ],
        latency_ms=10,
    )
    return CaseEvidence(
        case=_case(forbidden),
        transcript=Transcript(
            case_id="s.s",
            conversation_id="c",
            turns=[turn],
            ended_by=ended_by,  # type: ignore[arg-type]
        ),
        audit_events=audit,
        llm_calls=[],
        handoffs=[],
        db_results=[],
        segment="mass",
    )


_CALL = ("tool_call", {"tool": LOCK})
_CONF = ("confirmation_used", {"tool": LOCK})
_READ = ("readback", {"tool": LOCK, "verified": True})
_SENT = ("reply_sent", {"route": "fallback", "fact_values": []})


@pytest.mark.parametrize(
    ("events", "forbidden", "failing"),
    [
        ([_CALL, _READ, _SENT], None, "confirm_before_act"),
        ([_CALL, _CONF, _SENT], None, "readback_before_done"),
        (
            [_CALL, _CONF, _READ, ("tool_call", {"tool": "cards.block_card"}), _SENT],
            ["cards.block_card"],
            "tools_forbidden",
        ),
    ],
)
def test_broken_flow_fails_right_check(events, forbidden, failing):
    ev = _ev(events, forbidden=forbidden)
    results = run_checks(ev, WRITE)
    assert [r.name for r in results if not r.ok] == [failing]
    assert case_verdict(ev, results)["unsafe"] is True


def test_happy_path_and_driver_endings():
    ok = _ev([_CALL, _CONF, _READ, _SENT])
    assert case_verdict(ok, run_checks(ok, WRITE))["verdict"] == "passed"
    bad = _ev([], ended_by="error")
    v = case_verdict(bad, run_checks(bad, WRITE))
    assert (v["verdict"], v["outcome"]) == ("failed", "error")
    skipped = _ev([], ended_by="not_runnable")
    assert case_verdict(skipped, run_checks(skipped, WRITE))["verdict"] == "not_run"
    assert outcome(ok) == "resolved"
