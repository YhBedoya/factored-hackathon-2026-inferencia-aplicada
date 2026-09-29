# Spec: D4-B — G9 disputes and fraud, and the handoff screens

Card: `07-execution-plan.md` D4, Dev B track, rows B1–B4. Owner: Dev B. Branch `feat/d4-b-disputes-handoff-screens` → `develop`. The PR touches the tool registry, `tools.yaml` and identity (staff login), so it is safety-critical and Dev A reviews it before merge (ADR-018).

## Objective

A customer who doesn't recognize charges picks them from a list, and code decides the path. On a suspected compromise, the customer confirms one plan (block, then claim), and the case goes to Fraudes. On a single charge, the customer answers the `disputes.yaml` questions and gets a case ID. The card also ships the customer widgets (transaction list, handoff banner, bot/agent indicator) and the staff screens (login, live inbox, claim, packet view, live chat, return to bot). Those screens are built against a declared `/staff/*` API whose handlers A fills in (A3/A4). The card serves the "Done when" lines of B1–B4 and end-of-day steps 1, 3 and 5. Steps 1–2 run on the real stack only once A3/A4 land, and until then they are proved against mocks (D2). It also resolves the deferred "suspected-compromise rule" item and the "staff protection decided on the staff-panel card" item in ADR-008.

