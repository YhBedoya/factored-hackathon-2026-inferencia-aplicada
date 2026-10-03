# Plan: REQ-interaction-analytics-dashboard — admin analytics endpoint and page

Spec: [`docs/specs/interaction-analytics-dashboard.md`](../specs/interaction-analytics-dashboard.md) · Branch: `feat/interaction-analytics-dashboard` (stacked on `feat/interaction-analytics-pipeline` @ 8ba859e) · Owner: Dev A

Execution model: tasks in the same wave run at the same time **in one shared checkout**, the worktree `/home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline`. There are no extra worktrees, branches or commits; the orchestrator commits. Within a wave, no two tasks touch the same file. Work only in this worktree. Never read or copy `.env` or `data/` from the main checkout.

## Facts checked against the repo

**Baseline (HEAD `8ba859e`, stack up from this worktree):**
- Uncommitted files that belong to this card's commit:
  - `docs/requirements/interaction-analytics-dashboard.md` (M, open questions marked answered);
  - `docs/specs/interaction-analytics-pipeline.md` (M, OQ1/OQ3 closed);
  - `docs/specs/interaction-analytics-dashboard.md` (new).
- `backend/.mypy_cache` is **not** git-ignored. Never run `git add -A` or `git add .`.
- Running containers include `latam-cs-{backend,analytics-worker,postgres,nginx,frontend}-1`.
  - The backend runs with `--reload` from this worktree's `backend/app` mount, so a new route is served without a restart.
  - The analytics worker writes to the **dev** DB `latam_app` only.
- Alembic head is `0009`. **This card has no migration.**
- Card 1's last `make check` reported: 203 passed (backend), import-linter 4 kept / 0 broken. A new red belongs to the task that caused it.
- Dev DB `latam_app`:
  - `analytics.interactions` has 3257 `mock` rows (30 Bogota days) and 16 `real` rows;
  - `identity.accounts` has one admin account, username `admin`. Its password is only in the main checkout's `data/secrets/staff_credentials.csv`, which agents must not open.

**Fact tables (migration `backend/app/alembic/versions/0009_analytics.py`, read-only for this card, D16):**
- `analytics.interactions`, PK `conversation_id` uuid. Columns:
  - Identity and time: `source` (`real`/`mock`), `started_at`, `ended_at` (indexed `ix_interactions_ended_at`), `end_reason` (`customer_closed`/`idle`/`handoff_returned`), `duration_s`.
  - Dimensions: `language` (`es`/`pt`), `country` (`MX`/`CO`/`AR`), `channel`.
  - Counts (int NOT NULL default 0): `customer_messages`, `bot_messages`, `agent_messages`, `turns`, `real_intent_count`.
  - Outcome flags: `resolved` (nullable bool), `abandoned`, `abstained`, `degraded`, `escalated`.
  - Handoff: `handoff_count`, `handoff_queue`, `handoff_reason`, `handoff_cause_group`, `time_to_claim_s` (nullable int).
  - Cost: `cost_usd`, `cost_nlu_usd`, `cost_compose_usd`, `cost_handoff_summary_usd` (all Numeric(12,6)), `llm_call_count`.
  - Sentiment: `sentiment_overall`, `sentiment_start`, `sentiment_end` (`negative`/`neutral`/`positive`, nullable), `sentiment_model`, `sentiment_prompt_version`, `sentiment_cost_usd` (nullable), `sentiment_scored_at`.
  - Bookkeeping: `computed_at`, `metrics_version`.
- `analytics.interaction_intents`, PK (`conversation_id`, `seq`). Columns: `intent`, `outcome` (`resolved`/`handoff`/`abstained`/`abandoned`/`cancelled`), `needed_clarification`, `turns`, `bot_offered`.
- Mock values (card 1 `mock_profile.yaml`):
  - cause groups `by_design`, `customer_choice`, `bot_failure`, `security`;
  - queues `fraudes`, `reclamos`, `atencion`.
- `app.core.db.get_engine()` connects as the owner role and can read `analytics`. It is `lru_cache`d and **loop-bound**: after every `asyncio.run(...)`, a test calls `get_engine.cache_clear()`.
- `backend/app/core/config.py` already has `analytics_timezone: str = "America/Bogota"`. No new setting is needed.
- `backend/app/domains/analytics/__init__.py` is a docstring only, so importing `app.domains.analytics.dashboard` pulls in nothing else.
  - The domain's other modules read `app`/`audit`/`bank`.
  - `dashboard.py` must read **only** `analytics.*`, and must not import `worker`, `repository`, `sentiment`, `mock` or any `app.domains.conversation` module.

**Backend conventions:**
- Admin router: `backend/app/api/v1/staff_admin.py` is `APIRouter(prefix="/staff", dependencies=[Depends(require_role("admin")), Depends(require_csrf)])`.
  - It is already included by `backend/app/api/v1/__init__.py`.
  - `require_csrf` skips GET.
  - Error precedent: `HTTPException(status_code=422, detail="invalid_status")` in `staff.py::list_conversations`. That route also uses `Literal["es","pt"]` / `Literal["MX","CO","AR"]` query params, so FastAPI answers an unknown value with 422 by itself.
- `backend/tests/unit/test_r13_routes.py::test_every_route_declares_role_and_ownership`:
  - `/api/v1/staff/personas*` must have exactly `[("admin",)]`;
  - every other `/api/v1/staff/` route must include `("agent","admin")`.
  - So the new route **fails this test until the branch is amended in the same task**.
- Integration fixtures, in `backend/tests/integration/conftest.py`:
  - `it_db`: a session-scoped throwaway DB `latam_it_<hex>` at `alembic upgrade head`. It skips if Postgres is unreachable.
  - `it_env`: points `DATABASE_URL` at `it_db`; skips if Redis is unreachable.
  - `app_client`: a `TestClient(create_app())`.
  - `it_staff`: two agents keyed by queue, type `ItStaff(account_id, username, password, display_name, queue)`.
  - `_insert_staff(list[ItStaff])` inserts with role `'agent'`; `_delete_staff` removes the accounts.
  - There is no admin fixture. `ck_accounts_role` allows `'admin'`, `staff_queue` is nullable, and `uq_accounts_username` is unique.
  - Staff login is `POST /api/v1/auth/staff/login {username, password}` (see `_staff_login` in `backend/tests/integration/test_staff_round_trip.py`).
- Integration tests write only to `it_db`, **never** to `latam_app`.
  - Command: `cd backend && uv run pytest tests/integration/<file> -q -rs`.
  - A `skipped` result is not a pass. Proofs check the last line with `tail -1 | grep -E '^N passed(, [0-9]+ warnings?)? in'`.
- `backend/tests/integration/test_analytics_worker.py` is the seeding precedent. It inserts analytics rows through the engine and deletes what it created (`_forget`).
- mypy is slow on a cold cache (about 10 min in card 1). Run it only on the task's own files.

