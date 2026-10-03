import pytest
import yaml

from eval.harness.nlu_eval import NluItem, NLUResult, derive_suite_items, score
from eval.scenarios.schema import load_dir


def _write_seed(directory, personas):
    seed = {
        "seed_id": "s1",
        "intent": "card_status",
        "category": "normal_resolution",
        "persona": "CLI-1",
        "goal": "g",
        "setup": {},
        "labels": {
            "expected_intents": ["card_status", "card_block"],
            "expected_outcome": "resolved",
            "required_tools": [],
            "forbidden_tools": [],
            "eligible_for_automation": True,
        },
        "cases": [
            {
                "case_id": "s1.s",
                "language_variant": "es-MX",
                "expected_language": "es",
                "source": "seed",
                "turns": [{"otp": True}, {"say": "primero"}, {"say": "segundo"}],
            }
        ],
    }
    (directory / "s1.yaml").write_text(yaml.safe_dump(seed))
    personas.write_text(yaml.safe_dump({"personas": [{"customer_id": "CLI-1", "country": "MX"}]}))


def _nlu(intents):
    return NLUResult(language="es", intents=intents, status="clear")


def test_derive_and_score(tmp_path):
    scenarios = tmp_path / "dev"
    scenarios.mkdir()
    _write_seed(scenarios, tmp_path / "personas.yaml")
    (item,) = derive_suite_items(load_dir(scenarios), tmp_path / "personas.yaml")
    assert (item.text, item.country, item.pending) == ("primero", "MX", None)
    assert item.expected_intents == ["card_status", "card_block"]
    assert item.language_variant == "es-MX"

    def mk(i, intents, variant):
        return NluItem(f"i{i}", "t", None, None, intents, "es", variant)

    items = [
        mk(0, ["card_status"], "es-MX"),
        mk(1, ["card_status"], "es-MX"),
        mk(2, ["card_block"], None),
        mk(3, ["card_status", "card_block"], "es-CO"),
    ]
    # Fake run_nlu: right, right, wrong intent, half of the multi-intent item.
    preds = [
        _nlu(["card_status"]),
        _nlu(["card_status"]),
        _nlu(["card_status"]),
        _nlu(["card_status"]),
    ]
    r = score(items, preds)
    # card_status: tp 3, fp 1, fn 0 -> P .75, R 1, F1 6/7.
    # card_block: tp 0, fp 0, fn 2 -> P 0, R 0, F1 0.
    assert r["precision"] == pytest.approx(0.375)
    assert r["recall"] == pytest.approx(0.5)
    assert r["f1"] == pytest.approx(3 / 7)
    assert (r["exact_set"]["k"], r["exact_set"]["n"]) == (2, 4)
    assert (r["multi_intent"]["k"], r["multi_intent"]["n"]) == (0, 1)
    assert r["by_language_variant"]["unknown"]["k"] == 0
    assert r["by_language_variant"]["es-MX"]["k"] == 2
    assert r["status_accuracy"] is None
