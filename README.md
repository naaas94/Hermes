# Hermes

**Schema-bound LLM document extraction with auditable contracts and replayable runs.**

Hermes converts messy Excel spreadsheets, text-layer PDFs, and scanned documents into validated, structured JSON against a Pydantic schema you define. Every run is bound to a stored schema snapshot and prompt version, instrumented per LLM call, and routes unrecoverable chunks to a replayable dead-letter queue — against local (Ollama) or cloud (LiteLLM) models.

## Features

- **Schema-driven** — define your own Pydantic models; Hermes validates every chunk against them and repairs failures in-loop.
- **Auditable extraction contracts** — every LLM run and result is tagged with a content-addressed `contract_id` (canonical schema text + prompt version). You can always answer "which schema and prompt produced this row?"
- **Replayable** — failed chunks enter a dead-letter queue; `hermes retry` resumes them, optionally against a different model. Jobs are promoted to `completed` only when every chunk has a result and the DLQ is clear. `hermes extract --resume` continues after crash or interrupt without re-normalizing.
- **Deduplicated** — a completed job with the same file hash, schema, page spec, and model is reused instead of re-run. `--force` always starts fresh.
- **Observable** — per-call tokens, latency, prompt version, validation status; stage timings for preflight, normalization, chunking, extraction. Inspect with `hermes status`.
- **Streaming by design** — Excel read 50 rows at a time with `openpyxl` read-only; PDF pages processed and released one at a time; results persisted per chunk; exports stream row-by-row.
- **Runtime-flexible** — runs fully offline with Ollama (no data leaves the machine) or against any LiteLLM-supported provider (OpenAI, Anthropic, Google) with a single config change. Sequential for local models, bounded parallel workers for cloud. One config file controls the entire switch.
- **Subset extraction** — `--pages` limits which PDF pages or Excel sheets are normalized and extracted.

## Installation

Requires **Python 3.12+**.

```bash
pip install -e .
```

Optional: `pip install -e ".[tiktoken]"` for tokenizer-accurate chunk sizing (override encoding with `extraction.tiktoken_encoding`, default `cl100k_base`).

For OCR support (scanned PDFs):

```bash
pip install -e ".[ocr]"
```

Optional: **`normalization.ocr_timeout_seconds`** in `config.toml` caps how long the CLI waits per OCR page (see **Configuration**). **`0`** leaves waits unlimited.

For development:

```bash
pip install -e ".[dev]"
```

## Docker

The repo includes a **Dockerfile** for a reproducible CLI image: **Python 3.12** (`python:3.12-slim-bookworm`), install from package sources, non-root user **`hermes`** (uid 1000), **`ENTRYPOINT`** **`hermes`** with default **`--help`**. Optional build-arg **`PIP_EXTRAS`** maps to `pip install ".${PIP_EXTRAS}"` (e.g. `[tiktoken]` or `[ocr]`).

```bash
docker build -t hermes .

docker build --build-arg PIP_EXTRAS='[tiktoken]' -t hermes-tiktoken .
docker build --build-arg PIP_EXTRAS='[ocr]' -t hermes-ocr .

docker run --rm -v "$PWD:/work" -w /work hermes --help
docker run --rm -v "$PWD:/work" -w /work hermes extract ./document.pdf
```

Mount data and configure API keys the same way you would for a local install. Override the default `CMD` by passing subcommands and flags after the image name.

## Quick Start

### 1. Initialize

```bash
hermes init
```

This creates `~/.hermes/config.toml` with default settings, initializes the SQLite database, and installs editable example schemas under `~/.hermes/hermes_user/examples/` (vehicle fleet and generic table copies; existing files are left unchanged). The default `default_schema` in that config points at the local package (`hermes_user.examples.generic_table:GenericRow`) so extraction works without relying on site-packages paths. Hermes prepends `~/.hermes` to the import path when loading schemas, so you do not need to set `PYTHONPATH`.

### 2. Configure your LLM provider