**Planned backend names (implementers record the real ones in the state file):**
- Module `backend/app/domains/analytics/dashboard.py`, all models frozen pydantic:
  - `AppliedFilters{date_from: date, date_to: date, language: Literal["es","pt"] | None, country: Literal["MX","CO","AR"] | None, source: Literal["all","real","mock"], timezone: str}`. This is both the resolved input and the response's `filters` block.
  - Rates and tiles: `Rate`, `AnalyticsTiles`, `CostTile`, `MessagesTile`.
  - Per-day and intents: `DayOutcomes`, `IntentStat`.
  - Escalations: `GroupCount`, `QueueCount`, `EscalationStats`.
  - Sentiment: `SentimentSplit`, `SentimentTrajectory`, `SentimentStats`.
  - Cost: `DayCost`, `ResolvedCost`, `CostStats`.
  - `RecentInteraction` (`outcome: Literal["escalated","resolved","abandoned","abstained","other"]`) and `AnalyticsSummary`.
  - No name collides with a schema in `frontend/src/client/types.gen.ts` today.
  - Do **not** name a model `AnalyticsFilters`: that is the frontend component's name.
- `resolve_filters(date_from, date_to, language, country, source, *, today: date | None = None) -> AppliedFilters`. Defaults are `today − 6 … today` in `analytics_timezone`. It raises `InvalidDateRange(ValueError)` when `date_from > date_to` or the inclusive day count is over 92.
- `async def get_summary(filters: AppliedFilters) -> AnalyticsSummary`. It runs one transaction:
  - `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`, then `SET LOCAL statement_timeout = '5s'`, so every block sees one snapshot and one `now()`.
  - It raises `AnalyticsTimeout` on SQLSTATE `57014`.
- Route handler `get_analytics_summary` in `staff_admin.py`:
  - `InvalidDateRange` → `HTTPException(422, detail="invalid_date_range")`;
  - `AnalyticsTimeout` → `HTTPException(503, detail="analytics_timeout")`.
  - Expected SDK name: `getAnalyticsSummaryApiV1StaffAnalyticsSummaryGet` (T6 records the real one).

**Frontend conventions:**
- Host `frontend/node_modules` is empty. **Every** npm/npx command runs in the container: `docker exec -w /app latam-cs-frontend-1 sh -c "…"`.
- The container is `node:22`, running as root. The worktree's `frontend/` is bind-mounted at `/app`, and `/app/node_modules` is an anonymous volume. The command is `sh -c "npm ci && npm run dev"`, so `docker restart latam-cs-frontend-1` reinstalls from the lockfile.
- Files the container creates are root-owned. After any container command that writes under `/app`, run:
  `docker exec latam-cs-frontend-1 chown -R 1000:1000 /app/src /app/e2e /app/package.json /app/package-lock.json`
  This is harmless when run concurrently.
- Lint and format check your own files only, with explicit paths: `docker exec -w /app latam-cs-frontend-1 npx biome ci <paths>`.
  - Biome ignores `src/client` and `src/routeTree.gen.ts`.
  - Files use tabs.
  - Line endings are LF (Linux host).
- Typecheck while siblings are writing: filter the output to your own paths (the d4-b precedent):
  `docker exec -w /app latam-cs-frontend-1 sh -c "npm run -s typecheck > /tmp/tc-<task>.txt 2>&1; ! grep -E 'src/(<your paths>)' /tmp/tc-<task>.txt"`
  - `tsconfig.app.json` includes only `src`, so `e2e/` is not typechecked.
- Only one task at a time runs `npm run build` (it writes `dist/` and runs `tsc -b` over everything). In this plan that is T1, T11 and T12, each alone in its wave.
- Playwright (`frontend/playwright.config.ts`) runs against `npm run preview` on port 4173 with `reuseExistingServer`.
  - Kill a stale preview first: `pkill -f 'vite preview' || true`.
  - The API is mocked with `page.route`.
  - The container has **no Playwright browser** today. T1 installs chromium (`npx playwright install --with-deps chromium`). It survives `docker restart` but not a container recreate; if it is lost, re-run that command.
- `src/routeTree.gen.ts` is git-ignored. It is regenerated by `npm run build` and by the container's vite dev server. If `/staff/analytics` 404s in the dev stack, run `docker restart latam-cs-frontend-1`.
- `make client` doesn't work from the host. The equivalent is:
  `docker exec -w /app latam-cs-frontend-1 npx @hey-api/openapi-ts -i http://nginx/api/v1/openapi.json`
  - Afterwards, `src/client/client.gen.ts` must contain no `http://`.
  - Never hand-edit `src/client/`.
- `src/lib/api.ts` patterns:
  - `withStaffAuth(() => sdkCall())` (a `401` goes to `/staff/login`) and `unwrap`;
  - query types are aliased as `export type StaffConversationQuery = NonNullable<ListConversationsApiV1StaffConversationsGetData["query"]>`;
  - `staffMe(): Promise<StaffMeResponse | null>`, where `role: "agent" | "admin"`.
- `src/routes/staff/index.tsx` (inbox):
  - `beforeLoad` calls `staffMe()` and redirects to `/staff/login` when there is no session;
  - it renders `<Link to="/staff/conversations">{t("staff.conversations.nav_link")}</Link>`.
  - There is no admin UI anywhere in the frontend yet.
- Patterns to follow:
  - `src/components/staff/ConversationTable.tsx`: `Link` to `/staff/conversations/$conversationId`, dates with `new Date(x).toLocaleString()`.
  - `ConversationFilters.tsx`: native `<select>`/`<input>`, `data-testid="filter-*"`, raw codes for intents and countries.
  - `TurnTimeline.tsx`: has a private `formatUsd` (`US$ ${usd.toFixed(4)}`, `—` for null); the D13 precedent.
- `src/components/ui/` has `button`, `card`, `dialog`, `input`, `label`, `select`. There is no `chart.tsx` and no `recharts` dependency.
- `src/index.css`:
  - `@theme` defines `--color-bg #070b1a`, `--color-cyan #3dd6e0`, `--color-gold #f5c66b`, `--color-alert #ff6b6b`;
  - `:root` maps the shadcn variables onto them;
  - there are no `--chart-*` variables.
  - `components.json` uses style `radix-nova` with `cssVariables: true`.
- Chart colours (from `docs/brand.md`: cyan = Cardy and completed actions, gold = human agent, alert = escalation):
  - `--chart-1` = cyan: resolved, NLU, positive, better.
  - `--chart-2` = alert: escalated, negative, worse.
  - `--chart-3` = gold: queues, handoff summary, neutral, same.
  - `--chart-4` = `color-mix(in oklab, var(--color-cyan) 45%, var(--color-bg))`: abandoned, compose.
  - `--chart-5` = `var(--muted-foreground)`: abstained, other.
- i18n:
  - Flat keys in `src/lib/i18n/es.json` and `pt.json`. `TKey = keyof typeof es`, so a key missing from `pt` is a type error.
  - Reuse `staff.queue.{atencion,cobranza,fraudes,reclamos}` and `lang.es`/`lang.pt`.
  - Countries and intents are shown as raw codes (precedent).
- Mock API (`frontend/e2e/mock-staff-api.ts`):
  - `installMockStaffApi(page, {password, agentDisplayName?})`;
  - the `/staff/me` profile has `role: "agent"` hard-coded;
  - unmatched `/api/v1/**` paths get a catch-all `404`;
  - it is used by `e2e/staff.es.spec.ts` and `e2e/traceability.es.spec.ts`, which must keep passing.

**Planned frontend names:**
- `api.ts`:
  - `export type AnalyticsQuery = NonNullable<<SDK>Data["query"]>`;
  - `export async function getAnalyticsSummary(query: AnalyticsQuery): Promise<AnalyticsSummary>`.
  - The route's `validateSearch` returns an `AnalyticsQuery`.
