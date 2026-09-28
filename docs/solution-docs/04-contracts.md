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
| `cards.get_block_origin(card_id)` | — | — | — | `BlockOrigin{kind: customer_lock/customer_block/bank_side/none, reason}` |
| `cards.lock_card(card_id, token_id)` | ✓ | ✓ | — | `ActionResult` |
| `cards.unlock_card(card_id, token_id)` | ✓ | ✓ | ✓ | `ActionResult` |
| `cards.block_card(card_id, reason, token_id)` | ✓ | ✓ | — | `ActionResult` |
| `cards.order_replacement(card_id, address_ref, token_id)` | ✓ | ✓ | ✓ if address changed | `ActionResult{tracking_id}` |
| `transactions.search(filter: TxFilter)` | — | — | — | `[TxView{tx_id, card_id, occurred_at, amount, currency, amount_usd, type, category, merchant_name, merchant_category, channel, city, country, status, response_code, fraud_score}]`, max 10, newest first |
| `transactions.get(tx_id)` | — | — | — | `TxView` |
| `transactions.explain_decline(tx_id)` | — | — | — | `DeclineExplanation{code, cause_key, next_step_key, source}` |
| `disputes.create_claim(tx_ids, answers, token)` | ✓ | ✓ | — | `ActionResult{case_id, priority_flags}` |
| `handoff.create(queue, reason)` | ✓ (internal) | — | — | `HandoffRef` |
| `reference.get_fx_rate(source, target)` | — | — | — | `FxRate{source, target, rate, as_of}`: the latest `daily_exchange_rates` row for the pair (`exchange_rate` column); `NotFound` if the pair has none. Reference data, so there is no customer filter (D2-B D3) |

`BlockOrigin.kind` is `customer_lock | customer_block | bank_side | none`; `reason` is `past_due | fraud | customer_status | bank_status | None` (non-`None` only when `kind = bank_side`). `BlockReason` (the `reason` argument of `cards.block_card`) is `Literal["lost_or_stolen", "suspected_fraud"]`. `address_ref` (the argument of `cards.order_replacement`) is either `"on_file"` (the address in `bank.customers`) or a PII-vault token for an address the customer typed (`⟨ADDR_n⟩`, `01` §5 token style, D12); the raw address never reaches the LLM, state or checkpoint.

`ActionResult` (`app/core/actions.py`, frozen, `extra="forbid"`) = `{tool: str, status: "applied", verified: bool (REQUIRED, no default, R3), readback: dict[str, ReadbackValue], audit_event_id: UUID | None, tracking_id: str | None}`. The flow may report success **only** when `verified = true`. The `disputes.create_claim` row's `{case_id, priority_flags}` extra fields land with the disputes card (D9).

`ActionResult.readback` keys per write (FakeBank now, Postgres D3-A3; D2-B D7): `lock_card` → `{"locked": True, "at": datetime}`; `unlock_card` → `{"locked": False, "at": datetime}`; `block_card` → `{"status": "Blocked", "at": datetime}`; `order_replacement` → `{"status": "ordered", "at": datetime}`, with `tracking_id` set alongside. `verified = true` only when a re-read after the write matches; `at` fills `action_done`'s `{time}` (`HH:MM` in `BANK_TZ`, D2-B D17).

Two layers implement the write tools (spec `docs/specs/d2-k-write-contracts.md`, Decisions D3–D5): `BankWriteTools` (`app/domains/conversation/tools/write.py`) is the raw, session-bound facade bound to one `ToolContext`; it never sees a token, and each method takes only the write's own arguments (`card_id`, `reason`, `address_ref`). `ConfirmedWriteTools` (`app/domains/conversation/tools/executor.py`) is the one R2 enforcement point: for each write, in order, it (1) checks the step-up rule and raises `StepUpRequired` without consuming the token if step-up is needed and missing, (2) calls `consume_step(token_id, tool, args)` on the `ConfirmationStore`, (3) calls the raw method, and (4) cancels the plan (`cancel(token_id)`) if the raw call raises or returns `verified=False`, re-raising the error or returning the unverified result unchanged. The graph reaches writes only through `config["configurable"]["bank_write_tools"]`, which holds a `ConfirmedWriteTools`, never a raw `BankWriteTools` (R6). The step-up rule (which tools require it — e.g. `unlock_card` always, `order_replacement` when the address changed) is injected, not hard-coded: the source of truth is `policies/tools.yaml` (D3-A1).

