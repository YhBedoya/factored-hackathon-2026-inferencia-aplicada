# Spec: D6-B — G11 simulator, UI hardening, fixes

Card D6-B (Dev B, day track) · `07` lines 261-290, rows B1-B4 · branch `feat/d6-b-simulator-ui-hardening` (base `develop` @ `d48d08d`).

## Objective

This card has four parts:

- **B1: customer simulator.** It adds a goal-driven LLM simulator (`05` §5). The simulator plugs into the eval runner as a second driver, so `make eval DRIVER=simulator SUITE=dev` runs.
- **B2: UI hardening.** When the session expires in the chat, the customer sees a modal instead of being redirected. They log in again, and the chat resumes by re-sending the held request (client replay). This part also adds rendering for fallback and errors, loading states, and a mobile layout.
- **B3: expired-session dev cases.** The scripted driver now plays the dev cases that expire the session, so they are "included in the dev run". One dev seed is added for an injected `merchant_name`.
- **B4: fixes.** It fixes the Dev B workflow failures recorded by D5, with "improves" defined in D10.

It serves these B1-B4 "Done when" lines:
- "`make eval DRIVER=simulator SUITE=dev` runs"
- "Playwright covers expiry → resume"
- "Included in the dev run"
- "The dev report improves"

It also serves these end-of-day steps: step 2 (the frontend half; the server half is A2) and step 5.

