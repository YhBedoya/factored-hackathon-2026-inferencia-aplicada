# Spec: REQ-interaction-analytics-dashboard — admin analytics endpoint and page

Card source: `docs/requirements/interaction-analytics-dashboard.md` (not a `07` row; card 2 of 2) · architecture: ADR-033 (Accepted) · owner **Dev A** (human) · branch `feat/interaction-analytics-dashboard`, stacked on `feat/interaction-analytics-pipeline` @ 8ba859e · spec date 2026-10-02.

Naming: the requirement doc's items are **REQ-R1..REQ-R3**, its open questions **REQ-Q1..REQ-Q7**, its acceptance lines **DD1..DD7** (in the order of its "Done when"). Bare **R1–R13** always means the safety rules in `06` §1. **A1..A9** are the pass-1 assumptions, shown to the human and not corrected. **H1..H6** are the human's answers to the pass-1 questions. Card 1's decisions are cited as **P-D*n*** (`docs/specs/interaction-analytics-pipeline.md`).

## Objective

Give admins one page, `/staff/analytics`, that shows volume, resolution, escalation, cost, sentiment and intents over the `analytics` fact tables card 1 fills. The page has date, language, country and data-source filters, a "simulated data" badge, and a list of recent interactions that links to the existing conversation timeline. The page is fed by one admin-only endpoint, `GET /api/v1/staff/analytics/summary`, which reads only the `analytics` schema. The card delivers REQ-R1..REQ-R3, as amended by the decisions below, and serves DD1..DD7. It does not compute or store any metric (card 1), and it does not change any of card 1's files.

