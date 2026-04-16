# Part B — Memory-safe & scalable: Orchestrator Plan

**Version:** 0.1 · **Status:** Draft · **Source:** `.dev/evaluation-and-health-metrics-roadmap.md` Part B (lines 75–143)

---

## 1. Task statement

Hermes markets itself as **memory-safe** (bounded RAM, streaming, page-at-a-time) and **scalable** (workload size, parallelism with cloud, WAL SQLite). Part B turns those claims into measurable, reproducible artifacts by layering observability + a benchmark harness on top of the existing pipeline:

1. A **fixed, versioned log schema** covering stage boundaries, RSS samples, throughput counters, and LLM cost proxies.
2. **Structured logging** (`structlog` or stdlib + JSON formatter) with a **dual sink**: human-readable console (existing UX preserved) + NDJSON file under a configurable logs directory, behind a config flag `log_format = "json" | "console"`.
3. An **RSS sampling helper** wired at pipeline stage transitions (preflight / normalize / chunk / extract) with **optional `psutil`** and graceful degradation when absent.
4. A **benchmark command** (`hermes bench` or documented script) that executes a standard workload set and emits a summary of peak RSS, wall time, throughput (pages/rows/chunks per minute), token totals, and cost proxy.
5. **Docs** — a README "Benchmarks & memory" subsection with a reference-hardware table and methodology so claims are checkable.
6. **CI artifact** — upload the bench summary JSON on main-branch runs (best-effort; flaky regression gates explicitly out of scope).

The deliverable is: structured logs correlated by `job_id`, a repeatable bench command, a CSV/JSON output that can be charted per release, and docs that make the memory-safe/scalable claims auditable.

**Non-goals:**

- **Regression gates / CI fail-on-threshold** — the roadmap flags these as flaky on shared runners; track but do not block CI.
- **Full OpenTelemetry** — explicitly listed as "heavy for a CLI, export often unused locally" in the tradeoff table; not chosen for v1.
- **Remote metric sinks** (Prometheus, Grafana, Datadog, LangSmith, Braintrust) — local NDJSON is the v1 path.
- **Chart generation in-process** — charts are generated manually per release from CSV/JSON. No plotting dependency added.
- **Time-series storage of RSS inside SQLite** — the tradeoff table notes this is possible but not chosen; NDJSON is the artifact.
- **Changes to extraction, normalization, or LLM-call semantics** — Part B observes; it does not change pipeline behavior.
- **Part A** (eval manifests, scorer, `hermes eval`) — separate plan at `.dev/eval/eval-plan.md`.
- **Replacing stdlib `logging` wholesale** — existing console UX must be preserved via dual sink.
- **Synthetic workload generation for stress tests** — `hermes bench` uses existing fixtures (`tests/generate_fixtures.py`) and any committed/user-supplied files, not new large-file synthesis.

---

## 2. Shared contracts

Constraints binding **all** subagents. Drift here is the costliest failure mode.

### Types / interfaces

| Symbol | Location | Description |
|--------|----------|-------------|
| `LogSchemaVersion` | `hermes/obs/schema.py` | String constant (semver-ish: `"1.0"`). Every NDJSON event carries `schema_version`. |
| `EventName` | `hermes/obs/schema.py` | Literal/enum of canonical event names: `stage.start`, `stage.end`, `rss.sample`, `chunk.done`, `llm.call`, `job.start`, `job.end`, `bench.workload.start`, `bench.workload.end`, `bench.summary`. |
| `StageName` | `hermes/obs/schema.py` | Literal: `preflight` \| `normalize` \| `chunk` \| `extract` \| `repair` \| `export`. Matches existing pipeline stage terminology. |
| `BaseEvent` | `hermes/obs/schema.py` | Pydantic model (or TypedDict): `schema_version: str`, `ts: str` (ISO8601 UTC), `event: EventName`, `job_id: str \| None`, `trace_id: str \| None`, plus event-specific fields. |
| `RSSSample` | `hermes/obs/sampling.py` | Dataclass or dict: `ts`, `job_id`, `stage: StageName`, `rss_bytes: int`, `note: str \| None`. Conforms to `event="rss.sample"`. |
| `get_logger(name: str)` | `hermes/obs/logging.py` | Factory returning a structlog `BoundLogger` (or stdlib adapter) preconfigured with schema-version + sinks. |
| `bind_job(job_id, **kwargs)` | `hermes/obs/logging.py` | Context manager / helper that binds `job_id` (and optional `trace_id`) to the logger for the duration of a job. |
| `sample_rss(stage, job_id, logger)` | `hermes/obs/sampling.py` | Emits an `rss.sample` event. No-op (with a single warning on first call) when `psutil` missing. |
| `BenchWorkload` | `hermes/bench/runner.py` | Pydantic model: `name: str`, `input_path: Path`, `schema_ref: str`, `file_type: Literal["pdf", "excel"]`, `expected_page_count: int \| None`, `workers: int`, `model: str`. |
| `BenchResult` | `hermes/bench/runner.py` | Pydantic model: `workload: str`, `commit: str`, `machine: dict[str, str]`, `duration_s: float`, `peak_rss_bytes: int`, `pages_per_minute: float \| None`, `rows_per_minute: float \| None`, `chunks_per_minute: float \| None`, `tokens_in: int`, `tokens_out: int`, `cost_proxy_usd: float \| None`, `validation_pass_rate: float`, `timestamp: str`. |
| `BenchSummary` | `hermes/bench/runner.py` | List of `BenchResult` + top-level metadata (commit, date, environment). |
| Config fields | `hermes/config.py` | `log_format: Literal["json", "console"] = "console"`, `log_dir: Path = storage/logs`, `rss_sampling_enabled: bool = True`. Back-compat defaults. |