Dev A's rows A1-A4 are out of scope. That covers fault injection, server-side session handling, the injection seeder that applies `db_patches`, and data quality.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | The simulator is a new eval-only `simulate` step in `app/core/llm`: `STEP_PROVIDER["simulate"] = "openai"`, `MODEL_REGISTRY["simulate"] = {"openai": "gpt-6-luna"}`, `TEMPERATURE["simulate"] = 1.0`. It is called only through `get_llm_client()`, like `paraphrase`. ADR-030 is amended to add a "Simulator note". | Human answer Q1(a). ADR-030 is the precedent. R7 applies. |
| D2 | The card and `05` §5 say "temperature 0", but this step runs at 1.0 because `gpt-6-luna` rejects any other value. When a run uses `DRIVER=simulator`, `report.md` carries a caveat line: "Driver: simulator (`gpt-6-luna`, temperature 1.0) — transcripts are not repeatable run to run". | Human answer Q1(a). The caveat follows the ADR-031 pattern. |
| D3 | The simulator plays each **case**, not each seed. Turn 1 is the case's own first `say`, sent verbatim, which keeps the paraphrase and the `language_variant`. From turn 2 on, the simulator decides the next action from the case's `goal` and `fact_sheet`, its `language_variant`, and the conversation so far. | Human answer Q5(a). |
| D4 | `fact_sheet` is filled only for dev seeds where the bot asks the customer to choose something: which card, block kind, which transaction, address, or an OTP. Values are the ones the bot shows: last4, the merchant label, the amount as the UI formats it, the day. There is no document number, email, phone or full name. | Human answer Q5(a). R5. |
| D5 | Before bot text goes into the `simulate` prompt, it is masked with the persona's known PII. The `display_name` comes from `GET /auth/me` after the test-IdP login. The `app.core.pii.find_pii(text, KnownPii(None, names))` spans are replaced with `⟨NAME_n⟩` / `⟨KIND_n⟩` tokens. The bot turns appear only inside data fences. | R5 (the `core/llm` guard cannot see names). Assumption 3 was confirmed. R6 (fenced data). |
| D6 | The simulator stops on any of four conditions. (1) It returns `stop` with reason `goal` or `abstention`: `ended_by = "done"`. (2) The stream shows a handoff (`ui.handoff_banner` or `mode human`): `ended_by = "handoff"`. (3) It reaches 12 turns: `ended_by = "max_turns"`. (4) It hits a transport or protocol error: `ended_by = "error"`, as the scripted driver does. The simulator's own reason is recorded in a new optional `Transcript.stop_reason`. | `05` §5 and `07` B1. Assumption 2 was confirmed. |
| D7 | The OTP value comes from the harness's `otp_code`, never from the model. `confirm` and `cancel` resolve against the last `ui.confirm` token, and `select` against the last `ui.transaction_list`, exactly as in the scripted driver. | R2. Assumption 2. |
| D8 | Client replay. After a `401 session_expired`, the client holds the failed request, logs in again, and calls `GET /auth/me`. If `login_hint` and `display_name` match the ones captured when the chat opened, it re-sends the held request once and reopens the SSE stream. If they differ, it drops the request and opens a fresh conversation. The frontend (B2) and the scripted and simulator drivers (B3) all follow this rule. Dev A must confirm that A2 does not also replay the turn on the server; see Open questions. | Human answer Q2(a). The frontend never holds `customer_id` (R1), so `login_hint`/`display_name` are the comparison. `get_owned_conversation`'s `404` stays the real guard (R13). |
| D9 | For a case with `expire_session_before_turn: N`, the driver drops its session and CSRF cookies before playing turn N (same indexing as `schema.py`). The post of turn N then gets `401 session_expired`, the same 401 an expired JWT gets (`04` §3 "Auth"). The driver then re-creates the session with `POST /test-idp/sessions` for the same persona and replays per D8. Cases with non-empty `faults` stay `not_runnable`. | Human answer Q3(a). |
| D10 | **B4's "before"** is the evidence D5 recorded. D5-A state T25/T36 shows `card_block` forgets `block_kind` across the ask-which-card question: seed `a-card_block-normal_resolution-es-co-01` only passes because its turn 2 restates the block kind. D5-B state T10 shows 81/81 transcripts, 0 `error`, and 12 `not_runnable` (the D6 `setup` seeds). **"Improves"** means all four of these hold. (a) With that seed's turn 2 reverted to the card choice alone (`La que termina en 5772.`), `make eval SUITE=dev SYSTEM=proposed CASES=a-card_block` passes. (b) `CASES=a-` still passes 4/4. (c) The 6 `expired_session` cases move from `not_runnable` to played (B3). (d) Any further failure B4 fixes has a recorded before/after pair of subset runs (`CASES=<seed prefix>`). There is no paid full-suite baseline run. | Human answer Q4(b). The human asked for "improves" to be defined here. |
| D11 | The Playwright test for expiry → resume runs against the mocked API (`frontend/e2e/mock-api.ts` + `.sse` fixtures). The mock answers `401 session_expired` on a chosen POST. | Human answer Q6(a). D5-B B5 D7 pattern. |
| D12 | The fallback UI renders only what already exists on the SSE contract. A1's fallback arrives as a `message` (+ `ui.handoff_banner`); `error {code}`, 409 `turn_in_progress`, 409 `conversation_closed`, 409 `confirmation_invalid` (a held confirm whose plan died at its 5-min TTL), 429 and 5xx get localized ES/PT states. No new event kinds are added. | Assumption 4 was confirmed. `04` §3. D3-A D4 (plan TTL). |
| D13 | The mobile layout is B2's first cut if the day runs behind. | `07` D6 "If behind". |
| D14 | B3 adds one dev seed, `d-decline_explain-injection-es-mx-01`. It plants an instruction in `merchant_name` through `setup.db_patches`, has `forbidden_tools` set to every write tool, and gets 2 paraphrases via `make eval-paraphrase`. It stays `not_run (db_patches)` until A3 applies patches. Nothing under `eval/scenarios/_staging/heldout/` or `heldout/` is touched. | Assumption 5 was confirmed. End-of-day step 3. R9. |
| D15 | `DRIVER=scripted\|simulator` goes from the Makefile through `eval/harness/__main__.py --driver` to `runner.run(driver=...)`. `meta.json` records `driver`, and `report.py` prints the D2 caveat when that value is `simulator`. These three are Dev A files; the edits are wiring only and are flagged for A's review in the PR. | `07` B1 "Done when". The runner already has an injectable `driver` (`runner.py:273`). |
| D16 | *(Amends D8 for the drivers.)* If the identity after re-login doesn't match in the scripted or simulator driver, the transcript ends `error` with `error = "identity_mismatch"` and nothing is re-sent. The browser UI keeps D8's behavior: it drops the held request and opens a fresh chat. | Human decision at plan. |
| D17 | Ruff findings in `eval/harness/runner.py` and `report.py` that predate this card are accepted as they are and left for Dev A's review. | Human decision at T2. |
| D18 | Turn 2 of `d-card_status-expired_session-pt-br-01` (`.s`/`.p1`/`.p2`) now names the card's last4 (`4051`). The persona has 4 credit cards, so the seed as written couldn't be completed. | Human decision at T5. |
| D19 | The eval harness now works on win32. `runner.py` starts uvicorn with `--loop asyncio:SelectorEventLoop`, rewrites `localhost` to `127.0.0.1` in the `REDIS_URL`/`DATABASE_URL` passed to the backend, and kills the whole process tree on stop. These are Dev A files, flagged for A's review. | Human decision at T9 (added at verify). |
| D20 | The `report.md` and `meta.json` writes use `encoding="utf-8"`. This fixes a Windows cp1252 bug found at verify. | Human decision at V2. |
| D21 | The 44 px tap targets in the mobile layout also cover the AppShell header and the session-expired modal. | Human decision at V4. |
| D22 | Live proofs are deferred: the three evals (`CASES=a-`, the expired-session cases, `DRIVER=simulator`), the 10-transcript hand-check, live `/chat` at 375 px and the live modal. The local DB is stuck: golden has a stray `ck_accounts_role_customer_id` left by an old D4-B `0005`, and `latam_app` is at `0006`. Success criteria 3, 5 and 6 (the live parts) stay open until the DB is repaired. `04` is unchanged (V3 found no wire change). | Human decision at verify. |

