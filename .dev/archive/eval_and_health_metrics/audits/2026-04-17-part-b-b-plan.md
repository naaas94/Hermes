# Audit report — Part B memory-safe & scalable (`b-plan.md`)

## Document history

| Version | Date | Scope |
|---------|------|--------|
| **Part I (frozen)** | 2026-04-17 | Initial audit against **`b-plan.md` v0.3 · Complete** — verdict **`fail`** (F1, F2 major). |
| **Part II (addendum)** | 2026-04-17 | Rerun after **T7** and plan **v0.4** amendments; re-verifies code, tests, packets, CI, and consumer docs. |

---

# Part II — Addendum: post-T7 / v0.4 verification (2026-04-17)

## 1. Audit metadata (rerun)

| Field | Value |
|-------|--------|
| **Task** | `part-b-memory-safe-scalable` / Hermes-Part-B-b-plan |
| **Orchestrator plan** | `.dev/part_b/b-plan.md` — **v0.4** (references T7; banner still **Active** pending auditor sign-off — see §8 conditions) |
| **Audit date (rerun)** | 2026-04-17 |
| **Auditor focus (Phase 4)** | **(A) Failure / degradation paths** — obs error envelope, bench dual-run skip when structlog absent. **(B) Integration seams** — `ObservabilityConfig` → pipeline RSS wiring; schema 2.0 ↔ logging ↔ bench; WARN-string regression vs `EventName`. **(C) Regression surface** — T7 did not alter NDJSON `LogSchemaVersion`; `tests/test_obs_config.py` guards config contract. |
| **Pytest** | **`206 passed`** (2026-04-17, Windows; `pip install -e ".[dev,obs]"`, `python tests/generate_fixtures.py`, `pytest -q`) |

---

## 2. Context chain completeness

| Artifact | Status | Notes |
|----------|--------|-------|
| Pre-plan / intent | **Present** | `.dev/evaluation-and-health-metrics-roadmap.md` Part B (lines 75–134) + `b-plan.md` §1 |
| Orchestrator plan | **Present** | `b-plan.md` v0.4 (T7 spec, F2/T6 amendments, F6 packet note) |
| Shared contracts | **Present** | `b-plan.md` §2 — **see §8:** §2 “Config fields” table row still describes **pre-T7** F1 state (`getattr` / dropped TOML); **code** matches the **intended** five-field contract after T7 |
| Packets T1–T7, T1.1 | **Present** | `.dev/part_b/packets/` including **`T7.md`**; **T6** / **T2** amended per v0.4 audit notes |
| Decision logs | **Present** | `decisions/T1.md`, `T2.md`, `T4.md` — **T4 “Deferred” still stale** (§5) |
| Changelog | **Present** | `CHANGELOG.md` — T7 line documents F1/F5 closure; older T2 bullet still lists only three `ObservabilityConfig` fields (cosmetic incompleteness) |
| Code / tests | **Reviewed** | `hermes/config.py`, `hermes/extraction/pipeline.py`, `hermes/obs/*`, `hermes/bench/*`, `hermes/cli.py`, `tests/test_obs_config.py`, `tests/test_obs_*.py`, `tests/test_bench_runner.py`, `.github/workflows/ci.yml`, `README.md`, `config.toml.example` |

**Gap:** No machine-verified GHA main-branch bench run in this environment; T6 KC1–KC3 remain **operational / unknown** here (same as Part I).

---

## 3. Resolution of Part I major findings

| ID | Part I severity | Status after T7 / v0.4 | Evidence |
|----|-----------------|-------------------------|----------|
| **F1** | major `contract-violation` | **Closed in code** | `ObservabilityConfig` includes `rss_sampling_enabled`, `rss_sampling_interval_s`; `_parse_config` filters on `ObservabilityConfig.__dataclass_fields__`; `pipeline.py` uses `cfg.observability.rss_sampling_*` directly (`hermes/config.py`, `hermes/extraction/pipeline.py`); `tests/test_obs_config.py` round-trips TOML; `config.toml.example` lists five `[observability]` keys |
| **F2** | major `intent-drift` | **Closed by plan/packet amendment** | `b-plan.md` §4 T6 + `packets/T6.md` describe `hermes bench --mock-llm --output benchmarks` and real flag surface; `.github/workflows/ci.yml` matches; `hermes bench` has no `--workload` (uses `--include-large` + workload defaults) |

