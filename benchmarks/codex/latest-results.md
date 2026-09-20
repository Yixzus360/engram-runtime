# Codex + Engram paired result

Date: 2026-09-19  
Model: `gpt-5.6-luna`  
Reasoning effort: `low`  
Runs: one independent baseline and one independent Engram run for each of five tasks

| Task | Mode | Input | Cached | Uncached | Output | Seconds | Tools | Score |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| State storage | Baseline | 64,466 | 49,408 | 15,058 | 539 | 30.720 | 2 | 3/3 |
| State storage | Engram | 72,267 | 68,608 | 3,659 | 523 | 31.293 | 2 | 3/3 |
| Model routing | Baseline | 78,109 | 71,680 | 6,429 | 488 | 41.732 | 3 | 3/3 |
| Model routing | Engram | 91,105 | 79,616 | 11,489 | 514 | 39.126 | 3 | 3/3 |
| Procedure verification | Baseline | 110,470 | 91,904 | 18,566 | 698 | 58.700 | 4 | 3/3 |
| Procedure verification | Engram | 72,939 | 61,440 | 11,499 | 494 | 37.104 | 2 | 3/3 |
| Action safety | Baseline | 84,947 | 68,608 | 16,339 | 1,080 | 62.570 | 3 | 2/3 |
| Action safety | Engram | 98,187 | 89,856 | 8,331 | 810 | 41.796 | 3 | 3/3 |
| Context savings | Baseline | 96,083 | 88,832 | 7,251 | 658 | 44.118 | 4 | 3/3 |
| Context savings | Engram | 74,840 | 61,440 | 13,400 | 469 | 37.777 | 2 | 3/3 |

## Aggregate

| Metric | Baseline | Engram | Change |
| --- | ---: | ---: | ---: |
| Input tokens | 434,075 | 409,338 | -5.7% |
| Cached input tokens | 370,432 | 360,960 | -2.6% |
| Uncached input tokens | 63,643 | 48,378 | -24.0% |
| Output tokens | 3,463 | 2,810 | -18.9% |
| Elapsed inference time | 237.840 s | 187.096 s | -21.3% |
| Tool calls | 16 | 12 | -25.0% |
| Expected-answer terms | 14/15 | 15/15 | +1 term |

Local memory seeding took 12.151 seconds and is reported separately. With that
one-time cost included, the Engram condition remained 38.593 seconds faster in
this run.

This is a single initial sample. It demonstrates the evaluation path and gives
evidence for these tasks; it does not establish a general savings rate. Simple
lookups sometimes consumed more total input with MCP. The largest gains came
from questions where the recalled signal reduced repository exploration.
