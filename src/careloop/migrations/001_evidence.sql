CREATE TABLE evidence_sources (
    id uuid PRIMARY KEY,
    title text NOT NULL,
    locator text NOT NULL,
    edition text NOT NULL,
    content text NOT NULL,
    content_sha256 text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_rules (
    id uuid PRIMARY KEY,
    latest_revision integer NOT NULL CHECK (latest_revision > 0),
    active_revision integer,
    retired boolean NOT NULL DEFAULT false
);

CREATE TABLE evidence_revisions (
    rule_id uuid NOT NULL REFERENCES evidence_rules(id),
    revision integer NOT NULL CHECK (revision > 0),
    source_id uuid NOT NULL REFERENCES evidence_sources(id),
    body jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, revision)
);

ALTER TABLE evidence_rules ADD CONSTRAINT latest_revision_fk
    FOREIGN KEY (id, latest_revision) REFERENCES evidence_revisions(rule_id, revision)
    DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE evidence_rules ADD CONSTRAINT active_revision_fk
    FOREIGN KEY (id, active_revision) REFERENCES evidence_revisions(rule_id, revision);

CREATE TABLE evidence_approvals (
    rule_id uuid NOT NULL,
    revision integer NOT NULL,
    actor text NOT NULL,
    reason text NOT NULL,
    approved_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (rule_id, revision),
    FOREIGN KEY (rule_id, revision) REFERENCES evidence_revisions(rule_id, revision)
);

CREATE TABLE evidence_publications (
    id uuid PRIMARY KEY,
    actor text NOT NULL,
    reason text NOT NULL,
    conflict_review text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_publication_rules (
    publication_id uuid NOT NULL REFERENCES evidence_publications(id),
    rule_id uuid NOT NULL,
    revision integer NOT NULL,
    PRIMARY KEY (publication_id, rule_id),
    FOREIGN KEY (rule_id, revision) REFERENCES evidence_approvals(rule_id, revision)
);

-- A catalogue generation binds publication's manual conflict review to a snapshot.
CREATE TABLE evidence_catalogue (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    generation bigint NOT NULL DEFAULT 0
);
INSERT INTO evidence_catalogue DEFAULT VALUES;

CREATE TABLE audit_events (
    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    actor text NOT NULL,
    action text NOT NULL,
    entity_id uuid NOT NULL,
    reason text NOT NULL,
    details jsonb NOT NULL
);
CREATE INDEX audit_entity_idx ON audit_events(entity_id, sequence);
