# Spec: D9-C — Card requests: G8 open and close a card, G10 handoff

Card D9-C · `07` D9 section, table "Card requests", rows C1–C7, plus its "If behind (proposed)" line. It is taken as an exception to "Fixes only" (`07` §8, row "D9 | Card requests", decided 2026-10-04). Branch `feat/d9-c-card-requests`, based on `develop` @ ecc9655. The card touches the tool registry, policy, identity seeding and the first staff-made bank write, so it is safety-critical and the other dev reviews it (ADR-018).

Builds on the agent path: [`cardy-agent-s2-unlock-replacement.md`](cardy-agent-s2-unlock-replacement.md) (the OTP and address pauses, `propose_plan` results) and [`cardy-agent-s3-unrecognised-charge.md`](cardy-agent-s3-unrecognised-charge.md) (a plan step outside cards, a handoff built in code after Acepto). It also builds on the handoff: [`d4-a-escalation-handoff-deploy.md`](d4-a-escalation-handoff-deploy.md) and [`d8-h-handoff-v2.md`](d8-h-handoff-v2.md) (packet v2, staff screens).

## Objective

A customer asks Cardy, on the agent path only, for a new debit or credit card or to close one of their cards. For a new card, Cardy does the following:
1. Checks eligibility in code.
2. Shows a code-rendered personal-data form.
3. Asks for the OTP.
4. Shows the "Acepto / No acepto" plan card.
5. On Acepto, saves the changed data, reads it back, files a pending request and hands the conversation to **Créditos**.

For a closure, Cardy takes the card and a reason code and states the zero-balance condition and the balance. After the OTP and the plan card, she files the request and hands off to **Retención**, even when the balance is not 0.

The claiming staff agent decides from a panel on the handoff page. Approve creates a `bank.products` row. Cancel closes the card, and code refuses it unless the balance is 0. Decline, Keep and "not cancelled because of the balance" write no bank row. The customer gets a code-filled template only after a verified read-back, and the home refreshes its cards through a `cards_changed` SSE event. With the agent off or the LLM down, both requests get a fixed text and the offer of a person.

The spec serves the seven "Done when" lines (C1–C7) and the two browser checks in C6 (ES: open a credit card, Créditos approves; PT: close it, Retención cancels).

## Assumptions (accepted by the human with the answers)