---

## 4. Findings table (rerun)

| ID | Severity | Type | Phase | Subtask | One-line description |
|----|----------|------|-------|---------|----------------------|
| F3 | **minor** | `decision-log-stale` | 3 | T4 | `decisions/T4.md` **Deferred** still lists README reference row + CI artifact as open; T5/T6 shipped |
| F4 | **minor** | `decision-log-stale` | 3 | T1 | `decisions/T1.md` preamble **Alternatives rejected** still implies old stage-alias stance; superseded by **v0.2 contract refresh** section but confusing |
| F8 | **minor** | `contract-violation` | 2 | Plan doc | `b-plan.md` §2 **Types → Config fields** row still states F1 (**getattr**, TOML dropped); implementation post-T7 **does** type and parse RSS fields — **documentation drift** vs code |
| F9 | **observation** | — | 1 | Docs | `CHANGELOG.md` T2 bullet lists only three `ObservabilityConfig` fields; T7 entry above corrects for RSS — minor narrative redundancy |
| F7 | **observation** | — | 1 | Packets | Frozen packets (e.g. T3/T4 task-statement lines) still say “preflight / normalize / chunk / extract” in places; **b-plan** v0.2 four-literal names are canonical for **`StageName`** — cosmetic |

**Part I items fully cleared in rerun:** **F5** (README programmatic consumers — **present** under “Programmatic consumers” with plan-aligned wording), **F6** (`packets/T2.md` Outputs row — **amended** to `HermesObsExtraRequired`).

---

## 5. Detailed findings (above observation)

### F8 — `b-plan.md` §2 Config row vs post-T7 code (`contract-violation`, minor, documentation-only)

**Expected:** After T7, the shared-contract table should state that all five observability fields are typed on `ObservabilityConfig` and parsed from `[observability]`.

**Found:** Row at `b-plan.md` §2 (Config fields / `ObservabilityConfig`) still documents **v0.4 pre-T7** F1 analysis (`getattr`, keys dropped). That contradicts `hermes/config.py` and `tests/test_obs_config.py`.

**Classification:** **Drift** in the orchestrator document, not in runtime behavior. Fix owner: orchestrator — update §2 row, and the plan header/status lines when closing v0.4.

---

### F3 / F4 — Decision logs (`decision-log-stale`, minor)

**T4.md — Deferred:** Still requests README table + CI upload; both exist (README “Reference hardware”; `ci.yml` bench + artifact). Section should be closed or rewritten as “Completed (see T5/T6)”.

**T1.md — preamble:** Lines 13–16 **Alternatives rejected** still describe rejecting SQLite-aligned `StageName` strings; the **v0.2 contract refresh (2026-04-16)** section below correctly records Option B. Trim or mark the preamble historical to avoid contradiction.

---

## 6. Accepted deviation — `bench.dualsink.regression` WARN string vs `EventName`

| Layer | Consistent? | Evidence (rerun) |
|-------|-------------|------------------|
| **Plan (`b-plan.md` §2 `EventName` row)** | Yes | Documents WARN-level literal + consumer guidance (substring + `2.0 → 2.1` promotion path) |
| **Decision log (`T4.md`)** | Yes (technical); **Deferred section stale** | Chosen approach: WARN log line, not new `EventName` (schema file out of scope) |
| **Code** | Yes | `hermes/bench/runner.py` — `logging.warning(..., "bench.dualsink.regression workload=%s ...")`; `hermes/cli.py` — Rich summary + non-zero exit on `dual_sink_regression` |
| **Tests** | Yes | `tests/test_bench_runner.py` — caplog substring `bench.dualsink.regression` |
| **README** | Yes (F5 closed) | `README.md` — **Programmatic consumers** restates WARNING + substring; links `b-plan.md` §2 and `decisions/T4.md` |

**Classification:** **Documented override** per plan — not silent drift. NDJSON structured events use `EventName`; this signal intentionally uses stdlib/logger **WARNING** + message substring so T4 avoided editing `hermes/obs/schema.py`.

---

## 7. Adversarial test log (Phase 4, rerun)

