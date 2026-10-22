CREATE TABLE patients (
    id uuid PRIMARY KEY,
    latest_revision integer NOT NULL CHECK (latest_revision > 0),
    external_namespace text,
    external_id text,
    CHECK ((external_namespace IS NULL) = (external_id IS NULL)),
    UNIQUE (external_namespace, external_id)
);
CREATE TABLE patient_revisions (
    patient_id uuid NOT NULL REFERENCES patients(id),
    revision integer NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (patient_id, revision)
);
ALTER TABLE patients ADD CONSTRAINT patient_latest_revision_fk
    FOREIGN KEY (id, latest_revision) REFERENCES patient_revisions(patient_id, revision)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE target_sets (
    id uuid PRIMARY KEY,
    patient_id uuid NOT NULL,
    patient_revision integer NOT NULL,
    evaluation jsonb NOT NULL,
    latest_revision integer NOT NULL CHECK (latest_revision > 0),
    approved_revision integer,
    approved_by text,
    approved_at timestamptz,
    needs_review boolean NOT NULL DEFAULT false,
    review_reasons jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (patient_id, patient_revision) REFERENCES patient_revisions(patient_id, revision)
);
CREATE TABLE target_revisions (
    target_id uuid NOT NULL REFERENCES target_sets(id),
    revision integer NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (target_id, revision)
);
ALTER TABLE target_sets ADD CONSTRAINT target_latest_revision_fk
    FOREIGN KEY (id, latest_revision) REFERENCES target_revisions(target_id, revision)
    DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE target_sets ADD CONSTRAINT target_approved_revision_fk
    FOREIGN KEY (id, approved_revision) REFERENCES target_revisions(target_id, revision);
CREATE INDEX target_patient_idx ON target_sets(patient_id, created_at);
