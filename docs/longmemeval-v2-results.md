# LongMemEval-V2 controlled replication

Completed: 2026-09-20

Official repository commit: `2cc8c540bdb87fe6761629b585e727e1c4704520`

Official dataset revision: `f152293e235517d504809563c833d7190b8c713b`

## Result

Engram improved objective accuracy over no retrieval from **0/295 to 59/295
(20.0%)**. The paired difference is **+20.0 percentage points**, with a 95%
bootstrap interval of **+15.6 to +24.7 points** and an exact two-sided McNemar
`p = 3.47e-18`. Engram gained 59 objective questions and lost none.

Conventional RAG remained more accurate: **100/295 (33.9%)** on the objective
subset. Engram trailed it by 13.9 points, but used **91.2% fewer reader prompt
tokens**, **27.4% fewer reader completion tokens**, and **39.0% less condition
wall time**. This is evidence that Engram supplies useful memory with a much
smaller context than this RAG baseline; it is not evidence that Engram has
surpassed conventional RAG on retrieval quality.

This is a local controlled replication on the official LongMemEval-V2 small
dataset and grader prompts. The custom OpenCode OAuth reader and judge make it
separate from an official leaderboard submission.

## Primary objective scores

The preregistered claim policy treats deterministic graders as primary. LLM
judgments are reported separately and cannot override the objective result.

| Condition | Correct | Accuracy | Difference vs OFF |
| --- | ---: | ---: | ---: |
| OFF: `no_retrieval` | 0/295 | 0.0% | — |
| ON: `engram_runtime` | 59/295 | 20.0% | +20.0 pp |
| RAG: `rag_query_to_slice` | 100/295 | 33.9% | +33.9 pp |

The paired ON-minus-RAG objective difference was **−13.9 points** (95%
bootstrap interval −19.7 to −8.1; exact McNemar `p = 5.66e-6`). Engram gained
20 questions against RAG and lost 61.

## Secondary scores

| Subset | OFF | Engram ON | Conventional RAG |
| --- | ---: | ---: | ---: |
| LLM judged | 4/156 (2.6%) | 17/156 (10.9%) | 67/156 (42.9%) |
| All questions | 4/451 (0.9%) | 76/451 (16.9%) | 167/451 (37.0%) |

Across all 451 questions, Engram improved over OFF by **+16.0 points** (95%
bootstrap interval +12.4 to +19.5), with 74 gains and two losses. The LLM judge
was GPT-5.5 medium through OpenCode ChatGPT OAuth and differed from the answer
reader.

## Results by domain

| Domain | Questions | OFF | Engram ON | Conventional RAG |
| --- | ---: | ---: | ---: | ---: |
| Web | 240 | 1.7% | 23.3% | 40.4% |
| Enterprise | 211 | 0.0% | 9.5% | 33.2% |

Engram improved over OFF in both domains. Its combined-score gain was +21.7
points on web and +9.5 points on enterprise. The enterprise result shows that
the memory benefit survived the harder domain, while also exposing the largest
remaining quality gap against RAG.

## Efficiency

| Condition | Reader prompt tokens | Reader completion tokens | Condition wall time |
| --- | ---: | ---: | ---: |
| OFF | 1,615,194 | 4,317 | 1.07 h |
| Engram ON | 3,249,583 | 5,507 | 1.37 h |
| Conventional RAG | 37,058,883 | 7,590 | 2.24 h |

OFF has no retrieved memory, so it is not a valid baseline for a memory-context
savings claim. The efficiency claim compares Engram with the conventional RAG
condition, which solved more questions but sent about 11.4 times as many reader
prompt tokens.

## Protocol and validation

- Dataset: official `small` tier, 451 questions: 240 web and 211 enterprise.
- Conditions: OFF=`no_retrieval`, RAG=`rag_query_to_slice`,
  ON=`engram_runtime`.
- Reader: GPT-6 Astra, reasoning variant `low`, through OpenCode ChatGPT OAuth.
- Judge: GPT-5.5, reasoning variant `medium`, through OpenCode ChatGPT OAuth.
- Conventional RAG embeddings: local `Qwen/Qwen3-Embedding-8B`.
- Reader concurrency: two for every condition.
- Completed responses: exactly 1,353 across six complete runs.
- Grading: exactly 885 deterministic scores and 468 settled OAuth judgments.
- Cost reported by OpenCode: US$0 in direct API charges.
- One historical OAuth-limit failure was retained in the ledger and excluded;
  its partial condition was archived and rerun completely.

The complete matrix took 4.67 condition-hours after protocol gates, excluding
dataset preparation, smoke tests, the OAuth-limit pause, and earlier discarded
reader experiments. The full data preparation and protocol amendments are
recorded in the [execution preflight](../benchmarks/scientific/longmemeval-v2-preflight.md).

## Claim boundary

The result supports three narrow conclusions for this fixed reader, dataset
revision, and implementation:

1. Engram materially improves long-memory accuracy over no retrieval.
2. Engram delivers that improvement with far less reader context than the
   conventional RAG comparator.
3. Conventional RAG is still substantially more accurate, especially on the
   enterprise domain.

The study does not establish universal agent performance, official
LongMemEval-V2 leaderboard standing, or superiority over RAG. Broader claims
require other readers, seeds, memory suites, and agent benchmarks.

## Reproduce the analysis

The raw execution directory is intentionally gitignored because it contains
large benchmark artifacts. The committed analyzer validates every expected
count, transport, model setting, and complete-run telemetry before writing the
sanitized result.

```powershell
$env:PYTHONPATH = (Get-Location).Path
$env:ENGRAM_LONGMEMEVAL_DATA_ROOT = "C:\path\to\prepared-longmemeval-v2"
uv run python benchmarks/adapters/run_longmemeval_v2_matrix.py
uv run python benchmarks/adapters/analyze_longmemeval_v2.py `
  --artifact-root artifacts\official\LongMemEval-V2\opencode-astra-study
```

The matrix runner resumes only complete conditions and fails closed when it
finds partial output, preventing different attempts from being mixed.

The machine-readable result is
[`benchmarks/scientific/longmemeval-v2-results.json`](../benchmarks/scientific/longmemeval-v2-results.json).