The requirement's tile, chart and table lists are binding as written unless a `D` below changes them.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Per-day stacks are exclusive buckets, taken in order:** `escalated` (`escalated = true`) → `resolved` (`resolved = true`) → `abandoned` (`abandoned = true`) → `abstained` (`abstained = true`) → **`other`** (everything else: cancelled-only, closed mid-flow, no real intent). The five stacks add up to the Interactions tile for the same filters. The recent-interactions table's "outcome" column uses the same bucket | H1(a); closes REQ-Q6 (and the wider overlap found in pass 1); card 1 OQ1 |
| D2 | **No "active" number.** The Interactions tile shows finished interactions only, and REQ-R2's "with active ones as a secondary number" is dropped. The endpoint keeps reading only `analytics` | H2(a); ADR-033 "The dashboard reads only this schema"; REQ-R1.4; closes REQ-Q2 |
| D3 | **Intents chart uses the D22 rule.** `interaction_intents` rows with `bot_offered = true AND outcome = 'cancelled'` are left out of volume and of the per-intent resolution rate. Every other row counts, bot-offered or not. The table's intent list for a row applies the same rule | H3(a); P-D22; closes REQ-Q7 and card 1 OQ3 |
| D4 | **Recent interactions: the 50 most recent rows in view**, `ended_at` descending, returned inside the summary response. No paging, no second endpoint | H4(a); REQ-R1.3; closes REQ-Q3 |
| D5 | **Owner is Dev A** | H5(b); closes REQ-Q5 |
| D6 | **Badge wording:** ES "Incluye datos simulados", PT "Inclui dados simulados". It shows exactly when `includes_mock` is true (REQ-R3.1, DD4) | H6(b); closes REQ-Q4 |
| D7 | **Footer note.** ES text from the human, with only the accent fixed: "Este tablero se alimenta de datos simulados para demostrar su funcionalidad en ambientes productivos con tráfico real". PT translation, accepted by the human: "Este painel é alimentado por dados simulados para demonstrar sua funcionalidade em ambientes de produção com tráfego real". **It shows only when `includes_mock` is true**, the same rule as the badge (D6), so it is hidden under "Real only" | H6 (human addition); FQ1(a), FQ2 (human) |
| D8 | **Staff console language.** The page follows the ES \| PT toggle (ADR-022). Every label goes into both `es.json` and `pt.json` (`TKey = keyof typeof es` makes a key missing from `pt` a type error). Existing `staff.queue.*` keys are reused<br>**Amended (human, mid-card):** the tiles block has its own title key, `staff.analytics.tiles.title` ("Resumen" / "Resumo"), so the page title is not shown twice | A1; closes REQ-Q1; human mid-card |
| D9 | **Endpoint placement.** The route lives in `staff_admin.py` (router-level `require_role("admin")` + `require_csrf`), so an agent gets `403 forbidden_role`. Query code and response models live in `app.domains.analytics`, which imports no `conversation` module. `test_r13_routes.py` treats `/api/v1/staff/analytics` as admin only, next to `/staff/personas` | A2; REQ-R1.1; R13; ADR-025; P-D12 |
| D10 | **Query rules.** One read transaction on the app's existing engine with `SET LOCAL statement_timeout = '5s'`. A timeout returns `503 analytics_timeout`. Every block filters `ended_at <= now()`. Days are `(ended_at AT TIME ZONE ANALYTICS_TIMEZONE)::date`. `date_from` and `date_to` are inclusive local dates and default to the 7 days ending today. `date_from > date_to`, a range over 92 days, or an unknown filter value returns `422`<br>**Verified (mid-card):** `422` on a reversed range, on a range over 92 days and on an unknown filter value; `503 analytics_timeout` after the 5 s statement timeout. The timeout was shown by a probe; no committed test covers it | A3; REQ-R1.2, R1.4–R1.6; parameter names follow `GET /staff/conversations` in `04` §3; card verification |
| D11 | **Metric readings.** Resolution rate = `resolved = true` / `resolved IS NOT NULL`. Escalation rate = `escalated` / all rows. Messages = `customer_messages + bot_messages + agent_messages`. Negative share = `negative` / `sentiment_overall IS NOT NULL`. Better / same / worse compares `sentiment_start` with `sentiment_end` on the order negative < neutral < positive, over rows where both are set. Cost per resolved interaction = `sum(cost_usd)` / resolved count. Median time to claim = `percentile_cont(0.5)` over non-null `time_to_claim_s`. Every rate is null when its denominator is 0, and comes with its numerator and denominator (REQ-R1.7) | A4; REQ-R1.7, REQ-R2 tiles |
| D12 | **Sentiment cost is a separate "analytics overhead" figure** (`sum(sentiment_cost_usd)`) in the cost block. It is never added to any per-interaction cost | A4; REQ-R2 "Other rules"; P-D13 |
| D13 | **Money.** The API returns numbers. The frontend formats every amount with one code helper (the `TurnTimeline.tsx::formatUsd` precedent). No amount passes through an LLM | A5; REQ-R2; `06` §1 |
| D14 | **Navigation.** An "Analytics" link next to the existing conversations link on the inbox page, rendered only when `staffMe().role === "admin"`. The `/staff/analytics` route's `beforeLoad` sends a non-admin to `/staff` and a missing session to `/staff/login` | A6; REQ-R2; DD1 |
| D15 | **Charts** use Recharts through shadcn's `chart` component. Colours come from the `brand.md` tokens as CSS variables. The generated API client is regenerated with `openapi-ts`. A `source = 'real'` row links to `/staff/conversations/$conversationId`; a mock row renders no link<br>**Amended (human, mid-card):** the client is regenerated from an OpenAPI dump taken with `APP_ENV=eval`, so the eval-only test-idp route stays in it; the client diff holds only analytics additions. Known leftover, type-only: `ClientOptions.baseUrl` is typed as the literal `${string}://${string}` | A7; REQ-R2; DD6; human mid-card |
| D16 | **Card 1 is not touched.** `mock_profile.yaml` keeps 0% `cancelled` (P-D15), and the worker and migration `0009` are unchanged. REQ-R3.3 (README provenance row) is already met by card 1 and only gets checked here | H1(a); A9; README "Provenance of the analytics rows" |

## Contracts

Only the delta. Error envelope and auth: `04` §3 "Auth (ADR-025)". Table columns: card 1 REQ-R2 + P-D28.

