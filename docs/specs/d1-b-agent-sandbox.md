# Spec: D1-B — Agent core in the sandbox (G3)

Card: `07-execution-plan.md` D1, Dev B rows B1–B8. Owner: Dev B. Branch `feat/d1-b-agent-sandbox`. Builds on the K3 contracts (`docs/specs/d1-k3-contracts.md`, commit 7693af9).

## Objective

Deliver the agent core that runs in a terminal against local data:
- a customer-scoped `FakeBank` over DuckDB (B1)
- a thin, provider-agnostic LLM client in `core/llm` (B2)
- the v0 turn graph (B3)
- the `nlu@v1` and `compose@v1` prompts (B4, B6)
- the `card_status` workflow with card selection and hint resolution in code (B5)
- `make chat-sandbox` with a debug line (B7)
- 3 scripted fake-LLM conversations in pytest (B8)

It serves every Dev B "Done when" line in D1 and end-of-day test steps 3 (the B tests pass in `make check`/CI), 4 (the four sandbox utterances) and 5 (one log line per LLM call with provider, model ID and prompt version).

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | `FakeBank` takes a data directory. Tests and B8 point it at a fabricated fixture committed in `backend/tests/fixtures/fakebank/`, marked TEST FIXTURE: invented rows in the raw CSV schema, invented IDs, no rows copied from `data/`. The sandbox points it at `data/` | Human Q1(a). R10 |
| D2 | **R5 gap, accepted on purpose.** D1 has no PII guard and no `mask_pii` node. Sandbox turns send the typed text to the Anthropic API unmasked. D5 (G6b) adds the vault check in `core/llm` and the R5 test. Until then, nobody types real-looking PII (full card numbers, documents, emails) into the sandbox. Card facts never reach the LLM as values (D10) | Human Q2(b) |
| D3 | `core/llm` owns an `LLMSettings` class (pydantic-settings) and logs through `structlog.get_logger()`. A1 configures structlog globally. At merge, A's settings nest or import `LLMSettings` | Human Q3(a) |
| D4 | Provider models come from `langchain_anthropic.ChatAnthropic` and `langchain_aws.ChatBedrockConverse`, used through `with_structured_output(schema, include_raw=True)`. Only `app/core/llm/` imports those packages (import-linter contract, `06` §2) | Human Q4(b), ADR-028 |
| D5 | Rules the card requires, placed on top of D4 inside the wrapper:<br>(a) **One retry on invalid output.** When `parsing_error` is set or `parsed` is `None`, the wrapper calls again once, adding the validation error to the messages. If the second output is also invalid, it raises `LLMInvalidOutput`.<br>(b) **R11 transport retries.** The chat model is built with `max_retries=2` and `timeout=20` (`01` §7). When they are exhausted, the provider exception is mapped to `LLMUnavailable`.<br>(c) **One log line per attempt**, emitted by the wrapper itself (not a LangChain callback).<br>(d) Callers get only our Pydantic object and never a LangChain type | Human Q4 note, B2 "Done when", R7, R11, end-of-day step 5 |
| D6 | Model registry: step → `{anthropic: model_id, bedrock: model_id}`. Haiku 4.5 is used for both `nlu` and `compose`, at temperature 0 for both. The Bedrock ID is filled in when K2 passes | Assumption 4 (stood), `07` §8, `02` §2 |
| D7 | The tracing hook is a no-op when `LANGFUSE_HOST` is unset. The log line is the call record today, and `audit.llm_calls` comes on D5 | ADR-006 amendment, assumption 8 |
| D8 | Graph v0 nodes:<br>• `load_session` → `understand` → `route`<br>• `route` goes to `card_info`, `unsupported` or `fallback`<br>• `card_info` goes to `compose`<br>The in-memory checkpointer is `MemorySaver`, keyed by a sandbox `conversation_id`. `mask_pii`, `grounding_check`, `unmask`, handoff, abstain and the intent queue are not built today (`02` §3 nodes arrive with their cards) | B3, assumption 1 |
| D9 | Wiring follows K3 D1/D2. The sandbox builds `ToolContext` from `CUSTOMER=<id>` as the session (`actor="customer"`, `policy_version="unversioned"`, a generated `trace_id`). It passes `configurable["session"]`, `configurable["bank_tools"]` (the bound FakeBank) and `configurable["llm"]` (the client, a scripted fake in tests). `load_session` binds `customer_id` and fills `country` from `get_profile()` | K3 D1/D2/D9, ADR-025, assumption 2 |
| D10 | `compose@v1` gets the reply language, the fact **keys** (inside a data fence, with no values) and the turn's goal. It writes a sentence that uses `{placeholders}`. Code fills every placeholder with values formatted in `domains/localization/`. An unknown placeholder, or a digit written by the LLM, gets the fallback template. The compose call binds no tools | B6, R4, R6 |
| D11 | Formatting in D1:<br>• country money formats from `02` §7, **without** the MXN estimate<br>• day-first dates<br>• `•••• 1234` masks<br>• localized status labels<br>Babel is used. The MXN estimate and the 3-country format tests are D2-B2 | Assumption 5, `02` §7 |
| D12 | `card_select` eligibility comes from `policies/card_select.yaml`: every status except `Closed`. Exactly one eligible card → it is used directly. Several → masked options, and `pending={flow:"card_info", node:"card_select", awaiting_slot:"card_hint"}`. A hint (`credit`, `debit`, `last4:NNNN`) is resolved in code over **all** cards, so a hint that matches only a Closed card resolves to it. A hint that is still ambiguous or matches nothing asks again with `clarification_failures += 1`. At 2 failures the turn gets the fallback template | Human Q5(a), `02` §4.1, R8, assumption 10 |
| D13 | `card_status` facts:<br>• credit: mask, status, expiry, credit limit, available credit<br>• debit: mask, status, expiry (ADR-020)<br>Customer-status precedence, balance and minimum payment are D2-B1 | `07` end-of-day step 4, ADR-020 |
| D14 | Routes with no handler yet get a fixed ES/PT template in code with no LLM call: `out_of_market`, `out_of_scope`, `injection_suspected`, and any intent other than `card_status`, including `greeting` when it stands alone. The debug line shows the route. D4 (G10) replaces the templates with structured abstain | Human Q6(a) |
| D15 | Fallback: `LLMUnavailable`, `LLMInvalidOutput`, `ToolUnavailable` or exhausted clarification → a fixed per-language template with no LLM call. The handoff half of R11 comes on D4 | R11, `01` §7, assumption 10 |
| D16 | Reply language = `nlu.language` when it is `es` or `pt`. `mixed` keeps the previous `state.language` (`es` on the first turn) | `02` §7 (a tie goes to the previous reply language); see Open questions |
| D17 | FakeBank reads raw, unshifted CSVs. It implements all 4 `BankReadTools` methods, and every SQL query filters by the bound `customer_id`. `search_transactions` returns at most 10 rows, newest first | Assumption 3, K3 contracts |
| D18 | The NLU smoke set is `eval/nlu/nlu_v1_smoke.yaml`: 20 labeled ES-MX/CO/AR, voseo, PT-BR and portuñol messages. The gate is 20/20 valid `NLUResult` plus correct labels on the 4 end-of-day utterances. It is not a CI test | Assumption 6, B4 |
| D19 | B's ~10 test customers go in `eval/personas.yaml` (IDs + traits only). The graph picture is `docs/diagrams/turn-graph-v0.mmd`, generated from the compiled graph | Assumptions 7, 9 |

