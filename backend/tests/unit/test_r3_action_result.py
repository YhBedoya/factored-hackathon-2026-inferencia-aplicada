"""R3 (no "done" without `verified = true`) contract test.

See `docs/specs/d2-k-write-contracts.md` §"Test list".
"""

import pytest
from pydantic import ValidationError

from app.core.actions import ActionResult

_BASE = {"tool": "cards.lock_card", "status": "applied", "readback": {"locked": True}}


def test_verified_is_required() -> None:
    """`verified` has no default (R3): omitting it fails validation."""
    with pytest.raises(ValidationError):
        ActionResult.model_validate(_BASE)

    assert ActionResult.model_validate({**_BASE, "verified": True}).verified is True
