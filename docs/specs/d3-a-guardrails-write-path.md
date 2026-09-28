# Spec: D3-A — G6a guardrails and moving the write path

Card: `07-execution-plan.md` D3, Dev A track, rows A1–A6. Owner: Dev A. Branch `feat/d3-a-guardrails-write-path` → `develop`. The PR touches the tool executor, policy and identity, so it is safety-critical and Dev B reviews it before merge (ADR-018).

## Objective

The API path gets the real write path. Before this card, `runner._run_turn` passes `bank_write_tools=None` (D2-A D13). After it, the block, lock, unlock and replacement flows that D2-B built against FakeBank run through the API against Postgres. Every write goes through `ConfirmedWriteTools`, which enforces the intent allowlist, the step-up gate, a Redis single-use plan token and a verified read-back, and every tool call leaves audit events that carry the policy hash. The card delivers:
- A1: a startup-validated policy registry with a combined hash, and `tools.yaml` with `allowed_intents` and the step-up window
- A2: a Redis `ConfirmationStore` and the `POST /conversations/{id}/confirmations/{token_id}` route
- A3: Postgres write tools with read-back and idempotency keys (migration `0003`)
- A4: `POST /auth/otp/verify`, a session-backed step-up gate, and a `resume` turn on `/messages`
- A5: audit log v0 (`audit.audit_events`, migration `0004`)
- A6: the runner wiring and `make chat-api` support for confirmations and OTP

