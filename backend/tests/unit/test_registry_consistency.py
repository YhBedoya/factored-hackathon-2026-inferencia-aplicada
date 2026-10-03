"""D13: the intent registry, the `Intent` Literal and the `nlu@v7` prompt list agree."""

import re
import sys
from pathlib import Path
from typing import get_args

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from eval.harness.nlu_eval import (  # noqa: E402
    PERSONAS_PATH,
    SMOKE_PATH,
    derive_suite_items,
    load_smoke_items,
)
from eval.scenarios.schema import load_dir  # noqa: E402

from app.domains.conversation import graph  # noqa: E402
from app.domains.conversation.intent_registry import (  # noqa: E402
    classifier_labels,
    load_registry,
)
from app.domains.conversation.schemas import Intent  # noqa: E402

_PROMPT = _REPO_ROOT / "backend/app/domains/conversation/prompts/nlu@v7.md"


def _prompt_intents() -> set[str]:
    text = _PROMPT.read_text(encoding="utf-8")
    section = text.split("## Lista cerrada de intents (26)", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"`([a-z_]+)`", section))


def test_registry_matches_literal_and_prompt() -> None:
    registry = {r.intent for r in load_registry().intents}
    assert len(registry) == 26
    assert registry == set(get_args(Intent))
    assert registry == _prompt_intents()


def test_classifier_labels() -> None:
    assert classifier_labels() == (
        "card_status",
        "balance_due",
        "decline_explain",
        "transaction_search",
        "pending_reversal_explain",
        "card_block",
        "card_unlock",
        "unrecognized_charge",
        "replacement_request",
        "human_request",
        "general_question",
        "greeting",
        "thanks_close",
        "affirm",
        "deny",
        "pix_boleto",
        "loans",
        "accounts",
        "investments",
        "insurance",
        "transfers",
        "new_card",
        "other",
    )


def test_built_tables_equal_the_original_literals() -> None:
    assert graph._MANAGEMENT_INTENTS == {"greeting", "thanks_close", "affirm", "deny"}
    assert graph._INTENT_NODES == {
        "card_status": "card_info",
        "balance_due": "card_info",
        "card_block": "card_block",
        "card_unlock": "card_unlock",
        "replacement_request": "replacement",
        "unrecognized_charge": "unrecognized_charge",
        "decline_explain": "decline_explain",
        "transaction_search": "tx_search",
        "pending_reversal_explain": "tx_explain",
    }


def test_every_classifier_intent_has_an_eval_item() -> None:
    items = load_smoke_items(SMOKE_PATH) + derive_suite_items(
        load_dir(_REPO_ROOT / "eval" / "scenarios" / "dev"), PERSONAS_PATH
    )
    seen = {intent for item in items for intent in item.expected_intents}
    missing = {r.intent for r in load_registry().intents if r.classifier} - seen
    assert not missing


# Scope topics added after the served bundle was trained. The classifier loads
# (its labels are a subset of the registry) but never predicts them until the
# next retrain adds their training data; then drop them from this set.
_NOT_YET_TRAINED = {"new_card"}


def test_every_classifier_label_has_training_data_in_all_locales() -> None:
    data = _REPO_ROOT / "ml" / "intent" / "data"
    locales = ("es-mx", "es-co", "es-ar", "pt-br")
    missing = [
        f"{locale}/{label}.yaml"
        for label in classifier_labels()
        if label not in _NOT_YET_TRAINED
        for locale in locales
        if not (data / locale / f"{label}.yaml").is_file()
    ]
    assert not missing
