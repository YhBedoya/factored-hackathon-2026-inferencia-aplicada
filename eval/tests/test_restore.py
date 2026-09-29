"""D14: the post-restore diff aborts on a leftover app row."""

import pytest

from eval.harness.restore import RestoreDiffError, diff_rows


def test_leftover_row_aborts() -> None:
    golden = [{"product_id": "P1", "locked": False}]
    clone = [*golden, {"product_id": "P2", "locked": True}]
    with pytest.raises(RestoreDiffError) as exc:
        diff_rows("app.card_controls", golden, clone)
    assert exc.value.table == "app.card_controls"
    assert exc.value.key == "P2"
    diff_rows("app.card_controls", golden, list(golden))
