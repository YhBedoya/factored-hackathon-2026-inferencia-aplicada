# Spec: D7-B — Transactions, priority flags, traceability screens, LLM judge

Card D7-B (Dev B, G14) · `07` lines 291-318, rows B1-B4 · branch `feat/d7-b-transactions-traceability-judge` (base `develop`).

## Objective

This card has four parts:

- **B1: transaction search and the pending/reversal explainer.** It ships the `tx_search` and `tx_explain` flows (`02` §4.4, §4.5), which today fall through to `unsupported`. Dates are resolved in code, merchants are fuzzy-matched against the 24 known names, the amount window is ±10%, the search looks back at most 12 months and widens once. The result list is single-pick: a Pending or Reversed row is explained from `policies/transaction_states.yaml`, and an Approved row gets its decoded details.
- **B2: claim priority flags.** On `unrecognized_charge`, three flags are checked before the claim plan is issued: repeat complainer, amount above the threshold, and an open Critical complaint. If one hits, the claim is still created and verified, and then handed off to Reclamos.
- **B3: traceability screens.** The staff console gets a conversation list with filters and a per-turn "why" timeline. The screens are built against the `04` §3 shapes this spec proposes, with mocked API responses, and are wired to A1's real API once it lands.
- **B4: LLM judge.** A rubric, an eval-only `judge` step, about 50 human labels, and an agreement report with κ.

It serves these "Done when" lines:
- B1: "el cargo de Super Ahorro del martes pasado por unos 350" finds it. **Amended mid-card (AM1):** the live proof uses "el cargo de Super Ahorro del jueves pasado por unos 790 mil" for persona `CLI-M9B56QX9KMBU`.
- B2: an ES/PT test per flag.
- B3: the end-of-day test.
- B4: the agreement report exists, and if κ < 0.6 the judge is reported as weak.

It also serves end-of-day test steps 1-3. Step 4 is A2's.

## Assumptions (accepted with the human answers)

- **A1: search needs a criterion.** `transaction_search` needs at least one of merchant, amount, or a date expression code can resolve. With none, the flow asks one question and runs no search. Dev scenario `d-transaction_search-ambiguous-pt-br-01` expects `clarified` and forbids `transactions.search`.
- **A2: search filters.**
  - The search covers all the customer's cards. A `card_hint` narrows it to one card.
  - The window never starts more than 12 months before the bank clock's today. With no date, it is the last 12 months.
  - A missing currency means the card's record currency.
  - With zero results, the dates widen once by ±3 days (`02` §4.4). A second zero ends with "nothing found" plus the filters used. That outcome is `resolved`.
- **A3: date resolver.** It is plain code in ES and PT, run in the customer's `BANK_TZ`. It handles:
  - hoy/hoje, ayer/ontem, anteayer/anteontem;
  - "el <día> pasado" / "<dia> passada", which means the most recent such weekday strictly before today;
  - semana pasada/semana passada and mes pasado/mês passado;
  - "hace N días" / "há N dias";
  - "<d> de <mes>", meaning the most recent such date on or before today.

  Anything else is unresolvable, and the date is ignored.
- **A4: merchant match.** The 24 merchant names are a code constant in `app/domains/transactions/` (`01` §10). Matching folds case and accents and uses a fuzzy ratio. It never calls the LLM.
- **A5: explainer policy.** `policies/transaction_states.yaml` holds a synthetic `pending_hold_days: 3`.
  - A Pending row gets "expected to clear by <date>", where the date is `occurred_at` plus the hold days, formatted in code.
  - If that date has already passed, the reply says the charge is past the usual window and offers a human (Atención) as a quick reply.
  - The data has no twin row for a Reversed charge (0 twins in 2,000 sampled). So the reversal explanation describes the single row and never claims a second line exists.
- **A6: flag definitions.**
  - Repeat complainer: any `bank.complaints` row for the customer has `is_repeat_complainer = true`. This is the same definition as `eval/personas.yaml`.
  - Amount threshold: per currency, on the picked transaction's record `amount`. The values are USD 5,000, COP 20,000,000 and ARS 1,800,000, about p90 of transaction amounts.