### Error envelope

Observability must never crash or slow the hot path. All failures degrade silently (with a one-time warning) and are recorded as structured events rather than raised.

| Case | Behavior |
|------|----------|
| `psutil` not installed | `sample_rss()` emits one `warn` event (`rss.sample.unavailable`) on first call, then no-ops |
| `structlog` not installed | Fall back to stdlib `logging` + `JSONFormatter`; console sink still works; emit one `warn` event at startup |
| NDJSON sink write fails (disk full, permission) | Log the failure to stderr once; continue in console-only mode; never block pipeline |
| Invalid `log_format` value in config | Fall back to `"console"`; log a config warning |
| `hermes bench` workload fails mid-run | Emit `bench.workload.end` with `status: "error"`, `error: str`; continue with remaining workloads; non-zero exit at end |
| Missing fixture file for bench | Skip workload with `status: "skipped"`; do not crash |
| `BenchResult` missing optional fields (e.g. no page count for Excel) | Serialize as `null`; downstream readers must tolerate |

### Naming

| Kind | Convention |
|------|-----------|
| Packages | `hermes/obs/` (schema, logging, sampling) and `hermes/bench/` (runner, workloads). Rationale: observability is cross-cutting; bench is a user-facing command. |
| Modules | `hermes/obs/__init__.py`, `hermes/obs/schema.py`, `hermes/obs/logging.py`, `hermes/obs/sampling.py`, `hermes/bench/__init__.py`, `hermes/bench/runner.py`, `hermes/bench/workloads.py` |
| Test files | `tests/test_obs_schema.py`, `tests/test_obs_logging.py`, `tests/test_obs_sampling.py`, `tests/test_bench_runner.py` |
| CLI subcommand | `hermes bench` (Typer command added to `hermes/cli.py`) |
| NDJSON log files | `<log_dir>/hermes-<YYYYMMDD>.ndjson` — one file per day, append mode. `log_dir` resolvable via config (default: `storage/logs/`). |
| Bench output files | `benchmarks/<YYYYMMDD>_<short-sha>.json` (committed optionally) and optional CSV sibling `.csv` |
| Event names | Dotted: `<domain>.<action>` — e.g. `stage.start`, `rss.sample`, `bench.workload.end`. Keep lowercase, snake_case after dot. |
| Config flags | `log_format`, `log_dir`, `rss_sampling_enabled` — snake_case, in `hermes/config.py` |
| Optional deps | `structlog`, `psutil` — added under a new optional extra `[obs]` in `pyproject.toml` so base install stays minimal |

### Logging

- **Dual sink** is mandatory: every event flows to the existing console renderer (human-readable, respects current UX) **and** to an NDJSON file when `log_format=="json"` is also enabled (they are independent: console always on; NDJSON on when enabled).
- **Correlation:** every event inside a job carries `job_id`. `hermes bench` adds `bench_run_id` (a UUID) on bench-scope events so multi-workload runs can be reassembled.
- **Schema versioning:** `schema_version` is on every event. Bump on any breaking change (field removed, renamed, type changed). Additive changes (new optional field) do not bump the version.
- **Sampling cadence:** RSS sampled at stage boundaries (start + end of `preflight`, `normalize`, `chunk`, `extract`) and optionally on a timer during long normalization (config: `rss_sampling_interval_s`, default `0` = off, boundaries only).
- **No secrets in events** — never log API keys, full prompts, or full record payloads. Log counts, sizes, hashes, token totals.
- **Logger names:** `hermes.obs.*`, `hermes.bench.*`; pipeline modules retain their existing `logging.getLogger(__name__)` names but route through the new adapter.
- **Level policy:** `stage.*`, `rss.sample`, `chunk.done`, `llm.call` emit at `INFO`. Failures at `ERROR`. Fallback/degradation warnings at `WARN`, emitted once per process.

### Tests