The idempotency key for a confirmed step is `<token_id>:<step_index>`, with `step_index` as returned by `consume_step` (0-based). Storage and the replay lookup are D3-A3.

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
| `POST /auth/otp/verify` | customer | Step-up (checks the fixed demo code; no challenge or delivery). On success, the frontend runs the next turn with `TurnInput.resume="step_up"` |
| `POST /conversations` | customer | Start a conversation |
| `POST /conversations/{id}/messages` | customer | Send a turn (`202`; output arrives on the stream) |
| `POST /conversations/{id}/confirmations/{token_id}` | customer | Button confirm/cancel (equivalent to typing "sí"/"no"); maps to `TurnInput.confirmation{token_id, decision: confirm \| cancel}`. A `token_id` that doesn't match the state's `confirmation_token_id` is stale and executes nothing |
| `GET /conversations/{id}/stream` | customer, agent | SSE |
| `GET /staff/handoffs?queue=` · `POST /staff/handoffs/{id}/claim` · `POST /staff/handoffs/{id}/return` | agent | Inbox and live takeover |
| `POST /staff/conversations/{id}/messages` | agent | Agent reply |
| `POST /staff/actions/{tool}` | agent | One-click action through the policy engine |
| `GET /staff/conversations?filters` · `GET /staff/conversations/{id}/timeline` | agent, admin | Traceability console |
| `GET /staff/personas` · `GET /staff/personas/{customer_id}/credentials` | admin | Persona catalog and credential lookup |
| `POST /admin/demo/reset` | admin | Restore from the golden DB |
| `POST /test-idp/sessions` | eval only (router included under `/api/v1` only when `APP_ENV=eval`) | Mint a session for any customer |

`TurnInput` gains `resume: Literal["step_up"] | None` (D2-B D1, amends D2-K D17): `None` on every typed or button turn, and `"step_up"` for the one that follows a successful `/auth/otp/verify`. The graph checks it right after `load_session`, before `confirmation` or a fresh `understand` call would otherwise run, and resumes the flow paused at `pending.awaiting_slot == "otp"` only when that pause is actually open; with no matching pause, or the step-up gate still invalid, nothing executes and the turn replies with the `otp_required` template again (no LLM call either way). In the sandbox, `/otp <code>` calls the fake step-up gate's `verify(code)` directly and, on success, runs the resume turn the same way.

