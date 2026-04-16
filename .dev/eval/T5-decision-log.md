# T5 — Eval runner (CLI + pytest) — decision log

## Chosen approach

- Added `hermes/eval/runner.py` to orchestrate manifest load → job results (pipeline, existing job id, or JSONL) → `score_fixture` → optional golden updates; CLI exposes `hermes eval` with the options from the packet (`--fixture-dir`, `--manifest`, `--from-results`, `--from-jsonl`, `--update-goldens` + `--yes`, `--output`, `--model`, `--verbose`).
- **CI-safe regression:** `tests/test_eval_regression.py` runs the real pipeline against committed fixtures with **`create_llm_client` mocked** so the LLM returns the committed golden JSON—validating manifest wiring + scorer without a live API. Default `run_pipeline(..., force_new_job=True)` avoids silent dedup reuse during eval runs.
- **`--from-results` / `--from-jsonl`** require **`--manifest`** (single manifest) so one job or one JSONL maps unambiguously to expectations.
- **`--update-goldens`:** `typer.confirm` in the CLI, **`--yes`** for non-interactive runs, stdin `[y/N]` fallback in the library when interactive and no confirm callback, otherwise skip with a warning.

## Alternatives rejected

- **Batch `--from-results` across many manifests:** dropped because the DB has no stable manifest↔job link; users run one manifest per job id or use pipeline mode per fixture.

## Assumptions (load-bearing)

- Eval manifests use paths relative to the **current working directory** (typically the repo root); goldens resolve with `golden_base_dir=project_root` (`Path.cwd()` in the CLI).
- `extraction_results.contract_id` FK: tests and runner use **`contract_id=None`** when inserting synthetic rows unless a real contract row exists.

## Items deferred

- **Richer JSONL import formats** (e.g. flat export-only JSONL without `chunk_index`): not supported; documented format is one JSON object per line with `chunk_index`.