**If behind (`07`):** B moves the single-charge questions (`disputes.yaml` `questions` after the possession question) to D5 and the return-to-bot button to D6. The possession question stays, because it belongs to the compromise rule (D8).

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **Handoff contract only, with an in-memory fake.** B writes the `04` §4 schemas and a `HandoffPort` protocol in `app/domains/handoff/`, plus `InMemoryHandoffPort`, which fills `request` from a fixed ES/PT template. The B2 flow tests, the sandbox and (until A3 lands) the API runner use it. A owns the real port (`app.handoffs`, Redis `handoff:<queue>`, the LLM `request`, `mode = human`, `relay_to_agent`). B's code never writes `mode` | Human Q1. Assumption 1. `02` §6, `04` §4 |
| D2 | **`/staff/*` is declared now, and its handlers return `501 not_implemented`.** The routes have real Pydantic request and response models, so OpenAPI and the generated client exist today, and the staff screens are built against that client. `GET /staff/me` is fully implemented (it needs nothing from A). B4's two-browser proof waits for A | Human Q1 |
| D3 | **Staff login, one account.** One `identity.accounts` row with `role='agent'`, a `username`, a `display_name` and `customer_id = NULL`. It works every queue. `POST /auth/staff/login {username, password}` issues the same `session` and CSRF cookies. Its `login_key` is HMAC(`IDENTITY_HMAC_KEY`, `staff:<username>`), which reuses the login lookup and the `rl:login:` limiter. Customer login accepts only `role='customer'` and staff login only `role='agent'` | Human Q2. ADR-008 (amended in this PR), `03` §8 |
| D4 | **Session typing.** `Session.role: Literal["customer","agent"]`, `Session.customer_id: str \| None`, with a validator: customer ⇔ `customer_id` set, agent ⇔ `None`. Customer-only code narrows through `require_customer_id(session) -> str`, which raises if the id is `None`. `TokenClaims` changes the same way. The audit actor of an agent is `agent:<account_id>` | Human Q2 ("widen role Literal", "actor = agent:<id>"). R1, R13 |
| D5 | **Role split.** `/staff/*` routers declare `require_role("agent")` + `require_csrf`. `/auth/logout` moves to a router with `require_role("customer","agent")`. `/auth/me`, `/auth/otp/verify` and `/conversations/*` stay customer-only, so an agent session there gets `403 forbidden_role`. `/auth/refresh` with an agent session returns `403 forbidden_role`, and the staff SPA sends a `401` straight to `/staff/login` | Human Q2, R13, ADR-025 |
| D6 | **The agent stream is `GET /staff/conversations/{id}/stream`** (agent, after claiming). The `04` §3 row for `/conversations/{id}/stream` becomes customer only | Assumption 2. R13 (`conversations.py` `get_owned_conversation`) |
| D7 | **Pick input.** `POST /conversations/{id}/messages` accepts exactly one of `{text}`, `{resume}` or `{selection: {tx_ids}}` (1–10 unique ids). Before scheduling a turn, the route checks that the checkpoint is paused at `awaiting_slot == "transactions"` and that every id is in `dispute.offered_tx_ids`. If not, it returns `409 selection_invalid` and schedules no turn. The flow checks again. `TurnInput.selection` skips `understand` (entry-routing step 0), and the selection is not saved as a customer message | Human Q6. D3-A D7 pattern (two gates), D3-A D20(2) |
| D8 | **Compromise rule.** Suspected compromise = picked ≥ `compromise.min_picked` (2), or any picked `fraud_score` > `compromise.fraud_score_gt` (30), or "no" to the possession question. Both thresholds live in `policies/disputes.yaml`. The possession question is asked right after the pick, only if count and score haven't already triggered. "No" → compromise path, "yes" → the remaining `questions`, in order | Human Q4. `02` §4.8, R8. Resolves the decision-log deferred row |
| D9 | **Compromise path.** One ADR-027 plan, `[cards.block_card(card_id, "suspected_fraud"), disputes.create_claim(tx_ids, answers)]`, under intent `unrecognized_charge`, then a handoff to the `disputes.yaml` `handoff` queue (`fraudes`, priority `high`, reason `suspected_fraud`). The first failed or unverified step stops execution and hands off through the existing `action_unverified` path | `02` §4.8, ADR-027, `04` §4 example. Assumption 5 |
| D10 | **Refused block.** If the plan is cancelled, nothing is written, and the bot offers the claim alone as a one-step plan. If that is confirmed and verified, the bot gives the case ID and hands off to Fraudes with `open_questions` noting that the card is still active. If the claim is cancelled too, the bot still hands off to Fraudes (with no claim, and with both refusals in `open_questions`) | Human Q5. `02` §5 "Confirmed or suspected fraud → Fraudes" |
| D11 | **Single-charge path.** After the questions: a one-step plan `[disputes.create_claim([tx_id], answers)]` → confirm → verified → the case ID. No handoff | `02` §4.8 step 3, end-of-day step 3 |
| D12 | **Candidates.** `transactions.search(card_id, status = disputes.yaml candidate_statuses)`. The statuses are `[Approved, Pending, Reversed]`, so Declined is excluded. The tool's own cap applies: 10, newest first. With no candidates, the bot sends the fixed `dispute_no_transactions` template, writes nothing and clears `pending` | Assumption 7. `04` §1 `transactions.search` |
| D13 | **UI payloads built in code (R4).** `ui.transaction_list {options: [{tx_id, label}], multi: true}`, where the label is `merchant · money · day-first date · •••• last4` (from `localization.format`), and a missing merchant uses the fixed "Comercio"/"Estabelecimento" label. `ui.handoff_banner {handoff_id, queue, queue_label, case_ids}`. `mode {mode, agent_display_name}` is shown as in `04` §3 and emitted by A | Assumption 4. R4 |
| D14 | **Claim rows.** One `bank.complaints` row per picked transaction: `complaint_id = "CLM-" + 8 upper hex`, `case_type='Claim'`, `category='Transactions'`, `subcategory='Cargo no reconocido'`, `reception_channel='App'`, `status='Open'`, `origin='app'`, `conversation_id`, `creation_date=now()`, `customer_id` from `ToolContext`, and `affected_product_id`, `claimed_amount`, `currency` and `transaction_id` copied from the transaction record. `priority` stays NULL (priority flags are out of scope). `description` holds the answers built in code (see Open questions 1) | Human Q3, assumption 6. R1, R12, `04` §4 (`CLM-…`), D3-A `RPL-` pattern |
| D15 | **Claim idempotency.** Migration `0005` adds nullable `transaction_id` and a unique nullable `idempotency_key` to `bank.complaints`. The per-row key is `<token_id>:<step_index>:<tx_id>`. A step replayed with existing keys re-reads and returns the existing rows and writes nothing | Human Q3. D3-A D11, `04` §1 idempotency paragraph |
| D16 | **`ActionResult.case_ids: list[str] \| None`** (default `None`), set only by `disputes.create_claim`. `readback = {"status": "Open", "count": n, "at": datetime}`. `verified` is true only when a re-read of every row matches its transaction (amount, currency, product, `transaction_id`, `origin='app'`) and belongs to the session's customer. `priority_flags` is deferred | Human Q3. R3, `04` §1 amended |
| D17 | **Tool args.** `ToolArg` widens to `str \| int \| bool \| None \| list[str]`, so `tx_ids` and `answers` hash canonically (`04` §7); `tools_policy.step_up_rule`'s args mapping widens the same way (A2). `answers` is a sorted `list[str]` of `"<question_id>=<yes\|no>"` | `04` §1 `disputes.create_claim(tx_ids, answers, token)`, `04` §7 |
| D18 | **`policies/tools.yaml`.** Adds `disputes.create_claim {requires_confirmation: true, step_up: never, allowed_intents: [unrecognized_charge]}`, and `cards.block_card.allowed_intents` gains `unrecognized_charge`. `handoff.create` stays internal, with no token and not in `tools.yaml` | Assumption 5. ADR-027, R2, R8 |
| D19 | **Ports reach flows only through `config["configurable"]`:** `bank_write_tools` (as today) and a new `handoff`. The R6 test's forbidden keys gain `handoff`, so an LLM node can't open a case | R6. `04` §1 `handoff.create` "internal" |
| D20 | **Live inbox.** `GET /staff/handoffs?queue=` polled every 3 s (TanStack Query `refetchInterval`). There is no inbox SSE. Staff screens are `/staff/*` routes in the same SPA, with ES/PT from the shared dictionary | Assumptions 3, 9 |
| D21 | **Proof.** Frontend: Playwright against the built SPA with the API mocked (the D3-B D7 pattern). Backend: flow tests with `ScriptedLLM` + FakeBank + `InMemoryHandoffPort`, and integration tests for the tool and routes. The real two-browser test runs when A3/A4 merge | Human Q1. D3-B D7, CLAUDE.md test rules |
| D22 | **Out of scope:** priority flags → Reclamos, "recognize before you dispute", `POST /staff/actions/{tool}`, the traceability console, a transcript route for agents, A1 escalation rules, A2 abstention | Assumption 8 |
| D23 | **Migration order.** B's migration is `0005` (down `0004`). A's `app.handoffs` migration is `0006` (down `0005`) | Coordination. Human Q1 (A owns `handoffs`) |

