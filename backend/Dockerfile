# Slim Python base kept in sync with `requires-python` in pyproject.toml;
# `uv` is copied from its own distroless image instead of pip-installed, so
# the runtime image never needs a build toolchain for uv itself.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app

# Dependencies first so the layer only rebuilds when the lock changes, not on
# every source edit (T4 dev compose bind-mounts source over this anyway).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

# Personas come from the `eval` named build context (compose
# `additional_contexts`), since `eval/` sits outside the backend context.
COPY --from=eval personas.yaml /app/eval/personas.yaml

ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
