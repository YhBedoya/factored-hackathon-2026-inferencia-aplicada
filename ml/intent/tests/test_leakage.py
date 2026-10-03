"""Done-when 5: a training text equal to an eval text after normalization is flagged."""

import shutil
from pathlib import Path

from ml.intent.data_io import accepted_items, load_files
from ml.intent.leakage import eval_texts, find_leaks
from ml.intent.train import item_label

FIXTURE = Path(__file__).parent / "fixtures" / "dataset"


def test_dev_text_with_changed_case_and_accents_is_flagged(tmp_path: Path) -> None:
    data = tmp_path / "dataset"
    shutil.copytree(FIXTURE, data)
    train = [i.text for i in accepted_items(load_files(data))]
    evals = eval_texts()
    assert evals
    assert find_leaks(train, evals) == []

    dev_text = next(t for t in evals if "a" in t.casefold())
    leaked = dev_text.upper().replace("A", "Á", 1) + "!"
    assert (leaked, dev_text) in find_leaks([*train, leaked], evals)


def test_same_text_under_two_labels_fails() -> None:
    from ml.intent.check import duplicate_findings

    files = load_files(FIXTURE)
    donor = next(f for f in files if f.items and f.items[0].accepted)
    other = next(
        f
        for f in files
        if f.items and item_label(f.items[0], f.class_) != item_label(donor.items[0], donor.class_)
    )
    other.items[0] = other.items[0].model_copy(
        update={"text": donor.items[0].text, "accepted": True}
    )
    problems, _ = duplicate_findings(files)
    assert any("different labels" in p for p in problems)


def test_cell_needs_29_or_more_accepted_items() -> None:
    from ml.intent.check import cell_size_problems
    from ml.intent.data_io import DataFile, DataItem

    def cell(n: int) -> DataFile:
        items = [
            DataItem(
                text=f"t{k}",
                intents=["card_block"],
                status="clear",
                family="card_block-es-co-01",
                slot="plain",
                origin="seed",
                generator="g",
                accepted=True,
            )
            for k in range(n)
        ]
        return DataFile(provenance="p", version=1, locale="es-co", class_="card_block", items=items)

    assert cell_size_problems([cell(31)], 30) == []
    assert cell_size_problems([cell(29)], 30) == []
    assert len(cell_size_problems([cell(28)], 30)) == 1
