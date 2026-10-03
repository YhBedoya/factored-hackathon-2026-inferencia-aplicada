from eval.harness.runner import llm_unreachable


def test_all_unavailable_aborts() -> None:
    assert llm_unreachable(5, ["unavailable"] * 5)
    assert not llm_unreachable(5, [])  # baseline may make no LLM call at all
    assert not llm_unreachable(5, ["unavailable", "ok", "unavailable"])
    assert not llm_unreachable(4, ["unavailable"] * 4)
