# Hermes — Analysis and Next Steps

## Current State Assessment

Hermes is a local-first, memory-safe, LLM-powered document extraction engine. It converts Excel and PDF documents into validated, structured JSON using Pydantic schemas and local (Ollama) or cloud (LiteLLM) LLMs.

### What exists today (v0.1.0)

| Capability | Status | Notes |
|---|---|---|
| Ingestion (Excel, text PDF, scanned PDF) | Solid | Preflight detection, streaming normalization, OCR fallback chain (surya → easyocr → none) |
| Normalization to Markdown | Solid | Page-by-page, memory-safe; pixmaps freed immediately; Excel streamed 50 rows at a time |
| Context-window-aware chunking | Solid | Table-aware row splitting, overlap, merge of small pages |
| LLM extraction with repair loop | Solid | Pydantic validation, multi-attempt repair, works with both local and cloud models |
| Observability | Solid | Per-call token counts, latency, prompt version hashing, pipeline stage durations |
| Dead-letter queue | Solid | Failed chunks stored with context, retryable with different model |
| CLI | Solid | `extract`, `status`, `export`, `retry`, `init`, `test`, `version` |
| Concurrency | Solid | Sequential for Ollama, bounded ThreadPoolExecutor for cloud, WAL SQLite |
| Test suite | Solid | Unit tests + synthetic dataset generation + full pipeline telemetry test |
| Schema-driven extraction | Solid | Dynamic Pydantic model loading via `module:ClassName` |

**Bottom line:** Layer 1 (extraction substrate) is production-grade. The pipeline is correct, observable, memory-safe, and handles failures gracefully. This is the foundation everything else builds on.

---

## Architecture Layers

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Assisted Underwriting (paid, later)               │
│  Rules packs, coverage gap detection, enrichment hooks      │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Triage & Packaging (adoption driver)              │
│  Doc-type routing, missing-field detection, canonical JSON, │
│  export artifacts (checklists, summaries, email drafts)     │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Extraction Substrate (done)                       │
│  Streaming, memory safety, schema validation, DLQ,          │
│  telemetry, prompt versioning, repair loop                  │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 2: Triage and Packaging

This is the layer that makes Hermes useful to a broker or underwriter without requiring them to define schemas or write code. Each feature below is ordered by impact-to-effort ratio.

### 2.1 Document-type classifier

**What:** Before extraction, classify the incoming document as one of: `submission`, `schedule`, `loss_run`, `endorsement`, `policy`, `invoice`, `certificate`, `unknown`.

**Why:** Different document types need different schemas, different required fields, and different downstream actions. Today the user must manually pick a schema. This step removes that friction.

**How:**
- Add a `DocumentType` enum to `hermes/models.py`.
- Add a `hermes/triage/classifier.py` module. First pass: an LLM call on the first chunk with a classification prompt. Second pass (later): a lightweight local classifier (e.g., a fine-tuned sentence transformer) to avoid LLM cost for triage.
- Wire into `pipeline.py` between preflight and normalization. Store result on the `Job` model.
- Map each `DocumentType` to a default schema so `hermes extract invoice.pdf` auto-selects the right Pydantic model without `--schema`.

**Effort:** Small-medium. One new module, one new pipeline stage, one new column on `jobs`.

### 2.2 Insurance-domain schemas

**What:** Ship a set of production-quality Pydantic schemas for common insurance document types.

**Why:** `GenericRow` and `VehicleRecord` are demos. Real adoption requires schemas that match what brokers and underwriters actually handle.

**Schemas to build:**

| Schema | Fields (representative) |
|---|---|
| `SubmissionRecord` | insured_name, address, line_of_business, effective_date, expiration_date, premium, limits, deductibles, prior_carrier, loss_history_summary |
| `ScheduleItem` | item_number, description, location, value, coverage, limit, deductible |
| `LossRunEntry` | claim_number, date_of_loss, claimant, status, paid, reserved, incurred, description |
| `EndorsementRecord` | endorsement_number, effective_date, description, premium_change, coverage_change |
| `CertificateRecord` | certificate_holder, insured, policy_number, coverage_type, limits, effective_date, expiration_date |

**How:** Add to `hermes/schemas/insurance/`. Each file is a self-contained Pydantic model with field descriptions that guide the LLM.