**Endpoint** (new row in `04` §3):

`GET /api/v1/staff/analytics/summary?date_from=&date_to=&language=&country=&source=` · admin · `AnalyticsSummary`

| Param | Values | Default |
|---|---|---|
| `date_from`, `date_to` | ISO dates, local to `ANALYTICS_TIMEZONE`, inclusive | today − 6 … today |
| `language` | `es`, `pt` | absent = all |
| `country` | `MX`, `CO`, `AR` | absent = all |
| `source` | `all`, `real`, `mock` | `all` |

Errors: `403 forbidden_role` (agent), `401 session_expired`, `422` (D10), `503 analytics_timeout`.

**Response** (`app/domains/analytics/dashboard.py` or similar, frozen pydantic models). `Rate = {rate: float | null, num: int, den: int}`. Money is a `float` in USD.

```
AnalyticsSummary {
  filters:      {date_from, date_to, language, country, source, timezone}
  includes_mock: bool                      # any source='mock' row in view (D6)
  tiles: {
    interactions:              int          # finished only (D2)
    resolution:                Rate         # D11
    escalation:                Rate
    cost_per_interaction:      {avg_usd: float | null, total_usd: float, count: int}
    messages_per_interaction:  {avg: float | null, count: int}
    negative_sentiment:        Rate
  }
  per_day:     [{day: date, escalated, resolved, abandoned, abstained, other: int}]   # D1; every day in range, zeros included
  intents:     [{intent: str, count: int, resolution: Rate}]                          # D3; count desc
  escalations: {by_cause_group: [{group: str | null, count}], by_queue: [{queue: str | null, count}],
                time_to_claim_median_s: float | null, time_to_claim_count: int}
  sentiment:   {overall: {negative, neutral, positive, scored: int},
                trajectory: {better, same, worse, scored: int}}
  cost:        {per_day: [{day: date, nlu_usd, compose_usd, handoff_summary_usd: float}],
                total_usd: float, per_resolved: {usd: float | null, resolved: int},
                sentiment_overhead_usd: float}                                        # D12
  recent:      [RecentInteraction]                                                    # D4, max 50
}
RecentInteraction {conversation_id: UUID, source: "real" | "mock", ended_at: datetime,
                   end_reason: str, intents: [str] (by seq, D3), outcome: D1 bucket,
                   sentiment_overall: str | null, cost_usd: float}
```

`by_cause_group` and `by_queue` count escalated rows by the first handoff's `handoff_cause_group` / `handoff_queue` (card 1 REQ-R3). A null value is returned as `null`.

**Frontend:** route file `frontend/src/routes/staff/analytics.tsx`. i18n keys under `staff.analytics.*` in both dictionaries (D8).

**Footer (D7):** text fixed; rendered only when `includes_mock` is true (no extra response field).

**Docs this card edits when it builds:** `04` §3 (endpoint row above). ADR-033 needs no change (D2 keeps "reads only this schema").

**Docs amended together with this spec:** the dashboard requirement's open questions are marked answered. Card 1 spec OQ1 and OQ3 are marked closed by this spec.

## Touch map

| Path | Change |
|---|---|
| `backend/app/domains/analytics/dashboard.py` (new) | summary query (one transaction, timeout) and response models |
| `backend/app/api/v1/staff_admin.py` | `GET /staff/analytics/summary` |
| `backend/tests/unit/test_r13_routes.py` | admin-only branch includes `/api/v1/staff/analytics` |
| `backend/tests/integration/test_analytics_summary.py` (new) | tests below |
| `frontend/package.json`, `frontend/src/components/ui/chart.tsx` (shadcn add) | Recharts + shadcn chart |
| `frontend/src/client/*` (regenerated), `frontend/src/lib/api.ts` | `getAnalyticsSummary` |
| `frontend/src/routes/staff/analytics.tsx` (new), `frontend/src/routes/staff/index.tsx` (admin link), `frontend/src/routeTree.gen.ts` | page, nav (D14) |
| `frontend/src/components/staff/analytics/` (new) | filters, tiles, charts, table, badge, footer |
| `frontend/src/lib/i18n/es.json`, `pt.json` | `staff.analytics.*` |
| `frontend/e2e/analytics.es.spec.ts` (new), `frontend/e2e/mock-staff-api.ts` | admin persona + summary fixture |
| `docs/solution-docs/04-contracts.md` §3 | endpoint row |

