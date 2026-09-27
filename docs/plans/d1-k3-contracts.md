# Plan: D1-K3 — Read-side contracts PR

Spec: [`docs/specs/d1-k3-contracts.md`](../specs/d1-k3-contracts.md) · Branch: `feat/d1-k3-contracts`

## Facts checked against the repo

- **Nothing of `backend/` exists** on `main` (`01c8ccb`) or on this branch. Every file in the touch map is new except the two docs. There is no `docs/plans/` directory before this plan.
- **Root project is unrelated and frozen:** `/pyproject.toml` is the EDA project `latam-bank-cs` (`requires-python >=3.11`, duckdb/pandas/matplotlib, dev jupyterlab). It has **no `[tool.uv]` / `[tool.uv.workspace]` table**, so `backend/pyproject.toml` is a standalone uv project and `uv sync` run inside `backend/` creates `backend/.venv` and `backend/uv.lock` without touching the root `uv.lock`.
- **Toolchain on this machine:** `uv 0.11.15`. Python 3.12.3 is at `/usr/bin/python3.12` (uv also sees 3.11, 3.13, 3.14). `requires-python = ">=3.12,<3.13"` makes uv pick 3.12. No `.python-version` file is needed, and the touch map has none.
- **No Makefile, CI, pre-commit or `.importlinter` exist** (A2/A3). Every command runs with `uv run` from `backend/`. The Verify commands below are written relative to the worktree root and start with `cd backend &&`.
- **Git-ignore is already sufficient:** the root `.gitignore` ignores `.venv/` and `__pycache__/` at any depth, and the Ruff, mypy and pytest caches each write their own `.gitignore`. Do **not** edit `.gitignore`. `backend/uv.lock` **is** committed.
- **Project config conventions (set in T1, followed by all later tasks):**
  - Virtual project: `[tool.uv] package = false`, no `[build-system]`. `app` is imported from the `backend/` cwd, so `[tool.pytest.ini_options]` sets `pythonpath = ["."]` and `testpaths = ["tests"]`.
  - Ruff (the spec leaves the rule set to the plan): `target-version = "py312"`, `line-length = 100`, `lint.select = ["E", "F", "W", "I", "B", "UP", "RUF"]`. No `N` (it would flag `NotFound`), no `TC` (Pydantic needs runtime annotations).
  - mypy: `strict` is a **global-only** option in mypy config, so "strict on `app/core` and `app/domains/conversation`" is set as a global `[tool.mypy]` (`python_version = "3.12"`, `plugins = ["pydantic.mypy"]`, `warn_unused_configs`, `warn_redundant_casts`) plus one `[[tool.mypy.overrides]]` for `module = ["app.core.*", "app.domains.conversation.*"]` with the per-module strict flags: `disallow_untyped_defs`, `disallow_incomplete_defs`, `disallow_untyped_calls`, `disallow_untyped_decorators`, `disallow_any_generics`, `disallow_subclassing_any`, `check_untyped_defs`, `warn_return_any`, `warn_unused_ignores`, `no_implicit_reexport`, `strict_equality`, `extra_checks`. The `pydantic.mypy` plugin comes with the `pydantic` runtime dependency, so it adds no dependency.
- **Pydantic idioms for this card:** frozen is `model_config = ConfigDict(frozen=True)`, and forbid is `ConfigDict(extra="forbid")`. List defaults use `Field(default_factory=list)`, not `= []`, which keeps Ruff `RUF012` quiet. `computed_field` is stacked on `@property` so that consumers see a `Decimal | None` and not a method. If mypy reports `prop-decorator` on it, add `# type: ignore[prop-decorator]` on the `@computed_field` line (the pattern Pydantic documents).
- **Import direction:** `app.core` imports no domain. The `customers`, `cards` and `transactions` schemas import only `pydantic` and the stdlib, never `app.domains.conversation`. `conversation/state.py` imports `conversation/schemas.py`. `conversation/tools/bank.py` imports the three domain `schemas` modules (schemas only, never a repository). Because of `no_implicit_reexport`, `conversation/tools/__init__.py` must declare `__all__ = ["BankReadTools", "BankToolsFactory", "ToolContext"]`.
- **`NLUResult` defaults (the literal reading of `04` §2, where the example shows `null`s):** `language`, `intents` and `status` are required. `slots` defaults to an empty `NLUSlots` (`Field(default_factory=NLUSlots)`), and `clarification` defaults to `None`. Every `NLUSlots` field defaults to `None`, except `amount_approx: bool = False`. `currency` is `Literal["COP", "ARS", "USD", "MXN"] | None`, and `pending_answer` is `str | None`. A minimal valid payload is therefore `{"language": "es", "intents": ["card_status"], "status": "clear"}`.
- **Intent catalog size:** `02` §1 lists 26 intents: 11 feature intents (`card_status` … `general_question`), 4 conversation-management intents (`greeting`, `thanks_close`, `affirm`, `deny`) and 11 Stretch intents (`travel_notice` … `prequalification`).
- **`ToolError.code`** is a `ClassVar[str]` on each subclass. `bind_once`'s `ValueError` message must contain the string `R1`.
- **Doc anchors:** `04-contracts.md` line 27 has the errors sentence, lines 29–44 the MVP tools table, and line 48 the `TxFilter` line (`merchant_ids`, "12-month window **(proposed)**"). `02-conversation-design.md` line 48 has the graph-state list.