**Effort:** Medium. Schema design requires domain knowledge; implementation is straightforward Pydantic.

### 2.3 Required-field contracts and missing-info detection

**What:** For each document type, define a set of fields that *must* be present. After extraction, compare results against the contract and report gaps.

**Why:** The number-one pain point for underwriters is "the broker sent me incomplete information and I have to chase them." Hermes can automate the detection.

**How:**
- Add a `RequiredFieldContract` model: a mapping of `DocumentType` → `list[str]` of required field names.
- Add a `hermes/triage/completeness.py` module that takes extraction results and the contract, returns a `CompletenessReport` listing missing and present fields with confidence.
- Surface in CLI: `hermes check <job_id>` prints the gap report.
- Surface in export: the report can be included in JSON/CSV output or rendered as a summary.

**Effort:** Small. The hard part is defining *which* fields are required for each type — this is configuration, not code.

### 2.4 Canonical "Submission JSON" output

**What:** Define a stable, versioned JSON schema that represents a complete insurance submission. This becomes the integration surface for downstream systems.

**Why:** Extraction output today is schema-dependent and varies by run. A canonical format lets brokers, underwriters, and systems consume Hermes output without knowing which Pydantic model was used internally.

**How:**
- Define a `CanonicalSubmission` JSON Schema (or Pydantic model) that normalizes across document types.
- Add a post-extraction step that maps extraction results into the canonical format.
- Version the canonical schema (e.g., `v1`, `v2`) so consumers can pin to a version.
- `hermes export <job_id> --format submission-json` emits the canonical format.

**Effort:** Medium. Requires careful schema design. Implementation is a mapping layer.

### 2.5 Export artifacts for humans

**What:** Generate human-readable outputs from extraction results.

**Artifacts:**
- **Submission checklist:** "Here's what we have, here's what's missing, here's what looks suspicious."
- **Summary PDF:** A one-page overview of the submission with key fields highlighted.
- **Email draft:** A templated email to the broker listing missing items, ready to send.
- **Comparison view:** Side-by-side diff when a document is re-submitted (endorsement vs. original).

**How:**
- Add `hermes/export/` module with renderers for each format.
- Checklist and email draft can be Jinja2 templates populated from extraction results + completeness report.
- Summary PDF can use a lightweight library (e.g., `weasyprint` or `fpdf2`).
- Wire into CLI: `hermes export <job_id> --format checklist|summary|email`.

**Effort:** Medium. Each artifact is independent; can be shipped incrementally.

---

## Memory and Performance Hardening

These are engineering improvements that affect all layers. They matter because the target deployment is on-prem hardware with limited resources, and because the market will stress-test the pipeline with real documents (scanned multi-hundred-page PDFs, huge Excel workbooks).

### M.1 OCR memory pressure

**Problem:** Scanned PDFs go through `page → image → OCR → text`. Image buffers are large. At concurrency > 1, multiple pages' image buffers can coexist in RAM, leading to OOM on modest hardware.

**Mitigation:**
- **Bounded OCR concurrency:** Process OCR pages through a semaphore (e.g., `max_ocr_workers=2`) independent of LLM workers. OCR is CPU-bound; LLM extraction is I/O-bound. They shouldn't share the same pool.
- **Explicit buffer cleanup:** After OCR completes for a page, explicitly `del` the image array and call `gc.collect()` before processing the next page. This is partially done today (pixmaps freed in `pdf_ocr.py`) but should be audited for the OCR engine's internal buffers.
- **DPI adaptation:** The config already has `ocr_dpi` and `ocr_max_dpi`. Add a memory-pressure heuristic: if the system has < N GB free, reduce DPI automatically.

### M.2 Chunking memory

**Problem:** If all pages are loaded and concatenated before chunking, the full normalized text lives in memory as one string.

**Current state:** Hermes already reads page files one at a time in `chunk_pages()` — this is good. But `_merge_segments` accumulates segment text in a list before emitting chunks. For very large documents this list can grow.

**Mitigation:**
- Consider a streaming chunker that yields `Chunk` objects as they become ready, rather than building the full list first. This lets the pipeline start LLM extraction on early chunks while later pages are still being normalized.
- This also enables a producer-consumer architecture: normalizer produces pages → chunker consumes and yields chunks → LLM workers consume chunks. Memory at any point is bounded by the pipeline's depth, not the document's size.

