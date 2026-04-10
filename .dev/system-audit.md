# Hermes System Audit

## Executive Summary

Hermes is a well-architected local-first CLI for LLM-powered document extraction (~3,200 LoC across 22 Python source files + 2 SQL migrations). The separation of concerns is clean, memory-safety design is deliberate, and the core pipeline works end-to-end. However, several bugs, gaps, and scalability issues need to be addressed before a release.

---

## 1. BUGS (Fix Before Release)

### 1a. Missing space in CLI `test` command output

```119:119:c:\Users\Ale\Documents\Repos\Hermes\hermes\cli.py
        f"thinking=[bold]{'on' if cfg.llm.enable_thinking else 'off'}[/bold]"
```

Missing whitespace separator before `thinking=`. It renders as `workers=4thinking=off`.

### 1b. OCR models loaded per-page (critical perf bug)

```125:156:c:\Users\Ale\Documents\Repos\Hermes\hermes\normalization\pdf_ocr.py
def _ocr_with_surya(img_bytes: bytes) -> tuple[str, float]:
    # ...
    det_model = load_det_model()
    det_processor = load_det_processor()
    rec_model = load_rec_model()
    rec_processor = load_rec_processor()
    # ...
```

Four heavy ML models are loaded **on every single page**. A 50-page scanned PDF loads/unloads 200 models. These must be loaded once and cached. Same problem in `_ocr_with_easyocr` -- `easyocr.Reader()` is instantiated per page.

### 1c. Missing `__init__.py` files in subpackages

The following directories have no `__init__.py`:
- `hermes/ingestion/`
- `hermes/normalization/`
- `hermes/extraction/`
- `hermes/schemas/`
- `hermes/schemas/examples/`

Python 3 implicit namespace packages work at runtime, but **`hatchling` will not include these in sdist/wheel builds** unless configured to do so. Since you use `hatchling.build`, the installed package will be broken unless `__init__.py` files are added or a `[tool.hatch.build]` include pattern is set.

### 1d. Token estimation inconsistency

`preflight.py` uses `total_chars // 4` (4 chars/token), while `chunker.py` uses `CHARS_PER_TOKEN = 2` (2 chars/token). Preflight reports "~1,000 tokens" but the chunker treats the same text as ~2,000 tokens, creating unnecessarily small chunks and wasting LLM calls. Pick one heuristic (4 chars/token is standard for English; 2-3 for multilingual).

---

## 2. CODE QUALITY

### 2a. Dead code

| Location | Item | Status |
|---|---|---|
| `generate_test_datasets.py:5` | `from datasets import load_dataset` | Never used (PDF was rewritten to use Faker) |
| `hermes/ingestion/storage.py:30-34` | `read_raw()` function | Never called anywhere |
| `hermes/schemas/loader.py:62-74` | `discover_schemas()` function | Never called anywhere |
| `hermes/extraction/validator.py:8` | `re` import used, but `_FENCE_RE` could use `re.compile` at module level | Fine, but `from typing import Any` is only used once |

### 2b. Verbosity / repetition in pipeline.py

The normalization error handling pattern appears 3 times in `run_pipeline` (lines 124-150, 156-183, 185-208) -- each one does:
1. Build error message
2. Save pipeline stage
3. Update job status to FAILED
4. Print error
5. Close connection
6. Return job_id

This should be a `_fail_job(conn, job_id, stage, error_msg, started_at)` helper.

### 2c. Type annotations gaps

- `_save_failure` suppresses type checking: `conn, job_id: str, chunk: Chunk, error: str, retry_count: int  # type: ignore[no-untyped-def]`
- `_write_sheet_markdown` has untyped `ws` parameter
- `_ocr_page`, `_render_and_ocr`, `_get_ocr_function` all have `# type: ignore[no-untyped-def]`
- `_parse_config` takes `dict` without type args
- Given `[tool.mypy] strict = true`, these suppressed errors should be properly typed

### 2d. Connection management -- no context managers

