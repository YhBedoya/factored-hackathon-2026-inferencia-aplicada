"""`uv run python -m contracts` -- validate changed raw partitions (D17).

Reads `RUN_ID` (default: a UTC timestamp) so contracts and load share one run id.
Exits 2 on a structural break so `make data` stops.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from contracts import run
from ingest import RAW_DIR, REPO_ROOT, load_manifest


def main() -> int:
    run_id = os.environ.get("RUN_ID") or datetime.now(UTC).strftime("%Y%m%dt%H%M%S")
    return run(RAW_DIR, load_manifest(), REPO_ROOT / "data" / "quality", run_id)


if __name__ == "__main__":
    sys.exit(main())
