# State: REQ-interaction-analytics-dashboard — Interaction analytics dashboard
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-interaction-analytics-dashboard (card 2 of 2, owner A) · spec `docs/specs/interaction-analytics-dashboard.md` · plan `docs/plans/interaction-analytics-dashboard.md`
Branch `feat/interaction-analytics-dashboard`, based on `feat/interaction-analytics-pipeline` @ 8ba859e. Worktree `.claude/worktrees/interaction-analytics-pipeline`.

## Conventions established for this card
- Repo facts: plan §"Facts checked against the repo" is binding; read the bullets your task names.
- The dev stack runs from this worktree (it has .env). Frontend lint/typecheck/npm run inside `latam-cs-frontend-1`; host node_modules is incomplete.
- Integration tests use the throwaway `it_db`, never the shared dev DB.
- `backend/.mypy_cache` is not git-ignored: never `git add -A`; nobody commits during tasks.
- The admin password lives in `data/secrets/` of the main checkout: agents never open it.
- Uncommitted card files from spec phase (requirement doc, card 1 spec, this spec) belong to this card's commit; leave them alone.

## Human decisions taken mid-card
- T6: nginx returns 502 on /api (backend healthy); regenerate the client from http://backend:8000/api/v1/openapi.json inside the frontend container; nobody restarts nginx without asking.
- T6 drift: regenerate the client from an APP_ENV=eval OpenAPI dump (test-idp route kept); the client diff must hold only analytics additions.
- After T11: nginx 502 -> T12 may run `docker restart latam-cs-nginx-1` (nginx only), then regenerate the client via http://nginx to restore the baseUrl literal. Tiles block gets its own title key (T7 fix; es/pt.json extended to T7).
- After gate (2026-10-02): one-viewport BI layout at >=1024px, 3x2 panel grid, KPI strip, AppShell header skipped on /staff/analytics, recent table scrolls inside its panel (D4 kept). Task R1.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a3d9a322 | recharts@3.8.0 via shadcn chart.tsx, --chart-1..5 brand vars, container npm ci, chromium installed |
| T2 | done | ad5e02db | dashboard.py (resolve_filters, get_summary, InvalidDateRange, AnalyticsTimeout, frozen models); Python oracle over 7 filter cases |
| T3 | done | a8809c97 | 63 staff.analytics.* keys ES+PT; format.ts (formatUsd, formatPercent, formatRatio, formatAvg, formatSeconds); BlockFrame({title,testId,isLoading,isError,isEmpty,children}) |
| T4 | done | a2a17569 | 04 §3 summary endpoint row added; README mock provenance row already present |
| T5 | done | a9178234 | GET /staff/analytics/summary (get_analytics_summary) in staff_admin.py; R13 admin-only + bite check both ways; test_summary_access |
| T6 | done | a375a9e5 | client regenerated from backend:8000; getAnalyticsSummary(AnalyticsQuery) + AnalyticsSummary/Rate/RecentInteraction from @/lib/api; sub-types from @/client |
| T7 | done | a2d122f2 | AnalyticsFilters({value,applied,onChange}), MockBadge/MockFooter({show}), SummaryTiles({summary,isLoading,isError}) |
| T8 | done | a19b4b7d | OutcomesPerDayChart, IntentsChart, EscalationsChart ({summary,isLoading,isError}) |
| T9 | done | ae258ca1 | SentimentChart, CostChart ({summary,isLoading,isError}); overhead apart |
| T10 | done | a67681f5 | RecentInteractionsTable({summary,isLoading,isError}); real rows link, mock rows none |
| T11 | done | a8bbb439 | /staff/analytics page + admin nav link; Playwright 4 passed (analytics.es x2, staff.es, traceability.es); build ok |
| T12 | done | aefc3143 | nginx restarted (502->200); lint+typecheck, health, OpenAPI route, 401 unauth, SPA 200, 758 mock + 16 real in 7d; human browser step pending |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — Recharts via shadcn chart, brand chart colours, Playwright chromium
Created: `frontend/src/components/ui/chart.tsx` (shadcn chart).
Changed: `frontend/package.json` (+`recharts ^3.8.0` only), `frontend/package-lock.json`, `frontend/src/index.css` (`--chart-1..5` in `:root`, brand mapping).
Facts the next tasks need: installed `recharts@3.8.0` (verified by `npm ls` after container restart). Chromium installed in the container (lost on container recreate). Existing `overrides` in package.json untouched.
Deviations: one biome-ignore (`noDangerouslySetInnerHtml`) on ChartStyle's prop. Also edited shadcn output so `biome ci` passes: organized imports, `key={index}` -> `key={key}` in tooltip/legend (noArrayIndexKey), dropped unused `index` param in legend map.
Verify: npm ls recharts && biome ci && typecheck && build -> exit 0; package.json diff adds only recharts.

