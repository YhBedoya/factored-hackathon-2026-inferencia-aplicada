# State: D1-K3 — Read-side contracts PR
<!-- ORCHESTRATOR ZONE — you own this. Implementers never edit it. -->

## Card
Card D1-K3 (G3, owner A, B reviews) · spec `docs/specs/d1-k3-contracts.md` · plan `docs/plans/d1-k3-contracts.md`
Branch `feat/d1-k3-contracts`, based on `main` (01c8ccb). Worktree `.claude/worktrees/d1-k3-contracts`.

## Conventions established for this card
- `backend/` is a standalone uv project (`requires-python = ">=3.12,<3.13"`, `[tool.uv] package = false`, no build-system). Root `pyproject.toml`/`uv.lock` untouched. `backend/uv.lock` is committed. Do not edit `.gitignore`.
- No Makefile/CI/pre-commit yet: all commands run as `cd backend && uv run …` from the worktree root.
- pytest: `pythonpath = ["."]`, `testpaths = ["tests"]`.
- Ruff: py312, line-length 100, select `E F W I B UP RUF` (no `N`, no `TC`).
- mypy: global `[tool.mypy]` + `pydantic.mypy` plugin; per-module strict flags via overrides for `app.core.*` and `app.domains.conversation.*` (`no_implicit_reexport` ⇒ explicit `__all__`).
- Pydantic: `ConfigDict(frozen=True)` / `extra="forbid"`; `Field(default_factory=list)`; `@computed_field` on `@property` (`# type: ignore[prop-decorator]` if mypy asks).
- Imports: `app.core` imports no domain; bank domain schemas import only pydantic + stdlib; `conversation/tools/bank.py` imports domain `schemas` only.
- `NLUResult`: `language`, `intents`, `status` required; `slots` defaults to empty `NLUSlots`; `clarification=None`. 26-intent catalog from `02` §1.
- `ToolError.code` is a `ClassVar[str]`; `bind_once`'s `ValueError` message contains `R1`.

## Human decisions taken mid-card
- (spec) Q1–Q6 all option (a); spec approved as written incl. D6 (`nlu` in `TurnState`).
- (T4, orchestrator) Forbidden-dep grep `fastapi|sqlmodel|alembic|langgraph|anthropic|boto3` over `backend/app` is plain substring: keep those tokens out of prose/docstrings too (state.py docstring reworded in T3 repair 1).

## Task board
| Task | Status | Agent | One-line result |
|---|---|---|---|
| T1 | done | a3ad0f933ea56b5db | backend/ uv project (py3.12) + core/errors.py; Verify PASS |
| T2 | done | ad21ebb73f8b5b3cd | customers/cards/transactions schemas; Verify PASS |
| T3 | done | ab6b146dfe5a37555 | NLUResult + TurnState w/ bind_once; R1 write-once test green; Verify PASS |
| T4 | done | a491c8754767692c6 | ToolContext + BankReadTools Protocol (4 tools) + R1 no-customer_id test; Verify PASS after 1 repair |
| T5 | done | ac03d4dd67d13bebd | 04 §1 fixed read contracts + nlu in 02 §3; Verify PASS |

<!-- IMPLEMENTER ZONE — append-only, written by the task agents. -->
## Task log

### T1 — Create the `backend/` uv project and the read-side tool errors
Created: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/{__init__.py,core/__init__.py,domains/__init__.py}`, `backend/app/core/errors.py` (`ToolError`, `NotFound`, `AccessDenied`, `ToolUnavailable`).
Facts the next tasks need: `uv sync` picked `/usr/bin/python3.12` (3.12.3) via `requires-python = ">=3.12,<3.13"`; venv at `backend/.venv`. mypy override for `app.domains.conversation.*` currently reports "unused section(s)" since that package doesn't exist yet — expected until T3/T4 add it, not an error.
Deviations: none.
Verify: `cd backend && uv sync && uv run python --version | grep -q "3.12" && uv run python -c "from app.core.errors import ToolError, NotFound, AccessDenied, ToolUnavailable; assert NotFound.code == 'not_found' and issubclass(ToolUnavailable, ToolError)" && uv run ruff check app && uv run ruff format --check app && uv run mypy app && cd .. && git diff --quiet main -- pyproject.toml uv.lock notebooks/` → passed (ruff: all checks passed, format: 4 files already formatted, mypy: no issues in 4 source files, root files untouched).

### T2 — Bank read models (`CustomerProfile`, `CardSummary`/`CardDetails`, `TxFilter`/`TxView`)
Created: `backend/app/domains/customers/{__init__.py,schemas.py}` (`CustomerProfile`), `backend/app/domains/cards/{__init__.py,schemas.py}` (`CardSummary`, `CardDetails` with `available_credit` `computed_field`), `backend/app/domains/transactions/{__init__.py,schemas.py}` (`TxStatus`, `TxFilter` with `@model_validator(mode="after")` date-window check, `TxView`).
Facts the next tasks need: `CardDetails` inherits `frozen=True` from `CardSummary`'s `model_config` (not redeclared). `TxFilter`'s validator raises plain `ValueError` inside `model_validator`, which Pydantic wraps as `ValidationError`. Ruff `RUF002` flags the Unicode minus sign (`−`) in docstrings — used ASCII `-` instead. mypy's strict override for `app.domains.conversation.*` still reports "unused section(s)" (expected until T3 adds that package, per T1's note).
Deviations: none.
Verify: `cd backend && uv run python -c "from app.domains.customers.schemas import CustomerProfile; from app.domains.cards.schemas import CardSummary, CardDetails; from app.domains.transactions.schemas import TxStatus, TxFilter, TxView" && uv run ruff check app/domains/customers app/domains/cards app/domains/transactions && uv run ruff format --check app/domains/customers app/domains/cards app/domains/transactions && uv run mypy app` → passed (ruff: all checks passed; format: 6 files already formatted; mypy: no issues in 10 source files, with the expected "unused section(s)" note for `app.domains.conversation.*`).

### T3 — NLU contract and turn state with write-once `customer_id`
Created: `backend/app/domains/conversation/{__init__.py,schemas.py}` (`Intent` 26-value literal, `NLUStatus`, `Topic`, `Clarification`, `NLUSlots`, `NLUResult`), `backend/app/domains/conversation/state.py` (`Pending`, `Fact`, `bind_once`, `TurnState`), `backend/tests/unit/test_r1_customer_scope.py` (`test_customer_id_is_write_once`; T4 appends `test_no_customer_id_reaches_tools_or_nlu` to this same file, not a new one). Also created `backend/tests/unit/` (didn't exist before; no `tests/__init__.py`, pytest collects fine under `pythonpath = ["."]`).
Facts the next tasks need: `bind_once(current, update)` takes `current: str | None`; ruff's formatter (not just the linter) reflows long `Literal[...]` and long `raise ValueError(...)` lines onto one line even past the visual 100-col wrap in the source — run `uv run ruff format` after writing, don't hand-format. `state.py`'s only mention of "langgraph" is in a docstring, not an import (checked with grep).
Deviations: none.
Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation tests && uv run ruff format --check app/domains/conversation tests && uv run mypy app` → passed (pytest: 1 passed; ruff check: all checks passed; ruff format: 4 files already formatted; mypy: no issues in 13 source files).

