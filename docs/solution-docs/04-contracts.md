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

Errors are a typed union: `NotFound`, `AccessDenied` (the resource belongs to another customer; audited), `PolicyDenied(reason_code)`, `ConfirmationRequired`, `StepUpRequired`, `Conflict` (e.g., already blocked), `ToolUnavailable`.

### MVP tools

| Tool | Side effect | Confirm | Step-up | Returns |
|---|---|---|---|---|
| `cards.list_cards()` | — | — | — | `[CardSummary{card_id, kind, last4, status, locked}]` |
| `cards.get_card_details(card_id)` | — | — | — | `CardDetails{…, available_credit, source}` |
| `cards.get_block_origin(card_id)` | — | — | — | `BlockOrigin{kind: customer_lock/customer_block/bank_side/none, reason}` |
| `cards.lock_card(card_id, token)` | ✓ | ✓ | — | `ActionResult` |
| `cards.unlock_card(card_id, token)` | ✓ | ✓ | ✓ | `ActionResult` |
| `cards.block_card(card_id, reason, token)` | ✓ | ✓ | — | `ActionResult` |
| `cards.order_replacement(card_id, address_ref, token)` | ✓ | ✓ | ✓ if address changed | `ActionResult{tracking_id}` |
| `transactions.search(filter: TxFilter)` | — | — | — | `[TxView]`, max 10 |
| `transactions.get(tx_id)` | — | — | — | `TxView` |
| `transactions.explain_decline(tx_id)` | — | — | — | `DeclineExplanation{code, cause_key, next_step_key, source}` |
| `disputes.create_claim(tx_ids, answers, token)` | ✓ | ✓ | — | `ActionResult{case_id, priority_flags}` |
| `handoff.create(queue, reason)` | ✓ (internal) | — | — | `HandoffRef` |

`ActionResult` = `{status: "applied", verified: bool, readback: {...}, audit_event_id}`. The flow may report success **only** when `verified = true`.

`TxFilter` = `{date_from, date_to, merchant_ids[], amount_min, amount_max, currency, status[], card_id}`. Dates are resolved by code and validated (max 12-month window **(proposed)**).

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
| `POST /auth/login` · `POST /auth/logout` · `POST /auth/refresh` · `GET /auth/me` | any | Session (httpOnly cookie + CSRF) |
| `POST /auth/otp/verify` | customer | Step-up (checks the fixed demo code; no challenge or delivery) |
| `POST /conversations` | customer | Start a conversation |
| `POST /conversations/{id}/messages` | customer | Send a turn (`202`; output arrives on the stream) |
| `POST /conversations/{id}/confirmations/{token_id}` | customer | Button confirm/cancel (equivalent to typing "sí"/"no") |
| `GET /conversations/{id}/stream` | customer, agent | SSE |
| `GET /staff/handoffs?queue=` · `POST /staff/handoffs/{id}/claim` · `POST /staff/handoffs/{id}/return` | agent | Inbox and live takeover |
| `POST /staff/conversations/{id}/messages` | agent | Agent reply |
| `POST /staff/actions/{tool}` | agent | One-click action through the policy engine |
| `GET /staff/conversations?filters` · `GET /staff/conversations/{id}/timeline` | agent, admin | Traceability console |
| `GET /staff/personas` · `GET /staff/personas/{customer_id}/credentials` | admin | Persona catalog and credential lookup |
| `POST /admin/demo/reset` | admin | Restore from the golden DB |
| `POST /test-idp/sessions` | eval only (disabled in prod) | Mint a session for any customer |

**Auth (ADR-025):** the Role column is enforced by router-level dependencies (`Depends(require_role(...))`), not per route. Every `/conversations/{id}/…` route also depends on `get_owned_conversation`. Errors: `401 session_expired` (no or expired session), `403 forbidden_role`, `404 not_found` (the conversation doesn't exist *or* belongs to another customer). Only `/auth/login`, `/auth/refresh` and the health check are public.

**SSE events:** `status {step}` · `message {role, text, sources[]}` · `ui {kind: card_picker | confirm | transaction_list | otp_required | handoff_banner, payload}` · `mode {bot | human, agent_display_name}` · `error {code}` · `done {turn_id}`.

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
```

Other files: `tools.yaml` (intent → allowed tools, confirmation/step-up flags), `escalation.yaml` (rules and thresholds, queues), `min_payment.yaml` (synthetic formula per currency), `disputes.yaml` (required questions, amount thresholds per currency), `transaction_states.yaml`, `scope.yaml` (out-of-scope and out-of-market topics → `kind`, `reason_key`, `closest_intents[]`, `human_queue`; Pix, boleto and CPF are `kind: out_of_market`, ADR-026), and the Stretch files (limits bounds, benefits catalog, retention offers).

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

Issued by `policy` when a flow reaches one or more side-effecting steps. Every token is a **plan** (ADR-027): an ordered list of steps, where a single action is a plan of one. It's stored in Redis as `conf:<id>` with value `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor, expires_at}`, TTL 5 minutes. The tool executor rejects a call unless the token exists, belongs to the same session customer, and the call matches the step at `cursor` (tool and args hash). It advances the cursor atomically (a Lua script, replacing a plain `GETDEL`). The key is deleted after the last step, on the first failed or unverified step, or at TTL, so a token can't be reused and steps can't be reordered or added. `ui.confirm` carries `{token_id, steps: [{tool, summary_key, facts}]}`, and the frontend lists every step.
