# 04 — Contracts

Contracts are Pydantic models in the backend. The frontend types are generated from OpenAPI. The shapes below are the design intent, and field names are **(proposed)** until the first implementation PR fixes them.

## 1. Tool registry

Every bank tool is a typed async function registered with metadata. **The LLM never supplies `customer_id`.** The registry binds it from `ToolContext`, which is built from the session.

```python
class ToolContext(BaseModel):          # built by the registry, never by the model
    customer_id: str
    conversation_id: UUID
    actor: Literal["customer", "agent", "system"]
    trace_id: str
    policy_version: str

class ToolSpec(BaseModel):
    name: str                          # "cards.block_card"
    side_effect: bool
    requires_confirmation: bool        # server-issued single-use token
    requires_step_up: bool             # step-up OTP (fixed demo code, ADR-008) verified within the last N minutes
    allowed_intents: list[str]         # from policies/tools.yaml
    timeout_s: float
    retries: int = 2
```

Errors are a typed union: `NotFound`, `AccessDenied` (the resource belongs to another customer; audited), `ToolUnavailable`, `PolicyDenied(reason_code)`, `ConfirmationRequired(reason: unknown_or_expired | step_mismatch | wrong_owner)`, `StepUpRequired`, `Conflict` (e.g., already blocked). K3 ships the read-side errors only (`NotFound`, `AccessDenied`, `ToolUnavailable`); the write-side four are defined in `docs/specs/d2-k-write-contracts.md` (Decision D14).

### MVP tools

| Tool | Side effect | Confirm | Step-up | Returns |
|---|---|---|---|---|
| `customers.get_profile()` | — | — | — | `CustomerProfile{country, customer_status, first_name, city}` (`first_name` is PII: it reaches the LLM only as the `{customer_name}` key, ADR-029; `city` is PII too, D2-B D4, and reaches a reply only as the masked `•••, <city>` delivery-address label) |
| `cards.list_cards()` | — | — | — | `[CardSummary{card_id, kind, last4, status, locked}]` |
| `cards.get_card_details(card_id)` | — | — | — | `CardDetails{card_id, kind, last4, status, locked, currency, expiration_date, credit_limit, current_balance, interest_rate, days_past_due, source, available_credit}` (`available_credit` computed as `credit_limit − current_balance`; all credit-only fields are `None` for debit cards) |
| `cards.get_block_origin(card_id, intent)` | — | — | — | `BlockOrigin{kind: customer_lock/customer_block/bank_side/none, reason}` (`intent` gates on `allowed_intents`, D3-A1/D3) |
| `cards.lock_card(card_id, token_id)` | ✓ | ✓ | — | `ActionResult` |
| `cards.unlock_card(card_id, token_id)` | ✓ | ✓ | ✓ | `ActionResult` |
| `cards.block_card(card_id, reason, token_id)` | ✓ | ✓ | — | `ActionResult` |
| `cards.order_replacement(card_id, address_ref, token_id)` | ✓ | ✓ | ✓ if address changed | `ActionResult{tracking_id}` |
| `transactions.search(filter: TxFilter)` | — | — | — | `[TxView{tx_id, card_id, occurred_at, amount, currency, amount_usd, type, category, merchant_name, merchant_category, channel, city, country, status, response_code, fraud_score}]`, max 10, newest first |
| `transactions.get(tx_id)` | — | — | — | `TxView` |
| `transactions.get_by_ids(tx_ids)` | — | — | — | `[TxView]` in `tx_ids`' order, customer-scoped (R1): own rows first, then an existence probe (`AccessDenied` for another customer's id, `NotFound` for none). Used by the tx_search / tx_explain pick resume, since `search` caps at 10 |
| `transactions.explain_decline(tx_id)` | — | — | — | `DeclineExplanation{code, cause_key, next_step_key, self_service, source}` (`self_service` is `true` for code 54, and drives the replacement quick-reply offer, D5-B D7) |
| `disputes.create_claim(tx_ids, answers, priority_flags, token)` | ✓ | ✓ | — | `ActionResult{case_ids}`: one `bank.complaints` row per transaction (D4-B D14–D16); `answers` is a sorted `list[str]` of `"<question_id>=<yes\|no>"`. `priority_flags` is a sorted `list[str]`, built in code and bound by the confirmation token like `answers` (D7-B SA1); the row's `priority` is `'High'` when the list is non-empty, `NULL` otherwise |
| `disputes.get_priority_signals()` | — | — | — | `PrioritySignals{repeat_complainer: bool, open_critical: bool}`, customer-scoped from `ToolContext` (R1, D7-B D5/D9) |
| `handoff.create(packet)` | ✓ (internal) | — | — | the **persisted** handoff id (`UUID`): the packet's own on insert, or the id of the handoff already open for the conversation, which the customer is attached to (D4-A D32). Implemented by `HandoffTools.create(packet) -> UUID` (`conversation/tools/handoff.py`), injected as `config["configurable"]["handoff_tools"]` |
| `reference.get_fx_rate(source, target)` | — | — | — | `FxRate{source, target, rate, as_of}`: the latest `daily_exchange_rates` row for the pair (`exchange_rate` column); `NotFound` if the pair has none. Reference data, so there is no customer filter (D2-B D3) |