**Auth (ADR-025):** the Role column is enforced by router-level dependencies (`Depends(require_role(...))`), not per route. Every `/conversations/{id}/…` route also depends on `get_owned_conversation`. Errors: `401 session_expired` (no or expired session), `403 forbidden_role`, `404 not_found` (the conversation doesn't exist *or* belongs to another customer). Only `/auth/login`, `/auth/refresh` and the health check are public.

**Login and `/me` (D2-A, ADR-008 amended):** `POST /auth/login` is customer-only. It takes `{document_type: DNI | CC | CE | Pasaporte, document_number, password}` and returns `MeResponse` plus the `session` (httpOnly) and `csrf_token` cookies. Errors: `401 invalid_credentials` (unknown identifier and wrong password look the same), `429 too_many_attempts` (5 failures in 15 min per HMAC `login_key`; the counter is not reset by a successful login). `POST /auth/refresh` has no role dependency but requires the session cookie and CSRF. It re-issues both cookies and returns `MeResponse`, and the old token is not revoked (it expires at its own `exp`). `GET /auth/me` returns `MeResponse{role: "customer", login_hint, display_name (first name only), country, customer_status}`. `login_hint` is masked (`"DNI ••••462"`, last 3 characters, always 4 bullets). No full document number is ever returned or logged. **Staff:** there is no staff login for now. The staff panel is a separate page, and how it and the `/staff/*` routes below are protected is decided on the staff-panel card (D4).

**SSE events:** `status {step}` · `message {role, text, sources[]}` · `ui {kind: card_picker | confirm | transaction_list | otp_required | handoff_banner, payload}` · `mode {bot | human, agent_display_name}` · `error {code}` · `done {turn_id}` · `debug {language, status, intents, slots, route, tools_called}` (**only when `APP_ENV != prod`**; the sandbox `DebugInfo` fields, used by `make chat-api`).

The `ui.confirm` payload is `{token_id, steps: [{tool, summary_key, facts}]}` (`ConfirmPayload`, `app/domains/conversation/ui.py`); the `ui.otp_required` payload is `{tool}` (`OtpRequiredPayload`), naming the action waiting on step-up.

## 4. Handoff packet (D3.5)

```json
{
  "handoff_id": "uuid",
  "conversation_id": "uuid",
  "queue": "fraudes",
  "priority": "high",
  "reason": "suspected_fraud",
  "language": "es",
  "sentiment": "negative",
  "request": "Cliente no reconoce 3 compras con su tarjeta de crédito •••• 6475 y pide bloquearla.",
  "verified_facts": [
    {"fact": "card_status", "value": "Blocked", "source": "bank.products:PRD-123 (read-back 2026-…)"},
    {"fact": "unrecognized_transactions", "value": ["TX-1", "TX-2", "TX-3"], "source": "bank.transactions"}
  ],
  "actions_taken": [
    {"tool": "cards.block_card", "result": "applied", "verified": true, "audit_event_id": "…", "at": "…"},
    {"tool": "disputes.create_claim", "result": "applied", "verified": true, "case_id": "CLM-…"}
  ],
  "evidence": [{"type": "transaction", "ref": "TX-1", "fraud_score": 72}],
  "open_questions": ["¿El cliente tiene la tarjeta física en su poder?"],
  "escalation_rules_hit": ["suspected_fraud"],
  "policy_version": "sha256:…",
  "created_at": "…"
}
```

`request` is the only LLM-written field. It is generated from masked facts and length-capped. Every other field is assembled in code. Raw transcripts are never included; the agent opens the conversation separately (role-gated).

## 5. Policy YAML (`policies/`)

Every file starts with a provenance header and is validated at startup. The combined hash is logged on every decision.

```yaml
# policies/decline_codes.yaml
provenance: team-generated-synthetic   # REQUIRED on every policy file
version: 1
codes:
  "51": {cause_key: insufficient_funds, next_step_key: pay_or_use_other_card, self_service: false}
  "14": {cause_key: invalid_card_number, next_step_key: check_card_number, self_service: false}
  "05": {cause_key: do_not_honor, next_step_key: contact_or_retry, self_service: false}
  "54": {cause_key: expired_card, next_step_key: offer_replacement, self_service: true}

# policies/tools.yaml (D2-B D2, provisional; D3-A1 extends it): per-tool confirmation/step-up flags
tools:
  cards.lock_card:         {requires_confirmation: true, step_up: never}
  cards.unlock_card:       {requires_confirmation: true, step_up: always}
  cards.block_card:        {requires_confirmation: true, step_up: never}
  cards.order_replacement: {requires_confirmation: true, step_up: when_address_changed}
  cards.get_block_origin:  {requires_confirmation: false, step_up: never}

# policies/min_payment.yaml (D2-B D5): synthetic formula, no overdue term
min_payment: {percent_of_balance: "0.05", floors: {USD: "10", COP: "40000", ARS: "5000"}}
due_date:    {due_day_of_month: 10}

# policies/escalation.yaml v1 (D2-B D8, D10; D4-day adds the rest)
customer_not_active: {statuses: [Closed, Suspended, Inactive], allowed: [lock_card, block_card], queue: atencion}
bank_side_queues:    {past_due: cobranza, fraud: fraudes, bank_status: fraudes, customer_status: atencion}
action_queues:       {action_unverified: atencion}   # P7: the queue for an unverified write's handoff
```

Other files: `tools.yaml`, `escalation.yaml` and `min_payment.yaml` are shown above (D2-B). `disputes.yaml` (required questions, amount thresholds per currency), `transaction_states.yaml`, `scope.yaml` (out-of-scope and out-of-market topics → `kind`, `reason_key`, `closest_intents[]`, `human_queue`; Pix, boleto and CPF are `kind: out_of_market`, ADR-026), `card_select.yaml` (eligible statuses for card selection), and the Stretch files (limits bounds, benefits catalog, retention offers).

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

## 7. Confirmation token

Issued by `policy` (`app/domains/policy/confirmation.py`) when a flow reaches one or more side-effecting steps. Every token is a **plan** (ADR-027): an ordered list of steps, where a single action is a plan of one. The `ConfirmationStore` protocol, bound to one customer + conversation at construction:

- `issue(steps) -> ConfirmationPlan{token_id, steps, expires_at}`
- `consume_step(token_id, tool, args) -> int` — checks the step at the cursor, advances it atomically, and returns the consumed step's 0-based `step_index`. Raises `ConfirmationRequired` with reason `unknown_or_expired` (the key is absent: never issued, expired or already fully used), `step_mismatch` (the tool or args hash differs from the step at the cursor) or `wrong_owner` (another customer or conversation)
- `cancel(token_id) -> None` — idempotent; an unknown id is a no-op

`args_hash(tool, args)` is the hex SHA-256 of the canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) of `{"tool": tool, "args": args}`.

Storage is unchanged: it's stored in Redis as `conf:<id>` with value `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor, expires_at}`, TTL 5 minutes. The tool executor rejects a call unless the token exists, belongs to the same session customer, and the call matches the step at `cursor` (tool and args hash). It advances the cursor atomically (a Lua script, replacing a plain `GETDEL`). The key is deleted after the last step, on the first failed or unverified step, or at TTL, so a token can't be reused and steps can't be reordered or added. `ui.confirm` carries `{token_id, steps: [{tool, summary_key, facts}]}`, and the frontend lists every step.
