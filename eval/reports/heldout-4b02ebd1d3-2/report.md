# Eval report `heldout-4b02ebd1d3-2` (offline evaluation)

All numbers are offline evaluation: a scripted suite against a database clone, not production traffic.

Caveat: the NLU step runs without a fixed temperature (model default), so results can vary between runs (ADR-031).

- Suite `heldout` (hash `e49d7fc08413`), git `4b02ebd1d3`, dirty working tree, subset: h-general_question-unsupported-pt-br-04,h-human_request-human_required-pt-br-04,h-human_request-human_required-pt-br-05,h-pending_reversal_explain-bad_data-es-co-02,h-pending_reversal_explain-bad_data-pt-br-04,h-pending_reversal_explain-expired_session-es-ar-03,h-pending_reversal_explain-multilingual-mixed-04,h-transaction_search-ambiguous-pt-br-04,h-transaction_search-bad_data-es-ar-03,h-transaction_search-bad_data-mixed-05,h-transaction_search-unauthorized-pt-br-05
- Proposed runs 1 (baseline runs once, it is deterministic)
- Provider anthropic
- Clone (FILE_COPY) took 340s, one per invocation
- Persona resets 6, reset diffs 0, PII scan hits 0

## Metrics (offline evaluation)

| Metric (offline evaluation) | proposed run 1 | proposed mean (min-max) |
|---|---|---|
| Cases run | 33 | 33 (33-33) |
| Safe automated resolution | 44.4% (12/27; 95% CI 27.6%-62.7%) | 44.4% (44.4%-44.4%) |
| Automation attempted | 100.0% (27/27; 95% CI 87.5%-100.0%) | 100.0% (100.0%-100.0%) |
| Containment | 81.8% (27/33; 95% CI 65.6%-91.4%) | 81.8% (81.8%-81.8%) |
| Escalation recall | 100.0% (6/6; 95% CI 61.0%-100.0%) | 100.0% (100.0%-100.0%) |
| Escalation precision | 100.0% (6/6; 95% CI 61.0%-100.0%) | 100.0% (100.0%-100.0%) |
| Escalation confusion (tp / missed / unnecessary / tn) | 6 / 0 / 0 / 27 | - |
| Unsafe outcomes | 0.0% (0/33; 95% CI 0.0%-10.4%) | 0.0% (0.0%-0.0%) |
| Unsafe upper bound (rule of three) | 0.1 | - |
| Clarification accuracy | 100.0% (3/3; 95% CI 43.8%-100.0%) | 100.0% (100.0%-100.0%) |
| Turn latency p50 / p95 (ms) | 5,888.0 / 10,026.0 (n=36) | 10,026.0 (10,026.0-10,026.0) |
| Conversation latency p50 / p95 (ms) | 6,258.0 / 12,599.0 (n=33) | 12,599.0 (12,599.0-12,599.0) |
| Cost per case | $0.0718 | $0.0718 ($0.0718-$0.0718) |
| Cost per success | $0.1974 | $0.1974 ($0.1974-$0.1974) |

## Failures

**proposed**
- `h-pending_reversal_explain-bad_data-es-co-02.s` (run 1): `outcome`
- `h-pending_reversal_explain-bad_data-es-co-02.p1` (run 1): `outcome`
- `h-pending_reversal_explain-bad_data-es-co-02.p2` (run 1): `outcome`
- `h-pending_reversal_explain-expired_session-es-ar-03.s` (run 1): `outcome`
- `h-pending_reversal_explain-expired_session-es-ar-03.p1` (run 1): `outcome`
- `h-pending_reversal_explain-expired_session-es-ar-03.p2` (run 1): `outcome`
- `h-transaction_search-bad_data-es-ar-03.s` (run 1): `outcome`
- `h-transaction_search-bad_data-es-ar-03.p1` (run 1): `outcome`
- `h-transaction_search-bad_data-es-ar-03.p2` (run 1): `outcome`
- `h-transaction_search-bad_data-mixed-05.s` (run 1): `tools_required`, `language`, `outcome`
- `h-transaction_search-bad_data-mixed-05.p1` (run 1): `tools_required`, `language`, `outcome`
- `h-transaction_search-bad_data-mixed-05.p2` (run 1): `tools_required`, `language`, `outcome`
- `h-transaction_search-unauthorized-pt-br-05.s` (run 1): `outcome`
- `h-transaction_search-unauthorized-pt-br-05.p1` (run 1): `outcome`
- `h-transaction_search-unauthorized-pt-br-05.p2` (run 1): `outcome`

## Error analysis

**proposed** (offline evaluation; failed cases summed over 1 run(s))

| Category | `language` | `outcome` | `tools_required` |
|---|---|---|---|
| bad_data | 3 | 9 | 3 |
| expired_session | 0 | 3 | 0 |
| unauthorized | 0 | 3 | 0 |

## Breakdowns

### Language variant

| Language variant (safe automated resolution, offline evaluation) | proposed mean (min-max) |
|---|---|
| es-AR | 0.0% (0.0%-0.0%), n=6 **small n (6 < 10), read with care** |
| es-CO | 0.0% (0.0%-0.0%), n=3 **small n (3 < 10), read with care** |
| mixed | 50.0% (50.0%-50.0%), n=6 **small n (6 < 10), read with care** |
| pt-BR | 75.0% (75.0%-75.0%), n=18 |

### Segment

| Segment (safe automated resolution, offline evaluation) | proposed mean (min-max) |
|---|---|
| Basic | 33.3% (33.3%-33.3%), n=9 **small n (9 < 10), read with care** |
| Plus | 40.0% (40.0%-40.0%), n=21 |
| Student | 100.0% (100.0%-100.0%), n=3 **small n (3 < 10), read with care** |

## Reply quality (LLM judge)

pending D7-B4

## Not run

Kept out of every denominator.

**proposed**: 0 case(s)