## Test list

Fake LLM is irrelevant here (no LLM call). No tests for schemas, i18n parity (typecheck covers it) or chart internals.

| Test | Proves |
|---|---|
| `test_r13_routes.py` (amended) | DD1 / R13: every `/api/v1/staff/analytics...` route declares `require_role("admin")` only |
| `test_summary_access` (integration) | DD1: an agent session gets `403 forbidden_role`; an admin session gets `200` |
| `test_summary_matches_fact_tables` (integration) | DD2, DD3: with seeded real and mock rows, every block equals a direct SQL query over `analytics.*` for the default filters and for one changed value of each filter (date range, language, country, source). The per-day stacks add up to `tiles.interactions` (D1). Bot-offered cancelled rows are left out of `intents` (D3) |
| `test_summary_future_and_mock` (integration) | DD5, DD4 (API side): a mock row with `ended_at` in the future is in no block; `includes_mock` is true under `all` and false under `real` |
| `analytics.es.spec.ts` (Playwright, mocked staff API) | DD2 (render), DD4, DD6, DD1 (nav): an admin sees every tile, chart and the table; the badge shows, and disappears after switching to "Real only"; a real row opens its timeline; a mock row has no link; an agent session has no Analytics link; the footer note shows with the badge and is gone under "Real only" (D7) |

No PT happy path: this is not a conversation flow, and PT labels are covered by typecheck (D8).

## Boundaries

**Always**
- Read only the `analytics` schema in the endpoint, under the statement timeout.
- Apply `ended_at <= now()` and the filters to every block, including `includes_mock`.
- Format money in code, with one helper.

**Ask first**
- Any change to card 1's files (`mock_profile.yaml`, the worker, migration `0009`) or to the fact-table columns.
- A second analytics endpoint, or paging.
- Any new dependency beyond Recharts and the shadcn chart component.

**Never**
- Query `app.*`, `audit.*` or `bank.*` from the endpoint.
- Expose the page or the endpoint to `agent`, or add a cost-hidden view.
- Add exports, alerts, click-to-filter, or a Grafana/Superset/Metabase dashboard (REQ "Out of scope").
- Touch `eval/scenarios/heldout/`, or commit `.env` or `data/`.

## Success criteria

1. `cd backend && uv run pytest tests/unit/test_r13_routes.py tests/integration/test_analytics_summary.py -k access -q` passes, and removing `require_role("admin")` from the route makes the R13 test fail (DD1).
2. `uv run pytest tests/integration/test_analytics_summary.py -k matches_fact_tables` passes (DD2, DD3).
3. `uv run pytest tests/integration/test_analytics_summary.py -k future_and_mock` passes (DD4 API side, DD5).
4. `cd frontend && npx playwright test e2e/analytics.es.spec.ts` passes (DD1 nav, DD2 render, DD4, DD6).
5. In the frontend container, `npm run lint` and `npm run typecheck` pass. `make check` passes (DD7).
6. `04` §3 has the `GET /staff/analytics/summary` row, and the README provenance table still lists `source = 'mock'` rows as team-generated synthetic (REQ-R3.3).
7. With `make up` and mock seeding on, an admin opening `/staff/analytics` sees seeded data, the badge, and the footer note; switching to "Real only" hides both. An agent does not see the link, and gets redirected away from the URL.

## Open questions

| # | Question | Who decides |
|---|---|---|
| FQ1 | *Closed by D7*: the footer note shows only when mock rows are in view | Answered by the human |
| FQ2 | *Closed by D7*: PT footer translation accepted as written | Answered by the human |