`BlockOrigin.kind` is `customer_lock | customer_block | bank_side | none`; `reason` is `past_due | fraud | customer_status | bank_status | None` (non-`None` only when `kind = bank_side`). `BlockReason` (the `reason` argument of `cards.block_card`) is `Literal["lost_or_stolen", "suspected_fraud"]`. `address_ref` (the argument of `cards.order_replacement`) is either `"on_file"` (the address in `bank.customers`) or a PII-vault token for an address the customer typed (`⟨ADDR_n⟩`, `01` §5 token style, D12); the raw address never reaches the LLM, state or checkpoint.

`ActionResult` (`app/core/actions.py`, frozen, `extra="forbid"`) = `{tool: str, status: "applied", verified: bool (REQUIRED, no default, R3), readback: dict[str, ReadbackValue], audit_event_id: UUID | None, tracking_id: str | None}`. The flow may report success **only** when `verified = true`. `audit_event_id` is the `readback` audit event's id (`model_copy`, D3-A D14/D16); it stays `None` when that post-write audit insert fails, which never turns a verified write into a failure (D3-A D15). `ActionResult.case_ids: list[str] | None` (default `None`) is set only by `disputes.create_claim` (D4-B D16), with `readback = {"status": "Open", "count": n, "at": datetime}`; `verified` is true only when a re-read of every row matches its transaction (amount, currency, product, `transaction_id`, `origin='app'`) and belongs to the session's customer.

`ActionResult.readback` keys per write (FakeBank now, Postgres D3-A3; D2-B D7): `lock_card` → `{"locked": True, "at": datetime}`; `unlock_card` → `{"locked": False, "at": datetime}`; `block_card` → `{"status": "Blocked", "at": datetime}`; `order_replacement` → `{"status": "ordered", "at": datetime}`, with `tracking_id` set alongside. `verified = true` only when a re-read after the write matches; `at` fills `action_done`'s `{time}` (`HH:MM` in `BANK_TZ`, D2-B D17).

Two layers implement the write tools (spec `docs/specs/d2-k-write-contracts.md` D3–D5, amended by `docs/specs/d3-a-guardrails-write-path.md` D3, D10, D11, D16): `BankWriteTools` (`app/domains/conversation/tools/write.py`) is the raw, session-bound facade bound to one `ToolContext`; it never sees a token or an intent, and each write method takes only the write's own arguments plus a keyword-only `idempotency_key: str` (`get_block_origin` takes none). `ConfirmedWriteTools` (`app/domains/conversation/tools/executor.py`) is the one R2 enforcement point. Its `issue_plan(steps: Sequence[PlanStep], intent: Intent) -> ConfirmationPlan` and `get_block_origin(card_id, intent: Intent) -> BlockOrigin` both gate on `policies/tools.yaml`'s `allowed_intents` before anything else runs (D3): a tool not allowed for the given intent records a best-effort `rule_hit{rule_id: "tool_not_allowed"}` and raises `PolicyDenied("tool_not_allowed")` before the confirmation store or the raw call is ever touched. Each of the four writes then runs in this order (D16): (1) a `tool_call` audit event, fail closed — an event that can't be recorded means the raw call never runs, surfaced as `ToolUnavailable`, before `consume_step`; (2) the step-up check, raising `StepUpRequired` without consuming the token if step-up is needed and missing (`rule_hit` and `tool_result` recorded best effort); (3) `consume_step(token_id, tool, args)` on the `ConfirmationStore`, recording `confirmation_used{step_index}` on success or `tool_result{error}` and re-raising untouched on `ConfirmationRequired`; (4) the raw call, keyed `<token_id>:<step_index>` (`step_index` as returned by `consume_step`, D11); (5) on a raised exception or a returned but unverified `ActionResult`, a best-effort `tool_result{error}` then `cancel(token_id)`, re-raising the error or returning the unverified result unchanged (ADR-027: the plan is deleted on the first failed or unverified step); on a verified result, a `readback` event (the read-back made JSON-safe, never raw) then `tool_result`, whose id becomes `ActionResult.audit_event_id`. The graph reaches writes only through `config["configurable"]["bank_write_tools"]`, which holds a `ConfirmedWriteTools`, never a raw `BankWriteTools` (R6). The step-up rule (which tools require it — e.g. `unlock_card` always, `order_replacement` when the address changed) is injected, not hard-coded: the source of truth is `policies/tools.yaml` (D3-A1).

The idempotency key for a confirmed step is `<token_id>:<step_index>`, with `step_index` as returned by `consume_step` (0-based). `card_controls`, `card_status_history` and `card_replacements` each hold a unique nullable `idempotency_key` column (migration `0003`, D3-A3, `03` §6), and so does `bank.complaints` (migration `0005`, D4-B D15, keyed per row `<token_id>:<step_index>:<tx_id>`): a raw write whose key already exists re-reads and returns the existing record instead of writing a second one, and a unique-violation race on the same key is handled the same way — replaying a confirmed step is never a double write. FakeBank keeps an equivalent key → `ActionResult` map with the same replay behavior.

`TxFilter` = `{date_from, date_to, merchant_names[], amount_min, amount_max, currency, status[], card_id}`. Dates are resolved by code and validated (`date_from <= date_to`, window at most 366 days when both are set).

`TxView.occurred_at` is an aware UTC datetime; display in `BANK_TZ` of the customer's country (D1-A D1).

## 2. NLU output (`understand` node)