### Amendments (planning and implementation)

| # | Decision | Why / trace |
|---|---|---|
| D20 | The dev machine has `uv` and GNU `make` installed. The Makefile targets and Success criteria commands assume both | Human, plan Q1 |
| D21 | The graph's I/O is local to the graph: `StateGraph(GraphState, input_schema=TurnInput, output_schema=TurnOutput)` (langgraph 1.2.12 parameter names), with `TurnInput{user_text}` and `TurnOutput{reply}`. `GraphState(TurnState)` adds `user_text` and `reply` as `NotRequired`. `TurnState` is untouched by this. D1 sends no chat history to the NLU. **Amends D8/D9 and the Contracts line "`TurnState` gets no new fields"** | Human, plan Q2 |
| D22 | The `facts` reducer appends, or resets when it receives the `RESET_FACTS` marker. `load_session` resets `facts`, `nlu` and `escalation_reason` on every turn, so compose sees only the current turn's facts. This changes the K3 reducer, so Dev A reviews it (Ask first). **Closes the `facts` open question** | Human, plan Q3. K3 open question |
| D23 | The header of `policies/card_select.yaml` follows `04` §5: `provenance: team-generated-synthetic`, plus a top-level `version: 1` | Human, plan Q4. R8 |
| D24 | Money uses the **account country's pattern** with the **record currency code**: MX `US$1,234.50`, CO `COP $1.234.567` / `USD $1.234,50`, AR `ARS $ 1.234,50` / `USD $ 1.234,50`. The MXN estimate stays D2-B2. **Refines D11** | Human, plan Q5. `02` §7 |
| D25 | No hint and zero eligible cards: `select_card` returns a `NoCards` outcome. `card_info` then sets `escalation_reason="no_cards"`, clears `pending` and resets `clarification_failures`. The graph routes to `fallback`, which replies with the fixed ES/PT `no_cards` template (no LLM). **Extends D12/D15** | Human, T6 |