**Local (Ollama)** — install [Ollama](https://ollama.ai) and pull a model:

```bash
ollama pull qwen3:8b
```

The default config uses Ollama. No API keys, no data leaves the machine.

**Cloud (LiteLLM)** — set the provider and key in `~/.hermes/config.toml`:

```toml
[llm]
provider = "litellm"

[llm.litellm]
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
```

```bash
export OPENAI_API_KEY=sk-...
```

Any LiteLLM-supported provider (OpenAI, Anthropic, Google) works the same way. See **Configuration** for full options.

### 3. Extract

**Supported file types:** `.pdf` and Excel **`.xlsx`**, **`.xlsm`**, **`.xltx`**, **`.xltm`**. Pass a single file or a directory; only files with these extensions are processed.

```bash
# After hermes init: user-local copies (editable under ~/.hermes/hermes_user/examples/)
hermes extract invoice.pdf --schema hermes_user.examples.vehicle_fleet:VehicleRecord

# Same models via the shipped package (no init required)
hermes extract invoice.pdf --schema hermes.schemas.examples.vehicle_fleet:VehicleRecord

# Using the generic table extractor (default_schema from config, or override)
hermes extract data.xlsx

# Process an entire directory
hermes extract ./documents/ --schema my_schemas.custom:MyModel

# With concurrent workers (recommended for cloud LLMs only)
hermes extract data.xlsx --workers 4

# Always create a new job (disable completed-job reuse — see "Job deduplication" below)
hermes extract data.xlsx --force
hermes extract invoice.pdf --schema hermes_user.examples.vehicle_fleet:VehicleRecord -f

# Optional: limit PDF pages or Excel sheets (1-based indices; for Excel, sheet index only—not rows)
hermes extract large.pdf --pages 1-10 --schema hermes_user.examples.vehicle_fleet:VehicleRecord
hermes extract workbook.xlsx --pages 1,3,5

# Debug logs from pipeline, validator, and LLM client (place -v before the subcommand)
hermes -v extract invoice.pdf --schema hermes_user.examples.vehicle_fleet:VehicleRecord

# List module:Class references you can pass to --schema (bundled examples + ~/.hermes/hermes_user)
hermes list-schemas

# Only user schemas under ~/.hermes/hermes_user, or only packaged hermes.schemas.examples
hermes list-schemas --no-packaged
hermes list-schemas --no-user
```

#### Job deduplication

Before preflight, Hermes checks for an existing **`completed`** job with the same **SHA-256 of the source file**, **`schema_class`**, **`pages_spec`** (including “whole document” when `--pages` is omitted), and **effective LLM model** (override, else LiteLLM or Ollama model from config). If one exists, **`run_pipeline`** returns that job id and skips work (Rich explains the reuse).

Use **`hermes extract --force`** or **`-f`** to always create a new job.

**Caveat:** **Prompt version is not part of the dedup key.** Changing prompts alone can still match a prior completed job until you pass **`--force`**, or until the file bytes, schema, pages, or model differ.

**`-f` on different commands:** On **`extract`** and **`test`**, **`-f`** means **`--force`** (new job). On **`clean`**, **`-f`** skips the delete confirmation. On **`export`**, **`-f`** is **`--format`**, not “force”.

Schema refs import Python modules—use only modules you trust (see **Custom Schemas**).

### 4. Check Status

```bash
hermes status              # List all jobs
hermes status abc123       # Detailed view for a specific job
```

**Contract column:** The **All Jobs** table includes **Contract** with each job’s **`contract_id`**, truncated to **28 characters** (with an ellipsis when longer), or **`-`** when no contract is set. **`hermes status <job_id>`** shows a **Contract** row with the **full** id (or **`-`**). This matches the **`contract_id`** stored on the job and on related LLM runs and extraction results.

### 5. Export Results

Exports stream **JSONL** and **CSV** row-by-row so large jobs do not build the whole file in memory.

```bash
hermes export abc123 --format jsonl
hermes export abc123 --format csv --output results.csv
```

### 6. Clean Up Jobs

Remove a job’s storage directory under the configured base path and delete related database rows (with confirmation), or wipe all jobs:

```bash
hermes clean abc123
hermes clean --all
hermes clean -f abc123   # skip confirmation (e.g. scripts)
```

### 7. Retry and Resume

**Retry** replays chunks that landed in the dead-letter queue:

```bash
hermes retry               # Retry all pending DLQ items
hermes retry abc123        # Retry failures for a specific job
hermes retry --model gpt-4o-mini  # Retry with a different model
```

After replays, a job is marked **completed** only when there are no pending DLQ rows **and** every chunk has an extraction result (an empty DLQ alone does not mean all chunks ran—e.g. after interrupt).

**Resume** continues extraction for a job that stopped early (crash, kill, or Ctrl+C) without re-normalizing:

```bash
hermes extract --resume abc123
hermes extract --resume abc123 --workers 4 --model gpt-4o-mini
```

Hermes rebuilds chunks from the stored normalized Markdown under the job directory, checks that the chunk count still matches the job metadata (so your extraction config should be unchanged), and skips chunk indices that already have rows in `extraction_results`. The original file path is not required; if you pass one with `--resume`, it is ignored. **`retry`** replays DLQ failures; **`--resume`** picks up chunks that never ran.

## Testing

Hermes ships with a built-in test suite that runs synthetic datasets through the full pipeline and reports detailed telemetry.

### Generate Test Datasets

```bash
python generate_test_datasets.py
```

This creates two files in the project root:

| File | Purpose | Details |
|------|---------|---------|
| `test_excel_stress_synthetic.xlsx` | Stress / integration | 1,500 synthetic vehicle fleet rows with realistic noise (null VINs, merged headers, blank rows) matching the `VehicleRecord` schema. Exercises chunking and streaming through the full pipeline; it is **not** a formal accuracy benchmark. |
| `test_pdf_stress_riscbac.pdf` | Stress testing | 15-page synthetic insurance policy PDF with dense legal text, vehicle schedules, and endorsements scattered across pages to test chunking and context-window limits. |

### Run the Test Suite

```bash
hermes test
```

**Job deduplication applies here too:** without **`--force`**, a **prior completed job** for the same synthetic file content, schema, pages, and model may be **reused** (same behavior as `hermes extract`). To always run a full extraction for each fixture, use:

```bash
hermes test --force
hermes test -f
```

The test command automatically detects your configured LLM provider and picks the right concurrency strategy:

- **Ollama (local):** Runs sequentially (`workers=1`). Local models cannot process parallel requests efficiently; concurrent calls would queue up and risk OOM.
- **LiteLLM (cloud):** Runs in parallel (`workers=4`). Cloud APIs handle concurrent requests natively, so parallelism slashes wall time.

After both tests complete, Hermes prints a full telemetry report:

- **Pipeline stages** — duration of preflight, normalization, chunking, and extraction.
- **LLM stats** — total calls, tokens in/out, avg/min/max latency, repair attempts, validation failures.
- **Suite summary** — provider, concurrency mode, total wall time, aggregate token usage.

### Example output (illustrative, not SLA)

Representative run against `gpt-4o-mini` with 4 workers on the bundled synthetic fixtures. Chunk counts depend on `MAX_TABLE_ROWS_PER_CHUNK` and model context window; numbers below reflect a single run, not a guarantee.

```
Excel fixture (VehicleRecord, 1 500 rows)
  Chunks: 154 · LLM calls: 154 · Validation failures: 0 · Repairs: 0
  Avg latency: ~18s/call · Tokens: ~160k in, ~144k out · Wall: ~687s

PDF fixture (insurance policy, 15 pages)
  Chunks: 11 · LLM calls: 15 · Validation failures: 6 · Repairs: 4
  2 chunks stayed in DLQ — correctly: they contained boilerplate with
  no extractable rows under the schema.
```

The PDF result is the interesting signal. Of 6 validation failures, 4 were **recoverable** — the model's first JSON didn't match the schema, Hermes re-prompted with error context, and the repair attempt passed. The remaining 2 were **structurally empty**: chunks with no entities to extract. The validator correctly rejected them and the DLQ preserved them for inspection rather than inventing rows. That distinction — recoverable vs legitimately empty — is what `hermes status` and the DLQ are designed to surface.

## How we measure quality

Hermes is **schema-agnostic**: you supply the Pydantic model, so there is no single global “accuracy %” comparable across deployments. Quality work is layered:

- **Contract health** — validation and repair counts from normal runs (already surfaced in telemetry and `hermes status`).
- **Regression eval** — frozen inputs under `tests/fixtures/eval/` with `*.manifest.yaml` and optional `*.golden.jsonl` baselines; the scorer compares pipeline output to expectations (structural pass, stratified positive/negative chunks, field-level match when goldens exist).

Run the eval harness from the repo root (requires manifests present):

```bash
hermes eval
hermes eval --fixture-dir tests/fixtures/eval
hermes eval --manifest tests/fixtures/eval/sample_excel.manifest.yaml -v
```

Use `--from-results <job_id>` or `--from-jsonl <path>` to score without re-running extraction. `--output <file.json>` writes machine-readable results; `--update-goldens` refreshes golden files when you intentionally change outputs.

For fields where the lenient normalizer might match too eagerly (bare integers vs percent strings, ambiguous dates, near-zero comparisons), set `field_type_hint` explicitly in the manifest (behavior is defined alongside the normalization helpers in **`hermes.eval`**). When `match_key` is set on a manifest, anchor-mode scoring reports per-record `missing` / `extra` field diffs and populates **`EvalSummary`** fields `records_matched` / `records_extra` / `records_missing`. Callers that branch on coarse chunk `reason` strings should inspect `field_diffs` and those counts for specifics.

**`hermes test`** (above) remains a **stress / integration** path: large synthetic Excel + multi-page PDF through the real pipeline with telemetry. It complements eval; it does not replace golden regression.

## Benchmarks & memory

Hermes is built to stay **memory-safe** on large inputs: streaming Excel, page-at-a-time PDF normalization, per-chunk persistence, and no unbounded in-memory aggregation of document bytes. It is **scalable** in the sense that workload size and cloud parallelism are bounded by explicit knobs (`--workers`, page/sheet selection, WAL SQLite) rather than implicit full-document loads.

This section makes those claims **checkable**: the **`hermes bench`** command runs standard workloads (small PDF + Excel fixtures under `tests/fixtures/`, optionally the repo-root stress PDF with `--include-large`) and writes a JSON summary under `benchmarks/` (and optionally CSV with `--csv`). Enable **`[obs]`** (`pip install -e ".[obs]"`) so structured NDJSON logs and RSS sampling behave as documented; the default install still runs the pipeline.

### Running benchmarks locally

From the repository root (fixtures must exist — run `python tests/generate_fixtures.py` first if needed):

```bash
hermes bench --output benchmarks
```

Useful flags (see `hermes bench --help` for the full list):

| Flag | Short | Purpose |
|------|-------|---------|
| `--output` | `-o` | Directory for JSON (and optional CSV) summaries (default: `benchmarks`). |
| `--mock-llm` | | Use the integration-test stub LLM (CI-friendly; **not** representative of real throughput or latency). |
| `--model` | `-m` | Model override for every workload (default: `qwen3:4b`). |
| `--workers` | `-w` | Concurrency override for every workload (default: `1`). |
| `--csv` | | Also write a `.csv` next to the JSON summary. |
| `--include-large` | | Include `test_pdf_stress_riscbac.pdf` when present at the repo root. |
| `--log-format-compare` / `--no-log-format-compare` | | Control dual **console** vs **JSON** NDJSON runs for workloads that compare log formats (default: compare on `pdf_text_small` only when structlog is available). |
| `--verbose` | `-v` | Verbose logging after the run. |

CI runs **`hermes bench --mock-llm --output benchmarks`** on pushes to **`main`** and uploads the resulting JSON as a workflow artifact (informational; no threshold gate).

Raw timing and RSS-related events are also available in NDJSON when **`log_format = "json"`** and NDJSON logging are enabled — files are named `hermes-<YYYYMMDD>.ndjson` under the configured **`log_dir`** (see **`config.toml.example`** / **`hermes/config.py`**). Historical committed summaries live under [`benchmarks/`](benchmarks/).

### Reference hardware (point in time)

Numbers below come from [`benchmarks/20260417_afb5e93.json`](benchmarks/20260417_afb5e93.json): **`--mock-llm`**, default model **`qwen3:4b`**, **`workers=1`**, commit **`afb5e93`**, recorded **`2026-04-17`** (UTC). Environment: **Linux x86_64**, **Python 3.12.13** (Docker **`python:3.12-slim-bookworm`** on the maintainer machine). **Treat these as a snapshot**, not an SLA; re-run `hermes bench` and commit a new `benchmarks/<YYYYMMDD>_<short-sha>.json` when you need fresh figures.

| Workload | Peak RSS | Wall time | Throughput (primary) | Model | Date | Commit |
|----------|----------|-----------|----------------------|-------|------|--------|
| `pdf_text_small` | ~132 MiB | ~3.3 s | ~36 pages/min | `qwen3:4b` | 2026-04-17 | `afb5e93` |
| `excel_small` | ~135 MiB | ~0.17 s | ~352 rows/min | `qwen3:4b` | 2026-04-17 | `afb5e93` |

### Methodology (short)

- **What is measured:** wall-clock time per workload, peak RSS for the process (from `rss.sample` NDJSON events and `resource.getrusage` where available), token totals and derived throughput (pages/min, rows/min, chunks/min) from the job after the run.
- **What is not:** chart generation in-repo, regression thresholds in CI, or remote metric sinks — those are left to your own monitoring stack.
- **Caveats:** **`--mock-llm`** exercises the pipeline with a stub client; use a real provider for production-like timings. On **Windows**, `peak_rss_bytes` in the JSON summary may be **0** because the stdlib **`resource`** module is unavailable and the bench aggregator may not see RSS lines in the same form as on Linux — run under Linux/WSL or inspect NDJSON **`rss.sample`** lines when **`psutil`** is installed. RSS is **resident set size**, not GPU or mmap-heavy allocator peaks; shared runners and laptops will differ from the table above.

### Programmatic consumers

**Guidance:** code that needs to detect dual-sink bench regressions must filter log records on `level == "WARNING"` **and** message substring `"bench.dualsink.regression"`, not on `event` equality. That signal is intentionally a warning string today, not a structured `event` field. If you need it as a first-class log event, extend **`EventName`** in **`hermes/obs/schema.py`** in a minor schema bump (for example `2.0` → `2.1`) so existing consumers that only recognize older event names keep working.

## Configuration

Hermes looks for configuration in this order:

1. `./config.toml` (repo root)
2. `~/.hermes/config.toml` (user home)

Start from **`config.toml.example`** in the repo for the main TOML sections (`[llm]`, `[llm.litellm]`, `[normalization]`, `[storage]`, `[extraction]`). Some keys are documented only in comments there or below; defaults also live in **`hermes/config.py`** if you need the full dataclass picture.

### Switching Between Local and Cloud LLMs

```toml
# For local (Ollama):
[llm]
provider = "ollama"
model = "qwen3:8b"

# For cloud (any LiteLLM-supported provider):
[llm]
provider = "litellm"

[llm.litellm]
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"
```

Then set the env var: `export OPENAI_API_KEY=sk-...`

### Concurrency

The `--workers` flag on `hermes extract` controls how many chunks are sent to the LLM concurrently. The default is `1` (sequential), which is the correct choice for local Ollama models.

When using cloud providers via LiteLLM, increase workers to reduce wall time:

```bash
hermes extract large_document.pdf --schema my_schema:MyModel --workers 4
```

The pipeline uses a bounded `ThreadPoolExecutor` so the number of in-flight LLM requests never exceeds the worker count. Each worker gets its own SQLite connection (WAL mode handles concurrent writes safely).

### Optional: `tiktoken` encoding

When the **`[tiktoken]`** extra is installed, set **`[extraction] tiktoken_encoding`** (default **`cl100k_base`**) to match your tokenizer expectations. See **`config.toml.example`** under **`[extraction]`**.

### Optional: OCR page timeout (scanned PDFs)

With **`pip install ".[ocr]"`**, you can set **`normalization.ocr_timeout_seconds`** in config. **`0`** means no limit (default). A positive value bounds how long the CLI **waits** per page via a worker thread; on timeout the page gets placeholder text and processing continues. This does **not** reliably cancel work inside third-party OCR libraries—native OCR may keep using CPU/GPU until the call returns or the process exits.

### Large Excel preflight estimate

For very large workbooks, the CLI’s **estimated token** hint for Excel uses **row sampling** when per-sheet dimensions exceed internal thresholds, instead of scanning every row—small workbooks still use a full scan. Constants live in **`hermes/ingestion/preflight.py`** if you need exact behavior.

## Custom Schemas

Create a Python file with a Pydantic model:

```python
# my_schemas/invoice.py
from pydantic import BaseModel

class InvoiceItem(BaseModel):
    description: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    total: float | None = None
```

Then extract (ensure the directory containing your package is on `PYTHONPATH`, or place the package under `~/.hermes/` like `hermes init` does for `hermes_user`):

```bash
hermes extract invoice.pdf --schema my_schemas.invoice:InvoiceItem
```

**Trust:** `--schema` and `default_schema` use the form `module.path:ClassName`. Hermes loads the class by **importing** that Python module. Only pass references to code you trust—treat it like running `python -c "import module.path"`. Hermes does not sandbox schema modules; import-time code in that module can run. Do not point `--schema` at module paths supplied by untrusted users or copied from the internet without review.

## Architecture

```
Document → Preflight → Normalize (to Markdown) → Chunk → Bind Contract → LLM Extract → Validate → SQLite
                                                              │                ↑             ↓
                                                              │          Repair Loop    Dead Letter Queue
                                                              ↓
                                                  contract_id ← schema snapshot + prompt version
```

### Streaming and memory safety

Hermes is designed for large documents on modest hardware:

- Excel files are streamed with `openpyxl` read-only mode (50 rows at a time)
- PDF pages are processed one at a time; pixmaps are deleted immediately
- Results are persisted after each chunk, not batched
- **Ctrl+C** stops extraction cooperatively: the job can be left **partial** or **failed** with progress saved, not stuck in “extracting”
- **`hermes extract --resume <job_id>`** continues LLM extraction after interrupt or crash once chunking has completed (see §7 above)
- All inter-stage communication uses file paths, never raw bytes

### Extraction contracts (SQLite)

The database includes an **`extraction_contracts`** table (migration `005`) and nullable **`contract_id`** columns on **`jobs`**, **`llm_runs`**, and **`extraction_results`**. After chunking and before the first LLM write, Hermes inserts or reuses a contract row: canonical JSON Schema text, its SHA-256, the current **`get_current_prompt_version()`**, and the **`module:Class`** schema ref. The job row is updated, then every LLM run and extraction result for that extract carries the same **`contract_id`**. Older databases upgraded in place keep **`NULL`** on legacy rows; **`hermes retry`** and **`extract --resume`** attach a contract when missing before new writes.

### Observability

Every LLM call records:
- Input/output token counts
- Latency in milliseconds
- Prompt template version (SHA-256 hash)
- Validation pass/fail with error details
- Raw LLM output for debugging
- Pipeline stage durations (preflight, normalization, chunking, extraction)

Inspect jobs with **`hermes status`** (list or detail). The detail view includes pipeline stages, LLM runs, and the job’s **`contract_id`** when present (see §4).

## Development

```bash
pip install -e ".[dev]"

# Match CI locally: ruff, mypy, generate test fixtures, pytest (requires GNU Make — Git Bash / WSL on Windows)
make ci

# Or run only the test step the same way CI does (fixtures, then pytest)
make test

# Without Make: generate synthetic files under tests/fixtures/ (gitignored), then run pytest
python tests/generate_fixtures.py
pytest

# Generate synthetic test datasets (for hermes test)
python generate_test_datasets.py

# Static checks alone (also included in make ci)
ruff check .
mypy hermes/

# Run the full pipeline test suite with telemetry
hermes test
```

CI (GitHub Actions) runs on pushes to `main` and `dev` and on pull requests: editable install with `[dev]`, then `ruff`, `mypy`, `python tests/generate_fixtures.py`, and `pytest`. Output under **`tests/fixtures/`** is listed in **`.gitignore`**. OCR-heavy tests stay skipped unless the optional `ocr` extra is installed.

## License

MIT
