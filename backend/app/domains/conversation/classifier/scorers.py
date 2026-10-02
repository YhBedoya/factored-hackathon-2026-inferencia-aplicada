"""Text scorers behind the intent classifier, used by training and serving alike.

One code path for features and heads keeps train and serve from drifting. The
heavy dependencies (numpy, sklearn, fastembed) are imported inside functions so
the package imports without them. Nothing here touches the network: the
embedding model must already be in the local cache.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# e5 is the one model fastembed doesn't list, so we register it ourselves.
_E5_MODEL = "intfloat/multilingual-e5-small"
_E5_DIM = 384
# e5 was trained with a role prefix, and fastembed does not add it.
_E5_PREFIX = "query: "


class Scorer(Protocol):
    """Maps texts to a probability per label."""

    labels: tuple[str, ...]

    def predict_proba(self, texts: Sequence[str]) -> list[dict[str, float]]: ...


class Embedder:
    """fastembed sentence embedder that only ever reads the local cache."""

    def __init__(self, model_name: str, cache_dir: Path) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding

            if self.model_name == _E5_MODEL:
                from fastembed.common.model_description import ModelSource, PoolingType

                # Must run in every process before the model is constructed.
                # A repeat registration raises, and then it's already registered.
                try:
                    TextEmbedding.add_custom_model(
                        model=_E5_MODEL,
                        pooling=PoolingType.MEAN,
                        normalization=True,
                        sources=ModelSource(hf=_E5_MODEL),
                        dim=_E5_DIM,
                        model_file="onnx/model.onnx",
                    )
                except ValueError:
                    pass
            self._model = TextEmbedding(
                self.model_name,
                cache_dir=str(self.cache_dir),
                local_files_only=True,
            )
        return self._model

    def embed(self, texts: Sequence[str]) -> "NDArray[np.float32]":
        import numpy as np

        batch = [_E5_PREFIX + t for t in texts] if self.model_name == _E5_MODEL else list(texts)
        vectors = list(self._load().embed(batch))
        return np.asarray(vectors, dtype=np.float32)


class SklearnScorer:
    """A fitted sklearn estimator (or Pipeline) behind the ``Scorer`` protocol."""

    def __init__(
        self,
        estimator: Any,
        labels: tuple[str, ...],
        embedder: Embedder | None = None,
    ) -> None:
        self.estimator = estimator
        self.labels = labels
        self.embedder = embedder

    def predict_proba(self, texts: Sequence[str]) -> list[dict[str, float]]:
        features: Any = list(texts) if self.embedder is None else self.embedder.embed(texts)
        rows = self.estimator.predict_proba(features)
        return [
            {label: float(p) for label, p in zip(self.labels, row, strict=True)} for row in rows
        ]
