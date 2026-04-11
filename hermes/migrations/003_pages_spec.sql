ALTER TABLE jobs ADD COLUMN pages_spec TEXT;

INSERT OR IGNORE INTO schema_version (version) VALUES (3);
