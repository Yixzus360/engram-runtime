# Five-model scientific harness smoke test

Run date: 2026-09-19  
Task: `state-storage`  
Reasoning effort: `high`  
Design: one randomized Engram OFF/ON pair per model

This is an end-to-end instrumentation check. It has one task and one repetition,
so it is not a general effectiveness result.

| Model | Condition | Complete | Input | Cached | Uncached | Output | Reasoning | Seconds | Tools | API equiv. USD |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-5.5 | baseline | yes | 64,137 | 40,064 | 24,073 | 766 | 278 | 36.489 | 3 | 0.163377 |
| gpt-5.5 | engram | yes | 76,390 | 57,856 | 18,534 | 659 | 210 | 35.339 | 3 | 0.141368 |
| gpt-5.6-luna | baseline | yes | 78,903 | 64,512 | 14,391 | 665 | 79 | 36.544 | 3 | 0.004966 |
| gpt-5.6-luna | engram | yes | 93,627 | 79,616 | 14,011 | 857 | 275 | 40.625 | 3 | 0.005423 |
| gpt-5.6-terra | baseline | yes | 129,663 | 108,032 | 21,631 | 1,029 | 165 | 56.334 | 5 | 0.077216 |
| gpt-5.6-terra | engram | yes | 79,646 | 67,584 | 12,062 | 546 | 114 | 29.530 | 2 | 0.044193 |
| gpt-5.6-sol | baseline | yes | 42,639 | 30,336 | 12,303 | 372 | 72 | 21.549 | 1 | 0.068786 |
| gpt-5.6-sol | engram | yes | 81,106 | 69,120 | 11,986 | 515 | 81 | 45.995 | 2 | 0.085892 |
| gpt-6-astra | baseline | yes | 59,093 | 50,432 | 8,661 | 229 | 0 | 28.496 | 2 | 0.148492 |
| gpt-6-astra | engram | yes | 81,251 | 69,888 | 11,363 | 300 | 0 | 29.283 | 2 | 0.198518 |

## Aggregate paired result

| Metric | Baseline | Engram | Change |
| --- | ---: | ---: | ---: |
| Completed tasks | 5/5 | 5/5 | 0 |
| Input tokens | 374,435 | 412,020 | +10.0% |
| Cached input tokens | 293,376 | 344,064 | +17.3% |
| Uncached input tokens | 81,059 | 67,956 | -16.2% |
| Output tokens | 3,061 | 2,877 | -6.0% |
| Reasoning output tokens | 594 | 680 | +14.5% |
| Wall time | 179.412 s | 180.772 s | +0.8% |
| Tool calls | 14 | 12 | -14.3% |
| API list-price equivalent | $0.462838 | $0.475394 | +2.7% |

The primary paired completion difference is 0.000 with a bootstrap 95% CI of
0.000 to 0.000 and an exact McNemar p-value of 1.000. For uncached input, the
mean paired delta is -2,620.6 tokens, but its bootstrap 95% CI runs from
-6,912.6 to +878.0. No effectiveness claim follows from this smoke test.

`API list-price equivalent` applies the versioned standard token prices. These
runs used Codex subscription access, so the actual billed amount per run is not
observable and remains unknown.
