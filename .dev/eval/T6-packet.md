# Packet — T6: Fixture naming alignment & docs

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
| **ID** | T6 |
| **Scope** | Address the roadmap item: `test_excel_accuracy_synthetic.xlsx` implies accuracy testing; rename or add real accuracy metrics. Write a short "How we measure quality" section for the README pointing to this plan and the eval subsystem. |
| **Files to touch** | `generate_test_datasets.py` (rename references if renaming files), `README.md` (add eval section), `.dev/evaluation-and-health-metrics-roadmap.md` (mark completed items) |
| **Contract bindings** | Naming conventions from shared contracts. No code interfaces — docs and file naming only. |
| **Inputs** | T5 (to document accurate CLI usage) — soft dependency |
| **Outputs** | Updated README with eval section, renamed or annotated test datasets, roadmap items checked off. |
| **Kill criteria** | HALT if: renaming `test_excel_accuracy_synthetic.xlsx` breaks the `hermes test` CLI command — check `cli.py` references first. |
| **Log tier** | trivial |
| **Risks & mitigations** | **Risk:** Renaming files breaks the `hermes test` command for users who already have the files generated. **Mitigation:** Update `cli.py` to use the new name, add a deprecation note, or keep both names with a fallback. Prefer renaming to `test_excel_stress_synthetic.xlsx` to match intent (stress/integration, not accuracy). |

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

## Subtask spec (T6 — in full)

### T6 — Fixture naming alignment & docs

| Field | Content |
|-------|---------|
| **ID** | T6 |
| **Scope** | Address the roadmap item: `test_excel_accuracy_synthetic.xlsx` implies accuracy testing; rename or add real accuracy metrics. Write a short "How we measure quality" section for the README pointing to this plan and the eval subsystem. |
| **Files to touch** | `generate_test_datasets.py` (rename references if renaming files), `README.md` (add eval section), `.dev/evaluation-and-health-metrics-roadmap.md` (mark completed items) |
| **Contract bindings** | Naming conventions from shared contracts. No code interfaces — docs and file naming only. |
| **Inputs** | T5 (to document accurate CLI usage) — soft dependency |
| **Outputs** | Updated README with eval section, renamed or annotated test datasets, roadmap items checked off. |
| **Kill criteria** | HALT if: renaming `test_excel_accuracy_synthetic.xlsx` breaks the `hermes test` CLI command — check `cli.py` references first. |
| **Log tier** | trivial |
| **Risks & mitigations** | **Risk:** Renaming files breaks the `hermes test` command for users who already have the files generated. **Mitigation:** Update `cli.py` to use the new name, add a deprecation note, or keep both names with a fallback. Prefer renaming to `test_excel_stress_synthetic.xlsx` to match intent (stress/integration, not accuracy). |

---

## Filtered load-bearing assumptions (touching T6)

(none)

---

## Filtered hidden couplings (touching T6)

(none)

---

## Actual upstream artifacts (for T6)

`hermes eval` interface (expected from T5): (missing)