### T4 — Analytics summary endpoint in 04 §3
Changed: `docs/solution-docs/04-contracts.md` (new row after `GET /staff/personas`, line 115).
Facts the next tasks need: README provenance row for `source = 'mock'` (team-generated synthetic) exists; README untouched.
Deviations: none.
Verify: grep staff/analytics/summary + grep mock README + `git diff --quiet README.md` → all pass.

### T3 — Analytics i18n keys, format helpers, block frame
Created: `frontend/src/components/staff/analytics/format.ts` (`formatUsd`, `formatPercent`, `formatRatio`, `formatAvg`, `formatSeconds`), `.../BlockFrame.tsx` (`BlockFrame({title,testId,isLoading,isError,isEmpty,children})`, named export).
Changed: `frontend/src/lib/i18n/es.json`, `pt.json` (all 63 `staff.analytics.*` keys from plan Facts, flat dotted keys appended at the end).
Facts the next tasks need: `formatPercent` takes a 0..1 rate; `formatSeconds` rounds to whole seconds. Import `useI18n`/`TKey` from `@/lib/i18n`; dynamic keys need `as TKey`.
Deviations: none.
Verify: biome ci (4 files) + typecheck grep → exit 0; chown run.

### T2 — Summary query module with fact-table oracle tests
Created: `backend/app/domains/analytics/dashboard.py`, `backend/tests/integration/test_analytics_summary.py`.
Facts the next tasks need: exports `resolve_filters(date_from, date_to, language, country, source) -> AppliedFilters`, `async get_summary(filters) -> AnalyticsSummary` (uses `app.core.db.get_engine`), `InvalidDateRange`, `AnalyticsTimeout`, `AppliedFilters`, `AnalyticsSummary` + nested frozen models (`Rate`, `Tiles`, `PerDay`, `IntentRow`, `Escalations`, `SentimentBlock`, `CostBlock`, `RecentInteraction`...). Filter types are Literals (`Language`, `Country`, `Source`). Source column of `recent` and per_day order follow the spec.
Deviations: oracle in the test recomputes blocks in Python from raw `analytics.*` rows (not a second SQL), so it shares no SQL with the module. pytest output is coloured in this shell: the Verify grep `^2 passed` needs `NO_COLOR=1`.
Verify: `pytest tests/integration/test_analytics_summary.py` -> 2 passed; range ok; ruff check/format and mypy clean.

### T5 — Admin-only analytics summary route, R13 amendment, access test
Changed: `backend/app/api/v1/staff_admin.py` (`get_analytics_summary`, `GET /staff/analytics/summary`; docstring), `backend/tests/unit/test_r13_routes.py` (`/staff/analytics` admin-only like personas), `backend/tests/integration/test_analytics_summary.py` (`it_admin` fixture, `_login`, `test_summary_access`).
Facts the next tasks need: route imports `app.domains.analytics.dashboard`; 422 `invalid_date_range`, 503 `analytics_timeout` as HTTPException details; OpenAPI operation is `get_analytics_summary` (T6 regenerates the client). Test imports helpers from `tests.integration.conftest`.
Bite check: (a) removing router `require_role("admin")` -> test_r13_routes fails ("/api/v1/staff/personas has no RoleGuard dependency"); (b) route-level `require_role("agent","admin")` -> fails with `/api/v1/staff/analytics/summary` in message. Both reverted; staff_admin.py diff is only route + docstring + imports.
Deviations: none.
Verify: full Verify chain rc=0 (r13 1 passed, summary 3 passed, greps clean, lint-imports 4 kept, ruff, mypy ok).