- Framework: **pytest** (existing).
- Location: `tests/test_obs_*.py`, `tests/test_bench_*.py`.
- Naming: `test_<module>_<behavior>`.
- Coverage expectation: every public function in `hermes/obs/` and `hermes/bench/` has at least one positive test; error envelope cases each get a dedicated test (psutil missing, disk-full sink, invalid config, bench workload failure).
- Determinism: RSS and timing assertions must be tolerance-based (e.g. `peak_rss_bytes > 0`, `duration_s < 60`) — **never** assert exact numbers. The bench runner is tested with a mocked/no-op pipeline path for unit tests; end-to-end bench validation is a manual / nightly concern, not a CI blocker.
- No live LLM in CI — `hermes bench` tests use the same mock-LLM pattern as `tests/test_pipeline_integration.py`.

---

## 3. Dependency DAG

```mermaid
graph LR
    T1["T1: Log schema<br/>(events, versions, fields)"]
    T2["T2: Structured logger<br/>(dual sink, config flag)"]
    T3["T3: RSS sampling helper<br/>(psutil optional)"]
    T4["T4: hermes bench<br/>(workloads + summary)"]
    T5["T5: Docs — Benchmarks<br/>& memory (README)"]
    T6["T6: CI artifact upload<br/>(main-branch runs)"]

    T1 --> T2
    T1 --> T3
    T1 --> T4
    T2 --> T3
    T2 --> T4
    T3 --> T4
    T4 --> T5
    T4 --> T6
```

**Parallel groups:**