| Scenario | Expected | Actual | Result |
|----------|----------|--------|--------|
| `log_format=json` without `[obs]` | Fatal `HermesObsExtraRequired` | Unchanged | **pass** (tests + prior review) |
| NDJSON sink write failure | One stderr warning; continue | Unchanged | **pass** |
| `psutil` missing | One WARN `rss.sample.unavailable`; then no-op | Unchanged | **pass** |
| Dual-run without structlog | Skip compare; warn; continue | Unchanged | **pass** |
| `dual_sink_overhead_pct > 10` on smoke workload | WARN contains `bench.dualsink.regression`; non-zero exit | Unchanged | **pass** |
| TOML `rss_sampling_*` overrides | Values reach `ObservabilityConfig` | `_parse_config` + round-trip test | **pass** |
| CI bench on `main` | &lt; 5 min, artifact upload | Not executed in this audit | **unknown** |

---

## 8. Coverage gap analysis (Phase 5)

**Improvements since Part I**

- **F1 gap closed:** `test_observability_rss_fields_round_trip_from_toml`, field-set assertion, defaults test (`tests/test_obs_config.py`).

**Remaining gaps**

1. **Operational:** T6 kill criteria (runner time, artifact permissions, JSON noise) — not automated; acceptable under Part B non-goals for CI gates.
2. **Decision/prose hygiene:** F3, F4, F8 (documentation).

Tests remain behavioral (disk failure, schema reject, caplog substring, config round-trip) rather than tautological.

---

## 9. Verdict (rerun)

**`pass-with-conditions`**

**Rationale:** Implementation satisfies Part B intent and **shared contracts in code** after **T7**. Original **major** code/traceability issues (**F1**, **F2**) are **resolved**. Remaining items are **minor** or **observation**: orchestrator docs (**F8**, plan status banner), and stale subsections in **decision logs** (**F3**, **F4**). No critical or major **code** defects identified; pytest **206 passed**.

**Conditions (non-blocking for code merge; orchestrator/executor doc hygiene)**

1. Update **`b-plan.md` §2** Config fields row to the five-field typed `ObservabilityConfig` + remove obsolete F1/`getattr` prose; align header **Status** with **Complete** when v0.4 is accepted.
2. Refresh **`decisions/T4.md` Deferred** (or mark completed).
3. Reconcile **`decisions/T1.md`** preamble vs v0.2 section **or** label preamble historical.

---

## 10. Non-goals check (Phase 1)

Unchanged from Part I — no evidence Part B crossed listed non-goals (no CI threshold gate on bench, no OTel, no pipeline semantics change for Part B observability-only wiring).

---

## 11. Contract compliance snapshot (Phase 2, code)

| Topic | Status |
|-------|--------|
| `LogSchemaVersion` `"2.0"` | OK |
| `StageName` four literals | OK |
| `EventName` + documented WARN-string override for dual-sink regression | OK (**override**) |
| `ObservabilityConfig` five fields + TOML parse | OK (post-T7) |
| Error envelope | OK |
| Test file naming | OK (`test_obs_config.py` added) |

---

*Auditor role: review only; no code fixes in this pass.*

---

# Part I — Historical audit record (2026-04-17, frozen)

*The following sections are the **original** auditor report as filed against **`b-plan.md` v0.3 · Complete** (pre-T7). They are preserved for traceability. **Superseded** by **Part II** for current verdict and findings.*

---

# Audit report — Part B memory-safe & scalable (`b-plan.md` v0.3)

## 1. Audit metadata

| Field | Value |
|-------|-------|
| **Task** | `part-b-memory-safe-scalable` / Hermes-Part-B-b-plan |
| **Orchestrator plan** | `.dev/part_b/b-plan.md` — **v0.3 · Complete** |
| **Audit date** | 2026-04-17 |
| **Auditor focus (Phase 4)** | **(A) Failure / degradation paths** — obs error envelope (missing extras, NDJSON write failure, psutil, bench compare skip). **(B) Integration seams** — schema ↔ logging ↔ bench collector ↔ CLI exit codes; WARN-string regression signal vs `EventName`. **(C) Regression surface** — schema 2.0 `StageName`, dual-run / dual-sink behavior. |
| **Pytest** | `203 passed` (2026-04-17, Windows; `pip install -e ".[dev,obs]"`, `python tests/generate_fixtures.py`, `pytest -q`) |