- Block component props: `{ summary: AnalyticsSummary | undefined; isLoading: boolean; isError: boolean }`. The filters, badge and footer take what they need.
- i18n keys (all under `staff.analytics.`, in both dictionaries):
  - `nav_link`, `title`;
  - `filter.date_from`, `filter.date_to`, `filter.language`, `filter.country`, `filter.source`, `filter.all`;
  - `source.all`, `source.real`, `source.mock`;
  - `mock_badge`, which is **verbatim** ES "Incluye datos simulados" / PT "Inclui dados simulados";
  - `mock_footer`, which is **verbatim** ES "Este tablero se alimenta de datos simulados para demostrar su funcionalidad en ambientes productivos con tráfico real" / PT "Este painel é alimentado por dados simulados para demonstrar sua funcionalidade em ambientes de produção com tráfego real";
  - `tile.interactions`, `tile.resolution`, `tile.escalation`, `tile.cost`, `tile.messages`, `tile.negative`;
  - `chart.per_day`, `chart.intents`, `chart.escalations`, `chart.sentiment`, `chart.cost`;
  - `outcome.escalated`, `outcome.resolved`, `outcome.abandoned`, `outcome.abstained`, `outcome.other`;
  - `intents.volume`, `intents.resolution`;
  - `escalations.by_cause_group`, `escalations.by_queue`, `escalations.median_claim`, `escalations.unknown`;
  - `cause.by_design`, `cause.customer_choice`, `cause.bot_failure`, `cause.security`;
  - `sentiment.overall`, `sentiment.trajectory`, `sentiment.negative`, `sentiment.neutral`, `sentiment.positive`, `sentiment.better`, `sentiment.same`, `sentiment.worse`;
  - `cost.nlu`, `cost.compose`, `cost.handoff_summary`, `cost.total`, `cost.per_resolved`, `cost.sentiment_overhead`;
  - `table.title`, `table.ended_at`, `table.end_reason`, `table.intents`, `table.outcome`, `table.sentiment`, `table.cost`, `table.open`;
  - `end_reason.customer_closed`, `end_reason.idle`, `end_reason.handoff_returned`;
  - `state.loading`, `state.error`, `state.empty`.
- `data-testid`s:
  - Navigation: `analytics-nav-link`.
  - Filters: `analytics-filter-date-from`, `analytics-filter-date-to`, `analytics-filter-language`, `analytics-filter-country`, `analytics-filter-source` (option values `all`/`real`/`mock`).
  - Mock notices: `analytics-mock-badge`, `analytics-mock-footer`.
  - Tiles: `analytics-tile-{interactions,resolution,escalation,cost,messages,negative}`.
  - Charts: `analytics-chart-{per-day,intents,escalations,sentiment,cost}`.
  - Table: `analytics-recent` (the table block), `analytics-recent-row`, `analytics-recent-link`.
  - Block states: `analytics-block-loading`, `analytics-block-error`, `analytics-block-empty`.

**Docs and README:**
- `docs/solution-docs/04-contracts.md` §3 "HTTP API" starts at line 86. The `GET /staff/personas` row is at line 114, and the new row goes right after it.
- `README.md` (lines 166–171, "Provenance of the analytics rows") already lists `analytics.*` `source='mock'` rows as team-generated synthetic. REQ-R3.3 is checked here, not edited (D16).

## Components

| Component | Path | Depends on |
|---|---|---|
| Summary query and models | `backend/app/domains/analytics/dashboard.py` (new) | `app.core.db.get_engine`, `app.core.config.get_settings`; the `analytics` schema only |
| Admin route | `backend/app/api/v1/staff_admin.py` (modified) | `dashboard.resolve_filters`, `dashboard.get_summary`; router guard already admin + CSRF |
| R13 admin-only branch | `backend/tests/unit/test_r13_routes.py` (modified) | the route |
| Integration tests | `backend/tests/integration/test_analytics_summary.py` (new) | `it_db`, `it_env`, `app_client`, `it_staff`, `_insert_staff`/`_delete_staff` |
| Recharts and shadcn chart | `frontend/package.json`, `package-lock.json`, `src/components/ui/chart.tsx` (new), `src/index.css` (`--chart-*`) | shadcn CLI in the container |
| i18n, format helpers, block frame | `src/lib/i18n/{es,pt}.json`, `src/components/staff/analytics/format.ts`, `BlockFrame.tsx` (new) | `components/ui/card.tsx` |
| Generated client and API wrapper | `src/client/*`, `src/lib/api.ts` | the live route on the dev backend |
| Filters, badge and footer, tiles | `src/components/staff/analytics/{AnalyticsFilters,MockDataNotice,SummaryTiles}.tsx` | client types, `format.ts`, `BlockFrame`, i18n |
| Charts | `src/components/staff/analytics/{OutcomesPerDayChart,IntentsChart,EscalationsChart,SentimentChart,CostChart}.tsx` | `ui/chart.tsx`, client types, `format.ts`, `BlockFrame`, i18n |
| Recent table | `src/components/staff/analytics/RecentInteractionsTable.tsx` | client types, `format.ts`, `BlockFrame`, i18n |
| Page, nav, e2e | `src/routes/staff/analytics.tsx` (new), `src/routes/staff/index.tsx`, `e2e/analytics.es.spec.ts` (new), `e2e/mock-staff-api.ts`, `e2e/fixtures/analytics-summary.ts` (new) | all of the above |
| Contract doc | `docs/solution-docs/04-contracts.md` §3 | spec "Contracts" |

## Build order

1. **T1: frontend dependency (alone).** It changes `package.json`, the lockfile and the container's `node_modules`. Every chart task needs `ui/chart.tsx`. The browser install is also needed by T11.
2. **T2, T3, T4 in parallel.**
   - T2: the query module and its oracle tests have no frontend dependency.
   - T3: i18n keys and format helpers depend on nothing generated.
   - T4: the doc row.
3. **T5: the route,** after T2 (it imports `dashboard`). The R13 amendment must ship in the same task, or `test_r13_routes.py` goes red.
4. **T6: client regeneration,** after T5. It needs the route served by the hot-reloaded dev backend.
5. **T7, T8, T9, T10 in parallel.** These are the UI blocks. They need the client types (T6), `chart.tsx` (T1) and the i18n keys, `format.ts` and `BlockFrame` (T3). Their files are disjoint, and none of them builds.
6. **T11: page, nav and e2e.** It assembles every block and proves the page with Playwright (one build).
7. **T12: live proof (alone).** The full stack and the human's browser check.

## Touch map