## Contracts

Only the delta. Everything else is as in `04` §1, §3, §4 and §7.

**`policies/disputes.yaml`** (new; values are team-generated synthetic)
```yaml
provenance: team-generated-synthetic
version: 1
candidate_statuses: [Approved, Pending, Reversed]
compromise: {min_picked: 2, fraud_score_gt: 30, block_reason: suspected_fraud}
possession_question: card_in_possession      # asked first, only if count/score didn't trigger; "no" → compromise
questions: [card_in_possession, contacted_merchant]   # asked in order on the single-charge path
handoff: {queue: fraudes, priority: high, reason: suspected_fraud}
```
Model `DisputesPolicy` in `app/domains/policy/disputes.py`, registered as a known stem in `policy/registry.py`. The ES/PT question texts are templates (`dispute_q_<id>`), not YAML.

**`app/domains/handoff/schemas.py`** (new)
```python
Priority = Literal["normal", "high"]
HandoffStatus = Literal["queued", "claimed", "returned", "closed"]         # 03 §6
class VerifiedFact(BaseModel):  fact: str; value: str | list[str]; source: str
class ActionTaken(BaseModel):   tool: str; result: Literal["applied"]; verified: bool
                                audit_event_id: UUID | None; at: datetime | None; case_ids: list[str] | None = None
class Evidence(BaseModel):      type: Literal["transaction"]; ref: str; fraud_score: Decimal | None
class HandoffDraft(BaseModel):  # everything code assembles; frozen, extra="forbid"
    queue: Queue; priority: Priority; reason: str; language: Literal["es","pt"]
    verified_facts: list[VerifiedFact]; actions_taken: list[ActionTaken]; evidence: list[Evidence]
    open_questions: list[str]            # code-filled ES/PT text in `language`
    escalation_rules_hit: list[str]
class HandoffPacket(HandoffDraft):       # 04 §4, exactly
    handoff_id: UUID; conversation_id: UUID; request: str
    sentiment: Literal["negative","neutral","positive"] | None   # A decides how it is set; B's fake sets None
    policy_version: str; created_at: datetime
class HandoffRef(BaseModel):     handoff_id: UUID; queue: Queue; created_at: datetime
class HandoffPort(Protocol):     # bound per turn to (conversation_id, policy_version)
    async def create(self, draft: HandoffDraft) -> HandoffRef: ...
class HandoffSummary(BaseModel): handoff_id; conversation_id; queue; priority; reason; status: HandoffStatus
                                 created_at; claimed_by: str | None      # agent display name
class HandoffListResponse(BaseModel): items: list[HandoffSummary]
class HandoffDetail(HandoffSummary):  packet: HandoffPacket
class AgentMessageRequest(BaseModel): text: str (1..2000)        # extra="forbid"
class AgentMessageResponse(BaseModel): message_id: UUID
```
`app/domains/handoff/memory.py`: `InMemoryHandoffPort(conversation_id, policy_version)` stores `packets: list[HandoffPacket]` and fills `request` from the `handoff_request` template.