---

## 2. Context chain completeness

| Artifact | Status | Notes |
|----------|--------|-------|
| Pre-plan / intent | **Present** | `.dev/evaluation-and-health-metrics-roadmap.md` Part B (lines 75–134) + `b-plan.md` §1 |
| Orchestrator plan | **Present** | `b-plan.md` (v0.3) |
| Shared contracts | **Present** | `b-plan.md` §2 |
| Packets T1–T6, T1.1 | **Present** | `.dev/part_b/packets/` |
| Decision logs | **Present** | `.dev/part_b/decisions/T1.md`, `T2.md`, `T4.md` only (no T3/T5/T6 files — acceptable if log tier did not require them) |
| Changelog | **Present** | `CHANGELOG.MD` (schema 2.0 block + Part B narrative) |
| Code / tests | **Reviewed** | `hermes/obs/`, `hermes/bench/`, `hermes/config.py`, `hermes/cli.py`, `hermes/extraction/pipeline.py`, `tests/test_obs_*.py`, `tests/test_bench_runner.py`, `.github/workflows/ci.yml`, `README.md` |

**Gap:** No single git baseline diff was attached; mapping below is from repository structure + changelog + plan crosswalk (sufficient for this audit).

**Shipped surface (subtask → code/tests):**

- **T1 / T1.1:** `hermes/obs/schema.py`, `hermes/obs/__init__.py`, `tests/test_obs_schema.py`, `pyproject.toml` `[obs]`
- **T2:** `hermes/obs/logging.py`, `hermes/config.py` (`ObservabilityConfig`), `hermes/cli.py` (`configure_logging` in callback), `tests/test_obs_logging.py`
- **T3:** `hermes/obs/sampling.py`, `hermes/extraction/pipeline.py`, `tests/test_obs_sampling.py`
- **T4:** `hermes/bench/runner.py`, `hermes/bench/workloads.py`, `hermes/bench/__init__.py`, `hermes/cli.py` (`bench`), `benchmarks/.gitkeep`, `tests/test_bench_runner.py`
- **T5:** `README.md` (“Benchmarks & memory”), `.dev/evaluation-and-health-metrics-roadmap.md` checkboxes, committed `benchmarks/*.json` (per README reference row)
- **T6:** `.github/workflows/ci.yml` (main-only bench + artifact upload)

---

## 3. Findings table

| ID | Severity | Type | Phase | Subtask | One-line description |
|----|----------|------|-------|---------|----------------------|
| F1 | **major** | `contract-violation` | 2 | T2/T3 | `ObservabilityConfig` does not define `rss_sampling_enabled` / `rss_sampling_interval_s` as in `b-plan.md` §2; `[observability]` keys for those names are dropped by `_parse_config` |
| F2 | **major** | `intent-drift` | 1 | T6 | `b-plan.md` §4 / packets still describe `hermes bench ... --workload small` and per-run JSON path; shipped CLI has **no** `--workload`; CI matches README (`--mock-llm --output benchmarks`) |
| F3 | **minor** | `decision-log-stale` | 3 | T4 | `T4.md` “Deferred” still lists README reference row and CI artifact as open; T5/T6 shipped |
| F4 | **minor** | `decision-log-stale` | 3 | T1 | `T1.md` retains pre–v0.2 “Alternatives rejected” (stage vocabulary) that contradicts the v0.2 section below |
| F5 | **minor** | `coverage-gap` | 5 | T5 / contract | `b-plan.md` §2 consumer guidance for `bench.dualsink.regression` (WARNING + message substring) is not spelled out in README “Benchmarks & memory” |
| F6 | **minor** | `process-violation` | 2 | T2 packet | Packet `T2.md` §4 Outputs still list “structlog missing → stdlib fallback” for JSON; superseded by v0.2 / `HermesObsExtraRequired` (packet not cascaded for that bullet) |
| F7 | **observation** | — | 1 | Packets | Several packets still say `normalize`/`chunk`/`extract` in sampling prose; `b-plan` v0.2 uses four-literal `StageName` — cosmetic doc drift in frozen packets |

---

## 4. Detailed findings (above minor)

### F1 — Config fields vs shared contract (`contract-violation`)

