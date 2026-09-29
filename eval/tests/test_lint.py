import pytest

from eval.harness.lint import SuiteLintError, lint_suite
from eval.scenarios.schema import Case, LabelsBlock, SetupBlock, Turn

WRITE = {"cards.lock_card"}


def _case(
    seed_id: str, persona: str, tools: list[str], case_id: str | None = None
) -> Case:
    return Case(
        seed_id=seed_id,
        intent="card_block",
        category="normal_resolution",
        persona=persona,
        goal="g",
        fact_sheet={},
        setup=SetupBlock(),
        labels=LabelsBlock(
            expected_intents=["card_block"],
            expected_outcome="resolved",
            required_tools=tools,
            forbidden_tools=[],
            eligible_for_automation=True,
        ),
        case_id=case_id or f"{seed_id}.s",
        language_variant="es-CO",
        expected_language="es",
        source="seed",
        turns=[Turn(say="hola")],
        reviewer=None,
        reviewed_at=None,
    )


def test_writer_customer_reused_refused() -> None:
    with pytest.raises(SuiteLintError) as exc:
        lint_suite(
            [_case("a-w", "CLI-1", ["cards.lock_card"]), _case("a-r", "CLI-1", [])],
            WRITE,
        )
    assert exc.value.seed_ids == ["a-r", "a-w"]

    own = [
        _case("a-w", "CLI-1", ["cards.lock_card"]),
        _case("a-w", "CLI-1", ["cards.lock_card"], case_id="a-w.p1"),
        _case("a-r", "CLI-2", []),
    ]
    lint_suite(own, WRITE)
