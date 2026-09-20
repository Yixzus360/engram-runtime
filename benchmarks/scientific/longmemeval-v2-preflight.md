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

The fixed plan runs the official small tier twice over both domains:

- Engram OFF uses the official `no_retrieval` memory method.
- Engram ON uses `engram_runtime`.
- Both conditions use the same local `Qwen/Qwen3.5-9B` reader with official
  generation defaults.
- Both conditions use the same pinned `gpt-5.2-2025-12-11` evaluator for the
  question types that require an LLM judge.

This produces 902 local reader calls. Of the 902 scored answers, 590 use
deterministic graders and 312 require the OpenAI evaluator: 128 abstention and
28 gotcha questions in each condition.

## Local requirements

The host has an RTX 3090 with 24 GB VRAM. WSL2 Ubuntu sees the GPU and has
approximately 913 GB free. The official Qwen3.5-9B repository contains 19.33 GB
of model files. Engram uses its existing local State Core and embedding model;
the benchmark's Qwen3-Embedding-8B endpoint is not required for this method.

The reader therefore has no per-token API charge. It still requires a local
OpenAI-compatible server, conservative concurrency, and a context limit that
fits the 24 GB device.

## Evaluator cost gate

Official OpenAI pricing captured on 2026-09-20 for GPT-5.2 is $1.75 per million
input tokens, $0.175 per million cached input tokens, and $14.00 per million
output tokens. The exact bill cannot be known before the reader outputs exist
because those outputs become part of the judge prompts and reasoning output is
usage-dependent.

For 312 evaluator calls:

- a practical planning range is roughly **$2-$10**;
- the configured no-retry ceiling, if every call consumed about 20,500 input
  tokens and all 4,096 output tokens, is approximately **$29.10**;
- transient retries can raise the amount, so the run must retain an external
  spend limit and checkpoint usage.

No paid evaluator call was made during data preparation. A one-question-per-
condition calibration should be run first after approval, then its measured
usage should replace the planning range before the remaining 449 pairs proceed.

Pricing source: https://developers.openai.com/api/docs/models/gpt-5.2
