# T2 — Live-LLM / nightly eval policy — decision log

**Subtask:** T2 (eval tackle-now plan) · **Tier:** architectural · **Date:** 2026-04-20

## Chosen approach

### 1. What the harness does today (single trial, no aggregation)

- **`hermes eval`** in default **pipeline** mode obtains results by calling **`run_pipeline`** with **`force_new_job=True`** (see `hermes/eval/runner.py`). Each invocation allocates a **new job** and runs extraction; deduplication reuse is **not** used for eval. That keeps eval tied to a full pipeline execution for the fixture rather than returning an older completed job for the same file hash.
- **`run_eval_suite`** feeds those job rows into **`score_fixture`** once per manifest. Pass/fail and field diffs describe **that run’s** output vs goldens. There is **no** in-repo layer that runs **N** trials, aggregates metrics, or computes tolerance envelopes.

### 2. Variance and non-mocked runs

- **Output variance** (temperature, model drift, prompt changes) can change extracted records between runs. The scorer remains a **deterministic** comparison of actual rows to goldens for whatever single job was scored.
- **Interpretation policy for v1 (documentation-only):**
  - **Automated gates / CI:** Continue to rely on **mocked LLM** regression (committed fixtures) so pass/fail is stable and does not require an API key.
  - **Local or scheduled runs against a real model:** Treat each result as a **single snapshot**. Record **model id** (effective LLM key) and **job id** when filing issues; a one-off mismatch is **not** by itself proof of regression without a product-chosen repeatability rule.

### 3. Multi-sample aggregation and pass/fail under variance (options for stakeholders)

No option is **selected** in this plan version (numeric bands and aggregation rules require an owner). The following are **documented alternatives** for a future plan amendment or ops playbook:

| Option | Idea | Tradeoff sketch |
|--------|------|-----------------|
| **Worst-of-N** | Fail the suite if **any** of N sequential eval runs fails. | Strict; higher flake noise cost. |
| **Median / percentile** | Run N times; aggregate a metric (e.g. field accuracy or chunk pass rate) and compare to a **threshold**. | Needs defined metric + threshold (not set here). |
| **Majority** | Pass if more than half of N runs pass. | Softer than worst-of-N; still needs N and definition of “pass” per run. |
| **Single strict** | Keep current behavior: one run, binary compare to goldens. | Simple; flaky models will show unstable CI if used unmocked. |

**Tolerance bands** (e.g. “pass if aggregate field accuracy ≥ X%”) are **deferred** until a product owner specifies X and the aggregation window.

### 4. Machine-readable knobs

- **None** in this plan version. Any future **CLI flags**, **env vars**, **manifest keys**, or **aggregated result shapes** must follow the shared contract: owning subtask id, typed parse path, and construction/round-trip tests—or an explicit deferral with no partial `getattr` shims.

### 5. Relationship to other tackle-now items

- **A-01 / `match_key`:** Ordering vs anchor pairing is orthogonal to live-LLM variance; both affect how diffs line up when multi-record chunks differ.
- **A-04 / `resume_pipeline`:** Scoring via **`ResultsMode.FROM_JOB`** still reflects **one** job’s persisted rows; the same variance considerations apply (T3 covers integration proof).

## Alternatives rejected

- **Building an experiment platform in-repo** (scheduled multi-run harness, dashboards, stored trial history): **Out of scope** for T2; cap at policy + explicit deferrals.
- **Adding eval CLI flags or env vars for N-sample or tolerance in this subtask:** Would require typed surfaces and tests; **deferred** to a follow-up plan that amends §2.

## Assumptions (if wrong, revisit)

- **`force_new_job=True`** remains the eval pipeline default so eval does not silently reuse prior completed jobs for the same fixture.
- **Stakeholders** will choose aggregation and thresholds outside this document if product needs non-mocked gating.

## Items deferred

- **Numeric tolerance bands** and **chosen aggregation rule** — require product/owner input.
- **Machine-readable aggregation** (metrics fields, `--runs`, etc.) — follow-up subtask or plan version; must satisfy typed-surface contract when implemented.

## Changelog (architectural tier)

**T2:** Document live-LLM / nightly eval policy: single-trial scoring, `force_new_job=True` eval behavior, absence of an aggregation layer, stakeholder options for multi-sample rules without selecting numeric bands, and deferral of machine-readable knobs until a plan amendment. **Rationale:** Close plan item 3 with an explicit stance while respecting the kill criterion that undefined stakeholder rules must not be invented in code.
