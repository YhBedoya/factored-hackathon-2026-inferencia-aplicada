# 05 — Evaluation plan

## 1. Why every test utterance is team-generated

The dataset can't provide intent labels. `call_transcripts.customer_text` has 42 distinct strings, `detected_intents` has a single value, and `complaints.description` has 5 templates tied 1:1 to their category. The eval suite is therefore **team-generated and labeled as such** (B2). The dataset supplies personas, records and expected DB state.

## 2. Suites

| Suite | Size (target) | Used for | Frozen |
|---|---|---|---|
| `eval/scenarios/dev/` | ~80 conversations | Prompt and flow tuning, debugging | No |
| `eval/scenarios/heldout/` | **~150 conversations** (about 10 per category, split across ES and PT) | Reported results only | **Yes**, hash committed before tuning starts |
| `eval/nlu/` | Single-turn utterances derived from the same seeds and split the same way | NLU accuracy vs keyword baseline | Held-out part frozen |

**Held-out mix (target):**
- By language: ~50% ES (MX/CO/AR evenly), ~35% PT-BR, ~15% portuñol / code-switching.
- By category (each category covered in both ES and PT):

| Category | Examples | Req |
|---|---|---|
| Normal resolution | Block, status, balance/min payment, decline code, search, replacement | S3a |
| Ambiguous | "bloquear" (lock vs block), several cards with no hint, vague dates | S3b, D2.2 |
| Unsupported / out-of-market | Pix, boleto, mortgages, investment advice | S3b |
| Human required | Bank-side block unlock, fraud triage, regulator mention, priority claim, explicit human request | S3c |
| Incorrect / missing data | Card not found, no matching transaction, null income, orphan records | D5.2a |
| Expired session | Token expires mid-flow, then resume | D5.2b |
| Unauthorized access | Another customer's card number or document | D5.2c |
| Prompt injection | Direct, plus **via data fields** (a seeded `merchant_name` / complaint text carrying instructions in the eval DB clone) | D5.2d |
| Tool failures | Fault flags: Bedrock timeout, write error, read-back mismatch | D5.2e |
| Multilingual ambiguity | Portuñol, mid-conversation switches, voseo, regional terms | D5.2f |

## 3. Creating and labeling cases (D4.7, D4.8)

1. The team writes **seed scenarios** per intent × variant × category: persona, goal, fact sheet, expected labels.
2. A **different Bedrock model family** than the system under test generates paraphrases and regional variants of each seed.
3. Humans review **100% of held-out cases** and a sample of dev. Reviewer and date are recorded per case.
4. **Split by seed** (grouped): every paraphrase of a seed stays on the same side, and personas are not shared between dev and held-out.

**Labels per case:** `expected_intents`, `expected_outcome` (`resolved`, `clarified`, `abstained`, `handoff:<queue>`), `required_tools`, `forbidden_tools`, `expected_db_state` (assertions on the clone), `required_handoff_fields`, `expected_language`, `eligible_for_automation` (bool).

## 4. Systems compared on the same workload (E1)

| System | Description |
|---|---|
| **Baseline** | Keyword/regex intent router (with the regional lexicon) + the same tools, policy engine and flows + fixed ES/PT template replies. It isolates the value of the LLM layer. Multi-intent messages: clause split at connectors and punctuation, per-clause match, precedence rules and a negation window (ADR-005) |
| **Proposed** | Full system (LLM NLU + flows + answer node + composer) |
| Operational reference | Call-center figures from the data (FCR `was_resolved`, handle time, `was_escalated`, `sla_breached`) for card-related contact reasons. Labeled as **historical synthetic data, not comparable 1:1** |
| Learned component | The pretrained LLM NLU vs the keyword router on `eval/nlu/` held-out (ADR-005), plus a model-selection comparison between Bedrock models. The trained intent classifier (ADR-032) is compared with the keyword router and the LLM NLU (Ref) on the dev items, with run records and the report in `ml/intent/runs/<run_id>/nlu_classifier.md` |

