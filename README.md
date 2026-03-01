# Hermes

**Local-first, memory-safe, LLM-powered document extraction engine.**

Hermes converts messy Excel spreadsheets, text-layer PDFs, and scanned documents into validated, structured JSON using local or cloud LLMs. You define a Pydantic schema, Hermes does the rest.

## Features

- **Local-first** — runs entirely offline with Ollama. No data leaves your machine.
- **Cloud-ready** — switch to OpenAI, Anthropic, or Google with a single config change via LiteLLM.
- **Memory-safe** — streams documents page-by-page; never holds an entire file in RAM.
- **Schema-driven** — define your own Pydantic models; Hermes extracts to match.
- **Observable** — every LLM call is logged with tokens, latency, prompt version, and validation status.
- **Self-healing** — failed extractions enter a dead-letter queue and can be replayed.
- **Concurrency-aware** — sequential for local models, parallel with bounded workers for cloud APIs.

## Installation

```bash
pip install -e .
```

For OCR support (scanned PDFs):

```bash
pip install -e ".[ocr]"
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize

```bash
hermes init
```

This creates `~/.hermes/config.toml` with default settings and initializes the SQLite database.

### 2. Start Ollama

Make sure [Ollama](https://ollama.ai) is running with a model pulled:

```bash
ollama pull qwen3:8b
```

### 3. Extract

```bash
# Using a built-in example schema
hermes extract invoice.pdf --schema hermes.schemas.examples.vehicle_fleet:VehicleRecord

# Using the generic table extractor
hermes extract data.xlsx

# Process an entire directory
hermes extract ./documents/ --schema my_schemas.custom:MyModel

# With concurrent workers (recommended for cloud LLMs only)
hermes extract data.xlsx --workers 4
```

### 4. Check Status

```bash
hermes status              # List all jobs
hermes status abc123       # Detailed view for a specific job
```

### 5. Export Results

```bash
hermes export abc123 --format jsonl
hermes export abc123 --format csv --output results.csv
```

### 6. Retry Failures

```bash
hermes retry               # Retry all pending DLQ items
hermes retry abc123        # Retry failures for a specific job
hermes retry --model gpt-4o-mini  # Retry with a different model
```

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

See `config.toml.example` for all available settings.

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

Then extract:

```bash
hermes extract invoice.pdf --schema my_schemas.invoice:InvoiceItem
```

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
- All inter-stage communication uses file paths, never raw bytes

### Observability

Every LLM call records:
- Input/output token counts
- Latency in milliseconds
- Prompt template version (SHA-256 hash)
- Validation pass/fail with error details
- Raw LLM output for debugging
- Pipeline stage durations (preflight, normalization, chunking, extraction)

Query with: `hermes status <job_id>`

## Development

```bash
pip install -e ".[dev]"

# Generate test fixtures
python tests/generate_fixtures.py

# Generate synthetic test datasets
python generate_test_datasets.py

# Run unit tests
pytest

# Run the full pipeline test suite with telemetry
hermes test

# Lint
ruff check hermes/ tests/
```

## License

MIT