AS1. Agent path only. With `AGENT_ENABLED` off or the LLM down, the only new behaviour is C7's fixed text. The pipeline flows and the baseline are unchanged (`07` §8 D9; C7).
AS2. The OTP reuses the S2 agent step-up: pause `agent/otp`, the `accepted (step_up_required)` result, `/auth/otp/verify` followed by `resume: "step_up"`, and the `step_up_max_failures` limit leading to a `step_up_failed` handoff. Confirmation reuses the agent plan card ("Acepto / No acepto"), a single-use token and `execute_plan` (`02` §3, `04` §1, ADR-027).
AS3. The staff decision is a human click behind a review dialog plus a client-generated idempotency key, stored unique on the request (C5). It is not a customer confirmation token: R2 governs bot/tool writes. Audit events carry `actor = agent:<account_id>` (`02` §6.4, `audit/schemas.py` `AuditActor`). The route is claimant only (R13).
AS4. Writes go through domain services (R12, ADR-011). A new `bank.products` row carries `origin='app'`, `created_at` and `conversation_id`. Cancel updates `product_status` and writes a `card_status_history` row in the same transaction. The new row also has:
- `product_id` = `PRD-` + 12 upper alphanumerics.
- `product_number`: a unique 16-digit number with a Luhn check.
- `opening_channel='App'` and `opening_date` = the simulated today (`03` §5).
- `expiration_date` = today + `expiry_years`, and `days_past_due=0`.
- `current_balance=0` and `has_linked_app` NULL (D14).
- Credit: `interest_rate` from policy. Debit: `interest_rate` 0 and `credit_limit` NULL, as in the dataset.
AS5. Profile edits wait in the PII vault (`03` §6 `pii_vault`) until Acepto. Each field uses its own form-only vault kind (D16); the `kind` column is plain text, so no DDL is needed. State and the checkpoint hold only `changed_fields: list[str]`. Name, document (masked as `login_hint` is, `04` §3) and date of birth are read-only. The editable `address` is `bank.customers.address` only.
AS6. Declared income is shown in the country's local currency (MXN/COP/ARS), formatted in code (R4).
AS7. Eligibility runs in code, never in the LLM (R8):
- "No card past due" means any non-Closed card with `days_past_due > 0`.
- The cap counts the customer's non-Closed cards of the requested kind.
- "One pending request": one undecided `open` request per customer, and one undecided `close` request per card.
- A closure also needs the card to be not `Closed`.
AS8. The zero-balance rule is `current_balance == 0` for both kinds, read fresh at the staff click.
AS9. `POST /staff/handoffs/{id}/return` answers `409 request_undecided` while the linked request is undecided.
AS10. "Cards changed" is a named SSE event `cards_changed {}` on `conv:<id>`. The frontend invalidates its `/me/cards` queries on it. Decision templates are posted as `message{role: agent, agent_display_name}`.
AS11. Migration `0011` reaches the golden DB through `make seed-identity`, which runs `alembic upgrade head` on golden, seeds the staff accounts and then runs `demo-reset`. In the dev seed, `identity/provision.py` truncates `app.card_requests` and `app.customer_profile_history` together with the accounts and handoffs, because the 0011 foreign keys refuse a lone `TRUNCATE`.
AS12. `02` §1/§3/§5, `03` §6 and `04` §1/§3/§4/§5 are updated in the same PR. All tests use a fake LLM.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | Full card, built in card order C1→C7. The documented cut stays the card's "If behind" line: ship opening only and drop C4 plus its parts of C5/C6. If the card is not merged before the submission email, it is dropped | Human Q1 c); `07` D9 "If behind" |
| D2 | The agent starts both requests through `propose_plan`, with the new actions `open` and `close` (Contracts §2). Eligibility is a code `preconditions` check on the two new tools. Opening goes `accepted (form_required)` → pause `agent/profile_form` → `accepted (step_up_required)` → plan card → `execute_plan`. Closing goes straight to `accepted (step_up_required)`. The agent holds no new write capability (R6) | Human Q2 a); `04` §1 "`propose_plan` is the agent's only write capability" |
| D3 | No NLU change. The `Topic` and `Intent` literals, `intents.yaml` and `nlu@v7` stay as they are. `new_card` leaves `scope.yaml` and `TOPICS` validation. On the pipeline, topic `new_card` and intent `card_cancel` both get the fixed `card_request_unavailable` text plus a human offer, built in code. On the agent path, `card_cancel` becomes a supported intent. An opening is identified by the plan action and `app.card_requests.kind`, with no new intent. Amended mid-card: the only `intents.yaml` change is the `card_cancel` tier (Contracts §2); the baseline keeps `new_card_not_available` (D20, R-d); LLM-down detection is D17 | Human Q3 a); C1 bullet 5; C7 |
| D4 | The closing reason: the agent maps the customer's words to one code. `ProposedStep.reason` is checked in code against `card_requests.yaml` `cancel_reasons`, and anything else gets `rejected (<card>: invalid_reason)`. When the reason is unclear the agent asks, with `other` as the fallback. The reason label (code → localized label) is shown on the plan card before Acepto | Human Q4 a) |
| D5 | Cancel with `current_balance ≠ 0` at the click gets `409 balance_not_zero` and writes nothing: no bank row, no request update, no audit decision event. The panel then offers a fifth decision, `not_cancelled_balance`. It closes the request with no bank write and posts template 6 with the balance formatted in code | Human Q5 a); C5 "Cancel: refused by code unless the balance is 0 at the click" |
| D6 | New table `app.customer_profile_history` in migration `0011`. Old and new values are Fernet ciphertext under `PII_VAULT_KEY`. Its rows are written in the transaction that updates `bank.customers` and creates the request. It drives the panel's "just changed" flag | Human Q6 a); R12; ADR-011 |
| D7 | Policy values exactly as in Contracts §1: `card_requests.yaml` v1, `escalation.yaml` v10 (`card_open_request`→`creditos`, `card_close_request`→`retencion`, both normal priority) and `tools.yaml` v6 (`cards.request_card` and `cards.request_closure`, `requires_confirmation: true`, `step_up: always`, with `preconditions`) | Human Q7 a); R8; ADR-012 |
| D8 | Agent names, queue labels and the seven ES/PT templates exactly as in Contracts §8 | Human Q8 a); `07` D9 ("set at the spec gate") |
| D9 | For an opening, a failed eligibility check is a `rejected (open: <code>)` result that the agent explains. It never hands off, and that includes a customer who is not Active: for `cards.request_card` this rejection replaces the `customer_not_active` handoff that `04` §5 applies to agent write steps. `cards.request_closure` keeps the existing `customer_not_active` rule (handoff to Atención): C4 lists no eligibility check of its own | C3 "A failed check is explained and creates no handoff"; `04` §5 (`tools.yaml` v4 note); `escalation.yaml` `customer_not_active` |
| D10 | `cards.request_card` is one confirmed step. On Acepto it saves the changed profile fields from the vault (through `customers.service`), writes their history rows, creates the request, then re-reads both. `verified` is true only when every changed field and the request row match. An unverified result takes the existing `action_unverified` path (R3). There is no separate profile-write tool | C3 "On Acepto: save the changed data, read it back, create the request"; C1 lists exactly two tools; R3 |
| D11 | The form pause mirrors the agent OTP pause. The form has Send and Cancel. A typed `text` at the form pause gets `409 form_required` (no turn, nothing persisted, pause kept). Cancel ends with `action_cancelled` and no LLM call | AS2; `04` §3 agent OTP pause (S2 D15, D17, D30) |
| D12 | The staff decision is audited with the existing `AuditType`s: `tool_call`, `readback`, `tool_result`, tool `cards.decide_card_request`, `actor = agent:<account_id>`. There is no new audit type | C5 "Every decision writes an audit event with the agent as actor"; `04` §6 |
| D13 | The handoff packet gains an optional `card_request` block. `verified_facts` gains the fact `card_request_filed`. `HandoffReason` gains `card_open_request` and `card_close_request` | C4 "packet carries the reason code"; `04` §4 |
| D14 | Staff approve details. The new card has `current_balance` 0 and `has_linked_app` NULL. A `credit_limit` that is not a number gets `422 limit_out_of_bounds`; a missing or blank one gets `422 limit_required`. A debit approve ignores any `credit_limit` sent and stores NULL | Human, mid-card (plan T18) |
| D15 | The `request_card` read-back's `fields_saved` is one comma-joined string of field names (`",".join(changed_fields)`), not a list. `ReadbackValue` is unchanged, the Postgres writer returns the same shape, and readers split on `,` | Human, mid-card (plan T13) |
| D16 | Form values use the form-only vault kinds `PFEMAIL`, `PFPHONE`, `PFADDR`, `PFOCC` and `PFINCOME`. Each submit mints a fresh token per staged field, and the newest token per field wins. `TOKEN_RE` is unchanged, so `unmask` never puts a form value into chat text. This sharpens AS5 | Human, mid-card (plan Q1); R5 |
| D17 | LLM-down detection for C7 is a code check on agent-path turns that can't use the LLM: the message matches a fixed ES/PT keyword list (one for a new card, one for closing), or an `open`/`close` plan is in progress. Either gives `card_request_unavailable` plus the human chip. The lists live in code (`agent/node.py`) | Human, mid-card (plan Q2); C7 |
| D18 | `card_open_request` and `card_close_request` map to the analytics cause group `by_design`. Copy this spec did not word (reason labels, field labels, i18n strings, queue colours) was written by the implementers against `docs/brand.md` and is reviewed at the verifier gate | Human, mid-card (plan Q4, Q3) |
| D19 | `close_balance` is registered under the exact reference `close_balance` (new `TurnRefs.add_value`). The agent prompt stays `agent@v5` as written for the `open`/`close` actions, with no further change or bump. A card with no `current_balance` on record gets the code-built wording "saldo no disponible" (ES) / "saldo indisponível" (PT), never 0, and the closure is still filed | Human, mid-card (plan T29, T29b); R4 |
| D20 | Plan readings R-a to R-f stand as written in `docs/plans/d9-c-card-requests.md`. `card_requests.handoff_id` is written in the decision transaction (R-a). Read-backs also carry `request_id`, and for a closure `card_id`, `card_kind` and `last4` (R-b). A replayed decision returns the stored `request` and `verified` with `message_id: null` (R-c). The baseline keeps `new_card_not_available` (R-d). `make data` truncates the two new tables, in `pipeline/load/postgres.py` (R-e). The `card_cap_reached` case of T7 patches `max_cards_per_kind.debit` to 1 for the fixture customer (R-f) | Human, mid-card (plan readings) |

