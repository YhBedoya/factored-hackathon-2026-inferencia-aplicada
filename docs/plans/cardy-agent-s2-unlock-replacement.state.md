# State: REQ-cardy-agent-s2 — Unlock and replacement
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-cardy-agent-s2 (slice S2 of `docs/requirements/cardy-agent.md`, owner A) · spec `docs/specs/cardy-agent-s2-unlock-replacement.md` · plan `docs/plans/cardy-agent-s2-unlock-replacement.md`
Branch `feat/cardy-agent-s2-unlock-replacement`, based on `develop` @ 04c137a. Worktree `.claude/worktrees/cardy-agent-s2` — work only there.

## Conventions established for this card
- Full repo facts: plan §"Facts checked against the repo" (read the bullets your task names).
- Every backend Verify runs with `AGENT_ENABLED=false` (the worktree `.env` sets it true; three flag-off tests fail otherwise).
- Frontend typecheck `<FE-TYPECHECK>` (`latam-cs-frontend-1` mounts the main checkout, so use a throwaway container; run from the worktree root; volume may need re-reading per plan §Facts line 28):
  `! (docker run --rm -v "$PWD/frontend:/app" -v 9c244070f54d69deceda4c92b13d4b9908b614825deadda3fee879cf07d9cd95:/app/node_modules:ro -w /app node:22 npm run typecheck --silent 2>&1 | grep 'error TS' | grep -v -e 'routeTree.gen' -e '^src/routes/')`
- The worktree sandbox refuses long chained `&&` commands: run each part of a Verify as its own plain command (same checks).
- All tests use ScriptedLLM (fake LLM). New tests use a 6-digit OTP code; existing tests untouched except the one T2 assertion.
- Tasks that export names later tasks import (T1, T3, T7, T8): write the REAL names in your Task log entry.

