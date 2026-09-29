# Card-support dev workflow. See `docs/solution-docs/06-engineering-rules.md`
# and CLAUDE.md "Planned commands". Never prints `.env` contents.

-include .env
export

COMPOSE := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.dev.yml -f docker/docker-compose.observability.yml

COMPOSE_PROD := docker compose --env-file .env -f docker/docker-compose.base.yml -f docker/docker-compose.observability.yml -f docker/docker-compose.prod.yml
STACK_NAME ?= swip-card-support

.PHONY: setup mcp-setup fill-secrets up down test check client data demo-reset seed-identity chat-sandbox chat-ui chat-api nlu-smoke graph-diagram test-integration infra-up infra-down deploy deploy-remote smoke-prod

setup: mcp-setup ## Toolchains + .env.example -> .env if missing.
	cp -n .env.example .env
	$(MAKE) fill-secrets
	cd backend && uv sync
	cd pipeline && uv sync
	cd frontend && npm ci
	pre-commit install --hook-type pre-commit --hook-type commit-msg

fill-secrets: ## Fill empty JWT_SECRET / IDENTITY_HMAC_KEY / CREDENTIALS_SEED in .env with random values (D21). Never prints a value.
	python3 -c "\
	import re, secrets; \
	keys = ['JWT_SECRET', 'IDENTITY_HMAC_KEY', 'CREDENTIALS_SEED']; \
	lines = open('.env').read().splitlines(); \
	matches = [re.match(r'^([A-Z_]+)=(.*)$$', l) for l in lines]; \
	present = {m.group(1) for m in matches if m and m.group(1) in keys}; \
	filled = []; \
	out = [(filled.append(m.group(1)) or f'{m.group(1)}={secrets.token_urlsafe(32)}') if (m and m.group(1) in keys and m.group(2) == '') else l for l, m in zip(lines, matches)]; \
	out = out + [(filled.append(k) or f'{k}={secrets.token_urlsafe(32)}') for k in keys if k not in present]; \
	open('.env', 'w').write('\n'.join(out) + '\n'); \
	print('filled: ' + (', '.join(filled) if filled else 'none (already set)'))"

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
	$(MAKE) seed-identity

demo-reset: ## Reset latam_app from latam_golden (03 §7).
	cd pipeline && uv run python -m load.demo_reset

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

# --- D2-A live API chat (real login, real Postgres, `make up` running) ------

chat-api: ## CLI chat against the running API: make chat-api PERSONA=<customer_id>.
	@test -n "$(PERSONA)" || (echo "Usage: make chat-api PERSONA=<customer_id>" && exit 1)
	cd backend && uv run python scripts/chat_api.py --persona "$(PERSONA)"

graph-diagram: ## Regenerate the turn-graph Mermaid diagram.
	cd backend && uv run python -m app.domains.conversation.graph --mermaid > ../docs/diagrams/turn-graph-v0.mmd

test-integration: ## Integration tests against `make up`'s Postgres/Redis (D19). Local only, needs `make up`.
	cd backend && uv run pytest tests/integration -q

# --- D4-A5 AWS deploy v0 (08-deployment.md). The human runs the AWS-calling targets. ---

infra-up: ## Create/update the EC2 stack: make infra-up ALERT_EMAIL_1= ALERT_EMAIL_2= DATA_BUCKET= BEDROCK_ARNS=arn1,arn2
	@test -n "$(ALERT_EMAIL_1)" -a -n "$(ALERT_EMAIL_2)" -a -n "$(DATA_BUCKET)" -a -n "$(BEDROCK_ARNS)" || \
	  (echo "Usage: make infra-up ALERT_EMAIL_1=<e> ALERT_EMAIL_2=<e> DATA_BUCKET=<b> BEDROCK_ARNS=<arn,arn>" && exit 1)
	aws cloudformation deploy --stack-name $(STACK_NAME) --template-file infra/aws/ec2-stack.yaml \
	  --capabilities CAPABILITY_IAM --region us-east-1 --parameter-overrides \
	  AlertEmail1="$(ALERT_EMAIL_1)" AlertEmail2="$(ALERT_EMAIL_2)" \
	  DataBucketName="$(DATA_BUCKET)" BedrockModelArns="$(BEDROCK_ARNS)"

infra-down: ## Delete the EC2 stack (turn off termination protection first).
	aws cloudformation delete-stack --stack-name $(STACK_NAME) --region us-east-1

deploy: ## On the box: fetch DEPLOY_REF (default main), render .env, build, up, migrate, smoke.
	bash infra/aws/deploy.sh

deploy-remote: ## From a laptop: run `make deploy` on the box via SSM. INSTANCE_ID= [DEPLOY_REF=].
	@test -n "$(INSTANCE_ID)" || (echo "Usage: make deploy-remote INSTANCE_ID=<i-...> [DEPLOY_REF=main]" && exit 1)
	aws ssm send-command --region us-east-1 --instance-ids "$(INSTANCE_ID)" \
	  --document-name AWS-RunShellScript \
	  --parameters 'commands=["cd /opt/swip && sudo -u ubuntu env DEPLOY_REF=$(or $(DEPLOY_REF),main) make deploy"]'

smoke-prod: ## HTTPS smoke test: make smoke-prod HOST=<ip>.sslip.io (SMOKE_* env vars).
	@test -n "$(HOST)" || (echo "Usage: make smoke-prod HOST=<host>" && exit 1)
	bash infra/aws/smoke.sh "$(HOST)"
