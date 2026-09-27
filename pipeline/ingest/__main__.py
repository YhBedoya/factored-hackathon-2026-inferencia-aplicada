"""`uv run python -m ingest` -- reads `SOURCE` from the env and ingests.

`SOURCE=s3` (default) or `SOURCE=local:<path>` (D6). Prints `ingested=N
skipped=M` so `make data` and the Verify steps can check idempotency.
"""

from __future__ import annotations

import os

from ingest import load_manifest, save_manifest


def main() -> None:
    source = os.environ.get("SOURCE", "s3")
    manifest = load_manifest()

    if source == "s3":
        from ingest import s3

        changed, ingested, skipped = s3.ingest(manifest)
    elif source.startswith("local:"):
        from ingest import local

        changed, ingested, skipped = local.ingest(source[len("local:") :], manifest)
    else:
        raise SystemExit(f"Unknown SOURCE: {source!r} (expected 's3' or 'local:<path>')")

    manifest.update(changed)
    save_manifest(manifest)
    print(f"ingested={ingested} skipped={skipped}")


if __name__ == "__main__":
    main()
