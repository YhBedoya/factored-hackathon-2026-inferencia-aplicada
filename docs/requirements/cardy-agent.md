# Requirement: Cardy as an agent (human-like conversation, complex requests)

Status: **draft for review** · Date: 2026-10-02 · Owner: to be set at spec time · Architecture: a new ADR-035 that amends ADR-002 (written in slice 1).

This document is the input for `/wave-run`. It holds four cards, one per slice (S0–S3). Each `/wave-run` reads the shared sections plus its own slice section, and the `spec-writer` turns that into `docs/specs/<slug>.md`. It fixes what is built, why, and how "done" is judged. It does not fix implementation details. The open questions at the end are answered at spec time.

| Card | Slug | Scope |
|---|---|---|
| `REQ-cardy-agent-s0` | `cardy-agent-s0-empty-reply` | Fix the empty reply in the current pipeline |
| `REQ-cardy-agent-s1` | `cardy-agent-s1-conversation-reads-block` | Agent foundation, conversation, reads, lock and block for one or several cards |
| `REQ-cardy-agent-s2` | `cardy-agent-s2-unlock-replacement` | Unlock and replacement on the agent path |
| `REQ-cardy-agent-s3` | `cardy-agent-s3-unrecognized-charge` | Unrecognised charge on the agent path |

## Problem

Cardy must be a human-like assistant that, inside the restrictions of a banking system, talks naturally with customers and solves complex requests that affect one or more cards with one or more intents. Today it behaves like a form, and on a complex request it sends nothing.

The conversation that motivates this requirement:

```
cliente: Hola Cardy, como estas bbcita?
cardy:   ¡Hola de nuevo, Gustavo Miguel! Cuéntame, ¿en qué te ayudo con tus tarjetas?
cliente: Quiero bloquear mis tarjetas
cardy:   ¿Cuál tarjeta quieres bloquear?
cliente: Todas
cardy:   (empty reply)
```

### Why the reply is empty

1. "Todas" cannot be represented. The only card slot is `card_hint`, limited to `credit`, `debit`, `focus`, `other` or `last4:NNNN` (`conversation/schemas.py`). The NLU returns no intent and no slot.
2. `nodes/route.py` finds that the answer does not fit the open question and that there is no intent, and falls through to `enqueue`.
3. `nodes/next_intent.py::enqueue` builds an empty queue and, because a question was open, cancels the plan and deletes the open question.
4. `finish` joins zero segments into `""` and sends it.

Any message with no intent and no recognised slot ("las dos", "no sé cuál", "espera") takes the same path. The dev database holds one `reply_sent` event of length 0 out of 54, on the route this trace predicts. The path was traced in code and not reproduced live.

### Why Cardy sounds like a robot

The banking rules limit what Cardy may **do**, and the tool layer already enforces them. A second, self-imposed layer keeps the LLM out of the conversation, and that layer is what makes Cardy a form:

- **The LLM never talks to the customer.** It is called twice per turn: `understand` classifies the message into a closed list of 26 intents, and `compose` rewords a few facts. Everything else is a fixed template.
- **The schema is closed and turn-wide.** One set of slots serves the whole turn, so "block the credit one and tell me what I owe on the other" cannot carry two cards. One open question, one selected card and one confirmation exist per conversation.
- **The writer is blind.** `compose` sees the names of the facts, never the values, and is forbidden to offer something or to ask a question. It cannot compare two balances or work out which charge the customer means.
- **Small talk and out-of-scope are scripted.** `smalltalk.py` returns fixed templates; `abstain` follows a prescribed four-step order and may not comment on the topic. ADR-002's read-only answer node was never built, and `general_question` has no node.
- **Flows are single-card and single-action.** `card_select` resolves exactly one card and `card_block` plans one step.

## Proposed solution

Cardy becomes an agent, and code stays as the rail. Seven decisions, taken with the product owner on 2026-10-02:

