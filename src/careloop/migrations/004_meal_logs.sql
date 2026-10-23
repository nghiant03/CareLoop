CREATE TABLE meal_logs (
    id uuid PRIMARY KEY,
    patient_id uuid NOT NULL REFERENCES patients(id),
    logged_on date NOT NULL,
    plan_id uuid REFERENCES plans(id),
    slot text NOT NULL,
    latest_revision integer NOT NULL CHECK (latest_revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (patient_id, plan_id, logged_on, slot)
);
CREATE TABLE meal_log_revisions (
    log_id uuid NOT NULL REFERENCES meal_logs(id),
    revision integer NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (log_id, revision)
);
CREATE INDEX meal_logs_patient_date ON meal_logs(patient_id, logged_on);
CREATE TABLE meal_log_days (
    patient_id uuid NOT NULL REFERENCES patients(id),
    logged_on date NOT NULL,
    complete boolean NOT NULL DEFAULT false,
    PRIMARY KEY (patient_id, logged_on)
);