Connections in `cli.py` and `pipeline.py` are manually opened/closed without `try/finally`. If an exception occurs between `init_db()` and `conn.close()`, the connection leaks. Example:

```226:317:c:\Users\Ale\Documents\Repos\Hermes\hermes\cli.py
    conn = init_db()
    # ... 90 lines of logic that could throw ...
    conn.close()
```

### 2e. Per-operation commits

Every `save_result`, `save_llm_run`, `save_failed`, `save_pipeline_stage` does its own `conn.commit()`. A 100-chunk job does 300+ individual commits. Batch commits (e.g., per-chunk or per-stage) would reduce I/O.

---

## 3. SPEC vs IMPLEMENTATION DRIFT

| Item | `.dev/Hermes.md` says | Implementation does | Impact |
|---|---|---|---|
| `jobs.id` type | `INTEGER PRIMARY KEY` | `TEXT PRIMARY KEY` (UUID hex) | Implementation is better; spec outdated |
| `storage.base_path` default | `~/.hermes/storage` | `./storage` | User confusion; docs say one thing, code does another |
| Stage todos | All "pending" | All stages are implemented | Misleading for new contributors |
| `__init__.py` files | Listed in project structure | Missing from subpackages | Packaging broken |
| Migration 002 | Not in spec | Exists (adds `normalization_error`, `pipeline_stages`) | Spec incomplete |
| `enable_thinking` config | Not in spec | Implemented in config + Ollama client | Spec incomplete |

---

## 4. SCALABILITY ISSUES

### 4a. SQLite write serialization under concurrency

When `--workers > 1`, each worker thread opens its own SQLite connection. WAL mode allows concurrent readers, but **writes are still serialized** at the database level. With many workers, threads will contend on the write lock. For local CLI use with 4-8 workers this is acceptable; for anything higher, consider batching writes or switching to connection pooling.

### 4b. No streaming export for large result sets

`export_results_as_records` loads ALL records into memory, parses ALL JSON, then writes. For a job with 10,000+ records, this could be problematic. The export should stream records to the output file.

### 4c. Full-file-in-memory for large Excel token estimation

`preflight.py` iterates ALL rows of ALL sheets to estimate tokens:

```101:113:c:\Users\Ale\Documents\Repos\Hermes\hermes\ingestion\preflight.py
    elif file_type == FileType.EXCEL:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(file_path), read_only=True, data_only=True)
            page_count = len(wb.sheetnames)
            total_chars = 0
            for sheet in wb.sheetnames:
                ws = wb[sheet]
                for row in ws.iter_rows(values_only=True):
                    total_chars += sum(len(str(c)) for c in row if c is not None)
            estimated_tokens = total_chars // 4
            wb.close()
```

For a 100K-row spreadsheet, this scans everything just for an estimate. Consider sampling (first N rows x sheet count).

### 4d. No rate limiting for cloud LLM providers

When using LiteLLM with `--workers 4+`, there's no rate limiting. OpenAI/Anthropic APIs will return 429s. The code catches exceptions but doesn't distinguish retriable 429s from fatal errors.

---

## 5. MISSING FEATURES / GAPS

### Infrastructure (P0 for release)
- **No CI/CD** -- No `.github/workflows/`, no automated testing/linting on push
- **No `py.typed` marker** -- If anyone imports Hermes as a library, type checkers won't find type info
- **No `MANIFEST.in` or hatch build config** -- Migrations directory may not be included in the wheel

### CLI gaps
- **No `--verbose` / `--quiet` flags** -- No way to control log verbosity; `logging` is configured nowhere
- **No `hermes clean` command** -- No way to delete jobs or clean storage
- **No `hermes list-schemas` command** -- Would help discoverability
- **No progress for normalization/OCR** -- Progress bar only covers extraction, but OCR can take 10x longer