- **A7: handoff reason.** A new reason `priority_claim` routes `{queue: reclamos, priority: high}` in `escalation.yaml`. A flagged claim row gets `priority='High'` instead of NULL, which amends D4-B D14. A reviews this, because it is A's file and a safety-critical path (ADR-018).
- **A8: judge input.**
  - The judge reads only dev-suite run outputs. Held-out outputs are never labeled or opened (R9).
  - Before a transcript reaches the judge, it is masked with the persona's known PII and put inside data fences. This follows R5, R6 and the simulator note in ADR-030.
- **A9: judge files.** The rubric is `eval/judges/rubric.md`, the labels are `eval/judges/labels/*.yaml`, and the report is `eval/judges/agreement.md`. Putting judge scores into the held-out report is A2's call.
- **A10: screens.** They are staff routes for the agent and admin roles, run in Playwright on `mock-staff-api.ts`, and never show chain-of-thought (ADR-024).
- **A11: dev scenarios.** There is one dev scenario per new behavior (`06` §7). Every test uses the fake LLM.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **`tx_search` flow.** `transaction_search` → `tx_search` in `_INTENT_NODES` and `_FLOW_NODES`. Code builds a `TxFilter` from the NLU slots (A1-A4) and calls `transactions.search`. It never runs `card_select`; a hint only narrows `card_id`. One or more rows → a single-pick `ui.transaction_list` (`multi: false`) plus a count fact, pausing at `awaiting_slot = "transactions"`. Zero rows → widen once, then give the no-results reply | `02` §4.4, `07` B1, human Q6(a). Reuses the `transactions` pause and `_entry`'s generic step 0, as `decline_explain` does (D5-B D2/D3), so entry routing doesn't change |
| D2 | **Picking a search row.** A Pending or Reversed row → the `tx_explain` logic for that row. An Approved row, or any other status → decoded details from `TxView` (merchant, category, channel, city, date, amount), formatted in code. Two new clarifications are not added: an ambiguous search just shows the list | Human Q6(a); R4 |
| D3 | **`tx_explain` flow.** `pending_reversal_explain` → `tx_explain`. Code searches with the same slot filter (D1), restricted to `status in [Pending, Reversed]`. One match → explain it. Two or more → single-pick list, then explain the pick. Zero with a slot → offer every Pending or Reversed row from the last 12 months. None at all → a fixed "nothing pending or reversed" reply. The cause, next step and hold days come only from `transaction_states.yaml`; the LLM phrases the reply | `02` §4.5, `07` B1, A5. The "zero matches → offer all" pattern follows D5-B D2 |
| D4 | **`policies/transaction_states.yaml`** v1, with the `provenance` header, loaded and validated by `policy/registry.py`. Its contents are shown under Contracts | `04` §5 "Other files", R8, ADR-012 |
| D5 | **Priority flags are checked in code before the claim plan is issued**, both the single-charge and compromise plans, through a `disputes.service` read that gives `repeat_complainer` and `open_critical`, plus a threshold check on the picked amounts. The flow never asks the LLM for them | Human Q2(a), Q3(a); R8 |
| D6 | **Flag outcome on the single-charge path.** The claim runs through the normal C → `create_claim` → V path. After a verified read-back, the flow sets `escalation_reason = "priority_claim"` and `handoff_queue = "reclamos"`, and the graph goes `handoff_summary → handoff`. If the claim is unverified, it goes through the existing `action_unverified` handoff | Human Q2(a); `02` §4.8 step 4; R3 |
| D7 | **Flag outcome on the compromise path.** Fraudes wins. The handoff stays `suspected_fraud` → `fraudes`. `priority_claim` is added to `escalation_rules_hit`, and the flag names are rendered in code into `handoff_open_questions` | Human Q2(a) |
| D8 | **A regulator mention is unchanged.** The existing `legal_regulator` rule in `route` hands off to Reclamos (high) at once, with no claim. B2's regulator test asserts that routing when the mention comes during a paused `unrecognized_charge` | Human Q2(a) |
| D9 | **"Open Critical"** means a `bank.complaints` row for the customer with `priority = 'Critical'` and `status in disputes.yaml priority.open_statuses`, which is `[Open, In Process, Escalated]`. The data statuses are Open, In Process, Escalated, Resolved, Closed and Rejected; "open" is read as not Resolved, not Closed and not Rejected | Human Q3(a). The status list is this spec's reading of "open" (Open questions 1) |
| D10 | **Flagged claim rows** get `priority = 'High'`, which amends D4-B D14's NULL. Unflagged rows stay NULL. `ActionResult` gains no `priority_flags` field; the flags travel in graph state and the signed plan args (`create_claim.priority_flags`) | A7; R12 (the `origin='app'` append is unchanged) |
| D11 | **Timeline contract (proposed, `04` §3).** This spec adds `ConversationListItem`, `ConversationFilters` and `TurnTimeline` (see Contracts) to `04` §3, marked **(proposed)**. `GET /staff/conversations` and `GET /staff/conversations/{id}/timeline` are **exempt from `get_claimed_conversation`**: they check the agent or admin role only and show only masked data. A adopts or amends the shapes in A1 | Human Q1(a); ADR-024; `01` §8 field list; `07` A1 row |
| D12 | **B3 builds against the proposed shapes** with a hand-written `frontend/src/lib/traceability.ts` type and `e2e/mock-staff-api.ts` fixtures. Once A1 merges, it moves to the generated client (`06` §4) and the hand type is deleted | Human decision before Pass 1 |
| D13 | **Screens.** `/staff/conversations` is a table with filters for language, country, intent, outcome, escalation and date range, held in URL search params, with a row link. `/staff/conversations/$conversationId` shows the turns in order. Each turn expands to "why": NLU result, rules hit, tools with their results, sources, policy hash, model and prompt version per step, latency, cost, and the Langfuse link (hidden when null). There is no chain-of-thought and no raw PII: the payloads are the masked audit payloads | `07` B3, ADR-024, `01` §8; R5 |
| D14 | **Judge model.** A new eval-only step, `judge`, on the `openai` provider with `gpt-6-luna` and prompt `judge@v1`. Temperature is 1.0, the only value the model accepts; the report carries a non-repeatable caveat. It is called only through `get_llm_client()` and never runs in the served graph | Human Q4(a); ADR-030 pattern; R7 |
| D15 | **Judge unit and scale.** The unit is one bot reply plus its preceding turns, including the customer message from the reply's own turn (the message that prompted it; AM3). The reply itself is not part of its own context. Items are taken from a `make eval SUITE=dev SYSTEM=proposed` run (its `transcripts.jsonl`, plan SA2) and balanced across ES and PT and across flows. There are four pass/fail dimensions (grounding, tone, clarity, register) plus an overall pass/fail. The judge returns the same five booleans as structured output | Human Q5(a); `05` §5 dimensions. Context amended by AM3 |
| D16 | **Human labels.** 50 items: each person labels 20 alone, and both label the same 10. The labelers are `dev-a` and `dev-b` (`sample --labelers dev-a,dev-b`, AM2). The labeler and date go in each record | Human Q5(a); `07` B4; AM2 |
| D17 | **Agreement report.** For judge vs human, it reports κ and % agreement on overall and on each dimension, over all 50 items. For the shared 10 it uses the first labeler's label; the humans disagreed on 10 items, not on 50, so they are not adjudicated. It also reports human vs human κ and % agreement on the 10 shared items, with n, a small-sample caveat and the label "offline evaluation". If overall judge-vs-human κ < 0.6, the report says **"judge is weak"** at the top | Human Q5(a); `07` B4; `05` §6 E11 labels. Using the first labeler on the shared items is this spec's choice (Open questions 2) |
| D18 | **`priority_claim` handoff-summary fallback.** `handoff_summary`'s fixed `_FALLBACK` templates gain a `priority_claim` entry in ES and PT. It is used on a raw digit or an `LLMError`, like every other reason | AM4 (human-approved orchestrator follow-up after T5); R4, R11; `02` §3 "Handoff nodes" |
| D19 | **Transactions on non-card products** (for example a Cuenta Ahorro row) are listed and explained without a card mask. `card_mask_fact` returns none when `cards.get_card_details` raises `NotFound`. The explainer and details then carry no `card_mask` fact, and the `ui.transaction_list` label drops its `•••• last4` part. Before this, the pick crashed the turn (`NotFound`), and the list showed a fake `•••• 0000` | AM5 (T4 repair 1, human-accepted); R4. `04` §3 and `02` §4.5 amended |