- `{T1}` — root, no parallel peer.
- `{T2, T3}` — **soft-parallel.** Both depend only on T1. T3 uses the logger from T2 to emit `rss.sample` events, so it imports from T2; parallel is safe **only if** T3 codes against the public logger interface described in shared contracts and T2 freezes that interface early. If T2 reshapes `get_logger` mid-stream, T3 rebases. See hidden-coupling note 4.1.
- `{T4}` — depends on all three predecessors; starts after T3 lands (or scaffolds with stubs once T1's schema is frozen).
- `{T5, T6}` — **true-parallel** after T4. No file overlap.

**Soft dependencies:**

- T5 → T4 is soft in the sense that docs can be *drafted* once the CLI interface is stable, but must not be merged until T4 ships (otherwise docs reference a command that does not exist).
- T6 → T4 is strict (CI job references the bench output path), but the workflow YAML can be drafted against the documented output path before T4 merges, then wired up once T4 lands.

---

## 4. Subtask specs

### T1 — Log schema & event catalog

| Field | Content |
|-------|---------|
| **ID** | T1 |
| **Scope** | Define `EventName`, `StageName`, `BaseEvent`, `LogSchemaVersion`, and a catalog of event-specific field shapes (`stage.start`/`stage.end`, `rss.sample`, `chunk.done`, `llm.call`, `job.start`/`job.end`, `bench.*`). Document the versioning policy (additive → no bump; breaking → bump). Provide a validation helper `validate_event(dict) -> bool` used in tests. |
| **Files to touch** | `hermes/obs/__init__.py` (new), `hermes/obs/schema.py` (new), `tests/test_obs_schema.py` (new), `pyproject.toml` (add `[project.optional-dependencies] obs = ["structlog>=24", "psutil>=5.9"]` — version pins are illustrative, executor confirms latest) |
| **Contract bindings** | All shared contracts. `EventName`, `StageName`, `BaseEvent`, `LogSchemaVersion` are load-bearing — T2, T3, T4 all import from here. No other subtask may define event names or field shapes inline. |
| **Inputs** | None (root task). |
| **Outputs** | `hermes/obs/schema.py` exporting the symbols above; `tests/test_obs_schema.py` validating: (1) every `EventName` has a documented field set, (2) `validate_event` accepts a minimal event and rejects ones missing `schema_version` / `event`, (3) version string matches expected format. |
| **Kill criteria** | HALT if: (1) Pydantic v2 `Literal` unions over event names produce unwieldy types for consumers (>50 symbols or forward-ref issues) — escalate for a `TypedDict` vs `BaseModel` design decision. (2) The existing pipeline stages in `hermes/extraction/pipeline.py` do not cleanly map to the six `StageName` values — escalate with the real stage list rather than forcing a fit. (3) Adding `structlog`/`psutil` as optional deps is rejected by the project — fall back plan is stdlib-JSON logging and `resource.getrusage` (Unix) / `ctypes` (Windows) for RSS, which changes T2/T3 scope and must be re-planned. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** Schema drift once consumers start using it (fields renamed, types changed). **Mitigation:** Freeze v1 before T2/T3 start; require a `schema_version` bump + changelog entry for any breaking change. **Risk:** Event catalog balloons as downstream code adds ad-hoc events. **Mitigation:** `EventName` is a closed `Literal`; adding a new event is a deliberate edit to `schema.py`, reviewed. |

#### Decisions to capture (architectural log tier)

- **TypedDict vs Pydantic `BaseModel` for `BaseEvent`.** TypedDict is cheaper at emit time (no validation on hot path); BaseModel is safer in tests. Recommend: TypedDict in `schema.py` for runtime shape + a Pydantic `BaseEvent` in test helpers for validation.
- **Version scheme.** String `"1.0"` (major.minor). Breaking = major bump; additive optional fields = minor bump; typo fix = no bump.
- **`trace_id` strategy.** Optional — defaults to `None`. If the project later adopts OTel, `trace_id` is the bridge point. Document but do not implement propagation here.

---

### T2 — Structured logger with dual sink and config flag

| Field | Content |
|-------|---------|
| **ID** | T2 |
| **Scope** | Implement `hermes/obs/logging.py` with: `get_logger(name)` returning a configured structlog `BoundLogger` (or stdlib adapter if structlog absent), a bootstrap function `configure_logging(config)` reading `log_format` / `log_dir` from `hermes/config.py`, and dual-sink rendering (console always; NDJSON file when `log_format=="json"` or independent `log_ndjson=True`). Provide `bind_job(job_id, **kwargs)` context manager. Route existing `logging.getLogger(...)` calls through a compatibility adapter so no pipeline code changes are required beyond a single bootstrap call in `hermes/cli.py`. |
| **Files to touch** | `hermes/obs/logging.py` (new), `hermes/config.py` (extend with `log_format`, `log_dir`, `log_ndjson` — discovery required for exact pydantic settings style used there; read the file before editing), `hermes/cli.py` (add `configure_logging(settings)` call at app entry — discovery required: confirm `app_entry` is the entry point), `tests/test_obs_logging.py` (new) |
| **Contract bindings** | All shared contracts. Consumes T1's `EventName`, `BaseEvent`, `LogSchemaVersion`. Event emission must populate `schema_version` automatically. Must honor the error envelope: structlog or NDJSON failure degrades silently. |
| **Inputs** | T1 (schema symbols). |
| **Outputs** | Working `get_logger`/`configure_logging`/`bind_job`; console UX unchanged for default `log_format="console"`; with `log_format="json"` NDJSON appears at `<log_dir>/hermes-<date>.ndjson`; tests cover: (a) console sink renders human-readable, (b) NDJSON sink writes parseable one-object-per-line, (c) `bind_job` propagates `job_id`, (d) `structlog` missing → stdlib fallback, (e) invalid `log_format` → warn + console. |
| **Kill criteria** | HALT if: (1) `configure_logging` cannot be called idempotently without leaking handlers across tests — redesign the bootstrap before proceeding. (2) The existing CLI entry point already configures stdlib logging in a way incompatible with structlog (e.g. rich handler with custom formatter) — report the conflict and propose a migration strategy before overriding. (3) Dual sink causes observable slowdown on small-file smoke tests (> 10% regression) — measure and either async-queue the NDJSON sink or downgrade to sampling. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** structlog and the existing Rich-based console output render differently, breaking user-facing UX. **Mitigation:** Keep the console renderer as close to current output as possible; if needed, use structlog's `ConsoleRenderer` only for `log_format="json"` path and leave the current stdlib console path alone for `log_format="console"`. **Risk:** NDJSON file grows unbounded. **Mitigation:** One file per day; document rotation/cleanup in README; do not implement rotation in code for v1. **Risk:** Thread-safety of structlog context in the multi-worker LLM client. **Mitigation:** Use structlog's `contextvars`-based binding and test with a small parallel workload. |

#### Decisions to capture (architectural log tier)

- **structlog vs stdlib-JSON.** Shared contract recommends structlog. Document why (context vars, composable processors) and the fallback path.
- **Bootstrap location.** `hermes/cli.py` app-entry, before any subcommand runs. Pipeline modules get a logger lazily.

---

### T3 — RSS sampling helper wired at stage boundaries

| Field | Content |
|-------|---------|
| **ID** | T3 |
| **Scope** | Implement `hermes/obs/sampling.py` with `sample_rss(stage, job_id, logger, *, note=None)` and a `stage_timer(stage, job_id, logger)` context manager that emits `stage.start` + `stage.end` events and an `rss.sample` at both boundaries. `psutil` is optional: if missing, the first call logs `rss.sample.unavailable` at `WARN` once and subsequent calls no-op. Wire the context manager into `hermes/extraction/pipeline.py` at each stage transition (preflight, normalize, chunk, extract). Additionally add an optional periodic sampler (thread or async task) gated by `rss_sampling_interval_s > 0` for long normalization runs. |
| **Files to touch** | `hermes/obs/sampling.py` (new), `hermes/extraction/pipeline.py` (edit — wrap existing stage blocks with `stage_timer`; discovery required: read current stage boundaries before editing), `tests/test_obs_sampling.py` (new) |
| **Contract bindings** | All shared contracts. Emits events conforming to T1's `EventName` / `StageName`. Uses T2's logger (`get_logger("hermes.obs.sampling")`). Must honor error envelope (psutil missing, disk write failure). Must never raise into the pipeline; any failure in sampling is logged and suppressed. |
| **Inputs** | T1 (schema), T2 (logger). |
| **Outputs** | `sample_rss`, `stage_timer`, optional periodic sampler; pipeline stages emit `stage.start`/`stage.end`/`rss.sample` events; tests cover: (a) psutil present → sample has positive `rss_bytes`, (b) psutil absent → single warn + no-op, (c) `stage_timer` emits both boundary events even on exception, (d) periodic sampler stops cleanly at stage exit, (e) no pipeline behavior change (integration test asserts existing pipeline tests still pass). |
| **Kill criteria** | HALT if: (1) Wrapping existing stages with `stage_timer` requires restructuring `pipeline.py` beyond mechanical wrapping — stop and report the refactor needed; do not expand scope. (2) Periodic sampling introduces race conditions with the existing parallel LLM worker pool — drop the periodic sampler and ship boundaries-only. (3) `psutil` on Windows returns RSS that differs materially from Linux/macOS semantics such that comparisons across platforms are meaningless — document the caveat but proceed; do not attempt cross-platform normalization in v1. |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** `stage_timer` swallows exceptions or mis-attributes stage boundaries. **Mitigation:** Context manager emits `stage.end` with `status: "error"` in `__exit__` on exception, then re-raises; tested with a forced-exception stage. **Risk:** Periodic sampler thread leaks across tests. **Mitigation:** Stage-scoped; cleaned up in `__exit__`; pytest fixtures assert no lingering threads. **Risk:** RSS sample adds latency to fast stages (preflight). **Mitigation:** Single `psutil` call is sub-millisecond; measured once and documented. |

---

### T4 — `hermes bench` command: workloads, summary, CSV/JSON output

| Field | Content |
|-------|---------|
| **ID** | T4 |
| **Scope** | Implement `hermes/bench/runner.py` with `BenchWorkload`, `BenchResult`, `BenchSummary` models and a `run_bench(workloads, output_dir, model, workers) -> BenchSummary` function. Define 2–3 standard workloads in `hermes/bench/workloads.py` using the existing fixtures (`tests/fixtures/sample_text.pdf`, `tests/fixtures/sample.xlsx`, and one larger synthetic workload via `tests/generate_fixtures.py` / `generate_test_datasets.py` — discovery required). Add a Typer `bench` subcommand to `hermes/cli.py`. The bench: runs each workload end-to-end, consumes `stage.end` and `rss.sample` events via a log-tail or in-process collector, computes peak RSS and throughput, and writes `benchmarks/<date>_<short-sha>.json` (+ optional `.csv`). |
| **Files to touch** | `hermes/bench/__init__.py` (new), `hermes/bench/runner.py` (new), `hermes/bench/workloads.py` (new), `hermes/cli.py` (add `bench` subcommand — discovery required: confirm Typer pattern used by existing commands), `benchmarks/.gitkeep` (new directory marker), `tests/test_bench_runner.py` (new), `tests/fixtures/` (no new files; reuse existing sample fixtures — discovery required: confirm exact filenames via `ls tests/fixtures/`) |
| **Contract bindings** | All shared contracts. Consumes T1 schema (emits `bench.*` events), T2 logger, T3 RSS samples. `BenchResult` field names are frozen by the contract and must not drift. Mock-LLM pattern mirrors `tests/test_pipeline_integration.py` (discovery required: read that file before writing bench tests). |
| **Inputs** | T1 (schema), T2 (logger), T3 (RSS samples). |
| **Outputs** | Working `hermes bench` CLI; JSON + optional CSV summary under `benchmarks/`; tests cover: (a) single-workload run produces a `BenchResult` with positive duration and non-negative RSS, (b) multi-workload run produces an ordered `BenchSummary`, (c) missing fixture → skip with `status="skipped"`, (d) workload exception → `status="error"` recorded; remaining workloads continue, (e) CSV output parses as CSV with expected headers. |
| **Kill criteria** | HALT if: (1) Running the extraction pipeline inside `hermes bench` requires a live LLM API key even for the smallest workload, and no mock path exists for CLI (as opposed to tests) — propose either a `--mock-llm` flag or document that bench needs a key; do not silently call an LLM in CI. (2) Peak-RSS computation requires consuming the NDJSON file after the run completes, but the NDJSON sink buffers across days — switch to an in-process collector (subscribe to the logger's event stream) or document the single-day limitation. (3) The existing `hermes/cli.py` Typer structure does not support subcommand groups the way this plan assumes — report the structure and re-plan the CLI surface. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** Bench runs are expensive (real LLM calls, minutes-to-hours). **Mitigation:** Two modes: (a) default runs the full pipeline with a real model (documented for local/nightly use), (b) `--mock-llm` uses the same stub as `test_pipeline_integration.py` for CI + smoke. **Risk:** "Pages per minute" is ambiguous for Excel (no pages). **Mitigation:** `pages_per_minute` is `None` for Excel workloads; `rows_per_minute` is populated instead; docs explain the split. **Risk:** RSS peak captured by bench diverges from RSS observed by the OS (e.g. due to GC timing). **Mitigation:** Peak RSS is the max of observed `rss.sample` events plus an end-of-run `resource.getrusage` reading (platform-permitting); both are reported when they differ by >10%. |

#### Decisions to capture (architectural log tier)

- **Subscriber vs log-tail.** In-process subscription to the logger's event stream is simpler and more deterministic than tailing NDJSON. Recommend subscriber; NDJSON remains the auditable artifact.
- **Default workload set.** Start with 3: `pdf_text_small` (existing fixture), `excel_small` (existing fixture), `pdf_text_large` (larger synthetic, opt-in via `--workload large`). Keep the default set runnable in <5 minutes on a dev laptop.
- **Commit hash capture.** Use `subprocess.check_output(["git", "rev-parse", "--short", "HEAD"])` with a graceful fallback to `"unknown"` when not in a git checkout.

---

### T5 — README "Benchmarks & memory" subsection + methodology

| Field | Content |
|-------|---------|
| **ID** | T5 |
| **Scope** | Add a new README section titled "Benchmarks & memory" that: (1) states the memory-safety and scalability claims, (2) documents the `hermes bench` command and how to run it locally, (3) provides a reference-hardware table populated from an actual bench run (workload name, peak RSS, wall time, throughput, model, date, commit), (4) documents methodology (what is measured, what isn't, caveats around psutil/Windows RSS), (5) points at `benchmarks/` for historical runs and at the NDJSON logs for raw data, (6) checks off the relevant items in `.dev/evaluation-and-health-metrics-roadmap.md`. |
| **Files to touch** | `README.md` (edit — discovery required: read current README structure; Part A plan also adds a section, coordinate placement), `.dev/evaluation-and-health-metrics-roadmap.md` (edit — check off completed queued items in Part B's "Queued implementation" list) |
| **Contract bindings** | Naming and CLI contracts only. Documented CLI flags must match the T4 implementation verbatim. No code interfaces. |
| **Inputs** | T4 (CLI must be stable; at least one real bench run to populate the reference table). |
| **Outputs** | README subsection, updated roadmap, one `benchmarks/<date>_<sha>.json` committed as the reference row's source. |
| **Kill criteria** | HALT if: (1) The README already has a benchmarks section from elsewhere in the project — merge rather than duplicate; flag and stop if the existing content conflicts with Part B's direction. (2) The reference-hardware bench run fails or produces nonsensical numbers (e.g. peak RSS of 0) — investigate with T3/T4 owners before publishing. (3) Part A has merged a conflicting "How we measure quality" section that changes README heading structure — coordinate; do not reshape Part A's heading. |
| **Log tier** | trivial |
| **Risks & mitigations** | **Risk:** Reference numbers become stale within weeks and make the README misleading. **Mitigation:** Date-stamp every row; document that numbers are a point-in-time reference, and that `benchmarks/` holds historical runs. **Risk:** Documenting `psutil`/Windows caveats scares users. **Mitigation:** Keep caveats short and factual; link to methodology appendix rather than inlining caveats into the headline table. |

---

### T6 — CI artifact upload for bench summary JSON (main-branch runs)

| Field | Content |
|-------|---------|
| **ID** | T6 |
| **Scope** | Add a step to `.github/workflows/ci.yml` that, on pushes to `main` only, runs `hermes bench --mock-llm --workload small --output benchmarks/ci-<run-id>.json` and uploads the resulting JSON as a GitHub Actions artifact. No CI failure if the bench returns non-zero with `status="skipped"` workloads (still upload). Explicitly do **not** add a regression gate (per Part B non-goals). |
| **Files to touch** | `.github/workflows/ci.yml` (edit — existing file confirmed present), optionally `.github/workflows/bench.yml` (new, if isolating the bench job is cleaner — executor decides based on existing `ci.yml` structure) |
| **Contract bindings** | CLI flag names must match T4 verbatim (`--mock-llm`, `--workload`, `--output`). Artifact naming convention `bench-summary-<sha>` documented in T5. |
| **Inputs** | T4 (working `hermes bench --mock-llm`). |
| **Outputs** | A new CI step; on main-branch runs, the workflow produces a downloadable `bench-summary` artifact; existing `ruff` / `mypy` / `pytest` steps continue to pass. |
| **Kill criteria** | HALT if: (1) `hermes bench --mock-llm` takes longer than 5 minutes on GitHub's default Ubuntu runner — drop the CI step; document that bench is local-only for now. (2) The artifact upload fails on private repos / missing permissions — investigate; do not bypass permission errors by adding secrets. (3) The `--mock-llm` path is not deterministic enough to produce a stable JSON across runs (e.g. timing fields flap so aggressively that artifacts are noise) — still upload, but add a README note that artifacts are informational. |
| **Log tier** | standard |
| **Risks & mitigations** | **Risk:** CI runner RSS numbers are useless because of shared tenancy and caching. **Mitigation:** Document this in T5's methodology; the CI artifact's purpose is "this keeps working and produces a parseable summary", not "this is a regression oracle". **Risk:** Adding a job slows CI. **Mitigation:** Scope to `main` branch only (not PRs); use smallest workload; fail-soft on timeout. |

---

## 5. Adversarial pass

### 1. Rejected decompositions

**Alternative A — Merge T1+T2 into a single "structured logging" subtask.** Fewer handoffs. Rejected because the event catalog (T1) is a contract surface consumed by T3 and T4; freezing it as a deliberate, separate artifact before any emitter code is written reduces the risk of the schema drifting to match whatever the first emitter happens to produce. The adversarial-pass output of T1 (event catalog doc) is itself a review artifact worth isolating.

**Alternative B — Put bench inside `hermes/obs/bench.py` rather than a separate `hermes/bench/` package.** One fewer package, tighter coupling to telemetry. Rejected because `hermes bench` is a user-facing CLI concern (invokes the full pipeline, defines workloads, handles output formatting) whereas `hermes/obs/` is cross-cutting infrastructure. Mixing them invites circular imports (pipeline imports `hermes.obs`, bench imports pipeline + `hermes.obs`; if bench lives in `hermes.obs` then `hermes.obs` transitively depends on pipeline).

**Alternative C — Adopt OpenTelemetry instead of structlog+NDJSON.** Industry standard; future-proof. Rejected explicitly per the roadmap's tradeoff table ("heavy for a CLI; export often unused locally"). The plan leaves a `trace_id` seam in `BaseEvent` so a later migration is incremental, not a rewrite.

**Alternative D — Skip T6 (CI artifact) entirely.** One less moving part, no flaky-runner risk. Rejected because the roadmap's "CI artifact — Upload bench summary JSON on main-branch runs (if stable enough)" item is explicitly queued; shipping the artifact upload without a regression gate captures the value (auditable historical record) without the cost (flaky failures). The "if stable enough" hedge is respected by using `--mock-llm` and the smallest workload.

### 2. Load-bearing assumptions

1. **The existing pipeline stages in `hermes/extraction/pipeline.py` can be cleanly wrapped with a `stage_timer` context manager without restructuring.** If stages are spread across nested helpers or async tasks that resist wrapping, T3's kill criterion fires and the plan needs revision. Relates to **T3**.
2. **`structlog` and `psutil` are acceptable as optional extras (`[obs]`).** If the project insists on zero-new-deps, T1/T2/T3 all need re-scoping to stdlib-JSON + `resource.getrusage`/ctypes, which invalidates several files-to-touch entries. Relates to **T1, T2, T3**.
3. **Console UX can be preserved under `log_format="console"` while `log_format="json"` routes through structlog.** If the current Rich-based CLI output cannot coexist with structlog's console renderer, T2 must either downgrade to stdlib-JSON-only (no structlog) or the plan accepts a cosmetic regression. Relates to **T2**.
4. **`hermes bench --mock-llm` can produce meaningful throughput and RSS numbers without a live LLM.** If mocking the LLM trivializes the workload so much that RSS and throughput are unrepresentative, the CI artifact from T6 has limited value. Mitigated by documenting "mock mode is for plumbing regression, not performance regression" in T5. Relates to **T4, T6**.
5. **Bench peak-RSS via `psutil` is comparable across runs on the same machine.** If allocators (malloc, Python GC) introduce non-determinism at the 50%+ level, reference numbers are noise. This is tolerated for v1 (no regression gate) but the assumption becomes load-bearing the moment anyone adds a threshold check — not in this plan. Relates to **T3, T4**.
6. **The existing `hermes/config.py` uses a settings pattern (pydantic-settings or similar) that can be extended with three new fields without a breaking migration.** If the config loader is ad-hoc, T2's kill criterion may fire. Relates to **T2**.

### 3. Highest re-plan risk

**T4 (`hermes bench`)** — it sits at the confluence of T1's schema, T2's logger, T3's sampling, and the existing pipeline, and it introduces the first user-visible CLI command depending on the whole stack. The most likely surprises: (a) the mock-LLM path is too thin for meaningful numbers, (b) peak-RSS from subscriber vs OS diverges enough to require methodology rework, (c) the Typer subcommand structure requires CLI reshaping. Any of these forces a re-plan of T4, which cascades into T5 (docs referencing the CLI) and T6 (CI referencing the flags).

A secondary risk is **T3** — wrapping pipeline stages is described as "mechanical" but mechanical-in-planning often means "I haven't read the file yet". If stages are not already isolated, T3's kill criterion fires first and blocks everything downstream.

### 4. Hidden couplings

- **T2 ↔ T3 (logger interface).** T3 imports `get_logger` and `bind_job` from T2. If T2 changes that interface mid-stream, T3 rebases. Mitigation: T1 and T2 freeze the logger interface signature (in `hermes/obs/__init__.py` exports) before T3 begins; the DAG edge `T2 --> T3` is enforced rather than "soft-parallel".
- **T3 ↔ pipeline internals.** Wrapping existing stages with `stage_timer` is a behavior-neutral change in theory, but the pipeline's existing logging, error handling, and DB writes happen inside those stages. If `stage_timer`'s `__exit__` semantics mask an exception path (e.g. re-raises after logging) or changes stderr ordering, existing pipeline tests may flap. Mitigation: T3 runs the full pipeline test suite as part of its kill-criteria check before signing off.
- **T4 ↔ T3 RSS collection.** T4 peak-RSS derivation reads `rss.sample` events. If T3's periodic sampler is disabled or stage boundaries move, T4's `peak_rss_bytes` under-reports. Mitigation: T4 also captures end-of-run `resource.getrusage` as a cross-check and reports both when they disagree.
- **T5 ↔ T4 CLI flags.** Docs reference `--mock-llm`, `--workload`, `--output`. If T4 renames these late, T5 must update. Mitigation: T6 and T5 both cite the flag names via the shared-contracts section; if T4 renames, it must update shared contracts first, which is a visible change.
- **T5 ↔ Part A's README edit (`.dev/eval/eval-plan.md` T6).** Both plans add a top-level README section. If they land in the same PR window without coordination, they'll conflict on README structure. Mitigation: T5's kill criterion (2) calls this out; whichever plan merges second rebases.
- **T6 ↔ T4 `--mock-llm`.** T6 is the first consumer of `--mock-llm` in CI. If T4 implements it as a test-only fixture rather than a real CLI flag, T6 breaks. Mitigation: shared contracts enumerate `--mock-llm` as a first-class CLI flag, not a test hook.

---

## 6. Executor packets

Each subtask has a self-contained packet at `.dev/part_b/packets/T<n>.md`:

- [T1 — Log schema & event catalog](packets/T1.md)
- [T2 — Structured logger with dual sink and config flag](packets/T2.md)
- [T3 — RSS sampling helper wired at stage boundaries](packets/T3.md)
- [T4 — `hermes bench` command: workloads, summary, CSV/JSON output](packets/T4.md)
- [T5 — README "Benchmarks & memory" subsection + methodology](packets/T5.md)
- [T6 — CI artifact upload for bench summary JSON (main-branch runs)](packets/T6.md)

Each packet contains verbatim Sections 1, 2, and the subtask's Section 4 block, plus filtered load-bearing assumptions and hidden couplings, per the orchestrator-planning skill.

---

## Appendix: Roadmap item mapping

How the queued items from Part B map to subtasks:

| Roadmap item (lines 129–134) | Subtask |
|------------------------------|---------|
| Define **log schema** (fields + version field for schema evolution) | T1 |
| Introduce **structlog** (or structured JSON) behind config flag `log_format` | T2 |
| **RSS sampling** helper used at stage boundaries in `pipeline.py` | T3 |
| **`hermes bench`** or documented script — standard workloads + RSS/duration output; optional CSV export | T4 |
| **README subsection** — "Benchmarks & memory" with reference table + methodology | T5 |
| **CI artifact** — Upload bench summary JSON on main-branch runs | T6 |

Metrics coverage (lines 81–107) is distributed:

| Metric family | Subtask(s) |
|---------------|-----------|
| Peak RSS, RSS curve, per-stage peak | T3 collects, T4 aggregates |
| OOM boundary (lab) | Documented only in T5 (methodology appendix) |
| Pages/Rows/Chunks per minute | T4 computes from pipeline counters + events |
| End-to-end latency (p50/p95 by size bucket) | T4 emits per-run; aggregation across runs is out of scope for v1 — documented in T5 |
| LLM cost proxy | T4 reads existing token counts from DB / events |
| Validation pass rate, repair rate, DLQ depth, chunk failure rate | T4 reads from existing DB tables (`llm_runs`, `failed_extractions`, `failed_chunks`) and surfaces in `BenchResult` |

Tradeoffs table coverage (lines 138–143): the chosen path is **structlog + NDJSON** (T2) with **SQLite already queryable** kept as-is (no change to existing DB writes). **Stdlib only** is the automatic fallback path if `structlog` is rejected. **Full OTel** is explicitly a non-goal.

---

## Changelog

- **0.1 (2026-04-16):** Initial plan from Part B of evaluation-and-health-metrics-roadmap.
