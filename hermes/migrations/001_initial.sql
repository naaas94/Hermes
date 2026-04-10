CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    page_count INTEGER,
    has_text_layer INTEGER,
    schema_class TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    total_chunks INTEGER DEFAULT 0,
    completed_chunks INTEGER DEFAULT 0,
    failed_chunks INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    chunk_index INTEGER NOT NULL,
    source_pages TEXT,
    record_json TEXT NOT NULL,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_runs (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    chunk_index INTEGER NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'extraction',
    model TEXT,
    prompt_version TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    total_latency_ms INTEGER,
    validation_passed INTEGER,
    validation_error TEXT,
    raw_output TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS failed_extractions (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    chunk_index INTEGER NOT NULL,
    chunk_text_uri TEXT,
    last_error TEXT,
    retry_count INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
