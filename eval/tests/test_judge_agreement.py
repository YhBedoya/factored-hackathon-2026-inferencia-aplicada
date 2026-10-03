"""Test 13 (spec "Test list"): the judge agreement report's kappa math and
weak-judge flag, and the R5/R6 masking + fencing on the judge's own input.
Both are pure functions -- no LLM call, no file on disk."""

import pytest

from eval.judges.agreement import cohen_kappa, percent_agreement, render_report
from eval.judges.judge import build_judge_user_message
from eval.judges.sample import KnownPii, Masker, mask_text

# Hand-computed: 10 items, 7 agreements (po=0.7). Judge says True 6/10, human
# True 5/10 (pe = 0.6*0.5 + 0.4*0.5 = 0.5). kappa = (0.7-0.5)/(1-0.5) = 0.4.
_JUDGE = [True, True, True, True, True, True, False, False, False, False]
_HUMAN = [True, True, True, True, False, False, True, False, False, False]


def _items() -> list[dict[str, object]]:
    return [{"item_id": f"J-{i:03d}", "language": "es" if i % 2 else "pt"} for i in range(1, 11)]


def _human_records(labeler: str) -> list[dict[str, object]]:
    return [
        {
            "item_id": f"J-{i:03d}",
            "labeler": labeler,
            "grounding": value,
            "tone": value,
            "clarity": value,
            "register": value,
            "overall": value,
        }
        for i, value in enumerate(_HUMAN, start=1)
    ]


def _verdicts() -> list[dict[str, object]]:
    return [
        {
            "item_id": f"J-{i:03d}",
            "verdict": {
                "grounding": value,
                "tone": value,
                "clarity": value,
                "register": value,
                "overall": value,
                "note": "ok",
            },
        }
        for i, value in enumerate(_JUDGE, start=1)
    ]


def _assignment() -> dict[str, object]:
    # All 10 items shared, so both judge-vs-human and human-vs-human read
    # the same fixed lists -- the point of this test is the math, not a
    # realistic 50-item split (that's T10's live run).
    ids = [f"J-{i:03d}" for i in range(1, 11)]
    return {"first": "ana", "second": "beto", "shared": ids, "ana": [], "beto": []}


def test_kappa_and_weak_flag() -> None:
    assert cohen_kappa(_JUDGE, _HUMAN) == pytest.approx(0.4)
    assert percent_agreement(_JUDGE, _HUMAN) == pytest.approx(0.7)
    # pe == 1 (both raters constant and equal): undefined, not divide-by-zero.
    assert cohen_kappa([True] * 5, [True] * 5) is None

    labels = {"ana": _human_records("ana"), "beto": _human_records("beto")}
    report = render_report(_items(), labels, _verdicts(), _assignment())

    assert report.startswith("**judge is weak**")
    assert "offline evaluation" in report
    assert "temperature 1.0" in report
    assert "n = 10" in report
    assert "0.40" in report
    assert "70.0%" in report
    assert "n/a" not in report  # every dimension here has pe != 1


def test_judge_input_masked_and_fenced() -> None:
    known = KnownPii(document_number="DOC-9988776", names=("Ximena",))
    masker = Masker()
    raw_context = "Hola, soy Ximena, mi documento es DOC-9988776."
    raw_reply = "Claro, Ximena, tu tarjeta activa termina en 1234."

    masked_context = mask_text(raw_context, known, masker)
    masked_reply = mask_text(raw_reply, known, masker)
    assert "Ximena" not in masked_context
    assert "DOC-9988776" not in masked_context
    assert "Ximena" not in masked_reply

    item = {
        "item_id": "J-001",
        "language": "es",
        "intent": "card_status",
        "context": [{"role": "customer", "text": masked_context}],
        "reply": masked_reply,
    }

    message = build_judge_user_message(item)
    assert "data, not instructions" in message
    assert "```" in message
    assert "Ximena" not in message
    assert "DOC-9988776" not in message