**Identity** (`models.py`, `tokens.py`, `service.py`)
```python
class Session: role: Literal["customer","agent"]; customer_id: str | None   # validator (D4)
class StaffLoginRequest(BaseModel): username: str; password: str           # frozen
class StaffMeResponse(BaseModel):   role: Literal["agent"]; display_name: str
def require_customer_id(session: Session) -> str
async def staff_login(req: StaffLoginRequest, ...) -> Session               # 401 / 429 as customer login
async def staff_me(session: Session) -> StaffMeResponse
```
Provisioning (`provision.py`): one agent row with `username` = `STAFF_USERNAME` and `display_name` = `STAFF_DISPLAY_NAME` (settings with defaults; see Open questions 2). Its password is generated from `CREDENTIALS_SEED` like the customers', and written to the git-ignored `data/secrets/staff_credentials.csv`.

**Migration `0005_claims_staff`** (down `0004`)
| Table | Change |
|---|---|
| `bank.complaints` | + `transaction_id text null`, + `idempotency_key text unique null` |
| `identity.accounts` | `customer_id` drops NOT NULL (FK and unique stay); + `username text unique null`, + `display_name text null`; CHECK `(role='customer' AND customer_id IS NOT NULL) OR (role='agent' AND customer_id IS NULL AND username IS NOT NULL)` |

**Tools**
```python
# conversation/tools/write.py — BankWriteTools gains
async def create_claim(self, tx_ids: list[str], answers: list[str], *, idempotency_key: str) -> ActionResult
    # disputes.create_claim. May raise NotFound, AccessDenied (any tx not the customer's), ToolUnavailable
# executor.py — ConfirmedWriteTools.create_claim(tx_ids, answers, token_id): same D3-A D16 order
# app/core/actions.py — ActionResult + case_ids: list[str] | None = None
# policy/confirmation.py — ToolArg = str | int | bool | None | list[str]  (tools_policy.step_up_rule args too, A2)
```
`app/domains/disputes/{schemas,repository,service}.py` (new): `service.create_claims(customer_id, conversation_id, tx_ids, answers, idempotency_key) -> list[ClaimRow]` and `service.get_claims(customer_id, ids)`. The service reads each transaction through `transactions.service` (the own-row check comes first). `postgres_writes.py` calls `disputes.service`, which needs a new import-linter ignore edge. `FakeBankWrites.create_claim` records into the overlay with the same replay behavior.

