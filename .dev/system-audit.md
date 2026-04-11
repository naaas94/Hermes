# Hermes System Audit

**Document status:** The **quick reference** below separates **still open** work from **caveats on already-remediated behavior** (the latter are documented in **`[fixed]`** / `CHANGELOG.md`, not as unfixed audit items). Remediated detail is in **`[fixed]`** (aligned with `CHANGELOG.md` as of 2026_04_11).

---

## Quick reference — status

### Still open or to review

Work that is **not** fully closed or is **intentionally partial** (not the same as “shipped with a caveat” in **`[fixed]`**):

| Area | Item | Notes |
|------|------|--------|
| **Scalability** | **§4a** | SQLite WAL still **serializes writes** under high `--workers`; acceptable for typical local CLI; revisit for higher concurrency or shared DBs. |
| **Tests** | **§8 P2 #18** | **Broader coverage** still incomplete vs an ideal matrix (optional OCR stack, full CLI surface, etc.). CI covers core paths — see **`[fixed]` §5 tests** for what exists. |


### Caveats on remediated behavior *(see `[fixed]`)*

These features **are implemented**; the notes below are **limitations or semantics** already spelled out under **`[fixed]`** — listed here so they are not mistaken for open audit gaps.

| Topic | Where | One-line caveat |
|-------|--------|-----------------|
| **Cloud / §4d** | **`[fixed]` §4 `4d`** | **LiteLLM** retries/backoff mitigate many 429s; there is still **no Hermes-level request throttle**. |
| **Resume** | **`[fixed]` Resilience** | **`hermes extract --resume`** is **extraction-stage** only; **mid-normalization** crash recovery is **out of scope** for now. |
| **Job dedup** | **`[fixed]` §8 / `CHANGELOG.md`** | Reuse key **omits prompt version**; use **`--force`** or change another keyed field when only prompts change. |
| **OCR timeout** | **`[fixed]` Resilience** | **`ocr_timeout_seconds`** avoids blocking the CLI; native OCR **may keep running** after timeout. |
| **Local test fixtures** | **Dev** | CI runs **`generate_fixtures.py`** before **`pytest`**. Locally, run **`make test`** / **`make ci`** or **`python tests/generate_fixtures.py`** before **`pytest`**, or some tests **skip** (see **`[fixed]` §5 Test fixtures**). |

### Already addressed (summary)

Bugs §1a–§1d, packaging/migrations, CI (including **fixture generation before pytest**), `py.typed`, token alignment, dead code removal, `_fail_job`, context managers, optional `tiktoken`, `--verbose`, `hermes clean`, streaming export, DLQ retry job promotion (with chunk-count guard), LiteLLM retries, normalization progress bars, graceful SIGINT during extraction, **extraction-stage resume** (`hermes extract --resume`), **content-hash job dedup** (with `hermes extract --force` / `hermes test --force` to bypass), batched commits per chunk, typing/mypy hardening, `_parse_config` non-mutation, **`hermes list-schemas`**, **Dockerfile** / `.dockerignore`, **large-Excel preflight sampling** (hybrid prefix + extrapolation above row thresholds), optional **OCR page timeout**, **Makefile** / `.gitignore` for **`tests/fixtures/`**, and more — see **`[fixed]`** below.

---

## Executive Summary

