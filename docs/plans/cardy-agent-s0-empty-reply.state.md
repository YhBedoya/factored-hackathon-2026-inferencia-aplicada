# State: REQ-cardy-agent-s0 — Empty reply in the current pipeline
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card REQ-cardy-agent-s0 (slice S0 of `docs/requirements/cardy-agent.md`, owner A; safety-critical, Dev B reviews) · spec `docs/specs/cardy-agent-s0-empty-reply.md` · plan `docs/plans/cardy-agent-s0-empty-reply.md`
Branch `feat/cardy-agent-s0-empty-reply`, based on `develop` (51c72cc). Runs in the git worktree `.claude/worktrees/cardy-agent-s0-empty-reply`: work only under that root, plain commands, never `cd` to the main checkout.

## Conventions established for this card
The full list is the plan's "Facts checked against the repo" (lines 9–86). The ones every task must follow:
- No change under `flows/`, nor to `runner.py`, `hosting.py`, `ui.py`, `templates.py`, `schemas.py`, `policies/`, `conversation/tools/`. No migration, no new dependency, no client regeneration.
- `open_question` is a checkpointed `TurnState` field; `OpenQuestion` is declared in `state.py` beside `Pending` with `text: str`, `ui: list[Any]`.
- `non_answer_failures` is a checkpointed `TurnState` int. `clarification_failures` is never touched by a non-answer.
- Two per-turn channels on `GraphState` (not `TurnState`), both reset by `load_session`: `asked_ui` and `non_answer_counted`.
- `open_question.ui` = the asking node's own events (`update.get("ui", [])`), not the turn's `ui` list. `open_question.text` = last entry of `segments`.
- Only `finish` writes or clears `open_question` (plus `takeover.return_to_bot` clears it).
- Tests: exactly four, in `backend/tests/unit/test_non_answer.py`, with `ScriptedLLM`. No test calls a real LLM.
- `backend/.venv` exists in the worktree (git-ignored). Never run `uv add`, `uv sync` or `uv lock`.

## Human decisions taken mid-card
- (spec) Keep-and-re-ask covers every flow question except the `anything_else` closing pause.
- (spec) The re-ask is the flow's own question with its UI.
- (spec) Second non-answer on a `confirmation` pause: cancel the plan, then hand off `clarification_exhausted`.
- (spec) No intent and no open question on the LLM path: `clarify_rephrase`, not counted.
- (spec) Counter is per open question (`non_answer_failures`); 1 re-asks, 2 hands off.
- (planner) Re-ask mechanism: replay a stored question (`open_question`), no flow module change.
- (planner) `open_question.ui` holds the asking node's own events.
- Derived, shown to the human, not vetoed: `fact_values.record(<stored sentence>)` on a replay (spec D16); any intervening turn resets `non_answer_failures`; second per-turn channel `non_answer_counted` (plan).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | aaaa74ae | 7 source files + test_non_answer.py; 6 passed, ruff/format/mypy clean, protected paths unchanged |
| T2 | done | a1c2f53f | 02 §3/§5 and 04 §6 updated; verify clean, 2 files, +7 −2 |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T2 — Docs for the non-answer rule
Changed: `docs/solution-docs/02-conversation-design.md` (§3 state list + new "non-answer" paragraph after P1; §5 sentence after the rules table), `docs/solution-docs/04-contracts.md` (§6 `fact_values` sentence + new replayed-question bullet after `awaiting_slot`).
Facts the next tasks need: both `04` additions contain "replayed question"; UI wording is "the asking node's own UI events".
Deviations: none.
Verify: grep checks pass; `git diff --stat develop -- docs/solution-docs` → 2 files changed, 7 insertions(+), 2 deletions(-).

### T1 — Non-answer re-ask, `open_question` capture and the `finish` backstop
Changed: `state.py` (`OpenQuestion`, `non_answer_failures`, `open_question`), `graph.py` (`_keep_open_question(name, node)` wrapper, `asked_ui` and `non_answer_counted` channels; wraps the 8 flow nodes between `_track_segments` and `_guard_access`), `nodes/load_session.py`, `nodes/route.py`, `nodes/smalltalk.py`, `nodes/next_intent.py` (`finish` + `enqueue`), `takeover.py`.
Created: `backend/tests/unit/test_non_answer.py` (4 tests).
Facts the next tasks need: `fact_values.record` is imported at module level in `graph.py`; `_answer_fits` and `handoff` are imported inside the wrapper.
Deviations: none.
Verify: `pytest test_non_answer.py test_checkpoint_serde.py` → 6 passed; mermaid, ruff check, ruff format --check, mypy all clean; no diff vs develop in flows/, runner, hosting, ui, templates, test_checkpoint_serde.

### T1 repair 1 — queue from policy (R8)
Changed: `graph.py` (`_keep_open_question` exhaustion path: queue is `rule_queue(get_policies().escalation, "clarification_exhausted")`, not the literal; `rule_queue` imported at module level from `app.domains.policy.escalation`). `policies/escalation.yaml:7` resolves it to `atencion`, so behaviour is unchanged.
Deviations: none.
Verify: `pytest tests/unit/test_non_answer.py` → 4 passed; ruff check, ruff format --check, mypy on graph.py clean.
