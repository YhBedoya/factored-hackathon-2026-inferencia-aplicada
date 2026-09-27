# Spec: D1-K3 — Read-side contracts PR

Card: `07-execution-plan.md` D1 kickoff row K3. Owner: Dev A writes, Dev B reviews. Branch `feat/d1-k3-contracts` → `main`.

## Objective

Merge to `main` the typed contracts that Dev B's D1 work is built on, so that B can start from `main` (the K3 "Output"). The PR contains:
- a minimal `backend/` Python 3.12 uv project
- the read-tool interface `BankReadTools`, its result models and `ToolContext`
- the read-side tool errors
- `NLUResult`
- the LangGraph turn state `TurnState`

The consumers are B1 (FakeBank implements the interface), B3 (the turn graph uses `TurnState`), B4 (`nlu@v1` returns `NLUResult`) and B5 (the card status flow calls `list_cards` / `get_card_details`). No behavior ships. K3 only defines shapes, plus the two R1 guards that make those shapes safe. It serves D1 end-of-day step 3 (`make check`) by landing a backend project that lints, type-checks and tests clean.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | Flows call tools through a **session-bound facade**. `BankReadTools` is a `typing.Protocol` whose methods take no `ctx` and no `customer_id`. A factory `(ToolContext) -> BankReadTools` binds the context at construction, and the route passes the bound object to the graph in the run config | Human Q1(a). R1. ADR-025 (the session travels in the run config) |
| D2 | Run-config keys: `config["configurable"]["session"]` (ADR-025) and `config["configurable"]["bank_tools"]` (the bound facade). Graph nodes never build a `ToolContext` | Q1(a), ADR-025, `04` §1 ("built by the registry, never by the model") |
| D3 | `TurnState` is a `TypedDict` with every field in `02` §3. Fields needed after D1 are `NotRequired`. `facts` and `actions` use an append reducer; every other field is last-write | Human Q2(a) |
| D4 | `customer_id` in `TurnState` is **write-once**. Its reducer accepts the first value (the initial value is `""` or absent) and the same value again. It raises `ValueError` (message cites R1) on any different value | Q2(a), ADR-025 ("read-only"), R1 |
| D5 | `Fact{key, value, source}` (frozen Pydantic). `actions: list[dict[str, Any]]` until D2 defines `ActionResult`. B6 may add a formatting `kind` to `Fact` | Q2(a), `02` §4.2 ("each fact carries its source") |
| D6 | `TurnState` also carries `nlu: NLUResult \| None`, the current turn's NLU output | `02` §3: `route` branches on the turn's `status` and intents, so the state has to hold them. Added to `02` §3 by this card |
| D7 | Contracts are split by owner (see Touch map): bank read models in their domain `schemas.py`, `ToolContext` and the Protocol in `conversation/tools/`, `NLUResult` and `TurnState` in `conversation/`, errors in `core/errors.py` | Human Q3(a). `01` §4 ownership, `06` §2 layering (domains never import `conversation`) |
| D8 | `backend/pyproject.toml` is its own uv project: Python `>=3.12,<3.13`, runtime dependency `pydantic` only, dev group `ruff`, `mypy`, `pytest`. The root EDA `pyproject.toml` and `uv.lock` stay untouched. A1 adds FastAPI, settings, logging and Alembic | Human Q4(a), `06` §4 |
| D9 | A 4th read tool `customers.get_profile() -> CustomerProfile{country, customer_status}`. `load_session` uses it to fill `country` | Human Q5(a). `02` §2 (NLU needs country), ADR-021 (status precedence), `01` §4 (`customers` owns the masked profile) |
| D10 | Tool errors are **raised** exceptions under `ToolError` (with a `code` attribute). K3 ships `NotFound`, `AccessDenied` (the id exists but belongs to another customer) and `ToolUnavailable`. D2 adds `PolicyDenied`, `ConfirmationRequired`, `StepUpRequired` and `Conflict` | Human Q6(a), `04` §1 |
| D11 | Registry names follow `04` §1 (`customers.get_profile`, `cards.list_cards`, `cards.get_card_details`, `transactions.search`). The Python method names are in the Contracts table. There is no `ToolSpec` or registry in K3 | Assumption 1 (unchallenged). K3 row. Registry v0 is D2-A3 |
| D12 | Scope is the read side only: no write tools, `ActionResult`, confirmation or step-up | Assumption 2. `07` D2 kickoff |
| D13 | `CardDetails` fields come from `02` §4.2 and the `bank.products` columns. `available_credit` is a Pydantic `computed_field` (limit − balance; `None` if either is missing; may be negative), so FakeBank and Postgres can't disagree. Debit cards have `None` credit fields. Minimum payment is not a tool field. Only `last4` ever leaves a tool | Assumption 3. `02` §4.2 ("computed in code"), ADR-020, D2-B1 |
| D14 | Money is `Decimal` plus a currency code. Dates are `date` / `datetime`. No model field holds a formatted string | Assumption 4, R4 |
| D15 | `TxFilter.merchant_ids` becomes `merchant_names` (the data has `merchant_name` and no merchant id). The filter validates `date_from <= date_to` and a window of at most 366 days when both are set. Search returns at most 10 rows, newest first. `TxView` omits `is_fraud`, latitude/longitude and `customer_id` | Assumption 5. `04` §1 (max 10, 12-month window **(proposed)**), feature-list amendment (`fraud_score` is a data field only) |
| D16 | `NLUResult` follows `04` §2. The intent enum is the full `02` §1 catalog, including Stretch intents. Models use `extra="forbid"` | Assumption 6. `02` §1 ("from this list only"), `02` §2 (Pydantic-validated) |
| D17 | `ToolContext` follows `04` §1 exactly, as a frozen model. The D1 sandbox passes `policy_version="unversioned"` and a generated `trace_id` | Assumption 7 |
| D18 | This PR fixes the **(proposed)** field names in `04` §1 and updates `02` §3 with `nlu` | Assumption 8. `04` preamble ("until the first implementation PR fixes them"), `06` §7.4 |