**Graph and state**
```python
class DisputeState(TypedDict):          # TurnState.dispute: NotRequired[DisputeState | None]
    card_id: str; offered_tx_ids: list[str]; fraud_scores: dict[str, Decimal | None]
    picked_tx_ids: list[str]; answers: list[str]; question_index: int
    compromise: bool; block_refused: bool
class TxSelection(BaseModel): tx_ids: list[str]     # 1..10, unique; frozen, extra="forbid"
TurnInput.selection: NotRequired[TxSelection | None]   # graph-local, like confirmation
```
New `awaiting_slot` values: `"transactions"`, `"card_possession"` and `"dispute_question"`. The last two are affirm/deny slots in `route._answer_fits`. Entry routing gains step 0: `selection` set and `awaiting_slot == "transactions"` → `unrecognized_charge`, else `smalltalk`. `_INTENT_NODES`/`_FLOW_NODES` gain `unrecognized_charge`. `flows/actions.start_plan` takes a list of steps, and a new `execute_plan` runs them in order, stopping at the first failure. `runner.start_turn(..., selection: TxSelection | None = None)`, and `runner.checkpointed_dispute(host, conversation_id)` backs the D7 route check.

**UI events** (`ui.py`)
```python
class TxOption(BaseModel):              tx_id: str; label: str
class TransactionListPayload(BaseModel): options: list[TxOption]; multi: Literal[True] = True
class HandoffBannerPayload(BaseModel):  handoff_id: UUID; queue: Queue; queue_label: str; case_ids: list[str]
# TransactionListEvent{kind:"transaction_list"}, HandoffBannerEvent{kind:"handoff_banner"} join UIEvent
```
`ui.confirm` step `summary_key` gains `create_claim`, whose facts are `tx_count`.

**HTTP (`/api/v1`)**
| Route | Role | Body → response | Errors | Built by |
|---|---|---|---|---|
| `POST /conversations/{id}/messages` | customer | `{text} \| {resume} \| {selection:{tx_ids}}` → `202 {turn_id}` | `422` (not exactly one), `409 selection_invalid`, `409 turn_in_progress`, `404` | B |
| `POST /auth/staff/login` | public | `StaffLoginRequest` → `200 StaffMeResponse` + cookies | `401 invalid_credentials`, `429 too_many_attempts` | B |
| `POST /auth/logout` | customer, agent | → `204` | `401` | B (router move) |
| `GET /staff/me` | agent | → `StaffMeResponse` | `401`, `403` | B |
| `GET /staff/handoffs?queue=` | agent | → `HandoffListResponse` | | B declares (`501`), **A implements** |
| `GET /staff/handoffs/{id}` | agent | → `HandoffDetail` | `404` | B declares, **A implements** |
| `POST /staff/handoffs/{id}/claim` | agent | → `HandoffDetail` | `404`, `409 already_claimed` | B declares, **A implements** |
| `POST /staff/handoffs/{id}/return` | agent | → `HandoffSummary` | `404`, `409 not_claimed` | B declares, **A implements** |
| `POST /staff/conversations/{id}/messages` | agent | `AgentMessageRequest` → `202 AgentMessageResponse` | `404`, `409 not_claimed` | B declares, **A implements** |
| `GET /staff/conversations/{id}/stream` | agent | SSE (`04` §3 events) | `404`, `409 not_claimed` | B declares, **A implements** |

