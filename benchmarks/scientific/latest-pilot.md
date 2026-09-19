# Five-model paired pilot result

Run completed: 2026-09-20  
Design: 5 models x 5 tasks x 5 repetitions x 2 conditions  
Sample: 125 complete Engram OFF/ON pairs; 250 executions  
Reasoning effort: `high`  
Infrastructure failures included in analysis: 0

Runner commit: `14fd08315f7706dc41823921098ec5d4410fb9cf`  
Locked study digest: `a8bae98721a8d1635f1b00ec783729889998d609a2aec4c7a35002f0ecb876df`

This is the completed preregistered internal instrumentation pilot. It measures
the five repository tasks named in the locked protocol. It is stronger than the
earlier smoke test, but it is not evidence that Engram generalizes to external
tasks. LongMemEval-V2 is the next external validation stage.

## Primary endpoint

| Condition | Completed | Completion rate |
| --- | ---: | ---: |
| Engram OFF | 110/125 | 88.0% |
| Engram ON | 125/125 | 100.0% |

The paired completion difference was **+12.0 percentage points** for Engram
(bootstrap 95% CI **+6.4 to +17.6 points**). There were 15 Engram-only
successes and zero baseline-only successes. The two-sided exact McNemar
p-value was **0.000061**.

## Aggregate efficiency

| Metric | Engram OFF | Engram ON | Change |
| --- | ---: | ---: | ---: |
| Input tokens | 11,921,466 | 11,869,346 | -0.4% |
| Cached input tokens | 10,438,784 | 10,650,880 | +2.0% |
| Uncached input tokens | 1,482,682 | 1,218,466 | -17.8% |
| Output tokens | 113,148 | 89,896 | -20.6% |
| Reasoning output tokens | 26,081 | 22,197 | -14.9% |
| Wall time | 5,582.920 s | 4,767.226 s | -14.6% |
| Tool calls | 482 | 364 | -24.5% |
| API list-price equivalent | $12.609254 | $11.411918 | -9.5% |

The paired mean reduction in uncached input was 2,113.728 tokens per run
(bootstrap 95% CI 657.085 to 3,578.438 fewer; sign-flip p=0.006270). Output,
wall time, and tool-call intervals also excluded zero. The API-equivalent cost
interval narrowly included zero (Engram minus baseline: -$0.019030 to
+$0.000027 per pair; p=0.051219), so the cost result is directionally favorable
but does not pass the preregistered 0.05 threshold.

## Completion by model

| Model | Engram OFF | Engram ON |
| --- | ---: | ---: |
| GPT-5.5 | 20/25 | 25/25 |
| GPT-5.6 Luna | 20/25 | 25/25 |
| GPT-5.6 Terra | 22/25 | 25/25 |
| GPT-5.6 Sol | 23/25 | 25/25 |
| GPT-6 Astra | 25/25 | 25/25 |

The completion gain came entirely from the `action-safety` task: baseline
completed 10/25 and Engram completed 25/25. The other four tasks were 25/25 in
both conditions. This concentration is a central limitation and is why the
result cannot establish generalization by itself.

## Interpretation boundary

The result supports the claim that, on this frozen internal task set, Engram
improved completion and reduced several resource measures under paired
conditions. It does not yet support a general claim about arbitrary agents,
models, or workloads. That claim requires external tasks, starting with the
pinned official LongMemEval-V2 evaluation, and broader unique-task coverage.

`API list-price equivalent` applies the committed pricing manifest. The runs
used Codex subscription access, so actual per-run billing is unavailable and
must not be inferred from that estimate.