```json
{
  "language": "es | pt | mixed",
  "intents": ["card_block", "decline_explain"],
  "status": "clear | ambiguous | out_of_scope | out_of_market | injection_suspected",
  "slots": {
    "card_hint": "credit | debit | last4:6475 | null",
    "block_kind": "temporary_lock | permanent_block | null",
    "date_expression": "el martes pasado",
    "merchant_text": "super ahorro",
    "amount": 350.0,
    "amount_approx": true,
    "currency": "COP | ARS | USD | MXN | null",
    "pending_answer": "affirm | deny | <slot value> | null",
    "topic": "loans | accounts | investments | insurance | transfers | pix_boleto | other | null"
  },
  "clarification": "lock_vs_block | which_card | which_transaction | null"
}
```

## 3. HTTP API (`/api/v1`) and SSE

| Method & path | Role | Purpose |
|---|---|---|
| `GET /api/v1/health` | public | Liveness: `HealthResponse{status, db, redis}`, `200` when DB and Redis are both up, `503` otherwise (D15) |
| `POST /auth/login` · `POST /auth/logout` · `POST /auth/refresh` · `GET /auth/me` | any | Session (httpOnly cookie + CSRF) |
| `POST /auth/otp/verify` | customer | Step-up: `{code}` (checks the fixed demo code in constant time; no challenge or delivery). On success it re-issues the `session` and `csrf_token` cookies with a fresh `step_up_at`, exactly as `/auth/refresh` does (the old token stays valid until its own `exp`), and returns `MeResponse`; the frontend then runs the next turn with `TurnInput.resume="step_up"`. `401 otp_invalid` on a wrong code; `429 too_many_attempts` on `rl:otp:<account_id>`'s limit (D3-A D4), checked before the code so it wins even when the code is right |
| `POST /conversations` | customer | Start a conversation: `{language?: es \| pt, welcome: bool = false}` → `{conversation_id, welcome: {text} \| null}`. `welcome` is non-null only when the request had `welcome: true`; the text is Cardy's greeting, filled in code (R4), persisted as the conversation's first `bot` message and shown unmasked for display only |
| `GET /me/cards` | customer | `[CardView{card_id, kind: credit \| debit, last4, mask, status, locked}]`, every status. Read-only; the customer comes from the session (R1) |
| `GET /me/cards/{card_id}` | customer | `CardDetailsView` (`CardView` + `currency`, `expiration_date(_display)`, `credit_limit(_display)`, `current_balance(_display)`, `available_credit(_display)`, `days_past_due`; the credit fields are `null` for debit). `404 not_found` for another customer's card and for an unknown one (same body) |
| `GET /me/transactions?card_id=&date_from=&date_to=&cursor=` | customer | `TxPage{items: [TxRow{tx_id, card_id, card_mask, occurred_at, date_display, amount, currency, amount_display, merchant_name, type, status}], next_cursor}`, at most 20 per page, newest first, opaque keyset cursor. `404 not_found` on a foreign or unknown `card_id`; `422 invalid_filter` on a bad date window, `422 invalid_cursor` on a bad cursor |
| `POST /conversations/{id}/messages` | customer | Send a turn: `{text}` (1–2000 chars), `{resume: "step_up"}` or `{selection: {tx_ids}}` (1–10 unique ids picked from the pending `ui.transaction_list`, D4-B D7), exactly one set → `202 {turn_id}`; `422` otherwise. A `selection` is checked before any turn is scheduled: the checkpoint must be paused at `awaiting_slot == "transactions"`, every id must be in the offered list, and, when the offer was single-pick (`multi: false`, D5-B D3), exactly one id, else `409 selection_invalid`. `resume` and `selection` are not persisted as customer messages. `resume` is not persisted as a customer message; output arrives on the stream. `409 turn_in_progress` while another turn runs; `409 conversation_closed` once the customer said goodbye (start a new conversation); `429 turn_cap_reached` in bot mode once the conversation or account/day cap is reached (checked after the `conversation_closed`/`selection_invalid` gates and before `start_turn`, so it comes before `409 turn_in_progress`; no turn scheduled; D6-A D11) |
| `POST /conversations/{id}/confirmations/{token_id}` | customer | Button confirm/cancel (equivalent to typing "sí"/"no"); `{decision: confirm \| cancel}` → `202 {turn_id}`. Before any turn is scheduled, checks that `token_id` is an open plan owned by this customer and conversation (`RedisConfirmationStore.is_open`) *and* is the token the graph's last checkpoint is actually waiting on; either failing is `409 confirmation_invalid`, no turn scheduled. `429 turn_cap_reached` (checked after `confirmation_invalid`, before `turn_in_progress`) and `409 turn_in_progress` work as on `/messages` |
| `GET /conversations/{id}/stream` | customer | SSE (customer-only per R13; the agent stream is `GET /staff/conversations/{id}/stream`, below) |
| `POST /auth/staff/login` | public | Staff login `{username, password}` → `StaffMeResponse{role: agent \| admin, username, display_name, queue: Queue \| null}` plus the `session` and `csrf_token` cookies. `401 invalid_credentials`, `429 too_many_attempts`. CSRF-exempt like `/auth/login` |
| `GET /staff/me` · `POST /staff/logout` | agent, admin | `StaffMeResponse`; logout is `204` and revokes the `jti` |
| `GET /staff/handoffs?queue=&status=` | agent, admin | `[HandoffSummary]`, newest first; `status` defaults to `queued,claimed`, an unknown value is `422` |
| `GET /staff/handoffs/stream?queue=` | agent, admin | SSE: `handoff_created {HandoffSummary}`, `handoff_updated {HandoffSummary}`, `: ping` every 15 s |
| `GET /staff/handoffs/{id}` | agent, admin | `HandoffDetail{summary, packet}`; `404 not_found` |
| `POST /staff/handoffs/{id}/claim` | agent, admin | `HandoffDetail`, idempotent for the same agent. `409 already_claimed` (another agent), `409 handoff_closed` (returned) |
| `POST /staff/handoffs/{id}/return` | agent, admin | `HandoffSummary` (`status = returned`). Only the claimant: `409 not_claimant`. Flips the conversation to bot mode first, then closes the handoff; `409 turn_in_progress` while a turn holds the lock, with nothing changed |
| `GET /staff/conversations/{id}/messages` | agent, admin | `[TranscriptMessage{role, text, created_at}]`, oldest first |
| `POST /staff/conversations/{id}/messages` | agent, admin | `{text: 1..2000}` → `201 {message_id}`, relayed on `conv:<id>` |
| `GET /staff/conversations/{id}/stream` | agent, admin | SSE on `conv:<id>`, same framing as the customer stream |
| `POST /staff/actions/{tool}` | agent | One-click action through the policy engine (Stretch) |
| `GET /staff/conversations?language=&country=&intent=&outcome=&escalation=&date_from=&date_to=&limit=&offset=` | agent, admin | Traceability console list: `ConversationPage{total, items: [ConversationSummary]}`, newest first, filters ANDed, `limit` 1-200 (default 50) and `offset`, `total` counts every match. `outcome=handoff` matches every `handoff:<queue>`; `escalation` is `none`, `any` or a queue name; `date_from`/`date_to` are inclusive UTC dates on `app.conversations.started_at`. An invalid filter value is `422` |
| `GET /staff/conversations/{id}/timeline` | agent, admin | `ConversationTimeline{conversation: ConversationSummary, turns: [TurnTimeline]}`: per turn the masked customer and bot text, the NLU result, rule hits, tool calls, sources, policy version, LLM calls, latency, cost and a Langfuse link. Read-only, masked data only. `404 not_found` if the conversation doesn't exist |
| `GET /staff/system` | agent, admin | `SystemInfo{git_sha, app_env, llm_provider, llm_disabled, steps: [{step, model_id, temperature, prompt_version}], policy_hash, policies: [{file, sha256}]}`, read from code and config |
| `GET /staff/personas` · `GET /staff/personas/{persona_id}/credentials` | admin | Persona catalog `[PersonaEntry{customer_id, split, traits, notes}]` and credential lookup `PersonaCredentials{customer_id, document_type, document_number, password}`. `persona_id` is the catalog persona's id; the path doesn't use the name `customer_id` because of the R1 route guard (D7-A D22, amended). The credentials response carries `Cache-Control: no-store`; `404 not_found` when the id isn't in the catalog |
| `POST /admin/demo/reset` | admin | Restore from the golden DB → `{status: "reset", duration_ms}` |
| `POST /test-idp/sessions` | eval only (router included under `/api/v1` only when `APP_ENV=eval`) | Mint a session for any customer |

