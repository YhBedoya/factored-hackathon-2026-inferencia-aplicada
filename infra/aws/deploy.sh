#!/usr/bin/env bash
# Redeploy on the box (08 section 10). DEPLOY_REF defaults to main.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

git fetch --tags origin
git checkout "${DEPLOY_REF:-main}"
git merge --ff-only "origin/${DEPLOY_REF:-main}" 2>/dev/null || true

bash infra/aws/render-env.sh

COMPOSE=(docker compose --env-file .env
  -f docker/docker-compose.base.yml
  -f docker/docker-compose.observability.yml
  -f docker/docker-compose.prod.yml)
"${COMPOSE[@]}" build
"${COMPOSE[@]}" up -d --wait

# Migrate both DBs so demo-reset never brings back an old schema.
set -a
# shellcheck disable=SC1091
. ./.env
set +a
(cd backend && DATABASE_URL="$DATABASE_URL" uv run alembic upgrade head)
(cd backend && DATABASE_URL="$GOLDEN_DATABASE_URL" uv run alembic upgrade head)

bash infra/aws/smoke.sh "${PUBLIC_HOST:?PUBLIC_HOST missing from .env}"
