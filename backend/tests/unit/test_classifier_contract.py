"""Classifier adapter contract (spec D9/D10). The bundle-loading cases live in T19's tests."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from app.domains.conversation.classifier import load_classifier
from app.domains.conversation.flows.card_block import (
    PERMANENT_BLOCK_LABEL,
    TEMPORARY_LOCK_LABEL,
)
from app.domains.conversation.intent_registry import classifier_labels, load_registry
from app.domains.conversation.schemas import NLUResult
from app.domains.conversation.state import Pending
from app.domains.localization import mask_card
from tests.stub_classifier import make_stub_classifier


def _predict(mapping: dict[str, dict[str, float]], text: str, pending: Pending | None = None):
    clf = make_stub_classifier(mapping)
    return clf.predict(text, pending=pending, country="MX", previous_language="es")


def test_below_tau_is_ambiguous_without_a_guess() -> None:
    res = _predict({"hola": {"card_status": 0.4}}, "hola")
    assert (res.status, res.intents) == ("ambiguous", [])


@pytest.mark.parametrize(
    ("label", "text", "status", "topic"),
    [
        ("pix_boleto", "quiero pagar con pix", "out_of_market", "pix_boleto"),
        ("loans", "quiero un prestamo", "out_of_scope", "loans"),
    ],
)
def test_scope_class_gives_status_and_topic(label: str, text: str, status: str, topic: str) -> None:
    res = _predict({text: {label: 0.9}}, text)
    assert (res.status, res.intents, res.slots.topic) == (status, [], topic)


def test_bare_card_block_asks_lock_vs_block() -> None:
    res = _predict(
        {"quiero bloquear mi tarjeta": {"card_block": 0.9}}, "quiero bloquear mi tarjeta"
    )
    assert (res.status, res.clarification, res.intents) == (
        "ambiguous",
        "lock_vs_block",
        ["card_block"],
    )


def test_picker_label_sets_card_hint() -> None:
    text = f"Crédito {mask_card('6475')} · Activa"
    res = _predict({}, text)
    assert res.slots.card_hint == "last4:6475"


@pytest.mark.parametrize("language", ["es", "pt"])
def test_chip_labels_resolve_block_kind(language: str) -> None:
    pending: Pending = {"flow": "card_block", "node": "block_kind", "awaiting_slot": "block_kind"}
    for labels, expected in (
        (TEMPORARY_LOCK_LABEL, "temporary_lock"),
        (PERMANENT_BLOCK_LABEL, "permanent_block"),
    ):
        res = _predict({}, labels[language], pending)  # type: ignore[index]
        assert res.slots.block_kind == expected
        assert res.status == "clear"


def test_never_injection_suspected_and_always_valid() -> None:
    for label in classifier_labels():
        res = _predict({"x": {label: 0.95}}, "x")
        assert res.status != "injection_suspected"
        NLUResult.model_validate(res.model_dump())


def _build_bundle(root: Path, *, label_set_version: int, sha256: str | None = None) -> Path:
    """A real tiny C2 bundle (tfidf + logistic regression on 4 texts) plus its lock."""
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline

    labels = ["card_block", "card_status"]
    texts = ["bloquear tarjeta", "bloquea mi tarjeta", "estado de tarjeta", "tarjeta activa"]
    pipe = make_pipeline(TfidfVectorizer(), LogisticRegression(C=10))
    pipe.fit(texts, ["card_block", "card_block", "card_status", "card_status"])

    src = root / "src"
    src.mkdir()
    joblib.dump(pipe, src / "head.joblib")
    manifest = {
        "model_id": "intent_clf@v1",
        "tau": 0.5,
        "labels": labels,
        "label_set_version": label_set_version,
        "embedding_model": None,
    }
    (src / "manifest.json").write_text(json.dumps(manifest))
    models = root / "intent" / "models"
    models.mkdir(parents=True)
    tarball = models / "intent_clf@v1.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        for name in ("manifest.json", "head.joblib"):
            tar.add(src / name, arcname=name)
    lock = {
        "version": "intent_clf@v1",
        "sha256": sha256 or hashlib.sha256(tarball.read_bytes()).hexdigest(),
        "label_set_version": label_set_version,
        "s3_uri": None,
    }
    (root / "intent" / "model.lock").write_text(json.dumps(lock))
    return models


def test_stale_label_set_version_refuses_to_load(tmp_path: Path) -> None:
    stale = load_registry().label_set_version + 1
    clf, reason = load_classifier(_build_bundle(tmp_path, label_set_version=stale))
    assert clf is None
    assert "label_set_version" in reason


def test_wrong_sha256_refuses_before_unpickling(tmp_path: Path) -> None:
    models = _build_bundle(
        tmp_path, label_set_version=load_registry().label_set_version, sha256="0" * 64
    )
    clf, reason = load_classifier(models)
    assert clf is None
    assert "sha256" in reason


def test_good_bundle_loads_and_predicts(tmp_path: Path) -> None:
    models = _build_bundle(tmp_path, label_set_version=load_registry().label_set_version)
    clf, reason = load_classifier(models)
    assert clf is not None, reason
    assert clf.version == "intent_clf@v1"
    res = clf.predict("bloquear tarjeta", pending=None, country="MX", previous_language="es")
    assert res.status == "ambiguous"  # bare card_block asks lock_vs_block
    assert res.intents == ["card_block"]


def test_truncated_head_with_matching_sha256_returns_reason(tmp_path: Path) -> None:
    models = _build_bundle(tmp_path, label_set_version=load_registry().label_set_version)
    tarball = models / "intent_clf@v1.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        manifest = json.dumps(
            {
                "model_id": "intent_clf@v1",
                "tau": 0.5,
                "labels": ["card_block"],
                "label_set_version": load_registry().label_set_version,
                "embedding_model": None,
            }
        ).encode()
        for name, data in (("manifest.json", manifest), ("head.joblib", b"\x80\x04\x95")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    lock_path = tmp_path / "intent" / "model.lock"
    lock = json.loads(lock_path.read_text())
    lock["sha256"] = hashlib.sha256(tarball.read_bytes()).hexdigest()
    lock_path.write_text(json.dumps(lock))
    clf, reason = load_classifier(models)
    assert clf is None
    assert reason