| File | New / modified | Change | Task |
|---|---|---|---|
| `frontend/package.json`, `frontend/package-lock.json` | modified | `recharts` dependency | T1 |
| `frontend/src/components/ui/chart.tsx` | new | shadcn chart component | T1 |
| `frontend/src/index.css` | modified | `--chart-1..5` on brand tokens | T1 |
| `backend/app/domains/analytics/dashboard.py` | new | filters, models, one-snapshot summary query, timeout | T2 |
| `backend/tests/integration/test_analytics_summary.py` | new, then modified | `test_summary_matches_fact_tables`, `test_summary_future_and_mock` (T2); `test_summary_access` (T5) | T2, T5 |
| `frontend/src/lib/i18n/es.json`, `pt.json` | modified | `staff.analytics.*` | T3 |
| `frontend/src/components/staff/analytics/format.ts` | new | `formatUsd`, `formatPercent`, `formatRatio`, `formatAvg`, `formatSeconds` | T3 |
| `frontend/src/components/staff/analytics/BlockFrame.tsx` | new | titled card with loading, error and empty states | T3 |
| `docs/solution-docs/04-contracts.md` | modified | §3 endpoint row | T4 |
| `backend/app/api/v1/staff_admin.py` | modified | `GET /staff/analytics/summary` | T5 |
| `backend/tests/unit/test_r13_routes.py` | modified | admin-only branch includes `/api/v1/staff/analytics` | T5 |
| `frontend/src/client/*` | regenerated | new SDK function and types | T6 |
| `frontend/src/lib/api.ts` | modified | `AnalyticsQuery`, `getAnalyticsSummary` | T6 |
| `frontend/src/components/staff/analytics/AnalyticsFilters.tsx`, `MockDataNotice.tsx`, `SummaryTiles.tsx` | new | filters, badge and footer, six tiles | T7 |
| `.../OutcomesPerDayChart.tsx`, `IntentsChart.tsx`, `EscalationsChart.tsx` | new | three charts | T8 |
| `.../SentimentChart.tsx`, `CostChart.tsx` | new | two charts, cost figures, overhead | T9 |
| `.../RecentInteractionsTable.tsx` | new | 50-row table, real-row link | T10 |
| `frontend/src/routes/staff/analytics.tsx` | new | page, `beforeLoad`, `validateSearch`, one query | T11 |
| `frontend/src/routes/staff/index.tsx` | modified | admin-only nav link | T11 |
| `frontend/e2e/mock-staff-api.ts` | modified | `role` option, summary route | T11 |
| `frontend/e2e/fixtures/analytics-summary.ts` | new | summary fixture by `source` | T11 |
| `frontend/e2e/analytics.es.spec.ts` | new | Playwright test | T11 |
| `frontend/src/routeTree.gen.ts` | regenerated (git-ignored) | new route | T11, T12 |

Card 1 files (`mock_profile.yaml`, `worker.py`, `0009_analytics.py`) are **not** touched (D16).

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| `shadcn add chart` pulls a dependency other than `recharts`, or needs a `react-is` override for React 19 (spec "Ask first") | T1 checks that the `package.json` dependency diff is exactly `+recharts`. If not, it reverts and stops with a question. |
| Container-written files are root-owned, and the host can't edit them | Every container write step ends with the `chown` line in Facts (T1, T6, T11, T12). |
| `node_modules` drift between the lockfile and the container | T1 restarts the frontend container, so `npm ci` reinstalls from the new lockfile, then checks `npm ls recharts`. |
| Biome flags `dangerouslySetInnerHTML` or style issues in the generated `chart.tsx` | T1 runs `biome ci` on `chart.tsx`. It fixes formatting with `biome format --write` and adds a `biome-ignore` comment with a reason on the `ChartStyle` line only. |
| Chromium is missing in the container, so Playwright can't run | T1 installs it. T11 and T12 re-run the install if a recreate wiped it. |
| The query reads `app`/`audit`/`bank`, or imports conversation code (spec "Never") | T5 Verify greps `dashboard.py` for `app\.\|audit\.\|bank\.\|identity\.` table refs and `conversation` imports, plus `lint-imports`. |
| Blocks read different snapshots or different `now()` while the worker writes | T2 runs one `REPEATABLE READ, READ ONLY` transaction. Acceptance requires it. |
| Slow query holds a connection | T2: `SET LOCAL statement_timeout = '5s'` → `AnalyticsTimeout` → 503 (T5). |
| Loop-bound engine breaks the second `asyncio.run` in a test | T2 and T5 call `get_engine.cache_clear()` after each `asyncio.run` (Facts). |
| Tests touch the shared dev DB | All integration tests use `it_env`/`it_db`, and seeded rows are deleted on teardown (T2, T5). |
| Leftover analytics rows in `it_db` from other tests skew the counts | T2 compares against an oracle SQL over the same `it_db`, not hard-coded numbers. The seeded rows still exercise every bucket and filter value. |
| An integration skip is read as a pass | Every integration Verify checks the exact `N passed` tail line. |
| The new route fails R13 before the test is amended | Route and amendment are in one task (T5), with a two-way bite check. |
| Stale route tree or stale preview server | T11 builds (which regenerates the tree) and kills port 4173 first. T12 restarts the frontend container if `/staff/analytics` isn't served. |
| Client regeneration brings unrelated drift | T6 keeps the drift (never hand-edits) and records the drifted files in the state file. If an unrelated **signature** changed, it stops and reports. |
| Parallel frontend tasks see each other's half-written type errors | W5 tasks filter typecheck to their own paths and don't build. T11 runs the one full build. |
| `git add -A` would stage `backend/.mypy_cache` | Facts and every task's Files list explicit paths. The orchestrator stages by path. |
| The SC7 browser check needs admin credentials the agent must not open | T12 does every machine check. The browser login is the human's step, listed in T12's Acceptance. |

## Tests

| Test | Proves | Task |
|---|---|---|
| `backend/tests/unit/test_r13_routes.py` (amended) | DD1 / R13: `/api/v1/staff/analytics*` is admin-only | T5 |
| `test_summary_access` in `backend/tests/integration/test_analytics_summary.py` | DD1: agent → `403 forbidden_role`, admin → `200` | T5 |
| `test_summary_matches_fact_tables` (same file) | DD2, DD3, D1, D3 | T2 |
| `test_summary_future_and_mock` (same file) | DD5, DD4 API side | T2 |
| `frontend/e2e/analytics.es.spec.ts` | DD1 nav, DD2 render, DD4, DD6, D7 | T11 |

Criterion coverage:
- SC1: T5.
- SC2, SC3: T2.
- SC4: T11.
- SC5: T12 (`npm run lint`/`typecheck`); the verifier runs `make check`.
- SC6: T4.
- SC7: T12 (human browser step).

## Tasks

- [ ] T1: Add Recharts through shadcn's chart component, brand chart colours, and a Playwright browser in the frontend container
  - Depends on: nothing
  - Read exactly these: `frontend/components.json`; `frontend/src/index.css` (`@theme` and `:root`); `docs/brand.md` (colour section); this plan's Facts "Frontend conventions" (container, chown, chart colours)
  - Acceptance:
    - Inside the container, `docker exec -w /app latam-cs-frontend-1 npx shadcn@4 add chart -y` (use the local `shadcn` dependency; never overwrite existing `ui/*` files) has created `src/components/ui/chart.tsx`, and `recharts` is in `dependencies`. The `package.json` diff adds **only** `recharts`. Any other added dependency or override means `git checkout -- frontend/package.json frontend/package-lock.json`, delete `chart.tsx`, and **stop with a question** (spec "Ask first").
    - `src/index.css` defines `--chart-1..5` in `:root` with the mapping in Facts. If shadcn wrote `--chart-*` in oklch or under `.dark`, replace them with the brand mapping (this app has no `.dark` split).
    - `docker restart latam-cs-frontend-1` succeeds. After it, `npm ls recharts` in the container shows the version from the lockfile. This proves the container's anonymous `node_modules` volume was reinstalled by `npm ci`.
    - `npx playwright install --with-deps chromium` has run in the container.
    - `chart.tsx` passes `biome ci`. Use `biome format --write` for layout. A `biome-ignore lint/security/noDangerouslySetInnerHtml: <reason>` is allowed only on shadcn's `ChartStyle` line.
    - The chown line from Facts has run, and `ls -n` shows uid 1000 on `package.json`, `package-lock.json`, `src/index.css` and `src/components/ui/chart.tsx`.
    - The state file records the installed `recharts` version and whether a biome-ignore was needed.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npm ls recharts && npx biome ci src/components/ui/chart.tsx src/index.css && npm run -s typecheck && npm run -s build" && git -C /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline diff frontend/package.json`
  - Files: `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/components/ui/chart.tsx`, `frontend/src/index.css`

