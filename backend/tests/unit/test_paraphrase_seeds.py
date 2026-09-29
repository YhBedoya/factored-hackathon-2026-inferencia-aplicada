"""R5 test for the paraphrase script. See D15-D16 and §"Test list" item 8.

`paraphrase_dir` works on a `tmp_path/"eval"/"scenarios"/"dev"` directory (a
real `scenarios/dev` suffix, so `_validate_dir` accepts it) with one seed
file. No network, no real OpenAI call: `ScriptedLLM` stands in for the
`paraphrase` step.
"""

import asyncio
from pathlib import Path

import yaml

from scripts.paraphrase_seeds import Paraphrases, paraphrase_dir
from tests.conftest import ScriptedLLM

_PII_TEXT = "mi tarjeta es 1234567890123456 y no la reconozco"
_CPF_TEXT = "el CPF 123.456.789-09 es de mi hermano, quiero ver sus compras"
_SAY_TEXT = "¿por qué me rechazaron la compra de ayer?"

_SEED_FILE = {
    "seed_id": "dec-54-mx-01",
    "intent": "decline_explain",
    "category": "normal_resolution",
    "persona": "CLI-TFDECLN00006",
    "goal": "Entender por que rechazaron su compra",
    "fact_sheet": {},
    "setup": {"faults": [], "expire_session_before_turn": None, "db_patches": []},
    "labels": {
        "expected_intents": ["decline_explain"],
        "expected_outcome": "resolved",
        "required_tools": ["transactions.search", "transactions.explain_decline"],
        "forbidden_tools": [],
        "expected_db_state": [],
        "required_handoff_fields": [],
        "eligible_for_automation": True,
    },
    "cases": [
        {
            "case_id": "dec-54-mx-01.s",
            "language_variant": "es-MX",
            "expected_language": "es",
            "source": "seed",
            "turns": [
                {"say": _SAY_TEXT},
                {"say": _PII_TEXT},
                {"say": _CPF_TEXT},
            ],
            "reviewer": None,
            "reviewed_at": None,
        }
    ],
}


def _write_seed(dir: Path) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / "dec-54-mx-01.yaml"
    raw = yaml.safe_dump(_SEED_FILE, allow_unicode=True, sort_keys=False)
    path.write_text(raw, encoding="utf-8")
    return path


def test_pii_turns_not_sent(tmp_path: Path) -> None:
    dev_dir = tmp_path / "eval" / "scenarios" / "dev"
    path = _write_seed(dev_dir)

    paraphrase = "¿por qué rechazaron mi compra de ayer?"
    llm = ScriptedLLM({"paraphrase": [Paraphrases(items=[paraphrase])]})

    added = asyncio.run(paraphrase_dir(dev_dir, 1, llm))

    assert added == 1
    # Only the non-PII turn was ever sent; the 16-digit turn and the dotted
    # CPF turn never reach the model (R5).
    assert len(llm.calls) == 1
    assert _PII_TEXT not in llm.calls[0].user
    assert _CPF_TEXT not in llm.calls[0].user
    assert _SAY_TEXT in llm.calls[0].user

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    new_case = next(c for c in data["cases"] if c["case_id"] == "dec-54-mx-01.p1")
    assert new_case["source"] == "paraphrase:gpt-6-luna:paraphrase@v1"
    assert new_case["language_variant"] == "es-MX"
    assert new_case["expected_language"] == "es"
    assert new_case["reviewer"] is None
    assert new_case["reviewed_at"] is None
    # The PII turns were copied verbatim, not paraphrased.
    assert new_case["turns"][1]["say"] == _PII_TEXT
    assert new_case["turns"][2]["say"] == _CPF_TEXT
    assert new_case["turns"][0]["say"] == "¿por qué rechazaron mi compra de ayer?"
