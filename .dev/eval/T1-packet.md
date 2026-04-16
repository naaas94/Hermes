# Packet — T1: Manifest schema & loader

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
| **ID** | T1 |
| **Scope** | Define the `EvalManifest`, `ChunkLabel`, and `ChunkExpectation` Pydantic models. Implement a YAML loader that reads `.manifest.yaml` files and validates them. Support both chunk-index and page-range addressing. |
| **Files to touch** | `hermes/eval/__init__.py` (new package), `hermes/eval/manifest.py` (new), `tests/test_eval_manifest.py` (new) |
| **Contract bindings** | All shared contracts apply. `EvalManifest` is the most load-bearing type — T3, T4, T5 all consume it. |
| **Inputs** | None (root task) |
| **Outputs** | `hermes/eval/manifest.py` with models + `load_manifest(path) -> EvalManifest`, unit tests passing |
| **Kill criteria** | HALT if: (1) Pydantic v2 cannot represent the chunk-index-or-page-range union cleanly — escalate for design decision. (2) YAML parsing requires a new dependency not already in `pyproject.toml` — flag and decide (PyYAML is standard but must be explicitly added). |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** Page-range vs chunk-index addressing may be ambiguous when chunking strategy changes between runs. **Mitigation:** Manifest stores the addressing mode explicitly; scorer resolves at eval time using the job's actual chunk map. Chunk-index is primary; page-range is a convenience alias resolved before scoring. |

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

## Subtask spec (T1 — in full)

### T1 — Manifest schema & loader

| Field | Content |
|-------|---------|
| **ID** | T1 |
| **Scope** | Define the `EvalManifest`, `ChunkLabel`, and `ChunkExpectation` Pydantic models. Implement a YAML loader that reads `.manifest.yaml` files and validates them. Support both chunk-index and page-range addressing. |
| **Files to touch** | `hermes/eval/__init__.py` (new package), `hermes/eval/manifest.py` (new), `tests/test_eval_manifest.py` (new) |
| **Contract bindings** | All shared contracts apply. `EvalManifest` is the most load-bearing type — T3, T4, T5 all consume it. |
| **Inputs** | None (root task) |
| **Outputs** | `hermes/eval/manifest.py` with models + `load_manifest(path) -> EvalManifest`, unit tests passing |
| **Kill criteria** | HALT if: (1) Pydantic v2 cannot represent the chunk-index-or-page-range union cleanly — escalate for design decision. (2) YAML parsing requires a new dependency not already in `pyproject.toml` — flag and decide (PyYAML is standard but must be explicitly added). |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** Page-range vs chunk-index addressing may be ambiguous when chunking strategy changes between runs. **Mitigation:** Manifest stores the addressing mode explicitly; scorer resolves at eval time using the job's actual chunk map. Chunk-index is primary; page-range is a convenience alias resolved before scoring. |

#### Design decisions to capture

- **YAML vs JSON manifests:** YAML is friendlier for hand-authoring (comments, multi-line). JSON is zero-dep. Recommend YAML with PyYAML; fall back gracefully if missing. If adding PyYAML is rejected, switch to JSON — manifest schema stays the same.
- **`allow_empty` on negatives:** Defaults to `true` — a negative chunk producing zero records is correct behavior. If the user explicitly sets `allow_empty: false`, the scorer treats any output (including empty) on that chunk as a failure. This handles the roadmap's note about aligning with product rules.

---

## Filtered load-bearing assumptions (touching T1)

3. **PyYAML (or a YAML parser) can be added as a dependency.** If the project has a strict zero-new-deps policy, the manifest format must switch to JSON. The models are the same either way.

4. **The chunking algorithm is stable.** If `chunk_pages` changes behavior, chunk indices in manifests become invalid. Mitigated by the manifest's page-range fallback and by documenting that golden updates are expected after chunking changes.

---

## Filtered hidden couplings (touching T1)

- **T1 ↔ T4:** The manifest format is defined in T1, but the specific field values (chunk indices, page ranges) depend on how the fixtures are structured in T4. If T4 discovers that the fixtures need a different addressing scheme, T1's models must change. Mitigated by T1 supporting both chunk-index and page-range from the start.

---

## Actual upstream artifacts (for T1)

None (root task).