**Implementation notes** (orchestrator review, no human decision needed):
- When clarification runs out (D12), `card_info` also clears `pending` and resets `clarification_failures` before the fallback.
- Facts whose value is `None` are left out of the list sent to compose.
- Compose fills placeholders with a regex, not `str.format`. A draft with stray braces is rejected and gets the fallback template (D10).
- FakeBank `get_card_details` queries by customer. To tell `AccessDenied` from `NotFound` it only checks whether a card with that id exists (by `product_type`) and reads no other field.
- The `card_options` fact has source `conversation.card_select`. `card_kind` is a fact for both credit and debit cards.

## Contracts

The K3 contracts are unchanged (`BankReadTools`, `ToolContext`, `NLUResult`, `TurnState`, errors). New today:

**`app/core/llm/`** (public surface, re-exported from `app/core/llm/__init__.py`)
```python
class LLMSettings(BaseSettings):
    llm_provider: Literal["anthropic", "bedrock"] = "anthropic"   # env LLM_PROVIDER
    anthropic_api_key: SecretStr | None = None                     # env ANTHROPIC_API_KEY
    aws_region: str | None = None; aws_profile: str | None = None
    langfuse_host: str | None = None                               # unset → tracing no-op
    timeout_s: float = 20.0; max_retries: int = 2

Step = Literal["nlu", "compose"]
MODEL_REGISTRY: dict[Step, dict[Provider, str]]                    # D6

@dataclass(frozen=True)
class PromptRef: name: str; version: int          # "nlu", 1  → logged as "nlu@v1"

class LLMClient(Protocol):
    async def structured(self, *, step: Step, prompt: PromptRef, system: str,
                         user: str, schema: type[T]) -> T: ...

def get_llm_client(settings: LLMSettings | None = None) -> LLMClient: ...

class LLMError(Exception): ...
class LLMUnavailable(LLMError): ...                # R11 transport retries exhausted
class LLMInvalidOutput(LLMError): ...              # still invalid after the one retry
```
Log event `llm.call`, one per attempt, with these fields: `provider`, `model_id`, `step`, `prompt_version` (`"nlu@v1"`), `temperature`, `attempt`, `outcome` (`ok|invalid|unavailable`), `latency_ms`, `trace_id`. Prompt or output text is **never** logged.

**`app/domains/conversation/`**
- `prompts/nlu@v1.md`, `prompts/compose@v1.md`. The version is logged through `PromptRef`.
- `compose` output schema: `ComposeDraft{text: str}` (`extra="forbid"`). `text` may contain only `{key}` placeholders from the turn's facts.
- `tools/fakebank.py`: `FakeBank(ctx: ToolContext, data_dir: Path)` satisfies `BankReadTools`. `make_fakebank_factory(data_dir) -> BankToolsFactory`.
- `graph.py`: `build_graph(checkpointer) -> CompiledGraph`. Each turn also yields a `DebugInfo{language, status, intents, slots, route, tools_called}` that the sandbox prints (`07` §1).
- `TurnState` gets no new fields. If one is needed, that's Ask first (below). *Amended by D21/D22:* the graph-local `GraphState(TurnState)` adds `user_text` and `reply` (`NotRequired`), with `TurnInput{user_text: str}` and `TurnOutput{reply: str}` as the graph's input and output schemas. The `facts` reducer honors `RESET_FACTS`.
- `flows/card_select.py`: `select_card(...)` also returns `NoCards` (D25).
- `templates.py` also holds the ES/PT `no_cards` fallback text (D25).