Each run starts from a clone whose suite personas are verified equal to golden. One `FILE_COPY` clone of the golden DB is created per `make eval` invocation and reused by every run of every system; before each run the runner restores and verifies every persona in the selected cases, and any diff aborts the run. Runs record the git SHA, model IDs, prompt versions, policy hash and suite hash (E2).

## 5. Driving and judging

- **Multi-turn driver:** a goal-driven **LLM customer simulator** (temperature 0, different model family, chosen when the harness is built) plays the persona with its fact sheet: which card, which charge, how to answer confirmations and OTPs. Stop conditions: goal reached, handoff, abstention, or 12 turns. A sample of simulator transcripts is hand-checked for persona adherence.
- **Deterministic checks first:** tools called / forbidden, final DB state, policy compliance (confirmation before action, read-back before "done"), handoff packet completeness, reply language, grounding (every number in the reply comes from facts), no raw PII in LLM inputs.
- **LLM judge** (reply quality only: grounding, tone, clarity, correct register) with a written rubric in `eval/judges/rubric.md`. It is validated against **~50 human-labeled cases**, and agreement (Cohen's κ / % agreement) is reported (E4).
- **Repeated runs:** the held-out suite runs 3× for the proposed system, and variability is reported (E2).

## 6. Metrics (E5–E11)

| Metric | Definition | Denominator |
|---|---|---|
| Safe automated resolution (E5) | Eligible case reaches the correct, policy-compliant outcome with no human | **All in-scope cases**, plus the share where automation was attempted |
| Containment (E6) | Case ends without transfer (never presented as success on its own) | All cases |
| Escalation quality (E7) | Correct transfers (right queue + complete packet); **missed** and **unnecessary** transfers | Confusion matrix against `expected_outcome` |
| Unsafe outcomes (E8) | Unauthorized disclosure/action, materially incorrect outcome, "done" without verification | Counts / n, with a 95% upper bound (rule of three when 0 observed) |
| Clarification accuracy | Asked when required; not asked when not required | Ambiguous vs clear cases |
| NLU accuracy | Intent-set precision/recall/F1 (macro), exact-set match, status accuracy; multi-intent cases reported as their own slice | `eval/nlu/` held-out |
| Latency (E9) | End-to-end p50/p95 per turn and per conversation | All turns |
| Cost (E9) | Per attempted case and per **successful** automated resolution (Bedrock tokens × price table + fixed infra share, assumptions stated); "not defined" if 0 successes | As stated |

**Targets (D1.5):** these metrics are the intended customer and business outcomes. Their numeric targets are set after the first dev eval run and recorded before the held-out suite is frozen.

All rates carry n and a Wilson 95% CI. Breakdowns are **by language** (ES-MX, ES-CO, ES-AR, PT-BR, mixed) and **by segment** (Premium/Plus/Basic/Student), with small-sample caveats and a disparity investigation (E10). Every number is labeled **offline evaluation**, **simulation** or **projection** (E11).

## 7. Reports

The held-out run is one command a human triggers: `make eval SUITE=heldout SYSTEM=both RUNS=3 NLU=suite`. `RUNS=N` repeats only the proposed system; the baseline runs once because it is deterministic. It has three human preconditions:

1. Both humans review 100% of `_staging/heldout/`.
2. A human runs `make eval-freeze`.
3. The D1.5 targets are recorded in §6.

The harness refuses `--suite heldout` unless `eval/scenarios/heldout.lock` exists and the freeze check passes.

Each invocation writes one folder, `eval/reports/<suite>-<sha10>/` (`sha10` is HEAD's short SHA; a repeat gets `-2`, `-3`, and so on), containing `results.jsonl`, `llm_calls.jsonl`, `metrics.json`, `meta.json` and `report.md` (tables above, failures, error analysis by category, links to the Langfuse traces). Only `report.md`, `metrics.json` and `meta.json` may be committed; `results.jsonl` and `llm_calls.jsonl` stay git-ignored. For the held-out suite, failure lines show only the `case_id` and the failed check names, never transcript text (R9). The staff console scorecard (Stretch) reads the same metrics.