## Contracts

Everything here is a delta. Everything else is unchanged from `04`.

### B1: policy file and NLU

```yaml
# policies/transaction_states.yaml
provenance: team-generated-synthetic
version: 1
pending:  {hold_days: 3, cause_key: pending_hold, next_step_key: wait_until_date, overdue_next_step_key: offer_human}
reversed: {cause_key: reversed_charge, next_step_key: no_action_needed}
```

- **Graph:**
  - `_INTENT_NODES` gains `transaction_search → tx_search` and `pending_reversal_explain → tx_explain`.
  - `_FLOW_NODES` gains `tx_search` and `tx_explain`.
  - `Pending.flow` gains those two names, both pausing at `awaiting_slot = "transactions"`.
  - `pending_reversal_explain` is added to the `tools.yaml` intents for `transactions.search` and `transactions.get`, where reads are gated.
- **NLU:** no schema change. The `nlu@vN` prompt only bumps its version if the implementer needs new ES/PT examples for these intents.
- **Code:**
  - `app/domains/transactions/merchants.py` holds `KNOWN_MERCHANTS: tuple[str, ...]` (24 names) and `match_merchant(text) -> list[str]`.
  - `app/domains/localization/dates.py` holds `resolve_date_expression(expr, today, tz, language) -> tuple[date, date] | None`.
  - Both are pure and do no I/O.