| # | Decision | What it means |
|---|---|---|
| D1 | **Cardy drives the turn** | One LLM loop per turn reads the masked conversation, calls read tools and writes the reply itself. |
| D2 | **Propose, never execute** | Cardy's only write capability is `propose_plan`. Code validates the plan, issues the token and keeps it in server state, renders the card list and the warning, executes, and reads back. Confirmation comes from the button or from a narrow yes/no reader that is separate from the agent and sees only the customer's message. Anything that is not a clean yes leaves the plan unconfirmed. Code rejects a reply that claims an action that was not verified. |
| D3 | **Sees values, writes references** | Tool results reach Cardy already formatted by code, each with a reference. Cardy reasons over the values and writes the reference; code fills it in. The existing "no digit outside a placeholder" check stays. |
| D4 | **Preconditions on the tools** | Each write declares in policy YAML what it requires, and code checks it when a plan is proposed. A rejected plan returns its reason to Cardy, who asks for what is missing in its own words. Playbooks per request type are loaded from YAML and only guide. |
| D5 | **Current pipeline is the degraded path** | After two failed retries, or with `LLM_DISABLED`, the turn runs on the classifier, flows and templates, as ADR-032 describes. |
| D6 | **Agent in front, one request type at a time, behind a flag** | The agent takes every turn. A request type that is not migrated yet is passed to its existing flow. A setting turns the agent on or off. |
| D7 | **Hybrid outcome labels** | Cardy names the request type from the existing catalog and says whether it answered, asked or redirected. Code decides the status of anything that involves a write or a handoff. |

### A turn on the agent path

1. The session is loaded as today. `customer_id` comes only from the session.
2. Cardy sees the masked history, its persona (`docs/brand.md`), the playbooks, and tool results inside data fences.
3. Cardy calls the audited read tools as needed. The number of rounds per turn is bounded.
4. For a write, Cardy calls `propose_plan` with one step per action (two cards are two steps). Code checks ownership, policy and preconditions, then issues one plan token through `ConfirmedWriteTools.issue_plan` and emits the confirmation card.
5. On confirmation, code runs the plan through the existing executor. Each step must match the plan exactly, and each has its own read-back. On the first failed or unverified step the plan is cancelled and the case is handed off with what was and was not applied (ADR-027).
6. Cardy writes the result message from the verified results, with references.
7. The turn's audit record is written with the same shape as today.

### Rules

| Rule | Effect |
|---|---|
| R1, R2, R3, R5, R7, R11, R13 | Unchanged. R2 and R3 are enforced by the existing executor, which the agent cannot bypass. |
| R4 | Unchanged. The model never writes a number, date or card mask (D3). |
| R6 | Reworded: an LLM node that reads tool output may **propose** a plan and may never **execute** a write. The graph test is updated to guard that the agent holds no executing tool and never sees the token. |
| R8 | Unchanged in intent. The per-intent allowlist in `policies/tools.yaml` (`allowed_intents`) is replaced by per-tool preconditions (D4), because on the agent path the intent label comes from the model. |
| R9 | Unchanged. `eval/scenarios/heldout/` is not touched. |

### Contracts that stay as they are

The staff timeline, the eval checks (`eval/harness/checks.py`) and the analytics worker read the audit trail, not reply text. The agent path keeps that contract:

- tool calls are audited under their current names, through the same recorders;
- `reply_sent` carries `route` (`abstain` for a redirect), `degraded`, `fact_values` and `segments: [{intent, route, status, awaiting_slot?}]`, built per D7;
- a plan awaiting the customer's yes is an `awaiting` segment with slot `confirmation`; a clarifying question is an `awaiting` segment with another slot;
- handoffs use the existing reasons; a new reason gets a line in `analytics/cause_groups.py`.

## Expected result

Illustrative conversations. The wording is Cardy's own each time; none of these lines is a template.

```
cliente: Hola Cardy, ¿cómo estás?
cardy:   ¡Todo bien, gracias por preguntar! ¿En qué te ayudo con tus tarjetas?

cliente: ¿Cuál es la capital de Colombia?
cardy:   Qué buena pregunta, pero ahí no te puedo ayudar. Con tus tarjetas sí: ¿qué necesitas?

cliente: Quiero bloquear mis tarjetas
cardy:   Claro. ¿Las quieres bloquear temporalmente o de forma definitiva?
cliente: Temporal, todas
cardy:   Voy a bloquear temporalmente estas tarjetas:
         [confirmation card rendered by code: •••• 5214 · •••• 7854 · Confirmar / Cancelar]
cliente: sí
cardy:   Listo, tus tarjetas •••• 5214 y •••• 7854 quedaron bloqueadas.
```

