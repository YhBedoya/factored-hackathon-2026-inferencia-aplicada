# Eval report `dev-c64dd67067` (offline evaluation)

All numbers are offline evaluation: a scripted suite against a database clone, not production traffic.

Caveat: the NLU step runs without a fixed temperature (model default), so results can vary between runs (ADR-031).

- Suite `dev` (hash `e5baebd7ad15`), git `c64dd67067`, dirty working tree, subset: a-
- Proposed runs 3 (baseline runs once, it is deterministic)
- Provider anthropic
- Clone (FILE_COPY) took 60s, one per invocation
- Persona resets 20, reset diffs 0, PII scan hits 0

## Metrics (offline evaluation)

| Metric (offline evaluation) | proposed run 1 | proposed run 2 | proposed run 3 | proposed mean (min-max) | baseline |
|---|---|---|---|---|---|
| Cases run | 5 | 5 | 5 | 5 (5-5) | 5 |
| Safe automated resolution | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (100.0%-100.0%) | 75.0% (3/4; 95% CI 30.1%-95.4%) |
| Automation attempted | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (4/4; 95% CI 51.0%-100.0%) | 100.0% (100.0%-100.0%) | 100.0% (4/4; 95% CI 51.0%-100.0%) |
| Containment | 80.0% (4/5; 95% CI 37.6%-96.4%) | 80.0% (4/5; 95% CI 37.6%-96.4%) | 80.0% (4/5; 95% CI 37.6%-96.4%) | 80.0% (80.0%-80.0%) | 100.0% (5/5; 95% CI 56.6%-100.0%) |
| Escalation recall | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (100.0%-100.0%) | 0.0% (0/1; 95% CI 0.0%-79.3%) |
| Escalation precision | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (1/1; 95% CI 20.7%-100.0%) | 100.0% (100.0%-100.0%) | not defined (n=0) |
| Escalation confusion (tp / missed / unnecessary / tn) | 1 / 0 / 0 / 4 | 1 / 0 / 0 / 4 | 1 / 0 / 0 / 4 | - | 0 / 1 / 0 / 4 |
| Unsafe outcomes | 0.0% (0/5; 95% CI 0.0%-43.4%) | 0.0% (0/5; 95% CI 0.0%-43.4%) | 0.0% (0/5; 95% CI 0.0%-43.4%) | 0.0% (0.0%-0.0%) | 20.0% (1/5; 95% CI 3.6%-62.4%) |
| Unsafe upper bound (rule of three) | 0.6 | 0.6 | 0.6 | - | not defined |
| Clarification accuracy | not defined (n=0) | not defined (n=0) | not defined (n=0) | not defined | not defined (n=0) |
| Turn latency p50 / p95 (ms) | 1,912.0 / 4,258.0 (n=7) | 1,414.0 / 3,548.0 (n=7) | 1,449.0 / 3,732.0 (n=7) | 3,846.0 (3,548.0-4,258.0) | 86.0 / 118.0 (n=6) |
| Conversation latency p50 / p95 (ms) | 3,295.0 / 4,258.0 (n=5) | 2,851.0 / 3,548.0 (n=5) | 2,870.0 / 3,732.0 (n=5) | 3,846.0 (3,548.0-4,258.0) | 114.0 / 184.0 (n=5) |
| Cost per case | $0.0207 | $0.0207 | $0.0207 | $0.0207 ($0.0207-$0.0207) | not defined |
| Cost per success | $0.0259 | $0.0259 | $0.0259 | $0.0259 ($0.0259-$0.0259) | not defined |

## Failures

**baseline**
- `error`: 1 case(s), example `a-card_block-normal_resolution-es-co-01.s`
- `handoff_fields`: 1 case(s), example `a-human_request-human_required-es-ar-01.s`
- `outcome`: 1 case(s), example `a-human_request-human_required-es-ar-01.s`

## Error analysis

**proposed** (offline evaluation; failed cases summed over 3 run(s))

No failed checks.

**baseline** (offline evaluation; failed cases summed over 1 run(s))

| Category | `error` | `handoff_fields` | `outcome` |
|---|---|---|---|
| human_required | 0 | 1 | 1 |
| normal_resolution | 1 | 0 | 0 |

## Breakdowns

### Language variant

| Language variant (safe automated resolution, offline evaluation) | proposed mean (min-max) | baseline |
|---|---|---|
| es-AR | not defined, n=1 **small n (1 < 10), read with care** | not defined (n=0) **small n (1 < 10), read with care** |
| es-CO | 100.0% (100.0%-100.0%), n=1 **small n (1 < 10), read with care** | 0.0% (0/1; 95% CI 0.0%-79.3%) **small n (1 < 10), read with care** |
| es-MX | 100.0% (100.0%-100.0%), n=2 **small n (2 < 10), read with care** | 100.0% (2/2; 95% CI 34.2%-100.0%) **small n (2 < 10), read with care** |
| pt-BR | 100.0% (100.0%-100.0%), n=1 **small n (1 < 10), read with care** | 100.0% (1/1; 95% CI 20.7%-100.0%) **small n (1 < 10), read with care** |

### Segment

| Segment (safe automated resolution, offline evaluation) | proposed mean (min-max) | baseline |
|---|---|---|
| Basic | 100.0% (100.0%-100.0%), n=4 **small n (4 < 10), read with care** | 66.7% (2/3; 95% CI 20.8%-93.9%) **small n (4 < 10), read with care** |
| Plus | 100.0% (100.0%-100.0%), n=1 **small n (1 < 10), read with care** | 100.0% (1/1; 95% CI 20.7%-100.0%) **small n (1 < 10), read with care** |

## Reply quality (LLM judge)

pending D7-B4

## NLU comparison

Label: offline evaluation; smoke set, n=20.

Anthropic API; Bedrock serves the same models (ADR-028).

| System | Failed calls | Precision | Recall | F1 | Exact-set match | Multi-intent | Status acc. | p50 ms | p95 ms | Mean cost/call (USD) |
|---|---|---|---|---|---|---|---|---|---|---|
| keyword_nlu | 0 | 0.635 | 0.673 | 0.635 | 60.0% [38.7%-78.1%] (12/20) | n/a | 90.0% [69.9%-97.2%] (18/20) | n/a | n/a | n/a |
| claude-sonnet-5-5 | 0 | 1.000 | 1.000 | 1.000 | 100.0% [83.9%-100.0%] (20/20) | n/a | 100.0% [83.9%-100.0%] (20/20) | 1335 | 2904 | 0.01601 |
| claude-haiku-4-5-20251001 | 0 | 1.000 | 1.000 | 1.000 | 100.0% [83.9%-100.0%] (20/20) | n/a | 95.0% [76.4%-99.1%] (19/20) | 1424 | 2032 | 0.00620 |

Exact-set match by language variant (offline evaluation):

| System | unknown |
|---|---|
| keyword_nlu | 60.0% [38.7%-78.1%] (12/20) |
| claude-sonnet-5-5 | 100.0% [83.9%-100.0%] (20/20) |
| claude-haiku-4-5-20251001 | 100.0% [83.9%-100.0%] (20/20) |

## Not run

Kept out of every denominator.

**proposed run 1**: 0 case(s)

**proposed run 2**: 0 case(s)

**proposed run 3**: 0 case(s)

**baseline**: 0 case(s)

