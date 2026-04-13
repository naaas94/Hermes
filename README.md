# Hermes

**Local-first, memory-safe, LLM-powered document extraction engine.**

Hermes converts messy Excel spreadsheets, text-layer PDFs, and scanned documents into validated, structured JSON using local or cloud LLMs. You define a Pydantic schema, Hermes does the rest.

## Features

- **Local-first** — runs entirely offline with Ollama. No data leaves your machine.
- **Cloud-ready** — switch to OpenAI, Anthropic, or Google with a single config change via LiteLLM.
- **Memory-safe** — streams documents page-by-page; never holds an entire file in RAM.
- **Schema-driven** — define your own Pydantic models; Hermes extracts to match.
- **Subset extraction** — optional `--pages` limits which PDF pages or Excel sheets are normalized and extracted (large files).
- **Observable** — Rich progress for normalization and extraction; every LLM call is logged with tokens, latency, prompt version, and validation status.
- **Self-healing** — failed extractions enter a dead-letter queue and can be replayed; `retry` promotes jobs to completed only when every chunk has a result and the DLQ is clear.
- **Concurrency-aware** — sequential for local models, parallel with bounded workers for cloud APIs.
- **Extraction contracts** — jobs, LLM runs, and extraction results reference a stored **JSON Schema snapshot** and **prompt version** via a content-addressed **`contract_id`** (canonical schema string, deduplicated when identical). Makes it explicit which schema + prompt combination produced each row.
- **Job deduplication** — a **completed** job with the same file hash, schema, page spec, and effective model can be reused instead of re-running the pipeline; **`--force`** always starts a new job (see **Job deduplication** under Quick Start).

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

### 2. Start Ollama

Make sure [Ollama](https://ollama.ai) is running with a model pulled:

```bash
ollama pull qwen3:8b
```

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

### 7. Retry Failures

```bash
hermes retry               # Retry all pending DLQ items
hermes retry abc123        # Retry failures for a specific job
hermes retry --model gpt-4o-mini  # Retry with a different model
```

After replays, a job is marked **completed** only when there are no pending DLQ rows **and** every chunk has an extraction result (an empty DLQ alone does not mean all chunks ran—e.g. after interrupt).

### 8. Resume extraction (same job)

If normalization and chunking already finished but extraction stopped early (crash, kill, or Ctrl+C), you can continue LLM work for **the same job id** without re-normalizing:

```bash
hermes extract --resume abc123
hermes extract --resume abc123 --workers 4 --model gpt-4o-mini
```

Hermes rebuilds chunks from the stored normalized Markdown under the job directory, checks that the chunk count still matches the job metadata (so your extraction config should be unchanged), and skips chunk indices that already have rows in `extraction_results`. The original file path is not required; if you pass one with `--resume`, it is ignored. This complements **`hermes retry`**, which only replays rows already in the dead-letter queue.

## Testing

Hermes ships with a built-in test suite that runs synthetic datasets through the full pipeline and reports detailed telemetry.

### Generate Test Datasets

```bash
python generate_test_datasets.py
```

This creates two files in the project root:

| File | Purpose | Details |
|------|---------|---------|
| `test_excel_accuracy_synthetic.xlsx` | Extraction accuracy | 1,500 synthetic vehicle fleet rows with realistic noise (null VINs, merged headers, blank rows) matching the `VehicleRecord` schema. |
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
Document → Preflight → Normalize (to Markdown) → Chunk → LLM Extract → Validate → SQLite
                                                              ↑                ↓
                                                        Repair Loop     Dead Letter Queue
```

### Memory Safety

Hermes is designed for large documents on modest hardware:

- Excel files are streamed with `openpyxl` read-only mode (50 rows at a time)
- PDF pages are processed one at a time; pixmaps are deleted immediately
- Chunks are processed sequentially by default (parallel opt-in for cloud)
- Results are persisted after each chunk, not batched
- **Ctrl+C** stops extraction cooperatively: the job can be left **partial** or **failed** with progress saved, not stuck in “extracting”
- **`hermes extract --resume <job_id>`** continues LLM extraction after interrupt or crash once chunking has completed (see §8 above)
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
