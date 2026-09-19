# Verification record

This record describes the local MVP. It does not claim a hosted deployment.

Verified locally on 2026-09-19.

## Automated checks

- Python lint: `uv run ruff check .` passed.
- Test suite: `uv run pytest -q` passed all 43 tests, including workspace isolation, retrieval, procedure
  verification, side-effect gating, bounded action execution, and Focus Packet
  composition, profile policy, MCP discovery, credential rejection, and benchmark parsing.
- JavaScript syntax: `node --check` passed for the Runtime Console client.
- Distribution: `uv build` produced the source archive and wheel.
- Packaging: Runtime Console assets, the local Inter variable font, and its SIL
  Open Font License are present in the wheel.

## Live runtime checks

- PostgreSQL with pgvector remained reachable through the local WSL2 Docker
  engine while the Runtime Console was running.
- Ollama completed a real inference with `olmo-3:7b-instruct`.
- OpenAI completed a real economy-profile inference and a two-turn `calculate`
  Action Unit cycle.
- A fresh Codex execution loaded the repository-scoped `.codex/config.toml`,
  discovered `runtime_status`, and received `codex-evaluation` with local State
  Core ready.
- The first matching successful action sequence created a candidate Procedure
  Pack; the second verified it; later matching runs retained verified status.
- Procedure reuse reduced the composed Focus Packet from an estimated 438
  tokens to 259 and reduced selected action schemas from three to one. The
  estimated input avoided for that representative run was 179 tokens (41%).

## Codex MCP evaluation

A paired five-task run used `gpt-5.6-luna` with low reasoning. Every baseline
and Engram execution received the same question and an isolated copy of the
same repository. The Engram condition called one local recall tool and still
had to verify the decisive claim in current files.

| Aggregate | Baseline | Engram | Change |
| --- | ---: | ---: | ---: |
| Input tokens | 434,075 | 409,338 | -5.7% |
| Cached input tokens | 370,432 | 360,960 | -2.6% |
| Uncached input tokens | 63,643 | 48,378 | -24.0% |
| Output tokens | 3,463 | 2,810 | -18.9% |
| Elapsed inference time | 237.840 s | 187.096 s | -21.3% |
| Tool calls | 16 | 12 | -25.0% |
| Expected-answer terms | 14/15 | 15/15 | +1 term |

Seeding the five verified local signals took 12.151 seconds and is excluded
from the inference-time row so the acquisition cost remains visible. Including
that one-time seed still leaves this run 38.593 seconds faster overall.

The result is evidence for this task set, model, machine, and date. It is not a
general guarantee. Individual simple lookups sometimes used more total input
with MCP, while multi-file procedure and safety questions benefited most. Raw
event logs stay in ignored local artifacts; the reproducible task definitions
and sanitized result are stored under [`benchmarks/codex/`](../benchmarks/codex/).

## Scientific evaluation instrumentation

- The frozen pilot plan contains 125 complete pairs and 250 executions across
  five models, five tasks, and five repetitions.
- Fixed-seed tests verify reproducible pair order and prevent `--max-pairs`
  from splitting an Engram OFF/ON pair.
- Statistical unit tests cover exact McNemar, paired bootstrap intervals, and
  paired sign-flip randomization.
- Cost tests separately record API list-price equivalent and unknown actual
  subscription billing.
- The LongMemEval-V2 adapter targets pinned commit
  `2cc8c540bdb87fe6761629b585e727e1c4704520` and serializes trajectory evidence
  without benchmark-private answer or evaluator fields.

These checks validate the evaluation machinery. The 250-run internal pilot is
now complete: 125 intact pairs, 250 executions, no duplicate run IDs, no
nonzero exits, and no infrastructure failure included in analysis. Completion
was 110/125 without Engram and 125/125 with Engram (exact McNemar p=0.000061).
The sanitized result and its claim boundary are recorded in
[`benchmarks/scientific/latest-pilot.md`](../benchmarks/scientific/latest-pilot.md).
Official external benchmark evidence remains a separate result-producing
operation and must not be represented as complete until those artifacts exist.

A five-model, one-task smoke test then completed all ten scheduled executions:
5/5 baseline and 5/5 Engram. Engram reduced uncached input by 16.2%, output by
6.0%, and tool calls by 14.3%; API list-price equivalent increased by 2.7% and
wall time increased by 0.8%. With only five pairs and no completion discordance,
the exact McNemar p-value is 1.0. These values validate the harness and remain
explicitly non-confirmatory. The sanitized table is in
[`benchmarks/scientific/latest-smoke.md`](../benchmarks/scientific/latest-smoke.md).

The blind secondary jury accepted five of five schema-valid, no-tool verdicts.
All five judges selected the same anonymized response, revealed after
aggregation as GPT-6 Astra, while every candidate retained the same perfect
objective score. The result is recorded in
[`benchmarks/scientific/latest-debate.md`](../benchmarks/scientific/latest-debate.md)
and is not merged into the primary endpoint.

## Interface checks

- Desktop: 1440 x 900.
- Tablet: 1024 x 768.
- Mobile: 390 x 844.
- Body, Active Frame, and composer reported zero unintended horizontal
  overflow at all three viewports.
- Keyboard focus, loading, empty, success, failure, retry, touch sizing, and
  reduced-motion behavior are represented in the interface.

## Current limits

- The Runtime Console is a local single-operator MVP and has no remote account
  authentication layer.
- Inference calls run synchronously within a bounded Action Cycle; there is no
  distributed job worker in this release.
- Hosted model access depends on the operator's provider account, model access,
  network, and locally supplied environment variables.
- Codex token counters include its host instructions, cached context, tool
  schemas, and iterative tool turns. Repeat the benchmark before treating an
  observed percentage as a pricing forecast.
