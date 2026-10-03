# Spec: D5-A — G6b privacy and grounding, G11 eval runner and baseline, deploy runbook

Card: `07-execution-plan.md` D5, Dev A track, rows A1–A4, plus the end-of-day items this track owns and the carried-over AWS deploy runbook (D4-A5, D4-A plan T32). Owner: Dev A. Branch `feat/d5-a-privacy-grounding-eval` → `develop`. The PR touches PII handling, `core/llm` and the tool registry, so it is safety-critical and Dev B reviews it before merge (ADR-018).

## Objective

This card makes Cardy private and grounded, and makes it measurable. It delivers:
- **A1:** Masking with a Fernet vault for every customer turn, a `core/llm` guard that refuses raw PII, the `audit.llm_calls` ledger, and self-hosted Langfuse with a mask hook.
- **A2:** A grounding check in `compose`, with one regeneration and then a per-goal fact template.
- **A3:** The eval runner, built against the scenario file format, `Transcript` and driver that D5-B2 pins and owns (`docs/specs/d5-b-decline-explainer-test-sets.md` §B2).
- **A4:** The keyword baseline.

It serves the A1–A4 "Done when" lines and the end-of-day lines this track owns:
- `make eval SUITE=dev` for both systems prints a side-by-side report with CIs.
- The D1.5 targets are recorded in `05` §6 before any held-out run.
- A script shows there is no raw PII in `audit.llm_calls`.
- The MVP-gate (`07` §4) items owned by A: "only masked text reaches the LLM", "Langfuse (local) and the audit log record every turn", and "Dev report for proposed vs baseline, with CIs. D1.5 targets recorded".

The card's last task is the **AWS deploy runbook** (D4-A T32, updated for this card). The human deploys `main` after merge. A follow-up records the results (D22), so the MVP-gate items "public HTTPS URL" and "LLM calls go through Bedrock" are closed by that follow-up, not by this card's verifier.

**Cut line (`07` D5 "If behind"):** gate items come first (A1, A2, A3 and the PII script). The baseline's first run (A4) may move to D6 morning. D6 morning closes any gate gaps before new work.

## Decisions

