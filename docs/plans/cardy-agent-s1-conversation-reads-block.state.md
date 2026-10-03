# State: REQ-cardy-agent-s1 — Agent foundation, conversation, reads, lock and block
<!-- ORCHESTRATOR ZONE — the orchestrator owns this. Implementers never edit it. -->

## Card
Card REQ-cardy-agent-s1 (owner A, reviewer B) · requirement `docs/requirements/cardy-agent.md` §S1 · spec `docs/specs/cardy-agent-s1-conversation-reads-block.md` · plan `docs/plans/cardy-agent-s1-conversation-reads-block.md`
Branch `feat/cardy-agent-s1-conversation-reads-block`, based on `develop` (010b43f = `origin/develop`).

## Conventions established for this card
- The repo facts for this card are in the plan's section "Facts checked against the repo" (plan lines 44–127; the replacement amendment facts are its subsection "Replacement amendment (T22–T31)"). Read the paragraph for your area before you start; do not re-derive it.
- Work directly on the branch in this checkout. No new branch, no worktree. Diff against `origin/develop`.
- Tests always use a fake LLM (`ScriptedLLM` in `backend/tests/conftest.py`). No test calls the Anthropic API, Bedrock or Langfuse.
- `flows/card_block.py`, `flows/actions.py` and `allowed_intents` are read-only in this card. Import from them; never edit under `flows/`.
- `ConfirmedWriteTools` is constructed positionally in existing tests the card may not edit, so it gets no new required constructor argument.
- `graph.py` cannot import `nodes/`, `flows/` or `agent/` at module level; `build_graph` imports them in its body. `policy` must not import `app.domains.conversation`.
- `npm run typecheck` runs only inside `latam-cs-frontend-1`. There is no `gh` CLI. No new dependency is needed.
- When your task creates a name a later task uses (class, function, fixture, file), put the real name in your Task log entry. Later tasks read it from here.
- Never touch `eval/scenarios/heldout/`.