## Contracts (delta only; everything else is `04`)

### 1. Policy

`policies/card_requests.yaml` (new, validated at startup by `app/domains/policy/card_requests.py`, registered in `registry.py`):
```yaml
provenance: team-generated-synthetic
version: 1
currency_by_country: {MX: USD, CO: COP, AR: ARS}       # new card's currency (MX USD per ADR-014)
credit_limit_bounds: {USD: {min: "1000", max: "50000"}, COP: {min: "4000000", max: "200000000"}, ARS: {min: "350000", max: "17500000"}}  # dataset min/max
max_cards_per_kind: {credit: 3, debit: 2}               # non-Closed cards
interest_rate_by_country: {MX: "31.50", CO: "31.59", AR: "31.29"}   # % annual, credit only (dataset medians); debit 0
expiry_years: 4                                         # dataset median (range 3-5)
cancel_reasons: [no_longer_needed, high_cost, better_offer, too_many_cards, bad_experience, other]
decline_reasons: [low_credit_score, insufficient_income, high_existing_debt, inconsistent_data, other]   # staff-only, never shown to the customer
```
Money values are decimal strings, as in `disputes.yaml`. Validation: every country has a currency and a rate, every currency in `currency_by_country` has bounds, `min < max`, and both reason lists are non-empty and contain `other`. Reason labels (ES/PT) live in code next to the templates, keyed by code.