### B2: disputes

```yaml
# policies/disputes.yaml (v2): adds
priority:
  amount_threshold: {USD: "5000", COP: "20000000", ARS: "1800000"}
  open_statuses: [Open, In Process, Escalated]
  handoff: {queue: reclamos, priority: high, reason: priority_claim}
# policies/escalation.yaml (v4): adds under rules
  priority_claim: {queue: reclamos, priority: high}
```

- `disputes.service.priority_signals(customer_id) -> PrioritySignals{repeat_complainer: bool, open_critical: bool}`. It is customer-scoped from `ToolContext` (R1) and exposed as a read tool, `disputes.get_priority_signals()`, with no arguments.
- `HandoffReason` gains `priority_claim`. Update `04` §4 (the `reason` list) and `handoff/schemas.py`.
- A `create_claim` row for a flagged claim has `priority = 'High'`.

### B3: `04` §3 additions (proposed)

```python
class ConversationFilters(BaseModel):           # GET /staff/conversations query
    language: Literal["es","pt"] | None; country: Literal["MX","CO","AR"] | None
    intent: Intent | None; outcome: Literal["resolved","clarified","abstained","handoff"] | None
    escalation: HandoffReason | None; date_from: date | None; date_to: date | None
    limit: int = 50; offset: int = 0

class ConversationListItem(BaseModel):
    conversation_id: UUID; started_at: datetime; language: Literal["es","pt"] | None
    country: Literal["MX","CO","AR"]; intents: list[Intent]; outcome: str | None
    escalation: HandoffReason | None; handoff_queue: Queue | None; turns: int; mode: Literal["bot","human"]

class ConversationList(BaseModel):  items: list[ConversationListItem]; total: int

class TimelineLLMCall(BaseModel):
    step: str; model_id: str; prompt_version: str; latency_ms: float
    input_tokens: int | None; output_tokens: int | None; cost_usd: Decimal | None; status: str

class TimelineEvent(BaseModel):     # one audit.audit_events row, payload already masked
    at: datetime; type: str; actor: str; payload: dict; sources: list[str]

class TurnTimeline(BaseModel):
    turn_id: UUID; at: datetime; customer_text_masked: str | None; reply_text: str | None
    nlu: dict | None                       # nlu_result payload
    rules_hit: list[str]; tools: list[TimelineEvent]; sources: list[str]
    policy_version: str; llm_calls: list[TimelineLLMCall]
    latency_ms: float | None; cost_usd: Decimal | None; langfuse_url: str | None
    events: list[TimelineEvent]

class ConversationTimeline(BaseModel):
    conversation_id: UUID; system: dict    # git sha, model ids per step, prompt versions, policy hash
    turns: list[TurnTimeline]
```

