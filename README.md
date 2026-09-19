# Engram Runtime

Engram Runtime is a local-first, model-neutral execution system with durable
experience. It combines provider-independent inference, bounded action
execution, hybrid knowledge discovery, and evidence-gated procedure reuse in
one inspectable runtime.

The control plane runs on open-source components. Inference can remain local or
use an optional external provider such as OpenAI, Anthropic, Gemini, or any
OpenAI-compatible endpoint.

## Product language

Engram Runtime uses its own public vocabulary. The canonical definitions live
in [`docs/engram-lexicon.md`](docs/engram-lexicon.md).

The Runtime Console follows the crystalline specification in
[`docs/visual-system.md`](docs/visual-system.md), including Inter Variable and
the established deep-blue glass material system.

| Component | Responsibility |
| --- | --- |
| Inference Gateway | Normalizes local and hosted model providers. |
| State Core | Persists runs, messages, outputs, and configuration. |
| Signal Index | Finds relevant knowledge with lexical and vector signals. |
| Experience Ledger | Preserves active, factual, historical, and procedural experience. |
| Domain Lens | Grounds execution in project and organization knowledge. |
| Capability Forge | Registers actions and distills verified procedures. |
| Action Cycle | Runs bounded reason-action-observation cycles. |
| Attention Composer | Builds compact Focus Packets for each inference call. |
| Runtime Console | Makes execution, evidence, usage, and decisions visible. |

## Development principles

- Local operation is the default.
- Hosted inference is optional.
- Provider names never leak into domain logic.
- Every side effect passes through a registered Action Unit.
- Durable procedures require verification evidence.
- Large outputs are anchored and retrieved only when needed.
- The interface shows what the runtime selected and why.

## Status

Active development. The delivery sequence and acceptance gates are documented
in [`docs/build-stages.md`](docs/build-stages.md).

## Local development

```powershell
uv sync --all-groups
./scripts/up.ps1
. ./scripts/use-local-state.ps1
uv run engram migrate
uv run pytest
```

`scripts/up.ps1` uses Docker directly when available and falls back to the
Docker engine in WSL2. `scripts/use-local-state.ps1` selects the reachable
address without persisting credentials or provider keys.

Signal Index uses Ollama with `nomic-embed-text:v1.5` for local 768-dimensional
embeddings. It fuses PostgreSQL full-text and vector rankings, then can refine
the candidates locally with FastEmbed. The small Apache-2.0 refinement model is
downloaded on first use and cached under `~/.cache/engram/models`.

The Inference Gateway includes native Ollama and OpenAI Responses adapters. An
optional open-source LiteLLM bridge adds Claude, Gemini, hosted Llama,
OpenRouter, and other providers behind the same Action Cycle:

```powershell
uv sync --extra universal
```

The default inference profiles are `local`, `economy` (GPT-5.6 Luna),
`balanced` (GPT-5.6 Terra), and `frontier` (GPT-6 Astra). Model identifiers are
environment-configurable, so account access and provider choice remain local.

## License

Apache-2.0.
