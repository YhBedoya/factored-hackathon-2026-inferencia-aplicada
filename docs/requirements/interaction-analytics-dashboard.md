# Requirement: interaction analytics dashboard

Status: **draft for review** · Date: 2026-10-01 · Owner: to be set at spec time · Architecture: ADR-033.

This document is the input for `/wave-run`. The `spec-writer` turns it into `docs/specs/<slug>.md`. The open questions at the end are answered at that stage. It fixes what is built, why, and how "done" is judged. It does not fix implementation details.

It is card 2 of 2. Card 1 is [`interaction-analytics-pipeline.md`](interaction-analytics-pipeline.md), which creates and fills the tables this card reads. The table schema in that document's R2 is the contract between the two cards.

## Why

The pipeline card stores one row of metrics per finished interaction with Cardy. This card shows them: one page where an admin sees volume, resolution, escalation, cost, sentiment and intents, filtered by date, language and country. Judges reach it on the public deployment through the staff login.

## Current state

- The staff console is a React app under `/staff` (`frontend/src/routes/staff/`): handoff inbox, conversation list and per-turn timeline (ADR-024).
- Staff routes are protected at the router: `staff.py` allows `agent` and `admin`; `staff_admin.py` allows `admin` only. Both add the CSRF check (R13, ADR-025).
- The frontend has shadcn, Tailwind and TanStack Query and Router. It has no chart library.
- Grafana exists but stays private (reachable only through SSM port forwarding), so it is not where judges look.
- The fact tables hold real rows and mock rows, told apart by `source` (pipeline card R5).

## What is built

### R1 · Endpoint

1. `GET /api/v1/staff/analytics/summary`, admin only, following the `staff_admin.py` pattern (`require_role("admin")` and `require_csrf` at the router).
2. Query parameters: date range (default the last 7 days), `language`, `country`, and `source` (`all`, `real`, `mock`; default `all`).
3. One response carries every block the page needs, so the page loads in one request.
4. It reads only the `analytics` schema, with a statement timeout, so a slow query cannot hold up the chat.
5. It counts only rows whose `ended_at` has passed. Mock rows for later today exist in the table and must not appear early.
6. Days are bucketed in the analytics time zone setting (default `America/Bogota`).
7. Every rate comes with the count behind it.

### R2 · Page

A new route `/staff/analytics`, visible in the staff navigation to admins only. Charts use Recharts through shadcn's chart component. Colours, type and tone follow [`docs/brand.md`](../brand.md).

**Filters:** date range, language, country, and the data source switch (R3). They apply to everything below.

**Headline tiles**

| Tile | Shows |
|---|---|
| Interactions | finished interactions, with active ones as a secondary number |
| Resolution rate | share of interactions with `resolved = true`, over those with at least one real intent |
| Escalation rate | share of interactions with a handoff |
| Cost per interaction | average `cost_usd` |
| Messages per interaction | average total messages |
| Negative sentiment | share of interactions with `sentiment_overall = negative` |

**Charts**

| Chart | Shows |
|---|---|
| Interactions per day | stacked by how they ended: resolved, escalated, abandoned, abstained |
| Intents | volume per intent, with its resolution rate alongside |
| Escalations | count by cause group (by design, customer choice, bot failure, security) and by queue; median time to claim |
| Sentiment | negative, neutral and positive split; how many interactions ended better, the same or worse than they started |
| Cost | cost per day by step (NLU, compose, handoff summary); cost per resolved interaction |

**Table:** recent interactions with end time, end reason, intents, outcome, sentiment and cost. A real row links to the existing conversation timeline. A mock row has no link.

Other rules:

- The cost of sentiment scoring is shown separately. It is analytics overhead, not part of an interaction's cost.
- Money is formatted in code, as everywhere else.
- Loading, empty and error states exist for every block.

### R3 · Real and simulated data

1. When the current view includes mock rows, the page shows a visible badge: "Includes simulated traffic" (final wording at spec time).
2. A switch chooses All, Real only or Simulated only. The default is All.
3. The README's data provenance table lists the mock analytics rows as team-generated synthetic data (B2).

## Done when

1. An `agent` session gets `403` on the endpoint and does not see the page in the navigation; an `admin` session gets the data. The route is covered by the R13 route test.
2. With seeded rows, every tile, chart and the table renders, and the numbers match a direct query of the fact tables for the same filters.
3. Changing the date range, language, country or source changes every block.
4. The badge is visible whenever mock rows are in view, and absent with "Real only".
5. A mock row whose `ended_at` is in the future is not counted.
6. A real row opens its conversation timeline; a mock row offers no link.
7. `npm run lint` and `npm run typecheck` pass (run in the frontend container), and `make check` passes.

Tests stay minimal (CLAUDE.md): the lines above and R13.

## Out of scope

- Computing or storing metrics (card 1).
- Click-to-filter from a chart.
- Access for agents, or a view with cost hidden.
- Exports, scheduled reports and alerts.
- A Grafana, Superset or Metabase dashboard.

## Open questions

- **Q1 · Staff console language.** Does the page follow the ES | PT toggle (ADR-022), and are its labels added to both dictionaries?
- **Q2 · Active interactions.** The fact tables hold finished interactions only. Does the "active" number come from a live count of `app.conversations`, or is it dropped?
- **Q3 · Table size.** How many recent interactions the table shows, and whether it pages.
- **Q4 · Badge wording** in Spanish and Portuguese.
- **Q5 · Owner.** Which developer takes this card.
- **Q6 · Cancelled intents.** The pipeline spec adds the intent outcome `cancelled` (the customer declined a write at the confirmation) and removes `clarified`. An interaction whose only shortfall is a `cancelled` intent has `resolved = false` and is not escalated, abandoned or abstained, so it falls in none of the four per-day stacks. Where does it go?
- **Q7 · Bot-offered intents.** The pipeline spec (D22) adds the column `bot_offered` to `analytics.interaction_intents`: true when the bot offered the intent (the replacement offer after a permanent block) and the customer did not ask for it. A bot-offered intent that the customer declined is already left out of `resolved` and `real_intent_count`, so the resolution rate needs no change here. Do bot-offered rows count in the intents chart and its per-intent resolution rate?
