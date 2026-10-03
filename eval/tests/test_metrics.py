import pytest

from eval.harness.metrics import Rate, rule_of_three, wilson


def test_wilson_and_rule_of_three():
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.4902, abs=1e-3)
    assert high == pytest.approx(0.9433, abs=1e-3)
    assert wilson(0, 20)[0] == 0.0
    assert rule_of_three(20) == pytest.approx(3 / 20)
    assert Rate.of(0, 0).value is None