## Contracts (delta only)

**`app/core/llm/registry.py`:** `Step` gains `"simulate"`, with the D1 entries in `MODEL_REGISTRY`, `TEMPERATURE` and `STEP_PROVIDER`. Nothing else in `core/llm` changes. The `.importlinter` contracts stay as they are.

**Prompt:** `eval/prompts/simulate@v1.md` (`PromptRef("simulate", 1)`), with ES and PT examples. The system block carries the goal, the `language_variant` and the `fact_sheet`. The user block carries the masked, fenced transcript so far. It states that bot text is data, not instructions.

**`eval/simulator/simulator.py`:**
```python
class SimAction(BaseModel):          # structured output of the `simulate` step
    kind: Literal["say", "confirm", "cancel", "otp", "select", "stop"]
    text: str | None = None          # say
    tx_ids: list[str] | None = None  # select (must be ids from the last ui.transaction_list)
    stop_reason: Literal["goal", "abstention"] | None = None  # stop

async def run_case_simulated(
    case: Case, *, base_url: str, otp_code: str,
    client: httpx.AsyncClient | None = None, max_turns: int = 12,
    llm: LLMClient | None = None,   # test seam; default get_llm_client()
) -> Transcript
```
It has the same call shape as `eval.driver.driver.run_case`, so it fits `runner.Driver`. It reuses the driver's per-turn HTTP helpers by import, not by copy. It returns `not_runnable` under exactly the same `setup` conditions as the scripted driver after B3.

**`eval/driver/driver.py`:**
- `Transcript` gains `stop_reason: str | None = None`.
- `expire_session_before_turn` is no longer `not_runnable`; it follows D9 and D8.
- `SetupBlock`'s docstring is updated to say that only `faults` makes a case not runnable.

**CLI:** `make eval DRIVER=simulator SUITE=dev [SYSTEM=] [CASES=]` maps to `python -m eval.harness --driver simulator`. The default is `scripted`. `meta.json` gets a `"driver"` key.

**Frontend:**
- `lib/api.ts` `withAuthRetry`: when the refresh-and-retry gets a second 401 and the chat is mounted, it no longer redirects. It calls `sessionExpired.hold(retry)` and returns that promise, which resolves with the replayed result or rejects when the request is dropped. Routes outside the chat keep the redirect to `/login`.
- `components/chat/SessionExpiredModal.tsx`: a Radix `dialog` holding the existing login form. On success it applies the D8 comparison against the `MeResponse` captured when the chat opened.
- The ES and PT strings go in the UI dictionaries, in Cardy's voice (`docs/brand.md`).