### M.3 Excel memory

**Problem:** Large workbooks with many sheets or thousands of rows can balloon if intermediate representations (e.g., full sheet text) are kept in memory.

**Current state:** Hermes streams 50 rows at a time via `openpyxl` read-only mode. This is correct.

**Mitigation:**
- Audit for any code paths that accumulate all rows before writing to disk. The page-level write should happen per batch.
- For very wide sheets (100+ columns), consider column-pruning heuristics (drop columns that are entirely empty or contain only formatting).

### M.4 Parallel pipeline stages

**Problem:** Today the pipeline is sequential: normalize all → chunk all → extract all. The LLM sits idle during normalization and chunking.

**Mitigation:**
- Implement a producer-consumer pipeline where normalization feeds chunks to extraction as they become available.
- This overlaps I/O (normalization, disk writes) with compute (LLM calls), reducing total wall time.
- Use `asyncio` or `queue.Queue` with a bounded buffer to control memory.

---

## Layer 3: Assisted Underwriting (paid tier)

This layer is where monetization lives. It builds on top of the extraction and triage layers.

### 3.1 Rules packs (appetite and exclusions)

**What:** Configurable rule sets that evaluate extracted data against underwriting criteria.

**Examples:**
- "We don't write flood in Zone A."
- "Auto fleet: decline if average vehicle age > 10 years."
- "GL: flag if no prior insurance history."

**How:**
- Define a `Rule` model: condition (a Python expression or DSL), action (`flag`, `decline`, `refer`), severity, message.
- Rules are loaded from YAML/TOML files, organized by line of business.
- A `hermes/underwriting/rules_engine.py` evaluates rules against extraction results.
- Output is a `UnderwritingReport` with pass/fail/flag per rule.

### 3.2 Coverage gap detection

**What:** Compare the requested coverage against the insured's risk profile to identify gaps.

**Examples:**
- "Property schedule lists 5 locations but only 3 have flood coverage."
- "Cyber liability not included despite $10M+ revenue."
- "Umbrella limit is $1M but underlying auto is $500K — gap."

**How:**
- Define coverage templates per line of business.
- Post-extraction, compare the extracted schedule/coverage against the template.
- Flag gaps as advisory notes in the underwriting report.

### 3.3 Enrichment hooks

**What:** Plug in external data sources to augment extracted data.

**Examples:**
- Claims history lookup (from carrier or third-party).
- Geocoding addresses to assess catastrophe exposure.
- Company info enrichment (revenue, employee count, SIC/NAICS code).
- OFAC / sanctions screening.

**How:**
- Define a `HermesHook` interface: `async def enrich(record: dict) -> dict`.
- Ship a few built-in hooks (geocoding via free APIs, basic company lookup).
- Allow users to register custom hooks in config.
- Hooks run post-extraction, pre-rules-evaluation.

---

## The Privacy Wedge — Sharpening the Differentiator

The strongest market position is not "universal extraction" (many tools do that). It is **data boundary control + auditability**:

| Capability | What it means for procurement |
|---|---|
| Local-first, runs offline with Ollama | No data leaves the machine. Passes infosec review without a vendor security questionnaire. |
| Schema-driven validation | Every output is deterministic against a known contract. Auditors can verify. |
| DLQ replay | Every failure is recoverable. No silent data loss. |
| Prompt version hashing (SHA-256) | Every extraction is reproducible. "Which prompt produced this result?" is always answerable. |
| Full telemetry (tokens, latency, model, validation) | Compliance teams can audit cost, accuracy, and model drift over time. |

### Actions to sharpen this:

1. **Add a `hermes audit <job_id>` command** that prints a complete provenance chain: file hash → normalization → chunks → LLM calls (with prompt versions) → validation → output. One command, full traceability.

2. **Add data residency documentation.** A single markdown file (`DATA_RESIDENCY.md`) that maps every data flow: what goes where, what's stored, what's transmitted. This is the document infosec teams ask for.

3. **Add an air-gapped deployment guide.** Step-by-step instructions for running Hermes + Ollama on a machine with no internet. This is the proof point for "no data leaves your machine."

4. **Prompt immutability option.** A config flag that locks prompts to a specific version hash and refuses to run if the current prompt hash doesn't match. This guarantees reproducibility for regulated environments.