## Human decisions taken mid-card
- Plan review: the planner's 7 readings accepted as written (plan §"Decisions settled by the human"); T9 may touch `runner.py`, `graph.py` resume Literals, `docs/diagrams/turn-graph-v0.mmd`.
- Old test `test_agent_plan_check.py::test_precondition_rejects_blocked_card`: keep it, swap only the last assertion's tool to `disputes.create_claim` (T2); spec criterion 1 amended to allow it. Never degrade behaviour to keep an old test.
- V2 R5 edge (flag turned off while an agent address pause is open; text reached NLU raw): fix = vault the text with `vault.put_address`, drop it, clear the pause and plan, code reply `action_cancelled`, no LLM call (T17). Verify note: use `make check AGENT_ENABLED=false` (env-prefix form is overridden by .env); biome only via the pinned container (host npx biome is a wrong package).
- V5b wrong OTP (verifyOtp's refresh retry turns 401 otp_invalid into session expiry, burning attempts): human chose fix now for both agent and pipeline modals (T18). V5b prompt wording (PT sentence names Spanish buttons; Cardy words a replacement offer itself): human chose fix agent@v2.md now (T19).
- OTP-exit amendment D25–D33 (human, after browser test): 3 wrong OTP codes at any OTP pause -> server-triggered handoff step_up_failed (fraudes/high, via handoff_summary); X/Esc = Cancel on every OTP modal; step_up_cancel at any OTP pause; typed text 409 agent-only; outside click no-op (T20–T28).
- V7b staff summary invented "0 intentos fallidos" (no attempt count in the summary input): human chose to give `handoff_summary` the real facts for `step_up_failed` (failed-code count = `step_up_max_failures`, requested action not executed) in its tokenized input, plus one test assertion -> T30.
- `actions_taken[].at` holds the handoff time, not the action time (`nodes/handoff.py:119`, `at=now`): human said leave it for a later card. No task placed.

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a510f029c2834a5cd | tools.yaml v3 + Preconditions block_origin_in/replacement_eligible; 11 passed, lint/mypy clean |
| T2 | done | a17e42e70da909961 | issue_plan(intent=None) raises StepUpRequired + rule_hit, no token; old test swapped to create_claim; 16 passed |
| T3 | done | a1bc4beacf53fc51e | AgentPlanStep unlock/replace+address_ref, OtpRequiredPayload.cancellable, agent_plan_ready; 5 passed |
| T4 | done | ab5792b6d287bc2e0 | agent@v2.md + card_unlock/replacement_request playbooks + .env.example 6-digit note; v2 says 'acciones legales' (grep ban on 'reclamos'); wiring is T11 |
| T5 | done | ab1c8c12d1ecffe09 | docs ADR-035 S2 amendment, 02 §3/4.7/4.9, 04 §1/3/5 updated; greps pass |
| T6 | done | a3d382d0ab0a8cd92 | OtpModal cancellable/onCancel, 6-digit numeric, otp-cancel, no dismiss; biome+typecheck clean |
| T7 | done | a10a8145edd019011 | agent/plan.py unlock/replace, v3 checks, OTP/address pauses, issue_stored_plan, PlanHandoff; 7 passed, lint-imports ok |
| T8 | done | aa45548021505901f | agent_step_up/agent_address in step_up.py; import ok, r6 5 passed, lint/mypy/lint-imports clean |
| T9 | done | a9447a107ae97d6ee | resume Literal widened, _entry routes agent OTP/address pauses, runner labels, 409 cancel_invalid/otp_required gates, diagram regenerated; 27 passed, lint clean |
| T10 | done | a5411b6b78326f72d | Acepto runs unlock/replace, plan_segments everywhere, tracking_id in result; 15 passed, lint clean |
| T11 | done | a2b65569ce0d56b3b | node.py prompt v2, box pauses survive, D2 offer + bot_offered, PlanHandoff caught, post-OTP event; 16 passed, lint clean; imports confirm._replacement_offer |
| T12 | done | a6baff2f042163675 | postStepUpCancel, composer locked under cancellable modal, 409 otp_required reopens; mount cancel sequenced after decline (shares declinedOnMountRef); not browser-tested |
| T13 | done | a67a69d4df965bb09 | test_agent_step_up.py R2 (a-e) + R5 address; 2 passed; 'no write ran' = no confirmation_used audit |
| T14 | done | acb06bb988b77625e | 5 passed after T15 (unlock es/pt, replace es-on_file/pt-new, declined offer bot_offered) |
| T15 | done | a71dc76cc8567b6a9 | tracking_id plain-string formatter in compose._format_fact; 12 passed, lint clean |
| T16 | done | a14af0be807d8916b | pinned biome format on ChatView.tsx/OtpModal.tsx; biome ci clean, typecheck clean |
| T17 | done | a06e5ce3503e87487 | flag-off agent address pause -> agent_address vaults+drops, clears plan, action_cancelled, no LLM; new R5 test; 22 passed, lint clean |
| T18 | done | ab75d1b0903d58c36 | verifyOtp single call; otp_invalid -> inline error, no refresh; other 401 keeps refresh; biome+typecheck clean |
| T19 | done | ae8ccc633348f8361 | agent@v2 refers to buttons generically; Cardy never mentions replacement on unlock refusal/offer; 10 passed |
| T20 | done | a169b2615bcc5aa2a | tools.yaml v4 step_up_max_failures 3, escalation v8 step_up_failed fraudes/high, reason added |
| T21 | done | aab1d22a543f5be54 | step_up_failed_handoff template, cancellable default, staff fallback, security cause group |
| T22 | done | a93d4199d685e8d3e | one OTP modal, X/Esc cancel, conversation_id on verify, otp_handoff, staff label |
| T23 | done | a32c8a117388f4c08 | ADR-035 OTP-exit bullet, 02 §3 OTP pauses + §5 row |
| T24 | done | ac5fa8d9b95ab910e | step_up_exit.py step_up_failed + otp_cancel (code only) |
| T25 | done | ae299dacdd278e725 | verify_otp max_failures, OtpInvalid.failures, reset_otp_failures, auth.py uses step_up_max_failures |
| T26 | done | abe8d3eddbce75bdc | _otp_pause + _entry routing, nodes/edges both systems, checkpointed_otp_pause, widened gate, diagram |
| T27 | done | aa387b26d7afe563c | otp/verify ownership 404 first, step_up_failed turn, 429 otp_handoff, test_otp_verify limit 3 |
| T28 | done | ad0f8587020ece119 | test_otp_exits.py 4 passed (R2 agent+pipeline, R13 ownership, pipeline cancel) |
| T29 | done | a927f19c63afafcdf | 04 §3/§5 + service/graph/conversations docstrings fixed; ruff clean, 6 passed |
| T30 | done | a13d1f215b4e75881 | step_up_failed summary gets {failed_codes} (policy) + not-executed fact; 4 passed, lint/mypy clean |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T5 — Docs: ADR-035 S2 amendment, 02, 04
Changed: `docs/solution-docs/decision-log.md` (ADR-035 S2 amendment bullet), `02-conversation-design.md` (§3 agent pauses/nodes note, §4.7, §4.9 agent-path notes), `04-contracts.md` (§1 propose_plan row + issue_plan step-up, §3 resume/cancel_invalid/otp_required/cancellable, §5 tools.yaml v3 + paragraph).
Facts the next tasks need: docs only; names used are `agent/otp`, `agent/address`, `agent_step_up`, `agent_address`, `step_up_cancel`, `OtpRequiredPayload{tool, cancellable}`.
Deviations: none.
Verify: the plan's grep chain → all 7 greps matched.

### T1 — `tools.yaml` v3 and the `Preconditions` fields
Changed: `policies/tools.yaml` (version 3; `unlock_card` `{block_origin_in: [customer_lock]}`, `order_replacement` `{replacement_eligible: true}`); `backend/app/domains/policy/tools_policy.py` (`Preconditions`: `status_not_in` default `[]`, new `block_origin_in: list[str] | None`, `replacement_eligible: bool | None`; docstring names `not_locked`/`permanent_block`/`not_eligible`).
Facts the next tasks need: no new exports; `Preconditions` stays frozen/`extra="forbid"`; no conversation import added.
Deviations: none.
Verify: policy_registry + r2_confirmed_writes 11 passed; version/field assertions ok; grep -c preconditions = 4; ruff check/format, mypy clean.

### T3 — Contracts: AgentPlanStep, OtpRequiredPayload.cancellable, agent_plan_ready
Changed: `backend/app/domains/conversation/state.py` (`AgentPlanStep.action` adds unlock/replace, `address_ref: NotRequired[str]`), `ui.py` (`OtpRequiredPayload.cancellable: bool = False`), `templates.py` (`agent_plan_ready` in `TemplateKind` and `_TEMPLATES`, es/pt single strings).
Facts the next tasks need: `get_template("agent_plan_ready", lang)` returns a str; no existing template changed.
Deviations: none.
Verify: assert one-liner (run via a temp script, same asserts) ok; `pytest test_templates.py test_checkpoint_serde.py` → 5 passed; ruff check/format and mypy clean.

### T2 — Step-up checked at agent plan issue
Changed: `backend/app/domains/conversation/tools/executor.py` (`issue_plan`: when `intent is None`, after the has_preconditions gate, step needing step-up with invalid gate records `rule_hit step_up_required` and raises `StepUpRequired`, before `confirmations.issue`); `backend/tests/unit/test_agent_plan_check.py` (last assertion now `disputes.create_claim` step).
Facts: constructor and intent path unchanged; `_run` write-time check stays.
Deviations: none.
Verify: spec script → ok; pytest 5 files → 16 passed; ruff check/format, mypy clean.

### T4 — Prompt agent@v2, playbooks, demo OTP note
Created: `backend/app/domains/conversation/prompts/agent@v2.md` (copy of v1; plan section covers unlock/replace, `step_up_required`/`address_required`, `rejected (<card>: <code>)`, new codes, "step-up verified, plan shown").
Changed: `policies/playbooks.yaml` (`card_unlock`, `replacement_request`, version stays 1); `.env.example` (6-digit comment).
Facts the next tasks need: `AGENT_PROMPT_VERSION` (or equivalent) still points at v1; wiring v2 is not in T4. v1 text "reclamos legales" became "acciones legales" in v2 (verify greps `reclamos`).
Deviations: none.
Verify: all checks pass (run as split commands; the playbooks check via a /tmp script with PYTHONPATH=.).

### T6 — OTP modal widget (cancellable)
Changed: `frontend/src/components/chat/OtpModal.tsx`, `frontend/src/lib/sse.ts`, `frontend/src/lib/i18n/{es,pt}.json`.
Facts the next tasks need: `OtpModal` props are `conversationId`, `onVerified`, `cancellable?: boolean`, `onCancel?: () => void`. `OtpRequiredPayload = { tool: string; cancellable?: boolean }`. With `cancellable`: digits-only 6-char numeric input, Send enabled only at 6 digits, `otp-cancel` button, corner close button hidden (no `onOpenChange`, so Esc/outside click do nothing). Caller (T8) must pass `cancellable={payload.cancellable}` and `onCancel`.
Deviations: none.
Verify: biome check clean, `grep -c` → 1 and 1, FE-TYPECHECK → no errors outside routeTree.gen/routes.

### T12 — Chat wiring (cancellable modal)
Changed: `frontend/src/lib/api.ts` (`postStepUpCancel`), `frontend/src/components/chat/ChatView.tsx` (`otpCancellable` state, composer disabled under cancellable modal, `handleOtpCancel`, `409 otp_required` re-opens modal + drops bubble, mount cancel chained after the picker decline).
Facts: Cancel closes the modal then posts; `cancel_invalid` ignored; `otp_required` 409 uses tool "agent" if no modal open.
Deviations: mount cancel is chained after `postCardSelection` (not parallel) to avoid racing two turns.
Verify: biome check clean, both greps match, FE-TYPECHECK no errors outside routeTree.gen/routes.

### T7 — Plan module: unlock/replace, v3 checks, pauses, stored-plan issuer
Changed: `backend/app/domains/conversation/agent/plan.py` only.
Exports (all in `__all__`): `AGENT_OTP_PAUSE`, `AGENT_ADDRESS_PAUSE` (dicts), `PlanBox`, `PlanHandoff` (`.update`), `ProposeArgs`, `ProposedStep` (`address`), `otp_pause_update(steps, language) -> dict`, `address_pause_update(steps, language) -> (update, question_text)`, `otp_text(language)`, `issue_stored_plan(state, config, steps) -> (token_id, ConfirmEvent)`, `plan_segments(steps, status, awaiting_slot=None)`, `plan_labels(steps, language)`, `check_steps`, `cancel_open_plan`, `propose_plan`.
PlanBox members: `token_id`, `event`, `after_reply`, `permanent_blocked`, `opened` (property), `update()`, `set(token_id, event, steps)`, `pause(update)`, `clear()`.
Facts: `check_steps(steps, refs, bank_tools, tools_policy, state, config)` (no box); `propose_plan` fills `box.permanent_blocked` from `permanent_block` codes. `PlanBox.set` does NOT add `intent_segments` (node adds them); pauses do. `_rejected` is now `rejected (c1: code, ...)`. `check_steps` and `propose_plan` can raise `PlanHandoff`: T10 must catch it. node.py/confirm.py callers of `check_steps` not updated (T10/T11).
Deviations: none.
Verify: spec script → ok; pytest plan_check + r6 → 7 passed; ruff check/format, mypy, lint-imports clean.

### T10 — Acepto runs unlock and replacement; per-action segments
Changed: `backend/app/domains/conversation/agent/confirm.py` only (`_segment` removed; `plan_segments` used in accept/failure/decline/count_open_plan_turn with `card_block` fallback; unlock/replace calls and texts; helpers `_replace_call`, `_result_step`).
Facts: `agent_plan_result.steps` entries are `{"action","card_id"}` plus `"tracking_id"` for replace; confirm.py never called `check_steps`/`propose_plan`, so no PlanHandoff handling needed here.
Deviations: none.
Verify: 4 test files → 15 passed; ruff check/format, mypy, lint-imports clean.

### T8 — Code nodes `agent_step_up` and `agent_address`
Created: `backend/app/domains/conversation/agent/step_up.py` (`__all__ = ["agent_step_up", "agent_address"]`; both `async (state, config) -> dict`).
Facts the next tasks need: `agent_step_up` reads `state.get("resume")` as a plain str (`step_up_cancel` / `step_up`; the graph Literal widening is T9). Texts: with LLM up, cancel and plan-issued use `agent_code_text`; OTP-again and address-question always use `segments` + `agent_labels` (no LLM). LLM down: every branch uses `segments`, `agent_labels` (when steps exist), `escalation_reason: None`. `agent_address` always replies with `segments: [agent_plan_ready]` (no `agent_code_text`); `agent_step_up` issued branch also writes `agent_plan_result {"outcome": "issued", steps}`. Non-`step_up` input or empty stored steps → OTP pause again.
Deviations: none.
Verify: import ok; r6 test 5 passed; ruff check/format, mypy, lint-imports clean.

### T11 — Agent node: prompt v2, pauses, D2 offer, bot_offered, post-OTP event
Changed: `backend/app/domains/conversation/agent/node.py` only.
Facts the next tasks need: `_PROMPT = PromptRef("agent", 2)`; node merges `box.update()` when `box.opened` (box `intent_segments` win), appends `box.after_reply` after the reply; `permanent_blocked` -> `card_unlock` segment `abstained`, `block_permanent_no_undo` per card, offer via `_with_offer(update, state, offer=_replacement_offer(...))` unless an agent confirm/otp/address pause is open (AQ4); `_with_offer` sets `bot_offered_flow="replacement"`; `PlanHandoff` caught beside `PassToFlow`; `agent_plan_result.outcome=="issued"` (steps `{action, card_id}`) -> no propose_plan/pass_to_flow, event text per D10, only `language/segments/agent_labels/grounding` written; `_plan_event` reads `step["tracking_id"]` for replace; LLMError with an OTP/address pause open returns the pause with `otp_text` (D8). Imports `_replacement_offer` from `confirm.py` (T10 must keep that name/signature).
Deviations: none. Stray `.venv` at worktree root from an early `uv run` (gitignored; rm was denied).
Verify: pytest 5 files -> 16 passed; ruff check/format, mypy, lint-imports clean.

### T9 — Graph routing, runner labels, API gates
Changed: `graph.py` (`_agent_pause`, `_entry` routes `agent_step_up`/`agent_address`, `_after_agent_pause`, both nodes `_guard_access`-wrapped, baseline -> smalltalk), `runner.py` (resume Literal; both nodes set `agent_ran` + record labels like `agent`), `api/v1/conversations.py` (`resume` Literal; `409 cancel_invalid` / `409 otp_required` gates via `checkpointed_replacement_offer`), `docs/diagrams/turn-graph-v0.mmd` regenerated (uncommitted).
Facts: `resume` is `Literal["step_up","step_up_cancel"] | None` everywhere; the pause gate reads the checkpoint once for text or cancel bodies.
Deviations: none.
Verify: 27 passed; ruff check/format, mypy, lint-imports clean.

### T13 — Tests 1 and 2: agent step-up gate and address-never-to-LLM
Created: `backend/tests/unit/test_agent_step_up.py` (`test_r2_plan_needs_valid_step_up`, `test_r5_new_address_never_reaches_llm`).
Facts: card id is `PRD-TFS2CRED0001` on `CLI-TFSINGLE0002`; (c) calls `post_message` with a stub `turn_host` and monkeypatched `start_turn`; "no write ran" is asserted as no `confirmation_used` audit event (`tool_result` also fires for the `get_block_origin` read).
Deviations: none. No production defect found.
Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_agent_step_up.py -q` → 2 passed; ruff check and format --check clean.

### T14 — Tests 3, 4, 5: unlock, replace, declined offer
Created: `backend/tests/unit/test_agent_unlock_replace.py` (5 tests; `test_unlock_happy[es,pt]` and `test_declined_offer_cancelled_bot_offered` pass).
Facts: `otp_required` is a UI event (read `state["ui"]`), not an audit event; `run_recorded_turn` has no `resume`, so OTP/address turns use `run_turn`.
Deviations: none in the test; BOTH `test_replace_happy` params FAIL on a production defect: `agent/node.py::_plan_event` registers `Fact(key="tracking_id")` via `refs.add_card`, and `TurnRefs._register` calls `nodes/compose.py::_format_fact`, which has no `tracking_id` branch -> `ValueError: compose: no formatter for fact key 'tracking_id'`, so the Acepto turn fails (`turn.failed`) and the readback reply is never sent. Fix: add `"tracking_id"` to the plain-str keys in `_format_fact` (compose.py ~line 380).
Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_agent_unlock_replace.py -q` -> 2 failed, 3 passed; ruff check/format clean.

### T15 — Formatter for the `tracking_id` fact
Changed: `backend/app/domains/conversation/nodes/compose.py` (`_format_fact`: `tracking_id` added to the plain-string keys).
Facts the next tasks need: none.
Deviations: none.
Verify: pytest (unlock_replace + step_up + happy) → 12 passed; ruff check/format, mypy, lint-imports clean.

### T16 — Biome format fix (verifier)
Changed: `frontend/src/components/chat/ChatView.tsx`, `frontend/src/components/chat/OtpModal.tsx` (formatting only).
Facts the next tasks need: host `npx biome` is an unrelated v0.3.3 package, never use it. Use the pinned 2.5.14 in a container from the worktree root: `docker run --rm -v "$PWD/frontend:/app" -v 9c244070f54d69deceda4c92b13d4b9908b614825deadda3fee879cf07d9cd95:/app/node_modules:ro -w /app node:22 npx biome ci .` (swap `ci .` for `format --write <files>` to fix).
Deviations: none.
Verify: `biome ci .` → Checked 101 files, no fixes; FE typecheck filtered grep → no output.

### T17 — Flag-off address pause never reaches the LLM (R5 fix)
Changed: `graph.py` (`_flag_off_address_pause`; `_entry` routes plain text there to `agent_address`), `agent/step_up.py` (`agent_address` with flag off: vault, clear, `action_cancelled` as `segments`, cancelled plan segments), `api/v1/conversations.py` (gate comment now cites D15/D17), `tests/unit/test_agent_step_up.py` (`test_r5_flag_off_address_never_reaches_llm`).
Facts: `_agent_pause` unchanged (S1 D27); no graph edges changed, so the diagram was not regenerated.
Deviations: none.
Verify: the 6 named test files with AGENT_ENABLED=false → 22 passed; ruff, format, mypy, lint-imports clean.

### T18 — Wrong OTP inline error, no session refresh
Changed: `frontend/src/lib/api.ts` (`verifyOtp` calls once; only a 401 whose detail is not `otp_invalid` goes through `withAuthRetry`).
Facts: OtpModal unchanged (already maps ApiError `otp_invalid` / `too_many_attempts` to existing i18n keys and re-enables input); no i18n keys added. Assumes 429 detail is `too_many_attempts`. Not browser-verified.
Deviations: OtpModal.tsx not touched (not needed).
Verify: biome ci . → clean (101 files); `npm run typecheck` in latam-cs-frontend-1 → no errors.

### T19 — agent@v2 prompt wording
Changed: `backend/app/domains/conversation/prompts/agent@v2.md` (buttons referred to generically, never quoting labels; explicit ban on mentioning/suggesting a replacement when unlock fails or code adds the offer).
Facts the next tasks need: no prompt hash/registry/snapshot test pins agent@v2 content; PromptRef("agent", 2) unchanged; no code/matching logic touched.
Deviations: none.
Verify: `AGENT_ENABLED=false uv run pytest -q` (unlock_replace, step_up, plan_check) from backend/ → 10 passed.

### T23 — Docs: ADR-035 OTP-exit line, 02 §3 and §5
Changed: `docs/solution-docs/decision-log.md` (ADR-035 OTP-exit amendment bullet), `02-conversation-design.md` (§3 "OTP pauses (agent and pipeline)" paragraph before the P1 paragraph, `resume` Literal now three values, §5 "Step-up failed" row).
Facts the next tasks need: docs only; node names `step_up_failed`, `otp_cancel`.
Deviations: none.
Verify: 4 greps → ADR line found; step_up_failed count 3; otp_cancel found; old Literal gone (no match).

### T20 — Policies tools.yaml v4, escalation.yaml v8, step_up_failed reason
Changed: `policies/tools.yaml` (version 4, `step_up_max_failures: 3`), `policies/escalation.yaml` (version 8, `step_up_failed: {queue: fraudes, priority: high}`), `ToolsPolicy.step_up_max_failures: int = Field(ge=1)` (no default, docstring says so), `_REQUIRED_REASONS` and `HandoffReason` gain `"step_up_failed"`.
Facts the next tasks need: `load_policies().tools.step_up_max_failures` is the OTP failure cap; `load_policies().escalation.rules['step_up_failed']` resolves to fraudes/high.
Deviations: none.
Verify: 21 passed (policy_registry, escalation_rules, handoff_packet); load_policies assert OK; grep checks ok (preconditions count 4); ruff check/format and mypy clean.

### T22 — One OTP modal (D31)
Changed: `OtpModal.tsx` (always 6-digit + Send/Cancel; required `onCancel`, `onHandoff`; X/Esc via `onOpenChange` -> onCancel; `onInteractOutside` prevented; `otp_handoff` -> onHandoff, no error/no resume), `ChatView.tsx` (`otpCancellable` removed; composer disabled on `!!otpTool`; new `handleOtpHandoff` closes modal + keeps composer off), `lib/api.ts` (`verifyOtp(code, conversationId)` posts `conversation_id`), `es.json`/`pt.json` (`staff.reason.step_up_failed`).
Facts the next tasks need: `sse.ts` untouched (its `cancellable?` type stays, unread).
Deviations: none.
Verify: biome ci (5 files) exit 0; typecheck (throwaway container, per state-file form) no errors; grep -c cancellable -> 0 and 0; both i18n keys at line 107.

### T21 — step_up_failed template, OTP default, fallback, cause group
Changed: `templates.py` (`step_up_failed_handoff` in `TemplateKind` + `_TEMPLATES`, D32 es/pt), `ui.py` (`OtpRequiredPayload.cancellable` default True, docstring D31), `nodes/handoff_summary.py` (`_FALLBACK["step_up_failed"]` es/pt verbatim), `analytics/cause_groups.py` (`"step_up_failed": "security"`).
Facts: `_FALLBACK` is typed `dict[str, ...]`, so no dependency on T20's HandoffReason; `flows/` untouched.
Deviations: none.
Verify: test_templates+test_block_flows 11 passed; assert one-liner ok; both greps match; ruff check/format and mypy clean.

### T25 — Identity service: step-up limit argument, OtpInvalid.failures, counter reset
Changed: `backend/app/domains/identity/service.py` (`LoginLimiter.reset`, `_RedisLoginLimiter.reset`, `verify_otp(..., *, max_failures, limiter, settings)`, `OtpInvalid(message, *, failures)` with `.failures`, new `reset_otp_failures(session, *, limiter=None)` logging `auth.otp_reset`; exported in `__all__`), `backend/app/api/v1/auth.py` (route passes `max_failures=get_policies().tools.step_up_max_failures`).
Facts the next tasks need: `max_failures` is required keyword-only; any other caller or fake LoginLimiter must be updated by its owner.
Deviations: none.
Verify: test_login_pii 2 passed; ruff check, format --check, mypy, lint-imports all clean.

### T24 — Code nodes `step_up_failed` and `otp_cancel`
Created: `backend/app/domains/conversation/nodes/step_up_exit.py` (`step_up_failed`, `otp_cancel`, private `_flow_intent`).
Facts the next tasks need: both are `async (state: GraphState, config: RunnableConfig) -> dict[str, Any]`; `_FLOW_INTENT` imported inside `_flow_intent` (falls back to the flow name); `step_up_failed` leaves `pending` untouched; not wired into graph.py.
Deviations: none.
Verify: import ok; r6 test 5 passed; ruff check/format, mypy, lint-imports (4 kept) clean.

### T26 — Graph routing, runner, widened cancel gate, diagram
Changed: `graph.py` (`resume` Literal x3, `_otp_pause`, `_entry` routes `step_up_failed`/`otp_cancel` after human check, nodes `step_up_failed`/`otp_cancel` `_guard_access`-wrapped outside `if not baseline`, edges to `handoff_summary`/`finish`, entry map both systems), `runner.py` (Literals, `checkpointed_otp_pause`, node loop labels/route_taken), `api/v1/conversations.py` (gate: cancel at any OTP pause, text 409 only at agent pause), `docs/diagrams/turn-graph-v0.mmd` regenerated.
Facts: `checkpointed_otp_pause(host, conversation_id)` is imported by conversations.py but not added to runner `__all__` (neither is `checkpointed_replacement_offer`); without labels the exit nodes do not set `agent_ran`.
Deviations: none.
Verify: 21 passed; ruff check/format, mypy, lint-imports clean.

### T27 — `/auth/otp/verify`: ownership, handoff turn, `429 otp_handoff`
Changed: `backend/app/api/v1/auth.py` (`OtpVerifyRequest.conversation_id`; route takes `request`; private `_hand_off_if_paused`; imports `get_owned_conversation` from `app.api.v1.conversations`, no cycle, lint-imports clean), `backend/tests/integration/test_auth.py` (`test_otp_verify` loops `step_up_max_failures` times).
Facts the next tasks need: ownership runs before the code; handoff only when at limit and conversation open+bot+`checkpointed_otp_pause` not None; `TurnInProgress` -> 429 too_many_attempts, counter kept; success -> `reset_otp_failures` then 429 otp_handoff; no turn-cap/count.
Deviations: none.
Verify: `AGENT_ENABLED=false uv run pytest tests/integration/test_auth.py -k test_otp_verify -q` -> 1 passed; ruff check/format, mypy, lint-imports clean.

### T28 — Tests 6, 7, 8: OTP exits
Created: `backend/tests/unit/test_otp_exits.py` (`test_r2_third_wrong_code_hands_off[agent,pipeline]`, `test_r13_otp_conversation_must_be_owned`, `test_pipeline_otp_cancel`; in-file `_FakeLimiter` + `_Harness`).
Facts: routes called as functions (`verify_otp`, `post_message`) with stub `turn_host`; `start_turn` recorded in `auth` and `conversations`; limiter patched over `identity_service._default_limiter`; `store.get_conversation` patched on the module.
Deviations: none. No production defect found.
Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_otp_exits.py -q` -> 4 passed; ruff check and format --check clean.

### T29 — OTP-exit doc/docstring fixes
Changed: `docs/solution-docs/04-contracts.md` (§3 otp/verify row: handoff_summary, not "no LLM"; §5 tools.yaml version 4), `identity/service.py` (login/verify_otp docstrings), `conversation/graph.py` (2 spots), `api/v1/conversations.py` (PostMessageRequest): step_up_cancel = any OTP pause.
Facts the next tasks need: text-only; no behaviour change.
Deviations: none.
Verify: grep 'no LLM' leaves only lines 163/173 (unrelated); ruff check/format clean; 6 passed.

### T30 — step_up_failed facts in handoff_summary input
Changed: `backend/app/domains/conversation/nodes/handoff_summary.py` (for reason `step_up_failed` only: placeholder `{failed_codes}` = `get_policies().tools.step_up_max_failures`, filled in code; two ES `hecho:` lines in the fenced data block: wrong-code count placeholder and "acción NO se ejecutó"), `backend/tests/unit/test_otp_exits.py` (one assertion pair in `test_r2_third_wrong_code_hands_off`; draft now uses `{failed_codes}`).
Facts the next tasks need: the prompt `handoff_summary@v1` bans digits, so the count goes through a placeholder (R4); prompt untouched and does not force a count. `step_up_exit.py` untouched.
Deviations: none.
Verify: `AGENT_ENABLED=false uv run pytest tests/unit/test_otp_exits.py -q` → 4 passed; ruff check/format, mypy clean; no `handoff_summary` unit tests by -k (skipped).
