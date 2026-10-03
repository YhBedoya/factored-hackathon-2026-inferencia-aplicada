# Spec: D8-H — Handoff v2: G10 handoff packet and staff screens

Card D8-H · `07` D8 section, rows H1-H3 (an exception to the D8 rule; `07` §8 row "D8 | Handoff v2"). It must merge before the 18:00 freeze on 2026-10-04 or it is dropped. Branch `feat/d8-h-handoff-v2`. The card touches the handoff packet and an LLM node, so it is safety-critical and the other dev reviews it (ADR-018).

Builds on [`d4-a-escalation-handoff-deploy.md`](d4-a-escalation-handoff-deploy.md) (packet, staff API) and [`d4-b-disputes-handoff-screens.md`](d4-b-disputes-handoff-screens.md) (staff screens).

## Objective

The staff agent today gets a one-line `request` written blind: the LLM sees no transcript, `{tx_count}` is always offered, and the packet is empty when a flow was abandoned. The motivating case is HO-293FB42E: the bot wrote "Ha realizado 0 transacciones con la tarjeta •••• 9118". This card fixes that in three parts:
- **H1** The packet gains an LLM-written case summary (`asked`, `did`, `unfinished`). The LLM reads the masked transcript and may write numbers only through bounded placeholders that code fills. The packet also gains code-built fields: focus card, routing, risk, customer history and friction.
- **H2** The staff API shows the summary and the time in queue on inbox rows before claim. The transcript stays claim-only.
- **H3** The staff screens get an inbox preview and a redesigned packet view.

It serves the three D8-H "Done when" lines.

## Assumptions (accepted by the human with the answers)

AS1. One LLM call with the new prompt `handoff_summary@v2` (pinned and traced, R7). The degraded and `LLM_DISABLED` paths keep the fixed per-reason text (R11).
AS2. The transcript is `app.messages.content_masked`, oldest first, the last 30 messages, each cut to 500 chars. The customer message of the current turn is already persisted by the runner before the graph runs (`runner.py`).
AS3. A placeholder is offered only when code has a value for it.
AS4. Focus card = state `selected_card_id` → `get_card_details` → `<type> •••• <last4>`, otherwise `null`.
AS5. Routing is code-built from `resolve_escalation`, extended to return the branch it took.
AS6. Risk signals are snapshotted before the `handoff` node resets `priority_flags` and `unauthorized_attempts`.
AS7. Time in queue is computed by the client from `created_at` → now (or → `claimed_at`). The table already has `claimed_at`, so no migration.
AS8. The inbox SSE events carry the widened `HandoffSummary`, and the generated client is regenerated.
AS9. Stored packets still validate: every new field is optional (`null` / `[]`), and the UI falls back to `request`.
AS10. The packet stays in its JSONB column. `04` §3 and §4 are updated, `02` is not.
AS11. Staff labels go into the existing i18n (ES/PT). The summary is in the packet `language`.
AS12. All tests use a fake LLM.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | The case summary is written fully by the LLM from the masked transcript. The `handoff_summary` node now sees customer text, which is an intended change from D4-A D10. It keeps no tools (R6) and sends only tokenized text (R5) | Human pre-decision 1; `07` H1 |
| D2 | Numbers come only from bounded placeholders filled in code. `{card_mask}` comes from the focus card, `{plan_card_mask}`/`{tx_count}` from the **last unanswered `ui.confirm`** in the persisted transcript (its step facts `card_mask`, `tx_count`), and `{queue_label}` is always offered. `{tx_count}` keeps today's source, `len(handoff_evidence)`, when evidence is non-empty, so the fraud path is unchanged. A draft with a raw digit, an unknown placeholder or a brace residue in **any** field → fallback (R4) | Human Q1 a); existing `handoff_summary.py` rule |
| D3 | "Unanswered" `ui.confirm` = the last bot message carrying a `confirm` payload where no **later** bot message belongs to a turn without a customer message. Button decisions (confirm/cancel/OTP) run with `text=None` and persist no customer message (`runner.py`). This is read from the transcript, not from bot state, so it does not track interrupted flows | Human Q1 a) ("last unanswered ui.confirm in the persisted transcript"); pre-decision 4 (no flow tracking in state) |
| D4 | The single call returns `request` (≤200, kept as the inbox one-liner) and `case_summary{asked, did, unfinished}` (each ≤280). On any rejection or `LLMError`, `request` = today's fixed per-reason text, `case_summary = null`, and there is no second call (R11) | Human Q2 a); R11. The field is named `case_summary` (not `summary`) because `HandoffDetail.summary` already exists |
| D5 | Focus card, routing, risk, history and friction are computed in the `handoff` node at creation and frozen into the packet | Human Q3 a); `04` §4 "every other field is assembled in code" |
| D6 | History is read through a new session-bound `HandoffTools.history()` that takes no customer argument (R1). It returns up to 5 earlier handoffs of this customer (other conversations) and up to 5 claims (`bank.complaints`, via `disputes.service`), within `history_days`. A failed read → `history = null`, and the handoff still goes ahead | Human Q3 a), Q6 a); R1; R11 (never block the handoff) |
| D7 | `policies/escalation.yaml` v8 adds `handoff_packet: {history_days: 90}` | Human Q6 a); R8 |
| D8 | Graph state gains cumulative `friction{clarifications, abstentions, non_answers}`. It is incremented where `clarification_failures` and `non_answer_failures` increment and once per turn routed to `abstain`. No flow resets it. `return_to_bot` clears it | Human Q4 a) |
| D9 | `HandoffSummary` gains `request`, `case_summary` and `claimed_at`. The transcript route keeps `get_claimed_conversation` (`404` when unclaimed). The packet view links to `/staff/conversations/{id}` | Human pre-decision 2; `07` H2; R13 |
| D10 | Proof for H1: a hand-written masked fixture of the HO-293FB42E turns plus a fake-LLM test, and **one live replay with the real model**, run by the verifier and reused for the H3 browser check. No DB export goes into the repo (public repo, R10) | Human Q5 a) |
| D11 | Out of scope: a customer-context block, flow-interruption tracking in state (`enqueue` dropping the plan stays), a "suggested next step", and the wrong-queue routing fix | Human pre-decision 4 |

