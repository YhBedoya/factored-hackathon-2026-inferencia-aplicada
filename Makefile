# Card-support dev workflow. See `docs/solution-docs/06-engineering-rules.md`
# and CLAUDE.md "Planned commands". Never prints `.env` contents.

-include .env
export

# Baked into the backend image (Settings.git_sha, /staff/system). `?=` so a value
# from .env or the environment wins.
GIT_SHA ?= $(shell git rev-parse --short=10 HEAD 2>/dev/null || echo unknown)
export GIT_SHA

COMPOSE := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml -f docker/docker-compose.devtools.yml

COMPOSE_PROD := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.observability.yml -f docker/docker-compose.prod.yml
STACK_NAME ?= swip-card-support
# The deploy's own region and sizing (08 §1, ADR-017 amended 2026-10-03). Not AWS_REGION:
# the local .env may set that for dev Bedrock, and `-include .env` would leak it here.
DEPLOY_REGION ?= us-east-2
INSTANCE_TYPE ?= m7i-flex.large
MONTHLY_BUDGET_USD ?= 90

.PHONY: langfuse-up langfuse-down eval eval-pii-check setup mcp-setup fill-secrets up down test check client data demo-reset seed-identity chat-sandbox chat-ui chat-api nlu-smoke graph-diagram test-integration infra-up infra-down deploy deploy-remote smoke-prod eval-paraphrase eval-mix eval-freeze eval-freeze-check intent-gen intent-train intent-compare analytics

setup: mcp-setup ## Toolchains + .env.example -> .env if missing.
	cp -n .env.example .env
	$(MAKE) fill-secrets
	cd backend && uv sync
	cd pipeline && uv sync
	cd frontend && npm ci
	pre-commit install --hook-type pre-commit --hook-type commit-msg

fill-secrets: ## Fill empty JWT_SECRET / IDENTITY_HMAC_KEY / CREDENTIALS_SEED / PII_VAULT_KEY (Fernet) / ANALYTICS_DB_PASSWORD in .env with random values (D21). Never prints a value.
	python3 -c "\
	import base64, os, re, secrets; \
	keys = ['JWT_SECRET', 'IDENTITY_HMAC_KEY', 'CREDENTIALS_SEED', 'PII_VAULT_KEY', 'ANALYTICS_DB_PASSWORD']; \
	gen = lambda k: base64.urlsafe_b64encode(os.urandom(32)).decode() if k == 'PII_VAULT_KEY' else secrets.token_urlsafe(32); \
	lines = open('.env').read().splitlines(); \
	matches = [re.match(r'^([A-Z_]+)=(.*)$$', l) for l in lines]; \
	present = {m.group(1) for m in matches if m and m.group(1) in keys}; \
	filled = []; \
	out = [(filled.append(m.group(1)) or f'{m.group(1)}={gen(m.group(1))}') if (m and m.group(1) in keys and m.group(2) == '') else l for l, m in zip(lines, matches)]; \
	out = out + [(filled.append(k) or f'{k}={gen(k)}') for k in keys if k not in present]; \
	open('.env', 'w').write('\n'.join(out) + '\n'); \
	print('filled: ' + (', '.join(filled) if filled else 'none (already set)'))"

mcp-setup: ## Pull the three agent-tooling MCP images (compose services, docker-compose.devtools.yml).
	$(COMPOSE) pull mcp-victorialogs mcp-victoriatraces mcp-playwright

up: ## Dev stack, hot reload.
	$(COMPOSE) up -d --build --wait

down: ## Stop the dev stack.
	$(COMPOSE) down

LANGFUSE_SERVICES := langfuse-web langfuse-worker langfuse-postgres langfuse-clickhouse langfuse-redis langfuse-minio

langfuse-up: ## Self-hosted Langfuse (opt-in) at http://localhost:3100. Create a project, put its keys in .env.
	$(COMPOSE) --profile langfuse up -d --wait $(LANGFUSE_SERVICES)

langfuse-down: ## Stop and remove the Langfuse services (data volumes are kept).
	$(COMPOSE) --profile langfuse rm -sf $(LANGFUSE_SERVICES)

test: ## Backend + pipeline unit tests.
	cd backend && uv run pytest tests/unit -q
	cd pipeline && uv run pytest tests -q