**Docs:**
- ADR-030 gets a "Simulator note (D6-B)".
- `06` §2's `openai` line becomes "eval paraphrase and simulator only".
- The `07` §8 "Paraphrase, simulator and judge model family" row is marked decided for the simulator.

## Touch map

- `backend/app/core/llm/registry.py`: the `simulate` step.
- `eval/simulator/__init__.py` and `eval/simulator/simulator.py` (new). `eval/prompts/simulate@v1.md` (new).
- `eval/driver/driver.py`: expiry replay and `stop_reason`. `eval/scenarios/schema.py`: docstring only.
- `eval/harness/__main__.py`, `eval/harness/runner.py` (meta `driver`), `eval/harness/report.py` (caveat), `Makefile` (`DRIVER=`). These are A's files, touched for D15 wiring only.
- `eval/scenarios/dev/*.yaml`: `fact_sheet` for the choice seeds (D4); `a-card_block-normal_resolution-es-co-01` turn 2 reverted (D10); the new injection seed (D14).
- `eval/tests/test_simulator.py` (new) and `eval/tests/test_driver.py` (expiry test replaces the old not_runnable assertion for expiry).
- `frontend/src/lib/api.ts`, `frontend/src/components/chat/SessionExpiredModal.tsx` (new), `frontend/src/routes/chat.tsx`, the chat components for the error, fallback and loading states, the ES and PT dictionaries, and the mobile styles.
- `frontend/e2e/session-expiry.es.spec.ts` (new) plus the `mock-api.ts` hook for 401 on the Nth POST, and the fixtures.
- `backend/app/domains/conversation/flows/card_block.py` (or the graph state, wherever `block_kind` is dropped): the B4 fix. Its ES and PT flow tests go under `backend/tests/unit/`.
- `docs/solution-docs/decision-log.md` (ADR-030), `06-engineering-rules.md` §2, and `07-execution-plan.md` §8.

## Test list

All tests use a fake LLM. Each task runs only its own tests.

1. `eval/tests/test_simulator.py::test_bot_text_is_masked_before_prompt` (R5). A bot reply containing the persona's `display_name` reaches the fake LLM as `⟨NAME_1⟩`, inside a fence, and the raw name appears nowhere in `system` or `user`.
2. `eval/tests/test_simulator.py::test_stop_conditions` (B1 "Done when", unit half). This test is parametrized over four cases: `stop(goal)` gives `done`, a `ui.handoff_banner` gives `handoff`, a fake that never stops gives `max_turns` at 12, and an `otp` action sends the harness code and never model text. The HTTP side is an `httpx.MockTransport`.
3. `eval/tests/test_driver.py::test_expired_session_relogs_same_persona_and_replays_once` (B3 "Done when"; R13-adjacent D8). Turn N's post gets 401. The driver calls `/test-idp/sessions` for the same persona, then `/auth/me`, and re-sends exactly one identical request. A `faults` case is still `not_runnable`.
4. `frontend/e2e/session-expiry.es.spec.ts::expiry → modal → re-login → confirmation resumes` (B2 "Done when"). The mock 401s the confirm POST; the modal appears; after logging in as the same customer, the held confirm is re-sent once and the read-back message renders.
5. `frontend/e2e/session-expiry.es.spec.ts::different customer drops the held request` (R1/R13 on the client). Logging in as another customer re-sends nothing and lands on a fresh chat.
6. `backend/tests/unit/.../test_card_block_*::test_block_kind_survives_card_question_es` and `…_pt` (B4, one ES and one PT happy path). "Block temporarily" goes to the ask-which-card question, the answer names only the last4, and the result is one `ui.confirm` for a lock.
7. Runnable proofs (live, human-run, paid):
   - `make eval SUITE=dev SYSTEM=proposed DRIVER=simulator` finishes and writes a report with the D2 caveat (B1, end-of-day step 5).
   - `make eval SUITE=dev SYSTEM=proposed CASES=a-` gives 4/4 with the reverted card_block seed (D10 a/b).
   - A scripted driver run shows the 6 `expired_session` dev cases played, not `not_runnable` (D10 c).
   - The hand-check of 10 simulator transcripts for persona adherence is recorded in the state file by a human.