## Contracts (delta only; everything else is `04` §3, §4)

**Packet** (`app/domains/handoff/schemas.py`, frozen, `extra="forbid"`; the new fields default to `None`):
```python
class CaseSummary(_Frozen):        # LLM-written, placeholders already filled (D4)
    asked: str = Field(max_length=280)
    did: str = Field(max_length=280)
    unfinished: str = Field(max_length=280)

class Routing(_Frozen):
    reason: HandoffReason
    queue: Queue
    branch: Literal["rule", "flow", "by_flow", "default"]   # rule queue | queue set by the flow | human_request_queues.by_flow | .default
    flow: str | None                                        # pending flow used for by_flow, else None

class RiskSignals(_Frozen):
    priority_flags: list[str]
    legal_keyword: bool          # legal_hit() on this turn's masked text, or reason == legal_regulator
    unauthorized_attempts: int

class PastHandoff(_Frozen):  reference: str; reason: HandoffReason; queue: Queue; status: HandoffStatus; created_at: datetime
class PastClaim(_Frozen):    claim_id: str; category: str | None; status: str | None; created_at: datetime | None
class CustomerHistory(_Frozen): days: int; handoffs: list[PastHandoff]; claims: list[PastClaim]   # each ≤5, newest first

class Friction(_Frozen): clarifications: int; abstentions: int; non_answers: int

HandoffPacket += case_summary: CaseSummary | None = None
                 focus_card: str | None = None            # "Crédito •••• 9118", built in code (R4)
                 routing: Routing | None = None
                 risk: RiskSignals | None = None
                 history: CustomerHistory | None = None
                 friction: Friction | None = None
HandoffSummary += request: str; case_summary: CaseSummary | None; claimed_at: datetime | None
```
`04` §4 sentence "`request` is the only LLM-written field" becomes "`request` and `case_summary` are the only LLM-written fields". `04` §3 `HandoffSummary` shape gets the three fields.

**LLM step** `handoff_summary@v2`: structured output `HandoffSummaryDraft{request, asked, did, unfinished}`. User message: language, reason, queue, the placeholders on offer, and the transcript as `role: masked text` lines, all inside one data fence (R6).

**Graph state** (`conversation/state.py`): `friction: NotRequired[dict[str, int]]` (keys as `Friction`); `return_to_bot` sets it to zeros.

**Escalation** (`policy/escalation.py`): `resolve_escalation` result gains `branch` and `flow`; `EscalationPolicy` gains `handoff_packet: {history_days: int}`.

**Tools**: `HandoffTools.history(days: int) -> CustomerHistory | None` (Protocol, `InMemoryHandoffTools`, `ServiceHandoffTools` bound to `ToolContext.customer_id`, excluding `ctx.conversation_id`). `handoff.service.customer_history(customer_id, exclude_conversation_id, days, limit)` reads `app.handoffs ⋈ app.conversations` and calls a new `disputes.service.recent_claims(customer_id, since, limit)`.

## Touch map

