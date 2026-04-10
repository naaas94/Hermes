# Changelog

## 2026_04_10

- **`hermes init`** now installs editable example schema modules under `~/.hermes/hermes_user/examples/` (`vehicle_fleet.py`, `generic_table.py`), copied from the bundled examples only when each file is missing, so user edits are preserved on re-run.
- **New config from init** sets `default_schema` to `hermes_user.examples.generic_table:GenericRow` instead of the site-packages path, so extraction works from the user directory without touching installed packages.
- **Schema loading** prepends `~/.hermes` to `sys.path` before importing modules, so `hermes_user.examples.*` resolves without setting `PYTHONPATH`.
- **Documentation** (`README.md`) updates the Quick Start with the user-local schema paths and clarifies custom schema layout versus `~/.hermes`.
- **Tests** add coverage for user schema installation and loading (`tests/test_user_schemas.py`).
- **`hermes extract --pages`** (`hermes/cli.py`): optional page/sheet subset for large documents; help text documents 1-based PDF page numbers and Excel **sheet** indices (not rows); wired via `pages_spec` into `run_pipeline`.
- **Page spec parsing** (`hermes/ingestion/pages_spec.py`): supports ranges and lists (e.g. `1-10`, `3,5,7`); `resolve_page_indices_0` validates against preflight totals and yields 0-based indices for normalizers.
- **Pipeline** (`hermes/extraction/pipeline.py`): resolves `--pages` after preflight; passes `page_indices` to the router; preflight/normalization stage details note subset size; fails clearly if normalization returns no pages; chunking uses `normalized_pages`; `jobs.page_count` remains full document size.
- **Normalization** (`hermes/normalization/router.py`, `pdf_text.py`, `pdf_ocr.py`, `excel.py`): optional `page_indices` filters PDF iteration and Excel sheets; output still uses stable `page_{n}.md` / `sheet_{n}.md` names and original 0-based indices for `NormalizedPage` / chunk `source_pages` (DLQ chunk paths unchanged).
- **Tests** (`tests/test_pages_spec.py`, `tests/test_normalization.py`): parser/validation coverage and PDF single-page filter smoke test.
- **Chunk token estimates** (`hermes/normalization/chunker.py`): optional `tiktoken` for tokenizer-accurate `estimate_tokens` and token-window splits when installed; falls back to the `CHARS_PER_TOKEN` heuristic if `tiktoken` is absent or `get_encoding` fails (e.g. unknown encoding name).
- **Config** (`hermes/config.py`): `extraction.tiktoken_encoding` (default `cl100k_base`) selects the tiktoken encoding when the optional dependency is present.
- **Packaging** (`pyproject.toml`): optional extra `tiktoken` (`tiktoken>=0.7`).
- **Documentation** (`README.md`): install note for the `tiktoken` extra and `extraction.tiktoken_encoding`.
- **Dependencies** (`pyproject.toml`): removed unused `tenacity`; the extraction validator never imported it. **Rationale:** `hermes/extraction/validator.py` already implements repair retries with a plain `while` loop and `max_retries` (from `cfg.llm.max_retries` via `hermes/extraction/pipeline.py`)—bounded attempts, no inter-attempt backoff. Keeping an extra dependency would not change behavior unless we added waits/backoff, which would risk rate limits and test timing drift.
- **Documentation** (`.dev/Hermes.md`): tech stack and memory-safety tables now describe that bounded manual repair loop (default `max_retries=2` → up to three LLM attempts per chunk) instead of incorrectly citing `tenacity` and exponential backoff.
- **Python version:** `.dev/Hermes.md` now states Python 3.12+ to match `requires-python = ">=3.12"` in `pyproject.toml`. Ruff (`target-version`) and Mypy (`python_version`) are set to 3.12 for consistency with that minimum.