`policies/tools.yaml` v6 adds:
```yaml
  cards.request_card:    {requires_confirmation: true, step_up: always, allowed_intents: [], preconditions: {request_eligible: true}}
  cards.request_closure: {requires_confirmation: true, step_up: always, allowed_intents: [], preconditions: {status_not_in: [Closed], closure_pending: false, reason_in_policy: true}}
```
`request_eligible: true` runs the C3 checks in this order, and the first one that fails gives its rejection code: `customer_not_active`, `card_past_due`, `card_cap_reached`, `request_pending`. On `request_closure`, `status_not_in: [Closed]` gives `already_in_state`, `closure_pending: false` gives `closure_pending`, and `reason_in_policy: true` gives `invalid_reason`. `allowed_intents: []`: no pipeline flow may call either tool.

`policies/escalation.yaml` v10 adds `rules.card_open_request: {queue: creditos, priority: normal}` and `rules.card_close_request: {queue: retencion, priority: normal}`. `policies/scope.yaml` v3 removes `new_card`. `policies/playbooks.yaml` v2 adds the guidance entries `card_open` and `card_cancel`. These carry wording and order only (R8): ask debit or credit; say the form, the OTP and the plan card come from the system; for a closure, ask which card and why, and state the zero-balance condition and the balance only through the `{close_balance}` placeholder; never promise approval or a limit.

### 2. Agent (`propose_plan`, state)

```python
class ProposedStep(BaseModel):
    action: Literal["lock", "block", "unlock", "replace", "claim", "open", "close"]
    kind: Literal["credit", "debit"] | None = None   # only for open
    reason: str | None = None                        # only for close; a cancel_reasons code
    # card: required for close, rejected for open. open and close each stand alone (rejected whole: `request_alone`)
```
Results:
- `accepted (form_required)`: an open plan that passed eligibility, before the form.
- `accepted (step_up_required)`: after the form for an open plan, and directly for a close plan.
- `rejected (open: <code>)` and `rejected (<card>: <code>)`, with the codes from §1.
- A close step that is accepted also returns a code-built fact `close_balance` (money formatted in code, R4) for Cardy's reply. It is registered under the exact reference `close_balance`. With no balance on record its value is "saldo no disponible" / "saldo indisponível", never 0 (D19).

`TurnState` gains `card_request_kind: Literal["credit","debit"] | None` and `profile_changed_fields: list[str]`, plus `agent_plan_steps` entries `{action: "open", kind}` and `{action: "close", card_id, reason}`. All are cleared with `confirmation_token_id`, at handoff and at `return_to_bot`. Pause `agent/profile_form` (`awaiting_slot = "profile_form"`) leads to the code node `agent_profile_form`, routed like `agent_address` (S2). The plan card's step facts:
- open: kind label and the changed field labels (names only, never values);
- close: card mask, reason label and `close_balance`.

`intents.yaml`: `card_cancel` moves to `tier: core` and `node: null` (the agent handles it, and the pipeline gets the fixed text, D3). The `nlu@v7` prompt is untouched.

### 3. Write tools (`conversation/tools/write.py`, `executor.py`, `postgres_writes.py`, `fakebank.py`)

```python
request_card(kind: Literal["credit","debit"], changed_fields: list[str], *, idempotency_key: str) -> ActionResult
request_closure(card_id: str, reason: str, *, idempotency_key: str) -> ActionResult
```
`ActionResult.tracking_id` = the request `reference` (`CRQ-` + 8 upper hex). Read-backs:
- `request_card`: `{"status": "pending", "kind": ..., "fields_saved": "email,address", "request_id": ..., "at": datetime}`. `fields_saved` is a comma-joined string of field names (D15).
- `request_closure`: `{"status": "pending", "reason": ..., "request_id": ..., "card_id": ..., "card_kind": ..., "last4": ..., "at": datetime}` (D20, R-b).

After a verified Acepto, code sets `escalation_reason`, `handoff_queue` and the packet's `card_request`, and the graph routes `handoff_summary → handoff` (as S3 does).

### 4. Migration `0011_card_requests.py`

