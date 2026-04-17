# Packet — T3: Scorer engine

## Task statement + non-goals

Build a layered evaluation subsystem for Hermes that can measure extraction quality across schema-agnostic workloads. The system introduces: (a) a manifest format for tagging frozen fixtures with per-chunk expected outcomes, (b) a scorer that compares pipeline output against golden baselines using both structural (schema pass) and semantic (field-level) checks, (c) a runner invocable via `hermes eval` or `pytest`, and (d) the first set of committed golden fixtures with expected outputs.

The goal is to make quality regressions **visible and CI-blocking** without coupling to any single user schema or external eval vendor. The system should be self-contained — JSONL goldens, a Python scorer, and pytest — matching the "no vendor" path from the roadmap.

**Non-goals:**

- LLM-as-judge scoring (future layer; not part of this plan).
- Human review workflow or annotation UI.
- Integration with external eval platforms (LangSmith, Braintrust, etc.) — these remain documented as patterns.
- Part B of the roadmap (memory/throughput benchmarks, structlog, RSS sampling).
- Changes to the core extraction pipeline, validator, or repair logic.
- Synthetic data generation at scale (the `generate_test_datasets.py` large-file path is out of scope).

## Top-level scope

| Field | Content |
|-------|---------|
| **ID** | T3 |
| **Scope** | Core scoring logic. Given a manifest, a completed Hermes job (extraction results from DB or exported JSONL), and optional golden outputs, produce an `EvalResult` with: (1) per-chunk pass/fail against label expectations, (2) field-level diffs when goldens are present, (3) aggregate `EvalSummary`. |
| **Files to touch** | `hermes/eval/scorer.py` (new), `tests/test_eval_scorer.py` (new) |
| **Contract bindings** | All shared contracts. Consumes `EvalManifest` (T1), normalization functions (T2), reads `extraction_results` / exported JSONL. Produces `EvalResult`, `FieldDiff`, `EvalSummary`. |
| **Inputs** | T1 (manifest models), T2 (normalizer) |
| **Outputs** | `scorer.py` with `score_fixture(manifest, job_results, goldens?) -> EvalResult`. Tests covering: positive chunk with matching golden, positive chunk with mismatched golden, negative chunk with no output (pass), negative chunk with hallucinated output (fail), missing chunk in results. |
| **Kill criteria** | HALT if: (1) `extraction_results.record_json` format is not stable enough to parse reliably outside the pipeline — investigate and document the contract. (2) Scoring a "positive with no golden" case has no meaningful metric beyond schema-pass — this is a known gap; document it but don't block. (3) The scorer needs to re-run the pipeline (it should never do this — it only reads existing results). |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** `record_json` in `extraction_results` is a JSON string of `model_dump(mode="json")` arrays — the scorer must parse this identically. **Mitigation:** Use the same `json.loads` path; add a shared utility if needed. **Risk:** Field-level comparison requires knowing field names from the schema — schema-agnostic scoring means the scorer must introspect the golden file's keys, not hardcode them. **Mitigation:** Golden JSONL records define the field superset; scorer iterates golden keys and checks actual. |

---

## Shared contracts (Section 2 — in full)

### Types / interfaces

| Symbol | Location | Description |
|--------|----------|-------------|
| `EvalManifest` | `hermes/eval/manifest.py` | Pydantic model: fixture ref, schema ref, chunk-level labels (`positive` / `negative`), optional golden output path, metadata (modality, notes) |
| `ChunkLabel` | `hermes/eval/manifest.py` | Enum or literal: `positive`, `negative` |
| `ChunkExpectation` | `hermes/eval/manifest.py` | Per-chunk entry: `chunk_index` or `page_range`, `label: ChunkLabel`, `allow_empty: bool` (for negatives), optional `golden_path` |
| `EvalResult` | `hermes/eval/scorer.py` | Pydantic model: per-chunk and per-fixture scores, field-level diffs (when golden available), aggregate metrics |
| `FieldDiff` | `hermes/eval/scorer.py` | Per-field comparison result: field name, expected, actual, match type (`exact`, `normalized`, `mismatch`, `missing`) |
| `EvalSummary` | `hermes/eval/scorer.py` | Top-level report: positive pass rate, negative false-positive rate, field-level accuracy (when available), fixture metadata |

### Error envelope

Eval never raises exceptions into the pipeline — it operates post-hoc on already-completed job outputs. Errors are returned as structured data:

| Case | Behavior |
|------|----------|
| Manifest file not found or invalid | `EvalResult` with `error: str` set, zero scores, non-zero exit from CLI/pytest |
| Fixture file missing | Same — error string, skip fixture, summarize skips |
| Schema load failure | Same pattern |
| Golden parse failure | Flag in `FieldDiff` as `error`; do not crash scorer |

### Naming

