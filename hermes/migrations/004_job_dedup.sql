ALTER TABLE jobs ADD COLUMN content_sha256 TEXT;
ALTER TABLE jobs ADD COLUMN llm_model_key TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_dedup_lookup ON jobs (
    content_sha256,
    schema_class,
    pages_spec,
    llm_model_key,
    status
);

INSERT OR IGNORE INTO schema_version (version) VALUES (4);