**Traceability console shapes (D7-A D23, supersedes the D7-B D11 proposal):** `app/domains/audit/schemas.py`, generated into the frontend client by `make client`.

```python
class ConversationSummary(BaseModel):
    conversation_id: UUID; created_at: datetime          # from app.conversations.started_at
    language: Literal["es","pt"] | None; country: Literal["MX","CO","AR"] | None
    intents: list[str]                                   # distinct, first-seen order
    outcome: str | None                                  # resolved | clarified | abstained | handoff:<queue>
    escalated: bool; queue: str | None; mode: str; status: str; turns: int

class ConversationPage(BaseModel):  total: int; items: list[ConversationSummary]

class LLMCallView(BaseModel):       # no input_text / output_json (D7-A D17)
    step: str; model_id: str; prompt_version: str; temperature: float | None; attempt: int
    status: str; latency_ms: float; input_tokens: int | None; output_tokens: int | None; cost_usd: float | None

class TimelineEvent(BaseModel):     # one audit.audit_events row, payload already masked
    at: datetime; type: AuditType; actor: str; payload: dict; sources: list[str]

class TurnTimeline(BaseModel):
    turn_id: UUID; started_at: datetime; customer_text_masked: str | None; bot_text_masked: str | None
    nlu: dict | None                # the turn's nlu_result payload
    rules: list[TimelineEvent]; tools: list[TimelineEvent]; events: list[TimelineEvent]
    sources: list[str]; policy_version: str | None; llm_calls: list[LLMCallView]
    latency_ms: float | None; cost_usd: float | None; langfuse_url: str | None

class ConversationTimeline(BaseModel):  conversation: ConversationSummary; turns: list[TurnTimeline]
```

`GET /staff/conversations` has no `{id}` and checks the agent or admin role only; `GET /staff/conversations/{id}/timeline` uses `get_any_conversation` (§"Auth" below). Both return only the masked audit data already used elsewhere in this console (no chain-of-thought, no raw PII). The system metadata (git SHA, model per step, prompt versions, policy hash) comes from `GET /staff/system`, not from the timeline.