## Contracts

Everything not listed here stays as in `04` §1–2.

**`app/core/errors.py`**

| Class | `code` | Raised when |
|---|---|---|
| `ToolError(Exception)` | abstract base | — |
| `NotFound` | `"not_found"` | The id doesn't exist |
| `AccessDenied` | `"access_denied"` | The id exists but belongs to another customer (audited from D2) |
| `ToolUnavailable` | `"tool_unavailable"` | Backend or data-source failure. The R11 retry wrapper keys off this class |

**`app/domains/customers/schemas.py`**
```python
class CustomerProfile(BaseModel):          # frozen
    country: Literal["MX", "CO", "AR"]     # mapped from customers.country (México/Colombia/Argentina)
    customer_status: Literal["Active", "Inactive", "Suspended", "Closed"]
```

**`app/domains/cards/schemas.py`**
```python
class CardSummary(BaseModel):              # frozen
    card_id: str                           # bank.products.product_id ("PRD-…")
    kind: Literal["credit", "debit"]       # from product_type Tarjeta Crédito / Débito
    last4: str                             # pattern ^\d{4}$ ; never the full number
    status: Literal["Active", "Blocked", "Suspended", "Closed"]
    locked: bool                           # False until app.card_controls exists (D3)

class CardDetails(CardSummary):
    currency: str
    expiration_date: date | None
    credit_limit: Decimal | None           # None for debit (ADR-020)
    current_balance: Decimal | None
    interest_rate: Decimal | None          # None for debit
    days_past_due: int | None              # bucket 0/15/30/60/90/120/180; None for debit
    source: str                            # "bank.products:<card_id>"
    @computed_field
    def available_credit(self) -> Decimal | None: ...   # credit_limit − current_balance
```