## Human decisions taken mid-card
- Plan open item 1 (D17 threshold, raised by the planner, binds T18): typed replies to an open plan get TWO replays (the card shown again); the THIRD typed turn on the same plan hands off with `clarification_exhausted`. A replaced plan resets the count. Test 3 therefore needs five typed turns. The count for `asked` turns (D17 a) is settled: three, see below.
- Plan open item 2 (binds T2, T13): staff text for `agent_round_cap` is the planner's wording. `handoff_summary._FALLBACK`: ES "El asistente no logró completar la solicitud tras varios intentos." · PT "O assistente não conseguiu concluir a solicitação após várias tentativas." `staff.reason.agent_round_cap`: ES "Límite de pasos del asistente" · PT "Limite de passos do assistente".
- Plan open item 3 (binds T15): option (a). With the flag off, a `flow: "agent"` pause is treated as no pause: a button or pick goes to `smalltalk` as a stale click; a typed message goes to `understand`, whose `enqueue` cancels the plan.
- Plan open item 4: the human approved six files outside the spec's touch map: `handoff/schemas.py`, `nodes/handoff_summary.py`, `frontend/src/lib/sse.ts`, `conversation/sandbox.py`, `tests/conftest.py`, `docs/diagrams/turn-graph-v0.mmd`.
- T9 (persona): add a NEW dev persona with 2+ Active cards (from the customer data) to `eval/personas.yaml`; that file joins T9's Files. heldout untouched.
- D17(a) asked turns: ALIGNED TO THREE. Asked, asked again, and the third `asked` turn for the same request hands off (`clarification_exhausted`). Both counters (asked turns and typed replies to an open plan) use three.
- T15 gap (flag off, leftover agent pause): ACCEPTED AS KNOWN LIMIT. A typed answer that fits a leftover `flow: "agent"` pause with the flag off routes to `unsupported` via `nodes/route.py`; the plan is not cancelled that turn and its token expires on its own. No route.py change.
- T15 test 11 deviation: ACCEPTED. `test_pass_to_flow_keeps_later_turns_on_pipeline` uses an ambiguous lock-vs-block (card_block) request instead of card_unlock.
- T17 note for T18: when the `agent_plan` branch lands, the runner's `agent_ran` flag must cover it too, e.g. `node_name in ("agent", "agent_plan")`.
- T18 blocker (where the plan's steps live between propose and Acepto): CHECKPOINTED STATE FIELD. `agent_plan_steps: list[{action, card_id}]` on `TurnState`; code sets the block reason (as D8), the field holds no reason; `agent_plan` rebuilds lock_card/block_card calls from it in order; cleared on confirm, cancel, replace or handoff; card ids never reach the model. T18 Files gain `backend/app/domains/conversation/state.py`, `backend/app/domains/conversation/agent/plan.py` (`PlanBox.set` and `propose_plan` take the steps), and one line each in the spec (State) and `docs/solution-docs/04-contracts.md`.
- playbooks.yaml tool names: RENAME TO REAL TOOLS. New task T20 (only `policies/playbooks.yaml`): name the agent's real tools (card_status, balance_due, debit_balance, search_transactions, explain_decline, scope_facts) instead of `list_cards` / `get_card_details`. The prompt's "use the equivalent tool" mapping is then dropped (T18 owns the prompt).
- Runner path for `agent_plan`: SMALL RUNNER TASK. New task T21 (only `backend/app/domains/conversation/runner.py` plus one check in an existing agent test): `agent_ran` also covers node `agent_plan`, so an Acepto click that ends in handoff has `reply_sent.path` "agent". Runs after T18, in parallel with T19 if Files do not overlap.
- T18 review, replacement offer: ADD IT IN T19. After a verified PERMANENT block on an agent plan, offer the replacement the block flow sends today, as the same pause. T19 Files gain what it needs (see T19 brief).
- T18 review, count reset: ONLY A NEW PLAN RESETS the typed-turn count on an open plan. A button click (including a stale-token click) does NOT reset it. T19 changes `agent/confirm.py` and `test_agent_confirmation.py`.
- T18 review, click turn: ACCEPTED. On the turn after Acepto / No acepto, `pass_to_flow` is not offered, and an `LLMError` or the round cap sends `agent_code_text` (no handoff), because the writes already ran.
- T21 stale click route: `card_block`. A stale click (old token, `agent_plan` -> `finish`, no labels) records route `card_block` and path `agent`. T21 runs after T19 (both would touch `test_agent_confirmation.py`).
- T19 addition B redesigned (replacement offer after an agent plan's verified permanent blocks), BUILT IN THIS CARD: exactly one card -> today's one-card offer (same template, same pause, `selected_card_id`); more than one -> "the cards have been blocked, would you like to order a replacement for any of them?" with a MULTI-SELECT card picker, one option per card. Picker lists ONLY the cards this plan just permanently blocked and read back. After selection: ONE plan for all (one address check, one OTP, one confirm card with one `order_replacement` step per card, read-back per card; eligibility per card). Decline: a "No, gracias" / "Não, obrigado" button; submitting nothing also counts as no. Test 10 is extended for the one-card offer. A spec amendment (D28+) and new plan tasks follow before any code.
- Replacement amendment answers (spec D28+): change `flows/replacement.py` to a list of cards (`replacement_card_ids`), the only `flows/` file unlocked; multi-pick via `CardPickerPayload.multi`, `PickerOption.card_id`, new body `card_selection: {card_ids}` (0-N), and 'No, gracias' / empty submit post `[]`; gate checks the pause and that the ids are a subset (409 `selection_invalid`); ineligible card dropped with a new template, `replacement_not_eligible` if none left; OTP as today (at most one, `when_address_changed`); while the multi-card picker is open the text input is DISABLED (human: "block the text block, so the customer must select cards to replace, or no gracias, no type or text to avoid confusion"), and the gate rejects text there; plural decline text `replacement_declined_multi`; offer text without repeating 'blocked'.
- Replacement picker edge cases (spec D28-D38 open Q4-Q5): typed text at `replacement_cards` gets a new `409 selection_required`; the pause is kept and nothing changes. No extra way out: pick or 'No, gracias' first, then the text box is back. A page reload with the picker open DECLINES the offer (`replacement_declined_multi`, then the closing). Idle timeout and conversation close clear the pause like any other.
- Spec amendment D28-D40 APPROVED by the human. Also accepted: reload decline = on mount with a stored conversation id, `ChatView` posts `card_selection: {card_ids: []}` once (silent 409 otherwise); a page with no picker that gets `409 selection_required` (e.g. a second tab) also declines; a typed turn that reaches the graph at `replacement_cards` re-sends the stored offer text and picker (no LLM, no write, no counter, pause kept).
- Plan amendment T22-T31 APPROVED (waves W8 T22-T25, W9 T26-T28, W10 T29 alone, W11 T30-T31). Open items: F: add `CardSelection` to the allowlist roots in `hosting._checkpoint_types`; `hosting.py` joins T23. B: `postCardSelection` goes in `frontend/src/lib/api.ts`, mirroring `postSelection`; `api.ts` joins T31. A: on `409 selection_required` the chat shows ES 'Elige las tarjetas que quieres reemplazar o toca «No, gracias».' / PT 'Escolha os cartões que quer substituir ou toque em «Não, obrigado».' and DROPS the typed bubble. D: `ToolUnavailable` on the Acepto turn keeps today's handoff (no offer). C: ids not among those offered reaching the flow -> re-show the stored offer and picker. E: the one-card offer and the one-card address pause write `replacement_card_ids: None`.
- Slicing tasks T22+: awk -v t=T22 '$0 ~ "^- \\[[ x]\\] "t":" {f=1;print;next} f && /^(- \[[ x]\] T[0-9]+:|## )/ {exit} f' docs/plans/cardy-agent-s1-conversation-reads-block.md

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a5624ea8 | Verify passed: flag, step `agent`, `tool_loop`, `LLMRoundCap`, test 7 (6 passed) |
| T2 | done | | agent_round_cap in escalation v7, HandoffReason, cause_groups (bot_failure), _FALLBACK ES/PT |
| T3 | done | a47b911f | Verify passed: `playbooks.yaml`, `PlaybooksPolicy`, bundle field `playbooks` (file now required at startup) |
| T4 | done | | ConfirmPayload.labels confirm_cancel or accept_decline; i18n confirm.accept/confirm.decline |
| T5 | done | a30a929b | Verify passed: migration `0010_agent_cost.py` proven on a throwaway DB, `cost_agent_usd`, `served_by`, `agent_usd`, `path` (3 passed) |
| T6 | done | | agent/{schema,refs,checks}.py; compose aliases; refs/checks take language |
| T7 | done | | tools.yaml v2 Preconditions, has_preconditions(policy), ctor kw has_preconditions, issue_plan(intent=None) |
| T8 | done | ad7801bd | Verify passed: ADR-035, `02` §3 and §5, `04` §1, §4, §5, §6 |
| T9 | done | aa480dbc | 4 dev seeds d-*; new persona CLI-00BPQUST6X8L (MX) in eval/personas.yaml; out_of_scope seed uses category `unsupported` |
| T10 | done | ad7530d8 | 0010 on app + golden; worker clean; client regenerated (agent_usd, served_by, agent_round_cap); labels is SSE-only, not in client |
| T11 | done | a58821b2 | AgentScript, ScriptedLLM.tool_loop, agent_on, async run_recorded_turn; Call.messages/tool_results |
| T12 | done | abbd2de6 | agent/reads.py read_tools (6 tools); TurnRefs.scope_topic/scope_kind; TxOfferState.flow + agent; tx list built from tx_option |
| T13 | done | a30d8906 | agent cost series, served_by column (Agente / Flujo guiado / Mixto; PT Agente / Fluxo guiado / Misto), agent_round_cap label |
| T14 | done | a11af34a | R6/R8 in 06; 04 §1 issue_plan(intent None), propose_plan, §3 labels, §5 tools v2; 02 §3/§5 (three for both counters) |
| T15 | done | a0c511b2 | agent node + agent@v1 prompt, routing (_routes_to_agent, _after_summarize), D27 flag-off in _pipeline_entry; test 11 uses card_block (deviation, with human) |
| T16 | done | ad1737e3 | agent/plan.py check_steps, PlanBox, propose_plan (accepted / rejected (step n: code)), cancel_open_plan; tests 1, 2 (2 passed) |
| T17 | done | af3a071e | runner agent labels (nlu_result source agent, route, path agent, tx_offer on agent pause, grounding from agent), R6 scan of agent/; 14 passed |
| T18 | done | a1602997 | agent_plan button node, confirm.py (replay, counters three/three), propose_plan in node, agent_plan_steps state, prompt; 22 passed |
| T19 | done | a142e16d | tests 9, 10, R6 token, open-plan round cap, addition A (13 passed); addition B moved to T22-T31 |
| T20 | done | a819b7bf | playbooks.yaml names real tools (card_status, balance_due with debit_balance fallback); loads 8 playbooks v1 |
| T21 | done | a8bfe3c7 | runner agent_ran covers agent_plan; handoff on agent turn forces route handoff; stale click route card_block; 7 passed (click-then-handoff route checked by reading only) |
| T22 | done | a1a5e55d | PickerOption.card_id, CardPickerPayload.multi, TurnState.replacement_card_ids, six template keys ES and PT; 5 passed |
| T23 | done | a3945124 | graph CardSelection (max 10, no dups), card_selection and agent_offer channels, two _pipeline_entry rows, run_turn(card_selection=); hosting allowlist; 9 passed |
| T24 | done | ab87e120 | 04 §3 card_selection body and gates, card_picker multi payload; 02 §3 offer after agent plan, §4.9 several cards |
| T25 | done | aa28657c | CardPicker multi (checkboxes, submit, decline, self-disables), sse.ts types, card_picker.submit and decline keys; typecheck clean in container |
| T26 | done | aef4ff78 | PostMessageRequest.card_selection, gate 409 selection_invalid and selection_required before turn caps, checkpointed_replacement_offer, card_selection through runner; 11 passed |
| T27 | done | aefd2205 | replacement.py on a list of cards (_resume_cards, multi address texts, one N-step plan, list cleared centrally at every end); protected tests unedited; 18 passed |
| T28 | done | ac4f9ed2 | _accept builds agent_offer (one card or multi picker), node appends it after the reply on every click path, prompt line, test 10 extended; 13 passed |
| T29 | done | ab7beb4e | make client: CardSelection and PostMessageRequest.card_selection in client; multi and card_id SSE-only; typecheck clean |
| T30 | done | aba40134676d829b7 | tests 12-14 in test_replacement_multi.py; 6 passed crit 12; protected tests 13 passed; no defects; one-plan proof = one confirm card + one click + two readbacks (audit has no token_id) |
| T31 | done | a89319ccd1b9f230d | api.ts postCardSelection; picker wired, composer disabled while multi picker open; 409 selection_required drops bubble; mount decline ignores all errors (ask human); typecheck clean |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T9 — Four dev scenarios (STOPPED, nothing created)
Created: none.
Facts the next tasks need: of the 39 personas in `eval/personas.yaml`, only 2 are referenced by no seed in `eval/scenarios/dev/` and are not heldout-only candidates with 2+ cards: `CLI-F7PQP3J4AS6X` (MX, 3 credit, Active) and `CLI-UZ7Z6C3JFXGX` (MX, 2 credit, one already Blocked, so only 1 Active). The lint refuses a writing seed on any persona another seed already uses. The multi-card block and two-request cases both write (lock_card), so two fresh personas with 2+ Active cards are needed; only one exists.
Deviations: stopped per task rule "if no listed persona fits".
Verify: not run.

### T3 — playbooks.yaml and its loader
Created: `policies/playbooks.yaml` (v1, 8 keys, Spanish), `backend/app/domains/policy/playbooks.py` (`PlaybooksPolicy`, `load_playbooks_policy(path=None)`).
Changed: `backend/app/domains/policy/registry.py` (`"playbooks"` in `_MODELS_BY_STEM`; `PolicyBundle.playbooks: PlaybooksPolicy`, required; missing file raises `PolicyLoadError`).
Facts the next tasks need: read via `get_policies().playbooks.playbooks[<request_type>]` (str).
Deviations: none.
Verify: test_policy_registry 2 passed; bundle assert, ruff, format, mypy all clean.

### T8 — Docs for the agent, routing, the round cap and the audit labels
Changed: `docs/solution-docs/decision-log.md` (ADR-035 added before "D3-A D4"; one-line "Amended by ADR-035" under ADR-002; the file has no index), `04-contracts.md`, `02-conversation-design.md`.
Headings added in `04`: `### Agent tools (AGENT_ENABLED)` at the end of §1 (before the `TxFilter` paragraph); `#### Agent turns (AGENT_ENABLED)` in §6 (before the `segments` paragraph). §4 reason list, §5 escalation.yaml v7 + `playbooks.yaml` paragraph are inline, no new heading.
Headings added in `02`: `### Agent node (AGENT_ENABLED, ADR-035)` in §3 (routing table + "The pass rule", before "Masking and grounding"); in §5 a "**Round cap (agent).**" paragraph before the non-answer paragraph.
Not written (item 5 docs task): propose_plan, issue_plan, ConfirmPayload.labels, tools.yaml v2, D13, D17, `06`.
Deviations: none.
Verify: the five grep commands all matched (ADR-035, agent_round_cap, playbooks/pass_to_flow/scope_facts, AGENT_ENABLED, "agent").

### T5 — Analytics: migration 0010, agent cost, served_by
Created: `backend/app/alembic/versions/0010_agent_cost.py` (revision "0010", down "0009"; `analytics.interactions.cost_agent_usd numeric(12,6) default 0`, `served_by text default 'pipeline'`).
Changed: `worker.py` (`ReplyFact.path: str = "pipeline"` as last field with default, so positional 3-arg construction still works; `InteractionRow.cost_agent_usd`, `.served_by`), `repository.py` (`load_facts` reads `payload->>'path'`), `mock.py` (`MockInteraction.cost_agent_usd`=0, `.served_by`="pipeline"), `dashboard.py` (`CostDay.agent_usd`, `RecentInteraction.served_by`, SQL filled).
Facts the next tasks need: field names are exactly `cost_agent_usd`, `served_by` (`agent|pipeline|mixed`), `agent_usd`, `path`. `reply_sent` payload key is `path`. The frontend generated client / CostChart is not updated here (not in T5 files).
Deviations: none.
Verify: `uv run pytest tests/unit/test_analytics_segments.py -q` -> 3 passed; ruff check/format clean; throwaway-DB upgrade, downgrade -1, upgrade head all ran, DB dropped.

### T1 — Flag, step `agent`, `tool_loop`, `LLMRoundCap`
Changed: `core/config.py` (`agent_enabled`), `.env.example`, `core/llm/{registry,errors,client,__init__}.py`, `tests/unit/test_llm_client.py` (`test_r5_tool_loop_refuses_unmasked_tool_result`).
Facts the next tasks need: `LoopMessage(role: Literal["user","assistant"], content: str)` and `LoopTool(name, description, args_schema: type[BaseModel], handler: Callable[[BaseModel], Awaitable[str]])` are frozen dataclasses (positional ok). Output tool is named `final_answer`. A round = one response asking for tools other than `final_answer`; handlers run in order (args validated by `args_schema` first; a bad arg or unknown tool becomes the tool-result text, not an exception). After `max_rounds` rounds one more call is made; a further tool request raises `LLMRoundCap` before running handlers. A handler receives the validated `args_schema` instance and returns the result string (masked by the caller); its exceptions propagate. Invalid output (no tool call, final_answer mixed with other tools, schema error, `validate` reason) gets one retry, then `LLMInvalidOutput`. `_ChatModel` needs `bind_tools(tools, **kw)` returning a runnable whose `ainvoke(messages)` returns an `AIMessage` with `.tool_calls`; tools are passed as `{"name","description","parameters"}` dicts.
Deviations: none.
Verify: pytest 6 passed; config/registry assertion, no `app.domains` grep hit, ruff check/format and mypy all clean.

### T6 — Agent package base
Created: `backend/app/domains/conversation/agent/{__init__,schema,refs,checks}.py`.
Changed: `nodes/compose.py` (`draft_problem`, `format_fact` aliases, in `__all__`).
Names: `AgentTurn(language, intents, outcome, awaiting_slot, reported_done, reply)`; `PassToFlow`; `MAX_ROUNDS=6`. `TurnRefs(language, country)`: `add_card(card_id, facts)->handle`, `add_tx(tx_id, facts)->handle`, `add_group(prefix, facts)->prefix`, `card_id(h)`, `tx_id(h)`, `keys()`, `value(ref)`, `render(h)` (fenced, one JSON `{"reference","value"}` per line), `graph_update: dict`. Checks: `reply_problem(turn, refs, language)`, `fill_reply(reply, refs)`, `claims_problem(turn, verified: list[int])`.
Facts the next tasks need: `language` is `Language` ("es"|"pt") in refs/checks, not `AgentTurn.language`. `add_group` handle is the caller's prefix (use one not matching `c<N>`/`t<N>`). Facts with a key `format_fact` can't format raise ValueError.
Deviations: none.
Verify: plan Verify command passed (test_compose 5 passed, ruff, format, mypy clean).

### T2 — Escalation reason `agent_round_cap`
Changed: `policies/escalation.yaml` (v7, rule `agent_round_cap` atencion/normal), `policy/escalation.py` (`_REQUIRED_REASONS`), `handoff/schemas.py` (`HandoffReason`), `analytics/cause_groups.py` (bot_failure), `nodes/handoff_summary.py` (`_FALLBACK` ES/PT, human-approved wording).
Facts the next tasks need: not in `_FLOW_ROUTED_REASONS`; `staff.reason.agent_round_cap` i18n is T13's.
Deviations: none.
Verify: pytest policy_registry + escalation_rules → 17 passed; python assert, ruff check and format --check clean.

### T4 — ConfirmPayload.labels and Acepto / No acepto buttons
Changed: `backend/app/domains/conversation/ui.py`, `frontend/src/lib/sse.ts`, `frontend/src/components/chat/ConfirmCard.tsx`, `frontend/src/lib/i18n/es.json`, `frontend/src/lib/i18n/pt.json`.
Facts the next tasks need: field `ConfirmPayload.labels` with values `"confirm_cancel"` (default) and `"accept_decline"` (agent plans). i18n keys added after `confirm.cancel` in both files: `confirm.accept` (Acepto / Aceito), `confirm.decline` (No acepto / Não aceito).
Deviations: none. Generated API client not regenerated (not in T4 files).
Verify: all steps passed (checkpoint_serde 2 passed, ruff, biome, tsc typecheck clean).

### T7 — tools.yaml v2 preconditions and issue_plan(intent=None)
Changed: `policies/tools.yaml` (v2, `preconditions` on lock_card/block_card), `policy/tools_policy.py`, `tools/executor.py`, `tools/registry.py`, `sandbox.py`, `tests/conftest.py`.
Facts the next tasks need: model `Preconditions(status_not_in, locked)` and `ToolPolicy.preconditions` in `app/domains/policy/tools_policy.py`; helper `has_preconditions(policy) -> Callable[[str], bool]`; executor keyword-only `has_preconditions=` and alias `HasPreconditions`; `issue_plan(steps, intent: Intent | None)`, `None` + tool without preconditions (or no lookup) raises `PolicyDenied("tool_not_allowed")` after a `rule_hit`.
Deviations: none.
Verify: 19 passed; assert one-liner, ruff check/format, mypy all clean.

### T10 — Migrate dev DBs, restart worker, regenerate client (PARTIAL, stopped before `make client`)
Done: `alembic upgrade head` ran 0009 -> 0010 on latam_golden (GOLDEN_DATABASE_URL) and latam_app (default URL), both without refusal. `docker restart latam-cs-analytics-worker-1` done.
Blocked: running backend (`latam-cs-backend-1`) mounts `.claude/worktrees/cardy-agent-s0-empty-reply/backend/app`, not this checkout, so `/api/v1/openapi.json` has 0 `agent_usd`. `make client` NOT run (would generate a stale client). Needs the human: `make up` from this checkout (or restart backend on it), then rerun `make client` and the Verify.
Deviations: none.

### T9 (resumed) — Four dev scenarios
Created: `eval/scenarios/dev/` seeds `d-greeting-normal_resolution-es-mx-01`, `d-general_question-out_of_scope-pt-br-01`, `d-card_block-normal_resolution-es-mx-01` (persona CLI-F7PQP3J4AS6X, 3 cards, locked count 3), `d-card_block-multilingual-pt-br-01` (new persona CLI-00BPQUST6X8L, count 1).
Changed: `eval/personas.yaml` (appended dev persona CLI-00BPQUST6X8L, MX, credit+debit, Active; no existing entry touched).
Facts the next tasks need: `category: out_of_scope` is not in the schema, so the out-of-scope seed uses `unsupported` (file stem keeps the spec's wording). `card_controls` assertions carry no customer scoping (same as the existing seed). Not run (live LLM).
Deviations: none.
Verify: 96 cases, lint ok; 4 new d-* files; no other eval paths changed.

### T14 — Docs for propose-and-confirm
Changed: `06` §1 (R6, R8 rows), `04` §1 (`issue_plan(steps, intent: Intent | None)` fixed; `propose_plan` row and paragraph with four reason codes, no `token_id`), §3 (`ConfirmPayload.labels`, SSE and confirmations route unchanged), §5 (`tools.yaml` v2 block and paragraph); `02` §3 (paragraphs "Confirming an agent plan", "A typed message while an agent plan is open"), §5 ("Stuck conversation (agent)", thresholds three for both counters).
Facts the next tasks need: D27 not documented (not needed by the `02` §3 edit).
Deviations: none.
Verify: the three grep commands all matched.

### T11 — ScriptedLLM.tool_loop, AgentScript, agent_on, run_recorded_turn
Changed: `backend/tests/conftest.py` (kept T7's `has_preconditions` line). `Call` gained `messages`, `tool_results` (tuple[str, ...], default `()`); `ScriptedLLM.outputs["agent"]` takes `AgentScript`s.
Signatures: `AgentScript(rounds: Sequence[Sequence[tuple[str, dict[str, Any]]]], finals: Sequence[BaseModel | LLMError])` (frozen dataclass, kwargs or positional) · fixture `agent_on(monkeypatch) -> Iterator[None]` · `async run_recorded_turn(session: Session, monkeypatch, text: str, *, confirmation=None, selection=None) -> list[tuple[str, dict[str, Any]]]` (async: `await` it or wrap in `asyncio.run`).
Usage: `llm = ScriptedLLM({"agent": [AgentScript(rounds=[[("list_cards", {})]], finals=[turn])]})`; `session = make_session(cid, fakebank_dir, llm)`;
  `events = asyncio.run(run_recorded_turn(session, monkeypatch, "hola"))`  (test takes `agent_on` as a parameter)
Facts: `run_recorded_turn` patches `publish`/`add_message`/redis, so nothing is published; `Call.user` is "" for tool_loop calls (text is in `messages`); `calls[-1].tool_results` has every handler result.
Deviations: none.
Verify: test_degraded + test_non_answer 12 passed; inline script printed ok; ruff check/format clean.

### T12 — Agent read tools and `scope_facts`
Created: `backend/app/domains/conversation/agent/reads.py` (`read_tools(state, config, refs) -> list[LoopTool]`).
Changed: `state.py` (`TxOfferState.flow` adds "agent"); `agent/refs.py` (human-approved one edit: `TurnRefs.scope_topic: str | None`, `TurnRefs.scope_kind: str | None`, both default None; set by `scope_facts`, T15 reads them for `nlu_result`).
Args: `card_status(card: str|None)`; `balance_due(card: str)`; `debit_balance(card: str)`; `search_transactions(merchant_text, date_expression, amount, currency, card: handle, status: list[TxStatus])`; `explain_decline(transaction: handle|None, card: handle|None, merchant_text, amount)`; `scope_facts(topic: str)`. Bad handle -> "unknown reference..." text. `explain_decline` also covers Pending/Reversed (flow's `explain_tx`) and plain rows (`_tx_details`) by row status. Scope facts use group prefix `scope` (`scope_topic_label`, ...).
Example: `{"reference": "c1_card_mask", "value": "•••• 6475"}`, `{"reference": "c1_status", "value": "Activa"}`, `{"reference": "c1_credit_limit", "value": "US$5,000.00"}`.
Deviations: the `transaction_list` event is built from `tx_option` directly (not `offer_tx_pick`, typed for the pipeline flows and adds a template segment; flows/ read-only); `graph_update` carries `ui`, `tx_offer`, `pending` only when >1 match. Imports the flows' private builders (`_card_status_facts`, `_explain`, `_tx_details`, `_widen`, abstain's tables). Country: `state.get("country")` or refs' country.
Verify: card_status assert + checkpoint_serde 2 passed; ruff check/format (reads, refs, state) and mypy clean.

### T10 (resumed) — client regenerated
Changed: `frontend/src/client/{index,sdk.gen,types.gen}.ts` (generated by `make client`; `agent_usd`, `served_by`, `agent_round_cap` present). Both DBs `alembic current` = 0010 (head). Worker pass after recreate: no missing-column error.
Facts: generated client has no `labels` / `accept_decline` (SSE-only payload, not in OpenAPI).
Deviations: none.
Verify: full Verify chain passed, `npm run typecheck` (tsc --noEmit) clean.

### T13 — Staff analytics: agent cost series, served_by column, agent_round_cap label
Changed: `CostChart.tsx` (`agent_usd` series, `--chart-2`), `RecentInteractionsTable.tsx` (new "served_by" column before cost), `es.json`, `pt.json`.
Keys added (both files): `staff.analytics.cost.agent` (Agente/Agente), `staff.analytics.table.served_by` (Atendido por), `staff.analytics.served_by.{agent,pipeline,mixed}` (ES Agente / Flujo guiado / Mixto; PT Agente / Fluxo guiado / Misto), `staff.reason.agent_round_cap` (human-approved wording). `confirm.accept`/`confirm.decline` kept.
Deviations: none.
Verify: biome clean, agent_round_cap 1/1, grep hits, typecheck in container clean.

### T16 — Plan check and `propose_plan`
Created: `backend/app/domains/conversation/agent/plan.py`, `backend/tests/unit/test_agent_plan_check.py` (tests 1 and 2).
Signatures: `async propose_plan(args: ProposeArgs, *, state, config, refs: TurnRefs, box: PlanBox) -> str` (returns `"accepted"` or `"rejected (step 1: <code|ok>; ...)"`; reads `get_policies().tools`) · `PlanBox` (dataclass; `.update() -> dict` empty if none, `.token_id`, `.event`, `.set(token_id, event)`, `.clear()`) · `async cancel_open_plan(state, config, box) -> dict` (cancels state + box tokens, clears box, returns `{"confirmation_token_id": None, "pending": None}`) · `async check_steps(steps: list[ProposedStep], refs, bank_tools, tools_policy) -> list[str | None]`. `ProposeArgs(steps: list[ProposedStep(action: "lock"|"block", card: str)], min 1)`.
Facts the next tasks need: box update carries `confirmation_token_id`, `pending` (flow agent), `ui` and `asked_ui` (one `ConfirmEvent`, labels `accept_decline`). A box replaced by a second accepted `propose_plan` cancels the first token. `cancel_open_plan` does not touch `ui`.
Deviations: none.
Verify: 2 passed; no core.llm grep hit; ruff check/format and mypy clean.

### T15 — The `agent` node, its prompt and its routing
Created: `agent/node.py` (`agent`, `agent_tools(state, config, refs) -> list[LoopTool]`), `prompts/agent@v1.md` (slot `<<PLAYBOOKS>>`, filled by `str.replace` with every playbook as `### <type>`), `tests/unit/test_agent_happy.py`.
Changed: `graph.py` (channels `agent_enabled`/`agent_labels`/`agent_code_text`; `_entry` split into `_routes_to_agent` + `_pipeline_entry`; `_after_summarize`, `_after_agent`; node `agent` = `_guard_access(agent)`, proposed only; `"agent"` in `_BRANCH_NODES`; `run_turn` skips an `agent` update with no `agent_labels`), `nodes/load_session.py`, `docs/diagrams/turn-graph-v0.mmd`.
Facts the next tasks need: predicate `graph._routes_to_agent(state)` (flag on, not degraded, no legal hit, no pipeline flow question, typed text or a pick on `agent/transactions`); `_entry` returns "summarize" (typed) or "agent" (pick), the baseline maps both to `understand`. Tool list: add the plan tool inside `agent_tools` in `agent/node.py`. `agent_labels = {"language": turn.language, "status": clear|ambiguous|out_of_scope|out_of_market, "intents": [...], "route": node of first real intent | "abstain" | "smalltalk"}`. `_after_agent`: `agent_round_cap`→handoff_summary, failure reasons→fallback, `segments` non-empty→finish, else→understand (pass or `degraded`). `agent_code_text` is declared and reset but not read yet. `grounding` = "regenerated" when `validate` ran twice. A pick not on the agent's offer gets `nothing_pending`.
Deviations: (1) a button or step-up turn with no pipeline pause is `smalltalk` (stale click) even with the flag on, since the agent has no text to read; the later `agent_plan` task puts its own branch before this. (2) test uses `card_block` (ambiguous lock_vs_block, pause `card_block.block_kind`) not `card_unlock`: unlock on CLI-TFSINGLE0002's one unlocked card ends at the closing pause, so no flow question is left open. (3) `prompts/agent@v1.md` playbooks (T3) name `list_cards`/`get_card_details`; the prompt tells Cardy to use the equivalent tool of its list.
Verify: `pytest test_agent_happy test_graph test_non_answer test_checkpoint_serde` → 9 passed; grep clean; ruff check/format and mypy clean.

### T17 — Runner labels for agent turns, tests 6 and 8, R6 scan of `agent/`
Changed: `runner.py` (agent `nlu_result` `{language,status,intents,source:"agent"}`; `route_taken` = `agent_labels["route"]`, forced to `handoff` if the turn handed off; `reply_sent.path`; `checkpointed_offer` reads `tx_offer` for `flow == "agent"`; grounding is now read from `agent` updates too, not only `compose`). `agent/node.py` unchanged, no defect found. Runner's `_BRANCH_NODES` stays WITHOUT `agent` on purpose (comment added).
Created: `tests/unit/test_agent_reply_check.py`, `tests/unit/test_agent_fallbacks.py`. `test_r6_...py`: `scan_llm_modules` walks `agent` too; asserts `agent/node.py` is scanned and clean.
Path: `"agent"` iff node `agent` appeared this turn and `understand` did not, else `"pipeline"`; a later `agent_plan` task should set the same `agent_ran` flag where `node_name == "agent"` (add `or node_name == "agent_plan"`).
Test helpers: classifier = `make_stub_classifier({text: {"card_status": 0.95}})` passed to `make_session(..., classifier=...)` (needed for the degraded fallback, since the scripted LLM has no `nlu`). Reply text is captured by spying `InMemoryPiiVault.unmask` (the runner unmasks exactly the sent reply). Both tests run all turns inside ONE `asyncio.run` and `await get_engine().dispose()` in a `finally` (a pooled asyncpg connection otherwise breaks the next test's loop). Round-cap turn needs a `handoff_summary` script (`HandoffSummaryDraft`) and `monkeypatch.setattr(runner, "ServiceHandoffTools", lambda _ctx: session.handoff_tools)` (the runner builds the DB-backed one).
Deviations: none.
Verify: 14 passed; ruff check/format and mypy clean.

### T18 — Button node and plan in the agent turn (STOPPED, nothing changed)
Created/Changed: none.
Blocker: `agent_plan` (Acepto) must "build the calls in plan order", but nothing persists the plan's steps across turns. `ConfirmationStore` has no read method (only `issue`/`consume_step`/`cancel`); `PlanBox.update()` (T16) carries only `confirmation_token_id`, `pending`, `ui`, `asked_ui`; the stored `ConfirmEvent` steps hold `card_mask` facts, not card ids. Spec says a new checkpointed field needs the spec updated first.
Verify: not run.

### T20 — playbooks.yaml real tool names
Changed: `policies/playbooks.yaml` (card_status: list_cards+get_card_details -> `card_status`; balance_due: get_card_details -> `balance_due` / `debit_balance` for debit; card_block: get_card_details -> `card_status`).
Facts: version stays 1; loads via `load_playbooks_policy` (8 playbooks). No hash/version check changed.
Deviations: none.
Verify: grep for old names -> none; `pytest -k playbook` -> 298 deselected (no tests); one-off loader run OK.

### T18 (resumed, Option 1) — Button node and plan in the agent turn
Created: `agent/confirm.py` (`agent_plan`, `replay_open_plan(state, text=None)`, `async count_open_plan_turn(state, config, text=None)`), `tests/unit/test_agent_confirmation.py` (tests 3, 4).
Changed: `state.py` (`AgentPlanStep`, `TurnState.agent_plan_steps`), `agent/plan.py` (`PlanBox.set(token, event, steps)`; `cancel_open_plan` also clears `agent_plan_steps`), `agent/node.py` (`agent_tools(state, config, refs, box=None)` adds `propose_plan`; plan merge, D13/D16/D17, post-click turn), `graph.py`, `prompts/agent@v1.md`, `docs/diagrams/turn-graph-v0.mmd`, spec State line, `04` §1 line.
Graph: node `agent_plan` (`_guard_access`), `_entry` -> `agent_plan` via `_agent_plan_click` (flag on, button, pending agent/confirmation) before `_routes_to_agent`; edges `_after_agent_plan` -> agent | finish | fallback | handoff_summary; baseline maps it to smalltalk. `_after_agent` now sends any `handoff_queue` to handoff_summary. New channel `GraphState.agent_plan_result` ({outcome: confirmed|declined, steps}), written with `agent_code_text`, read only when `agent_code_text` is set.
Click in a test: `run_turn(session.graph, "", config=..., confirmation=ConfirmationDecision(token_id=..., decision="confirm"|"cancel"))`.
Facts: on a click turn the agent drops `pass_to_flow`, any LLMError (incl. round cap) sends `agent_code_text`, `agent_plan` emits the `intent_segments` (cancelled/resolved/handoff, intent card_block) and the agent does not. No replacement offer after a permanent block. Typed turn with the plan carried: Cardy reply + stored card, `non_answer_failures` 1,2, third hands off; replaced plan resets.
Runner (T21) must: treat `agent_plan` like `agent` for `agent_ran` (path "agent" on a click turn, which then also runs `agent`); on a click turn that hands off (no `agent` node, no `agent_labels`) route is `handoff`, path "pipeline"-or-"agent" by agent_ran (agent_plan ran => "agent"); stale-click turn (agent_plan -> finish, no labels): path "agent", route should be "card_block"-ish or "agent"; labels: agent turn after click carries `agent_labels` (route card_block, status clear); a declined/confirmed turn has `intent_segments` from agent_plan, not agent.
Verify: 22 passed (confirmation, happy, fallbacks, graph, block_flows, r6, plan_check, checkpoint_serde) + non_answer 4; ruff, format, mypy, no-llm-import grep clean.

### T19 — Block conversations end to end (PARTIAL: tests and addition A done, addition B NOT built, escalated)
Changed: `agent/confirm.py` (stale-click replay now sets `non_answer_counted`, so `finish` no longer resets the typed-turn count; only a replaced plan resets it), `tests/unit/test_agent_confirmation.py` (test 3: typed 1, stale click, typed 2, typed 3 hands off), `test_agent_happy.py` (tests 9, 10), `test_agent_fallbacks.py` (open-plan case in the round-cap test), `test_r6_...py` (token never in `Call`).
Facts: tests needing `readback` events use `make_session(..., write_audit=True)`; the confirm card is read from `values["open_question"]["ui"]`. No defect found in `node.py`/`plan.py`.
Addition B blocked: (i) holds, a plan may hold several `block` steps and the replacement flow offers one card (`selected_card_id`). Also for B: `replacement._resume_offer` needs `selected_card_id`; `segments` append, so agent_plan's offer text would precede Cardy's reply (the agent node must append it).
Verify: 13 passed (happy, fallbacks, r6, confirmation, plan_check); ruff check/format clean; mypy on `agent/` clean.

### T21 — Runner path and route for `agent_plan` turns
Changed: `runner.py` (`agent_plan` sets `agent_ran`; new `agent_plan_ran`; a handoff on any agent turn forces route `handoff`; `agent_plan` with no route set records `card_block`; unused `agent_labels` variable removed). `test_agent_confirmation.py` (stale-click turn of test 3 runs through `run_recorded_turn`, asserts path `agent`, route `card_block`; test takes `monkeypatch`).
Facts: `_BRANCH_NODES` untouched; the route is set after the loop.
Deviations: none.
Verify: 4 agent test files → 7 passed; ruff, format, mypy clean.

### T24 — Docs for the replacement amendment
Changed: `docs/solution-docs/04-contracts.md` (§3 POST messages row: `card_selection` body, `selection_invalid`/`selection_required` gates, not persisted; SSE `ui.card_picker` `{options:[{label, card_id?}], multi}`), `docs/solution-docs/02-conversation-design.md` (§3 "Replacement offer after an agent plan"; §4.9 "Several cards" block).
Facts the next tasks need: docs only; the `address_ask_multi` line says "after a no (several cards left)".
Deviations: none.
Verify: the five greps → all hit.

### T25 — Frontend picker widget (multi mode)
Changed: `frontend/src/components/chat/CardPicker.tsx` (props `multi?`, `onCardSelect?(cardIds)`; testids `card-picker-option|submit|decline`), `frontend/src/lib/sse.ts` (`PickerOption.card_id?`, `CardPickerPayload.multi?`), `es.json`/`pt.json` (`card_picker.submit`, `card_picker.decline`).
Facts the next tasks need: MessageList/ChatView not touched; T31 must pass `multi` and `onCardSelect` and post the card_ids.
Deviations: none.
Verify: biome check clean, grep counts 2/2, `npm run typecheck` clean.

### T22 — Replacement amendment contracts
Changed: `ui.py` (`PickerOption.card_id`, `CardPickerPayload.multi`), `state.py` (`TurnState.replacement_card_ids`), `templates.py` (six `*_multi` / `replacement_card_not_eligible` keys in `TemplateKind` and `_TEMPLATES`, es and pt, spec wording verbatim as one `str`).
Facts: `replacement_card_not_eligible` takes `{card_mask}`; `address_confirm_multi` takes `{address_masked}`. No existing text changed.
Deviations: none.
Verify: python assert OK; `test_templates` + `test_checkpoint_serde` 5 passed; ruff check/format and mypy clean.

### T23 — CardSelection, card_selection channel, agent_offer channel, routing
Changed: `backend/app/domains/conversation/graph.py` (`CardSelection(card_ids)`, in `__all__`; `card_selection` on `TurnInput`/`GraphState`; `GraphState.agent_offer`; two `_pipeline_entry` rows; `run_turn(card_selection=)` passes it in the input), `backend/app/domains/conversation/hosting.py` (`CardSelection` in `_checkpoint_types` roots, open item F).
Facts the next tasks need: `runner.py` and the route do not yet pass `card_selection` to `run_turn`. A typed turn at `replacement_cards` now routes to the flow node (`replacement`), which must re-send the stored offer and picker and keep the pause.
Deviations: none. `docs/diagrams/turn-graph-v0.mmd` was already modified in the tree before T23; `make graph-diagram` regenerated it, not checked for a T23-only diff.
Verify: python assert one-liner OK; `pytest test_graph/test_non_answer/test_selection_gate/test_checkpoint_serde` → 9 passed; ruff check, format --check, mypy clean; `make graph-diagram` ran.

### T26 — API and runner: card_selection body and gates
Changed: `backend/app/api/v1/conversations.py` (`PostMessageRequest.card_selection`, `_exactly_one` over four fields; gate after `selection` gate reads the checkpoint only for `card_selection`/`text` bodies: bad/unoffered ids or not at `replacement_cards` -> `409 selection_invalid`; text at `replacement_cards` -> `409 selection_required`), `backend/app/domains/conversation/runner.py` (`checkpointed_replacement_offer(host, conversation_id) -> (Pending | None, set[str])`; `start_turn`/`_run_turn_traced`/`_run_turn` take `card_selection`, default None; astream input carries it).
Facts the next tasks need: `card_selection` is not persisted as a message; T21 runner logic untouched.
Deviations: none.
Verify: block's full command -> 11 passed, ruff/format/mypy clean.

### T28 — Replacement offer after an agent plan
Changed: `agent/confirm.py` (`_replacement_offer(blocked, language)`; `_accept` success branch writes `agent_offer`: None for no block steps, one-card dict, or multi dict with `CardPickerEvent`), `agent/node.py` (`_with_offer(update, state)` merges it after the reply on the Cardy path and on the `LLMError` code-text path; drops `tx_offer`; sets pending/selected_card_id/replacement_card_ids, `asked_ui` for multi, `agent_offer: None`), `prompts/agent@v1.md` (one line), `test_agent_happy.py` (test 10 extended: block, Acepto, offer text after the result, `OFFER_REPLACEMENT_PAUSE`, `selected_card_id`, no picker; reply captured by spying `InMemoryPiiVault.unmask`).
Facts the next tasks need: offer dict keys `segment`, `ui`, `pending`, `selected_card_id`, `replacement_card_ids`. The multi branch has no test (budget).
Deviations: the plan's test name `test_block_and_balance_one_message_es` had no Acepto click; the click and second `AgentScript` were added to it.
Verify: 13 passed; no-llm-import grep, ruff check/format, mypy clean.

### T27 — flows/replacement.py on a list of cards
Changed: `backend/app/domains/conversation/flows/replacement.py` (`replacement()` now wraps `_dispatch` and sets `replacement_card_ids: None` on every ending; new `_resume_cards`, `_replay_offer`, `_card_eligible`, `_not_active_handoff`, `_address_confirm_update`, `_plan_card_ids`, `_execute_many`; `_start_replacement_plan` takes `card_ids: list[str]`).
Facts the next tasks need: the typed-turn/unoffered-ids replay reads `state["open_question"]` (set by `finish`) and sets `asked_ui` + `non_answer_counted`; the "cards" node reads `state["card_selection"].card_ids` and `state["replacement_card_ids"]` (offered ids). A selection with one eligible card runs today's one-card texts and calls.
Deviations: the module docstring no longer names `app.core.llm` (the Verify grep matched it); wording only.
Verify: 18 passed (4 files); unedited-tests, flows-only diff, grep, ruff check/format, mypy all clean.

### T29 — API client regenerated for card_selection
Changed: `frontend/src/client/{index,sdk.gen,types.gen}.ts` (generated by `make client`; no hand edits). `CardSelection {card_ids}` and `PostMessageRequest.card_selection?: CardSelection | null` present.
Facts: `CardPickerPayload.multi` and `PickerOption.card_id` are SSE-only, correctly absent from the client.
Deviations: none.
Verify: openapi has `card_selection` (count 1 line) -> `make client` ok -> grep hits `types.gen.ts` -> `npm run typecheck` in `latam-cs-frontend-1` clean.

### T31 — Chat wiring for the multi-card picker
Changed: `frontend/src/lib/api.ts` (`postCardSelection`), `MessageList.tsx` (`onCardSelect` prop; `multi`+`onCardSelect` to `CardPicker`), `ChatView.tsx` (`handleCardSelect`, `pickerOpen` disables Composer, `selection_required` in `KNOWN_ERROR_CODES`, mount decline guarded by a ref), `es.json`/`pt.json` (`errors.selection_required`).
Facts: "unused" = last `card_picker` message id != `usedPickerId` (set on submit, cleared on a failed post). On 409 `selection_required` the typed bubble is dropped, the error text shows, and a page with no open picker posts the decline once. Mount decline ignores all errors.
Deviations: none.
Verify: biome clean, greps hit, `npm run typecheck` in `latam-cs-frontend-1` clean.

### T30 — Tests 12, 13, 14 (multi-card replacement)
Created: `backend/tests/unit/test_replacement_multi.py` (`test_replace_two_blocked_cards_pt`, `test_r1_card_selection_gate`, `test_r3_unverified_second_replacement_hands_off`; helper `_to_picker`, stub `_UnverifiedSecondReplacement` delegating to `FakeBankWrites`).
Changed: none outside the new file.
Facts: all driven with `run_turn` (no runner); `readback` audit payload has no token id, so "one token" is asserted as one confirm card/one click giving two `cards.order_replacement` readbacks.
Deviations: none. No defect found in `replacement.py`, `confirm.py`, `node.py`, `graph.py` or `conversations.py`.
Verify: happy+multi 6 passed; offers+block_flows+selection_gate 13 passed; ruff check and format clean.

### R1 (verify revise)
Changed: `eval/scenarios/dev/d-card_block-multilingual-pt-br-01.yaml` (turn `say: Temporário.` before the confirm), `agent/checks.py` (`_DOUBLE_MASK` strips bullets in front of a code mask in `fill_reply`), `agent/node.py` (`_without_closing_question` applied to earlier segments in `_with_offer`), `tests/unit/test_agent_happy.py` (ES block test: done reply with doubled mask and closing question; asserts single mask and one `?`).
Facts: root cause #2 Cardy writes bullets before `{c1_card_mask}`, which code already fills as `•••• NNNN` (`format_fact`/`mask_card`); #3 Cardy's done reply ends with a question and `_with_offer` appends the offer, which has its own question. No template text changed.
Deviations: the old ordering assertion in test 10 now compares `bloqueada` with `reemplazar` (the offer wording has the last4 after).
Verify: 11 passed (happy, multi, r6); ruff, mypy, lint-imports clean; dev suite `lint_suite` ok.

### R1b (verify revise)
Changed: `nodes/next_intent.py` (`finish` strips Cardy's trailing question from the last segment before appending the owed closing), `templates.py` (`without_closing_question` lives here, a leaf module; in `agent/checks.py` it caused a circular import; `agent/node.py` imports it), `tests/unit/test_agent_happy.py` (`test_lock_done_reply_has_one_closing_question_es`).
Facts: root cause is `finish` (`next_intent.py` around line 118) appending the `closing_generic` template via `_owes_closing`. It applies to any flow's last segment, not only the agent's. A PT line that is not a question (a "e so me dizer" offer) is not stripped, no safe match without a judgement call.
Deviations: `nodes/next_intent.py` is outside the agent path, strictly needed because the closing is appended there.
Verify: happy, multi, r6 12 passed (14 with test_graph); test fails without the strip; ruff, mypy, lint-imports clean.

### R1c (verify revise)
Changed: `nodes/next_intent.py` (`finish` strips the last segment's trailing question only when `state["agent_labels"]` is truthy and segments is non-empty), `tests/unit/test_agent_happy.py` (`test_finish_keeps_trailing_question_when_agent_did_not_reply`).
Facts: marker is `agent_labels` (`graph.py:252`, reset per turn in `load_session.py:93`, set by the agent node on a reply); PT non-question line stays unhandled (known limit).
Deviations: none.
Verify: 7 files, 28 passed; ruff, mypy, lint-imports clean.

## R2 — welcome in history (user request, 2026-10-03)
- On a conversation's first graph turn, `runner._introduced_seed` now also seeds `history` with the stored welcome's masked text (`content_masked`) as the first `cardy` entry. This changes `MessageRow` (new `content_masked`), `list_messages` (selects it) and `TurnInput` (new `history`).
- Specs amended: naturalidad-cardy D8 and personalidad-cardy D10.
- Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_greeting_again.py tests/unit/test_agent_happy.py tests/unit/test_graph.py` passes (9); ruff, mypy and lint-imports are clean.

## R3 — readable card-data layout (user request, 2026-10-03)
- `prompts/agent@v1.md` "Cómo responder" has a new rule for card data: each card starts with its own line, then one fact per line, with a blank line between cards and before and after the list.
- `MessageList.tsx`: the message bubble now has `whitespace-pre-line`, so stored line breaks render. Before this, the reply arrived with `\n` already in it, but the bubble collapsed them.
- Verify: `test_agent_happy` passes (5); the frontend typecheck is clean.