## Components

| Component | Path | Depends on |
|---|---|---|
| uv project + tool config | `backend/pyproject.toml`, `backend/uv.lock` | nothing |
| Read-side tool errors | `backend/app/core/errors.py` | nothing |
| Customer profile model | `backend/app/domains/customers/schemas.py` | pydantic |
| Card models (`CardSummary`, `CardDetails`) | `backend/app/domains/cards/schemas.py` | pydantic |
| Transaction models (`TxStatus`, `TxFilter`, `TxView`) | `backend/app/domains/transactions/schemas.py` | pydantic |
| NLU contract (`NLUResult`, `NLUSlots`, literals) | `backend/app/domains/conversation/schemas.py` | pydantic |
| Turn state (`TurnState`, `Pending`, `Fact`, `bind_once`) | `backend/app/domains/conversation/state.py` | `conversation/schemas.py` |
| Tool context + read facade (`ToolContext`, `BankReadTools`, `BankToolsFactory`) | `backend/app/domains/conversation/tools/{context,bank,__init__}.py` | the three domain schemas |
| R1 contract tests | `backend/tests/unit/test_r1_customer_scope.py` | state, schemas, tools |
| Doc updates | `docs/solution-docs/04-contracts.md` §1, `docs/solution-docs/02-conversation-design.md` §3 | the built models (real field names) |

## Build order

1. **Project + errors (T1).** Nothing can be imported, linted or type-checked until `uv sync` has produced a venv with the configured Ruff, mypy and pytest.
2. **Bank read models (T2).** These are leaf modules. The facade in step 4 imports them.
3. **NLU contract + turn state + write-once test (T3).** `state.py` needs `Intent`, `NLUResult` and `NLUSlots` from `schemas.py`. The `bind_once` R1 test lands with the code it guards.
4. **Tool context + facade + contract-level R1 test (T4).** This step needs steps 2 and 3, and the R1 test checks all of them. Its Verify runs the spec's full import line (success criterion 2).
5. **Docs (T5).** Written last, so `04` records the field names as actually built and not as planned.

## Touch map

| File | New / modified | What changes |
|---|---|---|
| `backend/pyproject.toml` | new | uv project (py `>=3.12,<3.13`, deps `pydantic` only, dev group ruff/mypy/pytest), `[tool.uv] package=false`, Ruff/mypy/pytest config |
| `backend/uv.lock` | new | generated by `uv sync` |
| `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/domains/__init__.py` | new | empty package markers |
| `backend/app/core/errors.py` | new | `ToolError`, `NotFound`, `AccessDenied`, `ToolUnavailable` |
| `backend/app/domains/customers/{__init__,schemas}.py` | new | `CustomerProfile` |
| `backend/app/domains/cards/{__init__,schemas}.py` | new | `CardSummary`, `CardDetails` (+ `available_credit` computed field) |
| `backend/app/domains/transactions/{__init__,schemas}.py` | new | `TxStatus`, `TxFilter` (+ window validator), `TxView` |
| `backend/app/domains/conversation/__init__.py`, `schemas.py`, `state.py` | new | NLU literals and models; `Pending`, `Fact`, `bind_once`, `TurnState` |
| `backend/app/domains/conversation/tools/__init__.py`, `context.py`, `bank.py` | new | `ToolContext`; `BankReadTools` Protocol, `BankToolsFactory`; re-exports |
| `backend/tests/unit/test_r1_customer_scope.py` | new | the spec's 2 R1 tests |
| `docs/solution-docs/04-contracts.md` | modified | §1: `customers.get_profile` row, concrete `CardSummary`/`CardDetails`/`TxView` fields, `TxFilter` with `merchant_names` and the 366-day window, a note that K3 ships only the read-side errors, "(proposed)" dropped for the names fixed here |
| `docs/solution-docs/02-conversation-design.md` | modified | §3: `nlu` added to the graph-state list |

