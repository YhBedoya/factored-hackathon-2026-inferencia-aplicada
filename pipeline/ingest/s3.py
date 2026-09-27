"""S3 ingest source (`SOURCE=s3`, the default).

Lists `s3://$S3_BUCKET/$S3_PREFIX` and converts every matching CSV to
Parquet. Bucket, prefix and credentials come only from env vars / an AWS
profile (D10, R10) -- never written to a tracked file.
"""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import boto3

from ingest import (
    ManifestEntry,
    classify_relative_key,
    csv_to_parquet,
    destination_parquet_path,
)


def ingest(manifest: dict[str, ManifestEntry]) -> tuple[dict[str, ManifestEntry], int, int]:
    """Ingest every known table CSV under `s3://$S3_BUCKET/$S3_PREFIX`.

    Returns `(changed_entries, ingested, skipped)`; the caller merges
    `changed_entries` into `manifest` and persists it.
    """
    bucket = os.environ["S3_BUCKET"]
    prefix = os.environ["S3_PREFIX"].strip("/")
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    client = session.client("s3")

    changed: dict[str, ManifestEntry] = {}
    ingested = skipped = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            relative_key = key[len(prefix) + 1 :]
            table = classify_relative_key(relative_key)
            if table is None:
                continue

            etag = obj["ETag"].strip('"')
            size = obj["Size"]
            dest = destination_parquet_path(table, relative_key)
            existing = manifest.get(relative_key)
            if (
                existing is not None
                and existing.get("source") == "s3"
                and existing.get("etag") == etag
                and existing.get("size") == size
                and dest.exists()
            ):
                skipped += 1
                continue

            tmp_fd, tmp_name = tempfile.mkstemp(suffix=".csv")
            os.close(tmp_fd)
            tmp_path = Path(tmp_name)
            try:
                client.download_file(bucket, key, str(tmp_path))
                csv_to_parquet(tmp_path, dest)
            finally:
                tmp_path.unlink(missing_ok=True)

            changed[relative_key] = ManifestEntry(
                source="s3",
                key=relative_key,
                size=size,
                etag=etag,
                downloaded_at=datetime.now(UTC).isoformat(),
            )
            ingested += 1

    return changed, ingested, skipped
