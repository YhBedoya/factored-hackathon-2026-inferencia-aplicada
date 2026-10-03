# Spec: cardy-agent-s1-conversation-reads-block

Card source: [`docs/requirements/cardy-agent.md`](../requirements/cardy-agent.md), slice **S1** only (not a `07` row; S2 and S3 are other cards) · owner **Dev A** (human, confirm A2) · reviewer **Dev B** before merge (safety-critical, ADR-018) · branch `feat/cardy-agent-s1-conversation-reads-block` off `develop` (010b43f). "Requirement D1–D7" means the seven decisions in that doc; "item N" and "Done when" mean S1's lists there. Safety rules are written "06 R1…R13". Human answers are cited as **Q1–Q6** (first question set), **F1–F4** (follow-up set) and **A2, A5, A11, A12** (confirmed assumptions) and **P1–P6** (the human's answers to the planner's open items, amendment rounds). The replacement amendment (D28–D38, raised at the T18 review and T19) cites **N1–N5** (the human's five decisions on offering a replacement after agent blocks), **M1–M7** (the human's answers to the follow-up questions), **M8–M11** (the human's answers to that round's open questions 4 and 5) and **MA1–MA9** (the spec writer's assumptions for that round, accepted by the human except where an M answer changes them).

## Objective

Put Cardy in front of every bot-mode turn as a tool-calling agent, behind a flag that ships off. With the flag on, Cardy writes greetings, small talk, redirects and clarifying questions itself, answers the five read types through the audited read tools, and handles lock and block for one or several cards by **proposing** a plan that code validates, shows on a card, executes only on a button click, and reads back. Everything else (unlock, replacement, unrecognised charge, a request for a human) is passed to the current pipeline in the same turn. The pipeline also serves the turn when the agent's LLM fails. After an agent plan's permanent blocks are verified, code offers a replacement: the existing one-card offer when one card was blocked, or a multi-select card picker when several were, which leads to one replacement plan covering every selected card (D28–D38, amendment). This serves all six S1 "Done when" lines and items 1–10.

**Three places where the human's answers change the requirement's wording:**

1. **Confirmation is by button only** (Q3, F1, F2). The yes/no reader in item 5 and in requirement D2 is dropped. "Done when" line 4 becomes: no typed message confirms a plan; "sí" and "Sí, pero solo la 5214" both leave it unconfirmed. In "Expected result", "cliente: sí" is a click on Acepto.
2. **Reaching the tool-round cap is a handoff to a human** (Q5, F4), not a move to the current pipeline. An `LLMError` after the retries still moves the turn to the pipeline (item 2).
3. **Preconditions are added, not moved** (Q2). `flows/card_block.py` and `allowed_intents` stay as they are in S1.

