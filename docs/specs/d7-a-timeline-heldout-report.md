# Spec: D7-A — Timeline API and the held-out report pipeline

Card D7-A (Dev A's D7 track: G13 timeline API, G11 held-out report) · `07` lines 291-317, rows A1-A2 · branch `feat/d7-a-timeline-heldout-report` (base `develop`).

## Objective

This card makes every turn explainable to staff and builds the pipeline that produces the held-out report.

- **A1: timeline API.**
  - A staff conversation list with filters: language, country, intent, outcome, escalation and date.
  - A per-turn timeline built from `audit.audit_events`, `audit.llm_calls`, `app.messages` (masked text only) and `app.handoffs`. Each turn shows the intent result, rules hit, tools, sources, policy hash, model and prompt version, latency, cost and the Langfuse link.
  - A system metadata endpoint.
  - The admin-only persona catalog and credential lookup.
- **A2: the held-out report pipeline.**
  - `RUNS=N` (proposed ×N, baseline once).
  - One aggregate report per invocation, with CIs, breakdowns by language and segment, error analysis and labels.
  - The NLU comparison: keyword baseline vs 2 models, on a set derived from the scenarios.
  - A cheaper run isolation: one clone per invocation, with a verified reset between runs.
  - **The proof is a dev subset** (about 60 live calls). The full held-out run is a documented single command that a human triggers later (D2, D3).

It serves these "Done when" lines:
- A1: "Filter counts match a SQL check".
- A2: "`eval/reports/heldout-<sha>/report.md`". **This card delivers it as `eval/reports/dev-<sha>/report.md`.** The held-out report itself is deferred until the human review, freeze and D1.5 targets are done (D2).

It serves end-of-day step 1 through B3's screens, which use A1's API. Step 4 ("the held-out report is complete") is deferred by D2. Rows B1-B4 belong to Dev B. B3 consumes A1's schemas (D22). B4's judge is referenced from the report but not built here (D9).

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Scope** is A1 and A2 as listed in the Objective. **Out:** the full held-out run and its report, the B3 screens, the B4 judge, Bedrock (K2), `FILE_COPY` in `pipeline/load/demo_reset.py`, a per-conversation summary table, and any change to `eval/scenarios/heldout/`, `_staging/heldout/` or `heldout.lock` | Human Q1(a), Q5(a), isolation answer; R9 |
| D2 | **A2 is proven on a dev subset:** `make eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke`. That is proposed ×3 and baseline ×1 on the 4 `a-*` cases, plus the NLU comparison on the 20-utterance smoke set × 2 models. It costs about 60 live LLM calls, under $1. This card's Done-when artifact is `eval/reports/dev-<sha10>/report.md`, and `heldout-<sha10>/report.md` is deferred | Human Q1(a); standing rule: no full suites while the system is still changing |
| D3 | **The held-out run is one command a human triggers:** `make eval SUITE=heldout SYSTEM=both RUNS=3 NLU=suite`. It has three preconditions, all human steps: (1) both humans review 100% of `_staging/heldout/`; (2) a human runs `make eval-freeze`; (3) the D1.5 targets are recorded in `05` §6. The harness **refuses** `--suite heldout` unless `eval/scenarios/heldout.lock` exists and `freeze.check` passes. `05` §7 documents the command and the preconditions | Human Q1(a); R9; `07` §8 (D5 row: targets before any held-out run) |
| D4 | **`RUNS=N` repeats only the proposed system.** The baseline runs once, because it makes zero LLM calls and is deterministic (D5-A D17). The default is `RUNS=1` | `07` A2 "proposed ×3 + baseline"; `05` §5 "runs 3× for the proposed system" |
| D5 | **Aggregation.** Each `05` §6 metric shows proposed run 1..N (each with n and a Wilson 95% CI), then the mean and the min–max across runs, then the baseline value with its CI. Breakdown cells (by `language_variant` and by segment) show the proposed mean (min–max) and the baseline, with n per group and the existing small-n caveats. Runs are never pooled into one CI, because they aren't independent | Assumption 6 (stood); `05` §5-§6 (E2, E10) |
| D6 | **Report folder:** each `make eval` invocation writes one folder, `eval/reports/<suite>-<sha10>/`, where `sha10` is HEAD's short SHA. If the folder already exists, the new one gets `-2`, `-3`, and so on. `report.md`, `metrics.json` and `meta.json` may be committed; `results.jsonl` and `llm_calls.jsonl` stay git-ignored (existing `.gitignore` rule). `meta.json` records `dirty: bool` for the working tree | `07` A2 Done-when path; assumption 7 (stood); D5-A D16 |
| D7 | **Labels:** scripted-driver numbers are labeled **offline evaluation**, `DRIVER=simulator` numbers **simulation**, and any projected figure **projection**. This card produces none of the last kind. Each table header carries its label. The model comparison also carries the ADR-028 provider caveat (D14) | `05` §6 (E11); `07` A2 |
| D8 | **R9 in the report.** For `SUITE=heldout`, a failure line shows only the `case_id` and the names of the failed checks, never transcript text. Error analysis is counts by category × failed check, per system. Dev reports keep today's failure examples | Assumption 8 (stood); R9; `07` D7 rule |
| D9 | **Judge boundary:** the report has a "Reply quality (LLM judge)" section. It links to B4's agreement report when that file exists, and otherwise reads "pending D7-B4". No code imports B4's judge.<br>**Amended (plan Q2):** the link goes to a fixed path, `eval/judges/agreement.md` (next to `rubric.md`), which D7-B4 must write. When that file is absent, the section reads "pending D7-B4" | Assumption 9 (stood); `07` B4; human plan Q2 |
| D10 | **Run isolation: one clone per invocation.**<br>• `clone.create` uses `CREATE DATABASE … TEMPLATE latam_golden STRATEGY FILE_COPY`.<br>• The clone is created once per `make eval` invocation and reused by every run of every system.<br>• **Before each run** (including the first), the runner calls `restore_persona` + `verify_persona` for **every distinct persona** in the selected cases (not only writing ones), then clears `turns:*` in that system's eval Redis db.<br>• Any diff aborts the run (`RestoreDiffError`, D5-A D14).<br>• The per-case restore after writing cases stays.<br>• `meta.json` logs `clone_strategy`, a single `clone_seconds`, `resets` and `reset_diffs`.<br>`05` §4's "each run starts from a fresh clone" is amended to "each run starts from a clone whose suite personas are verified equal to golden".<br>**Amended (T6, T13):** FILE_COPY was measured at **489.5 s cold** (T6) and **59.5 s warm** (T13, `eval/reports/dev-c64dd67067/meta.json`), not the 1–3 min estimated before the build. The human kept the design: FILE_COPY, one clone per `make eval` invocation, reused across all runs and systems | Human isolation answer (A+B); golden DB is 7.7 GB and WAL_LOG clones measured 354–1030 s (D4-A T31, `eval/reports/*/meta.json`); human decision at T6 |
| D11 | **The first eval task measures the FILE_COPY clone time once** on the dev host and records it in the plan state file. `demo_reset.py` keeps its current statement.<br>**Amended (T6):** done. The measurement was 489.5 s cold on the dev host (WSL2 Docker), and 59.5 s warm in the T13 proof run | Human isolation answer; human decision at T6 |
| D12 | **The NLU set is derived at run time.**<br>• With `NLU=suite`, each selected scenario case gives one utterance: its first `say` turn, labeled with its seed's `labels.expected_intents`, `expected_language` and `language_variant`. The country comes from the persona's `country` trait in `eval/personas.yaml`, and `pending` is `None`.<br>• With `NLU=smoke`, the set is `eval/nlu/nlu_v1_smoke.yaml` as it stands (with `status` labels).<br>• No new labeled file is written, and the held-out part inherits `heldout.lock` | Human Q4(a); `05` §2 "derived from the same seeds and split the same way" |
| D13 | **NLU metrics** (`05` §6):<br>• intent-set precision, recall and F1 (macro over intents);<br>• exact-set match with a Wilson CI;<br>• a multi-intent slice (≥2 expected intents);<br>• a breakdown by `language_variant`;<br>• status accuracy **only for `NLU=smoke`** (the scenarios carry no status label).<br>Systems compared: `keyword_nlu` (0 calls) against `run_nlu` on each model. Each model row also shows p50/p95 latency and mean cost per call.<br>**Amended (T9):** an `nlu` call that still fails after its retries counts as an empty prediction, and each model row reports those calls as `failed_calls` | Human Q4(a); ADR-005; `05` §6; human decision at T9 |
| D14 | **The model comparison uses the Anthropic API:** `claude-sonnet-5-5` vs `claude-haiku-4-5-20251001` for the `nlu` step, same prompt (`nlu` current version). The report labels it "Anthropic API; Bedrock serves the same models (ADR-028)". `decision-log.md` gets a **Proposed** entry, "Model per step (D7)", that records the smoke result with that caveat and says the choice is final after the held-out NLU comparison. `07` §8 row D7 points to it | Human Q2(a); `07` A2 "chosen model per step recorded in the decision log" |
| D15 | **The NLU comparison runs in-process, like `nlu_smoke.py`.**<br>• It goes through `get_llm_client(..., sink=<in-memory sink>, model_overrides={"nlu": <model>})`, so the R5 `find_pii` guard, R7 pinning and R11 retries all apply unchanged.<br>• Every `LLMCallRecord` is appended to the report folder's `llm_calls.jsonl` and included in the run's PII scan.<br>• `model_overrides` is new, and only the eval comparison passes it. The served graph never does | Human Q2(a); R5, R7, R11; `06` §2 (only `core/llm` imports SDKs) |
| D16 | **Timeline access (read-only, no claim needed).**<br>• A new dependency, `get_any_conversation(conversation_id)` in `app/api/v1/staff.py`, returns the conversation or `404 not_found`. Roles are agent and admin, from the `/staff` router.<br>• It is used **only** by `GET /staff/conversations/{id}/timeline`. The list route has no `{id}`.<br>• `/messages` and `/stream` keep `get_claimed_conversation`.<br>• `test_r13_routes.py` allows exactly that one path with `get_any_conversation`, and every other claimed-prefix path still needs `get_claimed_conversation`.<br>• `04` §3 is amended | Human Q3(a); R13; ADR-025 |
| D17 | **Masked data only.** Turn text comes from `app.messages.content_masked`, never `content`. Event payloads are returned as recorded (structural only, `04` §6). No chain-of-thought, and no LLM `input_text` or `output_json` | Human Q3(a); ADR-024; R5 spirit for staff views |
| D18 | **Outcome is computed at query time**, re-implemented in `app/domains/audit/`, which can't import `eval/`. The precedence matches `eval/harness/checks.py::outcome()`:<br>1. Any `app.handoffs` row → `handoff:<queue of the latest>`.<br>2. Otherwise, the last `reply_sent.payload.route == "abstain"` → `abstained`.<br>3. Otherwise, the last turn's `nlu_result.status == "ambiguous"`, or its `reply_sent.payload.ui_kinds` contains `card_picker` → `clarified`. This is the server-side stand-in for the harness's `pending` `.card_hint` / `.block_kind` check: `block_kind` asks already come from an `ambiguous` NLU status.<br>4. Otherwise → `resolved`.<br>A conversation with no `reply_sent` has outcome `null`.<br>**Amended (T7 follow-up): the handoff wins.** Any handoff gives `handoff:<queue>` and `escalated = true`, even with no `reply_sent`. The outcome is `null` only when the conversation has neither a handoff nor a `reply_sent`. `bot_text_masked` comes only from `role = "bot"` messages; agent and system messages are not shown as bot text | Human Q5(a); `05` §3 label vocabulary; human decision at T7 |
| D19 | **Filter meanings.** They are ANDed; newest first; `limit` 1-200 (default 50) and `offset`; `total` counts every match.<br>• `language`: `app.conversations.language`.<br>• `country`: a read-only SQL join on `bank.customers.country`, mapped with `customers.service`'s `México→MX / Colombia→CO / Argentina→AR`. The customers repository is not imported (`06` §2).<br>• `intent`: any `nlu_result` in the conversation whose `payload.intents` contains it.<br>• `outcome`: D18. The value `handoff` matches every `handoff:<queue>`.<br>• `escalation`: `none` (no handoff), `any`, or a queue name.<br>• `date_from` / `date_to`: inclusive UTC dates on `app.conversations.created_at`.<br>**Amended (plan Q1):** `app.conversations` has no `created_at` column. The date filters use `app.conversations.started_at`, and the API's `created_at` field is filled from it, with no migration.<br>**Amended (T10):** the filters are typed. `language` is `es\|pt` and `country` is `MX\|CO\|AR`. `outcome` is `resolved\|clarified\|abstained\|handoff[:<queue>]`: `handoff` matches every queue, and `handoff:<queue>` matches one. `limit` is 1-200 and `offset` ≥ 0. `intent` and `escalation` are free strings. Any other value is `422` | ADR-024 filter list; assumption 1 (stood); human plan Q1; human decision at T10 |
| D20 | **Langfuse link:** `<LANGFUSE_HOST>/trace/<langfuse_trace_id>`, taken from the turn's `audit.llm_calls` rows (`audit_events.langfuse_trace_id` is always NULL). It is `null` when `LANGFUSE_HOST` is unset or no call carries a trace id | Assumption 2 (stood); ADR-006 (Langfuse local only) |
| D21 | **`GET /staff/system`** (agent, admin), everything read from code or config:<br>• `git_sha`: `Settings.git_sha`, from the `GIT_SHA` env, default `"unknown"`. **Amended (T1b):** the real SHA is passed as a build arg. The Makefile sets `GIT_SHA ?= $(shell git rev-parse --short=10 HEAD)` and exports it (the env or `.env` wins). `docker-compose.base.yml` passes backend `build.args.GIT_SHA: ${GIT_SHA:-unknown}`, and the Dockerfile turns `ARG GIT_SHA` into `ENV GIT_SHA`;<br>• `app_env`, `llm_provider`, `llm_disabled`;<br>• for each served step (`nlu`, `compose`, `handoff_summary`): model_id, temperature and prompt version;<br>• the policy bundle hash (`get_policies().hash`) and each `policies/*.yaml` file's sha256 | Human Q6(a) |
| D22 | **Persona catalog and credentials (admin only).**<br>• Both routes sit on a new router with `require_role("admin")` + `require_csrf` (R13).<br>• `eval/personas.yaml` is baked into the backend image at `/app/eval/personas.yaml` through a compose `additional_contexts` entry. Dev bind-mounts the same file read-only. The path is set by `PERSONAS_PATH`.<br>• `GET /staff/personas` returns each persona's id, split, traits and notes.<br>• `GET /staff/personas/{customer_id}/credentials` answers only for catalog personas (`404` otherwise). It recomputes the password with `generate_password(customer_id, seed=settings.credentials_seed)` and reads the document type and number from `bank.customers` through a new `customers.service` function. `data/secrets/credentials.csv` is never read. The response carries `Cache-Control: no-store`, and neither value is ever logged.<br>**Amended (T8):** the catalog has **42** personas (the plan's 52 was a plan error).<br>**Amended (2026-09-30, verification, human decision):** the path parameter is renamed from `{customer_id}` to `{persona_id}`, giving `GET /staff/personas/{persona_id}/credentials`. The value (the catalog persona's id) and the behavior are unchanged. Why: the R1 route guard (`test_r1_routes.py`) rejects any route that takes a `customer_id` path parameter, since `customer_id` comes only from the session | Human Q6(a); human decision at T8; assumption 5 (stood); `01` §Identity "admin-only persona lookup"; `04` §3; R10 |
| D23 | **A1 owns the API schemas** (`app/domains/audit/schemas.py`, still stdlib + pydantic only) and runs `make client`. B3 builds the screens against the generated client, and A1 ships no frontend | Assumption 4 (stood); `07` B3 |
| D24 | **Every test uses a fake LLM or no LLM.** The only live calls are the D2 proof, stated before it runs | `CLAUDE.md` development flow; standing rule |

## Contracts

### HTTP (all under `/api/v1`, amend `04` §3)

| Method & path | Role | Dependency | Response |
|---|---|---|---|
| `GET /staff/conversations?language=&country=&intent=&outcome=&escalation=&date_from=&date_to=&limit=&offset=` | agent, admin | router only | `ConversationPage{total, items: [ConversationSummary]}`; an invalid filter value is `422` |
| `GET /staff/conversations/{id}/timeline` | agent, admin | `get_any_conversation` | `ConversationTimeline`; `404 not_found` |
| `GET /staff/system` | agent, admin | router only | `SystemInfo` |
| `GET /staff/personas` | admin | admin router | `[PersonaEntry]` |
| `GET /staff/personas/{persona_id}/credentials` (D22, amended) | admin | admin router | `PersonaCredentials`; `404 not_found` if the id isn't in the catalog; `Cache-Control: no-store` |

### Schemas (`app/domains/audit/schemas.py`, except where noted)

```python
Outcome = Literal["resolved", "clarified", "abstained"] | str   # "handoff:<queue>"

class ConversationSummary(BaseModel):
    conversation_id: UUID; created_at: datetime   # from app.conversations.started_at (D19 amended)
    language: Literal["es", "pt"] | None
    country: Literal["MX", "CO", "AR"] | None; intents: list[str]   # distinct, first-seen order
    outcome: str | None; escalated: bool; queue: str | None
    mode: str; status: str; turns: int

class ConversationPage(BaseModel):
    total: int; items: list[ConversationSummary]

class LLMCallView(BaseModel):
    step: str; model_id: str; prompt_version: str; temperature: float | None
    attempt: int; status: str; latency_ms: float
    input_tokens: int | None; output_tokens: int | None; cost_usd: float | None

class TimelineEvent(BaseModel):
    at: datetime; type: AuditType; actor: str
    payload: dict[str, JsonValue]; sources: list[str]

class TurnTimeline(BaseModel):
    turn_id: UUID; started_at: datetime
    customer_text_masked: str | None; bot_text_masked: str | None   # bot text: role="bot" messages only (D18 amended)
    nlu: dict[str, JsonValue] | None           # the turn's nlu_result payload
    rules: list[TimelineEvent]; tools: list[TimelineEvent]   # rule_hit; tool_call + tool_result
    events: list[TimelineEvent]                # every audit event of the turn, in order
    sources: list[str]                         # union, first-seen order
    policy_version: str | None
    llm_calls: list[LLMCallView]
    latency_ms: float | None                   # reply_sent.at - customer message created_at
    cost_usd: float | None                     # sum of llm_calls.cost_usd; None if none priced
    langfuse_url: str | None                   # D20

class ConversationTimeline(BaseModel):
    conversation: ConversationSummary; turns: list[TurnTimeline]

class SystemInfo(BaseModel):
    git_sha: str; app_env: str; llm_provider: str; llm_disabled: bool
    steps: list[StepInfo]        # {step, model_id, temperature, prompt_version}
    policy_hash: str; policies: list[PolicyFileInfo]   # {file, sha256}

# app/domains/identity/schemas.py (or a new personas module in identity)
class PersonaEntry(BaseModel):
    customer_id: str; split: Literal["dev", "heldout"] | None
    traits: dict[str, JsonValue]; notes: str | None
class PersonaCredentials(BaseModel):
    customer_id: str; document_type: str; document_number: str; password: str
```

A turn is the set of `app.messages` and `audit.audit_events` rows that share a `turn_id`. Agent-relay turns appear with `actor = agent:<id>` events only.

### Backend internals

- `app/api/v1/staff.py`: `get_any_conversation(conversation_id) -> ConversationRow` (`404 not_found` when it is missing). Exported next to `get_claimed_conversation`.
- `app/core/llm/client.py`: `get_llm_client(settings=None, sink=None, *, model_overrides: Mapping[Step, str] | None = None)`. `build_chat_model` and the ledger's `model_id` use the override when one is present. Pricing falls back to the existing per-model table.
- `app/core/config.py`: `personas_path: Path = Path("/app/eval/personas.yaml")`, `git_sha: str = "unknown"`. `LANGFUSE_HOST` is read from the existing setting.
- `backend/Dockerfile`: `ARG GIT_SHA` → `ENV GIT_SHA`, and `COPY --from=eval personas.yaml /app/eval/personas.yaml`. `docker/docker-compose.base.yml` backend has `build.additional_contexts: {eval: ../eval}` and `build.args.GIT_SHA: ${GIT_SHA:-unknown}`. The `Makefile` sets `GIT_SHA ?= $(shell git rev-parse --short=10 HEAD)` and exports it (D21, amended). `docker/docker-compose.dev.yml` adds `../eval/personas.yaml:/app/eval/personas.yaml:ro`.

### Eval harness

- `make eval SUITE= SYSTEM= [CASES=] [DRIVER=] [RUNS=1] [NLU=off|smoke|suite]` → `python -m eval.harness … --runs N --nlu off|smoke|suite`. `NLU` defaults to `off`.
- `--suite heldout` refuses (exit 2, one-line reason) unless `heldout.lock` exists and `freeze.check` passes (D3).
- Output folder: `eval/reports/<suite>-<sha10>[-k]/` containing `report.md`, `metrics.json` (`{"runs": {"proposed": [..], "baseline": [..]}, "aggregate": {...}, "nlu": {...}}`), `meta.json`, `results.jsonl` and `llm_calls.jsonl`.
- `meta.json` adds `runs`, `clone_strategy: "FILE_COPY"`, `clone_seconds: float` (one clone), `resets: int`, `reset_diffs: 0`, `dirty: bool`, and `nlu: {source, n, models}`. It keeps `git_sha`, `suite_hash`, `policy_hash`, `models`, `provider`, `restore_count` and `pii_hits`.
- `make eval-pii-check RUN=<folder name>` works on the new folder.

### Docs amended by this card

- `04` §3: the rows above, and the `get_any_conversation` exception in the Staff paragraph.
- `05` §4: the isolation sentence (D10).
- `05` §7: the held-out command, its preconditions (D3) and the new folder layout (D6).
- `decision-log.md`: a "Model per step (D7)" entry, **Proposed** (D14).
- `07` §8: the D7 row points to that entry.

## Touch map

```
backend/app/api/v1/staff.py                 list, timeline, system routes; get_any_conversation
backend/app/api/v1/staff_admin.py           new: admin router, personas + credentials
backend/app/api/v1/__init__.py              register staff_admin router
backend/app/domains/audit/schemas.py        D23 schemas
backend/app/domains/audit/timeline.py       new: list query, filters, outcome (D18), turn assembly
backend/app/domains/audit/repository.py     read queries for events, llm_calls by conversation
backend/app/domains/customers/service.py    document type + number for one customer_id
backend/app/domains/identity/personas.py    new: catalog loader (PERSONAS_PATH), credentials via generate_password
backend/app/core/llm/client.py              model_overrides seam (D15)
backend/app/core/config.py                  personas_path, git_sha
backend/Dockerfile, docker/docker-compose.base.yml (additional_contexts, build.args.GIT_SHA), docker/docker-compose.dev.yml
backend/tests/unit/test_r13_routes.py       amended (D16, admin router)
backend/tests/integration/test_staff_timeline.py   new
eval/harness/{__main__,runner,clone,report,metrics}.py   RUNS, one clone, resets, aggregate, labels, heldout guard
eval/harness/nlu_eval.py                    new: D12 derivation, D13 metrics, in-memory sink
eval/tests/test_aggregate.py, eval/tests/test_nlu_eval.py   new
Makefile                                    RUNS, NLU on `eval`; exported GIT_SHA (D21)
frontend/src/client/                        regenerated by `make client` only
docs/solution-docs/{04-contracts,05-evaluation-plan,07-execution-plan,decision-log}.md
```

Read only: `eval/scenarios/**` (every `heldout` path included), `eval/driver/`, `eval/simulator/`, `eval/nlu/nlu_v1_smoke.yaml`, `eval/personas.yaml`.

## Test list

Four tests. They use a fake LLM or no LLM, and each task runs only its own tests.

1. **`backend/tests/unit/test_r13_routes.py` (amended), R13.** Every new route declares its role at the router level. `/staff/personas*` needs `admin`. Exactly `/staff/conversations/{conversation_id}/timeline` depends on `get_any_conversation`, and every other `/staff/conversations/{conversation_id}/…` path still depends on `get_claimed_conversation`. It fails if the timeline loses its dependency or another claimed route switches to it.
2. **`backend/tests/integration/test_staff_timeline.py::test_filter_counts_match_sql`, A1 Done-when.**
   - Seed: ephemeral DB with 7 conversations covering es/pt, MX/CO/AR, 2 intents, each D18 outcome, a handoff, and 2 dates. The 7th has a handoff but no `reply_sent`, and its outcome must be `handoff:<queue>` (D18, amended). The date filters are checked against `started_at` (D19, amended).
   - For each filter alone and one combination, `total` equals a hand-written SQL count over the same tables.
   - The timeline of one conversation returns its turns in order, with `customer_text_masked` equal to `content_masked` (not `content`), and `llm_calls` and `cost_usd` taken from the seeded ledger.
3. **`eval/tests/test_aggregate.py::test_proposed_runs_aggregate`, A2 report numbers.** Three fake per-run metric dicts plus one baseline dict give the per-run values, the mean, the min–max and an unchanged baseline column in `metrics.json` and the `report.md` table.
4. **`eval/tests/test_nlu_eval.py::test_derive_and_score`, A2 NLU comparison.**
   - Derivation from a tmp scenario dir takes the first `say` turn with the seed's intents.
   - Macro P/R/F1 and exact-set match are correct on a hand-computed 4-utterance fixture: keyword predictions vs a fake `run_nlu`, with one multi-intent item.

There is no ES/PT flow test: this card adds no flow. The D2 live run is the runnable proof of the A2 Done-when line.

## Boundaries

- **Always:**
  - Return only masked text and structural payloads from staff routes.
  - Keep `test_r13_routes.py` strict.
  - Before any live LLM run, state the call count (D2: about 60) and get the human's go-ahead.
  - Label every report number (D7).
  - Keep the per-case restore and diff.
- **Ask first:**
  - Starting the stack (`make up`) for the D2 proof or the FILE_COPY measurement (the stack is down at the human's request).
  - Any live call beyond the D2 subset.
  - Changing `demo_reset.py`.
  - A migration.
  - Any change to the `get_claimed_conversation` routes.
- **Never:**
  - Create, edit or delete anything under `eval/scenarios/heldout/`, `eval/scenarios/_staging/heldout/` or `eval/scenarios/heldout.lock`.
  - Run `make eval-freeze`.
  - Run any `SUITE=heldout` eval, or read held-out failures to tune anything (R9).
  - Return `app.messages.content`, LLM `input_text` or `output_json` from a staff route.
  - Read `data/secrets/credentials.csv` from the backend.
  - Log a document number or password.
  - Import an LLM SDK outside `app.core.llm`.

## Success criteria

1. `cd backend && uv run pytest tests/unit/test_r13_routes.py -q` passes. Pointing the timeline route at no ownership dependency makes it fail.
2. `cd backend && uv run pytest tests/integration/test_staff_timeline.py -q` passes. Every filter's `total` equals its SQL count (A1 Done-when).
3. `uv run --project backend pytest eval/tests/test_aggregate.py eval/tests/test_nlu_eval.py -q` passes.
4. `make eval SUITE=dev SYSTEM=both RUNS=3 CASES=a- NLU=smoke` exits 0 and writes `eval/reports/dev-<sha10>/report.md`, which contains:
   - proposed runs 1-3 with the mean and min–max, and a baseline column;
   - `language_variant` and segment breakdowns;
   - error analysis by category × check;
   - an NLU table for keyword, `claude-sonnet-5-5` and `claude-haiku-4-5-20251001` (with status accuracy);
   - the ADR-028 caveat, a label on every table, and the judge section reading "pending D7-B4" while `eval/judges/agreement.md` is absent, or linking to it once it exists (D9, amended).

   Its `meta.json` shows `clone_strategy: "FILE_COPY"`, exactly one `clone_seconds`, `restore_count` equal to the number of runs (4 for `SYSTEM=both RUNS=3`: 3 proposed + 1 baseline), `resets` equal to runs × distinct personas in the selected cases (20 for the `a-` subset's 5 personas), `reset_diffs: 0` and `pii_hits: 0`. `llm_calls.jsonl` has at most about 80 rows.
   **Amended (2026-09-30, human decision after T13):** this criterion used to expect `resets: 4`. `resets` counts persona restores, as the harness implements it, and the harness is unchanged.
5. `make eval SUITE=heldout SYSTEM=proposed` exits 2 with the freeze-precondition message and makes no LLM call or clone.
6. The plan state file records one measured FILE_COPY `clone_seconds` on the dev host (D11). Recorded: 489.5 s cold (T6); 59.5 s warm in the proof run (T13).
7. `04` §3, `05` §4 and §7, `decision-log.md` ("Model per step (D7)", Proposed) and `07` §8 D7 are amended as listed in Contracts.
8. `make check` is green, including import-linter. `make client` has been run, and the generated client includes the new schemas.
9. `git diff develop --stat -- eval/scenarios/heldout eval/scenarios/_staging/heldout eval/scenarios/heldout.lock` is empty.

## Open questions

- **Final model per step:** decided by the human from the held-out NLU comparison, after the freeze and the D1.5 targets. Until then the decision-log entry stays Proposed (D14).
- **The held-out run itself:** the human triggers it (D3). Its report closes `07` D7 end-of-day step 4 and the A2 Done-when as written.
- **FILE_COPY in `demo_reset.py`:** undecided, and out of scope (D1). The D11 measurement gives the human the number to decide on.
- **The Langfuse URL path** (`/trace/<id>`) is checked against the running local Langfuse version by the implementer. If it differs, the project-scoped path is used and D20 is amended.

### Resolved

- **What `resets` counts in `meta.json`** (found at T13; **resolved 2026-09-30 by the human**): success criterion 4 is amended and the harness is unchanged. `restore_count` equals the number of runs, `resets` equals runs × suite personas, and `reset_diffs` is 0.