**`app/domains/transactions/schemas.py`**
```python
TxStatus = Literal["Approved", "Declined", "Pending", "Reversed"]

class TxFilter(BaseModel):                 # extra="forbid"
    date_from: date | None = None
    date_to: date | None = None            # validator: from <= to, window <= 366 days
    merchant_names: list[str] = []         # replaces 04's merchant_ids
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    currency: str | None = None
    status: list[TxStatus] = []
    card_id: str | None = None

class TxView(BaseModel):                   # frozen
    tx_id: str                             # "TRX-…"
    card_id: str
    occurred_at: datetime                  # stored transaction_date; time zone per A5 (07 §8)
    amount: Decimal
    currency: str
    amount_usd: Decimal | None
    type: str                              # Purchase/Withdrawal/Transfer/Payment/Deposit/Adjustment
    category: str | None
    merchant_name: str | None              # untrusted text (R6: data fences downstream)
    merchant_category: str | None
    channel: str
    city: str | None
    country: str | None
    status: TxStatus
    response_code: str | None              # 05/14/51/54 on declines
    fraud_score: Decimal | None
```

**`app/domains/conversation/tools/`**
```python
class ToolContext(BaseModel): ...          # exactly 04 §1, frozen

class BankReadTools(Protocol):             # bound to one ToolContext at construction
    async def get_profile(self) -> CustomerProfile: ...                      # customers.get_profile
    async def list_cards(self) -> list[CardSummary]: ...                     # cards.list_cards (credit + debit, all statuses)
    async def get_card_details(self, card_id: str) -> CardDetails: ...       # cards.get_card_details
    async def search_transactions(self, tx_filter: TxFilter) -> list[TxView]: ...  # transactions.search (≤10, newest first)

BankToolsFactory = Callable[[ToolContext], BankReadTools]
```
Every method may raise `ToolUnavailable`. The two methods that take an id may also raise `NotFound` or `AccessDenied`. A `card_id` in `TxFilter` that isn't the customer's raises `AccessDenied`. K3 ships no implementation and no `BANK` selector: FakeBank and the selector are B1, Postgres is D2-A3.

**`app/domains/conversation/schemas.py`**: `NLUResult`, `NLUSlots`, and the `Intent`, `NLUStatus`, `Topic` and `Clarification` literals, as in `04` §2. Details:
- `language`: `es|pt|mixed`.
- `intents`: `list[Intent]`, ordered, over the full `02` §1 catalog.
- `NLUSlots.card_hint` matches `^(credit|debit|last4:\d{4})$`.
- `amount` is a `Decimal`.
- `extra="forbid"` on both models.

**`app/domains/conversation/state.py`**
```python
class Pending(TypedDict):
    flow: str; node: str; awaiting_slot: str | None

class TurnState(TypedDict):
    customer_id: Annotated[str, bind_once]            # D4
    language: NotRequired[Literal["es", "pt"]]        # reply language (02 §7)
    country: NotRequired[Literal["MX", "CO", "AR"]]
    mode: NotRequired[Literal["bot", "human"]]
    nlu: NotRequired[NLUResult | None]                 # D6
    intent_queue: NotRequired[list[Intent]]
    pending: NotRequired[Pending | None]
    slots: NotRequired[NLUSlots]
    selected_card_id: NotRequired[str | None]
    clarification_failures: NotRequired[int]
    confirmation_token_id: NotRequired[str | None]     # used from D2/D3
    facts: NotRequired[Annotated[list[Fact], add]]
    actions: NotRequired[Annotated[list[dict[str, Any]], add]]
    escalation_reason: NotRequired[str | None]

class Fact(BaseModel):                                  # frozen
    key: str; value: str | int | Decimal | date | datetime | None; source: str
```
`bind_once(current, update)`:
- returns `update` if `current` is `""` or `None`
- returns `current` if `update == current`
- raises `ValueError` otherwise

It is a plain function. K3 adds no langgraph dependency.

## Touch map

```
backend/pyproject.toml                          new: uv project, py3.12, pydantic; dev ruff/mypy/pytest; ruff, mypy, pytest config
backend/uv.lock                                 new
backend/app/__init__.py, core/__init__.py       new
backend/app/core/errors.py                      new
backend/app/domains/__init__.py                 new
backend/app/domains/customers/{__init__,schemas}.py      new
backend/app/domains/cards/{__init__,schemas}.py          new
backend/app/domains/transactions/{__init__,schemas}.py   new
backend/app/domains/conversation/__init__.py, schemas.py, state.py   new
backend/app/domains/conversation/tools/__init__.py, context.py, bank.py   new (re-export ToolContext, BankReadTools, BankToolsFactory)
backend/tests/unit/test_r1_customer_scope.py    new
docs/solution-docs/04-contracts.md              §1: get_profile row, CardDetails/TxView/TxFilter fields, error scope note
docs/solution-docs/02-conversation-design.md    §3: add `nlu` to the graph state list
```
mypy runs in strict mode on `app/core` and `app/domains/conversation` (`06` §4, proposed). The planner picks the Ruff rule set.