`TurnInput` gains `resume: Literal["step_up"] | None` (D2-B D1, amends D2-K D17): `None` on every typed or button turn, and `"step_up"` for the one that follows a successful `/auth/otp/verify`. The graph checks it right after `load_session`, before `confirmation` or a fresh `understand` call would otherwise run, and resumes the flow paused at `pending.awaiting_slot == "otp"` only when that pause is actually open; with no matching pause, or the step-up gate still invalid, nothing executes and the turn replies with the `otp_required` template again (no LLM call either way). In the sandbox, `/otp <code>` calls the fake step-up gate's `verify(code)` directly and, on success, runs the resume turn the same way.

**Auth (ADR-025):** the Role column is enforced by router-level dependencies (`Depends(require_role(...))`), not per route. Every `/conversations/{id}/…` route also depends on `get_owned_conversation`. Errors: `401 session_expired` (no or expired session), `403 forbidden_role`, `404 not_found` (the conversation doesn't exist *or* belongs to another customer). **Resume (D6-A D12):** a `401 session_expired` on `/messages` or `/confirmations` changes nothing server-side (checkpoint and `pending`, the plan in Redis, the turn lock, `app.messages`, `audit.*`). The client keeps the rejected request and re-sends it after re-login; the same customer proceeds, another customer gets `404` and the plan stays open. There is no resume endpoint. Only `/auth/login`, `/auth/refresh` and the health check are public.

**Login and `/me` (D2-A, ADR-008 amended):** `POST /auth/login` is customer-only. It takes `{document_type: DNI | CC | CE | Pasaporte, document_number, password}` and returns `MeResponse` plus the `session` (httpOnly) and `csrf_token` cookies. Errors: `401 invalid_credentials` (unknown identifier and wrong password look the same), `429 too_many_attempts` (5 failures in 15 min per HMAC `login_key`; the counter is not reset by a successful login). `POST /auth/refresh` has no role dependency but requires the session cookie and CSRF. It re-issues both cookies and returns `MeResponse`, and the old token is not revoked (it expires at its own `exp`). `GET /auth/me` returns `MeResponse{role: "customer", login_hint, display_name (first name only), country, customer_status}`. `login_hint` is masked (`"DNI ••••462"`, last 3 characters, always 4 bullets). No full document number is ever returned or logged. **Staff (D4-A, ADR-008 amended):** seeded staff accounts log in with `POST /auth/staff/login {username, password}` and get the same cookie + CSRF session with role `agent` or `admin` and no `customer_id`. The `/staff/*` routers require `agent` or `admin`, `/admin/*` requires `admin`. `/staff/*` routers require `agent` or `admin` plus CSRF; a customer session on `/staff/*` or `/admin/*`, or a staff session on `/conversations/*`, `/auth/me` or `/auth/refresh`, gets `403 forbidden_role` (the refresh rule is D4-B D5). Every `/staff/conversations/{id}/…` route depends on `get_claimed_conversation`: the conversation must have an open handoff claimed by the caller, otherwise `404 not_found`. **One exception (D7-A D16):** `GET /staff/conversations/{id}/timeline` depends on `get_any_conversation` instead. It needs no claim, is read-only and is open to `agent` and `admin`; the conversation must still exist, else `404 not_found`. Every other `/staff/conversations/{id}/…` route keeps `get_claimed_conversation`. The timeline's `created_at` is filled from `app.conversations.started_at` (the table has no `created_at`). Shapes (`app/domains/handoff/schemas.py`, frozen): `HandoffSummary{handoff_id, reference, conversation_id, queue, priority: high | normal, reason: HandoffReason, status: queued | claimed | returned, language: es | pt, created_at, claimed_by: str | null}` (`claimed_by` is the agent's `display_name`); `HandoffDetail{summary: HandoffSummary, packet: HandoffPacket}`. `reference` is `"HO-"` + the first 8 hex digits of `handoff_id`, uppercased.

**SSE events:** `status {step}` · `message {role: bot | customer | agent | system, text, sources[], agent_display_name?}` · `ui {kind: card_picker | confirm | transaction_list | otp_required | handoff_banner | quick_replies | conversation_closed, payload}` · `mode {bot | human, agent_display_name}` · `error {code}` · `done {turn_id}` · `debug {language, status, intents, slots, route, tools_called, degraded}` (**only when `APP_ENV != prod`**; the sandbox `DebugInfo` fields, used by `make chat-api`).

The `ui.confirm` payload is `{token_id, steps: [{tool, summary_key, facts}]}` (`ConfirmPayload`, `app/domains/conversation/ui.py`); the `ui.otp_required` payload is `{tool}` (`OtpRequiredPayload`), naming the action waiting on step-up. `ui.transaction_list` is `{options: [{tx_id, label}], multi: bool}`, each label `merchant · money · day-first date · •••• last4`, built in code (R4). The `•••• last4` part is left out when the row's product is not a card, for example a savings account (D7-B D19); `multi` is `true` for `unrecognized_charge`'s multi-select and `false` for `decline_explain`'s single-pick offer (D5-B D3) -- the frontend renders radio inputs instead of checkboxes when it is `false`, and the selection gate (above) accepts exactly one id. `ui.handoff_banner` is `{handoff_id, reference, queue, queue_label, case_ids}` (D4-A D12, D4-B D13).