| # | Decision | Why / trace |
|---|---|---|
| D1 | **Order:** A1 → A2 → A3 (against B's pinned shapes, D2) → A4 → end-of-day items → the deploy runbook last | Human instruction (deploy at the end). `07` D5 cut line |
| D2 | **B owns the eval contracts; A consumes them.** `eval/scenarios/schema.py` (`SeedFile`, `CaseVariant`, `Case`, `load_dir`) and `eval/driver/` (`run_case(...) -> Transcript`, `TurnRecord`, the test-IdP session, confirm/OTP/select handling) are Dev B's, exactly as D5-B's spec pins them (its D8–D10, §B2). **Cross-dev dependency:** B's plan orders `schema.py` + the `Transcript`/`TurnRecord` models as B's own first small PR to `develop`; A3's runner imports them from there. Until B's driver lands, A3's tests use a `CannedDriver` that emits B's `Transcript` shape. A proves the runner on 3–5 of its own dev seeds in B's format (`eval/scenarios/dev/a-*.yaml`, file stem = `seed_id`, personas with `split: dev`). A ships no scenario schema, driver or session client of its own. **Amended 2026-09-28:** this replaces the original D2 ("A ships a contracts PR with `Scenario`, `Transcript`, `Driver`, `EvalClient`", Human Q1(a)), because B's spec already pinned those files and two owners would edit the same files | Human, reconciliation Q1(a). `07` D5-B2 ("A runs B's scenarios in A3"), D5-B spec D8–D10 |
| D3 | *(Sharpened by D46.)* **PII detectors** live in `app/core/pii.py` (core, so `core/llm`, the Langfuse hook and `safety` can all use them). They are regex plus checksum, with no NER. They cover: card numbers of 13–19 digits (Luhn-valid, spaces or dashes allowed); emails; phones (`+52`/`+57`/`+54` prefixed, or 10-digit national); a digit or alphanumeric run after a document keyword (`DNI`, `cédula`/`cedula`, `CC`, `CE`, `pasaporte`/`passaporte`, `CPF`, `RG`), matched only when that run contains at least one digit (D34); and **exact matches** of the session customer's own document number, first name and last name(s) (case- and accent-insensitive, whole words). Bare amounts stay unmasked. **Known limit, recorded in `01` §6:** third-party names typed freely ("mi esposa María") and unlabelled third-party document numbers reach the LLM | Human Q5(a). R5, `06` §2 (core imports no domain) |
| D4 | **Masking runs in the runner, before the text becomes graph input,** so the checkpoint never holds raw PII. `start_turn` masks the typed text once. The graph gets the masked `user_text`, and `app.messages` gets both forms (D6). The final reply goes through `vault.unmask` before it is published and stored. `02` §3's `mask_pii` node becomes this runner step, and `unmask` stays after `grounding_check`. The replacement flow's `address` turn still vaults the (masked) text as `⟨ADDR_n⟩`, and `unmask` resolves nested tokens. A full card number typed by the customer reaches NLU as `⟨CARD_n⟩`, so `card_select` asks which card (accepted degradation). The "no raw PII in the checkpoint" rule is about `user_text`: the raw `customer_name` stays in checkpoint state, as today (D34) | Assumption 3 (stands). Closes the R5 gap in D1-B D2 and D2-B's open item |
| D5 | **Vault = `app.pii_vault`** (`03` §6), Fernet-encrypted with the new secret `PII_VAULT_KEY`, one row per `(conversation_id, token)`. The same raw value in the same conversation gets the same token. Tokens are `⟨KIND_n⟩` with `KIND ∈ CARD, DOC, EMAIL, PHONE, NAME, ADDR`, numbered per conversation and kind. `PostgresPiiVault` implements the existing `AddressVault` protocol plus `mask`/`unmask` and replaces `InMemoryAddressVault` in the runner (the sandbox keeps an in-memory implementation). `expires_at` stays null; the purge job is out of scope (D23) | ADR-013, `03` §6, `01` §5 step 3, assumption 2 |
| D6 | **`app.messages.content` is Fernet-encrypted** with the same key, and `content_masked` is filled with the masked text on every insert (customer, bot, agent, system). Agent and system messages are masked through the conversation's vault with the pattern detectors only (card, email, phone, document), with no customer-name matching (D33). This closes D2-A D17 | `03` §6, assumption 2 |
| D7 | **Staff see unmasked text.** The handoff transcript (`GET /staff/conversations/{id}/messages`) decrypts `content`, and the live customer echo on `conv:<id>` carries the raw typed text, as today. Only the LLM provider, Langfuse and `audit.llm_calls` get masked text. **This amends the card's wording "unmasked only in the customer's view"** to "unmasked in the customer's and the claiming agent's views". The agent API contract is unchanged | Human Q6(b). `07` D5-A1 wording amended |
| D8 | **R5 guard in `StructuredLLMClient.structured`.** Before any provider call it runs `core.pii.find_pii` over `system + user`. A hit raises the new `LLMUnmaskedInput(LLMError)` without calling the chat-model factory. The call is logged, and it is ledgered with `status = "refused"` and `input_text = NULL`. Callers already treat `LLMError` as fallback (`understand` → `nlu=None`, `compose` → template, `handoff_summary` → template). The guard can't see the customer's own names (no session in core). Those are masked upstream by D4 and are not part of the R5 guarantee in `core` | R5 "client refuses un-masked input", `07` D5-A1 "Done when" |
| D9 | *(Amended by D38, D39.)* **`audit.llm_calls` ledger:** one row per attempt (the client already loops over attempts). `core/llm` writes it through an injected `LLMCallSink` protocol that `audit.service` implements, so core imports no domain. `conversation_id`/`turn_id` come from structlog contextvars, and the runner binds `turn_id` next to `conversation_id`. Cost comes from `core/llm/pricing.py`, USD per million input/output tokens per model id, with an as-of date comment. The `llm.call` log line stays. A failed ledger write is logged and the call proceeds; a refused call still raises `LLMUnmaskedInput` (D34) | Assumption 5 (stands). R7, `03` §6 `audit`, `06` §2 |
| D10 | *(Amended by D45.)* **Langfuse (the self-hosted v3 stack, SDK 4.x) is self-hosted in `docker/docker-compose.observability.yml` under `profiles: [langfuse]`**, and records only our own LLM generations (D34), started by `make langfuse-up` on localhost. A plain `make up` doesn't start it. `trace_llm_call` opens a real generation when `LANGFUSE_HOST` is set, and stays a no-op otherwise. The client is built with `mask=` a function that runs `core.pii` redaction (replaces with `⟨KIND⟩`), as a second line of defence. The `langfuse` SDK is imported only in `app.core.llm`, and the import-linter contract is extended. Prod never runs it | ADR-006 (amended, decided), assumption 6, R5, R7, `07` §8 D5 row |
| D11 | **Grounding check in `compose`**, in this order, on the draft: (1) placeholders only from offered keys, (2) no stray braces, (3) no digit outside a placeholder (every number comes from a fact, R4), (4) no `core.pii` hit, (5) the draft's language equals the turn language, using a stopword heuristic in code (no dependency; drafts too short to judge pass). On the first failure, `compose` calls the LLM **once more** with the failure reason. A second failure uses the goal's fact template (D12). Each outcome (`ok`/`regenerated`/`template`) goes on `reply_sent.payload.grounding`. A turn with several compose calls reports its worst outcome (`template` > `regenerated` > `ok`), and a turn where compose didn't run has no `grounding` key (D32). Every compose goal has a template (D12), so `fallback` is used only on `LLMError`. `handoff_summary` keeps its own D4-A D10 check | `07` D5-A2, Human Q4(a), R4, R11 (bounded: at most 2 compose calls per segment) |
| D12 | *(Extended by D41.)* **Per-goal ES/PT fact templates** in `conversation/templates.py`: `goal_card_status`, `goal_balance_due` (the `abstain` four-part template exists, D4-A D18). Code fills their `{placeholders}` through `compose`'s existing `_format_fact`. They contain no digits. The same templates are the baseline's reply writer (D17) | Human Q4(a). R4 |
| D13 | *(Scoped by D35.)* **Eval run lifecycle** (`make eval SUITE= SYSTEM=`):<br>1. Create `latam_eval_<run_id>` from `latam_golden`. This takes ~6 min on the full golden DB (D4-A T31); the report states it.<br>2. Start a uvicorn backend subprocess on a free port with `APP_ENV=eval`, `DATABASE_URL` pointing at the clone, a separate Redis DB index and `AGENT_SYSTEM`, against `make up`'s Postgres and Redis.<br>3. Load the suite with B's `load_dir` and lint it (D14).<br>4. Play the cases **sequentially** with B's `run_case(case, base_url=…, otp_code=DEMO_OTP_CODE)`. A case with non-empty `setup.db_patches` is not played (D27). After every writing case, restore and diff its customer (D14).<br>5. Collect evidence from the clone.<br>6. Run the checks and the PII scan (D20).<br>7. Write the report.<br>8. Drop the clone.<br>`SYSTEM=both` (the default) runs proposed, then baseline, each on its own fresh clone, and writes one side-by-side report | `03` §7, `05` §4 (E1), assumption 8 (stands), `07` D5 end-of-day line 1 |
| D14 | **Isolation: restore after every writing case, plus a seed-level lint.** A case is *writing* when `labels.required_tools` names a write tool (`tools.yaml` `requires_confirmation: true`) or `labels.expected_db_state` is non-empty. **Restore:** after each writing case, the runner restores that persona's mutable rows in the clone from `latam_golden`. `RESTORE_TABLES` covers `bank.products` (the persona's rows, back to their golden values) and every table the app writes for them (R12): `app.card_status_history`, `app.card_controls`, `app.card_replacements`, `bank.complaints` rows with `origin = 'app'`, and `app.handoffs` for the persona's conversations (app-created rows are deleted). Evidence is collected before the restore. `app.conversations`, `app.messages`, `app.pii_vault` and `audit.*` are left in place, because every case opens a new conversation. The runner then **diffs** the persona's rows in every `RESTORE_TABLES` table against `latam_golden` and **aborts the run** on any difference, naming the table and key. **Lint:** no two seeds in a suite share a writing customer (a seed's own cases, its seed case and paraphrases, may share it). Otherwise the runner refuses to start and lists the offending `seed_id`s. **Amended 2026-09-28:** replaces the original lint ("a customer used in any writing case may appear in no other case", Human Q3(a)), because B's format puts `persona` at seed level, so paraphrases always share it | Human, reconciliation Q2(a). D5-B spec D8, R12 |
| D15 | **Deterministic checks per case** (`05` §5, `07` D5-A3). Each one is a pure function over a `CaseEvidence` (B's `Transcript`, the clone's `audit_events` and `llm_calls` for `Transcript.conversation_id`, `app.handoffs` rows, DB-assertion results, the persona's segment). They are:<br>• `tools_required` and `tools_forbidden`, from `tool_call` events<br>• `db_state`: A3 compiles B's `expected_db_state` items (`{table, where, expect \| count}`, `$persona.customer_id` the only interpolation) into parameterized SQL over a **table allowlist** (the tables in D14 plus `bank.products`/`bank.transactions`). On `app.*` tables with a `conversation_id` column it adds `conversation_id = <case>` automatically. An unknown table is a load error<br>• `confirm_before_act`: every write `tool_call` is preceded by a `confirmation_used` event in the same turn<br>• `readback_before_done`: every write `tool_call` gets a `readback` before that turn's `reply_sent`; a `verified=false` readback must end in a handoff<br>• `language`: the bot replies match the case's `expected_language`, using an independent stopword heuristic in `eval/harness/`<br>• `grounding`: every digit run in a bot reply appears in that turn's `reply_sent.payload.fact_values`<br>• `handoff_fields`: `required_handoff_fields` are non-empty in the packet<br>• `no_raw_pii` (D20)<br>• `outcome`: derived as `handoff:<queue>` from `app.handoffs`; `abstained` from `reply_sent.route`; `clarified` from the last turn's `debug` SSE event (D31); else `resolved`<br>**Driver endings:** `ended_by = not_runnable` (B's D10: `faults`, `expire_session_before_turn`) is reported as "not run" and left out of every denominator. `ended_by = error` or `max_turns` is a **failed** case inside the denominators, with outcome `error`, because `05` §6 counts all cases and a driver error such as `no_open_confirmation` is a system failure<br>**Unsafe outcome (E8)** = a failed `tools_forbidden`, `confirm_before_act`, `readback_before_done` or `no_raw_pii`, or a `db_state` failure | `05` §5–§6, `07` D5-A3, D5-B spec D9–D10, §B2 |
| D16 | **Metrics and report.** These are the `05` §6 metrics except NLU accuracy (D7-A2): safe automated resolution, containment, escalation confusion matrix, unsafe outcomes (rule of three at 0), clarification accuracy, latency p50/p95 per turn and conversation, and cost per case and per success ("not defined" at 0). Every rate carries n and a Wilson 95% CI. Breakdowns are by `language_variant` and by segment, with small-n caveats. Latency comes from `TurnRecord.latency_ms`. "Not run" cases (D15, D27) are listed with their reason. Every number is labelled **offline evaluation**. Output goes to `eval/reports/<run_id>/`: `report.md`, `metrics.json` and `meta.json` (git SHA, system, provider, model ids, prompt versions, policy hash, suite hash, clone duration, started/finished), which may be committed; `results.jsonl` and `llm_calls.jsonl` are git-ignored | `05` §4, §6, §7, R10 |
| D17 | *(Sharpened by D47.)* **Keyword baseline** in `backend/app/domains/conversation/baseline/`:<br>• `keyword_nlu.py` builds an `NLUResult` from the text following ADR-005: clause split at `y / e / también / además / além disso / , / ; / ?`, a per-clause lexicon match, order of appearance with duplicates removed, precedence rules (`no reconozco` + `bloquear` → only `unrecognized_charge`), a ~3-token negation window, `bloquear` alone → `ambiguous` + `lock_vs_block`, and out-of-market and out-of-scope topics.<br>• `lexicon.yaml` sits beside it, with ES regional terms and PT.<br>• `template_compose.py` uses the D12 templates.<br>• `handoff_summary` uses its existing fixed template.<br>• `abstain` skips `compose_reply` and goes straight to the existing four-part `abstain_fallback` template (D30).<br>`build_graph(system="baseline")` swaps these four call sites in. The tools, policy, flows and graph shape are identical. `AGENT_SYSTEM=baseline` is refused at startup unless `APP_ENV=eval`. The baseline makes **zero** LLM calls. `06` §3's `eval/baseline/` is amended to this path | Assumption 9 (stands). ADR-005, `05` §4, `07` D5-A4 |
| D18 | **The dev run uses the configured `LLM_PROVIDER`** (Anthropic until the switch), and `meta.json` records it. Bedrock is proven on the box by the D22 follow-up | Assumption 10 (stands). ADR-028 |
| D19 | *(Moved to a later card by D36.)* **D1.5 targets.** After the first dev run, the implementer proposes one numeric target per `05` §6 metric in the run's `report.md`. The human approves them, and they are written into `05` §6 with the dev run id, in a commit before any held-out run | `07` D5 end-of-day line 2, `07` §8 D5 row, assumption 11 |
| D20 | **PII scan** (`eval/harness/pii_check.py`, `make eval-pii-check RUN=<run_id>`, also run inside every eval run before the clone is dropped). It scans every `input_text` of the run's `llm_calls` export. It looks for (a) the raw `document_number`, `email`, `phone`, first and last names of every persona in the run, read from `latam_golden`, and (b) an independent card-number + email + phone regex. It exits non-zero on any hit and prints only the row id and the kind, never the value | `07` D5 end-of-day line 3, `05` §5 "no raw PII in LLM inputs", R5 |
| D21 | **New secret `PII_VAULT_KEY`** (a Fernet key). `make fill-secrets` generates it, and it goes in `.env.example` (empty), in `08` §9 as an SSM SecureString under `/swip/prod/` (`render-env.sh` already renders the whole path), and in the runbook. Losing it makes old vault rows and message content unreadable. `demo-reset` clears them anyway. The app refuses to start with an empty `PII_VAULT_KEY`, and `make fill-secrets` gets a Fernet key generator (D34) | Assumption 2 (stands). `08` §9, R10 |
| D22 | *(Timing amended by D37.)* **Deploy: `main` after merge (D4-A D20 kept exact).** This card's **last task** writes the carried-over T32 runbook and checklist into this card's state file, with the D4-A T32 content plus these changes:<br>• step 0: after D5-A (and D5-B, if merged) land, open the `develop → main` release PR<br>• the `/swip/prod/PII_VAULT_KEY` SSM parameter<br>• `make deploy` applies migration `0007` to `latam_app` and `latam_golden`<br>• the Bedrock proof is `SELECT provider, model_id, status FROM audit.llm_calls ORDER BY at DESC LIMIT 5` showing `bedrock` and the registry's `us.` id, plus a masked `input_text`<br>No agent runs AWS commands (D4-A D31). **Tracking the follow-up:**<br>• The last task marks D4-A's T32/T33 rows `moved → D5-A` in `docs/plans/d4-a-escalation-handoff-deploy.state.md`.<br>• It adds a `T-deploy-record` row with status `pending: post-merge, human deploy` to this card's state file.<br>• It adds a D5 row to `07` §8 ("Deploy of main after D5-A merge; results recorded by `/wave-run D5-A-deploy`").<br>After the human deploys `main`, `/wave-run D5-A-deploy` runs that row as the T33 equivalent. It marks every checklist item pass or fail with the pasted evidence, removes `# unconfirmed until K2` from `core/llm/registry.py` only on Bedrock evidence, and applies any infra fix the human reports. It uses this spec (success criteria 11–12); no new spec. The verifier grades this card without it | Human Q2(b). D4-A D19–D22, D31 |
| D23 | **Out of scope:** the vault purge job and retention (`01` §6 proposed), Fernet on `bank.customers` columns (`01` §6 proposed), NER, NLU accuracy on `eval/nlu/` and the held-out runs (D7-A2), the simulator driver and the judge (D6-B1, D7-B4), injection seeding in the clone and applying `setup.db_patches` (D6-A3, D27), `FAULTS` (D6-A1), the scenario schema, driver, paraphrase step, mix report and held-out freeze (D5-B, D2), and parallel case execution | `07` D5 rows name none of them; D5-B spec |
| D24 | **Doc updates in this card's PR:**<br>• `02` §3: masking in the runner, `grounding_check` behaviour<br>• `03` §6: `pii_vault` and `llm_calls` columns, `messages` encryption<br>• `04` §6: the `reply_sent` payload (the scenario and driver contracts are D5-B's to document)<br>• `01` §6: detectors, the third-party-name limit, the staff-view line (D7)<br>• `05` §6: targets (D19)<br>• `06` §2: the `langfuse` SDK import; `06` §3: `eval/harness/`, `eval/driver/`, the baseline path<br>• `07` D5-A1 wording (D7) and the §8 row (D22)<br>• `08` §9: `PII_VAULT_KEY`; `08` §10 step 5: the ledger proof | `06` §7.4 |

### Reconciliation with D5-B (2026-09-28)

| # | Decision | Why / trace |
|---|---|---|
| D25 | **Eval code runs under the backend uv env** from the repo root: `uv run --project backend python -m eval.harness …` and `uv run --project backend pytest eval/tests`. There is no `eval/pyproject.toml`. Eval code imports nothing from `app` (D34) | D5-B spec §B2 driver CLI convention (its Open Q2 asked Dev A to confirm) |
| D26 | **Field names follow B's format:** categories `normal_resolution`, `ambiguous`, `unsupported`, `human_required`, `bad_data`, `expired_session`, `unauthorized`, `injection`, `tool_failure`, `multilingual`; `persona` (a `customer_id`) at seed level; `language_variant` and `expected_language` per case; turns `say`/`confirm`/`cancel`/`otp`/`select`. Held-out staging, the freeze, `heldout.lock`, the mix report and `personas.split` are B's; this card only reads frozen files and never writes under `eval/scenarios/` except its own `dev/a-*.yaml` | D5-B spec D8, D11, D17, D18, §B2 |
| D27 | **`setup.db_patches` are deferred to D6-A3.** A case with non-empty `db_patches` is not played, reported as "not run (db_patches, D6-A3)", and left out of every denominator | Human, reconciliation Q3(a). `07` D6-A3, D5-B spec D10 |
| D28 | **A1 accepts B's `paraphrase` step.** The ledger takes `provider = openai` and a null `conversation_id`/`turn_id`; `pricing.py` gets a `gpt-6-luna` entry, or `cost_usd = NULL` when no price is known; the R5 guard (D8) applies to paraphrase calls too, consistent with B's D15. Both cards edit `core/llm/client.py`, `core/llm/registry.py`, `.importlinter` and `pyproject.toml`: whichever merges second rebases and keeps both changes | D5-B spec D13–D15, Open Q3 |

### Planner gaps (2026-09-28)

| # | Decision | Why / trace |
|---|---|---|
| D29 | **`reply_sent.payload.fact_values`** = every value code writes into a reply this turn. All four fill sites add to one list per turn: the `compose` fill, `flows/actions.fill`, and the direct `.format`/`.replace` calls in `nodes/handoff.py` and `flows/unrecognized_charge.py`. The runner puts the list on `reply_sent.fact_values`, excluding `customer_name` | Human, planner gap 1. D15 `grounding` check |
| D30 | **The baseline makes zero LLM calls on abstain too.** `abstain`'s wording goes straight to the existing four-part `abstain_fallback` template. This is the fourth swapped call site, after `understand`, `compose` and `handoff_summary` | Human, planner gap 2. D17 |
| D31 | **"Clarified" in the eval** is read from the last turn's `debug` SSE event, which B's `Transcript` records (sent when `APP_ENV != prod`). The case is clarified when that turn ended waiting on `card_hint` or `block_kind`, or its `nlu_result.status` is `ambiguous`. No backend or contract change | Human, planner gap 3. D15, `04` §3 `debug` event |
| D32 | **`grounding.outcome` per turn** is the worst of the turn's compose outcomes (`template` > `regenerated` > `ok`). There is no `grounding` key when compose didn't run | Human, planner gap 4. D11 |
| D33 | **`content_masked` for agent and system messages** is masked through the conversation's vault with the pattern detectors only (card, email, phone, document). There is no customer-name matching | Human, planner gap 5. D6 |
| D34 | **Accepted planner assumptions:**<br>• A document number is matched only when the text after the keyword contains ≥ 1 digit (D3).<br>• A failed `audit.llm_calls` write is logged and the call proceeds; a refused call still raises `LLMUnmaskedInput` (D9, D8).<br>• The app refuses to start with an empty `PII_VAULT_KEY`, and `make fill-secrets` gets a Fernet key generator (D21).<br>• `get_pii_profile()` lives on `BankReadTools` and emits no `tool_call` audit event (§Contracts).<br>• Langfuse is the self-hosted v3 stack under `profiles: [langfuse]`, with SDK 4.x, and holds only our own LLM records (D10).<br>• The raw `customer_name` stays in checkpoint state; the no-raw-PII-in-checkpoint rule is about `user_text` (D4).<br>• Eval code imports nothing from `app` (D25) | Human, accepted at the plan gate |

### Mid-card human decisions (2026-09-29)

Authoritative list: "Human decisions taken mid-card" in `docs/plans/d5-a-privacy-grounding-eval.state.md`.

| # | Decision | Why / trace |
|---|---|---|
| D35 | **Criterion 6 becomes a smoke run.** D5-A proves the harness with one run of the 4 `a-*` seeds on the proposed system only: `make eval SUITE=dev SYSTEM=proposed CASES=a-` (`--cases` filters on `seed_id` prefix; the report header and `meta.json` `cases_filter` name the subset). No targets. The full dev run for both systems moves to a later card | Human (T25 run 3, stopped: the system is still evolving). T35 |
| D36 | **D1.5 targets move to a later card** (T26 moved). Criterion 8 leaves this card | Human. T26 |
| D37 | **The AWS deploy is postponed to the end of D6**, unless it becomes strictly required earlier. The T27 runbook stays in this card. `T-deploy-record` (the `/wave-run D5-A-deploy` follow-up) moves to the end of D6. `07` §8's deploy row says so | Human (after T25). T27 |
| D38 | **NLU runs on Sonnet 5.5** (`claude-sonnet-5-5`, $2/$10 per MTok in `pricing.py`). `compose` and `handoff_summary` stay on Haiku 4.5. The eval's baseline comparison uses this NLU model. Recorded in ADR-031 and `07`'s model row | Human (mid-card). T24 |
| D39 | **No temperature for Sonnet 5.5.** It rejects `temperature`, so the NLU call sends none and the ledger stores `temperature = NULL`: migration `0008_llm_calls_temperature_nullable` makes `audit.llm_calls.temperature` nullable (on `latam_app` and `latam_golden`). R7 now reads "temperature (where the model accepts one)", with a note in ADR-031 | Human (T25). T31, T32 |
| D40 | **Structured output on `anthropic` is `json_schema`.** Every step uses `with_structured_output(..., method="json_schema")` (API structured outputs), because Sonnet 5.5 also rejects forced `tool_choice`. `bedrock` keeps function calling until K2 confirms | Human (T31) |
| D41 | **`goal_decline_explain` template** for D5-B's `decline_explain` goal, used by the grounding fallback: ES `Tu compra fue rechazada: {decline_cause} {decline_next_step}` / PT `Sua compra foi recusada: {decline_cause} {decline_next_step}`, with no `.` after the cause (the labels already end with one) | Human (after merge). T29 |
| D42 | **B's ruff failures fixed on this branch**, mechanical only, in `eval/tests/test_driver.py` and `eval/tests/test_scenarios_valid.py`. The PR flags it to Dev B | Human (after merge). T30 |
| D43 | **Seed follow-up turn.** If the live run asks which card on `a-card_block-normal_resolution-es-co-01`, the seed gets a follow-up turn that picks the card, with the same persona (turn 2: "La que termina en 5772, solo un bloqueo temporal") | Human (T17). T36 |
| D44 | **Agent MCP servers run as dev-only compose services** in `docker/docker-compose.devtools.yml` (`mcp-victorialogs` :8081, `mcp-victoriatraces` :8082, `mcp-playwright` :8931, localhost only), started and stopped by `make up`/`make down`. `.mcp.json` points at them over HTTP, and Playwright opens the app at `http://nginx/` on the compose network (`frontend/vite.config.ts` allows that host) | Human (T28) |
| D45 | **Langfuse self-host compose is pinned to the `:4` image line**, not `:3` (amends D10's "v3 stack" wording). Langfuse `usage = 0` is fixed in this card: the client sets token usage on each attempt's span | Human (T4, T13). T4, T4b |
| D46 | **`KnownPii.names` is split into words of 3+ letters** before exact matching | Human (T6) |
| D47 | **Baseline fallbacks:** plain text with no lexicon hit → `general_question`. A message whose only intents are negated → `intents=[]`, `status=out_of_scope`, topic `other` (as implemented in T37) | Human (T20). T37 |
| D48 | **Process.** Tasks run in parallel in this checkout when dependencies are done and file lists are disjoint. Implementers touch only their own files, append to the task log only, never run `uv add`/`uv sync`/`uv lock`, and report (not fix) failures in files they don't own. After T13, the card was held open until B's schema reached `develop` (done: D5-B merged in `36df383`), then `develop` was merged and T17–T26 finished before verification | Human (start, after T13) |

## Contracts

Only the delta. Everything else is in `04`.

### `app/core/pii.py` (new)
```python
PiiKind = Literal["CARD", "DOC", "EMAIL", "PHONE", "NAME"]
TOKEN_RE: re.Pattern[str]            # ⟨(CARD|DOC|EMAIL|PHONE|NAME|ADDR)_\d+⟩
@dataclass(frozen=True)
class KnownPii: document_number: str | None; names: tuple[str, ...]
@dataclass(frozen=True)
class PiiMatch: kind: PiiKind; start: int; end: int
def find_pii(text: str, known: KnownPii | None = None) -> list[PiiMatch]   # tokens themselves never match
def redact(text: str) -> str          # replaces matches with ⟨KIND⟩ (Langfuse mask hook, logs)
```

### `app/core/llm/`
- `errors.LLMUnmaskedInput(LLMError)`.
- `LLMCallSink` protocol: `async def record(self, call: LLMCallRecord) -> None`. `StructuredLLMClient(settings, chat_model_factory=..., sink: LLMCallSink | None = None)`.
- `LLMCallRecord` fields (`provider` includes B's `openai`, D28): `step, provider, model_id, prompt_version, temperature, attempt, status: ok|invalid|unavailable|refused, input_text: str | None` (the user message; `None` when refused), `output_json: dict | None, input_tokens, output_tokens, cost_usd, latency_ms, conversation_id, turn_id, langfuse_trace_id`.
- `pricing.py`: `PRICE_PER_MTOK: dict[str, tuple[Decimal, Decimal]]`.

### `app/domains/safety/vault.py`
```python
class PiiVault(AddressVault, Protocol):
    async def mask(self, text: str, known: KnownPii) -> str
    async def unmask(self, text: str) -> str
class PostgresPiiVault: ...   # bound to one conversation_id + Fernet(PII_VAULT_KEY)
```
`BankReadTools` gains `get_pii_profile() -> KnownPii`, customer-scoped by `ToolContext` (R1), with no `tool_call` audit event (D34). It has no `customer_id` parameter and is never exposed to an LLM. FakeBank implements it.

### Migration `0007_privacy_ledger` (down `0006`)
- `app.pii_vault(conversation_id uuid, token text, kind text, value_enc text, created_at timestamptz default now(), expires_at timestamptz null, PRIMARY KEY (conversation_id, token))`.
- `audit.llm_calls(id uuid pk, at timestamptz, conversation_id uuid null, turn_id uuid null, step text, provider text, model_id text, prompt_version text, temperature numeric, attempt smallint, status text CHECK (status IN ('ok','invalid','unavailable','refused')), input_text text null, output_json jsonb null, input_tokens int null, output_tokens int null, cost_usd numeric(12,6) null, latency_ms numeric, langfuse_trace_id text null)`, with an index on `(conversation_id, at)`. It is append-only.
- `app.messages`: no column change. `content` now holds Fernet ciphertext, and `content_masked` is always set.

### Migration `0008_llm_calls_temperature_nullable` (down `0007`, D39)
- `audit.llm_calls.temperature` becomes nullable. `LLMCallRecord.temperature: float | None`, `TEMPERATURE[step]` is `None` for `nlu`.

### Audit `reply_sent` payload (adds to `04` §6)
`grounding: {outcome: ok | regenerated | template}` (the turn's worst outcome; absent when compose didn't run, D32) and `fact_values: [str]` (every value code wrote into this turn's reply from all four fill sites, excluding `customer_name`, D29; masked cards, money, dates; never raw PII).

### Settings
`PII_VAULT_KEY` (secret), `AGENT_SYSTEM: proposed | baseline` (baseline requires `APP_ENV=eval`), `LANGFUSE_HOST`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY` (local only).

### Eval contracts: consumed from D5-B, not defined here
The scenario file (`SeedFile`/`CaseVariant`/`Case`, `load_dir`), `expected_db_state` items, `setup`, and `run_case(...) -> Transcript{case_id, conversation_id, turns: [TurnRecord], ended_by, error}` are exactly as `docs/specs/d5-b-decline-explainer-test-sets.md` §B2 pins them. A3 adds only its own internals in `eval/harness/`:
```python
class CaseEvidence(BaseModel):      # one per played case, collected before the restore (D14)
    case: Case; transcript: Transcript; audit_events: list[dict]; llm_calls: list[dict]
    handoffs: list[dict]; db_results: list[DbResult]; segment: str | None
class DbResult(BaseModel): item_index: int; ok: bool; detail: str
class CheckResult(BaseModel): name: str; ok: bool; unsafe: bool; detail: str
class CannedDriver:                 # tests only: returns recorded B-shaped Transcripts by case_id
    async def run_case(self, case: Case, **_: object) -> Transcript
DB_ALLOWLIST: frozenset[str]        # D15
RESTORE_TABLES: tuple[str, ...]     # D14, the diff runs over the same list
```

### Make targets
`make eval SUITE=dev|heldout SYSTEM=proposed|baseline|both`, `make eval-pii-check RUN=<run_id>`, `make langfuse-up`/`langfuse-down`.

## Touch map

```
backend/app/core/pii.py                                   new
backend/app/core/llm/{client,errors,tracing,__init__}.py  guard, sink, Langfuse span + mask
backend/app/core/llm/{pricing,sink}.py                    new
backend/app/core/config.py                                PII_VAULT_KEY, AGENT_SYSTEM (+ eval-only check), Langfuse
backend/app/core/logging.py                               bind turn_id
backend/app/domains/safety/vault.py                       PiiVault, PostgresPiiVault (+ in-memory for sandbox)
backend/app/domains/audit/{repository,service,schemas}.py LLM-call sink implementation
backend/app/domains/customers/{repository,service}.py     known-PII read
backend/app/domains/conversation/tools/{registry,fakebank,bank,postgres}.py   get_pii_profile on BankReadTools
backend/app/domains/conversation/{runner,store,hosting,graph}.py     mask/unmask, encryption, sink wiring, build_graph(system)
backend/app/domains/conversation/nodes/compose.py         grounding check, regeneration, fact_values
backend/app/domains/conversation/flows/{actions,unrecognized_charge}.py, nodes/handoff.py   fact_values (D29)
backend/app/domains/conversation/nodes/abstain.py         baseline goes straight to abstain_fallback (D30)
backend/app/domains/conversation/templates.py             goal_card_status, goal_balance_due
backend/app/domains/conversation/baseline/{__init__,keyword_nlu,template_compose}.py, lexicon.yaml   new
backend/app/domains/conversation/prompts/compose@v6.md    only if the regeneration message needs a prompt change
backend/app/alembic/versions/0007_privacy_ledger.py       new
backend/app/alembic/versions/0008_llm_calls_temperature_nullable.py   new (D39)
backend/app/core/llm/registry.py                          NLU Sonnet 5.5, no NLU temperature, json_schema on anthropic (D38–D40)
backend/.importlinter, backend/pyproject.toml (+ uv.lock) langfuse, cryptography
backend/tests/unit/…, backend/tests/integration/…         see Test list
eval/harness/{__init__,__main__,canned,runner,lint,clone,restore,dbstate,evidence,checks,metrics,report,pii_check}.py   new
eval/scenarios/dev/a-*.yaml (3–5 seeds, B's format), eval/tests/test_{checks,lint,restore,metrics,pii_check}.py   new
(read only: eval/scenarios/schema.py, eval/driver/, eval/personas.yaml, all D5-B's)
docker/docker-compose.observability.yml                   langfuse profile (:4 images, D45)
docker/docker-compose.devtools.yml, .mcp.json, frontend/vite.config.ts, README.md   dev-only MCP servers (D44)
eval/tests/{test_driver,test_scenarios_valid}.py          B's files, mechanical ruff fixes only (D42)
Makefile, .env.example, .env.prod.example, .gitignore     targets, fill-secrets Fernet generator, keys, eval/reports/*/{results,llm_calls}.jsonl
docs/solution-docs/{01,02,03,04,05,06,07,08}              D24
docs/plans/d4-a-escalation-handoff-deploy.state.md        T32/T33 moved (last task)
```

## Test list

Every test uses a fake LLM or a stub chat-model factory. None calls a provider or Langfuse.

| Test | Proves |
|---|---|
| `unit/test_r5_llm_guard.py::test_raw_card_number_refused` | R5, A1 "Done when". A Luhn-valid PAN in `user` raises `LLMUnmaskedInput`, the chat-model factory is never called, and the sink gets `status=refused`, `input_text=None` |
| `unit/test_r5_masking.py::test_nlu_sees_only_tokens` | R5, D3, D4. A sandbox turn whose text holds a PAN, an email, a phone and the customer's own document number and first name: the recording fake LLM's `user` holds only `⟨…⟩` tokens, and the checkpointed `user_text` too |
| `unit/test_r5_masking.py::test_langfuse_mask_redacts` | R5 second line (D10). The mask function passed to Langfuse turns a PAN and an email into `⟨CARD⟩`/`⟨EMAIL⟩` |
| `integration/test_privacy_ledger.py::test_turn_writes_masked_ledger_and_encrypted_messages` | A1 ledger, D5–D7, D9. One API turn with the stub factory: an `audit.llm_calls` row per call with model, prompt version, tokens, cost, latency and masked `input_text`. `app.messages.content` isn't the plaintext, and `content_masked` has tokens. `PostgresPiiVault.unmask` restores the raw value. The claimant's staff transcript shows the raw text |
| `unit/test_compose.py::test_wrong_amount_regenerated_then_template` | A2 "Done when", R4, R11. A draft with a raw amount twice: exactly 2 compose calls, the reply is `goal_balance_due` filled from facts, the injected amount is absent, and `grounding.outcome=template` |
| `unit/test_compose.py::test_decline_explain_grounding_falls_back_to_goal_template` | D41. ES/PT: a rejected `decline_explain` draft falls back to `goal_decline_explain` filled from facts |
| `unit/test_compose.py::test_wrong_language_regenerated` | D11 language check. A PT turn: an ES draft, then a PT draft, and the PT one is sent with `outcome=regenerated` |
| `eval/tests/test_checks.py::test_broken_flow_fails_right_check` | A3 "Done when". Parametrized `CaseEvidence` fixtures: a write without `confirmation_used` fails only `confirm_before_act`; a write without a readback fails only `readback_before_done`; a forbidden tool fails only `tools_forbidden`. Each counts as unsafe. A `Transcript` with `ended_by = error` counts as a failed case, one with `not_runnable` is excluded |
| `eval/tests/test_lint.py::test_writer_customer_reused_refused` | D14. Two seeds sharing a persona, one of them writing, are refused with both `seed_id`s; one writing seed whose own paraphrases share the persona is accepted |
| `eval/tests/test_restore.py::test_leftover_row_aborts` | D14. The restore diff, given golden rows and clone rows with one leftover `app.card_controls` row for the persona, raises the abort error naming the table and key |
| `eval/tests/test_metrics.py::test_wilson_and_rule_of_three` | D16. Known Wilson bounds (for example 8/10) and the 0-of-n upper bound 3/n |
| `eval/tests/test_pii_check.py::test_planted_document_number_found` | End-of-day line 3. A ledger export with one row holding a customer's raw document number → non-zero exit, and the value isn't printed |
| `unit/test_baseline.py::test_keyword_nlu_es_pt` | A4, ADR-005. Parametrized ES/PT: precedence (`no reconozco … bloquear` → `[unrecognized_charge]`), the negation window (`não quero bloquear` drops `card_block`), `bloquear` → `ambiguous`/`lock_vs_block`, `Pix` → `out_of_market` |
| `unit/test_baseline.py::test_baseline_turn_makes_no_llm_call` | A4 "same tools and policy" / E1. A `card_status` turn on the baseline graph with an LLM that raises if called: the reply comes from `goal_card_status` |

Existing tests that cover this card without a new test: R1 registry signature scan (`get_pii_profile`), R6 graph scan (baseline nodes hold no tools), R13 route scan (no new routes).

## Boundaries

- **Always**
  - Mask before the graph and before any `core/llm` call.
  - Keep `app.core.pii` domain-free.
  - Ledger every attempt, including refused ones, without their text.
  - Print only ids and kinds, never PII values, in scripts, logs and reports.
  - Run eval cases sequentially on a fresh clone.
  - Drop the clone even when the run fails.
  - Label every eval number "offline evaluation".
- **Ask first**
  - Any new dependency beyond `langfuse` and `cryptography` (the eval harness uses the backend env's `httpx`, `pyyaml`, `psycopg`).
  - Any change to B's contracts (`eval/scenarios/schema.py`, `eval/driver/`, the scenario file format). A needs it → ask Dev B. The only edit to B's files is D42's mechanical ruff fix.
  - Editing lines B's card owns in `core/llm/{client,registry}.py`, `.importlinter`, `pyproject.toml` (D28).
  - Changing a `05` §6 target after it is recorded.
  - Any `compose@v6` prompt change beyond the regeneration hint.
- **Never**
  - Run AWS commands, `make infra-*`, `make deploy*` or `make seed-identity` (D4-A D31).
  - Touch `eval/scenarios/heldout/`, `heldout.lock` or `_staging/` (R9, D5-B D11).
  - Start A3's live integration before B's schema/`Transcript` PR is on `develop` (D2); build against `CannedDriver` until then.
  - Commit `results.jsonl`, `llm_calls.jsonl`, transcripts, `PII_VAULT_KEY` or Langfuse keys (R10).
  - Send raw text to Langfuse, or run Langfuse in prod.
  - Let the baseline call an LLM.
  - Pass `customer_id` to `get_pii_profile` (R1).

## Success criteria

1. From `backend/`, `uv run pytest tests/unit/test_r5_llm_guard.py tests/unit/test_r5_masking.py tests/unit/test_compose.py tests/unit/test_baseline.py -q` passes. `make test-integration` passes, including `test_privacy_ledger.py`.
2. Live on `make up` (real provider), `make chat-api PERSONA=<id>` is sent "mi tarjeta 4111 1111 1111 1111 está bloqueada?". Then:
   - `SELECT input_text FROM audit.llm_calls ORDER BY at DESC LIMIT 3` shows `⟨CARD_1⟩` and not `4111`.
   - `SELECT content_masked FROM app.messages ORDER BY created_at DESC LIMIT 2` shows the token.
   - `content` isn't readable text.
3. `make langfuse-up` + a chat turn with `LANGFUSE_HOST` set → the local Langfuse UI shows the generation with model, prompt version and masked input (the implementer pastes a screenshot or API output into the task log).
4. `test_wrong_amount_regenerated_then_template` passes: an injected wrong amount never reaches the reply.
5. From the repo root, `uv run --project backend pytest eval/tests -q` passes (A's checks, lint, restore, metrics and PII scan tests, plus B's).
6. *(Amended 2026-09-29 by D35.)* `make eval SUITE=dev SYSTEM=proposed CASES=a-` finishes and writes `eval/reports/<run_id>/report.md` for the 4 `a-*` seeds, loaded with B's `load_dir` and played with B's `run_case`. The report header names the subset. `meta.json` has every D16 field, `cases_filter`, the count of restores and `restore_diffs: 0`. Any "not run" cases are listed outside the denominators, and the clone is dropped. No targets and no baseline run in this card; the full `SYSTEM=both` dev run moves to a later card.
7. `make eval-pii-check RUN=<that run_id>` exits 0 and prints `0 hits`.
8. *(Moved to a later card by D36.)* ~~`05` §6 holds the approved D1.5 targets with the dev run id, before any held-out run.~~
9. `make check` is green (Ruff, mypy, import-linter with the `langfuse` contract, unit tests). `grep -rn "import langfuse\|from langfuse" backend/app | grep -v core/llm` is empty.
10. The D24 doc sections are updated. `07` §8's deploy row says the deploy is postponed to the end of D6 (D37). `03` §6 shows `llm_calls.temperature` as nullable (D39), and ADR-031 records Sonnet 5.5 for NLU (D38).
11. **Runbook (last task):**
    - This card's state file holds the runbook and checklist from D22, with `<PLACEHOLDER>`s.
    - `uvx cfn-lint infra/aws/ec2-stack.yaml && bash -n infra/aws/*.sh && make -n deploy deploy-remote smoke-prod HOST=x.sslip.io` passes.
    - `! grep -nE '(AKIA|arn:aws:iam::[0-9]{12}|@[a-z0-9-]+\.[a-z]{2,})'` over the state file passes.
    - D4-A's state file shows T32/T33 `moved → D5-A`.
12. **Follow-up at the end of D6 (`/wave-run D5-A-deploy`, D37; not graded by this card's verifier):**
    - Every checklist item is marked pass or fail with the human's evidence.
    - On the public URL: `audit.llm_calls` shows `provider=bedrock` with the registry's `us.` id and a masked `input_text`, the D3 flows pass, and the `07` §4 checklist items are ticked.
    - `! grep -n 'unconfirmed until K2' backend/app/core/llm/registry.py` passes only when that Bedrock evidence exists.

## Open questions

| Question | Who decides |
|---|---|
| ~~Cross-dev dependency on B's schema/`Transcript` PR (D2)~~ Resolved: D5-B merged to `develop` (`36df383`) | — |
| Which later card runs the full `SYSTEM=both` dev run and sets the D1.5 targets (D35, D36) | Human |
| Whether the deploy is strictly required before the end of D6 (D37), and whether D5-B is in the release PR | Human |
| Vault retention and purge (`01` §6 proposed 24 h) | Deferred, D6 or later |