Out of the blast radius: the root `pyproject.toml` and `uv.lock`, `notebooks/`, `.gitignore`, any Makefile, any FastAPI, Alembic or LLM code.

## Risks and mitigations

| Risk | Mitigation (task) |
|---|---|
| `uv sync` resolves against the root project or rewrites the root `uv.lock` | Standalone `backend/pyproject.toml` with no workspace, run from `backend/`. T1's Verify includes `git diff --quiet main -- pyproject.toml uv.lock notebooks/` |
| uv picks Python 3.13/3.14 | `requires-python = ">=3.12,<3.13"`. T1's Verify prints `uv run python --version` and checks for 3.12 |
| `app` isn't importable under pytest (virtual project, not installed) | `pythonpath = ["."]` in the pytest config (T1). T3's Verify runs pytest |
| Per-module `strict = true` is rejected by mypy, or silently ignored | Explicit strict flags in an override (T1, see Facts). `warn_unused_configs` flags a mistyped module pattern |
| `available_credit` types as a method, which breaks B5 under mypy | `@computed_field` on `@property` (T2). T2's Verify runs mypy on `app` |
| A runtime dependency beyond pydantic creeps in (FastAPI, langgraph, an LLM SDK) | T1 fixes the dependency list. T4's Verify runs the spec's `grep -rE "fastapi\|sqlmodel\|alembic\|langgraph\|anthropic\|boto3" backend/app` and expects no hits |
| A `customer_id` parameter or field reaches a tool method or an LLM-facing model (R1) | `test_no_customer_id_reaches_tools_or_nlu` (T4) |
| The R1 test passes vacuously (for example, the NLU payload is invalid for another reason, so `ValidationError` is raised anyway) | T4's acceptance requires a positive control: the same payload without `customer_id` validates, and the Protocol has at least the 4 read methods |
| `customer_id` is overwritten mid-conversation through the state (R1, ADR-025) | `bind_once` + `test_customer_id_is_write_once` (T3) |
| Circular import between `conversation` and the bank domains | One-way import direction (Facts). T4's Verify runs the full import line |
| `04` drifts from the code | T5 reads the built schema files, not the spec, and records the field names from them |
| Offline machine: `uv sync` can't download packages | T1 escalates. It does not vendor packages or change the dependency list |

## Tests

| Test | Written in |
|---|---|
| `backend/tests/unit/test_r1_customer_scope.py::test_customer_id_is_write_once` | T3 |
| `backend/tests/unit/test_r1_customer_scope.py::test_no_customer_id_reaches_tools_or_nlu` | T4 |

No schema, validator or import tests. The spec's success criteria map to tasks as follows. SC1 and SC4 (dependency list): T1. SC2 (import line) and SC4 (grep): T4. SC6: T5. SC3 (full lint, format, mypy and pytest, exactly 2 tests) and SC5 (root untouched): the verifier's single end-of-card run. SC7 (Dev B approval and squash merge): the orchestrator's gate.

## Tasks

- [ ] T1: Create the `backend/` uv project and the read-side tool errors
  - Depends on: nothing
  - Read exactly these: spec §"Decisions" D8 and D10, spec §"Contracts" → `app/core/errors.py`, this plan's §"Facts checked against the repo" (project config conventions)
  - Acceptance: `backend/pyproject.toml` declares `requires-python = ">=3.12,<3.13"`, `[project].dependencies` = `pydantic` only, a `dev` dependency group with `ruff`, `mypy` and `pytest`, `[tool.uv] package = false`, and the Ruff, mypy (global + strict override for `app.core.*` and `app.domains.conversation.*`) and pytest (`pythonpath = ["."]`, `testpaths = ["tests"]`) config exactly as listed in Facts. `uv sync` creates `backend/uv.lock` on Python 3.12. `app/core/errors.py` defines `ToolError(Exception)` and its subclasses `NotFound`, `AccessDenied` and `ToolUnavailable`, each with `code: ClassVar[str]` = `"not_found"` / `"access_denied"` / `"tool_unavailable"`. The docstrings point to `04` §1 instead of restating it. The root `pyproject.toml`, `uv.lock` and `notebooks/` are unchanged.
  - Verify: `cd backend && uv sync && uv run python --version | grep -q "3.12" && uv run python -c "from app.core.errors import ToolError, NotFound, AccessDenied, ToolUnavailable; assert NotFound.code == 'not_found' and issubclass(ToolUnavailable, ToolError)" && uv run ruff check app && uv run ruff format --check app && uv run mypy app && cd .. && git diff --quiet main -- pyproject.toml uv.lock notebooks/`
  - Files: `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/core/errors.py`, `backend/app/domains/__init__.py`

