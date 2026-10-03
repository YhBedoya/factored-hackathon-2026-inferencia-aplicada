"""A real `ClassifierAdapter` over a fake scorer, so tests need no model or network."""

from collections.abc import Sequence

from app.domains.conversation.classifier import ClassifierAdapter
from app.domains.conversation.intent_registry import classifier_labels, load_registry

__all__ = ["StubScorer", "make_stub_classifier"]


class StubScorer:
    """Scores a text from `mapping` (exact text -> label probabilities).

    Unknown texts get a flat distribution, i.e. below any sensible tau.
    """

    def __init__(self, mapping: dict[str, dict[str, float]]) -> None:
        self.labels = classifier_labels()
        self._mapping = mapping

    def predict_proba(self, texts: Sequence[str]) -> list[dict[str, float]]:
        flat = dict.fromkeys(self.labels, 1 / len(self.labels))
        return [{**flat, **self._mapping[t]} if t in self._mapping else flat for t in texts]


def make_stub_classifier(
    mapping: dict[str, dict[str, float]], tau: float = 0.5
) -> ClassifierAdapter:
    return ClassifierAdapter(
        StubScorer(mapping),
        tau=tau,
        version="intent_clf@stub",
        label_set_version=load_registry().label_set_version,
    )
