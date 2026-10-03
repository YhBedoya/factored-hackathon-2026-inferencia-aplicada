"""Local-mirror ingest source (`SOURCE=local:<path>`).

Walks an existing S3 mirror already on disk. It needs no AWS credentials and
never creates a boto3 client -- `local:<path>` is meant for a dev's own copy
of `s3://$S3_BUCKET/$S3_PREFIX` (D6).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ingest import (
    REPO_ROOT,
    ManifestEntry,
    classify_relative_key,
    csv_to_parquet,
    destination_parquet_path,
)

_CHUNK_SIZE = 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest(
    mirror_path: str, manifest: dict[str, ManifestEntry]
) -> tuple[dict[str, ManifestEntry], int, int]:
    """Ingest every known table CSV under `mirror_path`.

    `mirror_path` (the part after `local:`) is resolved against the repo
    root when relative, so `SOURCE=local:data` reads `<repo root>/data`
    regardless of cwd.

    Returns `(changed_entries, ingested, skipped)`; the caller merges
    `changed_entries` into `manifest` and persists it.
    """
    root = Path(mirror_path)
    if not root.is_absolute():
        root = REPO_ROOT / root

    changed: dict[str, ManifestEntry] = {}
    ingested = skipped = 0

    for csv_path in sorted(root.rglob("*.csv")):
        relative_key = str(PurePosixPath(csv_path.relative_to(root)))
        table = classify_relative_key(relative_key)
        if table is None:
            continue

        size = csv_path.stat().st_size
        digest = _sha256(csv_path)
        dest = destination_parquet_path(table, relative_key)
        existing = manifest.get(relative_key)
        if (
            existing is not None
            and existing.get("source") == "local"
            and existing.get("sha256") == digest
            and existing.get("size") == size
            and dest.exists()
        ):
            skipped += 1
            continue

        csv_to_parquet(csv_path, dest)
        changed[relative_key] = ManifestEntry(
            source="local",
            key=relative_key,
            size=size,
            sha256=digest,
            downloaded_at=datetime.now(UTC).isoformat(),
        )
        ingested += 1

    return changed, ingested, skipped