### T6 — Regenerate client, add getAnalyticsSummary
Changed: `frontend/src/client/{index.ts,sdk.gen.ts,types.gen.ts}` (generated), `frontend/src/lib/api.ts` (`AnalyticsQuery`, `getAnalyticsSummary(query)`, re-exports `AnalyticsSummary`, `Rate`, `RecentInteraction`).
Facts the next tasks need: SDK fn `getAnalyticsSummaryApiV1StaffAnalyticsSummaryGet`; types `AnalyticsSummary` (filters, includes_mock, tiles, per_day, intents, escalations, sentiment, cost, recent), `GetAnalyticsSummaryApiV1StaffAnalyticsSummaryGetData`; query keys date_from, date_to, language, country, source ('all'|'real'|'mock', default). Other sub-types (Tiles, PerDay, IntentRow, ...) are in `@/client` types.
Deviations: nginx returned 502 (stale upstream), so generated from `http://backend:8000/api/v1/openapi.json` (human decision, nginx untouched). Generated drift beyond analytics: the dev backend no longer serves `POST /test-idp/sessions`, so `createTestSessionApiV1TestIdpSessionsPost`, `TestIdPRequest` and its types vanished from the client (unused in src/e2e); `ClientOptions.baseUrl` literal is now `'http://backend:8000'` (type only, client.gen.ts has no `http://`). Kept as generated.
Verify: grep + no http:// + biome ci api.ts + typecheck -> rc=0.

### T10 — Recent interactions table
Created: `frontend/src/components/staff/analytics/RecentInteractionsTable.tsx` (`RecentInteractionsTable({ summary, isLoading, isError })`, `summary: AnalyticsSummary | undefined`; named export).
Facts the next tasks need: test ids `analytics-recent`, `analytics-recent-row`, `analytics-recent-link` (real rows only; mock rows render no link). Title key `staff.analytics.table.title`; end_reason/sentiment keys are cast `as TKey` (unknown codes would show the raw key).
Deviations: none. Added an untitled last column for the link.
Verify: biome ci + typecheck grep → rc=0; file owned by host user.

### T8 — Per-day, intents and escalations charts
Created: `frontend/src/components/staff/analytics/{OutcomesPerDayChart,IntentsChart,EscalationsChart}.tsx` (named exports, props `{summary, isLoading, isError}`, test ids `analytics-chart-per-day|intents|escalations`).
Facts the next tasks need: EscalationsChart also exposes inner test ids `analytics-escalations-by-cause`, `-by-queue`, `-median`. Intents resolution label is built in code as `count · Resolución 62.5% (5/8)`. `other` and `abstained` share `--chart-5`.
Deviations: none (biome `check --write` run on my 3 files only).
Verify: biome ci + typecheck grep on my files -> rc=0.

### T7 — Analytics filters, mock notices, summary tiles
Created: `frontend/src/components/staff/analytics/{AnalyticsFilters,MockDataNotice,SummaryTiles}.tsx`.
Facts the next tasks need: `AnalyticsFilters({value: AnalyticsQuery, applied: AppliedFilters|undefined, onChange})` (AppliedFilters from `@/client`; "all" language/country emit `undefined`, source always emitted); `MockBadge({show})`, `MockFooter({show})`; `SummaryTiles({summary,isLoading,isError})` (BlockFrame testId `analytics-tiles`, title `staff.analytics.title`). Tiles read `tiles.cost_per_interaction.{avg_usd,count}`, `tiles.messages_per_interaction.{avg,count}`.
Deviations: none (added aria-label on controls from filter.* keys; biome --write run on my 3 files only; chown run).
Verify: biome ci (3 files) + typecheck grep -> rc=0.