- `bank.products` gains `origin text not null default 'dataset'`, `created_at timestamptz null` and `conversation_id uuid null` (`03` §6).
- `app.card_requests`:
  - Identity and links: `id uuid pk`, `reference text unique not null`, `customer_id text not null`, `conversation_id uuid not null` (fk), `handoff_id uuid null` (fk).
  - Request: `kind text not null CHECK (kind IN ('open','close'))`, `card_kind text not null CHECK IN ('credit','debit')`, `product_id text null` (the card to close; on approve, the new card), `reason_code text null` (close), `changed_fields text[] not null default '{}'`.
  - Decision: `status text not null default 'pending' CHECK IN ('pending','decided')`, `decision text null CHECK IN ('approve','decline','cancel','keep','not_cancelled_balance')`, `decline_reason text null`, `credit_limit numeric null`, `agent_id uuid null` (fk `identity.accounts`), `decided_at timestamptz null`.
  - Bookkeeping: `created_at timestamptz not null default now()`.
  - Idempotency: `idempotency_key text unique null` (bot step `<token_id>:<step_index>`) and `decision_key text unique null` (staff idempotency key).
  - Partial unique indexes: `(customer_id) WHERE kind='open' AND status='pending'` and `(product_id) WHERE kind='close' AND status='pending'`.
- `app.customer_profile_history`: `id uuid pk`, `customer_id text not null`, `field text not null CHECK IN ('email','mobile_phone','address','occupation','estimated_monthly_income')`, `old_value_enc text null`, `new_value_enc text not null` (Fernet), `actor text not null`, `conversation_id uuid null`, `card_request_id uuid null` (fk), `at timestamptz not null default now()`; index `(customer_id, at desc)`.

### 5. HTTP and SSE (`/api/v1`)

| Method & path | Role | Contract |
|---|---|---|
| `GET /conversations/{id}/profile-form` | customer (`get_owned_conversation`) | `ProfileFormView{editable: {email, mobile_phone, address, occupation, estimated_monthly_income}, read_only: {full_name, document_masked, date_of_birth_display}, income_currency, card_kind}` for the session's customer (R1). `Cache-Control: no-store`. `409 form_not_open` unless the checkpoint is paused at `agent/profile_form`. The response is never persisted |
| `POST /conversations/{id}/profile-form` | customer (`get_owned_conversation`) | `{action: "submit", values: ProfileFormValues}` or `{action: "cancel"}` → `202 {turn_id}`. Submit validates the values (Pydantic: email, phone, non-empty address/occupation, income > 0), stores each **changed** value in the vault and starts a turn with the internal `resume: "profile_form"`. Cancel starts `resume: "profile_form_cancel"`. `409 form_not_open`, `409 turn_in_progress` and `429 turn_cap_reached` work as on `/messages`. Neither `resume` value is accepted on `/messages` (`422`) |
| `POST /conversations/{id}/messages` | customer | New gate after the agent OTP pause gate: a `text` body at `agent/profile_form` gets `409 form_required` |
| `GET /staff/handoffs/{id}/card-request` | agent (claimant; otherwise `404 not_found`) | `CardRequestPanel`, described after this table |
| `POST /staff/handoffs/{id}/card-request/decision` | agent (claimant) | Header `Idempotency-Key: <uuid>` (required, and it must be a UUID: otherwise `422`), body `{decision, credit_limit?: str, decline_reason?: str}`. The response and errors are described after this table |
| `POST /staff/handoffs/{id}/return` | agent | Adds `409 request_undecided` while the linked request is `pending` |
| SSE `cards_changed {}` on `conv:<id>` | — | Published after a verified approve or cancel. The customer UI invalidates `/me/cards` and `/me/cards/{id}` |
| SSE `ui {kind: "profile_form", payload: {card_kind}}` | — | Opens the form widget. The payload carries no form value (R5) |

`CardRequestPanel` contains:
- `request{reference, kind, card_kind, card_mask?, reason_code?, reason_label?, status, decision?}`;
- `customer{credit_score, segment, tenure_years, occupation, occupation_changed, income_display, income_changed}`;
- `cards[{mask, kind, status, balance_display, credit_limit_display}]`;
- `credit_bounds{currency, min, max, min_display, max_display}` (open credit only);
- `close_balance_display` (close only).

The `*_changed` flags come from `customer_profile_history` rows linked to this request. `reason_label` is filled by the staff route (`cancel_reason_label`), not by the cards service.

The decision response is `CardRequestDecisionResult{request, verified, message_id?}`. Errors:
- `409 not_claimant`, `409 already_decided`, `409 balance_not_zero` (D5).
- `422 decision_not_allowed`: approve/decline only on `open`; cancel/keep/not_cancelled_balance only on `close`.
- On a credit approve: `422 limit_out_of_bounds` (outside the bounds, or not a number) and `422 limit_required` (missing or blank). A debit approve ignores `credit_limit` (D14).
- `422 decline_reason_invalid`: missing, or not in `decline_reasons`.