- [ ] T2: Summary query module (`app.domains.analytics.dashboard`) with the fact-table oracle tests
  - Depends on: nothing (T1 is frontend-only; T2 waits only for the wave order)
  - Read exactly these: spec §"Decisions" D1, D3, D4, D10–D12 and §"Contracts"; `backend/app/alembic/versions/0009_analytics.py`; `backend/tests/integration/test_analytics_worker.py` (fixture use, `get_engine.cache_clear()`, row insert and `_forget` cleanup)
  - Acceptance:
    - The module exists with the planned names in Facts: `AppliedFilters`, the response models, `resolve_filters`, `get_summary`, `InvalidDateRange` and `AnalyticsTimeout`. The response shape matches spec §"Contracts" exactly (field names, nullability). Money is a `float` in USD.
    - It imports only `app.core.*`, pydantic, sqlalchemy and the stdlib, and its SQL names only `analytics.interactions` and `analytics.interaction_intents`. Don't write `app.`, `audit.`, `bank.` or `identity.` followed by a name anywhere in the file, not even in a comment or docstring, except in `from app.core… import` lines: T5's guard greps for them.
    - `get_summary` runs one transaction with these first statements: `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`, then `SET LOCAL statement_timeout = '5s'`. SQLSTATE `57014` becomes `AnalyticsTimeout`.
    - Every block, including `includes_mock`, applies:
      - `ended_at <= now()`;
      - the local-date range on `(ended_at AT TIME ZONE :tz)::date`, with `tz = get_settings().analytics_timezone`;
      - `language`, `country`, and `source` (unless `all`).
    - `per_day` buckets follow D1, in order escalated → resolved → abandoned → abstained → other. Both `per_day` and `cost.per_day` list every day in the range, with zeros.
    - Intents: rows with `bot_offered AND outcome = 'cancelled'` are excluded from `intents` and from each recent row's `intents` (D3). The per-intent `resolution` is `Rate(num = rows with outcome 'resolved', den = counted rows)`. Intents are sorted by count descending, ties by intent name.
    - Rates follow D11, with `rate = null` when `den = 0`. `cost.sentiment_overhead_usd = sum(sentiment_cost_usd)` and is never added to any other cost (D12).
    - `recent` holds at most 50 rows, ordered by `ended_at` descending.
    - `resolve_filters` sets the defaults and raises `InvalidDateRange` for `date_from > date_to` or more than 92 inclusive days.
    - `tests/integration/test_analytics_summary.py` has two tests, both on `it_env` (throwaway `it_db`):
      - `test_summary_matches_fact_tables` seeds real and mock rows relative to now in the analytics tz. The rows cover every D1 bucket, including a cancelled-only row; both languages; two countries; a bot-offered cancelled intent; a null cause group and a null queue; sentiment start/end pairs. For the default filters, and for one changed value each of the date range, `language`, `country` and `source`, every block equals an independent SQL oracle over `analytics.*` in `it_db`. Floats use `pytest.approx`. The test asserts that `sum(per_day buckets) == tiles.interactions` and that the bot-offered cancelled intent is absent.
      - `test_summary_future_and_mock` seeds a mock row whose `ended_at` is later today, and proves it is in no block. It also proves `includes_mock` is true under `all` and false under `real`.
      - Both tests delete their seeded rows on teardown and call `get_engine.cache_clear()` after each `asyncio.run`.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline/backend && uv run pytest tests/integration/test_analytics_summary.py -q -rs | tail -1 | grep -E '^2 passed(, [0-9]+ warnings?)? in' && uv run python -c "from datetime import date as d; from app.domains.analytics.dashboard import resolve_filters as r, InvalidDateRange as E; f = r(None, None, None, None, 'all'); assert (f.date_to - f.date_from).days == 6; bad = [(d(2026,1,2), d(2026,1,1)), (d(2026,1,1), d(2026,4,3))]; import pytest; [pytest.raises(E, r, x, y, None, None, 'all') for x, y in bad]; print('range ok')" && uv run ruff check app/domains/analytics/dashboard.py tests/integration/test_analytics_summary.py && uv run ruff format --check app/domains/analytics/dashboard.py tests/integration/test_analytics_summary.py && uv run mypy app/domains/analytics/dashboard.py`
  - Files: `backend/app/domains/analytics/dashboard.py`, `backend/tests/integration/test_analytics_summary.py`

- [ ] T3: Analytics i18n keys, money/percent format helpers and the block frame
  - Depends on: nothing (T1 is environment-only; T3 waits only for the wave order)
  - Read exactly these: `frontend/src/lib/i18n/es.json` (key style; existing `staff.queue.*`, `lang.*`); `frontend/src/components/staff/TurnTimeline.tsx` (the `formatUsd` precedent); `frontend/src/components/ui/card.tsx`
  - Acceptance:
    - Every `staff.analytics.*` key listed in Facts is present in **both** `es.json` and `pt.json`. `mock_badge` and `mock_footer` are verbatim from Facts (D6, D7). Other labels are short ES and PT strings in Cardy's register (no emojis).
    - `src/components/staff/analytics/format.ts` exports pure functions over primitives (no client types, no `Intl`):
      - `formatUsd(usd: number | null, digits = 4)`: `US$ 0.0123`, or `—` for null. This is the **only** money formatter the page uses (D13).
      - `formatPercent(rate: number | null)`: one decimal and `%`, or `—`.
      - `formatRatio(num: number, den: number)`: `num/den`.
      - `formatAvg(value: number | null, digits = 1)`.
      - `formatSeconds(s: number | null)`: `m:ss`, or `—`.
    - `src/components/staff/analytics/BlockFrame.tsx` exports `BlockFrame({ title, testId, isLoading, isError, isEmpty, children })`:
      - it is a `Card` with `data-testid={testId}` that always renders the title;
      - while loading it shows `data-testid="analytics-block-loading"` with `t("staff.analytics.state.loading")`;
      - on error it shows `analytics-block-error` with `state.error`;
      - when empty it shows `analytics-block-empty` with `state.empty`;
      - otherwise it shows `children`.
    - The chown line from Facts has run if any container command wrote files.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/lib/i18n/es.json src/lib/i18n/pt.json src/components/staff/analytics/format.ts src/components/staff/analytics/BlockFrame.tsx && (npm run -s typecheck > /tmp/tc-T3.txt 2>&1; ! grep -E 'src/(lib/i18n|components/staff/analytics/(format|BlockFrame))' /tmp/tc-T3.txt)"`
  - Files: `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`, `frontend/src/components/staff/analytics/format.ts`, `frontend/src/components/staff/analytics/BlockFrame.tsx`