| Kind | Convention |
|------|-----------|
| Module | `hermes/eval/` package: `manifest.py`, `scorer.py`, `runner.py`, `normalize.py` |
| Test files | `tests/test_eval_manifest.py`, `tests/test_eval_scorer.py`, `tests/test_eval_runner.py` |
| Fixtures dir | `tests/fixtures/eval/` — frozen input files + golden outputs |
| Manifest files | `tests/fixtures/eval/<fixture_name>.manifest.yaml` |
| Golden files | `tests/fixtures/eval/<fixture_name>.golden.jsonl` |
| CLI subcommand | `hermes eval` (Typer command in `cli.py`) |

### Logging

- Use stdlib `logging` (matches current codebase; structlog is a future Part B concern).
- Logger name: `hermes.eval.*` per module.
- Key structured fields in log messages: `fixture=`, `chunk_index=`, `label=`, `score=`.

### Tests

- Framework: **pytest** (existing).
- Location: `tests/test_eval_*.py`.
- Naming: `test_<module>_<behavior>`.
- Coverage expectation: all public functions in `hermes/eval/` have at least one positive and one negative test. Scorer normalization logic needs edge-case coverage.
- Fixtures: small inline or committed under `tests/fixtures/eval/`.

---

## Subtask spec (T3 — in full)

### T3 — Scorer engine

| Field | Content |
|-------|---------|
| **ID** | T3 |
| **Scope** | Core scoring logic. Given a manifest, a completed Hermes job (extraction results from DB or exported JSONL), and optional golden outputs, produce an `EvalResult` with: (1) per-chunk pass/fail against label expectations, (2) field-level diffs when goldens are present, (3) aggregate `EvalSummary`. |
| **Files to touch** | `hermes/eval/scorer.py` (new), `tests/test_eval_scorer.py` (new) |
| **Contract bindings** | All shared contracts. Consumes `EvalManifest` (T1), normalization functions (T2), reads `extraction_results` / exported JSONL. Produces `EvalResult`, `FieldDiff`, `EvalSummary`. |
| **Inputs** | T1 (manifest models), T2 (normalizer) |
| **Outputs** | `scorer.py` with `score_fixture(manifest, job_results, goldens?) -> EvalResult`. Tests covering: positive chunk with matching golden, positive chunk with mismatched golden, negative chunk with no output (pass), negative chunk with hallucinated output (fail), missing chunk in results. |
| **Kill criteria** | HALT if: (1) `extraction_results.record_json` format is not stable enough to parse reliably outside the pipeline — investigate and document the contract. (2) Scoring a "positive with no golden" case has no meaningful metric beyond schema-pass — this is a known gap; document it but don't block. (3) The scorer needs to re-run the pipeline (it should never do this — it only reads existing results). |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** `record_json` in `extraction_results` is a JSON string of `model_dump(mode="json")` arrays — the scorer must parse this identically. **Mitigation:** Use the same `json.loads` path; add a shared utility if needed. **Risk:** Field-level comparison requires knowing field names from the schema — schema-agnostic scoring means the scorer must introspect the golden file's keys, not hardcode them. **Mitigation:** Golden JSONL records define the field superset; scorer iterates golden keys and checks actual. |

#### Scoring rules (to implement)

| Chunk label | Has golden? | Output present? | Output validates? | Score |
|-------------|-------------|-----------------|-------------------|-------|
| positive | yes | yes | yes | Field-level diff against golden |
| positive | yes | yes | no | `schema_reject` — fail |
| positive | yes | no | — | `missing_output` — fail |
| positive | no | yes | yes | `schema_pass` — pass (no field accuracy) |
| positive | no | no | — | `missing_output` — fail |
| negative | — | no | — | `correct_abstention` — pass |
| negative | — | yes (empty array) | — | pass if `allow_empty` (default) |
| negative | — | yes (non-empty) | — | `false_positive` — fail |

#### Decision: how to read job results

Two options for how the scorer accesses extraction results:

1. **Direct DB read** — query `extraction_results` by `job_id`. Tight coupling to DB schema but zero friction.
2. **JSONL export** — use existing `hermes export --format jsonl` output. Decoupled but requires the export to be run first.

Recommendation: support both. Primary path is DB read (it's already there via `db.py`). Accept a `--from-jsonl <path>` override for CI or external use. The scorer function signature takes `list[dict]` — the caller (runner) handles sourcing.

---

## Filtered load-bearing assumptions (touching T3)

1. **`extraction_results.record_json` is a stable, parseable JSON array of `model_dump(mode="json")` dicts.** If this format changes without the scorer being updated, all golden comparisons break. Mitigated by T3 reading through the same `json.loads` path and testing against real DB output.

---

## Filtered hidden couplings (touching T3)

- **T3 ↔ pipeline internals:** The scorer reads `extraction_results` from the DB. If `_process_chunk` in `pipeline.py` changes how `record_json` is serialized (e.g., wrapping in metadata), the scorer breaks. Mitigated by documenting the `record_json` contract in T3's tests.

---

## Actual upstream artifacts (for T3)

`hermes/eval/manifest.py` (expected from T1): (missing)

`hermes/eval/normalize.py` (expected from T2): (missing)

