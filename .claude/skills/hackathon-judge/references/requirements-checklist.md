# Requirements Checklist

Every requirement in the official documents, split into atomic, checkable items. Each item has an ID for citation, its source, the **evidence a judge would expect to see**, and typical **weak answers** that look like coverage but aren't.

- `PS §…` = official problem statement (`official-problem-statement.md`)
- `KO s…` = kickoff deck slide (`kickoff-and-submission.md`)
- **[HARD]** = a stated prohibition or a "must" whose violation is a blocker, not just a lower score.

## Contents
- S — Scope & mandatory scenarios
- P — Design principles ("think beyond the demo")
- D1 — Problem supported by data
- D2 — Functioning AI system
- D3 — Controlled automation
- D4 — Sound data & ML practice
- D5 — Measured quality & failure handling
- D6 — Credible route to operation
- B — Data & execution boundaries
- E — Evaluation evidence & metrics
- K — Submission deliverables & judging criteria
- N — Explicitly NOT required

---

## S — Scope & mandatory scenarios

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| S1 | One coherent, focused workflow (e.g., account/payment inquiries, card support, dispute intake, credit info & eligibility) | PS Scope; KO s10 | A named workflow with clear in-scope / out-of-scope intents | "We handle all banking questions"; several shallow workflows (no bonus for more) |
| S2 | Working end-to-end prototype, deployed | PS Scope; KO s18, s20 | Live URL, runnable repo, demo video showing real flows | Mockups, notebooks only, happy-path-only demo |
| S3a | **Normal resolution path** | PS Scope; KO s11 | A case resolved automatically, grounded in verified records, policy-compliant | Resolution based on LLM free text with no data lookup |
| S3b | **Ambiguous or unsupported request** → clarification or abstention | PS Scope; KO s11 | Clarifying question on missing parameters; safe refusal on unsupported requests | Model guesses; generic "I can't help" with no routing |
| S3c | **Case requiring human intervention** → structured handoff | PS Scope; KO s11 | Handoff packet (see D3.5), triggered by explicit rules | Dumping the transcript; "an agent will contact you" with no packet |
| S4 | **Spanish AND Portuguese** interactions demonstrated | PS Scope; KO s10 | Recorded/tested flows in both languages, incl. S3a–c ideally in both | Spanish only; "the LLM speaks Portuguese" with no tests |
| S5 | Report limitations in supplied data and language coverage | PS Scope; KO s15 | Explicit section: no Portuguese in data, synthetic data, label quality, etc. | Silence on limitations |
| S6 | Honest account of the work required before deployment | PS Scope; KO s15 | "Remaining work" list: security review, capacity, compliance, etc. | Claiming it's production-ready |

## P — Design principles ("think beyond the demo")

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| P1 | Design for privacy, explainability, fairness, reliability, scalability | PS intro | A design note per property with concrete mechanisms | Buzzwords without mechanisms |
| P2 | Explicit trade-offs across autonomy, accuracy, latency, cost, human oversight | PS intro | Documented decisions, e.g., "we require confirmation for X, costing Y latency, because Z" | No trade-offs stated; "maximize everything" |
| P3 | Justify where AI is appropriate vs. deterministic logic; how quality & safety are evaluated | PS intro; KO s11 ("AI should not be autonomous just because it can be") | A component map: which steps are LLM, which are rules/code, and why | LLM does everything, including permission checks and calculations |

## D1 — A problem supported by data

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D1.1 | Analyze contact reasons | PS §1 | Distribution of `contact_reason` / `reason_category`, complaint categories | Choosing the workflow by intuition |
| D1.2 | Analyze relevant demand patterns | PS §1; KO s14 | Volume over time, by channel/country/hour, wait times, FCR, escalation rates | A single total count |
| D1.3 | Analyze data quality | PS §1 | Dup/null/orphan/late-arrival rates measured on the real files | Assuming the data is clean |
| D1.4 | Analyze operational constraints | PS §1 | Agent capacity, SLAs (`sla_breached`), handle time, languages agents speak | Not considered |
| D1.5 | Use evidence to prioritize the workflow and define intended customer and business outcomes | PS §1; KO s13 ("justify workflow selection using reproducible logs") | Reproducible notebook/SQL → "we chose X because it is N% of contacts, low FCR, high cost"; target outcomes defined | Outcomes not defined; analysis not reproducible |
| D1.6 | Establish a baseline | PS intro; KO s12 | A baseline metric/system (current process or simple model) to compare against | No baseline |

