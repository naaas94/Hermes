
Remaining **work / exploration** worth tracking (from Part A closure residuals, the learning retro open questions, and `eval-plan.md` §R11 / future-work notes):

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 1 | **A-01 — anchors when no natural key** | Multi-record goldens without `match_key` stay **index-paired** (order drift on live LLM). | `hermes/eval/scorer.py` (`_field_diffs_for_records`), `hermes/eval/manifest.py` (`match_key`), README; `.dev/archive/.../eval-plan.md` A-01 row |
| 2 | **Explore generic matching (optional)** | Retro asks: **introspection** vs **Hungarian** fallback “on demand” if schemas lack a single required field or use **composite** keys. | T8 decision explicitly avoided schema introspection (see `.dev/archive/.../eval/T8-decision-log.md`); any new approach touches same pairing code + manifest schema |
| 3 | **Live-LLM / nightly eval policy** | **Variance**, **tolerance bands**, **multi-sample** aggregation still **unset** for non-mocked runs. | `hermes/eval/runner.py` (`run_pipeline` + `force_new_job=True`), CI vs local split described in retro; no aggregation layer in repo today |
| 4 | **Contract documentation template** | Retro asks whether **A-1 + §R10** pattern (**implicit persistence / construction contracts**: `record_json`, `validation_passed`, `source_pages`, Pydantic context) **generalizes** as a plan template row. | `.dev/archive/.../eval/eval-plan.md` (§Plan amendments A-1, §R10 E-1/E-2/E-3); `hermes/eval/scorer.py`, `hermes/eval/runner.py`, `hermes/extraction/pipeline.py` |
| 5 | **Refactor `scorer.py` (defer)** | **Part B** “second use case” for shared comparison — **YAGNI** until then; size is only a **signal**. | `hermes/eval/scorer.py` (~800 LOC); `hermes/eval/normalize.py` already factored for reuse |
| 6 | **A-04 — `resume_pipeline` + eval** | **No integration test**: resume path never scored through eval harness (`eval` uses fresh jobs). Revisit if **resume semantics** change. | `hermes/extraction/pipeline.py` (`resume_pipeline`), `hermes/eval/runner.py` (`force_new_job=True`), `tests/test_pipeline_integration.py` (resume only, no eval) |
| 7 | **A-02 — golden object vs array (F-07)** | **Out of scope** v0.2 §R1; **revisit** if authors use object-form goldens and **round-trip** breaks. | Golden read/write paths in eval package + manifest resolution (see audit F-07) |
| 8 | **A-03 — extra hallucinated fields (F-14)** | **By design**: schema-agnostic diff **keys off golden**; empty golden can’t flag extras. **Revisit** only if product wants that detection. | `hermes/eval/scorer.py` (field diff iteration vs golden keys) |

**New plan, not v0.2 bump:** `eval-plan.md` states further eval work should land in a **new plan** (not another version bump of Part A).

**Authoritative narrative:** `.dev/archive/eval_and_health_metrics/retrospectives/learning/2026-04-16-eval-part-a.md` (§6 open questions, §5 A-01–A-04), `.dev/archive/eval_and_health_metrics/audits/2026-04-16-eval-part-a.md` (residual table), `.dev/archive/eval_and_health_metrics/eval/eval-plan.md` (§R11 / A-01–A-04 / “Further work”).