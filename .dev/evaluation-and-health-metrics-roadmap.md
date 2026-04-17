# Evaluation & health metrics — implementation queue

This document queues work to **measure extraction quality** (eval) and to **quantify and demonstrate** Hermes’s positioning as **memory-safe** and **scalable**. It is not an implementation spec; it captures practices, tradeoffs, tool options, and concrete next steps.

---

## Part A — Evaluation (quality)

### Why eval is hard for a “universal” engine

Hermes is **schema-agnostic**: users supply Pydantic models, so there is no single global accuracy number comparable across deployments. Evaluation must be framed as:

- **Contract adherence** — Does output validate against the user schema? (already partially covered by validation + repair counts.)
- **Fidelity to source** — Do field values match what is in the document? (requires labels or golden outputs.)
- **Robustness** — Degradation under noise, long documents, OCR, merged cells, etc.

### Recommended eval layers (stack them)

| Layer | What it measures | Cost | When to use |
| ----- | ---------------- | ---- | ----------- |
| **Schema / constraint pass rate** | JSON parses, Pydantic validates, required fields present | Low | Every run; baseline health |
| **Stratified chunk labels (positive / negative)** | Per-chunk or page-range labels: *positive* = source should yield ≥1 valid record (optional golden JSON later); *negative* = no target entities — score abstention (no hallucinated rows) and optionally treat valid empty output as success | Low–medium | Before relying on a single job pass rate; separates “no entities in this chunk” from extraction mistakes |
| **Golden-file regression** | Byte- or normalized JSON diff vs saved expected output for fixed fixtures | Low–medium | CI on every change |
| **Field-level match** | Per-field equality or fuzzy match vs ground truth (CSV/JSONL keyed by row id) | Medium | Per-domain benchmarks you maintain |
| **LLM-as-judge** | Rubric-based scoring of extraction vs source text | Medium–high | Spot checks, not sole metric |
| **Human review** | Sampled rows with adjudication | High | Calibration, new document types |

**How stratified labels relate to golden eval**

Labels are the **scaffold**: cheap to author (even heuristically — e.g. “endorsement block present” vs “boilerplate only”). **Full golden outputs** (expected JSON per chunk) sit on top for strict regression. Without labels, aggregate metrics can treat **correct abstention** on negative chunks as failure when the engine requires ≥1 validated record to count success — so report **pass rate on positives** and **false-positive rate on negatives** separately before trusting one headline number.

**Best practices (this product category)**

1. **Version everything** — Fixture files, schema refs, prompt version (already hashed in `llm_runs`), model name, and eval script commit SHA. Reproducibility beats a single headline score.
2. **Separate “parser health” from “semantic accuracy”** — High validation pass rate can still mean wrong business values. Report both where possible.
3. **Stratify by modality** — Excel vs text PDF vs scanned PDF vs mixed; chunk boundaries affect LLM behavior.
4. **Per-chunk and per-job aggregates** — Report mean/median and p95; one bad chunk should not be hidden in a mean.
5. **Failure taxonomy** — Tag errors: `schema_reject`, `repair_exhausted`, `ocr_low_confidence`, `hallucinated_field`, etc. Drives product fixes better than one accuracy %.
6. **Avoid training on your eval set** — If you tune prompts on the same golden files, scores inflate; hold out a frozen set.
7. **Stratify expected outcomes** — For each fixture, tag chunks (or page ranges) as **positive** (must extract) vs **negative** (must not invent entities). Optionally define whether an empty validated result is **allowed** on negatives so eval matches product rules.

### Tradeoffs

| Choice | Upside | Downside |
| ------ | ------ | -------- |
| **Small curated goldens** | Fast CI, clear regressions | May not represent user documents |
| **Large synthetic data** | Scale, control | Generator bias; may not match real layouts |
| **User-uploaded eval (opt-in)** | Realistic | Privacy, inconsistency, hard to automate |
| **Single aggregate “accuracy”** | Easy to communicate | Misleading for multi-field, multi-table extractions |
| **Strict per-field equality** | Objective | Brittle on formatting, synonyms, locale |
| **Normalized comparison** (lower case, strip punctuation, numeric tolerance) | Practical | Needs careful definition per field type |

### Products & tooling (reference)

Useful as **patterns** even if Hermes stays primitives based or local:

- **LangSmith / Langfuse** — Traces, datasets, human annotation, A/B prompts. Strong when you already use LangChain-style flows; Hermes would need adapters to log runs.
- **Braintrust** — Scoring functions, eval loops, comparisons across prompts/models; good fit for “run extraction → score → diff.”
- **Weights & Biases (W&B)** — Experiment tracking; heavier than needed for a CLI unless you run large sweeps.
- **Open-source / self-hosted** — **Phoenix (Arize)**, **Langfuse** self-hosted: trace + eval UI without vendor lock-in.
- **No vendor** — JSONL goldens + `pytest` + small Python scorer (field-level diff) is enough for v1; SQLite already stores runs for offline analysis.

**Queued implementation (eval)**

