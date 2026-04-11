CREATE TABLE IF NOT EXISTS extraction_contracts (
    contract_id TEXT PRIMARY KEY,
    prompt_version TEXT NOT NULL,
    schema_class TEXT NOT NULL,
    json_schema TEXT NOT NULL,
    json_schema_sha256 TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_extraction_contracts_dedup ON extraction_contracts (
    json_schema_sha256,
    prompt_version
);

ALTER TABLE jobs ADD COLUMN contract_id TEXT REFERENCES extraction_contracts(contract_id);

ALTER TABLE llm_runs ADD COLUMN contract_id TEXT REFERENCES extraction_contracts(contract_id);

ALTER TABLE extraction_results ADD COLUMN contract_id TEXT REFERENCES extraction_contracts(contract_id);

INSERT OR IGNORE INTO schema_version (version) VALUES (5);