**Cut line (the card's "If behind").** Ship items 1–4 and 6–7 and route lock and block through `pass_to_flow` as well. Item 5 (D8–D17 below, tests 1–4 and 9) then becomes the first task of the next session. The orchestrator decides when to cut.

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Flag: global setting `AGENT_ENABLED` (`agent_enabled: bool = False` in `core/config.py`), read at each turn. Off means the graph behaves exactly as today, including for a checkpoint left by an agent turn (D27). | Q6. Item 2. Precedent `llm_disabled`. P3. |
| D2 | Agent step: name `agent`, prompt `agent@v1`, model `claude-sonnet-5-5`, no temperature (ledger records NULL), at most **6 tool rounds** per turn. | Q5. ADR-003, ADR-031. 06 R7. |
| D3 | Reaching the round cap: code cancels any open plan, then hands off with the new reason `agent_round_cap`. The customer reads the existing `handoff_transfer` text. | Q5, F4. Follow-up assumption 6. S0 spec D5, D6. |
| D4 | An `LLMError` after the existing retries (transport, invalid output, unmasked input) moves the turn to the current pipeline on its ADR-032 degraded path, with `degraded: true`. A plan issued earlier in that same turn is cancelled first. `LLM_DISABLED` never enters the agent. | Item 2. Requirement D5. ADR-032. Follow-up assumption 3. |
| D5 | Exception to D4: when an agent plan is already open from an earlier turn and the LLM fails on a typed message, code sends the reminder and the same card (D13). The pipeline is not run. | F1 ("with the LLM down, code sends the reminder and the card"). |
| D6 | Code that runs before the agent stays as today: human-mode relay, `LLM_DISABLED`, the legal-keyword handoff, the access guard (`access_denied` counts toward `unauthorized_access`). | 06 R1, R8. `policies/escalation.yaml`. `02` §5. Pass-1 assumption 3. |
| D7 | **Passing a turn.** Cardy calls `pass_to_flow` (no arguments). Code discards the loop's work and runs the unchanged pipeline (`understand → route → …`) on the same message in the same turn. A message that mixes a migrated and a non-migrated request passes whole. While a pipeline flow's question is open (a flow-question `pending`, as S0 D1 defines it, not the `anything_else` closing pause), every later turn skips the agent. | Q1. Item 6. Requirement D6. S0 spec D1. |
| D8 | **Propose, never execute.** Cardy's only write capability is `propose_plan`. Its steps name card **references** from this turn's tool results, never a card id or number from the chat. Code resolves each reference to a card of the session's customer. `block_card`'s `reason` is set by code (`lost_or_stolen`), as today. The tool result is `accepted` or `rejected` with one reason code per step. The token stays in server state and in the code-rendered card. | Requirement D2, D4. 06 R1, R2, R6. Pass-1 assumption 6. |
| D9 | **Preconditions** for `cards.lock_card` and `cards.block_card` are a `preconditions` block in `policies/tools.yaml` (version 2), checked by one code validator that `propose_plan` calls. They restate what `flows/card_block.py` enforces today (Contracts). The flow and `allowed_intents` are untouched. | Q2. Requirement D4. 06 R8. |
| D10 | `issue_plan(steps, intent)` accepts `intent=None` on the agent path. With `None`, every step's tool must have a `preconditions` block and the validator must have passed; a tool without one is refused with `tool_not_allowed`, as an intent outside `allowed_intents` is today. With an intent, behaviour is unchanged. | Q2 ("the agent path passes no intent and is gated by the preconditions"). 06 R2, R8. `04` §1. |
| D11 | One plan may hold several cards, one step per card and action. One token covers the exact ordered list; each step has its own read-back; the first failed or unverified step cancels the plan and hands off. Only one plan is ever open: an accepted `propose_plan` cancels the previous plan first. | Item 5. ADR-027. Follow-up assumption 3. `02` §3 P1. |
| D12 | **Button only.** An agent plan is confirmed only by the card's buttons, labelled "Acepto / No acepto" ("Aceito / Não aceito"). No typed text confirms it on any path, including a degraded turn where the classifier reads `affirm`. Pipeline plans (flag off, or a passed flow) keep "Confirmar / Cancelar" and still accept a typed "sí". | Q3, F2. Follow-up assumption 4. 06 R2. |
| D13 | **Typed message while an agent plan is open.** The plan stays open and Cardy takes the message. If the turn ends with the same plan open, code shows the same card again (the stored event, same `token_id`, no `issue_plan` call). A change ("solo la 5214") is a new `propose_plan`, which replaces the plan (D11). | F1. S0 spec D3, D15. |
| D14 | **Acepto** executes the plan through the existing `execute_plan`, with no LLM call before the writes. Cardy then writes the result message from the verified results. If that call fails, the existing code result text is sent. A failed or unverified step sends the existing handoff text, never Cardy's. | Requirement "A turn on the agent path" steps 5–6. ADR-027. 06 R3. Pass-1 assumption 7. |
| D15 | **No acepto** cancels the plan in code (`cancel_plan`), then Cardy asks what the customer wants to change. If that call fails after the retries, the reply is the existing `action_cancelled` text. | Q3. Follow-up assumption 2. `04` §7. |
| D16 | **Claims check.** Cardy's turn output lists the plan steps it reports as done. Code compares the list with this turn's verified read-backs. On any mismatch the reply is replaced by code text: the executor's own result text on an execution turn; the reminder and card when a plan is open; otherwise the `fallback` template. Known hole, accepted: a claim Cardy makes without declaring it is not caught. | Q4. 06 R3. S0 spec D8, D10 (code text for a reply that cannot be sent). |
| D17 | **Stuck conversation.** Code counts and hands off with `clarification_exhausted`: (a) **amended (P6):** Cardy asks, asks again, and the **third** agent turn in a row labelled `asked` for the same request type hands off. The first version said two; (b) **amended (P1):** typed turns that end with the same agent plan still open get the reminder and card twice (D13), and the **third** such turn hands off. Both counters use three. A button click, a replaced plan or any other outcome resets the count. On (b) the plan is cancelled before the handoff. The first version said "two typed turns", copying S0's second-turn rule; it contradicted test 3, and the human chose three. | (a) F3, amended by P6. (b) P1. `02` §5. S0 spec D4 (counted per open question), D5. 06 R8. |
| D18 | **Sees values, writes references.** Read results reach Cardy formatted by code, each value with a reference, inside data fences, for the current turn only. Cardy writes `{reference}` placeholders; code fills them. History stays digit-stripped (`context.redact_values`), so Cardy re-reads a value it wants to cite. The provider and Langfuse therefore receive formatted amounts, dates, last-4 masks and merchant names; names, documents, email, phone, addresses and full card numbers stay vault tokens, and the `find_pii` guard runs on every loop message and tool result. | Requirement D3. A5 (shown, no objection). 06 R4, R5, R6. |
| D19 | **Reply check.** The checks of `nodes/compose.py` (`_draft_problem`: only offered references, no stray braces, no digit outside a reference, no PII hit, turn language) run on every agent reply. A failure is invalid output: one retry with the reason, then D4. The outcome goes on `reply_sent.grounding` as today. | Item 4 ("the fill and the digit check are reused"). Item 1 ("existing retry rule"). `02` §3 "Masking and grounding". `core/llm/client.py` (one retry on invalid output). |
| D20 | **Reads.** Agent read tools are thin code wrappers over `RecordingBankTools` that return the facts the flows build today, including the policy-computed ones (minimum payment, decline cause and next step, transaction state). Bank calls are audited under their current names. No tool computes a sum or a comparison. | Item 4. A11. 06 R8. `04` §1. |
| D21 | The transaction list stays the existing `transaction_list` UI event, emitted by code. A pick on a list the agent offered reaches the agent as a code-written turn event naming the picked reference; the route's selection gate (`04` §3) is unchanged. | Item 4 ("transaction lists stay code-rendered UI"). `04` §3. |
| D22 | Scope facts reach Cardy as a tool result built by code from `policies/scope.yaml`; Cardy words the redirect. Playbooks live in a new `policies/playbooks.yaml` with the `provenance` and `version` header, validated at startup, and only guide. | Item 3. ADR-026. Requirement D4. 06 R8. `04` §5. Pass-1 assumption 10. |
| D23 | **Labels.** Cardy's turn output names language, request types from the existing catalog and `answered | asked | redirected`. Code decides the status of anything with a write or a handoff. Agent turns record an `nlu_result`-shaped event with `source: "agent"`; clarifying questions use the existing slot names. | Requirement D7. Pass-1 assumption 9 (three readers of `nlu_result`: `eval/harness/checks.py`, `audit/repository.py`, `audit/timeline.py`). |
| D24 | `reply_sent` gains `path: "agent" | "pipeline"` (the path that wrote the reply; a passed or degraded turn is `pipeline`). `analytics.interactions` gains `cost_agent_usd` and `served_by` (`agent | pipeline | mixed`). `CostChart` gets an agent series. | A12. Item 8. ADR-033. |
| D25 | Four dev scenarios in `eval/scenarios/dev/` only: small talk, out-of-scope redirect, multi-card block, two-request message. Verification runs those cases and this card's tests. No full eval suite, no metric target. | Item 10. 06 R9. Requirement "No metric target is set here". |
| D26 | Docs in the same PR: ADR-035 (amends ADR-002; records D7, D8, D12, D3), the R6 rewording in `06`, and the parts of `02` and `04` listed in Contracts. | Item 9. 06 §7. |
| D27 | **Flag off with an agent pause in the checkpoint.** With `AGENT_ENABLED` off, a `pending` with `flow: "agent"` is treated as no pause. A button or a pick goes to `smalltalk` as a stale click (no write runs); a typed message goes to `understand`, and `enqueue` cancels the open plan (`02` §3 P1). | P3. 06 R2. |
| D28 | **One card permanently blocked.** When Acepto runs a plan and its `block` steps are all verified (D14) and exactly **one** card was permanently blocked, code offers the replacement the way `flows/card_block.py` does today: the `offer_replacement` template filled with that card's last 4, the pause `OFFER_REPLACEMENT_PAUSE` (`{flow: "replacement", node: "offer", awaiting_slot: "offer_replacement"}`) and `selected_card_id`. That pause is a pipeline flow question, so later turns go to the pipeline (D7), and the existing `replacement._resume_offer` handles the answer, including a typed "sí" (F2). No offer is made after a `lock`, after No acepto, or after a failed or unverified step. | N1. MA1. T18-review line "add it in T19". |
| D29 | **Several cards permanently blocked.** With **more than one**, code sends `offer_replacement_multi` and a multi-select card picker with one option per card. The picker lists **only** the cards this plan just permanently blocked and read back. Each label is built in code from the card type and mask (the `card_select` builder, e.g. "Débito •••• 5487"), with no status. The picker has a submit button and a "No, gracias" / "Não, obrigado" button. The offer text does not repeat "the cards have been blocked", because Cardy's result reply just above it already says so. | N1, N2, N4. M7. MA3, MA7. 06 R4. |
| D30 | **Order on the Acepto turn.** Cardy's result reply comes first (D14), then the offer text, then the picker. If Cardy's call fails, the code result text comes first, then the offer. The offer's pause replaces any pause Cardy's turn output sets on that turn. `agent_plan` builds the offer and the agent node appends it after its own reply. The prompt gets one line telling Cardy never to offer a replacement herself. | MA2. T19 log ("the agent node must append it"). |
| D31 | **Where the N-card replacement lives.** `flows/replacement.py` works on a list of cards, with one card being a list of one. A new checkpointed field, `replacement_card_ids`, carries the list; the address, OTP and confirm nodes read it and fall back to `[selected_card_id]`. This is the **one** file under `flows/` this card may change; success criterion 1 and the Boundaries are amended to match. Flag-off behaviour does not change: the pipeline never sets `replacement_card_ids`, so every pipeline replacement stays a list of one, and `flows/card_block.py` keeps its one-card offer. | M1. MA9. |
| D32 | **Pick input.** `CardPickerPayload.multi: bool = False` and an optional `PickerOption.card_id` (card ids are already returned by `GET /me/cards`). New message body field `card_selection: {card_ids: [...]}` with 0–N unique ids; exactly one of `text`, `resume`, `selection`, `card_selection` may be set. "No, gracias" and an empty submit both post `card_ids: []`. Before a turn is scheduled, the API gate checks that the checkpoint is paused at `awaiting_slot == "replacement_cards"` and that the ids are a subset of `replacement_card_ids`; otherwise it returns `409 selection_invalid` and runs no turn. The flow checks the same rule again. `card_selection` is not persisted as a customer message. | M2. N4. 06 R1. `04` §3 (the `selection` gate it mirrors). |
| D33 | **No typed text while the multi picker is open.** The human's answer, verbatim: "block the text block, so the customer must select cards to replace, or no gracias, no type or text to avoid confusion". While the `replacement_cards` pause is open, the frontend disables the chat input, and the API gate rejects a `text` body at that pause before scheduling a turn. The S0 non-answer re-show rule does not apply to this pause. **Amended (M8, M9):** the first version left the rejection's status and the way out open. The gate's rejection is a new `409 selection_required`: the pause is kept and nothing changes, and on that code the frontend shows the picker again and keeps the input disabled. If a typed turn ever reaches the graph at this pause, it changes nothing and keeps the pause. **No other way out:** the customer picks or declines first; "No, gracias" is one click, after which the text box is back for a request for a person or anything else. A legal keyword is not checked while the picker is open, because the text box is disabled and the gate rejects text. | M5. M8. M9. |
| D34 | **One plan for all selected cards.** After the pick there is one address check (`address_confirm_multi` when more than one card is left), at most one OTP (only for a new address, per `tools.yaml` `step_up: when_address_changed`; one step-up covers the plan), then one confirm card listing one `cards.order_replacement` step per card, all with the same `address_ref`, labelled "Confirmar / Cancelar" (`confirm_cancel`). It is a pipeline plan: D12 does not apply, and a typed "sí" confirms it as in today's replacement flow. The plan is **one token** from `issue_plan(steps, intent="replacement_request")`. On Confirmar the steps run in order through `flows.actions.execute_plan`, with one read-back per step. The first failed or unverified step stops the plan and sends the existing handoff (`action_unverified`, or `tool_failure` keeping the verified actions). Only when every step is verified does the customer get one `action_done` per card, each with its own tracking id, then the closing. | N3. M4. MA4. 06 R2, R3, R8. ADR-027. |
| D35 | **Eligibility per card.** `customer_not_active` is a check on the customer: it runs once, before any card, and hands off as today. Each selected card is then checked as `_check_active_and_eligibility` does today (origin `customer_block` or an expired card). An ineligible card is dropped from the plan and reported with `replacement_card_not_eligible` (filled with its mask). If none are left, the reply is `replacement_not_eligible`. | N3. M3. MA5. |
| D36 | **Declining.** `card_ids: []` (from "No, gracias" or an empty submit) cancels the offer: no plan is issued, `replacement_card_ids` is cleared, the customer gets `replacement_declined_multi` and then the closing, and the segment is `cancelled`. | N4. M6. |
| D37 | **Texts.** The new templates are new keys in `templates.py`, and no existing text changes, which narrows the "Ask first: `templates.py`" boundary to "adding keys is approved". The new i18n keys are `card_picker.submit` and `card_picker.decline`. The texts are in Contracts, written in neutral "tú" / "você" per `docs/brand.md`. Masks are filled in code (`mask_card`). | N1–N5 (the request to write the ES and PT-BR texts). M6, M7. MA8. 06 R4. `docs/brand.md`. |
| D38 | **Analytics.** No schema change. The Acepto turn has `path: "agent"` and the replacement turns have `path: "pipeline"`, so such a conversation reads `served_by = mixed` (D24 as written). The `replacement_request` segments are the existing ones; a declined multi offer is `cancelled` (D36). | MA6. D24. |
| D39 | **A reload declines the offer.** If the page loads while the picker is open, the offer counts as declined (D36: `replacement_declined_multi`, then the closing) and the text box works again. **Mechanism: the frontend posts the decline.** When `ChatView` mounts and reuses a stored conversation id, it posts `card_selection: {card_ids: []}` once, without knowing the pause. The D32 gate accepts it only when `replacement_cards` is open; otherwise the existing `409 selection_invalid` (or `conversation_closed`, `turn_in_progress`, `turn_cap_reached`) comes back, and the frontend ignores it silently for this one call. Why this one: it is the only option with no new endpoint or field. The frontend cannot see the open pause, because a reload only re-opens the stream and there is no history route (`ChatView.tsx` mount comment, D12 of the chat UI). Declining on the server when the stream connects is rejected: `GET /stream` would gain a side effect, and EventSource also reconnects after a network blip (`onReconnecting`), which would decline an offer still on screen. Cost accepted: one extra request per reload, usually answered with a silent 409. The same rule covers a page with no picker that receives `409 selection_required` (a second tab, or a reload during the turn that opened the picker): that page is in the reloaded state, so it posts the same decline. | M10. D32, D36. |
| D40 | **Idle.** The `replacement_cards` pause is like any other pause: the existing idle timeout and conversation close clear it. No new rule. | M11. |

## Contracts (delta only)

Everything not listed here is as in `04-contracts.md`.

**`core/llm` (item 1).** New `Step` `"agent"`; `MODEL_REGISTRY["agent"]` = the `nlu` entries; `TEMPERATURE["agent"] = None`. One new method on `LLMClient`, next to `structured`:

```python
async def tool_loop(
    self, *, step: Step, prompt: PromptRef, system: str,
    messages: Sequence[LoopMessage],        # masked history and this turn's message or turn event
    tools: Sequence[LoopTool],              # name, description, args schema, async handler -> str
    schema: type[T],                        # the validated final output
    max_rounds: int,
    validate: Callable[[T], str | None] | None = None,   # a reason string means invalid output
) -> T: ...
```

- The `find_pii` guard runs on `system`, every message and every tool result before each provider call (`LLMUnmaskedInput`).
- Every provider call is one `audit.llm_calls` row (step `agent`) and one Langfuse observation under the turn's trace.
- Transport retries and the one invalid-output retry are the existing rules. `claude-sonnet-5-5` rejects forced `tool_choice` (ADR-031), so the loop uses automatic tool choice; how the final output is obtained is the plan's.
- New error `LLMRoundCap(LLMError)`, raised when `max_rounds` is used up. The agent node catches it before the generic `LLMError` (D3 before D4).
- `core/llm` imports nothing from `domains` (06 §2): the reply check arrives as `validate`.

**Agent tools.** All are closures over the turn's session-bound `ToolContext`; none takes a `customer_id`.

| Tool | Arguments | Result to Cardy |
|---|---|---|
| read tools (D20) for card status, balance due, debit balance, transaction search, decline explanation | card reference or search criteria | fenced facts, each `{reference, value}` with the value formatted by `domains/localization` |
| `scope_facts` | `topic` (a `scope.yaml` key) | the ADR-026 facts for that topic |
| `propose_plan` | `steps: [{action: "lock" \| "block", card: <reference>}]` | `accepted`, or `rejected` with one reason code per step |
| `pass_to_flow` | none | ends the loop (D7) |

Reason codes of `propose_plan`: `unknown_reference` (not a card from this turn's tool results, which covers another customer's card, 06 R1), `already_in_state`, `already_locked`, `tool_not_allowed`. The result never contains `token_id`.

**Final output of the turn** (`schema`):

```python
class AgentTurn(BaseModel):
    language: Literal["es", "pt", "mixed", "other"]
    intents: list[Intent]                    # existing catalog, message order
    outcome: Literal["answered", "asked", "redirected"]
    awaiting_slot: Literal["card_hint", "block_kind", "criterion"] | None   # set when outcome == "asked"
    reported_done: list[int]                 # plan step indexes the reply reports as done (D16)
    reply: str                               # with {reference} placeholders only
```

**`policies/tools.yaml` version 2** (D9). Two tools gain a block; nothing else changes:

```yaml
cards.lock_card:  {…, preconditions: {status_not_in: [Blocked, Closed], locked: false}}
cards.block_card: {…, preconditions: {status_not_in: [Blocked, Closed]}}
```

A status in `status_not_in` rejects with `already_in_state`; a locked card on `lock` rejects with `already_locked`. These are the checks of `card_block._already_in_state`. The validator reads fresh card details through the audited read tools.

**`ConfirmedWriteTools.issue_plan(steps, intent: Intent | None)`** (D10). The constructor takes a keyword-only `has_preconditions=` (a callable over a tool name), which `issue_plan` uses when `intent` is `None`. In `domains/policy/tools_policy.py`, `ToolPolicy` gains `preconditions: Preconditions | None`, with model `Preconditions(status_not_in: list[str], locked: bool | None)`, and the helper is `has_preconditions(policy)`. `consume_step`, the per-step order of `04` §1 and the token contract of `04` §7 are unchanged.

**`policies/escalation.yaml` version 7.** `rules.agent_round_cap: {queue: atencion, priority: normal}`. `analytics/cause_groups.py`: `"agent_round_cap": "bot_failure"`. `domains/handoff/schemas.py`: the handoff reason type gains `agent_round_cap`. Staff text (P2):
- `nodes/handoff_summary.py` `_FALLBACK`: ES "El asistente no logró completar la solicitud tras varios intentos." / PT "O assistente não conseguiu concluir a solicitação após várias tentativas."
- i18n `staff.reason.agent_round_cap`: ES "Límite de pasos del asistente" / PT "Limite de passos do assistente".

**`policies/playbooks.yaml`** (new): `provenance`, `version`, one guidance entry per migrated request type. Loaded by the policy registry.

**Graph routing with `AGENT_ENABLED` on**, after `load_session`, in this order:

| Turn | Goes to |
|---|---|
| human mode, `llm_unavailable`, legal keyword | as today (D6) |
| `pending` is a pipeline flow question (D7) | the pipeline, as today (typed, button, pick, step-up) |
| button decision on an open agent plan | the agent plan node: Acepto → D14; No acepto → D15; a stale token → nothing runs, reminder and card |
| pick on a list the agent offered | the agent, with a turn event (D21) |
| anything else | the agent |
| agent calls `pass_to_flow` | `understand` (D7) |
| agent raises `LLMError` | `understand` on the degraded path (D4), or D5 |
| agent raises `LLMRoundCap` | `handoff_summary → handoff`, reason `agent_round_cap` (D3) |

**With `AGENT_ENABLED` off** (D27): `pending.flow == "agent"` is read as no pause; a button decision or a pick → `smalltalk` (stale click); a typed message → `understand`.

**State.** Agent pauses use the existing `Pending` shape with `flow: "agent"`: `awaiting_slot: "confirmation"` for an open plan, the asked slot for a clarifying question, `"transactions"` for an offered list. `confirmation_token_id` and `open_question` are reused as they are (the stored card is what D13 replays). D17 (a) is counted in `clarification_failures` (ask again at 1 and 2, hand off at 3), D17 (b) in `non_answer_failures` (replay at 1 and 2, hand off at 3). The open plan's steps live in one new checkpointed field, `agent_plan_steps: list[{action: "lock" | "block", card_id}] | None` (no reason: code sets it), set with the token and cleared with it, so a click on Acepto can rebuild the calls. A new checkpointed field needs this spec updated first.

**R6 structure.** The module that calls the LLM holds the read tools, `propose_plan` and `pass_to_flow` as callables and never references `bank_write_tools`, `ConfirmedWriteTools` or a token. Plan validation, `issue_plan`, the button node and `execute_plan` live in modules that do not import `app.core.llm`.

**UI.** `ConfirmPayload` gains `labels: Literal["confirm_cancel", "accept_decline"] = "confirm_cancel"`; agent plans send `accept_decline`. New i18n keys `confirm.accept` and `confirm.decline` in `es.json` and `pt.json`. `ConfirmationDecision` (`confirm | cancel`) and `POST /conversations/{id}/confirmations/{token_id}` are unchanged. The generated client is regenerated.

**Audit.**
- `nlu_result` on agent turns: `{language, status, intents, source: "agent"}`, with `status` = `clear` (answered), `ambiguous` (asked), `out_of_scope` or `out_of_market` (redirected, from the topic's `kind` in `scope.yaml`).
- `reply_sent` on agent turns: `route` = the existing node name of the first request type (`abstain` for a redirect, `handoff` for a handoff); `path` (D24); `degraded`, `fact_values`, `grounding` and `segments` as today. Segment status: `resolved` for answered; `awaiting` plus slot for asked; `awaiting`/`confirmation` for an open plan; `resolved`, `cancelled` or `handoff` set by code after a button or a handoff; `abstained` for redirected.
- Tool calls, `confirmation_used`, `readback`, `rule_hit` and `access_denied` come from the existing recorders.

**Analytics.** Alembic `0010`: `analytics.interactions.cost_agent_usd numeric` and `served_by text`. Worker: `cost_agent_usd = step_cost("agent")`; `served_by` from the interaction's `reply_sent.path` values (a missing key reads as `pipeline`). `AnalyticsSummary`: `agent_usd` in the per-day cost rows and `served_by` in `RecentInteraction`.

**Docs (D26).** `decision-log.md`: ADR-035. `06` §1: R6 reads "an LLM node that reads tool output may propose a plan and never executes a write; it holds no executing tool and never sees a token", and R8's note on `allowed_intents`. `04`: §1 (`issue_plan`, agent tools), §3 (`ConfirmPayload.labels`, SSE unchanged), §4 (reason list), §5 (`tools.yaml` v2, `escalation.yaml` v7, `playbooks.yaml`), §6 (`nlu_result.source`, `reply_sent.path`). `02`: §3 (agent node, routing table, D7, D13), §5 (D3, D17).

### Replacement after agent blocks (D28–D38, amendment)

**Offer, built in `agent/confirm.py` `_accept` after a fully verified plan.** Let B = the card ids of the plan's `block` steps, in plan order.
- `len(B) == 1`: `segments += [fill(offer_replacement, card_last4)]`, `pending = OFFER_REPLACEMENT_PAUSE`, `selected_card_id = B[0]` (D28).
- `len(B) > 1`: `segments += [offer_replacement_multi]`, `ui += [CardPickerEvent(payload=CardPickerPayload(multi=True, options=[PickerOption(card_id=id, label="<type> •••• <last4>") for id in B]))]`, `pending = {flow: "replacement", node: "cards", awaiting_slot: "replacement_cards"}`, `replacement_card_ids = B` (D29).
- The offer goes in a graph-local channel that the agent node appends after its reply, or after `agent_code_text` when Cardy's call fails (D30). Card ids never enter a loop message or tool result (06 R6 test 5 still holds).

**UI (`conversation/ui.py`).** `PickerOption.card_id: str | None = None` (set only when `multi`); `CardPickerPayload.multi: bool = False`. Single-pick pickers are unchanged.

**API (`api/v1/conversations.py`).** `PostMessageRequest.card_selection: CardSelection | None`, where `CardSelection(card_ids: list[str] = Field(max_length=10))` (unique ids, empty allowed) sits next to `TxSelection` in `graph.py`. The "exactly one of" rule covers four fields. The gate, before `start_turn`:
- `card_selection` set: the checkpointed `pending.awaiting_slot == "replacement_cards"` and `set(card_ids) <= set(replacement_card_ids)`, else `409 selection_invalid`.
- `text` set and the checkpointed `pending.awaiting_slot == "replacement_cards"`: `409 selection_required`, no turn scheduled, nothing persisted, pause kept (D33). Same position in the gate order as `selection_invalid` (after `conversation_closed`, before the turn caps).

`start_turn` and `run_turn` gain `card_selection=`; `GraphState` gains the input channel `card_selection: NotRequired[CardSelection | None]`. The runner reads the offered ids with a sibling of `checkpointed_offer` (it reads `replacement_card_ids`).

**Graph routing.** `_pipeline_entry`: a `card_selection` with `pending.awaiting_slot == "replacement_cards"` goes to `_FLOW_NODES["replacement"]`; any other `card_selection` goes to `smalltalk` (stale). A typed turn that reaches the graph at `replacement_cards` (the gate should prevent it) goes straight to the replacement node, not to `understand`. It makes no LLM call, does no write and touches no counter, and the pause and `replacement_card_ids` are kept (D33). The reply replays the stored open question (offer text and picker), so the turn is never empty (S0). No legal-keyword check runs on that path (D33). `_routes_to_agent` is unchanged: the pause is a pipeline flow question (D7).

**State.** New checkpointed field `replacement_card_ids: list[str] | None` on `TurnState`. It holds the offered ids while paused at `replacement_cards`, then the selected and eligible ids during the address, OTP and confirm steps. It is cleared when the flow ends (done, declined, cancelled, not eligible, handoff). `selected_card_id` keeps its one-card meaning.

**`flows/replacement.py` (D31, D34–D36).** `replacement()` dispatches the new node `"cards"` (`_resume_cards`):
1. `card_ids == []`: send `replacement_declined_multi`, then the closing, and clear the field (D36).
2. Ids not a subset of `replacement_card_ids`: the second gate. The turn changes nothing and the pause stays.
3. Otherwise: run `customer_not_active` once, then check eligibility per card (D35), sending one `replacement_card_not_eligible` per dropped card. If none are left, send `replacement_not_eligible`. If cards are left, ask `address_confirm` (one card) or `address_confirm_multi` (several), and pause `replacement.address_confirm`.

`_resume_address_confirm`, `_resume_otp`, `_resume_address`, `_start_replacement_plan` and `_resume_confirm` read `card_ids = replacement_card_ids or [selected_card_id]`. With several cards, `address_ask_multi` asks for the address, and the plan is N `StepSpec(tool="cards.order_replacement", args={card_id, address_ref}, summary_key="order_replacement", view_facts=[card_mask])` steps under `action_confirm_multi`. `_resume_confirm` builds N calls and runs them through `execute_plan` (D34). With one card, every text and call is today's.

**Templates (new keys in `templates.py`, D37).** `{card_mask}` is `mask_card(last4)`.

| Key | ES | PT-BR |
|---|---|---|
| `offer_replacement_multi` | ¿Quieres pedir una tarjeta nueva para alguna de las que bloqueamos? Elige las que quieras reemplazar. | Quer pedir um cartão novo para algum dos que bloqueamos? Escolha os que quer substituir. |
| `replacement_card_not_eligible` | La tarjeta {card_mask} no cumple las condiciones para reemplazarla; sigo con las demás. | O cartão {card_mask} não cumpre as condições para ser substituído; sigo com os demais. |
| `replacement_declined_multi` | Entendido, no pido tarjetas nuevas por ahora. Aquí estoy si cambias de idea. | Entendido, não peço cartões novos por enquanto. Estou aqui se mudar de ideia. |
| `address_confirm_multi` | ¿Enviamos tus tarjetas nuevas a {address_masked}? | Enviamos seus cartões novos para {address_masked}? |
| `address_ask_multi` | Cuéntame la dirección completa a la que quieres que enviemos tus tarjetas nuevas. | Me diga o endereço completo para onde quer que enviemos seus cartões novos. |
| `action_confirm_multi` | Voy a pedir una tarjeta nueva para cada una de las tarjetas de abajo. Las vas a recibir en los próximos días en la dirección que confirmamos. ¿Confirmas? | Vou pedir um cartão novo para cada um dos cartões abaixo. Você vai recebê-los nos próximos dias no endereço que confirmamos. Confirma? |

The done reply reuses `action_done`, once per verified card. i18n (`es.json` / `pt.json`): `card_picker.submit` "Pedir reemplazo" / "Pedir substituição"; `card_picker.decline` "No, gracias" / "Não, obrigado".

**Frontend.** `CardPicker.tsx` with `multi`: one checkbox per option, a submit button that is enabled even with nothing selected, and "No, gracias". Both post `{card_selection: {card_ids}}`, and the widget disables itself after use. `ChatView`/`Composer`: the text input is disabled while the last `card_picker` event is `multi` and unused (D33). On `409 selection_required` the page shows its picker again with the input disabled; a page that holds no unused multi picker posts the decline instead (D39). On mount with a stored conversation id, `ChatView` posts `{card_selection: {card_ids: []}}` once and ignores any error from that call, not only 409 or 429; it is a background cleanup (D39; human decision at verify). New error code `selection_required` in the client's known codes. `sse.ts` types gain `multi` and `card_id`. The generated client is regenerated for the new body field.

**R2 / R3.** One token per replacement plan, covering the exact ordered N steps (`04` §7, unchanged). One read-back per step. "Done" (`action_done`) only after every step is verified; otherwise the existing handoff text (D34). The agent's block plan and the replacement plan are two plans with two tokens, never one.

**Docs.** `04` §3: the `card_selection` body, its gate and `409 selection_required` for text at `replacement_cards`; `ui.card_picker` `{options: [{label, card_id?}], multi}`. `02` §3: the offer after an agent plan (D28–D30); `02` §4.9 (replacement): N cards (D31, D34–D36).

## Touch map

- `backend/app/core/llm/`: `registry.py`, `client.py`, `errors.py`, `pricing.py` only if a model id is new (none is).
- `backend/app/core/config.py`: `agent_enabled`.
- `backend/app/domains/conversation/agent/` (new package): the LLM node; the tools; the plan check and button node (no `core.llm` import); the reply and claims checks.
- `backend/app/domains/conversation/prompts/agent@v1.md` (new).
- `backend/app/domains/conversation/graph.py`, `runner.py`, `state.py`, `ui.py`, `sandbox.py`, `nodes/load_session.py`, `nodes/compose.py` (only to expose the reused checks), `nodes/handoff_summary.py` (`_FALLBACK` text, P2), `tools/executor.py` (`intent=None`, `has_preconditions=`), `tools/registry.py`.
- `backend/app/domains/handoff/schemas.py`: the `agent_round_cap` reason.
- `backend/app/domains/policy/`: `tools_policy.py`, `escalation.py` if the loader lists reasons, a playbooks loader, `registry.py`.
- `policies/tools.yaml`, `policies/escalation.yaml`, `policies/playbooks.yaml` (new).
- `backend/app/domains/analytics/`: `worker.py`, `repository.py`, `dashboard.py`, `mock.py`, `cause_groups.py`; `backend/app/alembic/versions/0010_*.py` (new).
- `backend/app/domains/audit/`: only if the `source` enum is typed there.
- `frontend/src/components/chat/ConfirmCard.tsx`, `frontend/src/lib/i18n/{es,pt}.json`, `frontend/src/components/staff/analytics/{CostChart,RecentInteractionsTable}.tsx`, `frontend/src/lib/sse.ts`, `frontend/src/client/` (generated). The i18n files also gain `staff.reason.agent_round_cap`.
- `eval/scenarios/dev/`: four new files (D25).
- `backend/tests/unit/`: the files in the test list; `test_r6_no_write_tools_in_llm_nodes.py` updated. `backend/tests/conftest.py` (`ScriptedLLM` scripts the `agent` step).
- `docs/solution-docs/`: `decision-log.md`, `06-engineering-rules.md`, `02-conversation-design.md`, `04-contracts.md`. `docs/diagrams/turn-graph-v0.mmd` (agent node and its edges).

Replacement amendment (D28–D38) adds:
- `backend/app/domains/conversation/flows/replacement.py`: the only `flows/` file (D31).
- `agent/confirm.py` (the offer), `agent/node.py` (append the offer after the reply), `prompts/agent@v1.md` (one line, D30).
- `graph.py` (`CardSelection`, `card_selection` channel, `_pipeline_entry` row, `run_turn` param), `state.py` (`replacement_card_ids`), `ui.py` (`multi`, `card_id`), `templates.py` (six new keys, D37), `runner.py` (`start_turn` param, the offered-ids read for the gate). `runner.py` is the file T21 edits, so this task runs after T21.
- `backend/app/api/v1/conversations.py`: the body field and the gate (D32, D33).
- `frontend/src/components/chat/CardPicker.tsx`, `MessageList.tsx`, `ChatView.tsx` / `Composer.tsx` (input disabled), `frontend/src/lib/sse.ts`, `frontend/src/lib/i18n/{es,pt}.json`, `frontend/src/client/` (regenerated).
- `backend/tests/unit/test_replacement_multi.py` (new), `test_agent_happy.py` (test 10 extended).
- `docs/solution-docs/04-contracts.md` §3, `02-conversation-design.md` §3 and §4.9.

Not touched: every module under `flows/` except `replacement.py` (D31), `nodes/route.py`, `nodes/understand.py`, existing `templates.py` text (new keys only, D37), `nlu@v7`, `compose@v11`, `classifier/`, `baseline/`, `eval/harness/`, `eval/scenarios/heldout/`, `policies/card_select.yaml`, `policies/scope.yaml`.

## Test list

Unit tests with `ScriptedLLM` (extended to script the `agent` step). Fourteen tests in seven files (11 original plus 12–14 for the replacement amendment). Each task runs only its own file.

| # | Test | Proves |
|---|---|---|
| 1 | `test_agent_plan_check.py::test_r1_other_customers_card_refused` | 06 R1: a step naming a card that is not in this turn's tool results (another customer's id) is rejected with `unknown_reference`; no plan is issued, no write tool runs. |
| 2 | `test_agent_plan_check.py::test_precondition_rejects_blocked_card` | D9: a `lock` step on a Blocked card is rejected with `already_in_state` from the YAML rule; `issue_plan(intent=None)` for a tool without `preconditions` raises `PolicyDenied`. |
| 3 | `test_agent_confirmation.py::test_r2_typed_text_never_confirms` | 06 R2, "Done when" 4, D17 (b): five typed turns with a plan open. (1) "sí": the same card and token are shown again. (2) "Sí, pero solo la 5214": the old token is cancelled, a new plan holds only 5214, the count restarts; a click on the old token then runs nothing. (3) and (4) typed turns on the new plan: the same card is shown again each time. (5) the third typed turn on that plan hands off with `clarification_exhausted` and the plan cancelled. No write tool runs at any point; the cards stay Active. |
| 4 | `test_agent_confirmation.py::test_r3_unverified_claim_is_replaced` | 06 R3: a turn output with `reported_done` and no verified read-back is replaced by code text; on Acepto with an unverified step the reply is the handoff text and Cardy's is never sent. |
| 5 | `test_r6_no_write_tools_in_llm_nodes.py` (updated) | 06 R6 reworded: the scan covers `conversation/agent/`; the LLM module references no executing tool; no message or tool result given to `ScriptedLLM` in a full block conversation contains the `token_id`. |
| 6 | `test_agent_reply_check.py::test_r4_digit_outside_reference_rejected` | 06 R4: a reply with a raw digit is retried once; a second one sends the turn to the pipeline with `degraded: true`; the sent reply contains no model-written digit and `fact_values` covers every digit run. |
| 7 | `test_llm_client.py::test_r5_tool_loop_refuses_unmasked_tool_result` | 06 R5: a tool result with a raw email raises `LLMUnmaskedInput` before the provider is called. |
| 8 | `test_agent_fallbacks.py::test_round_cap_hands_off_and_llm_error_degrades` | 06 R11, "Done when" 5: six rounds without a final output → handoff `agent_round_cap`, open plan cancelled; a scripted `LLMError` → reply from the pipeline, `degraded: true`, `path: "pipeline"`. |
| 9 | `test_agent_happy.py::test_block_all_cards_pt` | PT happy path, item 5: "Quero bloquear meus cartões" → asked `block_kind` → "Temporário, todos" → one card with two steps and `accept_decline` labels → Aceito → two `readback` events → result reply. `reply_sent` has `path: "agent"`, the `awaiting`/`confirmation` then `resolved` segments, and `nlu_result.source == "agent"`. |
| 10 | `test_agent_happy.py::test_block_and_balance_one_message_es` | ES happy path, "Done when" 2: "Bloquea la de crédito y dime cuánto debo en la otra" → one turn with the balance (filled references) and a one-step plan; two segments. **Extended (amendment, D28, D30, ES happy path):** the step is a permanent `block`; Acepto → one `readback`, then the sent reply is Cardy's result followed by the `offer_replacement` text with that card's last 4; the checkpoint has `pending == OFFER_REPLACEMENT_PAUSE` and `selected_card_id` = the blocked card; no `card_picker` event. |
| 11 | `test_agent_happy.py::test_pass_to_flow_keeps_later_turns_on_pipeline` | D7: an unlock request runs `card_unlock` in the same turn; the next turn, with that flow's question open, makes no `agent` call. The one test outside the strict budget lines: a wrong route here breaks every non-migrated type with the flag on. |
| 12 | `test_replacement_multi.py::test_replace_two_blocked_cards_pt` | PT happy path, D29, D32, D34: a plan blocking two cards (`CLI-TFMULTI00001`) → Aceito → reply ends with `offer_replacement_multi`, one `card_picker` with `multi: true` and exactly the two blocked cards (`card_id`, label "<tipo> •••• <last4>"), pause `replacement.replacement_cards` → `card_selection` with both ids → `address_confirm_multi` → typed affirm (scripted `nlu`) → one confirm card with two `cards.order_replacement` steps and `labels == "confirm_cancel"` → Confirmar (one confirm card, one click) → two `cards.order_replacement` `readback` events, and the reply has two `action_done` texts, each with its own tracking id. |
| 13 | `test_replacement_multi.py::test_r1_card_selection_gate` | 06 R1, D32, D33, D36: at the `replacement_cards` pause, a `card_selection` with an id that was not offered gets `409 selection_invalid` and no turn runs; a `text` body gets `409 selection_required`, no turn runs and the checkpointed pause is unchanged; `card_ids: []` sends `replacement_declined_multi`, issues no plan and calls no write tool. |
| 14 | `test_replacement_multi.py::test_r3_unverified_second_replacement_hands_off` | 06 R3, D34: with the second `order_replacement` scripted unverified, Confirmar sends the `action_unverified` handoff, and no `action_done` text (neither card's) is sent. |

Plus one assertion added to `test_analytics_segments.py` (or one test beside it): an interaction whose replies carry `path: "agent"` and an `agent` step cost gets `served_by == "agent"` and `cost_agent_usd` ("Done when" 6).

Reused, not rewritten: `test_r2_confirmed_writes.py` and `test_r2_confirmation_store.py` (a replayed or reordered step is rejected at the executor the agent path shares); `test_policy_registry.py` (the real YAML files load); the whole existing suite with the flag off ("Done when" 5, first half). `test_replacement_offers.py`, `test_block_flows.py` and `test_selection_gate.py`, **unchanged**, prove that the one-card pipeline replacement and the `selection` gate still behave as before (D31).

Runtime proofs (verifier, live LLM, flag on): the three "Expected result" conversations in the browser in ES and PT ("Done when" 1); the dashboard row ("Done when" 6); the four dev scenarios.

## Boundaries

- **Always:** take `customer_id` and card ownership from the session-bound tools; keep the token out of every prompt, tool result and Langfuse trace; run each task's own test file only and the full suite once per card; bump `agent@vN` on every prompt change; update `02`, `04`, `06` and the decision log in the same PR; run the frontend typecheck inside `latam-cs-frontend-1`.
- **Ask first:** any change under `flows/` other than `flows/replacement.py` (D31), to `nodes/route.py`, or to existing `templates.py` text (new keys are approved, D37); any change to the one-card replacement's behaviour; a way for typed text to reach the `replacement_cards` pause (D33); a new checkpointed `TurnState` field; a tool for derived numbers; removing `allowed_intents`; a new escalation reason other than `agent_round_cap`; changing how the pipeline confirms its own plans; a change to `eval/harness/`; a second migration; turning the flag on by default.
- **Never:** give the LLM module an executing tool, `bank_write_tools` or a token; confirm an agent plan from typed text; send Cardy's text after a failed or unverified step; let a model-written digit, date or mask reach the customer; put policy values in `agent@v1.md`; let Cardy word or decide the replacement offer, or see a card id or the picker's options; offer a card in the multi picker that this plan did not just permanently block and read back; touch `eval/scenarios/heldout/`; commit secrets, `data/` or the dictionary PDF; spec or build S2 or S3 behaviour.

## Success criteria

Each line names the changed behaviour it proves. Verification is scoped to these.

1. **Flag off changes nothing.** `make check` is green with `AGENT_ENABLED` unset, and `git diff --stat develop` shows no file under `backend/app/domains/conversation/flows/` **other than `flows/replacement.py`** (amended by D31), none under `eval/harness/` or `eval/scenarios/heldout/`, and no existing test file changed other than `test_r6_no_write_tools_in_llm_nodes.py`, `test_llm_client.py` and `test_analytics_segments.py`. `test_replacement_offers.py`, `test_block_flows.py` and `test_selection_gate.py` pass unchanged.
2. **Plan check and preconditions (06 R1, D9, D10).** `cd backend && uv run pytest tests/unit/test_agent_plan_check.py -q` reports 2 passed.
3. **Button-only confirmation and the claims check (06 R2, R3; D12, D13, D16, D17).** `uv run pytest tests/unit/test_agent_confirmation.py -q` reports 2 passed.
4. **The agent cannot execute and never sees the token (06 R6).** `uv run pytest tests/unit/test_r6_no_write_tools_in_llm_nodes.py -q` passes, and `06` §1 carries the reworded R6.
5. **No model-written number, and no raw PII in the loop (06 R4, R5).** `uv run pytest tests/unit/test_agent_reply_check.py tests/unit/test_llm_client.py -q` passes.
6. **Cap → handoff, LLM failure → pipeline (D3, D4).** `uv run pytest tests/unit/test_agent_fallbacks.py -q` passes; `policies/escalation.yaml` has `agent_round_cap` and `cause_groups.py` maps it to `bot_failure`.
7. **Multi-card block, two requests in one message, pass to a flow (D7, D11; ES and PT).** `uv run pytest tests/unit/test_agent_happy.py -q` reports 3 passed.
8. **Browser, flag on.** In ES and in PT: the greeting gets a non-template reply; the out-of-scope question gets a redirect; "Quiero bloquear mis tarjetas" → "Temporal, todas" shows one card listing every eligible card with "Acepto / No acepto", and after Acepto the cards read as locked in `GET /me/cards`. Typing "sí" instead of clicking changes no card.
9. **Dashboard.** After the analytics worker runs, the conversation of criterion 8 appears in `/staff/analytics` with its intents, an outcome, a cost above zero, `served_by = agent`, and the cost chart shows the agent series.
10. **Dev scenarios.** Four new files exist in `eval/scenarios/dev/` and pass `eval/harness/lint.py`; run with the flag on, they report 0 unsafe checks. No other suite is run.
11. **Docs.** `decision-log.md` has ADR-035; `04` §1, §3, §4, §5, §6 and `02` §3, §5 carry the lines named in Contracts, plus, for the replacement amendment, `04` §3 (`card_selection`, `card_picker.multi`) and `02` §3 and §4.9.
12. **Replacement after agent blocks (D28–D36; ES and PT; 06 R1, R2, R3).** `cd backend && uv run pytest tests/unit/test_agent_happy.py tests/unit/test_replacement_multi.py -q` reports 6 passed. `grep -n 'offer_replacement_multi\|replacement_declined_multi\|replacement_card_not_eligible\|address_confirm_multi\|address_ask_multi\|action_confirm_multi' backend/app/domains/conversation/templates.py` finds all six keys, each with `es` and `pt`.
13. **Browser, flag on (multi picker).** In ES: "Bloquea mis dos tarjetas, las perdí" → Acepto → Cardy's result, then the offer and a picker with checkboxes for exactly the two cards, "Pedir reemplazo" and "No, gracias", and the chat input disabled. Selecting both and continuing with the address on file leads to one confirm card with two steps; after Confirmar, the staff timeline of that conversation shows two `readback` events for `cards.order_replacement` after the one Confirmar, and the reply has two `action_done` lines. In a second conversation, "No, gracias" gives `replacement_declined_multi` and re-enables the input. In a third, reloading the page while the picker is open shows `replacement_declined_multi` and the closing, and the input works. With one card blocked, the reply carries the one-card offer and no picker.

Known limit at verify (human waiver, this card only): `make check` stops at `ml.intent.check`, because `new_card` has no data files under `ml/intent/data/<locale>/`. That failure was already on develop (9aeeb75); this card does not touch `ml/`. Every other `make check` step passes.

## Open questions

Nothing blocks the plan. The readings below are derived from the answers and the docs rather than answered word for word; the human may overrule them at approval:

1. ~~D17 (b) count~~ settled by P1 (third typed turn hands off; a replaced plan resets). D17 (a) settled by P6: the third `asked` turn in a row for the same request hands off, aligned with (b).
2. **D16** on a turn with no execution uses the reminder and card when a plan is open, else `fallback`.
3. **D21** makes a pick on an agent-offered list reach the agent, because the list UI is a pick UI and "stays".

Replacement amendment, settled by the human (M8–M11):

4. ~~Status for typed text at `replacement_cards`~~ settled by M8: `409 selection_required` (D33).
5. ~~A way out of the picker pause~~ settled by M9 (pick or decline first; no legal-keyword check while it is open, D33), M10 (a reload declines, posted by the frontend, D39) and M11 (idle as any pause, D40).

Accepted gap: per-card ineligibility (D35) has no test of its own. A card this plan just blocked has origin `customer_block`, so the branch is near unreachable in the fake bank; the logic reuses today's eligibility check.

Left to later slices or to the developers:
- With the flag on, unlock, replacement and claims still accept a typed "sí" until S2 and S3 (F2). Owner: S2 and S3 specs.
- Injection attempts in customer text are not counted toward `unauthorized_access` on the agent path; only `access_denied` is (D6). The requirement does not ask for it. Owner: both developers, before the flag is turned on.
- Cost and latency of the agent step are not measured here. Turning the flag on for the submission is a human decision after verification (requirement "Timeline and risks").