## Test list

| Test | Proves |
|---|---|
| `test_r1_customer_scope.py::test_no_customer_id_reaches_tools_or_nlu` | R1 at the contract level. No `BankReadTools` method has a `customer_id` parameter (checked with `inspect.signature`). `TxFilter`, `NLUResult` and `NLUSlots` have no `customer_id` field. `NLUResult.model_validate({... "customer_id": "X"})` raises `ValidationError` |
| `test_r1_customer_scope.py::test_customer_id_is_write_once` | R1 plus ADR-025 "read-only". `bind_once("", "C1") == "C1"` and `bind_once("C1", "C1") == "C1"`, while `bind_once("C1", "C2")` raises `ValueError` |

There are no schema, validator or import tests (test budget). The "Done when" line is proved by the commands in Success criteria.

## Boundaries

- **Always:** keep `customer_id` out of every tool parameter and every LLM-facing model (R1). Keep money as `Decimal` and never add formatted-string fields (R4). Point back to `04`/`02` instead of duplicating them in docstrings.
- **Ask first:** adding any runtime dependency beyond `pydantic`. Adding a field to `TurnState` or a method to `BankReadTools` beyond this spec. Changing the root `pyproject.toml`.
- **Never:**
  - Add FastAPI, settings, logging, Alembic, Docker or a Makefile (that is A1/A2).
  - Add FakeBank, a `BANK` selector or any Protocol implementation (that is B1/D2-A3).
  - Add write tools, `ActionResult`, confirmation, step-up or `ToolSpec` (D2).
  - Import an LLM SDK.
  - Read or commit `data/`.
  - Touch `eval/scenarios/heldout/`.

## Success criteria

1. `cd backend && uv sync` succeeds on Python 3.12.
2. `uv run python -c "from app.domains.conversation.tools import ToolContext, BankReadTools, BankToolsFactory; from app.domains.conversation.schemas import NLUResult; from app.domains.conversation.state import TurnState, Fact; from app.domains.cards.schemas import CardSummary, CardDetails; from app.domains.transactions.schemas import TxFilter, TxView; from app.domains.customers.schemas import CustomerProfile; from app.core.errors import ToolError, NotFound, AccessDenied, ToolUnavailable"` exits 0.
3. In `backend/`, `uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest -q` all pass. pytest reports exactly the 2 tests above, both green.
4. `[project].dependencies` in `backend/pyproject.toml` lists only `pydantic`. `grep -rE "fastapi|sqlmodel|alembic|langgraph|anthropic|boto3" backend/app` returns nothing.
5. `git diff --stat main -- pyproject.toml uv.lock notebooks/` is empty.
6. `04-contracts.md` §1 shows the `customers.get_profile` row, the concrete `CardDetails` and `TxView` fields, `merchant_names` in `TxFilter`, and the note that K3 ships only the read-side errors. `02` §3 lists `nlu` in the graph state.
7. The PR to `main` is approved by Dev B (it touches tools, so ADR-018 requires review) and squash-merged. Dev B can then `git pull` and import the contracts on `main` (K3 "Output").

## Open questions

| Question | Who decides |
|---|---|
| Time-zone semantics of `TxView.occurred_at` (UTC vs local) | Dev A in D1-A5 (`07` §8). The field type doesn't change |
| Handling a null value in a required field (`status`, `currency`) from the ~5% nulls | The A5 data contracts (Pandera/dbt). The models stay strict |
| Whether `facts` is cleared per turn (the append reducer keeps them in the checkpoint) | Dev B in B3/B6 |
| Turn-local fields B3 may need (masked message, reply draft) | Dev B in B3. They are additive, and Dev A reviews them |