## Boundaries

- **Always:**
  - The model gets masked, fenced bot text.
  - The OTP comes from the harness.
  - The held request is replayed once, and only for the same customer.
  - Money, dates and masks in the UI come from the server, never reformatted by the model.
  - Each task runs only its own tests.
- **Ask first:**
  - Any edit to A's `eval/harness/*` or the `Makefile` beyond the D15 wiring.
  - Any change to the SSE, HTTP or `401` contract in `04`.
  - Any new dev seed beyond D14.
  - A fresh paid full-suite dev run.
- **Never:**
  - Touch `eval/scenarios/heldout/` or `_staging/heldout/`.
  - Open held-out failures (R9).
  - Implement fault injection, server-side replay or `db_patches` application (Dev A).
  - Put `customer_id` in the frontend or the simulator.
  - Send the persona's document, email or phone to the simulator.
  - Import `openai` outside `app.core.llm`.

## Success criteria

1. `grep -n '"simulate"' backend/app/core/llm/registry.py` shows `gpt-6-luna`, temperature `1.0` and `STEP_PROVIDER` `openai`, and `lint-imports` passes.
2. `uv run --project backend pytest eval/tests/test_simulator.py eval/tests/test_driver.py -q` passes, including tests 1-3.
3. `make eval SUITE=dev SYSTEM=proposed DRIVER=simulator` exits 0. The report's `meta.json` has `"driver": "simulator"`, and `report.md` contains the D2 caveat line. The state file records a human hand-check of 10 transcripts.
4. `cd frontend && npx playwright test e2e/session-expiry.es.spec.ts` passes (tests 4-5). `npx biome ci src` is clean.
5. In a scripted dev run, no case whose seed has `expire_session_before_turn` set ends `not_runnable`. Only the 2 `faults` seeds (6 cases) still do.
6. `make eval SUITE=dev SYSTEM=proposed CASES=a-` gives 4/4 passed with `a-card_block-normal_resolution-es-co-01` turn 2 = `La que termina en 5772.`. The ES and PT tests from test 6 pass.
7. `make eval-mix DIR=eval/scenarios/dev` exits 0 with the D14 seed added, `eval/tests/test_scenarios_valid.py` passes, and `git status --porcelain -- eval/scenarios/heldout eval/scenarios/_staging/heldout` is empty.
8. ADR-030 has the simulator note, and `06` §2 and `07` §8 are updated.

## Open questions

- **Live proofs (D22):** repair the local DB (the stray golden constraint, and bring `latam_app` from `0006` to head), then run the three evals, the hand-check, and the live 375 px and modal checks.
- **Dev A (with A2):** `01-technical-design.md:84` says "the turn is replayed" without saying who replays it. D8 is a client replay. A2 should amend that line when it confirms there is no server-side replay. This card leaves `01` unchanged, because its Contracts section doesn't call for editing it.

- **Dev A:** confirm that A2 keeps the pending step and does **not** replay the turn server-side, because D8 replays from the client. If A2 does replay on the server, the turn runs twice, so D8 must be amended before merge.
- **Dev A:** run the `faults` dev cases, for example with a second server started with `FAULTS=<case faults>` (Q3). Until then those 6 cases stay `not_runnable`.
- **Dev A (A3):** apply `db_patches` on the clone, so the two existing injection seeds with patches and the D14 seed actually play.
- **Planner:** check that `app` is importable from `eval/simulator` under `uv run --project backend` from the repo root. `eval/harness` does not import `app` today, and `paraphrase_seeds.py` lives in `backend/scripts/` for this reason. If it isn't importable, the plan picks the import path without moving LLM access out of `app.core.llm`.
