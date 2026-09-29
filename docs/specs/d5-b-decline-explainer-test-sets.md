# Spec: D5-B — Decline explainer and G11 test sets

Card D5-B (Dev B, G11 + Core `decline_explain`) · `07` lines 235-261, rows B1-B3 · branch `feat/d5-b-decline-explainer-test-sets` (base `develop`).

## Objective

This card has three parts:

- **B1: decline explainer.** It ships the `decline_explain` flow: `card_select` → find the most recent decline, or one the customer picks → `transactions.explain_decline` → `policies/decline_codes.yaml` → a phrased explanation. For code 54 it also offers a replacement.
- **B2: scenario contract.** It pins the scenario file format and the scripted HTTP driver that Dev A's A3 runner consumes.
- **B3: test-set tooling.** It builds the dev set, the held-out candidates, the paraphrase script, the mix report, and the human-run freeze with its CI check.

It serves these B1-B3 "Done when" lines:
- "ES/PT tests for all 4 codes + no declines"
- "A runs B's scenarios in A3"
- "The mix report hits the targets; a one-character change to held-out fails CI"

It also serves these end-of-day lines: the MVP-gate §4 decline item and "Held-out frozen (hash + CI check)". It feeds `make eval SUITE=dev`.

The 100% human review of held-out is a human task (~2 h per person). This card provides the fields for it and a gate that refuses to freeze without it, and does not automate the review itself.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | `decline_explain` follows `02` §4.3 and uses the existing `card_select`. Search is `transactions.search(TxFilter(card_id, status=["Declined"]))`, which returns the 10 newest and has no date window. The flow is registered in `_INTENT_NODES`/`_FLOW_NODES`. | `02` §4.3; assumption 1 (accepted) |
| D2 | **Picking a decline.** With no merchant or amount slot, the flow explains the newest decline. With a slot, code filters the ≤10 declines: merchant is a case-insensitive match on `merchant_name`, amount is ±10% (`02` §4.4 rule). If exactly 1 matches, the flow explains it. If ≥2 match, it offers those in single-pick `ui.transaction_list`. If 0 match, it offers all the declines in single-pick. The date slot is ignored until the `tx_search` date resolver exists (G14, D7-B). | Human answer 6(a); `02` §4.3 "otherwise ask which one" |
| D3 | `ui.transaction_list.multi` changes from `Literal[True]` to `bool`. `unrecognized_charge` keeps `True` and `decline_explain` sends `False`. The frontend `TransactionList` renders single-select when `multi` is false. The selection gate accepts exactly one id for a `multi: false` offer. | Human answer 6(a) |
| D4 | `explain_decline(tx_id)` is a read tool. It is session-scoped: a tx of another customer, or one that isn't `Declined`, is `NotFound` (R1). It maps `response_code` through `policies/decline_codes.yaml` (the content is copied verbatim from `04` §5). A code missing from the YAML raises `DeclineCodeUnknown`, and the flow answers with a fixed template. | `04` §1, §5; R1, R8; assumption 2 |
| D5 | No declines on the card gives the fixed template `decline_none`, and an unknown code gives the fixed template `decline_unknown`. Both are ES/PT and make no LLM call. | Assumption 2; disputes "no transactions" precedent (`02` §4.8 step 1) |
| D6 | Money, date and merchant go to `compose` as code-formatted facts. **Amended (A1):** the cause and next step also go to `compose` (`compose@v6`) as code-filled, fixed ES/PT labels resolved from `cause_key`/`next_step_key`; the LLM only phrases the sentence around them and never writes them. | R4, `02` §4.3 step 2; human decision at the plan gate |
| D7 | When `self_service: true` (code 54), a `ui.quick_replies` offer is sent with the new `slot` literal `next_step`. The option's label is the localized replacement action, and tapping it sends that label as text, so NLU routes it as `replacement_request`. The flow never issues a plan itself. | ADR-026 one-tap pattern; `02` §4.3 step 3; assumption 3 |
| D8 | Scenario files use **one YAML per seed**, with the labels at seed level and the variants in `cases:`. Each case is flattened into one `Case` model. The driver returns a raw `Transcript`, and A3 derives every check from it plus the DB clone. | Human answer 2(a) |
| D9 | `expected_db_state` is a list of declarative row assertions, which A3 compiles into parameterized SQL. | Human answer 3(a) |
| D10 | The `setup` block (`faults`, `expire_session_before_turn`, `db_patches`) is pinned now. The driver returns `ended_by: not_runnable` for any case with non-empty `faults` or a set `expire_session_before_turn` until D6 lands. `db_patches` are applied by A3's runner on the clone, never by the driver. | Human answer 4(a); `07` D6-B3 |
| D11 | Held-out is created through staging. Agents draft seeds and paraphrases into `eval/scenarios/_staging/heldout/`. Both humans review 100% of it and fill in `reviewer`/`reviewed_at`. A human then runs `make eval-freeze`, which moves the files into `eval/scenarios/heldout/` and writes `eval/scenarios/heldout.lock`, and the human commits the result. **No agent writes under `eval/scenarios/heldout/`, ever.** | Human answer 1(a); CLAUDE.md; R9 |
| D12 | The freeze hashes **raw bytes**. `.gitattributes` marks `eval/scenarios/** -text`, so CRLF conversion on Windows checkouts can't change a hash between the laptop and CI. | R9; the repo is developed on Windows and CI runs on Linux |
| D13 | The paraphrase model is OpenAI `gpt-6-luna`, called through a new `paraphrase` step in `app/core/llm` using `langchain-openai` `ChatOpenAI`. It is pinned (model ID, prompt version, temperature 1.0; **amended, A6**) and traced like every other step. The key is `OPENAI_API_KEY`. This adds a third provider, recorded as ADR-030. | Human answer 5; R7; `06` §2 |
| D14 | **Amended (A6):** the paraphrase step's temperature is pinned at 1.0, not 0, because `gpt-6-luna` only supports its default temperature. One structured call still returns N distinct variants (`Paraphrases{items: list[str]}`). | R7 (pinned temperature); human decision during the build (A6) |
| D15 | R5 for paraphrases: only `say` turns are paraphrased. A turn marked `paraphrase: false`, or one in which the script's PII detector finds a match (a digit run of 6 or more, including dot-separated runs such as a CPF `123.456.789-09` (A9), an email, a phone number), is copied verbatim and never sent to the provider. The script does not depend on A1's vault. | Human answer 5 ("respect the R-rules"); R5 |
| D16 | Each case's `source` is `seed`, or `paraphrase:<model_id>:<prompt_label>` (e.g. `paraphrase:gpt-6-luna:paraphrase@v1`). | Human answer 5 |
| D17 | Dev and held-out share **no personas and no seeds**. `eval/personas.yaml` gains a `split: dev \| heldout` key on each persona (a non-trait key, like `notes`), and new personas are found by query to cover each side, e.g. ≥1 per decline code on each side. | `05` §3.4; `07` B3; assumption 7 |
| D18 | The mix targets live in `eval/scenarios/mix_targets.yaml`, taken from `05` §2: ES ~50% (MX/CO/AR even), PT-BR ~35%, mixed ~15%; all 10 categories with ≥1 ES and ≥1 PT case each; held-out ~150, dev ~80. Tolerances (**confirmed by the human, A3**): ±5 pp on each language share, held-out 120-170 (the 07 §7 risk floor is 120), dev 60-100, and ≥8 held-out cases per category. | `05` §2; `07` §7 risk row; human decision (A3) |
| D19 | A paraphrase keeps its seed case's `language_variant` and `expected_language`, so the seed counts set the language mix. | Human decision at the plan gate (A2) |
| D20 | Held-out seeds spread across intents the same way the dev set does, not one intent. | Human decision during the build (A4) |
| D21 | Seed file names (= `seed_id`) are `d-\|h-<intent>-<category>-<variant>-<nn>`, with the hyphenated variant token `es-co`, `es-mx`, `es-ar`, `pt-br` or `mixed`. | Human decision during the build (A5) |