A repeated `Idempotency-Key` returns the stored result and writes nothing; on the replay `message_id` is `null`, because nothing is posted again (D20, R-c). The steps, in order:
1. Lock the request row.
2. Validate.
3. Make the bank write and the request update in one transaction. The update also sets `handoff_id` (D20, R-a).
4. Re-read.
5. If verified, post the template as an agent message and publish `cards_changed` (approve/cancel).

An unverified read-back posts nothing and returns `verified: false` (R3).

### 6. Handoff packet and schemas

- `HandoffReason` gains `card_open_request | card_close_request`.
- `Queue` (`localization/format.py`) gains `creditos | retencion`, with labels ES "Créditos" / "Retención" and PT "Crédito" / "Retenção".
- The packet gains `card_request: {request_id, reference, kind: open|close, card_kind, card_mask: str|null, reason_code: str|null} | null` (null on every other packet).
- `verified_facts[].fact` gains `card_request_filed` (value = `reference`).

### 7. Staff accounts

`identity/provision.py` `_AGENT_NAMES` gains `"creditos": "Valentina"` and `"retencion": "Andrés"`. The usernames follow from the existing rule: `agent.creditos` and `agent.retencion`.

### 8. Templates (`conversation/templates.py`; placeholders filled in code, R4)

| Key | ES | PT |
|---|---|---|
| `card_request_approved_debit` | ¡Buenas noticias! Aprobamos tu nueva tarjeta de débito {card_mask}. Ya la puedes ver en tu inicio. | Boas notícias! Aprovamos o seu novo cartão de débito {card_mask}. Ele já aparece na sua tela inicial. |
| `card_request_approved_credit` | ¡Buenas noticias! Aprobamos tu nueva tarjeta de crédito {card_mask} con un cupo de {credit_limit}. Ya la puedes ver en tu inicio. | Boas notícias! Aprovamos o seu novo cartão de crédito {card_mask} com limite de {credit_limit}. Ele já aparece na sua tela inicial. |
| `card_request_declined` | Revisamos tu solicitud y por ahora no podemos aprobar una nueva tarjeta. Gracias por tu interés; puedes volver a intentarlo más adelante. | Analisamos a sua solicitação e, por enquanto, não podemos aprovar um novo cartão. Obrigado pelo interesse; você pode tentar novamente mais adiante. |
| `card_request_cancelled` | Listo: cancelamos tu tarjeta {card_mask}. Ya aparece como cerrada en tu inicio. | Pronto: cancelamos o seu cartão {card_mask}. Ele já aparece como encerrado na sua tela inicial. |
| `card_request_kept` | Tu tarjeta {card_mask} sigue abierta, sin cambios. Gracias por seguir con nosotros. | O seu cartão {card_mask} continua aberto, sem alterações. Obrigado por continuar com a gente. |
| `card_request_not_cancelled_balance` | Todavía no podemos cancelar tu tarjeta {card_mask}: tiene un saldo de {balance}. Cuando esté en cero, escríbenos y la cancelamos. | Ainda não podemos cancelar o seu cartão {card_mask}: ele tem saldo de {balance}. Quando estiver zerado, fale com a gente e nós o cancelamos. |
| `card_request_unavailable` (C7, Cardy, plus a human chip) | En este momento no puedo tramitar solicitudes de tarjetas por aquí. Si quieres, te paso con una persona del equipo. | No momento não consigo tratar pedidos de cartão por aqui. Se quiser, te passo para uma pessoa da equipe. |

`{card_mask}` is `mask_card(last4)` ("•••• 1234"). `{credit_limit}` and `{balance}` use the money formatter of the card's currency (MX: the ADR-014 label rules). The template language is the conversation language.

## Touch map

- `policies/`: `card_requests.yaml` (new); `tools.yaml` v6, `escalation.yaml` v10, `scope.yaml` v3, `playbooks.yaml` v2.
- `backend/app/domains/policy/`: `card_requests.py` (new), plus `registry.py`, `tools_policy.py` (new precondition keys), `scope.py` (`TOPICS` without `new_card`) and `escalation.py`.
- `backend/app/alembic/versions/0011_card_requests.py` (new).
- `backend/app/domains/cards/`: card requests in `repository.py`, `service.py` and `schemas.py` (create, decide, new product row, Cancel with history, eligibility reads).
- `backend/app/domains/customers/`: `service.py` and `repository.py` (profile update plus `customer_profile_history`, encrypted).
- `backend/app/domains/conversation/`:
  - `agent/plan.py`, `agent/confirm.py`, `agent/node.py`, `agent/step_up.py` (or a new `agent/card_request.py` for `agent_profile_form`);
  - `graph.py`, `state.py`, `ui.py`, `templates.py`, `intents.yaml`;
  - `nodes/abstain.py` and the `unsupported_intent` path (C7 fixed text);
  - `agent/reads.py` (`scope_facts` without `new_card`);
  - `tools/write.py`, `tools/executor.py`, `tools/postgres_writes.py`, `tools/fakebank.py`, `tools/handoff.py`;
  - `prompts/agent@v5.md` (new version: the `open`/`close` actions; no policy values).
