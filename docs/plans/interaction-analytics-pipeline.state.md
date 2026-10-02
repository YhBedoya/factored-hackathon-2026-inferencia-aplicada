# State: REQ-interaction-analytics-pipeline — interaction analytics pipeline
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-interaction-analytics-pipeline (ADR-033, owner A) · spec `docs/specs/interaction-analytics-pipeline.md` · plan `docs/plans/interaction-analytics-pipeline.md`
Branch `feat/interaction-analytics-pipeline`, based on `origin/feat/learned-intent-fallback` (e7c8dc1, not merged into develop).
Runs in the worktree `.claude/worktrees/interaction-analytics-pipeline`. Never read or write the main checkout.

## Conventions established for this card
- Full facts and the planned-names table: plan §"Facts checked against the repo". Deviate from a planned name only with a line in the Task log.
- The worktree has no `.env`; `Settings` defaults apply (`postgres:postgres@localhost:5432/latam_app`). Unverified against the running Postgres. A connection failure or a **skipped** integration test is reported, never worked around, and a skip is not a pass. Never read or copy `.env` from the main checkout.
- The dev stack runs from the main checkout. Only T14 (ALONE) touches it.
- Alembic head is `0008`; this card adds `0009`. No new dependency: nobody runs `uv add`/`uv sync`/`uv lock`/`npm install`.
- `GraphState.segments` already means reply texts. The per-intent channel is `GraphState.intent_segments`; reducers live in `conversation/state.py`.
- Worker role `analytics_worker`; the worker never uses the app role or `AuditLLMCallSink`.
- Tests: the spec's 8 only, fake LLM always. Per task run only your own `Verify`.