- [ ] T2: Add the bank read models (`CustomerProfile`, `CardSummary`/`CardDetails`, `TxFilter`/`TxView`)
  - Depends on: T1 (the `backend/` venv and the Ruff/mypy config; the `app/domains/__init__.py` package marker)
  - Read exactly these: spec §"Contracts" → `app/domains/customers/schemas.py`, `app/domains/cards/schemas.py`, `app/domains/transactions/schemas.py`; spec §"Decisions" D13–D15; this plan's §"Facts checked against the repo" (Pydantic idioms, import direction)
  - Acceptance: the three `schemas.py` files define exactly the spec's fields and types. `CustomerProfile`, `CardSummary`, `CardDetails` and `TxView` are frozen. `CardSummary.last4` is constrained to `^\d{4}$`. `CardDetails.available_credit` is a `computed_field` property: `credit_limit − current_balance`, `None` if either is `None`, and it may be negative. `TxFilter` is `extra="forbid"`, its list fields use `default_factory=list`, and a model validator rejects `date_from > date_to` and a window over 366 days when both dates are set. Money is `Decimal`, and no field holds a formatted string. No field is named `customer_id`. These modules import only the stdlib and `pydantic`.
  - Verify: `cd backend && uv run python -c "from app.domains.customers.schemas import CustomerProfile; from app.domains.cards.schemas import CardSummary, CardDetails; from app.domains.transactions.schemas import TxStatus, TxFilter, TxView" && uv run ruff check app/domains/customers app/domains/cards app/domains/transactions && uv run ruff format --check app/domains/customers app/domains/cards app/domains/transactions && uv run mypy app`
  - Files: `backend/app/domains/customers/__init__.py`, `backend/app/domains/customers/schemas.py`, `backend/app/domains/cards/__init__.py`, `backend/app/domains/cards/schemas.py`, `backend/app/domains/transactions/__init__.py`, `backend/app/domains/transactions/schemas.py`