What must be true when all slices are done:

- No turn ends with an empty reply, on either path.
- Greetings, small talk and out-of-scope questions are answered in Cardy's voice, kind and proactive, with no fixed template on the agent path.
- One message may carry several requests and several cards, and they are handled together.
- No write runs without the customer's confirmation of the exact plan shown, and "done" is said only after a verified read-back. The eval's unsafe checks (`confirm_before_act`, `readback_before_done`, `tools_forbidden`, `db_state`, `no_raw_pii`) pass on the agent path.
- With the flag off, or with the LLM down, behaviour is the current pipeline.
- The dashboard, the staff timeline and the eval harness work on agent conversations without a redesign.

No metric target is set here. The system is still changing, and performance evaluation is postponed until it is stable.

## Slices

Every slice follows the test budget of `/wave-run`: unit tests for the safety rules it touches, one ES and one PT happy path per flow, always with a fake LLM.

### S0 · Empty reply in the current pipeline

Independent of the agent. It is needed in any case, because this pipeline stays as the degraded path (D5).

**What is built**
1. A message that does not answer the open question and carries no intent keeps the open question and its plan, and re-asks. It counts toward `clarification_failures`, so the existing `clarification_exhausted` handoff still applies.
2. `finish` never sends an empty reply. A turn with no segment ends in the safe fallback.

**Done when**
- The transcript above ("Todas" after "¿Cuál tarjeta quieres bloquear?") gets a non-empty reply and the open question survives. One test in ES, one in PT.
- A turn that produces no segment sends the fallback, not `""`.

### S1 · Agent foundation, conversation, reads, lock and block

**Depends on:** nothing. S0 is independent of it.

**What is built**
1. **Tool-calling loop** in `backend/app/core/llm/`, next to `structured`. Pinned model, prompt version and temperature, traced in Langfuse and `audit.llm_calls` under a new step name, with bounded rounds and the existing retry rule (R7, R11).
2. **The agent node and the flag.** With the flag on, every bot-mode turn enters the agent. With it off, nothing changes. An `LLMError` after the retries moves the turn to the current pipeline with `degraded: true`.
3. **Conversation.** Greetings, small talk, thanks and closing, out-of-scope redirects and clarifying questions are written by Cardy from its persona. Scope facts still come from `policies/scope.yaml`.
4. **Reads.** Card status, balance due, debit balance, transaction search and decline explanation, through the existing audited read tools. Values arrive formatted with references (D3); the fill and the digit check from `nodes/compose.py` are reused. Transaction lists stay code-rendered UI.
5. **`propose_plan`, the plan check and confirmation (D2, D4).** Preconditions for `cards.lock_card` and `cards.block_card` move from `flows/card_block.py` into policy YAML and a code validator. One plan may hold several cards. The yes/no reader, the code-rendered confirmation card and the claims check are part of this item.
6. **Passing a turn to an existing flow.** Unlock, replacement, unrecognised charge and a request for a human go to the current pipeline until their slice lands.
7. **Outcome labels and audit record (D7)**, so the eval, the timeline and analytics read agent turns.
8. **Analytics.** A cost column and chart series for the agent step, and a field that says which path served the conversation.
9. **Docs.** ADR-035, the rewording of R6 in `06`, and the changed parts of `02` and `04`.
10. **Dev scenarios** for small talk, an out-of-scope redirect, a multi-card block and a two-request message, in `eval/scenarios/dev/` only.

**Build order:** 1 → 2 → 3 and 4 → 5 → 6, 7 → 8, 9, 10.

**Done when**
- The three conversations in "Expected result" work in the browser in ES and PT with the flag on.
- "Bloquea la de crédito y dime cuánto debo en la otra" is handled in one conversation.
- Safety tests: a plan step for another customer's card is refused (R1); the agent holds no executing tool and never sees the token (R6); a write without a consumed confirmation is impossible and a replayed or reordered step is rejected (R2); a reply claiming an unverified action is replaced (R3); a digit outside a reference is rejected (R4).
- "Sí, pero solo la 5214" does not confirm the open plan.
- With the flag off, the existing flow tests pass unchanged. With a forced LLM failure, the turn is served by the current pipeline.
- A finished agent conversation appears in the dashboard with its intents, outcome and cost.