| Route | Role | Returns |
|---|---|---|
| `GET /staff/conversations` + `ConversationFilters` | agent, admin (no claimed check) | `ConversationList`, newest first |
| `GET /staff/conversations/{id}/timeline` | agent, admin (no claimed check) | `ConversationTimeline`, `404 not_found` if the id is unknown |

### B4: eval

- **Prompt:** `eval/prompts/judge@v1.md`.
- **Step:** `judge` in the `core/llm` model registry (openai, `gpt-6-luna`, temperature 1.0).
- **Judge output:** `JudgeVerdict{grounding, tone, clarity, register, overall: bool, note: str}`, with `note` capped at 200 chars and masked.
- **Label record** (`eval/judges/labels/<labeler>.yaml`): `{item_id, run_id, case_id, turn_index, labeler, labeled_at, grounding, tone, clarity, register, overall}`.
- **Items:** `eval/judges/items.jsonl`, 50 masked reply items. Each item's `context` is the earlier turns plus the customer message from the reply's own turn (D15, AM3). They are sampled from `eval/reports/<run_id>/transcripts.jsonl`, which is gitignored (plan SA2).
- **Labelers:** `dev-a` and `dev-b`. `sample --labelers dev-a,dev-b` writes `labels/{assignment,dev-a,dev-b}.yaml` (D16, AM2).
- **CLI:**
  - `python -m eval.judges sample --run <run_id>` writes `items.jsonl`.
  - `python -m eval.judges judge` writes `judge_verdicts.jsonl`.
  - `python -m eval.judges agreement` writes `agreement.md`.

## Touch map

- **Backend: flows and graph.**
  - New: `backend/app/domains/conversation/flows/tx_search.py`, `tx_explain.py`.
  - Changed: `flows/unrecognized_charge.py` (flags), `graph.py` (the node tables), `state.py`, `templates.py` (ES/PT no-results and "nothing pending" templates), `tools/{bank,fakebank,postgres,registry}.py` (`get_priority_signals`).
- **Backend: domains and policy.**
  - `domains/transactions/merchants.py`
  - `domains/localization/dates.py`
  - `domains/disputes/{service,repository,schemas}.py`
  - `domains/handoff/schemas.py`
  - `domains/policy/{registry,disputes,escalation}.py` and a new `transaction_states.py`
- **Backend: core.** `core/llm/` (the `judge` step in the registry).
- **Policies.** New `policies/transaction_states.yaml`. Changed `disputes.yaml`, `escalation.yaml` (A reviews) and `tools.yaml`.
- **Frontend.**
  - New: `src/routes/staff/conversations.index.tsx`, `src/routes/staff/conversations.$conversationId.tsx`, `src/components/staff/{ConversationFilters,ConversationTable,TurnTimeline}.tsx`, `src/lib/traceability.ts`.
  - Changed: `src/lib/i18n/{es,pt}.json`, `e2e/mock-staff-api.ts`.
  - New test: `e2e/traceability.es.spec.ts`.
- **Eval.**
  - New: `eval/judges/{__init__,__main__,sample,judge,agreement}.py`, `eval/judges/rubric.md`, `eval/judges/labels/`, `eval/judges/agreement.md`, `eval/prompts/judge@v1.md`.
  - New dev scenarios: `eval/scenarios/dev/` for search hit (ES), pending explained (PT) and repeat complainer to Reclamos (ES).
  - A repeat-complainer persona in `eval/personas.yaml` if none fits.
- **Docs.**
  - `04` §3: D11 shapes and the claimed-rule exemption.
  - `04` §4: `priority_claim`.
  - `04` §5: `transaction_states.yaml`, the `disputes.yaml` priority block, `escalation.yaml` v4.
  - `02` §4.4/§4.5: D1-D3, one line each. `02` §4.8: D5-D9.
  - `07` §8: judge model decided (D14).

## Test list

All tests use the fake LLM. There are 13 in total.