## Human decisions taken mid-card
- PQ1 (plan, T2): degraded queue-head handoff (`llm_unavailable` → `fallback` → `handoff_summary`, no flow node ran) writes ONE `handoff` segment, for the head intent only, route `handoff_summary`.
- PQ2 (plan, T5): `card_unlock` on a permanently blocked card (`block_permanent_no_undo`) → the `card_unlock` segment is `abstained`.
- D22 reading (plan, T5): the replacement offer made by `card_unlock` is `bot_offered`, same as `card_block`'s; a bot-offered occurrence is a real intent in every status except `cancelled`.
- Plan-level mechanics accepted as written: `ANALYTICS_DATABASE_URL` built in Compose, empty = start-up error (no superuser fallback); `infra/aws/render-env.sh` not edited; `ANALYTICS_MOCK_ENABLED=true` in both example env files, Settings default `false`; migration downgrade leaves the role; `make analytics` = one-off `run --rm analytics-worker … --once`, `mem_limit: 512m`; T14 runs `make fill-secrets` on the worktree's own `.env`; mock day count in `America/Bogota`.
- T2 (graph): `unsupported` on an `injection_suspected` turn writes NO segment (the queue head is the paused flow's intent, not the attack).
- T2 (graph): an `awaiting` or explicitly marked segment keeps its status when `compose` later fails and the turn hands off; only the deferred read-flow segment flips to `handoff`.
- T10 (worker): the empty analytics password is detected by parsing `analytics_database_url` with `make_url`; a missing or empty password is a start-up error (on top of the empty-URL check), passwordless URLs included. The `latam_eval_` database refusal reads the name from the same parsed URL.
- Gate (V3, T1/T11): keep the `conversations.closed_at` candidate source and index `app.conversations(closed_at)` in 0009; the first run reads every conversation once as a backfill.
- Gate (V3, T10): a conversation whose compute raises is skipped and logged by exception class; the pass continues (other candidates, mock seeding, sentiment); the watermark stops at the failed conversation so it is retried next pass.
- Gate (T11): an upsert that sees new customer messages on an existing row clears its sentiment columns, so the next pass rescores it.
- Gate (T11): sentiment scoring targets only conversations with at least one non-empty masked customer message; the others keep null sentiment.
- Gate: implementer choices of T1, T8, T9, T10, T13 accepted as written (spec agent folds them in).
- Gate (T12): `analytics-worker` gets only the variables it uses (explicit `environment:`), not the whole `.env` via `env_file`.
- Gate: `docs/requirements/interaction-analytics-dashboard.md` (card 2) goes in this card's commit.
- Gate (V3-recheck, T1): 0009 also indexes `app.handoffs(created_at)`, `(claimed_at)`, `(returned_at)`; human re-runs downgrade 0008 → upgrade head on both DBs.
- Gate (V4, T16 new): worker logs ship to VictoriaLogs via a new `setup_log_export(service_name)` in `core/telemetry.py` (reused by `instrument_app`), called by the worker with `analytics-worker`; endpoint env for the worker only in `docker-compose.observability.yml`.
- Gate (V3-recheck, T10): watermark not advanced at all while any conversation fails is accepted (a permanently failing one freezes it; `analytics.compute_failed` makes it visible).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a73407ac8b2c4e641 | repair 2: ix_handoffs_{created,claimed,returned}_at in 0009; throwaway up/down/up PASS |
| T2 | done | a961f12723e183ee8 | intent_segments channel, _track_segments wrapper, mark_segment, bot_offered_flow; 7 passed, ruff, mypy PASS. Two open judgement calls with the human; pytest re-run after a one-line type fix requested |
| T3 | done | a5af788f0dc538cef | repair 1: 04 §6 no-write resolved + D19/D23/D24; 03 index line |
| T4 | done | a631935ea49675082 | reply_sent carries segments ([] when none), close_conversation sets closed_at; 8 passed, ruff, mypy PASS |
| T5 | done | aea157857c4bbbbf4 | D18/PQ2 marks in card_block/card_unlock/replacement, no write/confirm/read-back change; 13 passed, ruff, mypy PASS |
| T6 | done | a8aabf71cc5f5b3d8 | D18 marks in tx_search/tx_explain/decline_explain/unrecognized_charge; 26 passed, ruff, mypy PASS |
| T7 | done | a28595d6ae34bfb9b | sentiment step in registry, SentimentScorer/HaikuSentimentScorer/SentimentResult, sentiment@v1 prompt; 5 passed, ruff, mypy PASS |
| T8 | done | a6e7eff0377db6a0f | cause_groups.py + service.py (METRICS_VERSION=1, build_occurrences, interaction_outcome, finish_reason); assertions, ruff, mypy PASS |
| T9 | done | a659e7dc20a4b4e42 | mock.py + mock_profile.yaml (load_profile, generate_day, MockInteraction/MockIntent); deterministic chain, ruff, mypy PASS |
| T10 | done | a92633674f1a556a4 | repair 2: docstrings (sentiment clear, no-advance watermark) |
| T11 | done | afc22c6ecf76628ae | repair 2: docstring + customer_messages excludes empty content_masked; 4 passed 0 skipped |
| T12 | done | a3e0b17c994bb4829 | repair 2 stopped: worker never initialises OTel export; routed to new T16 |
| T13 | done | a557cc3c74c37d2de | 2 e2e worker tests; repair 1: PT test now proves R5 on the real store (RecordingScorer, token assertion fails when the store selects content); 4 passed 0 skipped, ruff PASS |
| T14 | done | a1cee19d21906d2be | live proof PASS: both DBs 0009 (human ran upgrades; guard refused), indexes, worker Up clean, env has no secrets, mock 30 days idempotent, 4 role proofs, make check 203 passed |
| T15 | done | ac16f52516365bb07 | README make-up line now says 11 containers and lists analytics-worker; counted from base+dev+observability compose files |
| T16 | done | aa0be14a668bb48a9 | setup_log_export(analytics-worker) in core/telemetry.py, worker call, OTEL endpoint in observability overlay; ruff/mypy clean, 10 passed, config renders without secrets |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T3 — Docs
Changed: `docs/solution-docs/04-contracts.md` (§6 `segments`), `03-data-architecture.md` (§1 mock provenance row, §6 `### analytics`), `06-engineering-rules.md` (§3 domain list), `08-deployment.md` (§9 `ANALYTICS_DB_PASSWORD`, §7 `analytics-worker` row), `README.md` (`make analytics`, `### Analytics worker` settings table, provenance table).
Facts the next tasks need: README settings table lists the six env names; 03 §6 states `ix_messages_created_at` and the exact grants.
Deviations: added a mock-provenance row to 03 §1 so the README pointer to 03 §1 resolves.
Verify: the task's grep chain → PASS.

### T1 — Migration 0009, analytics settings, empty package
Created: `backend/app/alembic/versions/0009_analytics.py` (revision id `"0009"`, down_revision `"0008"`), `backend/app/domains/analytics/__init__.py`.
Changed: `backend/app/core/config.py` (the seven planned `analytics_*` settings, planned defaults), `.env.example` (`ANALYTICS_DB_PASSWORD=` after `PII_VAULT_KEY`; "Analytics" section at the end, mock enabled).
Facts the next tasks need: tables `analytics.interactions`, `analytics.interaction_intents`, `analytics.worker_state` (row id=1 inserted); index `ix_interactions_ended_at`, `app.ix_messages_created_at`; role `analytics_worker` (LOGIN, password only if `ANALYTICS_DB_PASSWORD` non-empty). Types: `duration_s`, `time_to_claim_s` and all counts are Integer (counts NOT NULL default 0); booleans NOT NULL default false except `resolved`; `cost_*` Numeric(12,6) NOT NULL default 0, `sentiment_cost_usd` nullable; `computed_at` default now(), `metrics_version` NOT NULL no default; `started_at`/`ended_at`/`end_reason`/`source` NOT NULL; language/country/channel nullable text. Constraint names `ck_interactions_{source,end_reason,sentiment}`, `ck_interaction_intents_outcome`.
Deviations: none from planned names. Password path also checked by hand with a `p:a%s'x` password (login works); the shared-cluster role password was reset to NULL afterwards. `uv run` created `backend/.venv` in the worktree (untracked, not committed).
Verify: migration upgrade/downgrade/upgrade + `0009 role proofs ok`; ruff check, ruff format --check, mypy app/core/config.py all clean.

### T8 — Pure analytics rules
Created: `backend/app/domains/analytics/cause_groups.py` (`CAUSE_GROUPS`, `cause_group(reason) -> CauseGroup | None`), `service.py` (`METRICS_VERSION = 1`, frozen dataclasses `Occurrence(seq, intent, outcome, needed_clarification, turns, bot_offered)` and `InteractionOutcome(real_intent_count, resolved, abandoned, abstained)`, `build_occurrences(turn_segments)`, `interaction_outcome(occurrences, *, end_reason, handoff_count, any_abstain_route)`, `finish_reason(*, status, last_message_at, handoff_statuses, now, idle_minutes)`).
Facts the next tasks need: `handoff_statuses` is in creation order; `handoff_returned` when the last one is `returned`; open (`queued`/`claimed`) → `None`. `resolved` is false whenever `handoff_count > 0`. An `awaiting` segment without a slot does not set `needed_clarification`.
Deviations: none (names beyond `build_occurrences` were unplanned in the task block).
Verify: task command → `ok`, grep empty, ruff check/format clean, mypy "no issues found in 2 source files".

### T12 — Compose service `analytics-worker`, `make analytics`, secret
Changed: `docker/docker-compose.base.yml` (service `analytics-worker`, same build as `backend`, both URLs as `analytics_worker`, `REDIS_URL` set too, `mem_limit: 512m`), `docker-compose.dev.yml` (mount `../backend/app`, `LLM_DISABLED`), `docker-compose.prod.yml` (`APP_ENV`, `LLM_PROVIDER`, `AWS_REGION`, `restart: unless-stopped`), `Makefile` (`analytics` target + `.PHONY`; `ANALYTICS_DB_PASSWORD` in `fill-secrets` keys and help), `.env.prod.example` (`ANALYTICS_DB_PASSWORD=` in SSM block, `ANALYTICS_MOCK_ENABLED=true`).
Facts the next tasks need: the prod overlay uses `!override`, so the task Verify's plain `yaml.safe_load` of `docker-compose.prod.yml` fails (pre-existing); use a loader with an `!override` constructor. `docker compose config` lists `analytics-worker` in dev and prod sets.
Deviations: added `REDIS_URL` (needed: `.env` points at localhost) and `AWS_REGION` in prod (like backend).
Verify: yaml asserts (with `!override` loader) → ok; `make -n analytics` shows `analytics.worker --once`; `fill-secrets` fills `ANALYTICS_DB_PASSWORD` in a temp `.env`.

### T9 — Mock profile and the deterministic per-day generator
Created: `backend/app/domains/analytics/mock.py` (`load_profile() -> dict`, `generate_day(day: date, profile: dict, tz: tzinfo) -> list[MockInteraction]`, frozen dataclasses `MockInteraction` (field names = `analytics.interactions` columns, plus `intents: list[MockIntent]`) and `MockIntent` (= `interaction_intents` columns)), `backend/app/domains/analytics/mock_profile.yaml`.
Facts the next tasks need: timestamps are tz-aware in `tz`; money is `Decimal`; `computed_at` = `ended_at` (no clock); `metrics_version` comes from the profile (`1`, must equal the worker's `METRICS_VERSION`); `channel` = `web`; `source = "mock"`; `bot_offered` always false. Cause groups used: `by_design`/`customer_choice`/`bot_failure`/`security`; queues `fraudes`/`reclamos`/`atencion` (invented mapping in the profile). `handoff_summary` unit cost 0.005 is invented (R5 gives none). 30-day sample: resolved 72.3%, escalated 16.3%, abandoned 7.8%, abstained 3.7%, 1.29 intents each.
Deviations: none from planned names.
Verify: the task's chain → `ok`, ruff check/format clean, mypy "no issues found in 1 source file".

### T15 — README container count
Changed: `README.md` §4 `make up`: "10 containers" -> "11 containers", `analytics-worker` added to the list.
Facts the next tasks need: counted from the `Makefile` `COMPOSE` set (base + dev + observability + devtools): default services = postgres, redis, backend, analytics-worker, nginx, frontend (base+dev) + otel-collector, victoriametrics, victorialogs, victoriatraces, grafana = 11; the six langfuse-* are profile-gated. The three `mcp-*` services in devtools have no profile (README never counted them; left as is).
Deviations: none.
Verify: `grep -n -i container README.md` line 106 shows 11.

### T2 — Per-intent segment channel and segment wrapper
Created: `backend/tests/unit/test_analytics_segments.py` (2 tests; imports `_UnverifiedLockWrites` from `test_r3_flows`).
Changed: `conversation/state.py` (`IntentSegment` keys `intent, route, status, awaiting_slot?, bot_offered?`; `SegmentStatus`; `RESET_INTENT_SEGMENTS`; `_reduce_intent_segments`; `mark_segment(status, *, awaiting_slot=None) -> {"segment_mark": {...}}`; `TurnState.bot_offered_flow: str | None`), `graph.py` (`GraphState.intent_segments`, `GraphState.segment_deferred`; wrapper `_track_segments(name, node)` on the 8 flows + `unsupported`, `abstain`, `compose`, `handoff_summary`; `_guard_access` refusal adds `mark_segment("abstained")`), `nodes/load_session.py` (resets `intent_segments`, `segment_deferred`), `flows/actions.py::cancel` (`mark_segment("cancelled")`).
Facts T4-T6 need: runner reads `intent_segments` from node updates (stream_mode="updates"; the reset marker streams as `[]`). Flow status order = mark, `no_cards`->abstained, other reason/`handoff_queue`->handoff, pending owned by this flow->awaiting(+slot), verified action->resolved, facts->deferred to `compose` (resolved, or handoff if compose sets a reason), else no segment + `segment.unmarked` warning (T5/T6 must `mark_segment` the D18 endings: already_in_state, not_blocked, decline_*, tx_*_none, dispute_no_transactions, replacement_not_eligible/declined, nothing_pending, tx_search_ask_criterion with slot `criterion`, PQ2 card_unlock abstained). `bot_offered` is derived by the wrapper: a pending with `node="offer"` owned by another flow sets `TurnState.bot_offered_flow`; the flow's later pending-entered turns carry `bot_offered: true`.
Deviations: `unsupported` on an `injection_suspected` turn writes NO segment (the queue head is the paused intent, not the attack); PQ1 handled in the `handoff_summary` wrapper (degraded + `llm_unavailable` + head in `degraded_handoff_intents` + no segment for head yet -> one head `handoff`, route `handoff_summary`). Open edge: a flow's `awaiting`/explicit-mark segment stays as is if `compose` later fails (only the deferred case turns into handoff).
Verify: `uv run pytest tests/unit/test_analytics_segments.py tests/unit/test_graph.py tests/unit/test_r3_flows.py tests/unit/test_checkpoint_serde.py -q` -> 7 passed; ruff check/format clean; mypy (state.py, graph.py) clean.

### T7 — Sentiment step, scorer interface, Haiku scorer, prompt
Created: `backend/app/domains/analytics/sentiment.py` (`SentimentScorer`, `SentimentResult`, `SentimentLabels`, `HaikuSentimentScorer`), `backend/app/domains/analytics/prompts/sentiment@v1.md`.
Changed: `backend/app/core/llm/registry.py` (`sentiment` in `Step`, `MODEL_REGISTRY`, `TEMPERATURE`).
Facts the next tasks need: `await scorer.score(conversation_id: str, messages: Sequence[str], language: str) -> SentimentResult | None`. `HaikuSentimentScorer(sink: LLMCallSink | None = None, *, client_factory: Callable[[LLMCallSink], LLMClient] = <get_llm_client(sink=...)>)`; the factory receives the per-call cost-collecting wrapper sink (test seam: return a fake LLMClient). `SentimentResult.cost_usd` is `Decimal | None` (None when no attempt was priced, e.g. a fake client); `model` is the model_id of the last attempt record ("" if none recorded). Messages go in a numbered fence in the user message; `PromptRef("sentiment", 1)`.
Deviations: none.
Verify: task chain → `ok`, `5 passed` (test_llm_client), ruff check/format clean, `Success: no issues found in 2 source files` (mypy; slow, ~10 min cold).

### T4 — Runner writes `segments`; `close_conversation` writes `closed_at`
Changed: `conversation/runner.py` (`_run_turn`: `intent_segments` collected from each node update's `intent_segments`, written as `"segments"` on every `reply_sent`, `[]` when none; relay path untouched), `conversation/store.py` (`close_conversation` sets `status='closed', closed_at=now()` in one UPDATE), `tests/unit/test_degraded.py` (one assertion).
Facts the next tasks need: `segments` entries are the `IntentSegment` dicts verbatim (`intent, route, status`, `awaiting_slot?`, `bot_offered?`), in stream order; `closed_at` is written only by `close_conversation` (ui `conversation_closed`).
Deviations: none.
Verify: `uv run pytest tests/unit/test_degraded.py -q` -> 8 passed; ruff check/format and mypy (runner.py, store.py) clean.

### T6 — D18 segment marks in tx / decline / dispute flows
Changed: `flows/tx_search.py`, `tx_explain.py`, `decline_explain.py`, `unrecognized_charge.py` (each imports `mark_segment`; marks merged into existing returns, nothing else changed).
Marks: `resolved` = tx_search_none, tx_explain_none (both returns), decline_none, decline_unknown, dispute_no_transactions; `awaiting`(slot `criterion`) = tx_search_ask_criterion; `cancelled` = every `nothing_pending` return that sets `pending: None` (tx_search 2, tx_explain 2, decline_explain 2, unrecognized_charge 4).
Not marked: `pending_reminder` returns and the `nothing_pending` return in `_resume_plan` that keeps the pause (unrecognized_charge, stale decision).
Deviations: none. No ending found outside D2/D18.
Verify: 4 flow test files -> 26 passed; ruff check/format --check, mypy (4 files) clean.

### T5 — D18 segment marks in card_block, card_unlock, replacement
Changed: `flows/card_block.py`, `card_unlock.py`, `replacement.py` (marks merged with `**mark_segment(...)`; nothing else).
Marks: `already_in_state`, `not_blocked` -> resolved; `replacement_not_eligible`, `card_unlock` `customer_block` (PQ2) -> abstained; `replacement_declined` and every `nothing_pending` return that sets `pending: None` (card_block confirm token-missing; card_unlock otp card_id-missing + confirm token-missing; replacement address_confirm/otp/address card_id-missing + confirm token-missing) -> cancelled.
Facts the next tasks need: the `nothing_pending` returns that keep `pending` (stale/None decision in each `_resume_confirm`, `outcome != "cancel"` in `replacement._resume_address_confirm`) get no mark, as the task says; the wrapper's fallback then applies (`segment.unmarked` warning).
Deviations: none. No ending found that fits none of D2/D18.
Verify: pytest (4 files) -> 13 passed; ruff check, ruff format --check, mypy clean.

### T10 — The worker (pass, loop, CLI)
Created: `backend/app/domains/analytics/worker.py`, `backend/tests/unit/test_analytics_sentiment.py` (2 tests, in-memory `FakeStore`).
`AnalyticsStore` methods (all async, ids are UUID strings): `get_state() -> WorkerState(watermark, mock_seeded_through)`, `set_watermark(dt)`, `set_mock_seeded_through(day)`, `list_candidates(since: datetime | None) -> list[str]`, `load_facts(id) -> ConversationFacts | None`, `upsert_interaction(row: InteractionRow, intents: Sequence[Occurrence])`, `insert_mock(rows: Sequence[MockInteraction])`, `list_scoring_targets(*, all_real: bool, limit: int | None) -> list[ScoringTarget]`, `customer_messages(id) -> list[str]` (content_masked only), `set_sentiment(id, SentimentResult, scored_at)`, `list_stale(metrics_version) -> list[str]`, `record_llm_call(LLMCallRecord)`. Dataclasses (`ConversationFacts`, `MessageFact`, `ReplyFact`, `HandoffFact`, `StepCost`, `InteractionRow`...) are in worker.py. Store semantics: upsert never touches the sentiment columns on conflict and replaces the intent rows in one transaction; `insert_mock` is idempotent per id; `list_scoring_targets(all_real=False)` = real, sentiment_overall null, customer_messages > 0, newest ended_at first; `list_candidates` covers messages, handoffs (created/claimed/returned) and `closed_at`; `step_costs` includes the `sentiment` step (worker drops it), null costs as 0.
Entry points: `run_pass(store, scorer, *, now, settings) -> PassStats`, `run_recompute(store, *, now, settings) -> int`, `run_rescore_sentiment(store, scorer, *, now) -> PassStats`, `validate_database_url(raw) -> URL`. CLI flags: `--once`, `--recompute`, `--rescore-sentiment` (last two run once and exit). Exit code 2 on a start-up error.
T11 must provide `app/domains/analytics/repository.py` with `build_engine(url: str)` and `PostgresAnalyticsStore(engine)`; `_amain` loads it with `importlib.import_module` (module absent today, keeps mypy/`--help` clean). Mock seeding runs from `today - (backfill_days - 1)` to today in `analytics_timezone`, one day per `insert_mock` + `set_mock_seeded_through`.
Human decisions (this task): the empty-password check parses `analytics_database_url` with `make_url` (no password = start-up error; `analytics_db_password` setting not used; no Compose edit); the eval-database refusal reads the database name from the same parsed URL.
Deviations: importlib load of the store (above); sentiment is scored in a separate step after compute (rows with null sentiment, batch of 50 per pass), not inline per candidate.
Verify: `pytest tests/unit/test_analytics_sentiment.py` -> 2 passed; `--help` ok; grep empty; ruff check/format clean; mypy "no issues found in 1 source file".

### T11 — Postgres store for the worker
Created: `backend/app/domains/analytics/repository.py` (`build_engine(url)`, `PostgresAnalyticsStore(engine)`, all 12 `AnalyticsStore` methods), `backend/tests/integration/test_analytics_worker.py` (2 tests).
Facts the next tasks need: T13 can import from the test file `NOW` (2026-10-02 15:00 UTC), `FakeScorer` (fixed neutral result), fixture `analytics_settings` (it_env + `ANALYTICS_DATABASE_URL` = it_db, mock off), `with_store(settings, body(store, engine))` (fresh worker engine per `asyncio.run`), `insert_conversation(conn, last_message_at=, roles=)`, `insert_handoff(conn, cid, status=, at=)`. Tests run on the throwaway `it_db` as its owner (no `analytics_worker` password used); the mock test parks `worker_state.watermark` at 2100 before each pass so leftover conversations from other tests are not computed. `list_candidates(since)` = messages.created_at, handoffs created/claimed/returned, plus `conversations.closed_at` (no index; small table), per the T10 protocol doc. `reply_sent` facts read `payload->>'route'`, `degraded`, `segments`. Ledger insert passes `record.temperature` as is (same as audit repo).
demo-reset: `make demo-reset` and the admin route DROP `latam_app` and recreate it `TEMPLATE latam_golden`, so `analytics.worker_state` comes back as golden has it (never run by the worker: NULLs), or the schema is absent until `alembic upgrade head` runs on it. A stale `mock_seeded_through` cannot survive. Not checked against the live golden DB.
Deviations: none.
Verify: `pytest tests/integration/test_analytics_worker.py -k "finish_rules or mock_seed_deterministic" -q -rs` -> 2 passed, 0 skipped; grep clean; ruff check/format clean; mypy "no issues found in 1 source file".

### T13 — End-to-end worker tests
Changed: `backend/tests/integration/test_analytics_worker.py` (`test_worker_es_multi_intent`, `test_worker_pt_write_happy_path`, helper `_run_worker_over`; imports `_login`, `_wait_for_bot_message`, `_confirm_token`, `_psycopg_dsn`, constants from `test_write_path_api`).
Facts: ES uses the blocked customer with NLU `["card_status","card_unlock"]` in one turn (compose draft + handoff_summary scripted), then SQL `handoffs.status='returned'` -> intents `[resolved, handoff]`, `resolved=false`, `escalated=true`, `language='es'`. PT: temporary lock + `/confirmations` -> one `card_block` `resolved` `turns=2`, `resolved=true`; no `customer_id`/message-text columns in either table. No flow ending had a wrong status.
Deviations: the PT conversation is created with `{"language": "pt"}`: `analytics.interactions.language` comes from `app.conversations.language` (set at creation), not from the NLU, so a default-created conversation reads `es`.
Verify: `uv run pytest tests/integration/test_analytics_worker.py -q -rs` -> 4 passed, 0 skipped; ruff check, ruff format --check clean.
T13 repair 1 (R5 on the real store): the PT test now sends an email in the customer turn and scores with `RecordingScorer`; asserts `content_masked` holds a token, the raw email is in none of the scored messages and a token is in them. `app.messages.content` is encrypted (not plaintext), so the bite is the token assertion: with `customer_messages` monkeypatched to read `content` it fails (`assert any(TOKEN_RE.search(m) ...)` False). Verify: 4 passed, 0 skipped; ruff clean. repository.py untouched.

### T3 repair 1 — Docs
Changed: `04-contracts.md` §6 (no-write endings resolve without verified; D19 direct and degraded handoff; D23 injection_suspected no segment; D24 late compose failure), `03-data-architecture.md` §6 (index on `app.conversations(closed_at)`).
Deviations: none.
Verify: grep of the new statements → matched.

### T1 repair round 1 — closed_at index
Changed: `backend/app/alembic/versions/0009_analytics.py` adds `app.ix_conversations_closed_at` on `app.conversations(closed_at)`; downgrade drops it. Same revision id "0009".
Verify: throwaway DB upgrade -> downgrade -> upgrade ok, index present; ruff check/format clean. latam_app and latam_golden not touched.

### T11 repair 1 — reopened conversations, scoring targets
Changed: `repository.py` only. `upsert_interaction` now runs `_CLEAR_STALE_SENTIMENT_SQL` in the same transaction: nulls all seven sentiment columns when a customer message is newer than `sentiment_scored_at` (the only scoring time the row stores). `list_scoring_targets(all_real=False)` now requires an `app.messages` customer row with non-empty `content_masked` (replaces `customer_messages > 0`).
Verify: `pytest tests/integration/test_analytics_worker.py -q -rs` -> 4 passed, 0 skipped; ruff check/format and mypy clean.

### T10 repair 1
Changed: `worker.py::run_pass` skips and logs (`analytics.compute_failed`, id + exception class) a conversation whose compute raises; the pass goes on (mock, sentiment). Any failure leaves the watermark unchanged (the protocol returns ids only, so "stop at the failed one" = "do not advance"); next pass retries. `test_analytics_sentiment.py` fixture now monkeypatches `app.core.llm.client._logger` with a fresh logger so a cached logger cannot hide `capture_logs()` in test_llm_client.
Note: the V1 failure did not reproduce here in either order before the fix (7 passed); the fix targets the suspected logger-cache cause.
Verify: sentiment+llm_client in both orders -> 7 passed; ruff clean; mypy clean.

### T12 repair 1 — no env_file on analytics-worker
Changed: `docker/docker-compose.base.yml` (removed `env_file` and `REDIS_URL`; explicit `environment`: ANALYTICS_DATABASE_URL, DATABASE_URL, ANALYTICS_IDLE_MINUTES, ANALYTICS_WORKER_INTERVAL_S, ANALYTICS_TIMEZONE, ANALYTICS_MOCK_ENABLED, ANALYTICS_MOCK_BACKFILL_DAYS, LLM_PROVIDER, ANTHROPIC_API_KEY, each with a `:-default` except the two URLs). Dev overlay adds LLM_DISABLED, prod adds APP_ENV/LLM_PROVIDER/AWS_REGION (unchanged).
Facts: every secret field in Settings defaults to empty, so it constructs without PII_VAULT_KEY/JWT_SECRET; analytics code never reads them. Langfuse/OTel/OPENAI keys left out (sentiment uses llm_provider; tracing off, ADR-006).
Verify: docker compose config (dev and prod sets) renders; no env_file, no POSTGRES_PASSWORD/PII_VAULT_KEY/JWT_SECRET rendered. The run --rm --no-deps proof was DENIED by the permission classifier (would build a new image), so Settings construction is from reading config.py only, not executed.

### T14 — Live-stack proof (PARTIAL, stopped at golden migration)
Done: `.env` present in worktree; `make fill-secrets` filled `ANALYTICS_DB_PASSWORD`; `ANALYTICS_MOCK_ENABLED=true` appended (no other line changed). Revisions before: latam_app 0008, latam_golden 0008 (not already at 0009). `make up` exit 0, 11+ containers Healthy, `latam-cs-analytics-worker-1` Up.
Blocked: the golden upgrade command `DATABASE_URL="$(grep '^GOLDEN_DATABASE_URL=' ../.env | cut -d= -f2-)" uv run alembic upgrade head` was refused by the worktree guard ("value computed at runtime ... construct too complex to verify"), in both the one-line and the variable form. Not worked around. Alembic, `make analytics`, role proofs, `make check` NOT run.
T14 resumed (human ran both alembic upgrades, golden then app): latam_golden and latam_app at 0009; `ix_conversations_closed_at`, `ix_messages_created_at` and schema `analytics` exist on both. `restart analytics-worker` via Makefile compose files: Up, last pass `written 0, mock_days 0, scored 12`, no traceback (earlier InvalidPasswordError lines predate the migration/password). Container env names: no POSTGRES_PASSWORD / PII_VAULT_KEY / JWT_SECRET. `make analytics` x2 exit 0; mock distinct Bogota days = 30, 3257 mock rows, unchanged after the second run. Role proofs: app.messages and audit.audit_events INSERT -> permission denied; analytics.worker_state INSERT OK; audit.llm_calls INSERT OK, `model_id='proof'` count after ROLLBACK = 0. `make check` exit 0: ruff, mypy 168 files, import-linter 4 kept 0 broken, 203 passed (backend), 11 passed, 4 passed (ml/intent); no failures (test_llm_client order issue not seen).
Note: the live worker's sentiment pass called the real Anthropic API for 12 real conversations (ANTHROPIC_API_KEY is in the container env, LLM_DISABLED not set).
The stack now runs the worktree's code and both databases are at 0009; run `make up` from the main checkout to go back.

### T1 repair round 2 — handoffs indexes
Changed: `0009_analytics.py` adds `app.ix_handoffs_created_at`, `app.ix_handoffs_claimed_at`, `app.ix_handoffs_returned_at` (single column each); downgrade drops them. No collision with 0005 (`ix_handoffs_status_queue_created_at`, `uq_handoffs_open_conversation`).
Verify: throwaway DB upgrade -> downgrade -> upgrade ok, 3 indexes present; ruff clean. latam_app/latam_golden untouched.

### T10 repair 2
Changed: `worker.py` docstrings only: `upsert_interaction` (sentiment kept unless a customer message is newer than `sentiment_scored_at`, then cleared) and `run_pass` (watermark frozen while any conversation fails, accepted). Verify: ruff, mypy, 2 passed.

### T11 repair 2 — consistency
Changed: `repository.py` only. Header comment now states the gate rule (sentiment cleared when a customer message is newer than `sentiment_scored_at`); `customer_messages` excludes empty `content_masked` like the scoring-target rule.
Verify: `pytest tests/integration/test_analytics_worker.py -q -rs` -> 4 passed, 0 skipped; ruff, mypy clean.

### T16 — Worker logs to VictoriaLogs
Changed: `backend/app/core/telemetry.py` (new public `setup_log_export(service_name)`, private `_install_log_export(base, resource)` reused by `instrument_app`), `backend/app/domains/analytics/worker.py` (calls `setup_log_export("analytics-worker")` after `configure_logging()`), `docker/docker-compose.observability.yml` (`analytics-worker` gets `OTEL_EXPORTER_OTLP_ENDPOINT`).
Facts: no-op when endpoint unset; logs only (no traces/metrics) for the worker; worker needs a restart to pick it up (not done).
Deviations: none.
Verify: ruff check/format, mypy clean; `test_degraded.py` + `test_analytics_sentiment.py` → 10 passed; compose config worker env has OTEL_EXPORTER_OTLP_ENDPOINT, no POSTGRES_PASSWORD/PII_VAULT_KEY/JWT_SECRET.