- [ ] T4: Add the analytics summary endpoint to `04` §3 and confirm the README provenance row
  - Depends on: nothing
  - Read exactly these: `docs/solution-docs/04-contracts.md` lines 86–130 (§3 table, `GET /staff/personas` row at line 114); spec §"Contracts" ("Endpoint" and "Errors"); `README.md` lines 160–175
  - Acceptance:
    - A new row right after the personas row, in the table's existing column style, for `GET /staff/analytics/summary?date_from=&date_to=&language=&country=&source=`, admin, response `AnalyticsSummary`. It notes:
      - reads only `analytics`;
      - 5 s statement timeout;
      - `ended_at <= now()`;
      - inclusive local dates (default the last 7 days, at most 92);
      - errors `403 forbidden_role`, `422`, `503 analytics_timeout`;
      - it cites the spec.
    - `README.md` is unchanged and still lists `source='mock'` analytics rows as team-generated synthetic (REQ-R3.3, D16). If it doesn't, stop and report; don't edit.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline && grep -n "staff/analytics/summary" docs/solution-docs/04-contracts.md && grep -nE "source *= *'?mock" README.md && git diff --quiet README.md`
  - Files: `docs/solution-docs/04-contracts.md`

- [ ] T5: Admin-only `GET /staff/analytics/summary` route, R13 amendment and the access test
  - Depends on: T2 (`dashboard.resolve_filters`, `get_summary`, `InvalidDateRange`, `AnalyticsTimeout`, `AnalyticsSummary`; real names in the state file; `test_analytics_summary.py` exists)
  - Read exactly these: `backend/app/api/v1/staff_admin.py`; `backend/tests/unit/test_r13_routes.py` (the `/api/v1/staff/personas` branch); `backend/tests/integration/conftest.py` (`it_staff`, `_insert_staff`, `_delete_staff`, `app_client`) and `_staff_login` in `backend/tests/integration/test_staff_round_trip.py`
  - Acceptance:
    - `staff_admin.py` gains `@router.get("/analytics/summary")` with handler name `get_analytics_summary`:
      - query params `date_from: date | None`, `date_to: date | None`, `language: Literal["es","pt"] | None`, `country: Literal["MX","CO","AR"] | None`, `source: Literal["all","real","mock"] = "all"`;
      - it returns `AnalyticsSummary`;
      - `InvalidDateRange` → `422 invalid_date_range`; `AnalyticsTimeout` → `503 analytics_timeout`;
      - it adds no route-level guard (the router's admin + CSRF guard applies).
    - The module docstring mentions the new route.
    - `test_r13_routes.py` treats paths starting with `/api/v1/staff/analytics` like `/api/v1/staff/personas`: roles exactly `[("admin",)]`. Update the docstring line on admin-only routes.
    - `test_summary_access` is appended to `test_analytics_summary.py`:
      - a local fixture inserts one admin with `_insert_staff` (unique username `it.admin.<hex>`), then `UPDATE identity.accounts SET role='admin', staff_queue=NULL`, and removes it with `_delete_staff`;
      - an `it_staff` agent → `403` with `detail == "forbidden_role"`;
      - the admin → `200`, with a body that has `tiles` and `filters.source == "all"`.
    - Bite check, recorded in the state file and reverted:
      - (a) removing `Depends(require_role("admin"))` from the router makes `test_r13_routes.py` fail;
      - (b) adding a route-level `dependencies=[Depends(require_role("agent", "admin"))]` to the summary route makes it fail, with `/api/v1/staff/analytics/summary` in the message.
      - After reverting, `git diff backend/app/api/v1/staff_admin.py` shows only the new route and docstring.
    - Spec "Never" grep: `dashboard.py` names no `app.`, `audit.`, `bank.` or `identity.` table, and imports no `conversation` module.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline/backend && uv run pytest tests/unit/test_r13_routes.py -q && uv run pytest tests/integration/test_analytics_summary.py -q -rs | tail -1 | grep -E '^3 passed(, [0-9]+ warnings?)? in' && ! grep -nE "\b(app|audit|bank|identity)\.[a-z_]+\b" app/domains/analytics/dashboard.py | grep -vE "^\S+:\s*(from|import) app\.core" && ! grep -n "conversation" app/domains/analytics/dashboard.py | grep -E "import" && uv run lint-imports && uv run ruff check app/api/v1/staff_admin.py tests/unit/test_r13_routes.py tests/integration/test_analytics_summary.py && uv run ruff format --check app/api/v1/staff_admin.py tests/unit/test_r13_routes.py tests/integration/test_analytics_summary.py && uv run mypy app/api/v1/staff_admin.py`
  - Files: `backend/app/api/v1/staff_admin.py`, `backend/tests/unit/test_r13_routes.py`, `backend/tests/integration/test_analytics_summary.py`

- [ ] T6: Regenerate the OpenAPI client and add `getAnalyticsSummary` to `api.ts`
  - Depends on: T5 (the route is served by the hot-reloaded dev backend at `http://nginx/api/v1/openapi.json`)
  - Read exactly these: `frontend/src/lib/api.ts` (staff section: `withStaffAuth`, `unwrap`, `StaffConversationQuery`, `listStaffConversations`); this plan's Facts "Frontend conventions" (`make client` equivalent, chown)
  - Acceptance:
    - Before regenerating, `curl -s http://localhost/api/v1/openapi.json | grep -c '/api/v1/staff/analytics/summary'` is ≥ 1. If not, check `docker logs --tail 50 latam-cs-backend-1` for a reload error and stop; don't restart services.
    - The client is regenerated with the container command in Facts, the chown line has run, and `src/client/client.gen.ts` contains no `http://`.
    - `api.ts` exports:
      - `type AnalyticsQuery = NonNullable<<SDK>Data["query"]>`;
      - `getAnalyticsSummary(query: AnalyticsQuery): Promise<AnalyticsSummary>`, through `withStaffAuth` and `unwrap`;
      - it re-exports the `AnalyticsSummary`, `RecentInteraction` and `Rate` types if the file's pattern re-exports client types.
    - The state file records:
      - the real SDK function name and the generated type names;
      - any regenerated `src/client/*` file that changed for reasons other than this route (kept as generated). An unrelated **signature** change means stop and report.
  - Verify: `cd /home/user/repositories/factored-hackathon-2026-inferencia-aplicada/.claude/worktrees/interaction-analytics-pipeline/frontend && grep -q "AnalyticsSummary" src/client/types.gen.ts && ! grep -n "http://" src/client/client.gen.ts && docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/lib/api.ts && npm run -s typecheck"`
  - Files: `frontend/src/client/` (generated: `sdk.gen.ts`, `types.gen.ts`, any other file the generator rewrites), `frontend/src/lib/api.ts`

