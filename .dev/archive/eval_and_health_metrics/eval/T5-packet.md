# Packet — T5: Runner (CLI + pytest)

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
| **ID** | T5 |
| **Scope** | Implement the eval runner: (1) a `hermes eval` CLI command that runs the pipeline on manifest fixtures, scores results, and prints a summary table; (2) a pytest entry (`tests/test_eval_regression.py`) that asserts no regressions against committed goldens. Support `--update-goldens` for refreshing baselines. Emit optional JSON export of eval results. |
| **Files to touch** | `hermes/eval/runner.py` (new), `hermes/cli.py` (add `eval` command), `tests/test_eval_regression.py` (new), `tests/test_eval_runner.py` (new, unit tests for runner logic) |
| **Contract bindings** | All shared contracts. Runner orchestrates: load manifest (T1) → run pipeline or load existing results → score (T3) → format output. Does **not** re-implement scoring logic. |
| **Inputs** | T3 (scorer), T4 (fixtures to run against) |
| **Outputs** | Working `hermes eval` command, pytest regression suite, optional `--output eval_results.json` export. |
| **Kill criteria** | HALT if: (1) Running the pipeline inside eval requires an LLM API key — this means eval in CI needs either a mock or a pre-computed results cache. Decide mock strategy before implementing. (2) `hermes eval` wants to import from `hermes.extraction.pipeline` but circular dependencies arise — restructure imports. (3) The `--update-goldens` flow would silently overwrite goldens without user confirmation — add a safety prompt or `--yes` flag. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** Eval requires live LLM calls, making it expensive and non-deterministic in CI. **Mitigation:** Two modes: (a) `hermes eval` runs the full pipeline (for local use, nightly CI with API key), (b) `hermes eval --from-results <job_id>` scores an existing job's results (cheap, deterministic). pytest regression tests use mode (b) with pre-committed fixture results or mocked LLM (same mock pattern as `test_pipeline_integration.py`). **Risk:** `--update-goldens` makes it too easy to paper over regressions. **Mitigation:** Require explicit flag; CI should **never** run with `--update-goldens`. |

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

## Subtask spec (T5 — in full)

### T5 — Runner (CLI + pytest)

| Field | Content |
|-------|---------|
| **ID** | T5 |
| **Scope** | Implement the eval runner: (1) a `hermes eval` CLI command that runs the pipeline on manifest fixtures, scores results, and prints a summary table; (2) a pytest entry (`tests/test_eval_regression.py`) that asserts no regressions against committed goldens. Support `--update-goldens` for refreshing baselines. Emit optional JSON export of eval results. |
| **Files to touch** | `hermes/eval/runner.py` (new), `hermes/cli.py` (add `eval` command), `tests/test_eval_regression.py` (new), `tests/test_eval_runner.py` (new, unit tests for runner logic) |
| **Contract bindings** | All shared contracts. Runner orchestrates: load manifest (T1) → run pipeline or load existing results → score (T3) → format output. Does **not** re-implement scoring logic. |
| **Inputs** | T3 (scorer), T4 (fixtures to run against) |
| **Outputs** | Working `hermes eval` command, pytest regression suite, optional `--output eval_results.json` export. |
| **Kill criteria** | HALT if: (1) Running the pipeline inside eval requires an LLM API key — this means eval in CI needs either a mock or a pre-computed results cache. Decide mock strategy before implementing. (2) `hermes eval` wants to import from `hermes.extraction.pipeline` but circular dependencies arise — restructure imports. (3) The `--update-goldens` flow would silently overwrite goldens without user confirmation — add a safety prompt or `--yes` flag. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** Eval requires live LLM calls, making it expensive and non-deterministic in CI. **Mitigation:** Two modes: (a) `hermes eval` runs the full pipeline (for local use, nightly CI with API key), (b) `hermes eval --from-results <job_id>` scores an existing job's results (cheap, deterministic). pytest regression tests use mode (b) with pre-committed fixture results or mocked LLM (same mock pattern as `test_pipeline_integration.py`). **Risk:** `--update-goldens` makes it too easy to paper over regressions. **Mitigation:** Require explicit flag; CI should **never** run with `--update-goldens`. |

#### CLI interface sketch

```
hermes eval [OPTIONS]

Options:
  --fixture-dir PATH     Directory with manifests + goldens (default: tests/fixtures/eval/)
  --manifest PATH        Run a single manifest instead of all in fixture-dir
  --from-results JOB_ID  Score an existing job's results instead of re-running pipeline
  --from-jsonl PATH      Score from exported JSONL file
  --update-goldens       Overwrite golden files with current output (requires --yes or interactive confirm)
  --yes                  Skip confirmation for --update-goldens
  --output PATH          Write eval results JSON to file
  --model TEXT           Override LLM model for pipeline runs
  --verbose              Detailed per-field output
```

#### pytest integration

`tests/test_eval_regression.py` would:

1. Load each manifest in `tests/fixtures/eval/`.
2. Run pipeline with mocked LLM (returning the golden output — i.e., the test validates the scorer and manifest, not the LLM).
3. Assert `EvalSummary.positive_pass_rate == 1.0` and `EvalSummary.false_positive_rate == 0.0`.
4. If goldens present, assert field-level accuracy == 1.0.

This ensures the eval *infrastructure* doesn't regress, not that the LLM produces perfect output (that's for `hermes eval` with a live model).

---

## Filtered load-bearing assumptions (touching T5)

3. **PyYAML (or a YAML parser) can be added as a dependency.** If the project has a strict zero-new-deps policy, the manifest format must switch to JSON. The models are the same either way.

---

## Filtered hidden couplings (touching T5)

- **T5 (runner) ↔ T5 (pytest):** Both are in T5 but serve different audiences (CLI users vs CI). The pytest path needs mocked LLM responses while the CLI path needs real ones. If the mock strategy isn't cleanly separated, changes to one break the other. Mitigated by the runner accepting pre-computed results (`--from-results`) so pytest never needs a live LLM.

---

## Actual upstream artifacts (for T5)

`hermes/eval/scorer.py` (expected from T3): (missing)

`tests/fixtures/eval/` fixtures + goldens (expected from T4): (missing)