**`policies/card_select.yaml`**
```yaml
provenance: team-generated-synthetic   # 04 §5 shape, plus a top-level `version: 1` (planning Q4)
card_status:
  eligible_statuses: [Active, Blocked, Suspended]   # Closed excluded; hints still match Closed (D12)
```

## Touch map

```
backend/pyproject.toml, uv.lock        + langgraph, langchain-anthropic, langchain-aws, pydantic-settings,
                                         structlog, duckdb, pyyaml, babel; dev + import-linter
backend/.importlinter                  new (or extend A3's): only app.core.llm imports anthropic/langchain_anthropic/
                                         langchain_aws/boto3; conversation reaches bank data only via conversation.tools
backend/app/core/llm/                  new: __init__.py, settings.py, registry.py, client.py, errors.py, tracing.py
backend/app/domains/localization/      new: format.py (money, date, mask, status label; ES/PT)
backend/app/domains/conversation/
  graph.py, nodes/ (load_session, understand, route, unsupported, fallback, compose)
  flows/card_info.py, flows/card_select.py
  prompts/nlu@v1.md, prompts/compose@v1.md
  templates.py                         fixed ES/PT unsupported + fallback texts (D14, D15)
  tools/fakebank.py
  sandbox.py                           CLI: python -m app.domains.conversation.sandbox --customer <id>
policies/card_select.yaml              new
eval/personas.yaml                     new (~10 IDs + traits)
eval/nlu/nlu_v1_smoke.yaml             new (20 labeled messages); runner in backend/scripts/nlu_smoke.py
docs/diagrams/turn-graph-v0.mmd        new, generated
Makefile                               + chat-sandbox, nlu-smoke, graph-diagram (create it if A2's isn't merged yet)
.env.example                           + LLM_PROVIDER, ANTHROPIC_API_KEY, AWS_PROFILE, AWS_REGION, LANGFUSE_HOST
backend/tests/fixtures/fakebank/       new TEST FIXTURE: customers.csv, products.csv, transactions/…/*.csv
backend/tests/unit/…                   see Test list
```

## Test list

All tests use a fake LLM or a stubbed chat model. None of them touch the network or `data/`.

| Test | Proves |
|---|---|
| `test_r1_fakebank.py::test_each_customer_sees_only_own_cards` | B1, R1. For every fixture customer, `list_cards()` returns exactly that customer's cards (the ID set matches the fixture) |
| `test_r1_fakebank.py::test_foreign_ids_are_refused` | R1. Another customer's `card_id` gives `AccessDenied` from both `get_card_details` and `search_transactions(TxFilter(card_id=…))`. An unknown ID gives `NotFound` |
| `test_llm_client.py::test_invalid_output_retried_once` | B2, R11. A stub model that returns invalid then valid output → a validated object after exactly 2 calls. Invalid twice → `LLMInvalidOutput` |
| `test_llm_client.py::test_transport_failure_is_bounded_and_logged` | R11, R7, end-of-day step 5. The built chat model has `max_retries=2` and `timeout=20`. A provider exception becomes `LLMUnavailable`. Each attempt emits an `llm.call` with provider, model_id, prompt_version and temperature |
| `test_llm_client.py::test_provider_switch_is_local` | B2 "switching changes nothing outside `core/llm`". `LLM_PROVIDER=bedrock` builds a `ChatBedrockConverse` with the registry's Bedrock ID, behind the same `LLMClient` interface, with no network (lint-imports enforces the rest) |
| `test_compose.py::test_facts_fenced_placeholders_filled_in_code` | R4, R6:<br>• the compose prompt gets fact keys inside a data fence and no values<br>• no tools are bound<br>• code fills money, date and mask in the country format<br>• a draft with a raw digit or an unknown placeholder → fallback template |
| `test_card_select.py::test_eligibility_and_hints` | B5, D12:<br>• Closed cards are excluded from the options<br>• exactly one eligible card is used directly<br>• `credit` and `last4:NNNN` resolve<br>• a hint matching only a Closed card resolves to it<br>• 2 failed hints → fallback |
| `test_graph.py::test_graph_compiles_and_diagram_is_current` | B3. The graph compiles, and the committed `.mmd` equals `draw_mermaid()` |
| `test_sandbox_conversations.py::test_es_multi_card_asks_then_answers` | B8, B5, end-of-day step 4a (ES happy path). "hola, ¿cuál es el estado de mi tarjeta?" → masked options → "la de crédito" → status, expiry, limit and available credit in ES |
| `test_sandbox_conversations.py::test_pt_single_card_answers_in_pt` | B8, B6 (PT happy path). The PT question to a one-card customer → the answer comes directly, in PT |
| `test_sandbox_conversations.py::test_pix_routes_out_of_market` | B8, end-of-day step 4d. Debug `status=out_of_market` and `route=unsupported`, the reply is the ES template, and there is no compose call |

