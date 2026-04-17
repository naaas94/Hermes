# T3 — Scorer engine — decision log

## Chosen approach

- Implemented `hermes/eval/scorer.py` with `score_fixture(manifest, job_results, goldens=None, *, golden_base_dir=None) -> EvalResult`, plus `FieldDiff`, `ChunkScore`, `EvalSummary`, and `EvalResult` per contract.
- `job_results` rows mirror DB/export usage: required `chunk_index`, optional `record_json` (same string format as `extraction_results.record_json`: JSON array of `model_dump(mode="json")` dicts), optional pre-parsed `records`, optional `validation_passed` (default true) for synthetic schema-reject cases.
- Field-level scoring iterates keys from golden records (per-chunk override, manifest JSONL line by `chunk_index`, or in-memory `goldens` map); comparisons use `normalize_value` from T2.
- `page_range` expectations are not mapped to chunk indices here; they yield `page_range_unresolved` so the runner can pre-resolve to `chunk_index` later.

## Alternatives rejected

- **Resolving `page_range` inside the scorer** without a page→chunk map would require duplicating pipeline chunking or guessing; deferred to the runner to keep the scorer a pure function of manifest + results.

## Assumptions (load-bearing)

- Successful pipeline rows store `record_json` as `json.dumps([...])` of object dicts, consistent with `hermes.extraction.pipeline._process_chunk` and `hermes.db.export_results_as_records` parsing.

## Items deferred

- **Positive + no golden**: pass with `schema_pass_no_golden` only measures “output present and validated,” not semantic quality (documented in scorer docstring).
- **Strict JSON Schema validation in eval**: scorer trusts `validation_passed` / presence of saved rows; re-validation belongs to the runner or fixture tooling if needed.