### What A must implement (A3/A4), against these contracts
1. A Postgres + Redis `HandoffPort`: persist to `app.handoffs` (migration `0006`), build `request` through `core/llm` (masked and capped), set `sentiment`, publish `handoff:<queue>`, set `mode = human` in the checkpoint and `app.conversations`, and emit the `mode` event. Then replace `InMemoryHandoffPort` in `runner._run_turn`.
2. `mode == human` → `relay_to_agent` in the graph, and return-to-bot (`mode = bot` plus a summary fact).
3. The bodies of the six `501` staff routes, the claimed-by-this-agent check behind the `404`/`409` codes, the inbox filter and order (see Open questions 3), and relaying agent messages to the customer's `/stream`.
4. A1's escalation rules and A2's abstention (not B's).

## Touch map

```
policies/{disputes.yaml (new), tools.yaml (edit)}
backend/app/alembic/versions/0005_claims_staff.py                      new
backend/app/core/actions.py                                            + case_ids
backend/app/domains/policy/{disputes.py (new), registry.py, confirmation.py (ToolArg), tools_policy.py (step_up_rule args, A2)}
backend/app/domains/disputes/{__init__,schemas,repository,service}.py  new (B1)
backend/app/domains/handoff/{__init__,schemas,memory}.py               new (D1)
backend/app/domains/identity/{models,tokens,service,provision,repository}.py   staff login (D3, D4)
backend/app/core/config.py                                             STAFF_USERNAME, STAFF_DISPLAY_NAME
backend/app/api/v1/{auth.py (staff login, logout router), staff.py (new), conversations.py (selection)}
backend/app/api/v1/__init__.py                                         mount staff router
backend/app/domains/conversation/tools/{write,executor,postgres_writes,fakebank,registry}.py   create_claim; fakebank _to_tx_view UTC fix (A3)
backend/app/domains/conversation/{state,graph,ui,templates,runner,sandbox}.py
backend/app/domains/conversation/store.py                              MessageRow.ui_payload widened (A1)
docs/diagrams/turn-graph-v0.mmd                                        regenerated (A4)
backend/app/domains/conversation/nodes/route.py                        new affirm/deny slots
backend/app/domains/conversation/flows/{actions.py (multi-step), unrecognized_charge.py (new)}
backend/app/domains/conversation/**/*.py call sites                    require_customer_id (D4)
backend/.importlinter                                                  postgres_writes -> disputes.service
backend/scripts/chat_api.py                                            /pick <n,…> (selection by list index)
backend/tests/fixtures/fakebank/…                                      one card with ≥3 non-declined txns (one fraud_score > 30) + one declined; one card with none
eval/personas.yaml                                                     demo persona CLI-0D54NQDU9AWV (fraud_score > 30); CLI-325VRPVVYG7T → CLI-F7PQP3J4AS6X (A5)
frontend/src/components/chat/{TransactionList,HandoffBanner,ModeIndicator}.tsx   new (B3)
frontend/src/routes/chat.tsx, lib/sse.ts                               ui.transaction_list, ui.handoff_banner, mode
frontend/src/routes/staff/{login,index,handoffs.$handoffId}.tsx        new (B4)
frontend/src/components/staff/{InboxList,PacketView,AgentChat}.tsx    new (B4)
frontend/src/lib/{api.ts (staff 401 → /staff/login), i18n/{es,pt}.json}
frontend/src/client/                                                   regenerated (make client)
frontend/e2e/{unrecognized.es.spec.ts, staff.es.spec.ts, fixtures/*.sse, mock-api.ts}
docs/solution-docs/{02,03,04,decision-log}.md                          amended in this PR (see below)
```

**Doc amendments in this PR:** `04` §1 (`create_claim` row, `ActionResult.case_ids`, `ToolArg`), §3 (`/messages` selection, the staff login and staff routes, the stream row, the staff paragraph, the `ui` payloads), §4 (schema location, `HandoffDraft`, nullable `sentiment`) and §5 (`tools.yaml`, `disputes.yaml`). `02` §3 (entry step 0, `dispute` state, slots) and §4.8 (rule decided). `03` §6 (`complaints`, `accounts`) and §8 (staff account). Decision log: ADR-008 amended, and the deferred compromise-rule row resolved.

## Test list

Flow tests use `ScriptedLLM` + FakeBank + `InMemoryHandoffPort`. Integration tests use `it_env`. E2E tests use the mocked API.

| Test | Proves |
|---|---|
| `unit/test_dispute_flows.py::test_compromise_path[es-two_picked, pt-possession_no, es-score_gt_30]` | B2 "compromise path" ES/PT, D8, D9. The pick turn (`selection`, no NLU call) → one `ui.confirm` with steps `[block_card, create_claim]` → confirm → both results verified → the reply holds the case IDs and the Fraudes handoff text → the port got one draft (queue `fraudes`, evidence = picked ids with scores, `actions_taken` from verified results) → `ui.handoff_banner.case_ids` equals the claim's `case_ids` |
| `unit/test_dispute_flows.py::test_single_charge_questions_claim[es, pt]` | B2 "single charge" ES/PT, end-of-day step 3, D11. One pick with a low score → possession "sí" → `contacted_merchant` → a one-step plan → the case ID. The port is never called |
| `unit/test_dispute_flows.py::test_no_transactions_writes_nothing` | B2 "no transactions", D12. A card with only declined transactions → `dispute_no_transactions`, no `transaction_list`, no plan issued, no write |
| `unit/test_dispute_flows.py::test_refused_block` | B2 "refused block", D10. Cancel the plan → no write → claim-only plan → confirm → case ID → the draft's `open_questions` mentions the card is still active. The card status is unchanged |
| `unit/test_dispute_flows.py::test_transaction_list_labels_from_code` | R4, D13. Every option label equals the `localization.format` output for merchant, money, date and mask |
| `unit/test_r2_confirmed_writes.py::test_compromise_plan_order_and_allowlist` | R2, D18. A `[block_card, create_claim]` plan: calling the claim first → `step_mismatch`; replaying the claim → `unknown_or_expired`; `create_claim` under intent `card_block` → `PolicyDenied("tool_not_allowed")` |
| `unit/test_r6_no_write_tools_in_llm_nodes.py` (+ `handoff` key) | R6, D19. No LLM node references `handoff` or `bank_write_tools` |
| `integration/test_postgres_disputes.py::test_claim_row_matches_transaction` | B1 Done-when, R3, R12, D14–D16. Two tx ids → two `bank.complaints` rows whose `claimed_amount`, `currency`, `affected_product_id` and `transaction_id` equal the transaction, with `origin='app'` and `conversation_id` set, and `verified=True`. A stale re-read stubbed in → `verified=False`. Replaying the same key → no new rows and the same `case_ids` |
| `integration/test_postgres_disputes.py::test_foreign_transaction_refused` | R1. A tx id of another customer → `AccessDenied`, no row, `access_denied` audited |
| `integration/test_confirmations_route.py::test_injected_tx_id_is_409` | D7, human Q6. A selection with an id not offered (or when no list is pending) → `409 selection_invalid`, no turn scheduled |
| `integration/test_auth.py::test_staff_login_and_role_split` | B4 staff login, R13, D3–D5. Staff login → `/staff/me` 200 with `display_name`; that session on `/conversations` → `403`; a customer session on `/staff/me` → `403`; customer credentials on staff login → `401` |
| `unit/test_r13_routes.py` (allowlist + `/auth/staff/login`) | R13. Every `/staff/*` route declares `RoleGuard(("agent",))` |
| `e2e/unrecognized.es.spec.ts` | B3 "rendered in the browser". A `transaction_list` renders checkboxes → picking 2 and pressing "Continuar" posts `{selection:{tx_ids:[…]}}` → the confirm card lists 2 steps → `handoff_banner` shows the queue label and case ID → a `mode` event switches the header to the agent's name |
| `e2e/staff.es.spec.ts` | B4 screens (mocked `/staff/*`). Staff login → the inbox shows a queued Fraudes case (polling) → claim → the packet view shows verified facts, actions, evidence and open questions → sending a message posts to `/staff/conversations/{id}/messages` → "Devolver al bot" posts `/return` |

`make check` and `make test-integration` pass, and `npx playwright test` passes in `frontend/`.

## Boundaries

- **Always:** take `customer_id` from the session (`require_customer_id`) and never from a selection, a route or the LLM (R1). Run every claim through `ConfirmedWriteTools` with a plan step (R2). Say "done" or show a case ID only from a verified `ActionResult` (R3). Build every label, amount, date and mask in code (R4). Keep thresholds and question ids in `disputes.yaml` (R8). Regenerate the client with `make client`.
- **Ask first:** changing a `04` §4 packet field; implementing any `/staff/*` handler body beyond `501` (that is A's); writing `mode`; adding priority flags or "recognize before you dispute"; any change to `escalation.yaml` (A1 edits it the same day).
- **Never:** let an LLM node reach `handoff` or `bank_write_tools` (R6); accept a `tx_id` that wasn't offered; put agent or customer credentials in the repo or logs; edit `eval/scenarios/heldout/`; edit an existing migration.

## Success criteria

1. B1: `test_claim_row_matches_transaction` and `test_foreign_transaction_refused` pass. After `make chat-api PERSONA=<demo persona>` → "no reconozco estas compras" → `/pick 1,2` → `/confirm`, `SELECT claimed_amount, currency, transaction_id, origin FROM bank.complaints WHERE conversation_id = …` returns 2 rows equal to the 2 transactions' amounts and currencies, with `origin = 'app'` (end-of-day step 5).
2. B2: the five `test_dispute_flows.py` tests pass (both paths in ES and PT, no transactions, refused block, labels). `policies/disputes.yaml` holds `2` and `30`, and no compromise literal exists in Python (`grep -rn "fraud_score_gt\|min_picked" backend/app` shows only the policy model).
3. B2/R2/R6: `test_compromise_plan_order_and_allowlist` and the R6 test pass. `tools.yaml` lists `disputes.create_claim` with `allowed_intents: [unrecognized_charge]`.
4. D7: `test_injected_tx_id_is_409` passes.
5. B3: `e2e/unrecognized.es.spec.ts` passes.
6. B4: `test_staff_login_and_role_split`, the R13 test and `e2e/staff.es.spec.ts` pass. `/api/v1/openapi.json` lists the six staff routes, and `frontend/src/client/` exports functions for them.
7. `make check` is green, and the `04`/`02`/`03`/decision-log amendments listed in the Touch map are present.
8. Deferred to A3/A4 merge (not graded on this card): end-of-day steps 1–2 in two browsers.

## Amendments during build

| # | Amendment | Why / trace |
|---|---|---|
| A1 | `store.MessageRow.ui_payload` is `dict[str, Any] \| list[dict[str, Any]] \| None` | Human decision (T10): list-shaped `confirm`/`transaction_list` rows broke `list_messages` |
| A2 | `policy/tools_policy.py::step_up_rule` accepts the `list[str]` arg form | Follows D17's `ToolArg` widening (T4) |
| A3 | `tools/fakebank.py::_to_tx_view` attaches UTC to naive DuckDB timestamps | Pre-existing bug, first hit by this flow |
| A4 | `docs/diagrams/turn-graph-v0.mmd` regenerated with the `unrecognized_charge` node | Graph shape changed |
| A5 | `eval/personas.yaml`: demo persona `CLI-0D54NQDU9AWV` (fraud_score > 30) added; stale `CLI-325VRPVVYG7T` swapped for `CLI-F7PQP3J4AS6X` (same trait; the old one drifted out of its 30-day window) | Human Q4 demo note |

**Known follow-ups (not built):**
- The backend emits no tool-level spans; tool order is proved by tests, not traces.
- The new checkpoint types log LangGraph msgpack "unregistered type" warnings; register them in `allowed_msgpack_modules`.
- `disputes.repository.fetch_claims_by_keys` could also filter by `customer_id` (defence in depth).
- **A must** add a claimed-by/ownership check to `/staff/handoffs/{id}` and `/staff/conversations/{id}` when implementing them.
- No test covers agent `/auth/refresh` → `403` (proved at runtime only).
- On Windows, integration tests need `WindowsSelectorEventLoopPolicy` and `REDIS_URL=127.0.0.1`.

## Open questions

1. **Claim `description` content.** Proposed: a code-built `answers` string (`"card_in_possession=no; contacted_merchant=yes"`), with no customer free text. Human at the spec gate.
2. **Staff display name and username defaults** (`STAFF_DISPLAY_NAME`, shown to customers in the `mode` event, and `STAFF_USERNAME`). Proposed: `Sofía` / `agente`. Human at the spec gate.
3. **Inbox filter and order** (`GET /staff/handoffs`): proposed `status in (queued, claimed)`, oldest first. Dev A confirms when implementing A4.
4. **Already-blocked card on the compromise path.** Proposed: keep `block_card` in the plan (it writes a history row, as FakeBank does today). Human at the spec gate.