**Handoff deltas (D4-A):** `mode` is emitted at handoff (`human`, `null`), at claim (`human`, the agent's `display_name`) and at return (`bot`, `null`). `message.role = customer` is published only in human mode, as the relay for the agent, and the customer UI ignores its own echo; `agent` carries `agent_display_name`; `system` is the fixed `back_with_cardy` text at return. In human mode a customer turn emits `status`, the `customer` echo and `done`, with no bot `message` and no LLM call. `ui.handoff_banner` is `{handoff_id, reference, queue, queue_label, case_ids}`, with `queue_label` localized to the conversation language, all built in code; `case_ids` lists the claims the bot opened in the conversation before the handoff (empty otherwise). `ui.quick_replies.slot` is `block_kind | abstain | next_step`; for `abstain` the options are the closest action's label and the human offer, and clicking one sends its label as text. `next_step` (D5-B D7) is `decline_explain`'s own self-service offer (code 54 only): one option, the localized replacement action; tapping it sends that label as text, so NLU routes it as `replacement_request` on its own turn.

## 4. Handoff packet (D3.5)

```json
{
  "handoff_id": "uuid",
  "conversation_id": "uuid",
  "queue": "fraudes",
  "priority": "high",
  "reason": "suspected_fraud",
  "language": "es",
  "sentiment": null,
  "request": "Cliente no reconoce 3 compras con su tarjeta de crédito •••• 6475 y pide bloquearla.",
  "verified_facts": [
    {"fact": "card_status", "value": "Blocked", "source": "bank.products:PRD-123 (read-back 2026-…)"},
    {"fact": "unrecognized_transactions", "value": ["TX-1", "TX-2", "TX-3"], "source": "bank.transactions"}
  ],
  "actions_taken": [
    {"tool": "cards.block_card", "result": "applied", "verified": true, "audit_event_id": "…", "at": "…"},
    {"tool": "disputes.create_claim", "result": "applied", "verified": true, "case_ids": ["CLM-…"]}
  ],
  "evidence": [{"type": "transaction", "ref": "TX-1", "fraud_score": 72}],
  "open_questions": ["¿El cliente tiene la tarjeta física en su poder?"],
  "escalation_rules_hit": ["suspected_fraud"],
  "policy_version": "sha256:…",
  "created_at": "…"
}
```

`sentiment` is always `null` (no sentiment model). `reason` is `human_request | clarification_exhausted | legal_regulator | customer_not_active | bank_side_block | action_unverified | unauthorized_access | suspected_fraud | tool_failure | llm_unavailable | priority_claim` (`tool_failure`/`llm_unavailable` D6-A D8; `priority_claim` D7-B D5-D9). `verified_facts[].fact` is `card_locked | card_unlocked | card_status | replacement_ordered | claim_filed`, one per verified `ActionResult`, with `source` `"audit:<audit_event_id>"` (or `"<tool> read-back"`). `open_questions` are rendered in code from `rules.<reason>.open_questions` keys. The customer-facing case `reference` (`HO-XXXXXXXX`) is derived from `handoff_id` and is not a packet field; it appears in `HandoffSummary` and the banner. `request` is the only LLM-written field. It is generated from masked facts and length-capped. Every other field is assembled in code. Raw transcripts are never included; the agent opens the conversation separately (role-gated).

Pydantic models live in `app/domains/handoff/schemas.py` (frozen, `extra="forbid"`). The `handoff` node builds the packet in code from the verified `ActionResult`s (D4-A D10); a flow that hands off (the fraud path, D4-B D9/D10) only sets `escalation_reason`, `handoff_queue`, `handoff_evidence` (`HandoffEvidence{type: "transaction", ref, fraud_score: Decimal | null}`) and `handoff_open_questions` (code-filled texts in the packet `language`, appended after the rule's own) in its state update, and the graph routes through `handoff_summary → handoff`. `actions_taken[].case_ids` is set only for `disputes.create_claim`; `claim_filed`'s `value` is that case-id list.

## 5. Policy YAML (`policies/`)

Every file starts with a provenance header and is validated at startup by `app/domains/policy/registry.py` (`load_policies`/`get_policies`, D3-A1): a file whose `provenance` isn't `team-generated-synthetic`, or that has no `version`, stops startup naming the file. The combined hash — `"sha256:" + hex(sha256(concat over sorted file names of name + "\0" + bytes + "\0"))`, one update per `policies/*.yaml` file in sorted-filename order over its raw bytes — is logged on every decision (`policy.loaded hash=…` at startup) and carried as `ToolContext.policy_version` and every audit event's `policy_version`.

```yaml
# policies/decline_codes.yaml
provenance: team-generated-synthetic   # REQUIRED on every policy file
version: 1
codes:
  "51": {cause_key: insufficient_funds, next_step_key: pay_or_use_other_card, self_service: false}
  "14": {cause_key: invalid_card_number, next_step_key: check_card_number, self_service: false}
  "05": {cause_key: do_not_honor, next_step_key: contact_or_retry, self_service: false}
  "54": {cause_key: expired_card, next_step_key: offer_replacement, self_service: true}

# policies/tools.yaml (D2-B D2; D3-A1 v1, final): per-tool confirmation/step-up flags and intent allowlist
version: 1
step_up_window_minutes: 5   # SessionStepUpGate's window (D3-A D4); no window literal exists in Python
tools:
  cards.lock_card:         {requires_confirmation: true,  step_up: never,                allowed_intents: [card_block]}
  cards.unlock_card:       {requires_confirmation: true,  step_up: always,               allowed_intents: [card_unlock]}
  cards.block_card:        {requires_confirmation: true,  step_up: never,                allowed_intents: [card_block, unrecognized_charge]}
  cards.order_replacement: {requires_confirmation: true,  step_up: when_address_changed, allowed_intents: [replacement_request]}
  cards.get_block_origin:  {requires_confirmation: false, step_up: never,                allowed_intents: [card_unlock, replacement_request]}
  disputes.create_claim:   {requires_confirmation: true,  step_up: never,                allowed_intents: [unrecognized_charge]}   # D4-B D18

# policies/transaction_states.yaml (D7-B D4): pending/reversed cause, next step and hold days
provenance: team-generated-synthetic
version: 1
pending:  {hold_days: 3, cause_key: pending_hold, next_step_key: wait_until_date, overdue_next_step_key: offer_human}
reversed: {cause_key: reversed_charge, next_step_key: no_action_needed}

# policies/disputes.yaml (v2, D4-B D8, D12; priority block D7-B D5/D9): compromise rule, candidates, questions, handoff target
candidate_statuses: [Approved, Pending, Reversed]
compromise: {min_picked: 2, fraud_score_gt: 30, block_reason: suspected_fraud}
possession_question: card_in_possession
questions: [card_in_possession, contacted_merchant]
handoff: {queue: fraudes, priority: high, reason: suspected_fraud}
priority:
  amount_threshold: {USD: "5000", COP: "20000000", ARS: "1800000"}
  open_statuses: [Open, In Process, Escalated]
  handoff: {queue: reclamos, priority: high, reason: priority_claim}

# policies/min_payment.yaml (D2-B D5): synthetic formula, no overdue term
min_payment: {percent_of_balance: "0.05", floors: {USD: "10", COP: "40000", ARS: "5000"}}
due_date:    {due_day_of_month: 10}

# policies/escalation.yaml v6 (D4-A D3-D6; D6-A D8 adds tool_failure, llm_unavailable; D7-B D5-D9 adds priority_claim; ADR-032 adds degraded_handoff_intents, then decline_explain)
customer_not_active: {statuses: [Closed, Suspended, Inactive], allowed: [lock_card, block_card]}
bank_side_queues:    {past_due: cobranza, fraud: fraudes, bank_status: fraudes, customer_status: atencion}
rules:               # queue null = resolved from context (bank_side_queues, human_request_queues)
  human_request:           {queue: null,     priority: normal}
  clarification_exhausted: {queue: atencion, priority: normal}
  legal_regulator:         {queue: reclamos, priority: high}
  customer_not_active:     {queue: atencion, priority: normal}
  bank_side_block:         {queue: null,     priority: high}
  action_unverified:       {queue: atencion, priority: high}
  unauthorized_access:     {queue: atencion, priority: high}
  suspected_fraud:         {queue: fraudes,  priority: high, open_questions: [card_in_possession]}
  tool_failure:            {queue: null,     priority: normal}   # D6-A D8, queue resolved as human_request
  llm_unavailable:         {queue: null,     priority: normal}   # D6-A D8
  priority_claim:          {queue: reclamos, priority: high}     # D7-B D5-D9
human_request_queues: {default: atencion, by_flow: {unrecognized_charge: fraudes}}
degraded_handoff_intents: [transaction_search, general_question, decline_explain]   # ADR-032: degraded turns (LLM failed or LLM_DISABLED) on these intents hand off as llm_unavailable
unauthorized_access:  {attempts_before_handoff: 2}
legal_keywords:      {es: [demanda, abogado, condusef, superfinanciera, bcra, ...], pt: [processo, advogado, procon, "banco central", ...]}

# policies/scope.yaml (D4-A D8): one entry per Topic literal
topics:
  <Topic>: {kind: out_of_market | out_of_scope, reason_key, closest_intents: [Intent], human_queue: Queue}
```

Other files: `tools.yaml` (D2-B, extended by D3-A1), `escalation.yaml`, `disputes.yaml`, `min_payment.yaml` and `transaction_states.yaml` (D7-B D4) are shown above. `scope.yaml` (shown above; out-of-scope and out-of-market topics → `kind`, `reason_key`, `closest_intents[]`, `human_queue`; Pix, boleto and CPF are `kind: out_of_market`, ADR-026), `card_select.yaml` (eligible statuses for card selection), and the Stretch files (limits bounds, benefits catalog, retention offers).

## 6. Audit event

```json
{
  "id": "uuid", "at": "…", "conversation_id": "uuid", "turn_id": "uuid",
  "actor": "bot | customer | agent:<id> | system",
  "type": "nlu_result | rule_hit | tool_call | tool_result | confirmation_issued | confirmation_used | readback | access_denied | handoff | reply_sent | error",
  "payload": {"…masked…"},
  "sources": ["bank.products:PRD-123", "policy:decline_codes@sha256:…"],
  "policy_version": "sha256:…",
  "model": {"step": "compose", "model_id": "…", "prompt_version": "compose@v3"},
  "trace_id": "otel trace id", "langfuse_trace_id": "…"
}
```

A `tool_result` for a failed tool attempt carries `{tool, error, attempt}` (1-based; D6-A D5), so retries are countable per tool. LLM attempts are counted in `audit.llm_calls.attempt`.

`reply_sent` payload adds two keys. `grounding: {outcome: ok | regenerated | template}` is the worst compose outcome of the turn (`template` > `regenerated` > `ok`) and is absent when `compose` didn't run. `fact_values: [str]` lists, deduplicated in order, every value code wrote into the turn's reply (masked card numbers, money, dates, labels; never raw PII and never `customer_name`); the eval `grounding` check reads it.

`reply_sent` payload also carries `degraded: bool`, always present: `true` when the turn ran on the no-LLM path (the trained classifier and fixed templates, ADR-032). The same per-turn value is set on the turn's OTel span as the attribute `cardy.degraded`. `nlu_result` payload carries `source: "llm" | "classifier"`. When the source is `classifier` it also carries `classifier_version` and `label_set_version`, so every degraded decision names the model that made it.

`reply_sent` payload also carries `segments`, always present: one entry per real intent the turn worked on, in order. A turn that worked on no real intent has `segments: []`. A turn relayed to an agent writes no `reply_sent`, so it has no segments.

```json
"segments": [{"intent": "card_block", "route": "card_block", "status": "awaiting", "awaiting_slot": "confirmation"}]
```

- `intent` is a non-management member of `Intent`. On a resume turn (card pick, confirmation, OTP, selection) it is the paused flow's intent.
- `route` is the branch node that served it, or `handoff_summary`.
- `status` is one of `resolved`, `awaiting`, `handoff`, `abstained`, `cancelled`. On a write flow that performs a write, `resolved` is written only on the turn whose `ActionResult.verified` read-back succeeded. Endings that need no write (`already_in_state` in `card_block`, `not_blocked` in `card_unlock`) are `resolved` without one.
- `awaiting_slot` is present only when `status` is `awaiting`: the value of `pending.awaiting_slot` at the end of the turn (`confirmation`, `otp`, or a flow's own slot such as `card_id`). When a flow asks without pausing, code sets the slot name.
- `bot_offered: true` is present only on a segment whose flow the bot offered, not the customer (the replacement offer after a permanent block or after `card_unlock`'s `block_permanent_no_undo` answer). It is absent otherwise.

- A turn that `route` sends straight to `handoff_summary` writes one `handoff` segment per non-management intent in its NLU result, in order, with `route = handoff_summary`. The degraded queue-head handoff (head intent in `degraded_handoff_intents`) writes one `handoff` segment for the head intent only.
- An `unsupported` turn flagged `injection_suspected` writes no segment.
- When `compose` fails after the flow ran and the turn hands off, an `awaiting` segment and any explicitly marked segment keep their status. Only a read-flow segment whose `resolved` depended on the composed answer becomes `handoff`.

The analytics worker reads `segments` to build `analytics.interaction_intents` (`03` §6).

## 7. Confirmation token

Issued by `policy` (`app/domains/policy/confirmation.py`) when a flow reaches one or more side-effecting steps. Every token is a **plan** (ADR-027): an ordered list of steps, where a single action is a plan of one. The `ConfirmationStore` protocol, bound to one customer + conversation at construction:

- `issue(steps) -> ConfirmationPlan{token_id, steps, expires_at}`
- `consume_step(token_id, tool, args) -> int` — checks the step at the cursor, advances it atomically, and returns the consumed step's 0-based `step_index`. Raises `ConfirmationRequired` with reason `unknown_or_expired` (the key is absent: never issued, expired or already fully used), `step_mismatch` (the tool or args hash differs from the step at the cursor) or `wrong_owner` (another customer or conversation)
- `cancel(token_id) -> None` — idempotent; an unknown id is a no-op

`ToolArg` is `str | int | bool | None | list[str]` (the list form carries `create_claim`'s `tx_ids` and `answers`, D4-B D17). `args_hash(tool, args)` is the hex SHA-256 of the canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) of `{"tool": tool, "args": args}`.

Storage is unchanged: it's stored in Redis as `conf:<id>` with value `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor, expires_at}`, TTL 5 minutes. The tool executor rejects a call unless the token exists, belongs to the same session customer, and the call matches the step at `cursor` (tool and args hash). It advances the cursor atomically (a Lua script, replacing a plain `GETDEL`). The key is deleted after the last step, on the first failed or unverified step, or at TTL, so a token can't be reused and steps can't be reordered or added. `ui.confirm` carries `{token_id, steps: [{tool, summary_key, facts}]}`, and the frontend lists every step.

`RedisConfirmationStore` (`app/domains/policy/confirmation_redis.py`, D3-A2) implements the protocol above over `conf:<id>` and adds `async def is_open(self, token_id: str) -> bool`, true only when the key exists and its `customer_id`/`conversation_id` match this store's owner (a plain `GET`, no script). `POST /conversations/{id}/confirmations/{token_id}` (§3, D3-A D7) calls `is_open` together with the checkpointed `confirmation_token_id` before scheduling any turn: either check failing is `409 confirmation_invalid`. The plan is not tied to the session (D3-A D4): it dies at its own TTL regardless of `step_up_at` or session expiry, and the route itself returns `401` once the session has expired, before `is_open` is even called. `InMemoryConfirmationStore` (the sandbox) has no `is_open`.