- [ ] T3: Add the NLU contract and the turn state with the write-once `customer_id` (R1 test)
  - Depends on: T1 (venv, mypy strict override on `app.domains.conversation.*`, pytest config)
  - Read exactly these: spec §"Contracts" → `app/domains/conversation/schemas.py` and `app/domains/conversation/state.py`, spec §"Decisions" D3–D6 and D16; `docs/solution-docs/04-contracts.md` §2 and `docs/solution-docs/02-conversation-design.md` §1 (the intent catalog table, for the `Intent` literal)
  - Acceptance: `conversation/schemas.py` defines the `Intent` (all 26 intents in `02` §1), `NLUStatus`, `Topic` and `Clarification` literals, plus `NLUSlots` and `NLUResult`. Both models use `extra="forbid"`. `card_hint` matches `^(credit|debit|last4:\d{4})$`, `amount` is `Decimal | None`, and the defaults are those in this plan's Facts. `conversation/state.py` defines `Pending`, `Fact` (frozen), `bind_once` and `TurnState`, exactly as the spec's code block shows: `customer_id: Annotated[str, bind_once]`, `facts` and `actions` annotated with `operator.add`, every other field `NotRequired`. `bind_once` returns `update` when `current` is `""` or `None`, returns `current` when `update == current`, and raises `ValueError` otherwise, with a message that contains `R1`. There is no langgraph import. `backend/tests/unit/test_r1_customer_scope.py` contains `test_customer_id_is_write_once`, which asserts `bind_once("", "C1") == "C1"`, `bind_once(None, "C1") == "C1"` and `bind_once("C1", "C1") == "C1"`, and that `bind_once("C1", "C2")` raises `ValueError`. Both files pass the strict mypy override.
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py -q && uv run ruff check app/domains/conversation tests && uv run ruff format --check app/domains/conversation tests && uv run mypy app`
  - Files: `backend/app/domains/conversation/__init__.py`, `backend/app/domains/conversation/schemas.py`, `backend/app/domains/conversation/state.py`, `backend/tests/unit/test_r1_customer_scope.py`

- [ ] T4: Add `ToolContext`, the session-bound `BankReadTools` facade and the contract-level R1 test
  - Depends on: T2 (`CustomerProfile`, `CardSummary`, `CardDetails`, `TxFilter` and `TxView` in the domain `schemas.py` modules), T3 (`NLUResult` and `NLUSlots` in `conversation/schemas.py`; the existing `test_r1_customer_scope.py`, which this task appends to and does not rewrite)
  - Read exactly these: spec §"Contracts" → `app/domains/conversation/tools/` (with the paragraph under it) and the Test list row `test_no_customer_id_reaches_tools_or_nlu`, spec §"Decisions" D1, D2 and D17; `docs/solution-docs/04-contracts.md` §1 (the `ToolContext` block only)
  - Acceptance: `tools/context.py` defines `ToolContext`, exactly the fields in `04` §1, frozen. `tools/bank.py` defines `BankReadTools(Protocol)` with the 4 async methods `get_profile()`, `list_cards()`, `get_card_details(card_id: str)` and `search_transactions(tx_filter: TxFilter)`. None of them has a `ctx` or `customer_id` parameter. Each has a one-line comment naming its registry name (`customers.get_profile`, `cards.list_cards`, `cards.get_card_details`, `transactions.search`) and the errors it may raise. `bank.py` also defines `BankToolsFactory = Callable[[ToolContext], BankReadTools]`. `tools/__init__.py` re-exports the three names with `__all__`. There is no implementation, FakeBank, selector or `ToolSpec`. `test_no_customer_id_reaches_tools_or_nlu` asserts that:
    - the public methods of `BankReadTools` are at least the 4 above, and no `inspect.signature` among them has a `customer_id` parameter;
    - `customer_id` is not in `TxFilter.model_fields`, `NLUResult.model_fields` or `NLUSlots.model_fields`;
    - `{"language": "es", "intents": ["card_status"], "status": "clear"}` validates as `NLUResult`, and the same dict plus `"customer_id": "X"` raises `ValidationError` (a positive control, so the test can't pass vacuously).

    Both R1 tests pass.
  - Verify: `cd backend && uv run pytest tests/unit/test_r1_customer_scope.py -q && uv run python -c "from app.domains.conversation.tools import ToolContext, BankReadTools, BankToolsFactory; from app.domains.conversation.schemas import NLUResult; from app.domains.conversation.state import TurnState, Fact; from app.domains.cards.schemas import CardSummary, CardDetails; from app.domains.transactions.schemas import TxFilter, TxView; from app.domains.customers.schemas import CustomerProfile; from app.core.errors import ToolError, NotFound, AccessDenied, ToolUnavailable" && ! grep -rE "fastapi|sqlmodel|alembic|langgraph|anthropic|boto3" app && uv run ruff check app/domains/conversation/tools tests && uv run ruff format --check app/domains/conversation/tools tests && uv run mypy app`
  - Files: `backend/app/domains/conversation/tools/__init__.py`, `backend/app/domains/conversation/tools/context.py`, `backend/app/domains/conversation/tools/bank.py`, `backend/tests/unit/test_r1_customer_scope.py`

- [ ] T5: Record the fixed read-side contracts in `04` §1 and add `nlu` to `02` §3
  - Depends on: T2 (the built field names in the three domain `schemas.py` files), T4 (the `BankReadTools` method names)
  - Read exactly these: spec §"Decisions" D9–D15 and D18; `docs/solution-docs/04-contracts.md` §1 (lines 5–48); `docs/solution-docs/02-conversation-design.md` §3 (line 48 onward, the graph-state list); for the field lists, the built files `backend/app/domains/{customers,cards,transactions}/schemas.py`
  - Acceptance:
    - The `04` §1 MVP tools table has a `customers.get_profile()` row returning `CustomerProfile{country, customer_status}`.
    - The `cards.list_cards` / `cards.get_card_details` rows list the concrete `CardSummary` / `CardDetails` fields as built, with `available_credit` computed and `None` for debit cards.
    - The `transactions.search` row lists the concrete `TxView` fields.
    - The `TxFilter` line reads `merchant_names[]` with a 366-day window. "(proposed)" is gone from those names.
    - Under the errors sentence, a note says K3 ships `NotFound`, `AccessDenied` and `ToolUnavailable`, and D2 adds the rest.
    - `02` §3's graph-state list includes `nlu` (the current turn's `NLUResult`, or none).
    - Nothing else in either doc changes, and field lists name the model instead of re-explaining the spec's reasoning.
  - Verify: `grep -q "customers.get_profile" docs/solution-docs/04-contracts.md && grep -q "merchant_names" docs/solution-docs/04-contracts.md && ! grep -q "merchant_ids" docs/solution-docs/04-contracts.md && grep -q "available_credit" docs/solution-docs/04-contracts.md && grep -q "fraud_score" docs/solution-docs/04-contracts.md && grep -n "Graph state" -A2 docs/solution-docs/02-conversation-design.md | grep -q "nlu" && git diff --stat main -- docs/solution-docs/`
  - Files: `docs/solution-docs/04-contracts.md`, `docs/solution-docs/02-conversation-design.md`
