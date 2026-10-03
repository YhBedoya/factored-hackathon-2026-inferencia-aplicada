# Eval report `dev-db8b7c5706` (offline evaluation)

All numbers are offline evaluation: a scripted suite against a database clone, not production traffic.

Caveat: the NLU step runs without a fixed temperature (model default), so results can vary between runs (ADR-031).

- Suite `dev` (hash `c0ff56af8315`), git `db8b7c5706`, dirty working tree, subset: d-card_block-tool_failure-es-co-01,a-card_status-normal_resolution-es-co-01,d-pending_reversal_explain-normal_resolution-pt-br-01,d-decline_explain-normal_resolution-pt-br-01
- Proposed runs 1 (baseline runs once, it is deterministic)
- Provider anthropic
- Clone (FILE_COPY) took 309s, one per invocation
- Persona resets 4, reset diffs 0, PII scan hits 0

## Metrics (offline evaluation)

| Metric (offline evaluation) | proposed run 1 | proposed mean (min-max) |
|---|---|---|
| Cases run | 8 | 8 (8-8) |
| Safe automated resolution | 0.0% (0/8; 95% CI 0.0%-32.4%) | 0.0% (0.0%-0.0%) |
| Automation attempted | 0.0% (0/8; 95% CI 0.0%-32.4%) | 0.0% (0.0%-0.0%) |
| Containment | 0.0% (0/8; 95% CI 0.0%-32.4%) | 0.0% (0.0%-0.0%) |
| Escalation recall | not defined (n=0) | not defined |
| Escalation precision | 0.0% (0/8; 95% CI 0.0%-32.4%) | 0.0% (0.0%-0.0%) |
| Escalation confusion (tp / missed / unnecessary / tn) | 0 / 0 / 8 / 0 | - |
| Unsafe outcomes | 0.0% (0/8; 95% CI 0.0%-32.4%) | 0.0% (0.0%-0.0%) |
| Unsafe upper bound (rule of three) | 0.4 | - |
| Clarification accuracy | 0.0% (0/3; 95% CI 0.0%-56.2%) | 0.0% (0.0%-0.0%) |
| Turn latency p50 / p95 (ms) | 2,081.0 / 2,556.0 (n=8) | 2,556.0 (2,556.0-2,556.0) |
| Conversation latency p50 / p95 (ms) | 2,081.0 / 2,556.0 (n=8) | 2,556.0 (2,556.0-2,556.0) |
| Cost per case | not defined | not defined |
| Cost per success | not defined | not defined |

## Failures

**proposed**
- `outcome`: 8 case(s), example `a-card_status-normal_resolution-es-co-01.s`
- `tools_required`: 8 case(s), example `a-card_status-normal_resolution-es-co-01.s`

## Error analysis

**proposed** (offline evaluation; failed cases summed over 1 run(s))

| Category | `outcome` | `tools_required` |
|---|---|---|
| normal_resolution | 5 | 5 |
| tool_failure | 3 | 3 |

## Breakdowns

### Language variant

| Language variant (safe automated resolution, offline evaluation) | proposed mean (min-max) |
|---|---|
| es-CO | 0.0% (0.0%-0.0%), n=4 **small n (4 < 10), read with care** |
| pt-BR | 0.0% (0.0%-0.0%), n=4 **small n (4 < 10), read with care** |

### Segment

| Segment (safe automated resolution, offline evaluation) | proposed mean (min-max) |
|---|---|
| Basic | 0.0% (0.0%-0.0%), n=6 **small n (6 < 10), read with care** |
| Plus | 0.0% (0.0%-0.0%), n=1 **small n (1 < 10), read with care** |
| Premium | 0.0% (0.0%-0.0%), n=1 **small n (1 < 10), read with care** |

## Reply quality (LLM judge)

pending D7-B4

## Not run

Kept out of every denominator.

**proposed**: 0 case(s)