- [ ] T7: Analytics filters, simulated-data badge and footer, and the six headline tiles
  - Depends on: T6 (`AnalyticsQuery`, `AnalyticsSummary` and `AppliedFilters` types from `@/lib/api` / `@/client`), T3 (i18n keys, `format.ts`, `BlockFrame`)
  - Read exactly these: `frontend/src/components/staff/ConversationFilters.tsx` (native-control pattern); spec §"Decisions" D2, D6, D7, D11; this plan's Facts "Planned frontend names" (props, test ids, i18n keys)
  - Acceptance:
    - `AnalyticsFilters.tsx` exports `AnalyticsFilters({ value, applied, onChange })`, where `value: AnalyticsQuery`, `applied: AppliedFilters | undefined` and `onChange(next: AnalyticsQuery)`.
      - It renders native `date` inputs and `<select>`s with the filter test ids.
      - Language options are all/`es`/`pt`, with `lang.*` labels. Country options are all/MX/CO/AR, as raw codes. Source options are `all`/`real`/`mock`.
      - The inputs show `value`, falling back to `applied` (the server-resolved defaults).
    - `MockDataNotice.tsx` exports `MockBadge({ show })` (`analytics-mock-badge`, `staff.analytics.mock_badge`) and `MockFooter({ show })` (`analytics-mock-footer`, `staff.analytics.mock_footer`). Each renders nothing when `show` is false. The page passes `summary.includes_mock` (D6, D7).
    - `SummaryTiles.tsx` exports `SummaryTiles({ summary, isLoading, isError })`, inside one `BlockFrame` (empty when `tiles.interactions === 0`). It renders six tiles with test ids `analytics-tile-*`:
      - interactions: a count only (D2);
      - resolution, escalation and negative: `formatPercent` plus `formatRatio(num, den)`;
      - cost: `formatUsd(avg_usd)` plus the count;
      - messages: `formatAvg(avg)` plus the count.
    - No `toFixed` or `toLocaleString` on money outside `format.ts`.
    - The chown line from Facts has run if any container command wrote files.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/components/staff/analytics/AnalyticsFilters.tsx src/components/staff/analytics/MockDataNotice.tsx src/components/staff/analytics/SummaryTiles.tsx && (npm run -s typecheck > /tmp/tc-T7.txt 2>&1; ! grep -E 'src/components/staff/analytics/(AnalyticsFilters|MockDataNotice|SummaryTiles)' /tmp/tc-T7.txt)"`
  - Files: `frontend/src/components/staff/analytics/AnalyticsFilters.tsx`, `frontend/src/components/staff/analytics/MockDataNotice.tsx`, `frontend/src/components/staff/analytics/SummaryTiles.tsx`

- [ ] T8: Interactions-per-day, intents and escalations charts
  - Depends on: T1 (`src/components/ui/chart.tsx`, `--chart-*` variables), T6 (`AnalyticsSummary` types), T3 (i18n keys, `format.ts`, `BlockFrame`)
  - Read exactly these: `frontend/src/components/ui/chart.tsx` (`ChartContainer`, `ChartConfig`, tooltip and legend exports); spec §"Decisions" D1, D3, D11 and §"Contracts" `per_day`, `intents`, `escalations`; this plan's Facts "Chart colours", "Planned frontend names"
  - Acceptance:
    - Each component takes `{ summary, isLoading, isError }` and wraps its content in `BlockFrame` with test ids `analytics-chart-per-day`, `analytics-chart-intents` and `analytics-chart-escalations`.
    - `OutcomesPerDayChart.tsx`: a Recharts stacked `BarChart` over `per_day`, five series in D1 order, labels `staff.analytics.outcome.*`, colours from Facts via `ChartConfig` (`var(--chart-n)`). It is empty when every bucket is 0.
    - `IntentsChart.tsx`: a horizontal bar of `count` per intent (raw intent code), with each intent's resolution shown next to it as `formatPercent` plus `formatRatio`. It is empty when `intents` is empty.
    - `EscalationsChart.tsx`: bars by cause group (`staff.analytics.cause.*`; `null` → `escalations.unknown`) and by queue (`staff.queue.*`; `null` → `escalations.unknown`), plus the median time to claim (`formatSeconds`) with its count. It is empty when both lists are empty.
    - No hard-coded hex colours.
    - The chown line from Facts has run if any container command wrote files.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/components/staff/analytics/OutcomesPerDayChart.tsx src/components/staff/analytics/IntentsChart.tsx src/components/staff/analytics/EscalationsChart.tsx && (npm run -s typecheck > /tmp/tc-T8.txt 2>&1; ! grep -E 'src/components/staff/analytics/(OutcomesPerDayChart|IntentsChart|EscalationsChart)' /tmp/tc-T8.txt)"`
  - Files: `frontend/src/components/staff/analytics/OutcomesPerDayChart.tsx`, `frontend/src/components/staff/analytics/IntentsChart.tsx`, `frontend/src/components/staff/analytics/EscalationsChart.tsx`

- [ ] T9: Sentiment and cost charts, with the analytics-overhead figure
  - Depends on: T1 (`src/components/ui/chart.tsx`, `--chart-*` variables), T6 (`AnalyticsSummary` types), T3 (i18n keys, `format.ts`, `BlockFrame`)
  - Read exactly these: `frontend/src/components/ui/chart.tsx`; spec §"Decisions" D11, D12, D13 and §"Contracts" `sentiment`, `cost`; this plan's Facts "Chart colours", "Planned frontend names"
  - Acceptance:
    - Each component takes `{ summary, isLoading, isError }` inside `BlockFrame`, with test ids `analytics-chart-sentiment` and `analytics-chart-cost`.
    - `SentimentChart.tsx`: the negative/neutral/positive split with `scored`, and better/same/worse with its `scored`, labelled with `staff.analytics.sentiment.*`. It is empty when both `scored` are 0.
    - `CostChart.tsx`:
      - a stacked bar over `cost.per_day` (NLU, compose, handoff summary);
      - figures for `total_usd`, `per_resolved.usd` (with `resolved`), and `sentiment_overhead_usd` labelled `cost.sentiment_overhead`, shown apart from the totals (D12);
      - every amount goes through `formatUsd` (D13);
      - it is empty when `total_usd === 0` and the overhead is 0.
    - No hard-coded hex colours, and no `toFixed` on money outside `format.ts`.
    - The chown line from Facts has run if any container command wrote files.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/components/staff/analytics/SentimentChart.tsx src/components/staff/analytics/CostChart.tsx && (npm run -s typecheck > /tmp/tc-T9.txt 2>&1; ! grep -E 'src/components/staff/analytics/(SentimentChart|CostChart)' /tmp/tc-T9.txt)"`
  - Files: `frontend/src/components/staff/analytics/SentimentChart.tsx`, `frontend/src/components/staff/analytics/CostChart.tsx`

- [ ] T10: Recent interactions table, with real rows linking to the timeline
  - Depends on: T6 (`RecentInteraction` type), T3 (i18n keys, `format.ts`, `BlockFrame`)
  - Read exactly these: `frontend/src/components/staff/ConversationTable.tsx` (`Link` to `/staff/conversations/$conversationId`, date display); spec §"Decisions" D1, D3, D4, D15; this plan's Facts "Planned frontend names"
  - Acceptance:
    - `RecentInteractionsTable.tsx` exports `RecentInteractionsTable({ summary, isLoading, isError })` inside `BlockFrame` with test id `analytics-recent`. It is empty when `recent` is empty.
    - Columns, one `analytics-recent-row` per row (at most 50, server order):
      - ended at: `new Date(x).toLocaleString()`, the existing precedent;
      - end reason: `staff.analytics.end_reason.*`;
      - intents: joined raw codes;
      - outcome: `staff.analytics.outcome.*`;
      - sentiment: `staff.analytics.sentiment.*`, or `—`;
      - cost: `formatUsd`.
    - A `source === "real"` row has a `Link` (`analytics-recent-link`, text `table.open`) to `/staff/conversations/$conversationId`. A mock row renders no link and no anchor (D15, DD6).
    - The chown line from Facts has run if any container command wrote files.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npx biome ci src/components/staff/analytics/RecentInteractionsTable.tsx && (npm run -s typecheck > /tmp/tc-T10.txt 2>&1; ! grep -E 'src/components/staff/analytics/RecentInteractionsTable' /tmp/tc-T10.txt)"`
  - Files: `frontend/src/components/staff/analytics/RecentInteractionsTable.tsx`