## D2 — A functioning AI system

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D2.1 | Maintain relevant conversational context | PS §2; KO s11 | Multi-turn demo using prior turns correctly | Single-turn Q&A |
| D2.2 | Clarify ambiguity | PS §2; KO s11 | Explicit ambiguity detection → clarifying question | Silent guessing |
| D2.3 | Ground factual responses in permitted account, transaction, or policy information | PS §2; KO s13 ("ground all responses in verified records") | Every factual claim traceable to a record/policy source, with citations in logs | LLM answers from its own knowledge; RAG over unrelated docs |
| D2.4 | Use tools when they serve the workflow | PS §2 | Tools with typed contracts, called only when needed | Tool count as a goal |
| D2.5 | Report only actions whose outcomes the system has verified | PS §2; KO s11 ("verify that actions actually happened") | Post-action read-back/confirmation before telling the user "done" | "I've blocked your card" based on the model's intent, not the tool result |

## D3 — Controlled automation

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D3.1 | Define which requests the system can answer | PS §3 | Written scope/intent list | Implicit |
| D3.2 | Define which actions require confirmation | PS §3 | Confirmation step enforced in code for side-effecting actions | Prompt says "ask before acting" |
| D3.3 | Define when it must abstain or transfer to a human | PS §3; KO s11 | Explicit escalation rules (thresholds, intents, risk flags) | "The LLM decides when to escalate" with no rules or evaluation |
| D3.4 **[HARD]** | Enforce permissions and policy **outside model-generated prose** | PS §3; KO s13 | Authorization/policy checks in the service/tool layer; model cannot bypass | Permission rules only in the system prompt |
| D3.5 | Human handoff includes: request, verified facts, actions taken, supporting evidence, unresolved questions | PS §3; KO s11, s14 ("structured JSON handoffs", "without dumping raw transcripts") | A structured (e.g., JSON) handoff schema with all five fields, shown in the demo | Raw transcript forwarding; free-text summary missing fields |

## D4 — Sound data & ML practice

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D4.1 | Repeatable data preparation | PS §4; KO s12 ("deterministic pipeline execution") | Scripted pipeline (not manual notebook steps), same input → same output | One-off notebook |
| D4.2 | Data contracts | PS §4; KO s12 ("strict input schema enforcement") | Schema definitions validated on ingest (types, nullability, enums, keys) | None |
| D4.3 | Quality checks | PS §4 | Dedup, null, FK orphan, range checks with reported results | Silently dropping rows |
| D4.4 | Lineage | PS §4 | Traceable raw → clean → feature/serving tables | None |
| D4.5 | Update/freshness policy; if only static data, update correctness shown with a clearly labeled test fixture | PS §4, Architecture freedom | Incremental load handling late arrivals & schema evolution, demonstrated with a fixture | Full reload only, no freshness story |
| D4.6 | Evaluate **at least one learned component against an appropriate baseline** | PS §4; KO s12 | E.g., intent classifier vs. keyword/majority baseline; retriever vs. BM25 | No learned component evaluated; LLM compared to nothing |
| D4.7 | Valid labels or relevance judgments | PS §4; KO s12 | Label source stated and quality-checked (sample manually audited) | Using `detected_*` fields as ground truth unchecked |
| D4.8 | Prevent leakage | PS §4; KO s12 | Grouped/time-based splits; no outcome fields as features | Random row split; same customer in train & test |
| D4.9 | Justify representations, metrics, thresholds, evaluation splits | PS §4; KO s12 | Written rationale for each | Default choices with no reasoning |
| D4.10 | Error analysis (esp. for pretrained/retrieval solutions); component selection justified | PS Architecture freedom; KO s20 ("model selection, optimization, implementation and tracking") | Failure categories with examples; experiment tracking | Aggregate score only |

