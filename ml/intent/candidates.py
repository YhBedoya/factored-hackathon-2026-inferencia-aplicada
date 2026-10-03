"""Model candidates C0-C4 for the learned intent classifier (spec D17).

Each candidate is a seeded estimator factory plus a small grid. The embedding
candidates share one `Embedder` per model, so training, serving and the grid
all go through the backend's `classifier/scorers.py` code path. C1 is the
existing keyword baseline wrapped to a single label, with no fitting.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from ml.intent import data_io  # noqa: F401  (puts backend/ on sys.path before app.* imports)

NO_MATCH = "unrecognized"

_E5 = "intfloat/multilingual-e5-small"
_MINILM = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass(frozen=True)
class Candidate:
    name: str
    description: str
    grid: list[dict[str, Any]]
    # Fitted estimator factory; None for C1 (rules, nothing to fit).
    build: Callable[[dict[str, Any], int], Any] | None
    embedding_model: str | None = None
    fixed: dict[str, Any] = field(default_factory=dict)


def _c0(params: dict[str, Any], seed: int) -> Any:
    from sklearn.dummy import DummyClassifier

    # "prior" gives class frequencies as probabilities; argmax is the majority class.
    return DummyClassifier(strategy="prior")


def _c2(params: dict[str, Any], seed: int) -> Any:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(analyzer="char_wb", ngram_range=tuple(params["ngram_range"])),
            ),
            ("lr", LogisticRegression(C=params["C"], max_iter=2000, random_state=seed)),
        ]
    )


def _lr(params: dict[str, Any], seed: int) -> Any:
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=params["C"], max_iter=2000, random_state=seed)


def _knn(params: dict[str, Any], seed: int) -> Any:
    from sklearn.neighbors import KNeighborsClassifier

    # Embeddings are L2-normalised, so cosine and euclidean agree; cosine is explicit.
    return KNeighborsClassifier(n_neighbors=params["k"], metric="cosine", weights="distance")


_C_GRID = [{"C": c} for c in (1.0, 10.0, 100.0)]

CANDIDATES: dict[str, Candidate] = {
    "c0": Candidate("c0", "majority class", [{}], _c0),
    "c1": Candidate("c1", "keyword_nlu rules wrapped to a label", [{}], None),
    "c2": Candidate(
        "c2",
        "TF-IDF char_wb + logistic regression",
        [{"C": c, "ngram_range": ng} for ng, c in product(((2, 4), (2, 5)), (1.0, 10.0, 100.0))],
        _c2,
    ),
    "c3a": Candidate("c3a", "e5-small embeddings + LR", _C_GRID, _lr, embedding_model=_E5),
    "c3b": Candidate("c3b", "MiniLM embeddings + LR", _C_GRID, _lr, embedding_model=_MINILM),
    "c4": Candidate(
        "c4",
        "e5-small embeddings + kNN",
        [{"k": k} for k in (3, 5, 10, 20)],
        _knn,
        embedding_model=_E5,
    ),
}


def keyword_label(text: str) -> str:
    """C1: the first intent `keyword_nlu` finds, else its scope topic, else NO_MATCH."""
    from app.domains.conversation.baseline.keyword_nlu import keyword_nlu

    result = keyword_nlu(text)
    if result.intents:
        return str(result.intents[0])
    topic = result.slots.topic
    return str(topic) if topic else NO_MATCH


def keyword_labels(texts: Sequence[str]) -> list[str]:
    return [keyword_label(t) for t in texts]
