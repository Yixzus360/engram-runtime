# Engram Lexicon

This document is the canonical product vocabulary. Public APIs, interface copy,
documentation, event names, and package names should use these terms.

## Runtime components

| Engram term | Meaning |
| --- | --- |
| Inference Gateway | Provider-neutral access to local or hosted reasoning models. |
| State Core | Transactional persistence for runtime state and stored outputs. |
| Signal Index | Lexical, vector, hybrid, and reranked discovery. |
| Experience Ledger | Durable experience available across runs. |
| Domain Lens | Project facts, conventions, schemas, and institutional knowledge. |
| Capability Forge | Action registration, procedure storage, and procedure distillation. |
| Action Cycle | Bounded execution cycle that selects and dispatches actions. |
| Attention Composer | Selects the smallest useful input for one inference call. |
| Runtime Console | Operator interface for execution and inspection. |

## Experience forms

| Engram term | Meaning |
| --- | --- |
| Active Frame | Current run state and recent interaction. |
| Knowledge Map | Durable facts and definitions. |
| Run Journal | Prior executions, outcomes, failures, and corrections. |
| Procedure Vault | Verified reusable operating procedures. |
| Focus Packet | Compact input assembled for one inference call. |

## Capabilities and execution

| Engram term | Meaning |
| --- | --- |
| Runtime Worker | One executing Engram identity. |
| Action Unit | A callable capability with a validated input contract. |
| Action Catalog | Searchable registry of Action Units. |
| Procedure Pack | Versioned instructions for a repeatable task. |
| Procedure Library | Searchable registry of Procedure Packs. |
| Execution Recipe | Captured sequence from a completed run. |
| Action Dispatch | One validated Action Unit invocation. |
| Run Record | Ordered evidence emitted during execution. |
| Stored Output | Full result retained outside the active prompt. |
| Pattern Distillation | Conversion of verified run evidence into a Procedure Pack candidate. |
| Recipe Crystallization | Consolidation of repeated successful recipes into one reusable procedure. |
| Output Anchoring | Persistence of large results with a compact in-prompt reference. |
| Attention Trimming | Removal or compression of low-value prompt material. |
| Inference Routing | Selection of an inference profile from task requirements. |
| Persistence Budget | Limits governing retries, duration, actions, and inference usage. |
| Operator Gate | A deliberate pause for human authorization or correction. |

## Interoperability language

Standards and technologies retain their real names: API, MCP, HTTP, SQL, JSON,
PostgreSQL, pgvector, HNSW, OpenAI, Anthropic, Gemini, Ollama, llama.cpp, and
vLLM. These identify external contracts rather than Engram product concepts.