| Test | Proves |
|---|---|
| `unit/test_tx_search_flow.py::test_super_ahorro_last_tuesday_es` | B1 "Done when", on the FakeBank fixture. The live proof uses the amended phrase (AM1, success criterion 3). A MX persona with a fixed bank clock says "el cargo de Super Ahorro del martes pasado por unos 350". The filter covers only that Tuesday, `merchant_names=["Super Ahorro"]` and 315-385 USD. The row is offered in a single-pick list |
| `unit/test_tx_search_flow.py::test_widen_once_then_nothing_found_pt` | PT happy path for the no-match branch. The widen happens once (±3 days), then the no-results reply lists the filters |
| `unit/test_tx_search_flow.py::test_vague_date_clarifies_without_search` | A1. No criterion → a clarify reply and 0 `transactions.search` calls |
| `unit/test_dates.py::test_resolve_expressions` | A3. A parametrized table in ES and PT (martes pasado, terça passada, ayer, há 3 dias, 12 de marzo, unresolvable → None) at a fixed today and TZ |
| `unit/test_tx_explain_flow.py::test_pending_explained_pt` | B1 explainer, PT. A Pending pick → the hold-days date is formatted in code (R4) and the source is `policy:transaction_states@…` |
| `unit/test_tx_explain_flow.py::test_reversed_explained_es` | B1 explainer, ES. A Reversed row → reversal cause, with no claim of a twin line |
| `unit/test_tx_explain_flow.py::test_pending_on_non_card_product_still_explained` | D19 regression. A Pending row on a non-card product is explained with no `card_mask` fact and no crash |
| `unit/test_priority_flags.py::test_flag_hands_off_to_reclamos[repeat-es, amount-pt, critical-es, critical-pt, repeat-pt, amount-es]` | B2 "Done when" (ES/PT per flag). The claim is created and verified (R3), then the handoff is `priority_claim` → `reclamos`/high, and the claim row has `priority='High'` |
| `unit/test_priority_flags.py::test_regulator_mention_goes_to_reclamos[es, pt]` | B2 regulator flag, D8. A mention during a paused claim → `legal_regulator` → Reclamos, with no claim |
| `unit/test_priority_flags.py::test_compromise_keeps_fraudes` | D7. Compromise plus a flag → the Fraudes handoff, with `priority_claim` in `escalation_rules_hit` |
| `unit/test_r1_customer_scope.py` (extend) `::test_priority_signals_bound_to_session` | R1. `get_priority_signals` takes no customer argument, and the FakeBank returns only the session customer's complaints |
| `unit/test_r6_no_write_tools_in_llm_nodes.py` (extend) | R6. The new flow nodes and the `judge` step have no write tools, and tool output reaches `compose` only as facts |
| `e2e/traceability.es.spec.ts` | B3 end-of-day step 1 on mocks. Staff login → list → filter by intent (the count changes) → open a conversation → expand a turn → NLU, rules, sources, policy hash and Langfuse link are visible |
| `eval/tests/test_judge_agreement.py::test_kappa_and_weak_flag` | B4 "Done when". Fixed labels give a known κ and % agreement, and κ < 0.6 writes "judge is weak". A second test that the judge input is masked and fenced (R5, R6) goes in the same file |

## Boundaries

- **Always:**
  - Build `TxFilter`, dates, merchant matches and flags in code.
  - Format money, dates and masks in code (R4).
  - Scope reads by `ToolContext` (R1).
  - Mask and fence judge input (R5, R6).
  - Label only dev-run outputs (R9).
  - Keep the new `04` §3 shapes marked (proposed).
