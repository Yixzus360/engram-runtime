CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS engram_workspace (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    display_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS engram_worker (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    worker_key text NOT NULL,
    label text NOT NULL,
    profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, worker_key)
);

CREATE TABLE IF NOT EXISTS engram_thread (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    worker_id uuid REFERENCES engram_worker(id) ON DELETE SET NULL,
    title text NOT NULL DEFAULT 'Untitled run',
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'archived')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS engram_entry (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id uuid NOT NULL REFERENCES engram_thread(id) ON DELETE CASCADE,
    sequence_no bigint GENERATED ALWAYS AS IDENTITY,
    speaker text NOT NULL CHECK (speaker IN ('operator', 'worker', 'action')),
    body text NOT NULL,
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thread_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS engram_run (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id uuid NOT NULL REFERENCES engram_thread(id) ON DELETE CASCADE,
    request_text text NOT NULL,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'complete', 'failed', 'stopped')),
    inference_profile text NOT NULL,
    usage jsonb NOT NULL DEFAULT '{}'::jsonb,
    outcome text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE IF NOT EXISTS engram_run_record (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES engram_run(id) ON DELETE CASCADE,
    record_kind text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS engram_experience (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    worker_id uuid REFERENCES engram_worker(id) ON DELETE CASCADE,
    thread_id uuid REFERENCES engram_thread(id) ON DELETE CASCADE,
    experience_form text NOT NULL CHECK (
        experience_form IN ('active_frame', 'knowledge_map', 'run_journal', 'procedure_vault')
    ),
    content text NOT NULL,
    fingerprint text NOT NULL,
    source text NOT NULL,
    confidence real NOT NULL DEFAULT 1.0 CHECK (confidence >= 0 AND confidence <= 1),
    attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(768),
    superseded_by uuid REFERENCES engram_experience(id) ON DELETE SET NULL,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, experience_form, fingerprint)
);

ALTER TABLE engram_experience
    ADD COLUMN IF NOT EXISTS search_document tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;

CREATE INDEX IF NOT EXISTS engram_experience_text_idx
    ON engram_experience USING gin (search_document);
CREATE INDEX IF NOT EXISTS engram_experience_vector_idx
    ON engram_experience USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS engram_experience_scope_idx
    ON engram_experience (workspace_id, experience_form, created_at DESC);

CREATE TABLE IF NOT EXISTS engram_action_unit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    name text NOT NULL,
    description text NOT NULL,
    input_contract jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_contract jsonb NOT NULL DEFAULT '{}'::jsonb,
    handler text NOT NULL,
    risk_level text NOT NULL DEFAULT 'read' CHECK (risk_level IN ('read', 'write', 'external')),
    enabled boolean NOT NULL DEFAULT true,
    embedding vector(768),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, name)
);

CREATE INDEX IF NOT EXISTS engram_action_unit_vector_idx
    ON engram_action_unit USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS engram_procedure_pack (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    name text NOT NULL,
    version integer NOT NULL DEFAULT 1,
    status text NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'verified', 'retired')),
    description text NOT NULL,
    trigger_text text NOT NULL,
    procedure_body jsonb NOT NULL,
    verification_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    fingerprint text NOT NULL,
    embedding vector(768),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (workspace_id, name, version),
    UNIQUE (workspace_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS engram_procedure_pack_vector_idx
    ON engram_procedure_pack USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS engram_stored_output (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    run_id uuid REFERENCES engram_run(id) ON DELETE CASCADE,
    dispatch_id text,
    media_type text NOT NULL DEFAULT 'application/json',
    byte_count bigint NOT NULL,
    sha256 text NOT NULL,
    preview text NOT NULL,
    content bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    UNIQUE (workspace_id, sha256)
);

CREATE INDEX IF NOT EXISTS engram_stored_output_run_idx
    ON engram_stored_output (run_id, created_at DESC);

