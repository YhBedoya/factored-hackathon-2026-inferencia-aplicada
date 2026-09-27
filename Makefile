# Card-support dev workflow. See `docs/solution-docs/06-engineering-rules.md`
# and CLAUDE.md "Planned commands". Never prints `.env` contents.

-include .env
export

COMPOSE := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml

.PHONY: setup mcp-setup up down test check client data demo-reset

setup: mcp-setup ## Toolchains + .env.example -> .env if missing.
	cp -n .env.example .env
	cd backend && uv sync
	cd pipeline && uv sync
	cd frontend && npm ci
	pre-commit install --hook-type pre-commit --hook-type commit-msg

mcp-setup: ## Pull every Docker-run MCP image pinned in .mcp.json (Playwright, VictoriaLogs, VictoriaTraces).
	python3 -c "\
	import json, subprocess; \
	servers = json.load(open('.mcp.json'))['mcpServers']; \
	images = [a for s in servers.values() if s.get('command') == 'docker' \
	          for a in s.get('args', []) if '/' in a and ':' in a and not a.startswith('-')]; \
	[subprocess.run(['docker', 'pull', image], check=True) for image in images]"

up: ## Dev stack, hot reload.
	$(COMPOSE) up -d --build --wait

down: ## Stop the dev stack.
	$(COMPOSE) down

test: ## Backend + pipeline unit tests.
	cd backend && uv run pytest tests/unit -q
	cd pipeline && uv run pytest tests -q

check: ## Lint + types + import-linter + unit tests.
	cd backend && uv run ruff check app tests && \
	uv run ruff format --check app tests && \
	uv run mypy app && \
	uv run lint-imports && \
	uv run pytest tests/unit -q
	cd pipeline && uv run ruff check ingest load tests && \
	uv run ruff format --check ingest load tests && \
	uv run pytest tests -q
	cd frontend && npx biome ci .

client: ## Regenerate the OpenAPI client from the running backend (D19).
	cd frontend && npx @hey-api/openapi-ts

data: ## Ingest (S3 by default, or SOURCE=local:<path>) -> dbt -> golden DB -> demo reset.
	cd pipeline && uv run python -m ingest && uv run python -m load

demo-reset: ## Reset latam_app from latam_golden (03 §7).
	cd pipeline && uv run python -m load.demo_reset