---

## Distribution and Go-to-Market Strategy

```
Open-source (Layer 1 + most of Layer 2)
├── Extraction substrate (full)
├── Document-type classifier
├── Insurance schemas (basic set)
├── Missing-info detection
├── Canonical JSON export
├── CLI + export artifacts (checklist, email draft)
└── Air-gapped deployment docs

Paid (Layer 3 + hardening)
├── Rules packs (appetite, exclusions, referral logic)
├── Coverage gap detection
├── Enrichment hooks (claims, geocoding, company data)
├── On-prem hardening (HA, monitoring, backup, upgrade)
├── Custom schema development
├── SLA + support
└── Managed deployment
```

**Rationale:** Open-sourcing Layer 1 and Layer 2 builds trust ("try it for free, see that it works, see that your data stays local"). Layer 3 is where the domain expertise lives — rules packs, coverage logic, enrichment integrations. That's consulting-grade work that justifies a paid tier.

---

## Recommended Execution Order

### Phase 1 — Triage foundation (weeks 1–3)

| # | Task | Depends on | Deliverable |
|---|---|---|---|
| 1 | Document-type classifier | — | `hermes/triage/classifier.py`, `DocumentType` enum, auto-schema selection |
| 2 | Insurance-domain schemas (submission, schedule, loss run) | — | `hermes/schemas/insurance/` with 3–5 production schemas |
| 3 | Required-field contracts | #2 | `hermes/triage/completeness.py`, `hermes check` CLI command |
| 4 | `hermes audit` command | — | Provenance chain output for any job |

### Phase 2 — Packaging and polish (weeks 4–6)

| # | Task | Depends on | Deliverable |
|---|---|---|---|
| 5 | Canonical Submission JSON | #1, #2 | Versioned JSON schema, `--format submission-json` export |
| 6 | Export artifacts (checklist, email draft) | #3 | Jinja2 templates, `--format checklist\|email` |
| 7 | Streaming pipeline (normalize → chunk → extract overlap) | — | Producer-consumer pipeline, reduced wall time |
| 8 | OCR memory hardening (semaphore, buffer cleanup) | — | Bounded OCR concurrency, explicit GC |

### Phase 3 — Privacy and distribution (weeks 7–8)

| # | Task | Depends on | Deliverable |
|---|---|---|---|
| 9 | `DATA_RESIDENCY.md` | — | Data flow documentation for infosec review |
| 10 | Air-gapped deployment guide | — | Step-by-step offline setup (Hermes + Ollama) |
| 11 | Prompt immutability mode | — | Config flag, hash verification on startup |
| 12 | PyPI package release | All above | `pip install hermes-extract`, clean entry point |

### Phase 4 — Assisted underwriting (weeks 9+)

| # | Task | Depends on | Deliverable |
|---|---|---|---|
| 13 | Rules engine | #2, #5 | `hermes/underwriting/rules_engine.py`, YAML rule packs |
| 14 | Coverage gap detection | #2, #13 | Gap analysis report |
| 15 | Enrichment hooks interface | #5 | `HermesHook` protocol, geocoding example |

---

## Open Questions

1. **Schema marketplace or schema builder?** Should Layer 2 include a CLI/UI tool that helps users *build* schemas interactively (e.g., `hermes schema new` walks through field definition)? This lowers the bar for non-developer users.

2. **Multi-document jobs.** Today each file is a separate job. Submissions often arrive as a bundle (app + schedule + loss runs in separate files). Should Hermes support a "submission" abstraction that groups multiple jobs and cross-references them?

3. **Web UI.** The CLI is powerful but not accessible to non-technical users. A lightweight web interface (FastAPI + HTMX or similar) for uploading documents, viewing results, and running checks would dramatically broaden the user base. When to build this?

4. **Accuracy benchmarks.** The test suite generates synthetic data. Real-world accuracy on actual insurance documents is unknown. Building a benchmark suite with anonymized real documents would establish credibility. Is there access to such data?

5. **Model recommendations.** Which Ollama models perform best for insurance document extraction? Running a structured evaluation across qwen3:4b, qwen3:8b, llama3.1:8b, and mistral:7b on the existing test suite would produce a concrete recommendation for users.
