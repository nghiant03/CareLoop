CREATE TABLE evidence_documents (
    source_id uuid PRIMARY KEY REFERENCES evidence_sources(id),
    original bytea NOT NULL,
    original_sha256 text NOT NULL,
    metadata jsonb NOT NULL,
    refresh_of uuid REFERENCES evidence_sources(id)
);
CREATE TABLE evidence_passages (
    source_id uuid NOT NULL REFERENCES evidence_sources(id),
    ordinal integer NOT NULL,
    location text NOT NULL,
    content text NOT NULL,
    start_offset integer NOT NULL,
    end_offset integer NOT NULL,
    PRIMARY KEY (source_id, ordinal)
);
CREATE INDEX evidence_passages_search ON evidence_passages USING gin(to_tsvector('english', content));
INSERT INTO evidence_passages
SELECT id, 1, 'Submitted text', content, 0, char_length(content) FROM evidence_sources;
