# Packet — T2: Value normalizer

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
| **ID** | T2 |
| **Scope** | Implement field-value normalization functions for comparison: lowercase + strip whitespace, numeric tolerance (absolute and relative), date normalization (parse to ISO then compare), optional currency-string cleaning. These are pure functions, no pipeline dependency. |
| **Files to touch** | `hermes/eval/normalize.py` (new), `tests/test_eval_normalize.py` (new) |
| **Contract bindings** | All shared contracts. `FieldDiff.match_type` values (`exact`, `normalized`, `mismatch`, `missing`) are consumed by the scorer. |
| **Inputs** | None (root task) |
| **Outputs** | `normalize.py` with: `normalize_string(v) -> str`, `numbers_close(a, b, rel_tol, abs_tol) -> bool`, `normalize_date(v) -> str | None`, `normalize_value(expected, actual, field_type_hint) -> MatchType`. Unit tests with edge cases (locale, whitespace, `$350,000.00` vs `350000.0`, `"5%"` vs `0.05`). |
| **Kill criteria** | HALT if: (1) Numeric tolerance logic cannot be defined without knowing the schema field type at eval time — escalate; the normalizer may need access to JSON Schema field metadata. (2) Date parsing requires `dateutil` or heavy dependency — flag; decide whether to keep stdlib-only or add it. |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** Over-normalizing can mask real regressions (e.g., `"Toyota"` vs `"TOYOTA"` might matter for some schemas). **Mitigation:** Normalizer is configurable per-field via type hints in the manifest or golden file. Default is lenient (lowercase, strip); strict mode available. The scorer reports *which* normalization was applied in `FieldDiff` so regressions in formatting are still visible. |

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

## Subtask spec (T2 — in full)

### T2 — Value normalizer

| Field | Content |
|-------|---------|
| **ID** | T2 |
| **Scope** | Implement field-value normalization functions for comparison: lowercase + strip whitespace, numeric tolerance (absolute and relative), date normalization (parse to ISO then compare), optional currency-string cleaning. These are pure functions, no pipeline dependency. |
| **Files to touch** | `hermes/eval/normalize.py` (new), `tests/test_eval_normalize.py` (new) |
| **Contract bindings** | All shared contracts. `FieldDiff.match_type` values (`exact`, `normalized`, `mismatch`, `missing`) are consumed by the scorer. |
| **Inputs** | None (root task) |
| **Outputs** | `normalize.py` with: `normalize_string(v) -> str`, `numbers_close(a, b, rel_tol, abs_tol) -> bool`, `normalize_date(v) -> str | None`, `normalize_value(expected, actual, field_type_hint) -> MatchType`. Unit tests with edge cases (locale, whitespace, `$350,000.00` vs `350000.0`, `"5%"` vs `0.05`). |
| **Kill criteria** | HALT if: (1) Numeric tolerance logic cannot be defined without knowing the schema field type at eval time — escalate; the normalizer may need access to JSON Schema field metadata. (2) Date parsing requires `dateutil` or heavy dependency — flag; decide whether to keep stdlib-only or add it. |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** Over-normalizing can mask real regressions (e.g., `"Toyota"` vs `"TOYOTA"` might matter for some schemas). **Mitigation:** Normalizer is configurable per-field via type hints in the manifest or golden file. Default is lenient (lowercase, strip); strict mode available. The scorer reports *which* normalization was applied in `FieldDiff` so regressions in formatting are still visible. |

#### Tradeoffs

| Choice | Upside | Downside |
|--------|--------|----------|
| **Lenient default** (lowercase, strip, numeric tolerance) | Fewer false negatives in eval | May hide formatting regressions |
| **Strict default** (byte equality) | Catches all changes | Brittle; every locale/format difference is noise |
| **Per-field config in manifest** | Precise control | More authoring burden per fixture |

Recommendation: lenient default, per-field override as a future refinement. Track normalization applied in `FieldDiff` for auditability.

---

## Filtered load-bearing assumptions (touching T2)

(none)

---

## Filtered hidden couplings (touching T2)

(none)

---

## Actual upstream artifacts (for T2)

None (root task).

