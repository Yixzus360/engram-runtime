# LongMemEval-V2 equal-budget diagnostic

Completed: 2026-09-21

Preregistration commit: `ba00b2b`

Preregistered plan SHA-256:
`d6493bf090a17f911c1cb860b55d4489ff459e8e0abbd98de0dc60d699c62dd3`

## Result

Engram met the preregistered token-quality rule at the **16,384-token memory
budget**. It answered 8/30 questions correctly (26.7%) versus 6/30 (20.0%) for
conventional RAG while using 249,507 versus 322,392 observed reader prompt
tokens, a **22.6% reduction**. Correct answers per million reader prompt tokens
were 32.1 for Engram and 18.6 for RAG.

The accuracy difference was +6.7 percentage points, but its 95% paired
bootstrap interval ranged from −10.0 to +23.3 points and exact McNemar
`p = 0.727`. This 30-question development diagnostic identifies a promising
operating point; it does not establish statistical superiority.

## Equal-budget curve

| Memory cap | Engram accuracy | RAG accuracy | Engram prompt tokens | RAG prompt tokens | Correct/M prompt tokens |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 4,096 | 7/30 (23.3%) | 4/30 (13.3%) | 276,577 | 161,336 | 25.3 vs 24.8 |
| 8,192 | 8/30 (26.7%) | 4/30 (13.3%) | 240,770 | 178,472 | 33.2 vs 22.4 |
| **16,384** | **8/30 (26.7%)** | **6/30 (20.0%)** | **249,507** | **322,392** | **32.1 vs 18.6** |
| 32,768 | 8/30 (26.7%) | 9/30 (30.0%) | 221,540 | 646,327 | 36.1 vs 13.9 |

At 32,768 tokens, RAG led accuracy by one question but consumed 2.9 times as
many observed prompt tokens. Engram therefore remained about 2.6 times as
efficient by correct answers per million prompt tokens at that point.

## What the curve reveals

Engram improved from seven to eight correct answers between the 4,096 and
8,192 caps, then stayed at eight through 32,768. Its retrieved memory also
stayed at 145,647 aggregate tokens from the 8,192 cap upward. The current
six-chunk retrieval policy saturates before it can use the larger budgets.

RAG moved from four to nine correct answers as the cap increased. Its aggregate
memory context rose from 12,042 tokens at the smallest cap to 634,571 at the
largest. RAG gains accuracy by expanding raw evidence, while Engram reaches a
compact plateau.

The next engineering step is therefore not simply raising Engram's context
limit. It is adding budget-aware retrieval: query decomposition, more candidate
chunks, local reranking, and neighbor expansion only when the first evidence
set is insufficient. The 16,384 result is the target operating region for that
work.

## Domain detail

| Cap | Web Engram/RAG | Enterprise Engram/RAG |
| ---: | ---: | ---: |
| 4,096 | 26.7% / 20.0% | 20.0% / 6.7% |
| 8,192 | 26.7% / 20.0% | 26.7% / 6.7% |
| 16,384 | 26.7% / 26.7% | 26.7% / 13.3% |
| 32,768 | 26.7% / 33.3% | 26.7% / 26.7% |

## Protocol and validation

- Frozen sample: 30 objective questions, with 15 web and 15 enterprise.
- Strata per domain: five static-environment, five dynamic-environment, and
  five procedure questions.
- Conditions: `engram_runtime` and official `rag_query_to_slice`.
- Identical memory-context caps: 4,096, 8,192, 16,384, and 32,768 tokens.
- Reader: GPT-6 Astra `low` through OpenCode ChatGPT OAuth, concurrency two.
- RAG embeddings: local `Qwen/Qwen3-Embedding-8B`.
- Complete runs: 16/16; objective responses: 240/240.
- LLM judge calls: zero; direct API cost reported: US$0.
- Total condition wall time: 42.3 minutes; observed elapsed execution was about
  45 minutes.
- Observed reader use: 2,296,921 prompt tokens and 2,457 completion tokens.

The sample was selected before execution with seed `20260921`. The question
IDs, execution order, metrics, and decision rule were published before results
in the [frozen plan](../benchmarks/scientific/longmemeval-v2-budget-curve-plan.json).

## Limitations

This is one seeded subset and one reader pass per condition. Its paired
intervals are wide, and none of the accuracy differences is statistically
conclusive. It excludes abstention, gotcha, and image questions to keep every
score objective and the run inexpensive. OpenCode OAuth also reported varying
prompt-token totals for some repeated Engram prompts whose retrieved memory was
unchanged, so observed provider token counts should be confirmed in a repeated
study.

The result complements rather than replaces the completed 451-question
[controlled replication](longmemeval-v2-results.md). It supports the narrower
claim that Engram has a favorable token-quality operating point around 16k on
this frozen subset and exposes the retrieval plateau that should be improved
next.

## Reproduce the analysis

```powershell
$env:PYTHONPATH = (Get-Location).Path
uv run python -m benchmarks.adapters.analyze_longmemeval_v2_budget_curve
```

The sanitized machine-readable result is
[`benchmarks/scientific/longmemeval-v2-budget-curve-results.json`](../benchmarks/scientific/longmemeval-v2-budget-curve-results.json).
