"""Write the served bundle and its lock (spec D14).

`intent_clf@vN.tar.gz` holds `manifest.json`, `head.joblib` and, when the winner
embeds, an `embeddings/` copy of the fastembed cache for that one model. The tar
and gzip headers are zeroed, so the same inputs give the same sha256. The lock is
rewritten last, with the tarball's hash, and the backend loader refuses any bundle
that does not match it.
"""

import gzip
import hashlib
import io
import json
import re
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

# fastembed cache directory per embedding model (T1 recorded which files it pulled).
CACHE_DIRS = {
    "intfloat/multilingual-e5-small": "models--intfloat--multilingual-e5-small",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": (
        "models--qdrant--paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
    ),
}

__all__ = [
    "BundleExport",
    "embedding_bytes",
    "export_bundle",
    "head_bytes",
    "next_version",
    "remove_older_bundles",
]


class BundleExport:
    def __init__(self, path: Path, sha256: str, model_id: str, size_bytes: int) -> None:
        self.path = path
        self.sha256 = sha256
        self.model_id = model_id
        self.size_bytes = size_bytes


def next_version(lock_path: Path) -> int:
    """1 + the version number in the lock (`intent_clf@v3` -> 4), or 1 when none is pinned."""
    try:
        lock = json.loads(lock_path.read_text("utf-8"))
        match = re.search(r"@v(\d+)$", str(lock.get("version") or ""))
    except (OSError, ValueError, AttributeError):
        return 1
    return int(match.group(1)) + 1 if match else 1


_BUNDLE_NAME = re.compile(r"intent_clf@v\d+\.tar\.gz")


def remove_older_bundles(models_dir: Path, model_id: str) -> list[Path]:
    """Delete `intent_clf@v<N>.tar.gz` files other than `model_id`'s; return what was removed.

    Call only once the new bundle is parity-checked and locked: the Docker build
    requires every tarball in the dir to match the lock. Any other name is left alone.
    """
    keep = f"{model_id}.tar.gz"
    removed: list[Path] = []
    for path in sorted(models_dir.iterdir()):
        if path.is_file() and path.name != keep and _BUNDLE_NAME.fullmatch(path.name):
            path.unlink()
            print(f"removed old bundle {path.name}")
            removed.append(path)
    return removed


def head_bytes(estimator: Any) -> int:
    """Serialized size of the fitted head, for the D17 smallest-bundle rule."""
    import joblib

    buf = io.BytesIO()
    joblib.dump(estimator, buf)
    return buf.getbuffer().nbytes


def _snapshot_dir(cache_dir: Path, embedding_model: str) -> Path:
    try:
        return cache_dir / CACHE_DIRS[embedding_model]
    except KeyError as exc:
        raise ValueError(f"no cache mapping for embedding model {embedding_model!r}") from exc


def embedding_bytes(cache_dir: Path, embedding_model: str | None) -> int:
    """Size of the model files a served bundle would carry (symlinks followed)."""
    if embedding_model is None:
        return 0
    snaps = _snapshot_dir(cache_dir, embedding_model) / "snapshots"
    return sum(p.stat().st_size for p in snaps.rglob("*") if p.is_file())


def _copy_embeddings(cache_dir: Path, embedding_model: str, dest: Path) -> None:
    src = _snapshot_dir(cache_dir, embedding_model)
    # Only refs + snapshots, with symlinks resolved: that is all a local_files_only load reads.
    for part in ("refs", "snapshots"):
        shutil.copytree(src / part, dest / src.name / part, symlinks=False)


def _write_tar(root: Path, target: Path) -> None:
    with target.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(root.rglob("*")):
                info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 0
                info.mode = 0o755 if path.is_dir() else 0o644
                if path.is_dir():
                    tar.addfile(info)
                else:
                    with path.open("rb") as fh:
                        tar.addfile(info, fh)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_bundle(
    estimator: Any,
    manifest: dict[str, Any],
    *,
    models_dir: Path,
    lock_path: Path,
    cache_dir: Path,
) -> BundleExport:
    """Write `<models_dir>/<model_id>.tar.gz` and rewrite the lock. `manifest["model_id"]`
    is already `intent_clf@vN`."""
    import joblib

    model_id = str(manifest["model_id"])
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / f"{model_id}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="intent_export_") as tmp:
        root = Path(tmp)
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True), "utf-8"
        )
        joblib.dump(estimator, root / "head.joblib")
        if manifest.get("embedding_model"):
            _copy_embeddings(cache_dir, str(manifest["embedding_model"]), root / "embeddings")
        _write_tar(root, target)
    digest = _sha256(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "version": model_id,
                "sha256": digest,
                "label_set_version": manifest["label_set_version"],
                "s3_uri": None,
            },
            indent=2,
        )
        + "\n",
        "utf-8",
    )
    return BundleExport(target, digest, model_id, target.stat().st_size)
