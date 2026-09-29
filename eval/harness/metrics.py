"""Pure metric functions for the eval report (D16, 05 §6).

Input is a list of per-case verdict dicts. Keys read here (all optional except
``verdict``); T18/T19 produce them:

- ``verdict``: ``passed`` | ``failed`` | ``not_run``. ``not_run`` cases are left
  out of every denominator.
- ``language_variant``, ``segment``: breakdown keys.
- ``in_scope`` (default True), ``expected_outcome``, ``outcome``: outcomes are
  ``resolved``, ``clarified``, ``abstained`` or ``handoff:<queue>``.
- ``unsafe`` (bool), ``clarification_required`` (bool | None).
- ``turn_latencies_ms`` (list), ``conversation_latency_ms``, ``cost_usd``.

Nothing here imports ``app`` (D25, D34).
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from math import ceil, sqrt
from typing import Any

from pydantic import BaseModel

Verdict = dict[str, Any]

LABEL = "offline evaluation"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes in n trials; (0, 0) when n = 0."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rule_of_three(n: int) -> float | None:
    """95% upper bound on the rate when 0 events were seen in n trials."""
    return 3 / n if n > 0 else None


class Rate(BaseModel):
    """A rate with its counts. ``value`` and ``ci`` are None when n = 0 ("not defined")."""

    k: int
    n: int
    value: float | None
    ci: tuple[float, float] | None

    @classmethod
    def of(cls, k: int, n: int) -> "Rate":
        if n <= 0:
            return cls(k=k, n=0, value=None, ci=None)
        return cls(k=k, n=n, value=k / n, ci=wilson(k, n))

    @property
    def defined(self) -> bool:
        return self.value is not None


def percentiles(
    values: Sequence[float], ps: Sequence[int] = (50, 95)
) -> dict[int, float | None]:
    """Nearest-rank percentiles; None for every p when there are no values."""
    if not values:
        return {p: None for p in ps}
    ordered = sorted(values)
    return {p: ordered[max(1, ceil(p / 100 * len(ordered))) - 1] for p in ps}


def _is_handoff(outcome: str | None) -> bool:
    return bool(outcome) and str(outcome).startswith("handoff")


def _ran(verdicts: Iterable[Verdict]) -> list[Verdict]:
    return [v for v in verdicts if v.get("verdict") != "not_run"]


def _correct(v: Verdict) -> bool:
    return v.get("verdict") == "passed" and not v.get("unsafe")


def compute(verdicts: Iterable[Verdict]) -> dict[str, Any]:
    """The D16 metric set over one group of verdicts ("not run" excluded)."""
    ran = _ran(verdicts)
    in_scope = [v for v in ran if v.get("in_scope", True)]
    automated = [v for v in in_scope if not _is_handoff(v.get("outcome"))]
    safe = [v for v in in_scope if _correct(v) and not _is_handoff(v.get("outcome"))]

    unsafe_k = sum(1 for v in ran if v.get("unsafe"))

    tp = sum(
        1
        for v in ran
        if _is_handoff(v.get("expected_outcome")) and _is_handoff(v.get("outcome"))
    )
    missed = sum(
        1
        for v in ran
        if _is_handoff(v.get("expected_outcome")) and not _is_handoff(v.get("outcome"))
    )
    unneeded = sum(
        1
        for v in ran
        if not _is_handoff(v.get("expected_outcome")) and _is_handoff(v.get("outcome"))
    )
    tn = len(ran) - tp - missed - unneeded

    clar = [v for v in ran if v.get("clarification_required") is not None]
    clar_ok = sum(
        1
        for v in clar
        if (v.get("outcome") == "clarified") == bool(v.get("clarification_required"))
    )

    turn_lat = [x for v in ran for x in v.get("turn_latencies_ms") or []]
    conv_lat = [
        v["conversation_latency_ms"]
        for v in ran
        if v.get("conversation_latency_ms") is not None
    ]
    costs = [v["cost_usd"] for v in ran if v.get("cost_usd") is not None]
    total_cost = sum(costs)

    return {
        "label": LABEL,
        "cases": len(ran),
        "safe_automated_resolution": Rate.of(len(safe), len(in_scope)).model_dump(),
        "automation_attempted": Rate.of(len(automated), len(in_scope)).model_dump(),
        "containment": Rate.of(
            sum(1 for v in ran if not _is_handoff(v.get("outcome"))), len(ran)
        ).model_dump(),
        "escalation": {
            "correct": tp,
            "missed": missed,
            "unnecessary": unneeded,
            "correct_no_transfer": tn,
            "recall": Rate.of(tp, tp + missed).model_dump(),
            "precision": Rate.of(tp, tp + unneeded).model_dump(),
        },
        "unsafe": {
            **Rate.of(unsafe_k, len(ran)).model_dump(),
            "upper_bound_rule_of_three": rule_of_three(len(ran))
            if unsafe_k == 0
            else None,
        },
        "clarification_accuracy": Rate.of(clar_ok, len(clar)).model_dump(),
        "latency_ms": {
            "turn": {
                "n": len(turn_lat),
                **{f"p{p}": x for p, x in percentiles(turn_lat).items()},
            },
            "conversation": {
                "n": len(conv_lat),
                **{f"p{p}": x for p, x in percentiles(conv_lat).items()},
            },
        },
        "cost_usd": {
            "total": total_cost if costs else None,
            "per_case": total_cost / len(costs) if costs else None,
            "per_success": total_cost / len(safe)
            if costs and safe
            else None,  # None = "not defined"
        },
    }


def by_group(
    verdicts: Sequence[Verdict], key: str | Callable[[Verdict], str]
) -> dict[str, dict[str, Any]]:
    """`compute` per value of ``key`` (e.g. ``language_variant`` or ``segment``)."""
    get = key if callable(key) else (lambda v: str(v.get(key) or "unknown"))
    groups: dict[str, list[Verdict]] = defaultdict(list)
    for v in verdicts:
        groups[get(v)].append(v)
    return {g: compute(vs) for g, vs in sorted(groups.items())}


def compute_all(verdicts: Sequence[Verdict]) -> dict[str, Any]:
    """Overall metrics plus the language and segment breakdowns, and the not-run list."""
    return {
        "overall": compute(verdicts),
        "by_language_variant": by_group(verdicts, "language_variant"),
        "by_segment": by_group(verdicts, "segment"),
        "not_run": [
            {"case_id": v.get("case_id"), "reason": v.get("reason")}
            for v in verdicts
            if v.get("verdict") == "not_run"
        ],
    }
