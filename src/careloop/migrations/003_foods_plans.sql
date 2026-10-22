CREATE TABLE foods (
    id uuid PRIMARY KEY,
    latest_revision integer NOT NULL CHECK (latest_revision > 0),
    namespace text NOT NULL,
    external_id text NOT NULL,
    UNIQUE (namespace, external_id)
);
CREATE TABLE food_revisions (
    food_id uuid NOT NULL REFERENCES foods(id),
    revision integer NOT NULL,
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (food_id, revision)
);
ALTER TABLE foods ADD CONSTRAINT food_latest_revision_fk
    FOREIGN KEY (id, latest_revision) REFERENCES food_revisions(food_id, revision)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE plan_requests (
    id uuid PRIMARY KEY,
    patient_id uuid NOT NULL REFERENCES patients(id),
    target_id uuid NOT NULL REFERENCES target_sets(id),
    target_revision integer NOT NULL,
    body jsonb NOT NULL,
    outcome jsonb NOT NULL,
    selected_plan_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (target_id, target_revision) REFERENCES target_revisions(target_id, revision)
);
CREATE TABLE plans (
    id uuid PRIMARY KEY,
    request_id uuid NOT NULL REFERENCES plan_requests(id),
    parent_plan_id uuid REFERENCES plans(id),
    objective text NOT NULL,
    body jsonb NOT NULL,
    needs_review boolean NOT NULL DEFAULT false,
    review_reasons jsonb NOT NULL DEFAULT '[]',
    allergy_alerts jsonb NOT NULL DEFAULT '[]',
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE plan_requests ADD FOREIGN KEY (selected_plan_id) REFERENCES plans(id);
CREATE TABLE plan_foods (
    plan_id uuid NOT NULL REFERENCES plans(id),
    food_id uuid NOT NULL,
    revision integer NOT NULL,
    PRIMARY KEY (plan_id, food_id, revision),
    FOREIGN KEY (food_id, revision) REFERENCES food_revisions(food_id, revision)
);
CREATE INDEX plan_target_idx ON plan_requests(target_id);
CREATE INDEX plan_patient_idx ON plan_requests(patient_id);
CREATE INDEX plan_food_idx ON plan_foods(food_id);