It serves the "Done when" line of every row A1–A6 and the backend half of the D3 end-of-day test, steps 3–7. The "If behind" cut (idempotency keys and extra audit event types move to D4) is **not** taken for idempotency, by the human's decision (D11).

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **One policy registry, validated at startup.** `policy/registry.py` loads every `policies/*.yaml` in the app lifespan. A file whose `provenance` isn't `team-generated-synthetic`, or that has no `version`, stops startup (`RuntimeError` naming the file). Known policy-domain stems use their own model (`tools`, `escalation`, `min_payment`), and any other stem (including `card_select`, whose model lives in `conversation/flows/card_select.py` and which `policy` must not import) is checked against a header-only model; the lifespan also calls the card-select loader once. The combined hash is `"sha256:" + hex(sha256(concat over sorted file names of name + "\0" + bytes + "\0")))`. The existing per-file loaders stay | Assumption 2. `07` D3-A1, ADR-012, R8, `04` §5 |
| D2 | **The policy hash reaches every decision.** `ToolContext.policy_version` is the combined hash (replacing `"unversioned"`, D2-A D10), and every audit event's `policy_version` is that value | Assumption 2. `04` §5 ("combined hash logged on every decision"), `04` §6 |
| D3 | **Allowlist.** Each `tools.yaml` tool entry gains `allowed_intents: [Intent]`. `ConfirmedWriteTools.issue_plan(steps, intent)` raises `PolicyDenied("tool_not_allowed")` before touching the store if any step's tool isn't allowed for `intent`, and `get_block_origin(card_id, intent)` does the same check. Read tools are not gated. Flows pass their intent: `card_block` → `"card_block"`, `card_unlock` → `"card_unlock"`, `replacement` → `"replacement_request"` (also when it runs after a block) | Human Q3(a). `04` §1 `ToolSpec.allowed_intents`, `02` §1 intent → flow |
| D4 | **Step-up window and OTP limit.** `tools.yaml` gains the top-level `step_up_window_minutes: 5`. `SessionStepUpGate` is valid when `session.step_up_at` is set and `now - step_up_at <= window`. An open plan is not tied to the session: when the session expires, `/confirmations` returns `401` and the plan dies at its own 5-minute TTL. `/auth/otp/verify` failures count in `rl:otp:<account_id>` with the login limiter's settings (`LOGIN_MAX_FAILURES`=5, `LOGIN_WINDOW_SECONDS`=900); at the limit it returns `429 too_many_attempts` even for the right code | Human Q5(a). Resolves the decision-log deferred item "step-up validity window"; ADR-008, ADR-025, R8 |
| D5 | **`POST /auth/otp/verify {code}`** sits on the customer `router` in `auth.py` (role + CSRF). It compares the code with `DEMO_OTP_CODE` in constant time, and an empty configured code never matches. On success it re-issues the session and CSRF cookies with `step_up_at = now` and returns `MeResponse`, exactly as `/auth/refresh` does, so the old token is not revoked; it has no fresh `step_up_at` and grants nothing more. A wrong code gets `401 otp_invalid`. The code is never logged | Assumption 6 (mirror refresh; `04` §3 says refresh doesn't revoke). ADR-008, `04` §3 |
| D6 | **The resume turn goes through `/messages`.** `PostMessageRequest` becomes `{text?: str (1..2000), resume?: "step_up"}` with exactly one set; anything else is `422`. A `resume` turn runs with `TurnInput{user_text: "", confirmation: None, resume: "step_up"}` and is not persisted as a customer message | Human Q1(a). `04` §3 (`TurnInput.resume`), D2-B D1 |
| D7 | **`POST /conversations/{id}/confirmations/{token_id}` body `{decision: "confirm" \| "cancel"}` → `202 {turn_id}`.** Before any turn is scheduled, the route checks that `conf:<token_id>` exists, belongs to this session's customer and this conversation, and equals the checkpointed `confirmation_token_id`. If any check fails, it returns `409 confirmation_invalid` and schedules no turn. `409 turn_in_progress` works as on `/messages`. The executor's R2 checks stay as the second gate | Human Q2(a). `04` §3, §7, R2, R13 |
| D8 | **`RedisConfirmationStore`** implements the D2-K `ConfirmationStore` exactly as `04` §7 describes: `conf:<id>` JSON `{conversation_id, customer_id, steps: [{tool, args_hash}], cursor, expires_at}`, TTL 300 s, token `secrets.token_urlsafe(32)`, and one Lua script for check + advance that deletes the key after the last step. It adds `is_open(token_id) -> bool` (the key exists and the owner matches) for D7. `InMemoryConfirmationStore` stays for the sandbox | Assumption 3. ADR-027, `04` §7 |
| D9 | **Migration `0003_card_writes`** (down `0002`) creates the `03` §6 tables (Contracts below). `card_replacements` stores `address_ref` + `address_changed` and **no raw address**; D5-A1 adds the encrypted snapshot. Applied through the existing `make seed-identity` / `make data` path (alembic on golden, then `demo-reset`) | Human Q4(a). Assumption 4, ADR-011, `03` §6 |
| D10 | **Postgres raw writes** (`PostgresBankWrites` in `conversation/tools/postgres_writes.py`) call new `cards.service` write functions, following the D2-A D11 pattern: an import-linter ignore edge, the own-row-first ownership probe (`AccessDenied` on a foreign card, logged `tool.access_denied`), and a re-read of the record before returning `verified` (R3). `block_card` updates `bank.products.product_status = 'Blocked'` and inserts a `card_status_history` row **in the same transaction** (R12). Behavior matches FakeBank (D2-B D7): no `Conflict` is raised, and the read-back keys are those in `04` §1. `get_block_origin` uses FakeBank's order: customer block (Blocked with the latest history row `actor='customer'`), then customer lock (`card_controls.locked`), then customer status, `days_past_due`, and dataset Blocked/Suspended. `cards.service` reads `locked` from `card_controls` | Assumption 5. R1, R3, R12, `02` §4.6–4.7 |
| D11 | **Idempotency keys, built now (amends D2-K D13).** Every raw write in `BankWriteTools` gains a keyword-only `idempotency_key: str`. `ConfirmedWriteTools` passes `f"{token_id}:{step_index}"`, using the index returned by `consume_step`. `card_status_history`, `card_controls` and `card_replacements` each get a unique nullable `idempotency_key`. A raw write whose key already exists returns a re-read of the existing record and writes nothing; a unique-violation race is handled the same way. FakeBank keeps a key → `ActionResult` map with the same behavior | Human Q6(b) (not the recommended option). `06` §4, `01` §7 |
| D12 | **Migration `0004_audit_events`** (down `0003`) creates `audit.audit_events` in the `04` §6 shape. Rows are append-only: the service has no update or delete path | Assumption 4/7. `03` §6 `audit`, `04` §6 |
| D13 | **`AuditRecorder`**, bound per turn to `(conversation_id, turn_id, trace_id, policy_version, actor)`, does a synchronous insert per event through `audit.service`. Conversation code reaches it only from `conversation/tools/` (a new import-linter ignore edge) and from the runner through the registry. Payloads are structural only: intents, status, rule id, tool, opaque `card_id`, `args_hash`, `step_index`, `verified`, read-back, error class, and `{route, ui_kinds, length}` for `reply_sent` (amended by D21). **No user text and no reply text** (masking is D5) | Assumption 7. `06` §2, R5. Amended by D21, D22 |
| D14 | **Which events come from where.** `ConfirmedWriteTools` emits `confirmation_issued`, plus a `tool_call`/`tool_result` pair for every write and for `get_block_origin`, `confirmation_used` (with `step_index`), `readback`, `rule_hit` (`tool_not_allowed`, `step_up_required`) and `access_denied`. `RecordingBankTools` emits the pair for every read, plus `access_denied`. The runner emits `nlu_result`, `rule_hit` for any `escalation_reason` set this turn, and `reply_sent`. `ActionResult.audit_event_id` is the `readback` event's id (`model_copy`) | Assumption 7. `07` D3-A5, `04` §6 |
| D15 | **Audit failure.** If the `tool_call` event can't be written, the call doesn't run (`ToolUnavailable`; for a write, before `consume_step`). After a raw write has run, an audit insert failure is logged (`audit.write_failed`, ids only) and never turns a verified write into a failure; `audit_event_id` stays `None` | Assumption 7 (fail closed before the write). After-write half confirmed by the human at the spec gate (D20) |
| D16 | **Order inside a confirmed write** (amends D2-K D3): (1) `tool_call` audit, fail closed; (2) step-up check → `StepUpRequired` + `rule_hit`, without consuming; (3) `consume_step` → `confirmation_used`; (4) raw call with `idempotency_key`; (5) `readback` + `tool_result`. On an exception or `verified=False`, it writes `tool_result{error}` (best effort) and cancels the plan (unchanged D2-K D3/D20 semantics) | D3, D11, D14, D15. R2, R3 |
| D17 | **A6 runner wiring.** `_run_turn` builds `bank_write_tools = ConfirmedWriteTools(PostgresBankWrites(ctx) \| FakeBankWrites when BANK=fake, RedisConfirmationStore(customer, conversation), SessionStepUpGate(session, window), step_up_rule(tools policy), allowlist(tools policy), recorder)` and passes `vault = InMemoryAddressVault()` per turn. `start_turn` takes `text \| resume \| confirmation`. The sandbox builds its executor with the same allowlist and a no-op recorder | Assumption 1. Human Q4(a) (per-turn vault), D2-A D13 ends |
| D18 | **`make chat-api`** gains `/otp <code>` (`/auth/otp/verify`, then the `resume` turn), `/confirm` and `/cancel` (the confirmations route with the last `ui.confirm` token), and `/replay` (re-posts the last used token and prints the status, for step 6) | Assumption 8. `07` D3 "If behind" (unlock and replacement testable through `chat-api`) |
| D19 | **Doc updates in this PR.** `04` §1 (`issue_plan`/`get_block_origin` intent, `idempotency_key`, the order in D16), §3 (`/messages` resume, the `/confirmations` body and `409`, the `/auth/otp/verify` errors), §5 (`tools.yaml` shape). `03` §6 (the three app tables' columns, `card_replacements` without a snapshot until D5). The decision-log deferred row for the step-up window becomes resolved, pointing at D4 | `06` §7.4 |
| D20 | **Spec-gate decisions (end of card).** (1) An audit insert failure after a raw write has run is logged as `audit.write_failed`, and the verified result stands with `audit_event_id=None` (confirms D15). (2) A button confirmation is not saved as a customer message; the `confirmation_used` audit event records it. (3) `card_controls` keeping only the last write's `idempotency_key` is accepted (a lock replayed after a later unlock would lock again; no code path replays a consumed step across turns) | Human, spec gate |
| D21 | **Amends D13:** the `reply_sent` payload is `{route, ui_kinds, length}`. It has no template kinds, because `TurnState` carries none | Human, plan T11 |
| D22 | **Amends D13:** audit events written during a customer turn use `actor="bot"` | Human, plan |
| D23 | **Built fact (T13):** `flows/replacement.py` never filled the `action_done` `{result}` placeholder. It is now filled from a per-language label (`es` "pedida", `pt` "pedido"), mirroring `card_block`/`card_unlock` | Built, T13. R4 |
| D24 | **Built fact:** the integration fixture `it_env` turns off structlog logger caching, so `capture_logs` works in any test order | Built |

## Contracts

Only the delta. Everything else is as in `04` and the D2-K spec.

**`policies/tools.yaml`** (`version: 1`, the new fields are required):
```yaml
provenance: team-generated-synthetic
version: 1
step_up_window_minutes: 5
tools:
  cards.lock_card:         {requires_confirmation: true,  step_up: never,                allowed_intents: [card_block]}
  cards.unlock_card:       {requires_confirmation: true,  step_up: always,               allowed_intents: [card_unlock]}
  cards.block_card:        {requires_confirmation: true,  step_up: never,                allowed_intents: [card_block]}
  cards.order_replacement: {requires_confirmation: true,  step_up: when_address_changed, allowed_intents: [replacement_request]}
  cards.get_block_origin:  {requires_confirmation: false, step_up: never,                allowed_intents: [card_unlock, replacement_request]}
```
`ToolPolicy.allowed_intents: list[str]`, `ToolsPolicy.step_up_window_minutes: int` (≥ 1), `provenance: Literal["team-generated-synthetic"]` on every policy model. New `tool_allowed(policy) -> Callable[[str, str], bool]` (`(intent, tool)`; an unknown tool → `False`).

**`app/domains/policy/registry.py`** (new)
```python
class PolicyBundle(BaseModel):   # frozen
    hash: str                    # "sha256:<hex>" (D1)
    tools: ToolsPolicy; escalation: EscalationPolicy; min_payment: MinPaymentPolicy
    files: list[str]             # every stem validated, header-only ones included
def load_policies(directory: Path | None = None) -> PolicyBundle   # raises PolicyLoadError(file)
def get_policies() -> PolicyBundle                                  # cached; the lifespan calls it first
```

**`app/domains/policy/confirmation_redis.py`** (new): `RedisConfirmationStore(customer_id: str, conversation_id: str)` implements `ConfirmationStore` (D8) and adds `async def is_open(self, token_id: str) -> bool`.

**`app/domains/identity/step_up_session.py`** (new): `SessionStepUpGate(step_up_at: datetime | None, window: timedelta, now: Callable[[], datetime] = utcnow)` implements `StepUpGate`.

**`app/domains/conversation/tools/write.py`**: amended `BankWriteTools` (D11)
```python
async def lock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult: ...
async def unlock_card(self, card_id: str, *, idempotency_key: str) -> ActionResult: ...
async def block_card(self, card_id: str, reason: BlockReason, *, idempotency_key: str) -> ActionResult: ...
async def order_replacement(self, card_id: str, address_ref: AddressRef, *, idempotency_key: str) -> ActionResult: ...
```

**`app/domains/conversation/tools/executor.py`**: `ConfirmedWriteTools`
```python
IntentAllowlist = Callable[[str, str], bool]          # (intent, tool) -> allowed
def __init__(self, raw, confirmations, step_up, requires_step_up, allowed: IntentAllowlist, audit: AuditRecorder) -> None
async def issue_plan(self, steps: Sequence[PlanStep], intent: Intent) -> ConfirmationPlan   # PolicyDenied("tool_not_allowed")
async def get_block_origin(self, card_id: str, intent: Intent) -> BlockOrigin
# the four writes keep their D2-K signatures; the order is D16
```
`flows/actions.start_plan(..., intent: Intent)` passes it through.

**`app/domains/audit/`** (new domain: `schemas.py`, `repository.py`, `service.py`)
```python
AuditType = Literal["nlu_result","rule_hit","tool_call","tool_result","confirmation_issued",
                    "confirmation_used","readback","access_denied","reply_sent","error"]
class AuditRecorder:  # bound per turn (D13)
    def __init__(self, *, conversation_id: UUID, turn_id: UUID, trace_id: str, policy_version: str,
                 actor: Literal["bot","customer","system"]) -> None
    async def record(self, type: AuditType, payload: dict[str, JsonValue], sources: list[str] = []) -> UUID
class NullAuditRecorder  # sandbox and unit tests; returns uuid4()
```

**Migration `0003_card_writes`** (schema `app`)
| Table | Columns |
|---|---|
| `card_controls` | `product_id text pk`, `locked bool not null default false`, `locked_by text null` (`customer\|agent\|system`), `locked_at timestamptz null`, `updated_at timestamptz not null default now()`, `idempotency_key text unique null` |
| `card_status_history` | `id uuid pk`, `product_id text not null`, `old_status text`, `new_status text not null`, `reason text null`, `actor text not null`, `conversation_id uuid null`, `trace_id text null`, `at timestamptz not null default now()`, `idempotency_key text unique null`; index `(product_id, at desc)` |
| `card_replacements` | `id uuid pk`, `product_id text not null`, `address_ref text not null`, `address_changed bool not null`, `tracking_id text unique not null` (`RPL-` + 8 hex upper), `status text not null` (`ordered`), `conversation_id uuid null`, `created_at timestamptz not null default now()`, `idempotency_key text unique null` |

**Migration `0004_audit_events`**: `audit.audit_events(id uuid pk, at timestamptz not null default now(), conversation_id uuid null, turn_id uuid null, actor text not null, type text not null, payload jsonb not null, sources jsonb not null default '[]', policy_version text not null, model jsonb null, trace_id text null, langfuse_trace_id text null)`, index `(conversation_id, at)`.

**HTTP (`/api/v1`)**
| Route | Body → response | Errors |
|---|---|---|
| `POST /auth/otp/verify` (customer, CSRF) | `{code: str}` → `200 MeResponse` + re-issued `session` (with `step_up_at`) and `csrf_token` cookies | `401 otp_invalid`, `429 too_many_attempts`, `401 session_expired` |
| `POST /conversations/{id}/messages` | `{text} \| {resume: "step_up"}` → `202 {turn_id}` | `422` (neither or both), `409 turn_in_progress`, `404` |
| `POST /conversations/{id}/confirmations/{token_id}` | `{decision: "confirm"\|"cancel"}` → `202 {turn_id}` | `409 confirmation_invalid`, `409 turn_in_progress`, `404`, `401` |

**Runner**: `start_turn(host, *, session, conversation_id, trace_id, text: str | None = None, resume: Literal["step_up"] | None = None, confirmation: ConfirmationDecision | None = None)`, with exactly one of the three set. Only `text` is persisted as a customer message.

## Touch map

```
policies/tools.yaml                                             edit (A1)
backend/app/domains/policy/{registry,tools_policy}.py           new/edit (A1)
backend/app/domains/policy/{escalation,min_payment}.py, conversation/flows/card_select.py   edit: provenance Literal only (A1)
backend/app/main.py                                             edit: lifespan loads policies (A1)
backend/app/domains/policy/confirmation_redis.py                new (A2)
backend/app/alembic/versions/0003_card_writes.py                new (A3)
backend/app/domains/cards/{repository,service}.py               edit: writes, block origin, locked read (A3)
backend/app/domains/conversation/tools/postgres_writes.py       new (A3)
backend/.importlinter                                           edit: postgres_writes -> cards.service; tools.* -> audit.service (A3, A5)
backend/app/api/v1/auth.py, identity/service.py                 edit: otp verify + limiter (A4)
backend/app/domains/identity/step_up_session.py                 new (A4)
backend/app/alembic/versions/0004_audit_events.py               new (A5)
backend/app/domains/audit/{__init__,schemas,repository,service}.py   new (A5)
backend/app/domains/conversation/tools/{write,executor,fakebank,registry}.py   edit (W2-exec)
backend/app/domains/conversation/flows/{actions,card_block,card_unlock,replacement}.py   edit: pass intent (W2-exec)
backend/app/domains/conversation/sandbox.py                     edit: executor ctor (W2-exec)
backend/app/api/v1/conversations.py                             edit: resume, confirmations (W2-route)
backend/app/domains/conversation/runner.py                      edit: turn inputs (W2-route), wiring + audit (A6)
backend/scripts/chat_api.py                                     edit (A6)
docs/solution-docs/{04-contracts,03-data-architecture,decision-log}.md   edit (D19)
backend/tests/…                                                 see Test list
```

### Build order (parallel groups)

- **Wave 1: five implementers in parallel, no shared files.**
  - A1 policy registry (policy/*, `tools.yaml`, `main.py`)
  - A2 Redis store (`confirmation_redis.py`)
  - A3 migration `0003` + `cards` writes + `postgres_writes.py`. It defines its methods with the D11 keyword signature, but does not touch `write.py`.
  - A4 OTP route + `SessionStepUpGate` (`auth.py`, `identity/*`)
  - A5 audit domain + migration `0004`
  - The docs (D19) can run alongside any of them.
  - Shared points to coordinate:
    - A3 and A5 both edit `.importlinter`; each adds one line, so the merge is trivial.
    - A5's migration chains on `0003` by its fixed revision id, so A5's DB test runs after A3 lands.
- **Wave 2: two in parallel, after wave 1.**
  - W2-exec: `write.py`, `executor.py`, `fakebank.py`, `registry.py`, the flows and the sandbox (the allowlist D3, idempotency D11, audit D14–D16, and `policy_version` D2)
  - W2-route: `conversations.py` + `runner.start_turn` inputs (D6, D7)
  - The two share no files.
- **Wave 3: A6 alone.** The runner wiring (D17), runner audit events, `chat_api.py` and the end-to-end integration test.

## Test list

Unit tests use fakes and `ScriptedLLM`. Integration tests run against `make up` (`it_env`, D2-A D19).

| Test | Proves |
|---|---|
| `unit/test_policy_registry.py::test_headerless_file_fails_startup` | A1 Done-when: a tmp `policies/` with one header-less file → `load_policies` raises naming it; a clean copy → the hash is stable and changes when one byte changes (D1, R8) |
| `unit/test_r2_confirmed_writes.py::test_intent_not_allowed_is_refused` | A1 Done-when: `issue_plan([lock_card], intent="card_unlock")` → `PolicyDenied("tool_not_allowed")`, the store is never called, and a `rule_hit` is recorded (D3) |
| `unit/test_r2_confirmed_writes.py` (existing four, updated) | R2 order is unchanged with the new constructor and the `idempotency_key` passed as `<token>:<index>` (D11, D16) |
| `integration/test_r2_redis_store.py::test_reused_expired_foreign_tokens_rejected` | A2 Done-when: reuse → `unknown_or_expired`; expired (TTL forced) → `unknown_or_expired`; another customer or conversation → `wrong_owner`; reordered step → `step_mismatch` (D8) |
| `integration/test_confirmations_route.py::test_replayed_token_is_409` | End-of-day step 6, D7: a used or foreign token on the route → `409 confirmation_invalid`, no turn scheduled |
| `integration/test_r13_ownership.py` (+1 case) | R13: customer B posting to A's `/confirmations` → `404` (the route-introspection unit test covers the new routes automatically) |
| `integration/test_postgres_writes.py::test_each_write_verified_from_reread` | A3 Done-when, R3: each of the four writes returns `verified=True` and `readback` equal to the DB row; with the re-read stubbed to a stale row → `verified=False` |
| `integration/test_postgres_writes.py::test_foreign_card_write_refused` | R1: a write on another customer's card → `AccessDenied`, no row written, `access_denied` audited |
| `integration/test_postgres_writes.py::test_block_history_same_transaction` | R12: block → `product_status='Blocked'` + one history row (old, new, reason, actor, conversation_id); a forced history-insert failure → the product is unchanged |
| `integration/test_postgres_writes.py::test_idempotency_key_replay` | D11: the same key twice → one history/replacement/controls change, and the same read-back returned |
| `unit/test_step_up.py::test_unlock_without_valid_step_up_refused` | A4 Done-when: `step_up_at=None` and `step_up_at` 6 min ago → `StepUpRequired`, token not consumed (D4) |
| `integration/test_auth.py::test_otp_verify` (+1) | D4/D5: wrong code → `401`; 5 failures → `429`; right code → the cookie decodes with `step_up_at` |
| `unit/test_audit_pairs.py::test_every_tool_call_leaves_a_pair_with_policy_hash` | A5 Done-when: one read, one refused write and one verified write → a `tool_call`/`tool_result` pair each, every event with `policy_version == bundle.hash`, `audit_event_id` = the `readback` event id, no free text in payloads (D13, D14) |
| `integration/test_write_path_api.py::test_lock_confirm_unlock_otp_block_replace` | A6 Done-when and end-of-day steps 3–5 (ES), `ScriptedLLM`: lock → `/confirmations` → `card_controls.locked` true and "done" only from a verified result; unlock → `otp_required` → `/auth/otp/verify` → `resume` → confirm → unlocked; block → history row → replacement with a changed address → OTP → tracking ID |
| `integration/test_write_path_api.py::test_pt_lock_happy_path` | The PT happy path for the flow over the API |
| `integration/test_write_path_api.py::test_bank_blocked_unlock_handoff` | End-of-day step 7: a bank-blocked persona's unlock → handoff placeholder, no write, no plan issued |

`make check` (lint, mypy, import-linter, unit) green, and `make test-integration` green locally.

## Boundaries

- **Always:** take `customer_id` only from the session (R1); run every write through `ConfirmedWriteTools`; re-read before `verified`; keep policy values in YAML; keep audit payloads free of user and reply text; keep the fixed migration revision ids `0003`/`0004`.
- **Ask first:** any change to the flows' behavior beyond passing the intent; any `TurnState` change; changing `ActionResult`, `ConfirmationPlan` or the `ui` payloads; adding a column not listed above; storing any raw address.
- **Never:** give an LLM node access to `bank_write_tools` (R6); log the OTP code, the session token or a document number; commit `DEMO_OTP_CODE`; edit `eval/scenarios/heldout/`; edit an existing migration.

## Success criteria

1. Removing the `provenance` line from any `policies/*.yaml` makes `make up`'s backend exit with an error naming that file; restoring it starts cleanly. `test_headerless_file_fails_startup` passes.
2. `test_intent_not_allowed_is_refused` passes. `policies/tools.yaml` holds `allowed_intents` and `step_up_window_minutes: 5`, and no step-up window or allowlist literal exists in Python.
3. `test_reused_expired_foreign_tokens_rejected` and `test_replayed_token_is_409` pass. `curl` replaying a used token on `/confirmations/{token}` prints `409` with `confirmation_invalid`.
4. `test_each_write_verified_from_reread`, `test_foreign_card_write_refused`, `test_block_history_same_transaction` and `test_idempotency_key_replay` pass. After step 5 of the end-of-day test, `SELECT` shows `product_status='Blocked'`, one `card_status_history` row and one `card_replacements` row with `address_changed=true` and no address column.
5. `test_unlock_without_valid_step_up_refused` and `test_otp_verify` pass.
6. `test_audit_pairs` passes. After an end-of-day run, `audit.audit_events` holds `tool_call`/`tool_result` pairs for the turn's tools, all with the same `policy_version` as the startup log line `policy.loaded hash=…`.
7. `test_write_path_api` (the three tests) passes, and `make chat-api PERSONA=<multi-card>` runs end-of-day steps 3–7 with `/confirm`, `/otp` and `/replay`.
8. `make check` is green. `04` §1/§3/§5, `03` §6 and the decision-log deferred row are updated as D19 lists.

## Open questions

None. The three items the spec left open were resolved at the spec gate (D20).