## D5 — Measured quality & failure handling

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D5.1 | Evaluate on held-out cases | PS §5 | A frozen held-out test set not used for prompt tuning | Evaluating on the dev examples |
| D5.2a | Incorrect or missing data | PS §5 | Test cases + expected behavior | — |
| D5.2b | Expired sessions | PS §5 | Test cases | — |
| D5.2c | Unauthorized access attempts | PS §5 | Test cases (e.g., asking about another customer's account) | — |
| D5.2d | Prompt injection | PS §5; KO s13 | Adversarial test cases, incl. injection via data fields (e.g., complaint text) | Only direct "ignore instructions" prompts |
| D5.2e | Tool failures | PS §5; KO s15 | Simulated timeouts/errors → safe behavior | — |
| D5.2f | Multilingual ambiguity | PS §5 | Mixed ES/PT, code-switching, regional terms | — |
| D5.3 | Report successful outcomes, unsafe outcomes, handoff behavior, latency, cost — with sample sizes and limitations | PS §5 | Results table with n per category | Percentages without n |

## D6 — Credible route to operation

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| D6.1 | Tracing | PS §6; KO s15 | Per-request traces (LLM calls, tool calls, decisions) | print logs |
| D6.2 | Bounded retries | PS §6; KO s15 | Retry limits with backoff in code | Infinite/unbounded retries |
| D6.3 | Safe fallback | PS §6; KO s15 | Defined degraded mode → handoff | Crash or hallucinated answer |
| D6.4 | Reproducible setup | PS §6; KO s13, s15 | One-command setup, pinned versions, seeds, env template; scripted data download from the organizers' S3 bucket with credentials from env | "Works on my machine"; manual download steps; data files committed |
| D6.5 | Explain capacity limits, monitoring, access controls, data retention, remaining deployment work | PS §6; KO s15 | Written ops section covering all five | Missing any |
| D6.6 | Explanations based on sources, policy rules, execution records — **not hidden chain-of-thought** | PS §6; KO s13 ("audit execution logs") | Audit log: inputs, sources, rule hits, tool results, outputs | Showing model reasoning text as the audit trail |

## B — Data & execution boundaries

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| B1 **[HARD]** | Only organizer-approved data and permitted external resources | PS Boundaries | Data sources listed | Scraped external bank data |
| B2 | Label each input as real, de-identified, synthetic, or team-generated; follow data-use terms | PS Boundaries | Data provenance table (LATAM Bank = synthetic; Portuguese cases & policies = team-generated) | Unlabeled mix |
| B3 **[HARD]** | No private customer records, credentials, or restricted data in public submissions or external model requests | PS Boundaries | Secrets out of repo (S3 dataset keys and LLM API keys read from env/profile; `.env` gitignored); PII minimization/masking before LLM calls | API keys in repo; the official data-dictionary PDF (it contains the S3 keys) committed to the public repo; full customer rows sent to an LLM |
| B4 | Mock/sandbox banking tools OK if contracts and limitations documented | PS Boundaries | Tool contracts (inputs, outputs, errors, limits) documented | Undocumented mocks |
| B5 **[HARD]** | Authentication via trusted test session or identity service; **national ID or customer number alone does not prove identity** | PS Boundaries | Session token / mock IdP / OTP flow; session expiry | "Tell me your customer ID" as authentication |
| B6 **[HARD]** | Access to each customer's records and action permissions enforced in the service or tool layer | PS Boundaries; KO s14 ("customer record isolation") | Tools scoped to the authenticated customer server-side | Model is trusted to only query the right customer |
| B7a **[HARD]** (credit workflows) | Separate conversation handling, predictive risk estimates, eligibility policy | PS Boundaries | Three distinct components | One LLM prompt doing all three |
| B7b **[HARD]** (credit) | Approved rules or clearly labeled synthetic policy service produce a *simulated* eligibility outcome; model must not invent rules or approve credit | PS Boundaries | Deterministic policy service, labeled synthetic | LLM decides eligibility |
| B7c (credit) | Explanations, uncertainty, review paths for missing data or borderline cases | PS Boundaries | Reason codes, confidence, human review route | Binary yes/no |
| B8 **[HARD]** | No live lending decisions or money movement | PS Boundaries | All actions simulated/sandboxed | Real payment APIs |

## E — Evaluation evidence & metrics

| ID | Requirement | Source | Evidence expected | Weak answers |
|---|---|---|---|---|
| E1 | Baseline vs. proposed system **on the same held-out workload** | PS Evaluation; KO s12 | Side-by-side table on identical cases | Different test sets; no baseline |
| E2 | Report number & mix of cases, label quality, model and prompt versions, repeated-run variability | PS Evaluation | Metadata block in results; multiple runs for LLM components | Single run, unversioned prompts |
| E3 | Include failures in results | PS Evaluation | Failure examples shown | Cherry-picked successes |
| E4 | If an LLM judges answers: document rubric; validate a sample vs. human or deterministic judgments | PS Evaluation | Rubric + agreement rate on a human-labeled sample | Unvalidated LLM-as-judge |
| E5 | **Safe automated resolution** rate over *all in-scope* test cases + share of cases where automation was attempted | PS Evaluation; KO s12 | Both numbers, with denominators | Rate computed only over attempted cases |
| E6 | **Containment** reported but not treated as proof of success | PS Evaluation | Containment shown alongside correctness | Containment as the headline success metric |
| E7 | **Escalation quality**: correct transfers with useful context; missed and unnecessary transfers | PS Evaluation | Confusion-matrix-style handoff table | Only "escalation rate" |
| E8 | **Unsafe outcomes** (unauthorized disclosures/actions, materially incorrect outcomes) with counts and denominators; zero observed ≠ zero risk | PS Evaluation; KO s12 | "0/120 (95% CI upper bound ≈ 2.5%)"-style reporting | "0 unsafe outcomes, fully safe" |
| E9 | **Operating efficiency**: p50/p95 end-to-end latency; cost per attempted case AND per successful automated resolution; state workload, sample size, cost assumptions; "not defined" when no successes | PS Evaluation; KO s12, s14 ("cost-per-resolution ROI") | All of these, with assumptions | Mean latency only; token cost without per-resolution cost |
| E10 | Compare outcomes by **language** and **authorized customer segments**; small-sample caveats; investigate disparities | PS Evaluation | ES vs PT breakdown; segment breakdown; disparity discussion | Single aggregate |
| E11 | Label offline measurements, simulations, and projected business savings separately; never present offline comparison as measured production improvement | PS Evaluation | Labels on every number | "Our system reduces costs by 40%" from an offline sim |

## K — Submission deliverables & judging criteria

| ID | Requirement | Source |
|---|---|---|
| K1 | Public GitHub repo named `factored-hackathon-2026-[team name]` | KO s18 |
| K2 | Link to deployed tool | KO s18 |
| K3 | 4–6 slide presentation | KO s18 |
| K4 | Short **mandatory** video pitch: working solution + core architectural decisions | KO s18 |
| K5 | Send to hackathon.admin@factored.ai; submit no matter what | KO s18 |
| K6 | Judged on: **it works (first and foremost)**; AI Engineering (backend, frontend, deployment); rationale & documentation; Data Engineering (extraction & transformation); ML (model selection, optimization, implementation, tracking); Data Analytics (data quality & insights). No published weights. | KO s20 |

## N — Explicitly NOT required (don't penalize their absence)

Training a new model · multiple agents · a tool-count target · streaming · demand forecasting · a dashboard (PS Architecture freedom). Incremental file delivery does not by itself require streaming. Operating a live banking service is not expected. More workflows do not earn a bonus.

Building these anyway is fine only if they serve the workflow; if they consume time that the mandatory items needed, a judge counts that as poor prioritization.