**If behind:** ship items 1–4 and 6–7 (conversation and reads), and pass lock and block to the existing flow as well. Item 5 then becomes the first task of the next session.

### S2 · Unlock and replacement

**Depends on:** S1.

**What is built**
1. Preconditions and playbooks for `cards.unlock_card` and `cards.order_replacement`, moved from `flows/card_unlock.py` and `flows/replacement.py`.
2. OTP step-up on the agent path. Step-up happens before the plan is shown (ADR-027).
3. The replacement offer after a permanent block, made by Cardy and marked `bot_offered` in the segment.

**Done when**
- Unlock and replacement work in the browser in ES and PT with the flag on, including the OTP.
- A plan that needs step-up cannot be issued without a valid one (R2 test).
- A declined replacement offer is recorded as `cancelled` and `bot_offered`.

### S3 · Unrecognised charge

**Depends on:** S1. Independent of S2.

**What is built**
1. Preconditions for `disputes.create_claim`: every question in `policies/disputes.yaml` answered, and the charges owned by the customer.
2. The compromise rule and the priority flags stay in code and may add the block step to the plan or force the handoff.
3. The two-step plan (block, then claim) and the handoff to Fraudes with its evidence, as today.

**Done when**
- A single-charge claim and a suspected-compromise case work in ES and PT with the flag on.
- A claim with a missing answer or a foreign transaction id is refused (R1, R8 tests).
- The handoff packet carries the same fields as today.

## Timeline and risks

- **Time.** Today is D6. The code freeze is Sunday 4 October at 18:00 and the submission is Monday 5 October (`07-execution-plan.md`). The plan gives D7 to the held-out report and to fixes from dev failures, and its D8 rule allows new features only if the held-out report shows 0 unsafe outcomes. This requirement is a new feature outside that plan, so running it is a decision of both developers.
- **The flag is the safety net.** It ships off. Turning it on for the submission is a human decision taken after S1 is verified.
- **Safety-critical.** S1–S3 touch the tool layer and policy, so the other developer reviews each PR before merge (ADR-018).
- **Cost and latency.** The agent makes several LLM calls per turn on a larger model. Both rise, and nothing here measures by how much.
- **Injection.** Cardy now reads tool output and customer text in the same loop that can propose a plan. The worst case is a proposed plan that the customer must still confirm on a code-rendered card. A false statement that is not about an action or a number is not caught by any check.
- **Two systems.** The current pipeline stays for outages and for non-migrated types, so a policy change has to hold on both paths. The shared executor covers writes.
- **Eval scripts.** Dev and held-out scenarios send fixed turns. If Cardy asks a different question than the flow did, a scripted answer may no longer fit.

## Out of scope

- Removing the current flows, templates or classifier.
- A cancel-card tool. "Cancelar" stays a permanent block.
- New request types from the stretch list.
- Changes to the held-out suite, the simulator or the judge.
- Streaming the reply token by token.

## Open questions (for the spec)

1. **Agent model.** Which model, prompt version and temperature to pin, and the maximum tool rounds per turn.
2. **Flag.** Its name and whether it is global or per conversation.
3. **Passing a turn to a flow.** How the agent hands a non-migrated request to the current pipeline, and how later turns of that flow reach it while its question is open.
4. **Handoff on request.** Whether "quiero hablar con una persona" is passed to the existing handoff node in every slice, or the agent gets a tool whose effect code decides from `policies/escalation.yaml`.
5. **Clarified outcome in the eval.** The harness marks a turn as clarified from the open slot name or from `nlu_result` status. Either the agent path records an `nlu_result`-shaped event built from Cardy's label, or `outcome` in `eval/harness/checks.py` learns to read the segment.
6. **Precondition schema.** Where preconditions live (`policies/tools.yaml` or a new file) and what replaces `allowed_intents` for the degraded path, which still passes an intent.
7. **Yes/no reader.** A small LLM call, the trained classifier's `affirm` and `deny` labels, or both.
8. **Derived numbers.** Whether S1 needs a tool for a sum or a comparison, or Cardy only reports the values the tools return.
9. **S0 behaviour.** Whether an unrecognised answer re-asks with the same template or with the existing clarification wording.