- **Ask first:**
  - Anything in `escalation.yaml` beyond adding `priority_claim` (it is A's file).
  - Changing `route` or the `legal_regulator` rule.
  - Implementing the `/staff/conversations*` handler bodies (they are A1's).
  - A new `awaiting_slot` or `Clarification` value.
  - Putting judge scores into the held-out report.
- **Never:**
  - Open or edit `eval/scenarios/heldout/` or held-out outputs.
  - Let the LLM supply dates, amounts, merchants or flag values.
  - Show chain-of-thought or unmasked payloads in the console.
  - Import `openai` outside `app.core.llm`.
  - Send the persona's raw PII to the judge.

## Success criteria

1. `make check` is green: Ruff, mypy, import-linter and unit tests, including every test in the list above.
2. `cd frontend && npx playwright test e2e/traceability.es.spec.ts` passes.
3. With `make up`, persona `CLI-M9B56QX9KMBU` (CO) types "el cargo de Super Ahorro del jueves pasado por unos 790 mil" (AM1) and gets a list containing the 2026-09-24 Super Ahorro row (about COP 790,000). The pick shows decoded details. Picking a Pending row gives the explainer with a date. (End-of-day step 2.)
4. The repeat-complainer persona files a single-charge claim. The staff inbox shows a Reclamos handoff with reason `priority_claim`, and the `bank.complaints` row has `priority='High'` and `origin='app'`. (Step 3.)
5. `policies/transaction_states.yaml` exists with `provenance: team-generated-synthetic` and loads at startup. The policy hash changes.
6. `eval/judges/rubric.md` and `eval/judges/agreement.md` exist.
   - The report shows n=50 and, for overall and each of the four dimensions, judge-vs-human κ and % agreement.
   - It shows human-vs-human κ on the 10 shared items.
   - It is labeled "offline evaluation".
   - It starts with "judge is weak" when overall κ < 0.6.
7. `04` §3, §4 and §5 and `02` §4.4, §4.5 and §4.8 carry the deltas in the touch map. `07` §8 records the judge model.
8. `git diff develop -- eval/scenarios/heldout/` is empty.

## Amendments during build

Human decisions taken mid-card, from `docs/plans/d7-b-transactions-traceability-judge.state.md`. The plan's SA1 (token-bound `priority_flags`, reflected in D10) and SA2 (the harness writes `transcripts.jsonl`, reflected in the B4 contracts) are binding too.

- **AM1: B1 phrase.** The fixture data has no Super Ahorro charge of about 350 on a Tuesday. The "Done when" proof is now "el cargo de Super Ahorro del jueves pasado por unos 790 mil", for persona `CLI-M9B56QX9KMBU` (CO; row dated 2026-09-24, about COP 790,000). The dev seed is `d-transaction_search-normal_resolution-es-co-01`. To keep the eval mix on target, the es-MX seed `a-card_status-normal_resolution-es-mx-01` became `-es-co-01`.
- **AM2: labelers.** `dev-a` and `dev-b` (D16).
- **AM3: judge context.** It includes the customer message from the reply's own turn (D15).
- **AM4: `priority_claim` handoff-summary fallback** (D18).
- **AM5: non-card products** are explained without a card mask (D19).
- **AM6: environment setup.** The app DB (`latam_app`) was migrated from 0006 to 0008 with `alembic upgrade head`, human-authorized. This card adds no migration; the running DB was simply behind head, which made `app.pii_vault` missing.
- **AM7: other human-approved edits.**
  - `runner.py` `DebugInfo` reads `language` from the final checkpointed state, so a pick turn reports the conversation's language. Dev A reviews it.
  - The regenerated `frontend/src/client/index.ts` and `sdk.gen.ts` are kept, including the existing `test-idp/sessions` route.

### Known issues, accepted as unfixed (human decision)

1. **Missing period in the compose join.** The compose draft sometimes joins `{tx_date}` and `{tx_state_cause}` with no period in ES and PT. Example: "...no dia 06/12/2025 Seu pagamento...". This is cosmetic. Grounding still passes.
2. **Card-less `goal_tx_details` fallback.** `goal_tx_details` needs `{card_mask}`. So when the LLM draft fails grounding twice on an Approved row from a non-card product, the reply falls back to the generic `fallback` template instead of the details template.

## Open questions

1. D9 reads "open" as status in `[Open, In Process, Escalated]`. The human decides if that reading is wrong. It is one line in `disputes.yaml`.
2. D17 uses the first labeler's label on the 10 shared items rather than adjudicating them. The human can ask for adjudication, which is about 10 more minutes.
3. A1 may amend the D11 shapes. When it does, B3 moves to the generated client and this spec's Contracts section is amended. Dev A decides.
4. Whether A2's held-out report includes judge scores. Dev A decides.