check: ## Lint + types + import-linter + unit tests.
	cd backend && uv run ruff check app tests && \
	uv run ruff format --check app tests && \
	uv run mypy app && \
	uv run lint-imports && \
	uv run pytest tests/unit -q
	cd pipeline && uv run ruff check ingest load contracts tests && \
	uv run ruff format --check ingest load contracts tests && \
	uv run pytest tests -q
	cd frontend && npx biome ci .
	uv run --project backend python -m ml.intent.check
	uv run --project backend pytest ml/intent/tests -q
	uv run --project backend ruff check --config backend/pyproject.toml ml
	uv run --project backend ruff format --check --config backend/pyproject.toml ml

client: ## Regenerate the OpenAPI client from the running backend (D19).
	cd frontend && npx @hey-api/openapi-ts

data: ## Ingest (S3 or SOURCE=local:<path>) -> contracts -> dbt -> golden DB -> reports -> demo reset (one RUN_ID).
	cd pipeline && export RUN_ID=$${RUN_ID:-$$(date -u +%Y%m%dt%H%M%S)} && uv run python -m ingest && uv run python -m contracts && uv run python -m load
	$(MAKE) seed-identity

demo-reset: ## Reset latam_app from latam_golden (03 §7).
	cd pipeline && uv run python -m load.demo_reset

analytics: ## One analytics pass over finished conversations (analytics worker, --once). Needs the stack up.
	$(COMPOSE) run --rm analytics-worker uv run --no-sync python -m app.domains.analytics.worker --once

seed-identity: ## Seed identity.accounts into latam_golden (D5), then reset latam_app from it.
	cd backend && DATABASE_URL=$(GOLDEN_DATABASE_URL) uv run alembic upgrade head
	cd backend && uv run python -m app.domains.identity.provision
	cd pipeline && uv run python -m load.demo_reset
	@test -z "$$($(COMPOSE) ps -q backend)" || $(COMPOSE) restart backend

# --- D1-B sandbox (FakeBank over DuckDB, no API or Postgres needed) ----------

chat-sandbox: ## CLI chat against FakeBank: make chat-sandbox CUSTOMER=<customer_id>.
	@test -n "$(CUSTOMER)" || (echo "Usage: make chat-sandbox CUSTOMER=<customer_id>" && exit 1)
	cd backend && uv run python -m app.domains.conversation.sandbox --customer "$(CUSTOMER)"

chat-ui: ## Streamlit sandbox page on http://localhost:8501.
	@echo "Sandbox UI: http://localhost:8501"
	cd backend && uv run streamlit run scripts/sandbox_ui.py

nlu-smoke: ## Live NLU smoke set (needs ANTHROPIC_API_KEY).
	cd backend && uv run python scripts/nlu_smoke.py

eval: ## Offline eval run: make eval SUITE=dev SYSTEM=both [CASES=a-] [DRIVER=scripted|simulator] [RUNS=1] [NLU=off|smoke|suite] [FAULTS=a,b].
	uv run --project backend python -m eval.harness --suite $(or $(SUITE),dev) --system $(or $(SYSTEM),both) $(if $(CASES),--cases $(CASES)) --driver $(or $(DRIVER),scripted) --runs $(or $(RUNS),1) --nlu $(or $(NLU),off) $(if $(FAULTS),--faults $(FAULTS))

intent-gen: ## Fill intent dataset cells up to 30 accepted: make intent-gen [LOCALE=es-mx] [CLASS=card_block].
	uv run --project backend python -m ml.intent.generate $(if $(LOCALE),--locale $(LOCALE)) $(if $(CLASS),--class $(CLASS))

intent-train: ## Train intent candidates: make intent-train [CANDIDATE=all] [SEED=42].
	uv run --project backend python -m ml.intent.train --candidate $(or $(CANDIDATE),all) --seed $(or $(SEED),42)

intent-compare: ## Compare candidates, write the report run, bundle and model.lock: make intent-compare [SEED=42].
	uv run --project backend python -m ml.intent.compare --seed $(or $(SEED),42)

eval-pii-check: ## PII scan of a run's LLM-call export (RUN=<folder>).
	@test -n "$(RUN)" || { echo "usage: make eval-pii-check RUN=<run_id>"; exit 2; }
	uv run --project backend python -m eval.harness.pii_check --run $(RUN)

# --- D2-A live API chat (real login, real Postgres, `make up` running) ------

