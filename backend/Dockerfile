# Slim Python base kept in sync with `requires-python` in pyproject.toml;
# `uv` is copied from its own distroless image instead of pip-installed, so
# the runtime image never needs a build toolchain for uv itself.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Dependencies first so the layer only rebuilds when the lock changes, not on
# every source edit (T4 dev compose bind-mounts source over this anyway).
COPY pyproject.toml uv.lock ./
# `ml` (training/embedding deps) is excluded: the runtime only needs the
# loader, and the bundle is baked in below.
RUN uv sync --frozen --no-install-project --no-group ml

COPY . .
RUN uv sync --frozen --no-group ml

# Personas come from the `eval` named build context (compose
# `additional_contexts`), since `eval/` sits outside the backend context.
COPY --from=eval personas.yaml /app/eval/personas.yaml

# Intent-classifier bundle from the `intent` named context (compose
# `additional_contexts`): `model.lock` next to `models/`, as the loader expects.
COPY --from=intent model.lock /app/ml/intent/model.lock
COPY --from=intent models/ /app/ml/intent/models/

# Build-time re-check, no network: a tarball whose name or sha256 differs from
# the lock fails the build. No tarball passes (the app starts without a
# classifier). The loader repeats the check at start.
RUN python - <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path("/app/ml/intent")
lock = json.loads((root / "model.lock").read_text())
for tar in sorted((root / "models").glob("*.tar.gz")):
    digest = hashlib.sha256(tar.read_bytes()).hexdigest()
    want = f"{lock.get('version')}.tar.gz"
    if tar.name != want or digest != lock.get("sha256"):
        sys.exit(f"model.lock mismatch for {tar.name}: expected {want} / {lock.get('sha256')}, got {digest}")
PY

ENV INTENT_MODEL_DIR=/app/ml/intent/models

ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
