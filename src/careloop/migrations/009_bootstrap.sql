CREATE TABLE bootstrap_jobs (
    key text PRIMARY KEY,
    state text NOT NULL CHECK (state IN ('pending', 'running', 'completed', 'failed')),
    detail jsonb NOT NULL DEFAULT '{}',
    error text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