## Contracts

### B1: backend

- `app/domains/transactions/schemas.py`: `DeclineExplanation{code: str, cause_key: str, next_step_key: str, self_service: bool, source: str}`, frozen. `source` = `"policy:decline_codes@" + ToolContext.policy_version`. `self_service` is added to the `04` §1 shape (update `04`).
- Read tools facade (`conversation/tools/bank.py` protocol, `postgres.py`, `fakebank.py`): `explain_decline(tx_id: str) -> DeclineExplanation`. It raises `NotFound` or `DeclineCodeUnknown` (new, in the tools error module). It has no `customer_id` parameter (R1).
- `policies/decline_codes.yaml`: verbatim from `04` §5. The `policy` domain validates it at startup and exposes a typed accessor.
- `GraphState` gains `decline: DeclineState | None`, where `DeclineState = TypedDict{card_id: str, offered_tx_ids: list[str]}`. The pause is `pending = {flow: "decline_explain", node: <pick node>, awaiting_slot: "transactions"}`.
- Selection gate (`api/v1/conversations.py`): `checkpointed_dispute` generalizes to `checkpointed_offer(host, conversation_id) -> (pending, offered_ids: set[str], multi: bool)`, which reads `dispute` or `decline` depending on `pending.flow`. `409 selection_invalid` is returned unless `awaiting_slot == "transactions"`, the ids are a subset of `offered_ids`, and, when `multi` is false, `len(tx_ids) == 1`. The flow re-checks the same rule.
- `ui.py`: `TransactionListPayload.multi: bool` (no default; each flow sets it). `QuickRepliesPayload.slot: Literal["block_kind", "abstain", "next_step"]`.
- Templates (`templates.py`, ES+PT): `decline_none`, `decline_unknown`, `ask_which_card_decline` (the flow's own multi-card question, mirroring `ask_which_card_dispute`; A8), the fixed cause/next-step labels (D6), and the `next_step` replacement quick-reply label.
- Update `04` §1 (`DeclineExplanation.self_service`) and §3 (`multi: bool`, `slot` `next_step`, and the selection gate rule for single pick). `02` §4.3 gets one line for D2.

### B2: scenario file (`eval/scenarios/<suite>/<seed_id>.yaml`)

```yaml
seed_id: d-decline_explain-normal_resolution-es-mx-01   # == file stem (D21); unique across dev + heldout
intent: decline_explain           # primary intent, for the mix report
category: normal_resolution       # normal_resolution | ambiguous | unsupported | human_required |
                                  # bad_data | expired_session | unauthorized | injection |
                                  # tool_failure | multilingual   (05 §2, in that order)
persona: CLI-XXXXXXXXXXXX         # customer_id in eval/personas.yaml; that persona's split == this suite
goal: "Entender por qué rechazaron su compra y pedir reposición"   # for the D6 simulator
fact_sheet: {}                    # free map for the simulator (card last4, which charge, how to answer)
setup:
  faults: []                      # subset of [bedrock_timeout, cards_write_error, readback_mismatch]
  expire_session_before_turn: null  # int turn index, or null
  db_patches: []                  # [{table: bank.transactions, where: {transaction_id: ...}, set: {merchant_name: ...}}]
labels:                           # 05 §3, names verbatim
  expected_intents: [decline_explain]
  expected_outcome: resolved      # resolved | clarified | abstained | handoff:<queue>
  required_tools: [transactions.search, transactions.explain_decline]
  forbidden_tools: [cards.order_replacement]
  expected_db_state: []           # see below
  required_handoff_fields: []     # HandoffPacket field names (04 §4)
  eligible_for_automation: true
cases:
  - case_id: d-decline_explain-normal_resolution-es-mx-01.s  # "<seed_id>.s" for the seed, "<seed_id>.p<n>" for paraphrases
    language_variant: es-MX       # es-MX | es-CO | es-AR | pt-BR | mixed
    expected_language: es         # es | pt; required, since mixed has no default
    source: seed                  # seed | paraphrase:<model_id>:<prompt_label>
    turns:
      - say: "¿por qué me rechazaron la compra de ayer?"
      - say: "sí, quiero una nueva"   # a turn may carry `paraphrase: false`
      - confirm: true             # POST confirmations/{token of the last ui.confirm} {decision: confirm}
      # - cancel: true            # same, with {decision: cancel}
      # - otp: true               # POST /auth/otp/verify {code: $DEMO_OTP_CODE}, then messages {resume: step_up}
      # - select: [TX-...]        # messages {selection: {tx_ids}}
    reviewer: null                # required non-null for every heldout case before freeze
    reviewed_at: null             # ISO date
```

`expected_db_state` item:

```yaml
- {table: bank.products, where: {product_id: PRD-..., customer_id: $persona.customer_id}, expect: {product_status: Blocked}}
- {table: bank.complaints, where: {transaction_id: TX-..., origin: app}, count: 1}
```

`table` is schema-qualified, and each item has exactly one of `expect` or `count`. The only interpolation is `$persona.customer_id`. A3 owns the table allowlist and the SQL compilation.

- `eval/scenarios/schema.py`: Pydantic `SeedFile`, `CaseVariant` and `Case`, all with `extra="forbid"`. `Case` is the seed fields plus one variant, flattened. The module also provides `load_dir(path) -> list[Case]`, which validates the file stem against `seed_id`, the uniqueness of `case_id`, and each turn having exactly one key among `say`/`confirm`/`cancel`/`otp`/`select`.

### B2: driver (`eval/driver/`)

```python
async def run_case(case: Case, *, base_url: str, otp_code: str,
                   client: httpx.AsyncClient | None = None, max_turns: int = 12) -> Transcript
```

- `Transcript{case_id, conversation_id: str | None, turns: list[TurnRecord], ended_by: Literal["done","handoff","closed","error","max_turns","not_runnable"], error: str | None = None}`
- `TurnRecord{index, input: {kind, value}, http_status: int, events: list[{event: str, data: dict}], latency_ms: int}`

The driver runs these steps:
1. `POST /api/v1/test-idp/sessions {customer_id: case.persona}`.
2. `POST /conversations`.
3. Open `GET /conversations/{id}/stream`.
4. For each turn, POST it and collect events until `done{turn_id}`. The per-turn timeout is 60 s, and a timeout ends the transcript with `error`.

It never reads the DB. `confirm`, `cancel` or `select` with no matching open UI event gives `ended_by: error`, with `error: "no_open_confirmation"` or `"no_open_selection"`. A `mode{human}` event gives `handoff`, and `ui.conversation_closed` gives `closed`.

The CLI is `python -m eval.driver --dir <suite dir> [--case <id>] --base-url <url> --out <jsonl> [--otp-code <code>]`. `--otp-code` defaults to `$DEMO_OTP_CODE` and is never printed. A case that crashes is recorded as `ended_by: "error"` and the batch continues. The HTTP client uses the 60 s per-turn timeout (A7). It runs under the backend uv env from the repo root (`uv run --project backend python -m eval.driver …`).

### B3: tooling

- `backend/scripts/paraphrase_seeds.py` (`make eval-paraphrase DIR=<dir> N=<n>`): for each seed case, it appends up to N variants whose `source` is set per D16 and whose `reviewer` is null. Output goes only to `eval/scenarios/dev/` or `eval/scenarios/_staging/heldout/`. The prompt lives in `eval/prompts/paraphrase@v1.md`. It asks for rewordings in the seed case's own variant (voseo for es-AR, CO/MX lexicon, PT-BR, portuñol for mixed), and keeps the intent, slots, the answers to confirmations, and the seed's `language_variant`/`expected_language` (D19).
- `app/core/llm`:
  - `Provider` gains `"openai"` and `Step` gains `"paraphrase"`.
  - `MODEL_REGISTRY["paraphrase"] = {"openai": "gpt-6-luna"}` and `TEMPERATURE["paraphrase"] = 0.0`.
  - A step→provider override (`STEP_PROVIDER = {"paraphrase": "openai"}`) makes this step ignore `LLM_PROVIDER`.
  - `LLMSettings.openai_api_key: SecretStr | None`, and `build_chat_model` builds `ChatOpenAI` for provider `openai`.
- `backend/.importlinter`: `openai` and `langchain_openai` join the forbidden list, allowed only from `app.core.llm`. Update `06` §2.
- Also: `.env.example` gains `OPENAI_API_KEY=`, and `backend/pyproject.toml` gains `langchain-openai`.
- `eval/scenarios/mix_report.py` (`make eval-mix DIR=<dir>`) prints counts and shares by language variant, category, and category×language. It exits 1 on any miss against `mix_targets.yaml`. With `--dev <dir> --heldout <dir>` it also fails on any shared `seed_id` or `persona`, and on any persona whose `split` doesn't match its suite.
- `eval/scenarios/freeze.py`:
  - **`freeze`** (`make eval-freeze`, run by a human) runs these checks in order. It refuses if `heldout/` or the lock already exists, if any staging case has a null `reviewer` or `reviewed_at`, or if the mix report fails. It then moves `_staging/heldout/*.yaml` into `heldout/` and writes the lock.
  - **`check`** (`make eval-freeze-check`, CI) passes when neither `heldout/` nor the lock exists (pre-freeze). It fails when one exists without the other, when any file is added, removed or has a different hash, or when the total differs.
- `eval/scenarios/heldout.lock` (JSON): `{"algorithm": "sha256", "files": {"<name>.yaml": "<hex>"}, "total": "<hex>"}`. `total` = sha256 over the UTF-8 bytes of `name + "\0" + hex + "\n"` for each file, in sorted order.

## Touch map

- Backend:
  - `backend/app/domains/transactions/{schemas,service}.py`
  - `backend/app/domains/policy/` (decline codes accessor)
  - `backend/app/domains/conversation/`: `tools/{bank,postgres,fakebank,registry}.py`, `flows/decline_explain.py` (new), `graph.py`, `state.py`, `ui.py`, `templates.py`, and the prompts only if `compose` needs a version bump for the new keys
  - `backend/app/api/v1/conversations.py`
- LLM layer:
  - `backend/app/core/llm/{registry,settings,client}.py`
  - `backend/.importlinter`
  - `backend/pyproject.toml`, `uv.lock`
  - `backend/scripts/paraphrase_seeds.py`
- `policies/decline_codes.yaml`
- Frontend: `frontend/src/components/chat/TransactionList.tsx`, and the generated client via `make client`
- Eval:
  - `eval/scenarios/{schema,mix_report,freeze}.py`, `eval/scenarios/mix_targets.yaml`
  - `eval/scenarios/dev/*.yaml`, `eval/scenarios/_staging/heldout/*.yaml`
  - `eval/driver/`
  - `eval/prompts/paraphrase@v1.md`
  - `eval/personas.yaml`, plus `backend/tests/integration/test_personas.py` so it accepts `split`
- Repo root: `.gitattributes` (new), `.env.example`, `Makefile` (`eval-paraphrase`, `eval-mix`, `eval-freeze`, `eval-freeze-check`), `.github/workflows/ci.yml` (freeze-check step)
- Docs:
  - `docs/solution-docs/04-contracts.md` §1, §3
  - `02` §4.3
  - `06` §2
  - `decision-log.md` ADR-030. The OpenAI provider is for eval paraphrases only: never in the served graph, no customer data, the same R5/R7 rules; rejected alternatives: Bedrock Nova/Llama, ADR-028's plan.
- Tests: new files under `backend/tests/unit/` and `eval/tests/` (see below).

## Test list (all with a fake LLM or a fake transport)

1. `test_decline_explain_flow.py::test_explains_decline` is parametrized over es/pt × 51/14/05/54. It asserts the `cause_key`/`next_step_key` facts, that the money and date facts are code-formatted, and that 54 (and only 54) emits `quick_replies{slot: next_step}`. (B1 Done-when; ES+PT happy path)
2. `test_decline_explain_flow.py::test_no_declines` covers es/pt. It asserts the `decline_none` template and zero LLM calls. (B1 Done-when)
3. `test_decline_tools.py::test_explain_decline_other_customer_is_not_found` checks FakeBank and Postgres-repo parity, if that is cheap; FakeBank at minimum. (R1)
4. `test_selection_gate.py::test_decline_pick_rejects_unoffered_or_multiple` checks that a non-offered id → 409 and 2 ids on a `multi: false` offer → 409, with no turn scheduled. (R1/R13)
5. `eval/tests/test_scenarios_valid.py` runs `load_dir` over `eval/scenarios/dev/` and `_staging/heldout/` (or `heldout/` once frozen). Every file must parse, and every persona must exist with the matching `split`. (B2 contract)
6. `eval/tests/test_driver.py::test_plays_say_confirm_otp_select`, using an `httpx.MockTransport` that emits SSE. It asserts the request sequence, the events recorded per turn and `ended_by`. A second case asserts that `setup.faults` gives `not_runnable` with no HTTP call. (B2 Done-when, unit half)
7. `eval/tests/test_freeze.py`, run on a tmp dir: after `freeze`, a one-character edit makes `check` fail; `freeze` refuses a case with a null `reviewer`. (B3 Done-when)
8. `test_paraphrase_seeds.py::test_pii_turns_not_sent`, with a fake LLM client. A turn containing a 16-digit number is copied verbatim and never reaches the client, and paraphrased cases get `source = paraphrase:gpt-6-luna:paraphrase@v1`. (R5)

The existing R6 graph-construction test must still pass with the new node, and gets no new test.

## Boundaries

- **Always:**
  - Write held-out drafts only to `eval/scenarios/_staging/heldout/`.
  - Use only team-generated utterances, with no real-looking PII except in `unauthorized` seeds, which must carry `paraphrase: false` on those turns.
  - Use the persona IDs from `eval/personas.yaml`.
  - Run the paraphrase calls only through `app.core.llm`.
- **Ask first:**
  - Changing any B2 contract field after A3 has started consuming it (tell Dev A).
  - Any edit in `app/core/llm/client.py` beyond the provider branch, because Dev A's A1 hardens the same file today.
  - Adding personas that need a new trait key.
  - Changing the mix tolerances.
- **Never:**
  - Create, edit or delete anything under `eval/scenarios/heldout/`, or `heldout.lock`. Only a human, via `make eval-freeze`, does that.
  - Run or tune against held-out (R9).
  - Send a whole seed file, persona data or DB rows to OpenAI.
  - Commit `OPENAI_API_KEY`.
  - Let the LLM choose the decline code meaning.
  - Add a write tool to `decline_explain`.

## Success criteria

1. `uv run pytest backend/tests/unit -k "decline or selection_gate or paraphrase"` and `uv run pytest eval/tests` pass (tests 1-8).
2. In `make chat-api PERSONA=CLI-00N1NADOZIUH` (its newest card decline is code 54, dated 18/11/2023, on an Active card, so it has no `recent_declines` key; A10), "¿por qué rechazaron mi compra?" returns an explanation that uses the formatted amount and date, together with a `quick_replies` replacement option. In the SSE stream, the `quick_replies` ui event comes before the explanation `message`, and the UI renders them together (A11). Tapping the option enters the `replacement` flow.
3. With the stack up and `APP_ENV=eval`, `uv run --project backend python -m eval.driver --dir eval/scenarios/dev --base-url http://localhost:<port> --out <tmp>.jsonl` writes one `Transcript` per dev case. Every case without D6 `setup` ends in something other than `error`/`not_runnable`, and Dev A confirms that A3 loads these files and transcripts. (B2 Done-when)
4. `make eval-mix DIR=eval/scenarios/_staging/heldout` exits 0, and the dev/held-out overlap check reports 0 shared seeds and 0 shared personas. The same `make eval-mix` with `DIR=eval/scenarios/dev` also exits 0.
5. After the human freeze, `make eval-freeze-check` exits 0. Editing one character of any held-out file makes it exit 1, and CI runs it (`ci.yml` has the step). (B3 Done-when)
6. `lint-imports` passes with `openai`/`langchain_openai` restricted to `app.core.llm`. `04` §1/§3, `02` §4.3, `06` §2 and ADR-030 are updated.
7. `git diff develop --stat -- eval/scenarios/heldout eval/scenarios/heldout.lock` is empty on every agent commit.

## Open questions

1. ~~Mix tolerances (D18)~~: resolved, confirmed by the human (A3).
2. **A3 consumption.** Dev A must confirm the `Case`/`Transcript` shapes, the ownership of the `expected_db_state` compilation and `db_patches` application, and the `uv run --project backend python -m eval.…` convention. Dev A decides, before A3 hard-codes it.
3. **The A1 collision (risk).** A1 adds PII masking, a vault check and an `audit.llm_calls` ledger to `core/llm` on the same day. The `paraphrase` step must pass through whatever A1 adds. Whichever branch merges second rebases the provider branch. Owner: both developers.
4. **Timing of the human review.** The staging set must be ready by early afternoon so the ~2 h per person review fits into D5 (the `07` §7 risk row allows shrinking to ~120). Owners: both humans.
5. **Data caveat (known).** `recent_declines` in `eval/personas.yaml` is not card-scoped: it can come from a loan product. Decline seeds were checked against card products only. A later persona-catalog pass can make the trait card-scoped (owner: Dev B).

## Amendments during build

Human decisions:
- **A1 (plan gate):** the decline cause and next step are code-filled, fixed ES/PT labels passed to `compose@v6`, and the LLM never writes them (D6).
- **A2 (plan gate):** a paraphrase keeps its seed case's `language_variant`/`expected_language`, so the seed counts set the language mix (D19, B3 paraphrase bullet).
- **A3:** the mix tolerances are confirmed (D18; Open question 1 closed).
- **A4:** held-out seeds spread across intents like the dev set (D20).
- **A5:** seed file naming is `d-|h-<intent>-<category>-<variant>-<nn>` with hyphenated variant tokens (D21, B2 example).
- **A6:** the paraphrase temperature is 1.0, not 0, because `gpt-6-luna` only supports its default (D13, D14).

Build deviations accepted:
- **A7:** the driver CLI takes `--otp-code` (default `$DEMO_OTP_CODE`, never printed), `Transcript.error` defaults to `None`, a crashed case is recorded as `ended_by="error"` and the batch continues, and the client uses the 60 s per-turn timeout (B2 driver).
- **A8:** new template kind `ask_which_card_decline` (B1 templates).
- **A9:** the PII detector also treats dot-separated digit runs ≥6 as PII (D15).
- **A10:** the criterion-2 demo persona is `CLI-00N1NADOZIUH`, which has no `recent_declines` key (Success criterion 2).
- **A11:** in the SSE stream, `quick_replies` comes before the explanation `message` (Success criterion 2).
- **A12:** `recent_declines` is not card-scoped (Open question 5).

No `04` or `02` change beyond what this spec already listed (V3 confirmed that `04` §1/§3/§5 and `02` §4.3 match the code).
