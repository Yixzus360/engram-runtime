# Verification record

This record describes the local MVP. It does not claim a hosted deployment.

Verified locally on 2026-09-19.

## Automated checks

- Python lint: `uv run ruff check .` passed.
- Test suite: `uv run pytest -q` passed all 19 tests, including workspace isolation, retrieval, procedure
  verification, side-effect gating, bounded action execution, and Focus Packet
  composition.
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
- The first matching successful action sequence created a candidate Procedure
  Pack; the second verified it; later matching runs retained verified status.
- Procedure reuse reduced the composed Focus Packet from an estimated 438
  tokens to 259 and reduced selected action schemas from three to one. The
  estimated input avoided for that representative run was 179 tokens (41%).

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
