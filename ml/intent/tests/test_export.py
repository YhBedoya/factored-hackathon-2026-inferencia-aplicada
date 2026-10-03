"""T40: a successful export leaves only the locked tarball; nothing else is deleted."""

from pathlib import Path

from ml.intent.export import remove_older_bundles


def _populate(d: Path) -> None:
    for name in (
        "intent_clf@v1.tar.gz",
        "intent_clf@v2.tar.gz",
        "intent_clf@v3.tar.gz",
        ".gitkeep",
        "notes.txt",
        "other@v1.tar.gz",
    ):
        (d / name).write_text("x")


def test_cleanup_keeps_only_locked_bundle_and_unrelated_files(tmp_path: Path) -> None:
    _populate(tmp_path)
    (tmp_path / "intent_clf@v9.tar.gz").mkdir()  # a directory with a matching name stays
    remove_older_bundles(tmp_path, "intent_clf@v3")
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        ".gitkeep",
        "intent_clf@v3.tar.gz",
        "intent_clf@v9.tar.gz",
        "notes.txt",
        "other@v1.tar.gz",
    ]
