# Telemetry and Extraction Quality Reference

This document explains how to use Hermes' stored telemetry to find bottlenecks and optimization opportunities, and how to evaluate extraction quality for downstream pipelines.

---

## 3. Using Telemetry to Find Bottlenecks and Optimization Opportunities

All pipeline and LLM metrics are stored in SQLite after each run. You can query them to see where time and resources are spent and where failures occur.

### Where to Look

**`pipeline_stages`** (per job, one row per phase):

| Column        | Description |
|---------------|-------------|
| `stage`       | One of: `preflight`, `normalization`, `chunking`, `extraction` |
| `duration_ms` | Time spent in that phase (milliseconds) |
| `detail`      | Short summary (e.g. `normalized_pages=3`, `chunks=5`, `completed_chunks=4, failed_chunks=1`) |
| `started_at`, `ended_at` | ISO timestamps for the phase |

Use this to see **which phase dominates runtime** (e.g. extraction vs normalization vs chunking).

**`llm_runs`** (per LLM call, one row per chunk attempt or repair):

| Column              | Description |
|---------------------|-------------|
| `tokens_in`, `tokens_out` | Input/output token counts |
| `total_latency_ms`  | Time for that LLM call |
| `validation_passed` | 1 if the response passed Pydantic validation, 0 otherwise |
| `validation_error`  | Error message when validation failed |
| `run_type`          | e.g. `extraction`, `repair`, `retry` |

Use this for **token usage**, **latency distribution**, and **validation failure rate**.

**`jobs`** (one row per ingested file):

| Column               | Description |
|----------------------|-------------|
| `total_chunks`, `completed_chunks`, `failed_chunks` | Chunk counts for that job |
| `status`             | `queued`, `normalizing`, `extracting`, `completed`, `partial`, `failed` |
| `normalization_error`| Set when preflight/normalization failed (e.g. unsupported type, OCR error) |

Use this for **throughput** (chunks per job), **overall failure rate**, and **normalization failures**.

### Example Queries (SQLite)

**Time by stage (find the bottleneck):**

```sql
SELECT stage, SUM(duration_ms) AS total_ms, COUNT(*) AS job_count
FROM pipeline_stages
GROUP BY stage
ORDER BY total_ms DESC;
```

**LLM cost and latency:**

```sql
SELECT
  SUM(tokens_in) AS total_tokens_in,
  SUM(tokens_out) AS total_tokens_out,
  SUM(total_latency_ms) AS total_latency_ms,
  AVG(total_latency_ms) AS avg_latency_ms
FROM llm_runs;
```

**Validation failure rate:**

```sql
SELECT
  COUNT(*) AS total_runs,
  SUM(CASE WHEN validation_passed = 1 THEN 1 ELSE 0 END) AS passed,
  SUM(CASE WHEN validation_passed = 0 THEN 1 ELSE 0 END) AS failed
FROM llm_runs;
```

**Jobs that failed normalization:**

```sql
SELECT id, file_name, file_type, normalization_error
FROM jobs
WHERE normalization_error IS NOT NULL AND normalization_error != '';
```

**Dead-letter queue size:**

```sql
SELECT COUNT(*) FROM failed_extractions WHERE status = 'pending';
```

### Interpreting Results

- **Extraction phase dominates** → LLM is the bottleneck; consider smaller context, parallel chunks (if added), or a faster model.
- **High validation failure rate** → Prompt or schema may need tuning; or model (e.g. 4b) may be underperforming.
- **Many normalization_error rows** → Check file types and OCR/config for problematic inputs.
- **Large DLQ** → Review `last_error` and `chunk_text_uri` in `failed_extractions` to fix schema or prompts.

---

## 4. Evaluating Extraction Quality for the Next Pipeline

Downstream pipelines need **valid, complete records** that match your schema. You can assess this using existing telemetry plus exported results.

### What the Next Pipeline Needs

- **Schema compliance**: Every exported record validates against your Pydantic model.
- **Coverage**: No systematic missing rows or fields when the source document contained the data.
- **Low error rate**: Few validation failures and few items in the dead-letter queue.

### Metrics You Already Have

- **Schema compliance**: From `llm_runs.validation_passed` and `failed_extractions`. For a batch run, report:
  - Percentage of chunks that passed validation on the first attempt.
  - Percentage of jobs with at least one DLQ entry.
- **Throughput**: From `jobs.completed_chunks` vs `jobs.total_chunks`; jobs with `status = 'partial'` or `'failed'` indicate incomplete extraction.

### Exporting Results for Inspection

Export extracted records for a job (or many jobs) to JSONL:

```bash
hermes export <job_id> --format jsonl --output results_<job_id>.jsonl
```

Then you can:

- **Count records per job**: Compare number of lines in the JSONL to expected count (e.g. one contract per file).
- **Sample and inspect**: Open a few files and check that key fields (e.g. vehicle ID, premium) are present and plausible.
- **Compare to ground truth**: If the source data came from a dataset with known fields (e.g. RISCBAC), write a small script to join exported JSON to the source rows and compute agreement or accuracy for key fields.

### Optional: Quality Script

A small script can:

1. Connect to the Hermes SQLite DB (e.g. `~/.hermes/hermes.db` or the path from your config).
2. Aggregate telemetry: total time by stage, total tokens, validation pass rate, DLQ count.
3. For a sample of completed jobs, run `hermes export <job_id> --format jsonl` (or read from `extraction_results` and flatten `record_json`) and compare to ground truth if available.

That gives you a single report for **bottlenecks** (section 3) and **extraction quality** (section 4) after a large batch run.
