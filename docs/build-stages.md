# Build stages

Each stage ends with automated verification, a Git commit, and a push to the
private origin.

## 1. Identity Contract

- Canonical vocabulary and clean implementation rules.
- Repository policy, license, configuration boundaries, and architecture record.
- Gate: terminology check and documentation validation.

## 2. State Core

- PostgreSQL and pgvector through a local Compose profile.
- Transactional storage for runs, messages, records, actions, procedures, and outputs.
- Gate: migrations, health check, and persistence test.

## 3. Signal Index

- Local embeddings, full-text search, vector search, reciprocal-rank fusion, and reranking.
- Gate: deterministic retrieval evaluation over seeded fixtures.

## 4. Experience Ledger

- Active Frame, Knowledge Map, Run Journal, Procedure Vault, and retention rules.
- Gate: write, recall, supersession, isolation, and deletion tests.

## 5. Capability Forge

- Action Catalog, Procedure Library, execution recipes, and Pattern Distillation.
- Gate: action contract validation and evidence-gated procedure creation.

## 6. Action Cycle

- Inference Gateway, local and hosted adapters, bounded dispatch, retries, and verification.
- Gate: offline scripted-provider run plus optional live-provider probe.

## 7. Attention Composer

- Focus Packet construction, dynamic capability selection, token estimates, and Output Anchoring.
- Gate: repeated-run comparison demonstrates bounded input and procedure reuse.

## 8. Runtime Console

- Local web interface for conversations, runs, records, stored outputs, procedure candidates,
  provider profiles, and usage comparison.
- Gate: end-to-end browser verification in local and optional hosted-inference modes.

