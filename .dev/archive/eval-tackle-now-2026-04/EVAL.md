
Remaining **work / exploration** worth tracking (from Part A closure residuals, the learning retro open questions, and `eval-plan.md` §R11 / future-work notes).

## Tackle now

No items queued.

## Defer

### Defer / low urgency

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 5 | **Refactor `scorer.py` (defer)** | **Part B** “second use case” for shared comparison — **YAGNI** until then; size is only a **signal**. | `hermes/eval/scorer.py` (~800 LOC); `hermes/eval/normalize.py` already factored for reuse |

### Process / documentation (not “code pending” but still “open”)

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 4 | **Contract documentation template** | Retro asks whether **A-1 + §R10** pattern (**implicit persistence / construction contracts**: `record_json`, `validation_passed`, `source_pages`, Pydantic context) **generalizes** as a plan template row. | `.dev/archive/.../eval/eval-plan.md` (§Plan amendments A-1, §R10 E-1/E-2/E-3); `hermes/eval/scorer.py`, `hermes/eval/runner.py`, `hermes/extraction/pipeline.py` |

### Optional / exploratory

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 2 | **Explore generic matching (optional)** | Retro asks: **introspection** vs **Hungarian** fallback “on demand” if schemas lack a single required field or use **composite** keys. | T8 decision explicitly avoided schema introspection (see `.dev/archive/.../eval/T8-decision-log.md`); any new approach touches same pairing code + manifest schema |
| 7 | **A-02 — golden object vs array (F-07)** | **Out of scope** v0.2 §R1; **revisit** if authors use object-form goldens and **round-trip** breaks. | Golden read/write paths in eval package + manifest resolution (see audit F-07) |

**New plan, not v0.2 bump:** `eval-plan.md` states further eval work should land in a **new plan** (not another version bump of Part A).

**Authoritative narrative:** `.dev/archive/eval_and_health_metrics/retrospectives/learning/2026-04-16-eval-part-a.md` (§6 open questions, §5 A-01–A-04), `.dev/archive/eval_and_health_metrics/audits/2026-04-16-eval-part-a.md` (residual table), `.dev/archive/eval_and_health_metrics/eval/eval-plan.md` (§R11 / A-01–A-04 / “Further work”).

---

## DONE

Eval **tackle-now** plan (`.dev/plans/eval-tackle-now-2026-04`) — completed items moved here from **Tackle now**.

| # | Item | Rationale / outcome | Primary files / refs |
|---|------|---------------------|----------------------|
| 1 | **A-01 — anchors when no natural key** | Multi-record file-backed goldens without `match_key` are rejected at `load_manifest`; runtime warning for in-memory multiset paths; index-only pairing documented as unsafe for multisets. | `hermes/eval/scorer.py` (`_field_diffs_for_records`), `hermes/eval/manifest.py` (`match_key`), README; `.dev/archive/.../eval-plan.md` A-01 row |
| 3 | **Live-LLM / nightly eval policy** | **Documented:** single-trial scoring, `force_new_job=True` for default pipeline eval, no in-repo aggregation; variance and multi-sample options deferred pending product thresholds. | **Decision log:** `.dev/decision-logs/eval-tackle-now-T2-live-llm-policy.md`. Code refs: `hermes/eval/runner.py` (`run_pipeline` + `force_new_job=True`) |
| 6 | **A-04 — `resume_pipeline` + eval** | **Covered:** `tests/test_eval_resume_integration.py` runs `resume_pipeline` then **`run_eval_suite`** with **`ResultsMode.FROM_JOB`** (same `job_id`, mocked LLM). Default `hermes eval` still uses fresh jobs (`force_new_job=True`). Revisit if **resume semantics** change. | `hermes/extraction/pipeline.py` (`resume_pipeline`), `hermes/eval/runner.py`, `tests/test_eval_resume_integration.py` (A-04); `tests/test_pipeline_integration.py` (resume mechanics only) |
| 8 | **A-03 — extra hallucinated fields (F-14)** | **By design** (documented): positive chunks **without a golden** get **`schema_pass_no_golden`**; with goldens, paired rows use union of keys; **`FieldMatch` `"extra"`** = orphan actual **records** in anchor mode, not extra keys on a matched row. **Revisit** only with product approval. | `hermes/eval/scorer.py` (module docstring, `_field_diffs_for_records`) |