**Expected (`b-plan.md` §2 Types / interfaces):** Config includes `log_format`, `log_dir`, `rss_sampling_enabled` (and logging subsection references `rss_sampling_interval_s`).

**Found:** `ObservabilityConfig` only declares `log_format`, `log_dir`, `log_ndjson`. `hermes/extraction/pipeline.py` uses `getattr(cfg.observability, "rss_sampling_enabled", True)` and `getattr(..., "rss_sampling_interval_s", 0)`, so **defaults** behave, but users **cannot** set these via `config.toml` through the typed loader — unknown keys under `[observability]` are ignored by `_parse_config`.

**Evidence:** `hermes/config.py` (`ObservabilityConfig`), `_parse_config` `obs_fields` filter; `grep` on `config.toml.example` shows no `[observability]` block.

**Note:** `log_ndjson` is an additive implementation choice (console + NDJSON without `log_format=json`) — consistent with T2 decision log; not listed in the short §2 table but not inherently conflicting.

---

### F2 — T6 plan text vs shipped CLI (`intent-drift`)

**Expected:** `b-plan.md` §4 T6 and `.dev/part_b/packets/T6.md` scope cite  
`hermes bench --mock-llm --workload small --output benchmarks/ci-<run-id>.json` and contract bindings requiring `--workload` with T4.

**Found:** `hermes bench` has `--mock-llm`, `--output`, etc.; **no** `--workload`. CI runs `hermes bench --mock-llm --output benchmarks` and uploads `benchmarks/*.json` — aligns with README, not with the literal T6 packet scope line.

**Classification:** Implementation is internally consistent (README + workflow); the **orchestrator/packet spec** was not updated when T4 dropped a workload filter flag. Treat as **plan/packet staleness**, not a runtime defect.

---

## 5. Accepted deviation — `bench.dualsink.regression` WARN string vs `EventName`

| Layer | Consistent? | Evidence |
|-------|-------------|----------|
| **Plan (`b-plan.md` §2)** | Yes | Documents WARN-level literal string, not `EventName`; consumer guidance: WARNING + substring |
| **Decision log (`T4.md`)** | Yes | Explicit reject adding `EventName`; WARN line carries signal |
| **Code** | Yes | `hermes/bench/runner.py` — `_BENCH_LOG.warning("bench.dualsink.regression workload=%s ...")`; `hermes/cli.py` — Rich message + `summary.dual_sink_regression` → exit `1` |
| **Tests** | Yes | `tests/test_bench_runner.py` — `assert any("bench.dualsink.regression" in r.message for r in caplog.records)` |
| **README consumer guidance** | Partial | Describes dual-run, overhead, CI; **does not** restate substring/`event` pitfall (F5 — minor) |

**Verdict on deviation:** **Documented override** (not silent drift). Wire format for warnings under NDJSON uses `level` + `message` on the logging envelope (`HermesNDJSONHandler`), not `event` — consistent with not using `EventName` for this signal.

---

## 6. Adversarial test log (Phase 4)

| Scenario | Expected (plan/contract) | Actual (code + tests) | Result |
|----------|--------------------------|-------------------------|--------|
| `log_format=json` without `[obs]` | Fatal `HermesObsExtraRequired` at startup | `configure_logging` raises; `test_json_log_format_requires_obs_extra` | **pass** |
| NDJSON sink write failure | One stderr warning; continue console-only | `HermesNDJSONHandler` + `test_ndjson_handler_write_failure_degrades_once` | **pass** |
| `psutil` missing | First `sample_rss` warns `rss.sample.unavailable` once; then no-op | `hermes/obs/sampling.py` + sampling tests | **pass** |
| Dual-run compare without structlog | Skip compare; warn; still run bench | `run_bench` + `_structlog_available()` branch | **pass** |
| `dual_sink_overhead_pct > 10` on `pdf_text_small` | WARN containing `bench.dualsink.regression`; non-zero CLI exit | `_warn_dual_sink_regression`, `dual_sink_regression_triggered`, CLI `typer.Exit(1)`; bench test | **pass** |
| Stage vocabulary vs DB | `StageName` matches `save_pipeline_stage` literals | `test_stage_names_match_save_pipeline_stage_string_literals` | **pass** |
| NDJSON consumer parses only `event` JSON lines | Regression signal must not rely on `event` equality for dual-sink | Warning is plain `logging.warning`, not `HermesLogEvent`; documented | **pass** |
| CI bench runtime | T6 KC1: &lt; 5 min on GHA default | Not executed in this audit environment; local pytest ~11s | **unknown** (operational) |

