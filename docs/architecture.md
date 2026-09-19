# Architecture decision record

## Local control plane

The first release uses a Python service, PostgreSQL with pgvector, local embedding
and reranking models, and a browser-based Runtime Console. A Compose profile starts
the supporting services on one workstation.

## Provider boundary

Inference Gateway exposes one internal request and response contract. Provider
adapters translate that contract for Ollama, OpenAI, Anthropic, Gemini, and
OpenAI-compatible endpoints. Domain packages depend only on the internal contract.

## Durable experience

State Core owns transactions and isolation. Signal Index owns discovery. Experience
Ledger assigns lifecycle meaning to stored records. Capability Forge may propose a
Procedure Pack after one successful action sequence. A candidate may guide the next
matching run with an explicit validation marker; a distinct second success promotes
it to verified.

## Execution

Action Cycle requests a Focus Packet, invokes one inference profile, validates
requested actions, anchors large outputs, and stops at a configured Persistence
Budget. Every transition emits a Run Record for Runtime Console.

## Attention economy

Attention Composer compares the selected Focus Packet with an uncompressed local
baseline. When a matching procedure exists, it keeps the procedure cue and narrows
the recent exchange, experience signals, and Action Units. The estimated input and
avoided-token counts are exposed as run evidence rather than hidden heuristics.