- `backend/app/domains/conversation/nodes/handoff_summary.py`: transcript, placeholders, the new draft schema, validation over all fields
- `backend/app/domains/conversation/prompts/handoff_summary@v2.md` (new, ES and PT examples)
- `backend/app/domains/conversation/nodes/handoff.py`: build the new packet fields
- `backend/app/domains/conversation/state.py`, `graph.py` (friction increments), `takeover.py` (`return_to_bot` clears friction)
- `backend/app/domains/conversation/tools/handoff.py`: `history()`
- `backend/app/domains/conversation/baseline/template_compose.py`: degraded path leaves `case_summary` null
- `backend/app/domains/handoff/{schemas,repository,service}.py`
- `backend/app/domains/disputes/{service,repository}.py`: `recent_claims`
- `backend/app/domains/policy/escalation.py`, `policies/escalation.yaml` (v8)
- `frontend/src/components/staff/InboxList.tsx`, `PacketView.tsx`, `frontend/src/routes/staff/handoffs.$handoffId.tsx`, `frontend/src/lib/i18n/`, `frontend/src/client/` (regenerated)
- `docs/solution-docs/04-contracts.md` §3, §4, §5 (escalation.yaml v8 line)
- Tests below

## Test list

| Test | Proves |
|---|---|
| `unit/test_handoff_summary_v2.py::test_replay_ho293fb42e_es` | H1 Done-when, using the hand-written masked fixture (D10). The fake LLM returns `{tx_count}` and `{plan_card_mask}`. The filled `case_summary` contains `2` and `•••• 9118`, and no packet field contains `0 transacciones`. `{tx_count}` is not offered when there is no evidence and no unanswered confirm (bug regression) |
| `…::test_pt_happy_path` | The PT summary is filled and `request` is in PT |
| `…::test_r4_raw_digit_falls_back` | A raw digit or an unknown placeholder in any of the 4 fields → fixed per-reason `request`, `case_summary` null |
| `…::test_r5_only_masked_text_sent` | The raw `content` (a name) never reaches the fake LLM, only `content_masked` |
| `…::test_r11_llm_error_one_call` | `LLMError` → fallback, exactly one LLM call |
| `unit/test_graph.py` (existing R6 check) | `handoff_summary` still holds no tools. Extend it only if it does not cover the node |
| `unit/test_handoff_packet.py::test_packet_v2_code_fields` | Routing branch (`by_flow` vs `default`), risk snapshot, friction counted across two flows and cleared by `return_to_bot`, history from `InMemoryHandoffTools`, `history=None` on a failed read |
| `unit/test_handoff_packet.py::test_r1_history_session_bound` | `HandoffTools.history` takes no customer argument, and the service is called with `ctx.customer_id` |
| `integration/test_staff_round_trip.py` (extend) | H2: `GET /staff/handoffs` rows carry `request`, `case_summary`, `claimed_at`; `GET /staff/conversations/{id}/messages` → `404` on a queued, unclaimed case (R13) |
| Live replay (verifier, real model) | H1 on the real model: replaying the HO-293FB42E turns on the local stack gives a summary naming the 2 movements on •••• 9118 and the unconfirmed block |
| Browser check (verifier) | H3 in ES and PT on the replayed case |

## Boundaries

- **Always:** use only `content_masked`; offer placeholders only when they have values; build every number, date and card mask in code; keep transcript access claim-only; never block a handoff on the summary or history.
- **Ask first:** any change to queue routing; adding a new `HandoffReason`; any Alembic migration; a second LLM call.
- **Never:** give `handoff_summary` a tool or token; read history by an id from the LLM or the chat; commit a DB export of the real conversation; touch `eval/scenarios/heldout/`; add the out-of-scope items from D11.

## Success criteria

1. `cd backend && uv run pytest tests/unit/test_handoff_summary_v2.py tests/unit/test_handoff_packet.py tests/unit/test_graph.py` passes.
2. `make check` passes (lint, mypy, import-linter, unit tests).
3. The `test_staff_round_trip.py` integration tests pass, including the `404` on an unclaimed case.
4. Verifier live replay: after replaying the HO-293FB42E turns (status → •••• 5611 → movements → "sospechoso, bloquear" → •••• 9118 → mark 2 → confirm shown → "¿qué es reportarla como perdida?" → "Quiero hablar con un asesor"), `SELECT packet->'case_summary', packet->>'request' FROM app.handoffs` for that conversation names 2 movements, `•••• 9118` and the unconfirmed block, and contains no `0 transacciones`. The packet has a non-null `focus_card`, `routing.branch`, `risk`, `history` and `friction`.
5. In the browser, in ES and PT: the inbox row shows the summary and a running time in queue before claim. After claim, the packet view shows summary, focus card, routing, risk, history, friction and a working link to `/staff/conversations/{id}`, next to the conversation.
6. `policies/escalation.yaml` is `version: 8` with `handoff_packet.history_days: 90`. `04` §3, §4 and §5 reflect the contracts above.

## Open questions

None blocking. Live-replay wording quality depends on the real model and the prompt. If the live replay misses the Done-when, the verifier reports it, and the human decides whether to iterate on the prompt (v3) or accept it before the freeze.
