# LongMemEval-V2 execution preflight

Prepared: 2026-09-20  
Official repository commit: `2cc8c540bdb87fe6761629b585e727e1c4704520`  
Official dataset revision: `f152293e235517d504809563c833d7190b8c713b`

## Data validation

The complete official dataset was downloaded, its screenshot archives were
extracted, and the official validator passed the small tier with screenshot
checks enabled.

| Item | Count or size |
| --- | ---: |
| Questions | 451 |
| Web questions | 240 |
| Enterprise questions | 211 |
| Trajectories | 1,870 |
| Questions with image input | 29 |
| Downloaded source | 7.12 GB |
| Prepared local footprint | 19.53 GB |
| Prepared screenshot trajectory directories | 1,913 |

## Controlled comparison

The fixed plan runs the official small tier three times over both domains:

- Engram OFF is explicitly the official `no_retrieval` memory method.
- Conventional RAG uses the official `rag_query_to_slice` method as a secondary
  retrieval baseline.
- Engram ON uses `engram_runtime`.
- All conditions use the same `gpt-6-astra` reader at the `low` reasoning
  variant through OpenCode and ChatGPT OAuth. Each question gets a fresh
  OpenCode session; prompts travel through stdin, tool calls are rejected,
  autocompaction is disabled, and there are no hidden retries.
- OpenCode adds a fixed client system prompt and the OAuth transport differs
  from the benchmark's ordinary API reader, so this is recorded as a separate
  frontier-reader replication rather than an official leaderboard submission.
- All conditions use `gpt-5.5` at reasoning `medium` through OpenCode and
  ChatGPT OAuth for question types that require an LLM judge. The 885
  deterministic scores are unchanged. The 468 judge calls use a distinct model
  from the Astra answer reader and persist their token usage and session IDs.

This produces 1,353 reader calls. Of the 1,353 scored answers, 885 use
deterministic graders and 468 require the OpenAI evaluator: 128 abstention and
28 gotcha questions in each condition.

### Protocol amendment after the smoke gate

The initial plan enabled reader thinking. The first matched smoke exposed a
runtime failure in the conventional RAG condition: the reader consumed the
fixed 20,000-token completion allowance without emitting a final boxed answer.
That single RAG question took 73.3 minutes, including 64.8 minutes of first-use
embedding work and 8.2 minutes of reader generation. Continuing unchanged
would both create invalid answers and miss the 24-hour execution target.

On 2026-09-20 the user authorized disabling reader thinking. The revision is
applied identically to `no_retrieval`, `rag_query_to_slice`, and
`engram_runtime`; no scored full-study run had started and evaluator spend was
$0. Before the full study, all three deterministic smoke tests must be repeated
and must produce a parseable final answer. The pre-amendment smoke artifacts
remain preserved as evidence for the decision.

The repeated no-thinking smoke still failed in the Qwen RAG condition: it used
the full 20,000-token output allowance without a boxed answer and took 577.3
seconds. The user then authorized using OpenCode with a non-Qwen frontier
model. The answer reader was changed, before any full-study result existed, to
`gpt-6-astra` at reasoning `low`. The local Qwen3-Embedding-8B model remains
only as the frozen vector encoder for the conventional RAG comparator.

Matched integral smokes passed for OFF, RAG, and Engram ON. Astra generation
took 9.69, 11.40, and 7.84 seconds respectively. The RAG case included 164,384
prompt tokens and five images. A second gate completed four OFF questions with
two concurrent readers in 20.8 seconds, and concurrency two also passed for RAG
and Engram. The same concurrency and prompt-worker count are fixed across all
three conditions.

## Local requirements

The host has an RTX 3090 with 24 GB VRAM and approximately 913 GB free under
WSL2. Astra runs remotely through OpenCode, so the GPU is available for
Engram's local encoder and the conventional RAG embedding endpoint. The local
Qwen answer-reader experiments remain preserved but are no longer part of the
full matrix.

OpenCode reported USD 0 for the Astra OAuth smoke calls. Those calls still
consume ChatGPT account usage and can encounter subscription limits. The
observed reader and local retrieval timings support a planning range of four to
six hours with concurrency two; five hours is the target, not a guaranteed
deadline, because provider throttling and the 468 GPT evaluator calls remain
variable.

## Evaluator transport and cost

The original preflight reserved up to US$30 for 468 GPT-5.2 API judge calls.
Before the full study reached scoring, the run was stopped with zero evaluator
calls and zero evaluator spend. The user authorized replacing that paid route
with a subscription-backed judge.

The replacement smoke used the official abstention grader path with GPT-5.5
medium through OpenCode OAuth. It completed in 9.84 seconds, recorded 10,010
input tokens, 40 output tokens, 22 reasoning tokens, and reported US$0. The
wrapper disables hidden retries and records each OAuth judge call in a
persistent JSONL ledger. OAuth calls can still consume ChatGPT subscription
usage or hit account limits, but they do not use the OpenAI API key or the
former US$30 budget.

Evaluator OAuth usage is reported separately from reader OAuth usage and local
execution. Reader wall time and tokens, memory indexing time, embedding work,
retrieval time, and memory-context tokens remain separate operational
measurements.

Pricing source: https://developers.openai.com/api/docs/models/gpt-5.2

## Completed execution

The controlled matrix finished on 2026-09-20 with all six conditions complete:
1,353 reader responses, 885 deterministic evaluations, and 468 settled OAuth
judge records. OpenCode reported US$0 of direct API cost. One historical OAuth
limit failure remains in the audit ledger but its three partial scored rows are
excluded; that condition was archived and rerun from the beginning.

The objective primary result was 59/295 (20.0%) for Engram ON versus 0/295 for
OFF, a paired difference of +20.0 percentage points (95% bootstrap interval
+15.6 to +24.7; exact McNemar `p = 3.47e-18`). Conventional RAG reached
100/295 (33.9%). Engram therefore demonstrated a real memory benefit over OFF
and a 91.2% reader-prompt reduction versus RAG, while remaining less accurate
than RAG. See the [full result](../../docs/longmemeval-v2-results.md) and the
[machine-readable analysis](longmemeval-v2-results.json).