The B4 "20 → 20 valid" line and the B7 sandbox line are runnable proofs (see Success criteria), not tests. **There is no R5 test today** (D2).

## Boundaries

- **Always**
  - Filter every FakeBank query by the bound `customer_id`.
  - Format money, dates and masks in code.
  - Keep tool values out of LLM prompts except as fenced keys.
  - Log every LLM call through the wrapper.
  - Keep `langchain_*` imports inside `app/core/llm/`.
  - Mark fixture files TEST FIXTURE.
- **Ask first**
  - Adding a `TurnState` field or a `BankReadTools` method (Dev A reviews K3 contracts).
  - Changing `get_llm_client`'s surface.
  - Adding a runtime dependency beyond the touch map.
  - Building any node from `02` §3 that this spec leaves out.
- **Never**
  - Copy rows from `data/` into the repo, or commit `.env` or API keys.
  - Pass `customer_id` from NLU or chat text.
  - Let the LLM write money, dates or masks.
  - Build write tools, confirmation, handoff or structured abstain (D2/D4).
  - Touch `eval/scenarios/heldout/`.
  - Import an LLM SDK outside `core/llm`.

## Success criteria

1. `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports && uv run pytest -q` all pass. The 11 tests above are present and green, and the same commands are green in CI.
2. With `ANTHROPIC_API_KEY` set and `LLM_PROVIDER=anthropic`, `make nlu-smoke` prints `20/20 valid` and the 4 end-of-day utterances are labeled correctly (`card_status`, PT `card_status`, voseo `card_status`, `out_of_market`) (B2, B4).
3. `grep -rnE "langchain_anthropic|langchain_aws|import anthropic|boto3" backend/app --include=*.py | grep -v "app/core/llm/"` returns nothing.
4. `make chat-sandbox CUSTOMER=<multi-card persona from eval/personas.yaml>` reproduces end-of-day step 4:
   - ES which-card → "la de crédito" → status, expiry, limit and available credit
   - PT question → PT answer
   - voseo is understood
   - Pix → debug line `status=out_of_market`
   Every LLM call prints an `llm.call` line with provider, model ID and prompt version (step 5).
5. `docs/diagrams/turn-graph-v0.mmd` exists and matches the compiled graph (B3).
6. `eval/personas.yaml` lists ~10 customers covering multi-card, debit-only, blocked card and MX/CO/AR. `policies/card_select.yaml` has a `provenance` header.
7. `git ls-files data .env` is empty. Every file under `backend/tests/fixtures/fakebank/` starts with or sits next to a TEST FIXTURE marker.

## Open questions

| Question | Who decides |
|---|---|
| The Bedrock model ID for Haiku 4.5 (region, inference profile) | Dev A when K2 passes (`07` §8). Registry entry only |
| When `LLM_PROVIDER` defaults to `bedrock` | ADR-028: after K2, before D4 at the latest |
| ~~`facts` keeps accumulating across turns~~ **Closed by D22** (`RESET_FACTS` marker, reset in `load_session`). Dev A still has to review the K3 reducer change | Dev A review |
| The `02` §7 rule "`mixed` → the dominant language of the latest message" needs the NLU to say which language dominates. D1 uses the previous language (D16) | Dev B with `nlu@v2`, or a `02` amendment |
| The R5 gap (D2) closes with the vault guard | D5-A (G6b) |