- `backend/app/domains/handoff/`: `schemas.py` and `service.py` (reason, `card_request` block, return gate).
- Added mid-card: `backend/app/domains/analytics/cause_groups.py` (D18), `backend/app/domains/safety/vault.py` (D16), `conversation/agent/refs.py` (D19), `conversation/card_request_messages.py` (decision templates and labels) and `pipeline/load/postgres.py` (D20, R-e).
- `backend/app/domains/localization/format.py` (queues and labels); `backend/app/domains/identity/provision.py` (names).
- `backend/app/api/v1/`: `conversations.py` (profile-form routes, `form_required` gate) and `staff.py` (panel, decision, return gate).
- `frontend/src/`:
  - `components/chat/ProfileForm.tsx` (new) and the `ConfirmCard`/`ChatView` wiring;
  - the stream hook (`cards_changed` → invalidate);
  - `components/staff/CardRequestPanel.tsx` (new) with the review dialog, on `routes/staff/handoffs.$handoffId.tsx`;
  - i18n (ES/PT); `make client`.
- `backend/tests/unit/` and `backend/tests/integration/`: the tests below.
- Docs: `02` §1 (`card_cancel` tier; `new_card` no longer an abstain), §3 (pause `agent/profile_form`), §5 (queues `creditos`/`retencion` no longer Stretch; `new_card` abstain text), §6 (the decision panel); `03` §6 (0011 tables and columns, staff names); `04` §1 (`propose_plan` actions, the two tools), §3 (routes, gates, SSE), §4 (reasons, `card_request`), §5 (the policy files).

## Test list (test budget: R-rules touched, one per "Done when" line, ES and PT happy paths; fake LLM throughout)

| # | Task | Test | Proves |
|---|---|---|---|
| T1 | C1 | `test_card_requests_policy_loads` (unit) | `card_requests.yaml` validates with its `provenance` header. A file missing it, or with `min ≥ max`, is refused at startup (R8, Done when C1) |
| P1 | C1 | Runnable: `make check`, then `make seed-identity`, then log in `agent.creditos` and `agent.retencion` and `GET /staff/handoffs` | `make check` is green, and each agent logs in and sees its queue (Done when C1) |
| T2 | C2 | `test_profile_form_values_never_reach_llm_ui_or_checkpoint` (unit) | After a submit with changed values, no value appears in the fake LLM's input, in any `app.messages.ui_payload` or in the checkpointed state. State holds only `profile_changed_fields` (R5) |
| T3 | C2 | `test_profile_form_cross_customer_404` (integration, in `test_r13_ownership.py`) | Customer B's GET and POST on A's conversation get `404`, and A's profile is unchanged (R1/R13). The existing route-introspection test covers the new routes' role dependency |
| T4 | C3 | `test_open_credit_es_happy` (unit, flow) | ES: credit → form (one field changed) → OTP → Acepto ends in a queued `creditos` handoff with `card_request.kind=open`. The profile and history rows are saved, and the request is `pending` (Done when C3) |
| T5 | C3 | `test_open_debit_pt_happy` (unit, flow) | The same in PT for debit, with no field changed (Done when C3) |
| T6 | C3 | `test_open_nothing_written_before_accept` (unit) | At the form, OTP and plan-card pauses, and after No acepto: `bank.customers`, `card_requests` and `customer_profile_history` are unchanged and no handoff exists (R2, Done when C3) |
| T7 | C3 | `test_open_failed_check_no_handoff[customer_not_active, card_past_due, card_cap_reached, request_pending]` (unit, parametrized) | Each check is rejected with its code, and there is no request, no handoff and no write (Done when C3, D9) |
| T8 | C3 | `test_request_card_unverified_readback` (unit) | A read-back mismatch gives `verified=false`, no "done" and the `action_unverified` path (R3) |
| T9 | C4 | `test_close_es_happy` (unit, flow) | ES: card → reason → `close_balance` stated → OTP → Acepto ends in a queued `retencion` handoff whose packet carries `reason_code` (Done when C4) |
| T10 | C4 | `test_close_pt_nonzero_balance_happy` (unit, flow) | PT, balance ≠ 0: the same, still a `retencion` handoff with `reason_code` (Done when C4) |
| T11 | C5 | `test_decision_non_claimant_refused` (integration) | Another agent's decision is refused and nothing is written. Return is `409 request_undecided` while the request is pending (R13, Done when C5) |
| T12 | C5 | `test_decision_limit_out_of_bounds` (integration) | Approve credit with a limit outside `credit_limit_bounds` gets `422` and no product row (Done when C5) |
| T13 | C5 | `test_cancel_nonzero_balance_writes_nothing` (integration) | `409 balance_not_zero`: product, history, request and audit decision events are unchanged (Done when C5, D5) |
| T14 | C5 | `test_decision_idempotency_key_writes_once` (integration) | Two approves with the same key give one product row, one request update and the same `request` and `verified`; the replay's `message_id` is `null` (D20, R-c) (Done when C5) |
| T15 | C5 | `test_decision_message_only_after_verified_readback` (unit) | An unverified read-back posts no agent message and no `cards_changed`. A verified one posts the template (R3) |
| T16 | C6 | `test_decision_templates_fill_in_code[es, pt]` (unit) | All six decision templates render with `{card_mask}`/`{credit_limit}`/`{balance}` filled by code formatters and no stray brace (R4) |
| P2 | C6 | Browser (verifier), ES | A persona asks for a credit card, Valentina approves with a limit, and the card appears on the home with no reload (Done when C6) |
| P3 | C6 | Browser (verifier), PT | The same persona closes that card, Andrés cancels, and it shows as closed with no reload (Done when C6) |
| T17 | C7 | `test_card_requests_off_path[flag_off-open, flag_off-close, llm_down-open, llm_down-close]` (unit, parametrized) | The fixed `card_request_unavailable` text plus a human offer, with no request and no write (Done when C7) |