---

## 7. Test coverage gap analysis (Phase 5)

**Strengths**

- Schema: positive/negative `validate_event`, v2.0 stages, `run_type`, pipeline string guard.
- Logging: console, NDJSON line shape, `bind_job`, invalid `log_format`, `HermesObsExtraRequired`, NDJSON OSError path, idempotent reset fixture.
- Sampling: `stage_timer` boundaries, exception path, periodic sampler smoke, psutil-off path.
- Bench: mock pipeline, skip missing fixture, error workload, CSV headers, dual-sink regression caplog, ordered summary.

**Gaps (prioritized)**

1. **F1:** No test that `load_config()` applies `rss_sampling_*` from TOML — because dataclass cannot express them today (**major** contract gap).
2. **Kill criteria / operational:** T6 KC1–KC3 (runner time, artifact permissions, JSON determinism) are not automated in-repo — acceptable for “informational artifact” non-goals but **unknown** without CI logs.
3. **README:** Explicit `bench.dualsink.regression` parsing guidance (F5).

Several tests are behavioral rather than tautological (e.g. disk failure, schema rejection, caplog substring).

---

## 8. Verdict

**`fail`**

**Rationale:** There are **major** findings under the skill taxonomy: **F1** (shared contract for observability config fields not implemented in the typed config surface) and **F2** (T6 orchestrator/packet scope still describes CLI flags and paths that do not exist; traceability gap between plan text and shipped CLI/CI). Automated tests pass and runtime behavior for Part B is largely coherent; the blockers are **contract/documentation/plan accuracy**, not pytest failures.

**To reach `pass`:** Add first-class `rss_sampling_enabled` / `rss_sampling_interval_s` to `ObservabilityConfig` + parsing (and document in `config.toml.example`), and reconcile **T6** (and packet T6) text with the actual `hermes bench` interface and CI command — or formally amend the plan with a recorded override.

**Optional (`pass-with-conditions` path):** If the team treats F1/F2 as **accepted post-v0.3 amendments** with an explicit plan revision, downgrade severity after updating `b-plan.md` / packets; until then this audit stands as **`fail`**.

---

## 9. Non-goals check (Phase 1)

| Non-goal | Crossed? |
|----------|----------|
| CI fail-on-threshold | No (`continue-on-error`, no gate on bench) |
| Full OpenTelemetry | No |
| Remote sinks | No |
| In-process charts | No |
| RSS in SQLite time-series | No |
| Pipeline/LLM semantics change | No observability-only wrapping (T3) |
| Part A scope | Not mixed into Part B deliverables |
| Replace stdlib logging wholesale | No; dual path preserved |
| Synthetic stress **generation** for bench | Uses fixtures / optional large PDF |

---

## 10. Contract compliance snapshot (Phase 2)

| Topic | Status |
|-------|--------|
| `LogSchemaVersion` `"2.0"` | OK |
| `StageName` four literals | OK |
| `EventName` + documented WARN-string override for dual-sink regression | OK (override) |
| Error envelope: `HermesObsExtraRequired`, NDJSON degrade, psutil warn-once | OK |
| Logger names `hermes.obs.*` / `hermes.bench.*` | OK (`hermes.bench.harness` under `hermes.bench.*`) |
| Test file naming `test_obs_*`, `test_bench_*` | OK |
| Config fields `rss_sampling_*` | **Fail** — see F1 |

---

*Auditor role: review only; no code or plan edits performed in this pass.*

---

## Resolution note (2026-04-17, executor — superseded by Part II)

Subtask **T7** subsequently closed audit findings **F1** (typed **`ObservabilityConfig`** fields for RSS sampling so user TOML applies) and **F5** (README programmatic-consumer guidance for **`bench.dualsink.regression`** WARN-string filtering). **Part II** records the auditor’s verification of that closure and the amended plan/packets for **F2** / **F6**. Original Part I severity labels remain **historical** for the pre-T7 snapshot.