Hermes is a local-first CLI for LLM-powered document extraction with a clear pipeline (ingestion → normalization → chunking → extraction → validation → persistence) and deliberate memory-safety choices. Most issues from the original **“fix before release”** audit (bugs §1a–§1d, code quality §2a–§2e, and the bulk of scalability/gaps below) have been **remediated** — see **`[fixed]`**. **Still open:** §4a, broader tests (§8 P2 #18) — see **Still open or to review** above. **Shipped caveats** (retries vs throttle, resume scope, dedup key, OCR timeout semantics) are under **Caveats on remediated behavior** and **`[fixed]`**.

---

## 1. BUGS (historical — remediated)

Original findings: CLI spacing in `hermes test`, per-page OCR model reload, packaging/wheel layout vs subpackages, and token-heuristic mismatch between preflight and chunker. **Status:** addressed — see **`[fixed]` Section 1** (`1a`–`1d`).

---

## 2. CODE QUALITY (historical — remediated)

Original findings: dead imports/helpers, duplicated failure paths in the pipeline, strict-mypy gaps, manual DB lifecycle, per-call commits on hot paths. **Status:** addressed — see **`[fixed]` Section 2** (`2a`–`2e`).

---

## 3. SPEC vs IMPLEMENTATION DRIFT

*(Subsection retired.) The original audit included a **spec vs implementation** table against an early scope-of-work write-up, not a maintained product spec. That table is omitted; **`README.md`** and the repository code are the sources of truth for intended behavior.*

---

## 4. SCALABILITY ISSUES

### 4a. SQLite write serialization under concurrency *(still relevant)*

When `--workers > 1`, each worker thread opens its own SQLite connection. WAL mode allows concurrent readers, but **writes are still serialized** at the database level. With many workers, threads contend on the write lock. For typical local CLI use (roughly 4–8 workers) this is usually acceptable; for higher concurrency or shared DB scenarios, consider batching, pooling, or a different store — see **quick reference** above.

### 4b–4e. Other scalability notes *(remediated)*

Export memory use, Excel preflight cost on huge sheets, cloud LLM retry behavior, and table row batching per chunk were discussed in the original audit. **Status:** addressed or superseded — see **`[fixed]` Section 4** (`4b`–`4e`). *Note:* there is still **no separate application-level request throttle**; LiteLLM-side retries/backoff address many 429-style cases (`4d` in **`[fixed]`**).

---

## 5. MISSING FEATURES / GAPS

Most items from the original **infrastructure / CLI / resilience** lists (CI, `py.typed`, wheel + migrations, verbose logging, `clean`, `list-schemas`, normalization progress, streaming export, OCR timeout, graceful SIGINT, DLQ promotion rules, extraction-stage resume, cross-job dedup, Docker, etc.) are **closed** — see **`[fixed]` Section 5**.

**Still worth tracking:** **Still open** table + **Caveats** at the top; §4a below; full behavior in **`[fixed]`** / `CHANGELOG.md`.

---

## 6. SECURITY NOTES

Schema modules are loaded via **import** from user-supplied `module:Class` paths — same trust as running that Python code; **`README.md`** documents this. Config parsing no longer mutates loaded tables for LiteLLM. **Details:** **`[fixed]` Section 6**.

---

## 7. WHAT'S DONE WELL

- **Clean architecture** — Clear pipeline: ingestion → normalization → chunking → extraction → validation → persistence
- **Memory safety** — Page-at-a-time processing and bounded normalization patterns
- **DLQ pattern** — Failed extractions persisted for replay; promotion rules tightened (see **`[fixed]`**)
- **Prompt versioning** — Template hashes for traceability (dedup reuse key omits prompt version — see **Caveats** table / **`[fixed]`**)
- **Dual LLM backend** — Ollama / LiteLLM behind a single interface
- **Repair loop** — Structured validation/repair around LLM output
- **Immutable config** — `frozen=True` dataclasses where used
- **Table-aware chunking** — Row-batched table splits with tunable caps (see **`[fixed]` 4e**)

---

## 8. RECOMMENDED NEXT STEPS (historical backlog → outcomes)

The original **P0–P3** checklist from the audit is **mapped item-by-item** in **`[fixed]` Section 8** (what shipped vs what is partial or N/A). For **current** priorities, use **Still open or to review** (work left), **Caveats on remediated behavior** (limits of shipped fixes), and **`[fixed]`** for full detail.

---

## [fixed] — Remediated items (changelog cross-reference)

The following maps **audit IDs** to **what changed**. The narrative sections above are **condensed**; paths and line-level detail live in the repo and `CHANGELOG.md` (e.g. migrations under `hermes/migrations/`).

### Section 1 — Bugs

| ID | Remediation |
|----|-------------|
| **1a** | Trailing whitespace before `thinking=` in `hermes test` output (`hermes/cli.py`). |
| **1b** | Surya models and EasyOCR reader cached per process (`@lru_cache` helpers in `hermes/normalization/pdf_ocr.py`). |
| **1c** | Wheel includes package tree via `[tool.hatch.build.targets.wheel] packages = ["hermes"]` in `pyproject.toml` (alternative to adding five `__init__.py` files). |
| **1d** | `CHARS_PER_TOKEN = 4` aligned with preflight `// 4`; optional `tiktoken` for accurate counts (`hermes/normalization/chunker.py`, config `extraction.tiktoken_encoding`). |

### Section 2 — Code quality

| ID | Remediation |
|----|-------------|
| **2a** | Removed unused `datasets` import, `read_raw()`, `discover_schemas()`. |
| **2b** | `_fail_job()` helper in `hermes/extraction/pipeline.py`. |
| **2c** | Strict mypy pass: typed `_save_failure`, `_parse_config(dict[str, Any])`, Excel `Worksheet` under `TYPE_CHECKING`, OCR `Protocol`s; narrow `# type: ignore` only where stubs lack types (e.g. `pymupdf.open`). |
| **2d** | `open_db()` / `open_connection()` context managers in `hermes/db.py`; CLI and pipeline use `with` blocks. |
| **2e** | `save_*` functions accept `commit=`; `_process_chunk` batches one `commit()` per chunk. |

### Section 3 — Spec drift (retired)

| ID | Remediation |
|----|-------------|
| **§3** | Original drift table targeted a non-normative initial SOW; **not tracked** in this audit anymore. User-facing accuracy is maintained in **`README.md`** and code. |

### Section 4 — Scalability

| ID | Remediation |
|----|-------------|
| **4a** | Unchanged by design (documented tradeoff). |
| **4b** | `export_results_as_records` is a generator; `hermes export` streams JSONL/CSV (`hermes/db.py`, `hermes/cli.py`). |
| **4c** | Hybrid **sampling** for large workbooks when summed per-sheet row counts exceed **`EXCEL_PREFLIGHT_FULL_SCAN_MAX_ROWS`** (10_000): prefix of up to **`EXCEL_PREFLIGHT_PREFIX_ROWS_PER_SHEET`** (500) rows per sheet with **extrapolation** from dimensions; smaller workbooks keep a **full row scan**. **`estimated_tokens`** uses **`CHARS_PER_TOKEN`** from **`hermes/normalization/chunker.py`** (same divisor as PDF preflight). See `CHANGELOG.md` 2026_04_11 / `tests/test_preflight.py`. |
| **4d** | LiteLLM path uses retries / backoff strategy (see `CHANGELOG.md` for `litellm.completion` parameters; evolved from early `retry_after` notes). |
| **4e** | **Table-aware chunking:** `MAX_TABLE_ROWS_PER_CHUNK` raised **10 → 80** in `hermes/normalization/chunker.py` — fewer LLM calls per wide sheet when using stronger models; re-tune if validation errors or timeouts increase on very wide rows (`CHANGELOG.md` 2026_04_11). |

### Section 5 — Gaps

| ID | Remediation |
|----|-------------|
| **Infra** | `.github/workflows/ci.yml`, `hermes/py.typed`, hatch wheel + `hermes/migrations/`. **Container:** `Dockerfile` (Python 3.12-slim, non-root `hermes` user, `ENTRYPOINT hermes`, optional build-arg **`PIP_EXTRAS`** for extras), `.dockerignore`. |
| **Test fixtures** | CI runs **`python tests/generate_fixtures.py`** before **`pytest`**. **`tests/fixtures/`** is **gitignored**; **`Makefile`** targets **`test`** (fixtures + pytest) and **`ci`** (ruff, mypy, fixtures, pytest) match CI for local runs (`README.md`). |
| **CLI** | Global `--verbose` / `-v`; `hermes clean` with `--all`, `--force`, `typer.confirm`; normalization **Progress** + `on_page_done` in normalizers. **`hermes list-schemas`** (`hermes/schemas/discover.py`): sorted `module:Class` for packaged + user schemas; **`--no-packaged`** / **`--no-user`**; failed user modules skipped with stderr warning. |
| **§5 tests** | Table chunking, mocked `pdf_ocr` + OCR timeout, LiteLLM client unit tests, Typer smoke tests for `export` / `init` / `version`, pipeline parallel `ThreadPoolExecutor` smoke (`tests/`). |
| **Resilience** | SIGINT during extraction: `threading.Event`, partial/failed final status, stage detail `interrupted`; threaded pool shutdown with cancel. **Per-page OCR timeout** via `normalization.ocr_timeout_seconds` + `Future.result(timeout=...)` (does not reliably kill native OCR). **Extraction-stage resume:** `hermes extract --resume` (`hermes/extraction/pipeline.py`). **Cross-job content-hash dedup** for **`completed`** jobs (`content_sha256` + schema + `pages_spec` + effective model; `hermes extract --force` / `hermes test --force` bypasses). **Resume-after-crash for full pipeline** (not only post-chunking) — not implemented. |
| **DLQ** | After `retry`, jobs can promote to `completed` when DLQ empty for job, status was partial/failed, and distinct extraction chunk count matches `total_chunks` (see `CHANGELOG.md` / `count_distinct_extraction_chunk_indices`). |

### Section 6 — Security

| ID | Remediation |
|----|-------------|
| **§6** | `_parse_config` uses `.get("litellm", {})` and excludes `litellm` from `llm_fields` — **no mutation** of loaded dict. **`README.md`** (Quick Start, Custom Schemas): **trust** for `--schema` / `default_schema` — paths are **imported** (same boundary as running that import); Hermes does **not** sandbox schema code; untrusted paths should not be used. |

### Section 8 — Recommended next steps (mapping)

| Audit list | Outcome |
|------------|---------|
| **P0 1–5** | Addressed (packaging path, OCR cache, CLI spacing, CI, migrations in wheel + `get_migrations_dir()`). |
| **P1 6–11** | Addressed. |
| **P2 12** | Redundant after 1b (cached readers). |
| **P2 13–15, 17, 23** | `clean`, graceful shutdown, LiteLLM retries, streaming export, normalization progress. |
| **P2 16** | **Extraction-stage resume** — `hermes extract --resume` (MVP; not mid-normalization). |
| **P2 18** | **Partial** (CI tests; gaps may remain). |
| **P3 19** | **Largely addressed** (residual ignores only where stubs require). |
| **P3 20** | Batch commits per chunk — **done**. |
| **P3 21** | Content-hash job dedup + `--force` on `extract` / `test` — **done** (prompt version not in dedup key; see `CHANGELOG.md`). |
| **P3 22** | **`hermes list-schemas`** — **done** (`hermes/schemas/discover.py`; tests in `tests/test_discover.py`, CLI in `tests/test_cli.py`). |
| **P3 24** | **Dockerfile** — **done** (see **Infra** row above; `CHANGELOG.md` 2026_04_11). |

---

*End of audit document. Update the **Quick reference** and **`[fixed]`** sections when closing additional items.*
