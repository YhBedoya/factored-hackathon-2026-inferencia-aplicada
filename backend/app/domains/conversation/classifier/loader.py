"""Load the pinned intent-classifier bundle, or refuse with a reason (spec D11, D14).

The lock (``<model_dir>/../model.lock``) pins the bundle's version and sha256. Every
check runs before ``joblib.load``, which is pickle: the tarball hash is verified
first, so a tampered bundle is never unpickled. No network is touched.
"""

import atexit
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from app.domains.conversation.classifier.adapter import ClassifierAdapter, IntentClassifier
from app.domains.conversation.classifier.scorers import Embedder, SklearnScorer
from app.domains.conversation.intent_registry import classifier_labels, load_registry


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_classifier(model_dir: Path) -> tuple[IntentClassifier | None, str]:
    """Return ``(classifier, "ok")`` or ``(None, reason)``; never raises for a bad bundle."""
    lock_path = model_dir.parent / "model.lock"
    try:
        lock = _read_json(lock_path)
    except (OSError, ValueError):
        return None, f"model.lock missing or unreadable at {lock_path}"
    if not isinstance(lock, dict):
        return None, "model.lock is not a JSON object"
    version, pinned_sha = lock.get("version"), lock.get("sha256")
    if not version or not pinned_sha:
        return None, "model.lock has no pinned version"
    # The version names a file: refuse anything that could leave model_dir.
    if Path(str(version)).name != str(version):
        return None, "model.lock version is not a plain file name"

    tarball = model_dir / f"{version}.tar.gz"
    if not tarball.is_file():
        return None, f"bundle {tarball.name} not found in {model_dir}"
    if _sha256(tarball) != pinned_sha:
        return None, f"sha256 of {tarball.name} differs from model.lock"

    registry_version = load_registry().label_set_version
    if lock.get("label_set_version") != registry_version:
        return None, (
            f"model.lock label_set_version {lock.get('label_set_version')} "
            f"!= registry {registry_version}"
        )

    work = Path(tempfile.mkdtemp(prefix="intent_clf_"))
    # The embedder reads its files lazily, so the dir lives as long as the process.
    atexit.register(shutil.rmtree, work, ignore_errors=True)
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            tar.extractall(work, filter="data")
        manifest = _read_json(work / "manifest.json")
        if manifest.get("label_set_version") != registry_version:
            return None, (
                f"manifest label_set_version {manifest.get('label_set_version')} "
                f"!= registry {registry_version}"
            )
        labels = tuple(manifest["labels"])
        unknown = set(labels) - set(classifier_labels())
        if unknown:
            return None, f"manifest labels not in the registry: {sorted(unknown)}"

        import joblib

        estimator = joblib.load(work / "head.joblib")
        embedding_model = manifest.get("embedding_model")
        embedder = Embedder(embedding_model, work / "embeddings") if embedding_model else None
        scorer = SklearnScorer(estimator, labels, embedder)
        return (
            ClassifierAdapter(
                scorer,
                tau=float(manifest["tau"]),
                version=str(manifest["model_id"]),
                label_set_version=int(manifest["label_set_version"]),
            ),
            "ok",
        )
    except Exception as exc:  # a bad bundle must never stop app startup
        return None, f"bundle unreadable: {type(exc).__name__}: {exc}"