- [ ] T11: `/staff/analytics` page, admin-only nav link and the Playwright test
  - Depends on:
    - T6 (`getAnalyticsSummary`, `AnalyticsQuery` in `@/lib/api`);
    - T7 (`AnalyticsFilters`, `MockBadge`, `MockFooter`, `SummaryTiles`);
    - T8 (`OutcomesPerDayChart`, `IntentsChart`, `EscalationsChart`);
    - T9 (`SentimentChart`, `CostChart`);
    - T10 (`RecentInteractionsTable`).
    - Real export names are in the state file.
  - Read exactly these: `frontend/src/routes/staff/index.tsx`; `frontend/e2e/mock-staff-api.ts`; `frontend/e2e/staff.es.spec.ts` (login flow and spec style)
  - Acceptance:
    - `src/routes/staff/analytics.tsx`, via `createFileRoute("/staff/analytics")`:
      - `beforeLoad`: `staffMe()` null → `redirect({ to: "/staff/login" })`; `role !== "admin"` → `redirect({ to: "/staff" })` (D14);
      - `validateSearch` returns an `AnalyticsQuery` (unknown values dropped);
      - one `useQuery({ queryKey: ["staff","analytics",search], queryFn: () => getAnalyticsSummary(search) })`;
      - it renders the title, `AnalyticsFilters` (`onChange` navigates with the new search), `MockBadge`, the tiles, the five charts, the table and `MockFooter`, passing `{ summary: data, isLoading, isError }`.
    - `src/routes/staff/index.tsx` renders `<Link to="/staff/analytics" data-testid="analytics-nav-link">` next to the conversations link **only** when the session role is `admin`. For example, return `{ staff: agent }` from the existing `beforeLoad` and read it with `Route.useRouteContext()`.
    - `e2e/mock-staff-api.ts`:
      - gains `role?: "agent" | "admin"` (default `"agent"`, so existing specs are unchanged);
      - gains a `GET **/api/v1/staff/analytics/summary` handler that answers `403 forbidden_role` for an agent, and otherwise returns the fixture for the request's `source` param.
    - `e2e/fixtures/analytics-summary.ts` exports a function `(source) => AnalyticsSummary-shaped object`. It may `import type` from `../src/client`. Under `all`/`mock` it has `includes_mock: true` and one real plus one mock recent row; under `real` it has `includes_mock: false` and only the real row. Every block is non-empty under `all`.
    - `e2e/analytics.es.spec.ts` (ES UI):
      - Admin path: log in as admin, click `analytics-nav-link`, and see all six tiles, all five charts and `analytics-recent-row`. Badge and footer are visible. The real row's `analytics-recent-link` opens `/staff/conversations/<id>` (the timeline mock answers). The mock row has no link. After switching `analytics-filter-source` to `real`, the badge and footer are gone.
      - Agent path: log in as an agent; there is no `analytics-nav-link`, and `goto("/staff/analytics")` ends on `/staff`.
    - `staff.es.spec.ts` and `traceability.es.spec.ts` still pass.
    - The chown line from Facts has run after the build.
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "(pkill -f 'vite preview' || true) && (ls ~/.cache/ms-playwright | grep -q chromium || npx playwright install --with-deps chromium) && npm run -s build && npx playwright test e2e/analytics.es.spec.ts e2e/staff.es.spec.ts e2e/traceability.es.spec.ts && npx biome ci src/routes/staff/analytics.tsx src/routes/staff/index.tsx e2e/analytics.es.spec.ts e2e/mock-staff-api.ts e2e/fixtures/analytics-summary.ts"`
  - Files: `frontend/src/routes/staff/analytics.tsx`, `frontend/src/routes/staff/index.tsx`, `frontend/e2e/mock-staff-api.ts`, `frontend/e2e/fixtures/analytics-summary.ts`, `frontend/e2e/analytics.es.spec.ts`

- [ ] T12: Live proof on the dev stack (SC5 frontend half, SC7)
  - Depends on: T4, T11 (everything built), and the dev stack up from this worktree with `ANALYTICS_MOCK_ENABLED` set (card 1)
  - Read exactly these: spec §"Success criteria" 5 and 7; this plan's Facts "Baseline" (dev DB counts, admin account) and "Frontend conventions" (container, chown, route tree)
  - Acceptance:
    - Full frontend checks in the container: `npm run lint` and `npm run typecheck` both exit 0 (SC5, frontend half). The verifier runs `make check`.
    - `curl -s localhost/api/v1/health` is OK. The served OpenAPI has `/api/v1/staff/analytics/summary`. An unauthenticated `curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/staff/analytics/summary` answers `401`.
    - `curl -s localhost/staff/analytics` serves the SPA. If the route tree is stale (blank route in the browser), run `docker restart latam-cs-frontend-1` once and re-check.
    - Data is in view: `docker exec latam-cs-postgres-1 psql -U postgres -d latam_app -Atc "select source, count(*) from analytics.interactions where ended_at <= now() and ended_at >= now() - interval '7 days' group by source"` shows mock rows (counts only).
    - **Human step** (the admin password lives only in the main checkout's `data/secrets/staff_credentials.csv`, which agents must not open), recorded in the state file as pending until the human confirms:
      - log in as `admin` at `/staff/login`, follow the Analytics link, and see seeded data, the badge and the footer;
      - switch to "Real only" and see the badge and footer disappear;
      - as an agent, there is no link, and `/staff/analytics` redirects to `/staff`.
    - The chown line from Facts has run, and `git status --short` shows no unexpected root-owned or untracked files (`dist/` and `routeTree.gen.ts` are git-ignored).
  - Verify: `docker exec -w /app latam-cs-frontend-1 sh -c "npm run -s lint && npm run -s typecheck" && curl -sf localhost/api/v1/health && curl -s localhost/api/v1/openapi.json | grep -q '/api/v1/staff/analytics/summary' && test "$(curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/staff/analytics/summary)" = 401`
  - Files: none edited (it may regenerate `frontend/src/routeTree.gen.ts`, which is git-ignored)

## Parallel waves

| Wave | Tasks | Runs alone? | Why these can build together |
|---|---|---|---|
| W1 | T1 | **alone** (adds a dependency, rewrites the lockfile, restarts the frontend container, installs chromium, builds) | Changes the shared environment that every frontend task runs in |
| W2 | T2, T3, T4 | | Three independent chains: backend query and tests (`backend/app/domains/analytics/dashboard.py`, `test_analytics_summary.py`), frontend i18n and helpers (`es.json`, `pt.json`, `format.ts`, `BlockFrame.tsx`), the doc (`04-contracts.md`). Disjoint files. None builds or restarts anything. |
| W3 | T5 | | Needs T2's module. Its only parallel candidate would be T6, which needs this route. |
| W4 | T6 | | Regenerates `src/client/*` against the live backend. Every UI block needs its types. |
| W5 | T7, T8, T9, T10 | | Four disjoint sets of new files under `components/staff/analytics/`. Each lints its own paths and filters typecheck to its own paths. None builds. |
| W6 | T11 | **alone** (the one full `npm run build` plus Playwright on port 4173) | Assembles every block, so it needs all of W5 |
| W7 | T12 | **alone** (may restart the frontend container; live checks against the shared stack) | Final proof on the running stack |