### T9 — Sentiment and cost charts
Created: `frontend/src/components/staff/analytics/SentimentChart.tsx` (`SentimentChart`), `.../CostChart.tsx` (`CostChart`), named exports, props `{summary, isLoading, isError}`.
Facts the next tasks need: test ids `analytics-chart-sentiment`, `analytics-chart-cost`; inner ids `analytics-cost-total`, `analytics-cost-per-resolved`, `analytics-cost-sentiment-overhead` (overhead sits apart under a border). Sentiment = two single-bar stacked splits; `scored` shown as `(n = N)` since no i18n key for "scored" exists.
Deviations: none (files stayed user-owned, no chown needed).
Verify: biome ci (2 files) + typecheck grep → rc=0.
T6 addendum: client regenerated again from an eval-mode OpenAPI dump (`APP_ENV=eval /app/.venv/bin/python` building `create_app().openapi()`, copied into the frontend container, file removed after). test-idp symbols are back; `git diff --stat -- frontend/src/client` is analytics additions only (index.ts, sdk.gen.ts, types.gen.ts). Only other change: `ClientOptions.baseUrl` literal is now `${string}://${string}` instead of `'http://nginx'` (generator derives the literal from a URL input host; a file input gives the generic type). Kept as generated. Verify rc=0.

### T11 — /staff/analytics page, admin nav link, Playwright test
Created: `frontend/src/routes/staff/analytics.tsx`, `frontend/e2e/analytics.es.spec.ts`, `frontend/e2e/fixtures/analytics-summary.ts` (`analyticsSummaryFixture(source)`, `REAL_CONVERSATION_ID`).
Changed: `frontend/src/routes/staff/index.tsx` (beforeLoad returns `{staff}`; admin-only `analytics-nav-link`), `frontend/e2e/mock-staff-api.ts` (`role` option, analytics summary handler, 403 `forbidden_role` for agent).
Facts the next tasks need: page title and tiles frame both use `staff.analytics.title`; the route tree is generated at build (routeTree.gen.ts, check git status for it).
Deviations: Verify's `pkill -f 'vite preview'` matches its own `sh -c` and kills the run silently; I ran it as `'vite[ ]preview'`, rest identical.
Verify: build ok; playwright 4 passed (analytics x2, staff, traceability); biome ci 5 files clean; chown run.

### T7 addendum — own title key for the tiles block
Changed: `SummaryTiles.tsx` title -> `staff.analytics.tiles.title`; added that key to `es.json` ("Resumen") and `pt.json` ("Resumo"). testId unchanged.
Verify: biome ci (3 files + both dictionaries) rc=0, typecheck rc=0, `playwright test e2e/analytics.es.spec.ts` -> 2 passed; chown run.

### T12 — Live proof on the dev stack
Changed: none committed (nginx restarted once; client regen attempted and reverted).
Facts: nginx restart fixed 502 (health 200). Regen via http://nginx dropped `createTestSessionApiV1TestIdpSessionsPost` (dev backend has no test-idp), so the prior client was restored; `ClientOptions.baseUrl` stays `${string}://${string}` (needs an eval-mode backend behind nginx to get `'http://nginx'` back).
Checks: lint+typecheck rc=0; health ok; openapi has analytics/summary; unauth 401; /staff/analytics 200 SPA; dev DB last 7d: mock 758, real 16; no root-owned files in frontend/.
Pending human: admin login check (Analytics link, seeded data, badge, footer; "Real only" hides badge and footer; agent has no link and /staff/analytics redirects to /staff).
Verify: block Verify chain all pass.

### R1 — One-viewport BI layout for /staff/analytics
Changed: `AppShell.tsx` (`ownsChrome`), `routes/staff/analytics.tsx` (header line, 12x2 grid), `components/staff/analytics/*` (BlockFrame className + Card sm; charts fill panels; SummaryTiles has no outer card and its own loading/error/empty line; table scrolls with sticky header; footer one line), `es.json`/`pt.json` (removed `tiles.title`), spec row D17.
Facts the next tasks need: IntentsChart label uses a custom `BarLabel` <text> (recharts LabelList wrapped long labels); Escalations cause axis uses `SingleLineTick`; backend rejects ranges over 90 days (422), so a 92-day URL shows "loading" forever. Playwright MCP writes screenshots on its own FS (inline only).
Deviations: none vs plan (intent label keeps the "Resolución" word, margin 190).
Verify: lint+typecheck rc=0; analytics.es.spec.ts 2 passed; live scrollHeight == innerHeight at 1920x1080/1366x768/1280x720 (all, 30d, real), 800px no horizontal overflow.
