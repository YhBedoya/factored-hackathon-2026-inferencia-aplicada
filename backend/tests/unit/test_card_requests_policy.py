"""Spec T1: the card-requests policy loads and refuses bad copies (R8)."""

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.policy.card_requests import load_card_requests_policy

_REAL = Path(__file__).resolve().parents[3] / "policies" / "card_requests.yaml"


def test_card_requests_policy_loads(tmp_path: Path) -> None:
    policy = load_card_requests_policy()
    assert policy.credit_limit_bounds["USD"].min == Decimal("1000")
    assert policy.interest_rate_by_country["MX"] == Decimal("31.50")
    assert "other" in policy.cancel_reasons

    text = _REAL.read_text(encoding="utf-8")

    headerless = tmp_path / "headerless.yaml"
    headerless.write_text(text.replace("provenance: team-generated-synthetic\n", ""))
    with pytest.raises(ValidationError):
        load_card_requests_policy(headerless)

    inverted = tmp_path / "inverted.yaml"
    inverted.write_text(
        text.replace('USD: {min: "1000", max: "50000"}', 'USD: {min: "50000", max: "1000"}')
    )
    with pytest.raises(ValidationError):
        load_card_requests_policy(inverted)