The legacy flows and the baseline are covered by the existing suite in the verifier's single full run. Each task runs only its own tests.

## Boundaries

- **Always:**
  - Take `customer_id` from `ToolContext` or the session only (R1), in the form routes, `request_*` and the panel.
  - Keep eligibility, bounds, cap, reasons and the zero-balance rule in code reading `card_requests.yaml`, never in `agent@v5` or the playbooks (R8).
  - Format money and card masks in code (R4).
  - Keep form values only in the vault until Acepto (R5).
  - Post decision templates only after a verified read-back (R3).
  - Write the history row in the same transaction as each in-place update (R12).
- **Ask first:**
  - Any change to `nlu@v7`, the `Intent`/`Topic` literals, `intents.yaml` beyond the `card_cancel` row, or the trained classifier.
  - Any new `AuditType`.
  - Dropping a test from the list above.
  - Applying the "If behind" cut (D1).
- **Never:**
  - Give the agent a tool that executes a write, or show it the token, the form values, the decline reason or the bounds (R6).
  - Show the decline reason to the customer.
  - Write before Acepto (R2) or before the staff click.
  - Edit `eval/scenarios/heldout/` (R9).
  - Commit `data/` or the staff credential CSVs (R10).

## Success criteria

1. **C1:**
   - `make check` exits 0.
   - `policies/card_requests.yaml` starts with `provenance: team-generated-synthetic`.
   - After `make seed-identity`, `POST /auth/staff/login` works for `agent.creditos` and `agent.retencion`, and `GET /staff/me` shows `queue` `creditos` and `retencion`.
   - `scope.yaml` has no `new_card` key.
   - `alembic upgrade head` on a fresh DB creates `app.card_requests` and `app.customer_profile_history`, and `bank.products` has `origin`, `created_at` and `conversation_id`.
2. **C2:** T2 and T3 pass.
3. **C3:** T4–T8 pass.
4. **C4:** T9 and T10 pass.
5. **C5:** T11–T15 pass.
6. **C6:** T16 passes, and the verifier records P2 (ES) and P3 (PT) in the browser on the dev stack with `AGENT_ENABLED=true`, each with no page reload.
7. **C7:** T17 passes, and the existing baseline and legacy flow tests pass unchanged in the full run.
8. `02`, `03` and `04` describe the new tools, queues, routes, SSE events and packet fields, as listed in the touch map.

## Open questions

- Persona for P2/P3: the verifier picks a demo persona that passes the checks (Active, no past due, under the credit cap). For example CLI-U6NAXZG11P97 (MX) has 1 credit and 1 debit card with no past due. CLI-F7PQP3J4AS6X (3 credit cards) can demo `card_cap_reached`. The verifier decides at P2. This spec adds no new persona.
- Whether `make demo-reset` on prod runs before or after this card merges is a D9 deploy step, decided by the human per `07` D9.
- A card with no `current_balance` on record, at the staff click. D19 settles only what the customer is told. Today Cancel on such a card is refused with `409 balance_not_zero`, and the `not_cancelled_balance` template has no balance to fill in. The human decides what the staff side should do.
