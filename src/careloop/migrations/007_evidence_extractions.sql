CREATE TABLE evidence_extractions (
    id uuid PRIMARY KEY,
    source_id uuid NOT NULL REFERENCES evidence_sources(id),
    request jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'completed', 'failed')),
    response jsonb,
    result jsonb,
    error text,
    rule_ids jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX evidence_extractions_source ON evidence_extractions(source_id, created_at, id);
