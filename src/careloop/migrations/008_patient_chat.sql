CREATE TABLE patient_chat (
    id uuid PRIMARY KEY,
    patient_id uuid NOT NULL REFERENCES patients(id),
    input jsonb NOT NULL,
    context jsonb NOT NULL,
    request jsonb NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'completed', 'failed')),
    response jsonb,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE INDEX patient_chat_history ON patient_chat(patient_id, created_at, id);