- [x] **Stratified eval manifest** — For frozen fixtures, a small JSON/YAML mapping (chunk index or page range → `positive` | `negative`, optional notes). Drive **separate** metrics: recall / extraction success on positives; false positives (and optional “allowed empty”) on negatives.
- [x] **Scorer rules for negatives** — Align with product: if empty extraction is valid when no entities exist, the scorer should not count that as a regression (Hermes’s current validator may still mark the chunk failed — eval can bridge that gap until behavior changes).
- [x] **Golden outputs** — For 1–3 frozen fixtures (Excel + PDF), commit expected JSONL (or normalized form) + a scorer script (field match + tolerances for numbers/dates).
- [x] **`hermes eval` or `pytest` entry** — Run pipeline on fixtures, compare to golden, exit non-zero on regression; optional `--update-goldens`.
- [x] **Align naming** — Renamed synthetic Excel to `test_excel_stress_synthetic.xlsx` (was `test_excel_accuracy_synthetic.xlsx`); docs describe stress/integration vs `hermes eval` goldens.
- [x] **Optional export** — Emit eval results as JSON for CI artifacts (JUnit-style or custom).
- [x] **Docs** — Short “How we measure quality” section in README pointing to this roadmap.

---

## Part B — Memory-safe & scalable: quantify and show

Hermes claims **memory-safe** (bounded RAM, streaming, page-at-a-time) and **scalable** (workload size, parallelism with cloud, WAL SQLite). Marketing claims need **measurable** backing.

### What to measure

**Memory (memory-safe)**

| Metric | Definition | How to collect |
| ------ | ---------- | -------------- |
| **Peak RSS** | Max resident set size during a run | `psutil.Process().memory_info().rss` sampled in pipeline stages, or `/usr/bin/time -v` / Windows equivalents |
| **RSS curve** | RSS vs wall time | Sample every N seconds or at stage boundaries |
| **Per-stage peak** | Max RSS during preflight, normalize, chunk, extract | Stage markers + sampling |
| **OOM boundary** (lab) | Largest file / page count before failure on a reference machine | Stress matrix documented in README or bench doc |

**Throughput & latency (scalable)**

| Metric | Definition | Notes |
| ------ | ---------- | ----- |
| **Pages / minute** (PDF) | Normalized pages processed per minute | Split by text vs OCR |
| **Rows / minute** (Excel) | Rows streamed through normalization | |
| **Chunks / minute** | LLM-bound throughput | Varies heavily by model and `workers` |
| **End-to-end latency** | p50/p95 job time by document size bucket | |
| **LLM cost proxy** | Tokens in+out × price (if cloud) | Already have token counts in DB |

**Health / reliability**

| Metric | Source |
| ------ | ------ |
| Validation pass rate | `llm_runs.validation_passed` |
| Repair rate | Count `run_type == repair` / total runs |
| DLQ depth | `failed_extractions` pending count |
| Chunk failure rate | `failed_chunks` / `total_chunks` on job |

### How to show it (audience-dependent)

1. **Reproducible benchmark script** — One command (e.g. `python scripts/bench_memory.py` or `hermes bench`) that runs a standard workload and prints RSS peak + duration + token totals. Store results in CI artifacts or a `benchmarks/` table in docs (date, machine spec, commit).
2. **Charts for releases** — Simple line charts: RSS over time for a 200-page PDF; throughput vs `workers` for LiteLLM. Generated from CSV logs in CI or manually per release.
3. **Documentation table** — “Reference hardware: … | Workload: … | Peak RSS: … | Wall time: …” so claims are checkable.
4. **Regression gates (optional)** — CI fails if peak RSS or duration exceeds a threshold vs baseline (flaky on shared runners; better on dedicated or self-hosted).

### Structlog & telemetry (implementation direction)

Today the codebase uses **stdlib `logging`**. Moving toward **structured logs** makes aggregation and dashboards feasible without losing local-first operation. [Update, hermes is no longer local first but rather local is a feature]

**Recommended approach**

- Add **`structlog`** (or `logging` JSON formatter) with a **fixed schema** per event: `event`, `job_id`, `stage`, `duration_ms`, `peak_rss_bytes`, `file_type`, `page_count`, `chunk_index`, `workers`, `model`, etc.
- **Dual sink**: human-readable console (existing UX) + **NDJSON file** under `storage/` or `~/.hermes/logs/` for analysis.
- **Correlation**: propagate `job_id` (and optional `trace_id`) through pipeline, normalization, and LLM client.
- **Sampling** — RSS every stage transition + optional periodic sample during long normalization to catch spikes.

**Queued implementation (observability & proof points)**

- [x] Define **log schema** (fields above + version field for schema evolution).
- [x] Introduce **structlog** (or structured JSON) behind a config flag `log_format = "json" | "console"`.
- [x] **RSS sampling** helper used at stage boundaries in `pipeline.py` (optional dependency on `psutil`; degrade gracefully if absent).
- [x] **`hermes bench` or documented script** — Standard workloads + RSS/duration output; optional CSV export.
- [x] **README subsection** — “Benchmarks & memory” with one table of reference numbers and methodology (file sizes, hardware, provider).
- [x] **CI artifact** — Upload bench summary JSON on main-branch runs (if stable enough).

### Tradeoffs (telemetry vs simplicity)

| Approach | Pros | Cons |
| -------- | ---- | ---- |
| Stdlib only | Zero deps | Hard to parse programmatically |
| structlog + NDJSON | Queryable, local-first | Another dependency, doc for users |
| Full OTel | Industry standard | Heavy for a CLI; export often unused locally |
| SQLite only (current) | Already queryable | No time-series of RSS; need code to record |

---

## Summary

- **Eval** should combine **schema health**, **stratified positive/negative chunk labels** (before trusting aggregate pass rates), **golden regressions**, and optionally **field-level** scores—with versioning and stratified reporting—not a single opaque “accuracy.”
- **Memory-safe & scalable** claims should be backed by **peak RSS**, **stage-level breakdown**, **throughput**, and **documented benchmark methodology**; **structlog + optional NDJSON** plus a **small bench harness** are the practical path to “show, don’t tell.”

This file is the queue; implement in small PRs aligned with release priorities.