chat-api: ## CLI chat against the running API: make chat-api PERSONA=<customer_id>.
	@test -n "$(PERSONA)" || (echo "Usage: make chat-api PERSONA=<customer_id>" && exit 1)
	cd backend && uv run python scripts/chat_api.py --persona "$(PERSONA)"

graph-diagram: ## Regenerate the turn-graph Mermaid diagram.
	cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd

# --- D5-B eval test-set tooling (B3) -----------------------------------------

eval-paraphrase: ## Append up to N paraphrases per seed case: make eval-paraphrase DIR=<dir> N=<n>.
	@test -n "$(DIR)" -a -n "$(N)" || (echo "Usage: make eval-paraphrase DIR=<dir> N=<n>" && exit 1)
	cd backend && uv run python scripts/paraphrase_seeds.py --dir ../$(DIR) --n $(N)

eval-mix: ## Mix report + target check for one suite dir: make eval-mix DIR=<dir>.
	@test -n "$(DIR)" || (echo "Usage: make eval-mix DIR=<dir>" && exit 1)
	uv run --project backend python -m eval.scenarios.mix_report $(DIR)

eval-freeze: ## Human-run only (D11): moves _staging/heldout/ into heldout/ and writes heldout.lock.
	@echo "eval-freeze must be run by a human, after both reviewers have set reviewer/reviewed_at on every eval/scenarios/_staging/heldout/*.yaml case."
	uv run --project backend python -m eval.scenarios.freeze freeze

eval-freeze-check: ## CI check: eval/scenarios/heldout/ matches heldout.lock byte-for-byte.
	uv run --project backend python -m eval.scenarios.freeze check

test-integration: ## Integration tests against `make up`'s Postgres/Redis (D19). Local only, needs `make up`.
	cd backend && uv run pytest tests/integration -q

# --- D4-A5 AWS deploy v0 (08-deployment.md). The human runs the AWS-calling targets. ---

infra-up: ## Create/update the EC2 stack: make infra-up ALERT_EMAIL_1= ALERT_EMAIL_2= DATA_BUCKET= BEDROCK_ARNS=arn1,arn2 [INSTANCE_TYPE=] [MONTHLY_BUDGET_USD=]
	@test -n "$(ALERT_EMAIL_1)" -a -n "$(ALERT_EMAIL_2)" -a -n "$(DATA_BUCKET)" -a -n "$(BEDROCK_ARNS)" || \
	  (echo "Usage: make infra-up ALERT_EMAIL_1=<e> ALERT_EMAIL_2=<e> DATA_BUCKET=<b> BEDROCK_ARNS=<arn,arn>" && exit 1)
	aws cloudformation deploy --stack-name $(STACK_NAME) --template-file infra/aws/ec2-stack.yaml \
	  --capabilities CAPABILITY_IAM --region $(DEPLOY_REGION) --parameter-overrides \
	  AlertEmail1="$(ALERT_EMAIL_1)" AlertEmail2="$(ALERT_EMAIL_2)" \
	  DataBucketName="$(DATA_BUCKET)" BedrockModelArns="$(BEDROCK_ARNS)" \
	  InstanceType="$(INSTANCE_TYPE)" MonthlyBudgetUsd="$(MONTHLY_BUDGET_USD)"

infra-down: ## Delete the EC2 stack (turn off termination protection first).
	aws cloudformation delete-stack --stack-name $(STACK_NAME) --region $(DEPLOY_REGION)

deploy: ## On the box: fetch DEPLOY_REF (default main), render .env, build, up, migrate, smoke.
	bash infra/aws/deploy.sh

deploy-remote: ## From a laptop: run `make deploy` on the box via SSM. INSTANCE_ID= [DEPLOY_REF=].
	@test -n "$(INSTANCE_ID)" || (echo "Usage: make deploy-remote INSTANCE_ID=<i-...> [DEPLOY_REF=main]" && exit 1)
	aws ssm send-command --region $(DEPLOY_REGION) --instance-ids "$(INSTANCE_ID)" \
	  --document-name AWS-RunShellScript \
	  --parameters 'commands=["cd /opt/swip && sudo -u ubuntu env DEPLOY_REF=$(or $(DEPLOY_REF),main) make deploy"]'

smoke-prod: ## HTTPS smoke test: make smoke-prod HOST=<ip>.sslip.io (SMOKE_* env vars).
	@test -n "$(HOST)" || (echo "Usage: make smoke-prod HOST=<host>" && exit 1)
	bash infra/aws/smoke.sh "$(HOST)"
