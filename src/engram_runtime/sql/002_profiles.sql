CREATE TABLE IF NOT EXISTS engram_inference_profile (
    workspace_id uuid NOT NULL REFERENCES engram_workspace(id) ON DELETE CASCADE,
    name text NOT NULL,
    configuration jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, name)
);