### T4 — `ToolContext`, `BankReadTools` facade and the R1 contract test
Created: `backend/app/domains/conversation/tools/{__init__.py,context.py,bank.py}` (`ToolContext` frozen, `BankReadTools(Protocol)` with `get_profile`/`list_cards`/`get_card_details`/`search_transactions`, `BankToolsFactory`). Appended `test_no_customer_id_reaches_tools_or_nlu` to `backend/tests/unit/test_r1_customer_scope.py` (not rewritten).
Facts the next tasks need: no implementation, FakeBank, selector or `ToolSpec` shipped (per plan). `bank.py` imports domain `schemas` only (no `conversation.schemas`/`state`).
Deviations: none.
Verify: ran the task's exact command; all steps passed except the `grep -rE "fastapi|sqlmodel|alembic|langgraph|anthropic|boto3" app` step, which fails on a pre-existing docstring in `app/domains/conversation/state.py` (T3, line 4: `` no `langgraph` dependency ... LangGraph itself will read``) — a prose mention, not an import; not caused by this task and out of scope for T4's file list. All other steps: `pytest tests/unit/test_r1_customer_scope.py -q` → 2 passed; the import one-liner → OK; `ruff check`/`ruff format --check` on `app/domains/conversation/tools tests` → all checks passed / 4 files already formatted; `mypy app` → no issues in 16 source files. Escalated to the orchestrator (see reply).
T4 re-verify: after T3's owner reworded the `state.py` docstring (option a), re-ran the exact Verify command unchanged → all steps pass (2 passed; imports OK; grep clean; ruff check/format clean; mypy: no issues in 16 source files). No files changed by me.

### T3 repair 1 — reworded `state.py` docstring to drop the lowercase `langgraph` token
Changed: `backend/app/domains/conversation/state.py` module docstring only (`"The LangGraph turn state."` → `"The turn graph's state."`; `` no `langgraph` dependency ... LangGraph itself will read `` → `no graph-framework dependency ... The graph framework itself will read``). No other lines touched.
Verify: `cd backend && ! grep -rE "fastapi|sqlmodel|alembic|langgraph|anthropic|boto3" app && uv run pytest tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation && uv run ruff format --check app/domains/conversation && uv run mypy app` → passed (grep: no matches; pytest: 2 passed; ruff check: all checks passed; ruff format: 6 files already formatted; mypy: no issues in 16 source files).

### T5 — Fixed the read-side contracts in `04` §1 and added `nlu` to `02` §3
Changed: `docs/solution-docs/04-contracts.md` §1 (added `customers.get_profile()` row returning `CustomerProfile{country, customer_status}`; expanded `cards.get_card_details` row to the concrete `CardDetails` fields with `available_credit` noted as computed and `None` for debit; expanded `transactions.search` row to the concrete `TxView` fields; `TxFilter` line now reads `merchant_names[]` with the `date_from <= date_to` / ≤366-day validation, "(proposed)" removed; appended a note after the errors sentence that K3 ships `NotFound`/`AccessDenied`/`ToolUnavailable` and D2 adds the rest). `docs/solution-docs/02-conversation-design.md` §3 (added `nlu` (current turn's `NLUResult`, or none) to the graph-state list).
Facts the next tasks need: field lists in `04` §1 now name the models built in T2/T4 rather than re-deriving them; no other lines in either doc touched.
Deviations: none.
Verify: `grep -q "customers.get_profile" docs/solution-docs/04-contracts.md && grep -q "merchant_names" docs/solution-docs/04-contracts.md && ! grep -q "merchant_ids" docs/solution-docs/04-contracts.md && grep -q "available_credit" docs/solution-docs/04-contracts.md && grep -q "fraud_score" docs/solution-docs/04-contracts.md && grep -n "Graph state" -A2 docs/solution-docs/02-conversation-design.md | grep -q "nlu" && git diff --stat main -- docs/solution-docs/` → passed (2 files changed, 6 insertions(+), 5 deletions(-)).