### Test coverage gaps
- **No test for OCR pipeline** (`pdf_ocr.py` is completely untested)
- **No test for LiteLLM client** (only Ollama paths are tested via mocked pipeline)
- **No test for concurrent extraction** (`workers > 1`)
- **No test for `hermes test` CLI command**
- **No test for `hermes export` CLI command**
- **No test for table chunking** (`_split_table_by_rows` in chunker)
- **No test for the `hermes init` CLI flow** directly (only `user_schemas` is tested)
- Test fixtures (`tests/fixtures/`) are gitignored and must be generated -- tests skip silently instead of failing, which can mask real breakage in CI

### Resilience gaps
- **No timeout on OCR** -- surya-ocr on a complex page could hang indefinitely
- **No graceful shutdown** -- Ctrl+C during extraction leaves the job in "extracting" status forever; no cleanup hook
- **No job resumption** -- If a job crashes mid-extraction, there's no way to resume from the last completed chunk
- **No idempotency** -- Running `extract` on the same file creates duplicate jobs with no dedup
- **DLQ `retry` doesn't update the parent job status** -- After successful replay, the job stays as "partial" or "failed"

---

## 6. SECURITY NOTES

- `schemas/loader.py` executes `importlib.import_module()` on arbitrary user-provided strings. For a CLI tool this is acceptable (same trust boundary as running Python), but document that schema refs should be trusted.
- `_parse_config` does `llm_raw.pop("litellm", {})` which mutates the input dict. Harmless due to `lru_cache`, but a code smell.

---

## 7. WHAT'S DONE WELL

- **Clean architecture** -- Pipeline stages are well-separated: ingestion -> normalization -> chunking -> extraction -> validation -> persistence
- **Memory safety** -- Deliberate page-at-a-time processing, `del page`/`del pixmap`, streaming Excel reads
- **DLQ pattern** -- Failed extractions are persisted with chunk text URIs for replay; this is production-grade
- **Prompt versioning** -- SHA-256 of prompt templates lets you track which prompt version produced which results
- **Dual LLM backend** -- Ollama/LiteLLM factory pattern with unified interface
- **Repair loop** -- Self-healing extraction with structured error feedback to the LLM
- **Immutable config** -- `frozen=True` dataclasses prevent mutation bugs
- **Table-aware chunking** -- Splitting by row count instead of token count for tabular data is smart
- **Test coverage of core paths** -- DB, config, validator, pipeline integration, pages spec, preflight are all tested

---

## 8. RECOMMENDED NEXT STEPS (Priority Order)

### P0 -- Must fix before release
1. Add `__init__.py` to all subpackages (5 files)
2. Fix OCR model caching (load once, reuse)
3. Fix the `thinking=` missing-space bug in `cli.py`
4. Add CI (GitHub Actions: `ruff check`, `mypy`, `pytest` with fixture generation)
5. Verify the built wheel includes `migrations/` directory

### P1 -- Should fix before release
6. Unify token estimation heuristic (pick 3 or 4 chars/token consistently)
7. Add connection context managers (or at minimum try/finally)
8. Extract repeated normalization-failure handling in pipeline.py
9. Add `--verbose` / logging configuration
10. Clean up dead code (`read_raw`, `discover_schemas`, unused `datasets` import)
11. Add `py.typed` marker

### P2 -- Next iteration
12. Cache OCR reader instances across pages
13. Add `hermes clean` command
14. Add graceful shutdown (signal handler to mark interrupted jobs)
15. Add rate limiting for cloud providers
16. Resume support for interrupted jobs
17. Stream `export` instead of loading all records
18. Test coverage for OCR, LiteLLM, concurrency, CLI commands

### P3 -- Nice to have
19. Proper type annotations (remove all `# type: ignore`)
20. Batch DB commits per chunk instead of per operation
21. Job deduplication (content hash)
22. `hermes list-schemas` command
23. Progress bars for normalization/OCR phases
24. Dockerfile for containerized deployment

---

Overall, the system is well-built for a v0.1. The architecture is sound and the pipeline design is solid. The biggest risks for release are the missing `__init__.py` files (packaging will be broken), the OCR per-page model loading (will make scanned PDFs unusable), and the lack of CI (regressions will slip through). Fix those three and you have a viable release.
