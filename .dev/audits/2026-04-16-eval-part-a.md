# Audit — Eval Part A

**Date:** 2026-04-16
**Auditor:** auditor-review skill (Opus 4.7)
**Task:** Part A of `evaluation-and-health-metrics-roadmap.md` — eval subsystem (manifest, normalizer, scorer, runner, fixtures, docs)
**Plan:** `.dev/eval/eval-plan.md` v0.1
**Scope IN:** plan + T1–T6 packets + T3/T5 decision logs + `hermes/eval/*.py` + `eval` subcommand + posterior artifacts + tests
**Scope OUT:** `.dev/part_b/`

---

## 1. Audit metadata

### Adversarial focus areas chosen

The roadmap recommended three candidates; this audit goes deep on all three because they are not redundant — each surfaces a different failure mode, and the user explicitly approved these as good targets.

1. **Edge cases in `hermes/eval/normalize.py`** — T2 is pure comparison logic with rich boundary behavior (currency, percent, date coercion). Hidden over-normalization is the most likely silent failure: it turns red into green without anyone noticing. Highest "wrong-but-passing" risk.
2. **Integration seams between `manifest` ↔ `scorer` ↔ `runner`** — the contract composition determines whether the system can score live LLM output (vs. self-replay only). Hidden assumptions about ordering and `page_range` resolution live here.
3. **Regression surface on `hermes/extraction/{validator,pipeline,prompts}.py` and `vehicle_fleet.py`** — these were explicitly listed as **non-goals** in plan §1, but were touched anyway and documented in `T7-abstention-decision-log.md`. The question is: were the changes necessary, were they correct, and did they break prior contracts?

---

## 2. Context chain completeness

| Artifact | Status | Notes |
|----------|--------|-------|
| Pre-plan analysis (`.dev/evaluation-and-health-metrics-roadmap.md`) | Present | Part A queue items mapped to subtasks in plan §Appendix |
| Plan (`.dev/eval/eval-plan.md`) | Present | v0.1, 6 subtasks (T1–T6), shared contracts in §2 |
| Shared contracts (plan §2) | Present | Types, error envelope, naming, logging, tests defined |
| T1 packet | Present | Manifest schema & loader |
| T2 packet | Present | Value normalizer |
| T3 packet | Present | Scorer engine |
| T4 packet | Present | Frozen fixtures & goldens |
| T5 packet | Present | Runner (CLI + pytest) |
| T6 packet | Present | Fixture naming & docs |
| T3 decision log | Present | Architectural tier — covered |
| T5 decision log | Present | Architectural tier — covered |
| Changelog (`CHANGELOG.md ## 2026_04_16`) | Present | Six bullets covering eval work + abstention remediation |
| `hermes/eval/manifest.py`, `normalize.py`, `scorer.py`, `runner.py`, `__init__.py` | Present | All implemented |
| `hermes/cli.py` `eval` subcommand | Present | Lines 660–836 |
| `hermes/extraction/{validator,pipeline,prompts}.py` edits | Present (and **out-of-plan** — see §3 F-09) | Documented in `T7-abstention-decision-log.md` |
| `hermes/schemas/examples/vehicle_fleet.py` edit | Present (and **out-of-plan**) | `numero_serie` made required |
| `T7 packet` (abstention/false-positive remediation) | **MISSING** | Decision log exists at `.dev/eval/T7-abstention-decision-log.md` but no `T7-packet.md`; T7 was never added to the plan's DAG, contracts, or kill criteria. See F-09. |
| `tests/test_eval_*.py` (manifest, normalize, scorer, runner, regression, fixtures) | Present | Six test files |
| `tests/fixtures/eval/*` (manifests + goldens + binaries) | Present | Two manifests + two goldens + two binary copies |
| `README.md` "How we measure quality" | Present | Lines 253–270 of README |
| `generate_test_datasets.py` rename + docstring | Present | `test_excel_stress_synthetic.xlsx` |
| `tests/generate_fixtures.py` extension | Present | Adds boilerplate sheet/page + sync to `eval/` |
| `tests/test_pipeline_integration.py` updates | Present (and out-of-plan in T6) | Adapted to new fixture layout (boilerplate page) |

**Limit on this audit imposed by the missing T7 packet:** without a packet, there is no record of what kill criteria, contract bindings, or files-to-touch were authorized for the abstention work. The decision log is the only document, and it post-hoc-justifies edits to files the plan explicitly listed as non-goals. The audit can still inspect the code, but cannot verify the changes against an *approved* spec.

---

## 3. Findings table

| ID | Severity | Type | Phase | Subtask | One-liner |
|----|----------|------|-------|---------|-----------|
| F-01 | minor | contract-violation | 2 | T2 | `normalize_value(50, "50%") → "exact"` — percent fallback over-normalizes plain integers in (0, 100] |
| F-02 | major | adversarial-fail | 4 | T3 | `_field_diffs_for_records` pairs records by **index**; live LLM order changes produce 100% field mismatch even when content is identical |
| F-03 | major | coverage-gap / adversarial-fail | 4/5 | T1+T3+T5 | `page_range` addressing is accepted by the manifest, scored as `page_range_unresolved` (always fail), and **never resolved** by the runner — entire feature path is unusable end-to-end |
| F-04 | minor | contract-violation | 2 | T1 | Package `__init__.py` exports manifest types but **not** `EvalResult`/`FieldDiff`/`EvalSummary` (contracted at the package level in plan §2) |
| F-05 | minor | adversarial-fail | 4 | T2 | `normalize_date` silently equates US (`%m/%d/%Y`) and EU (`%d/%m/%Y`) interpretations of ambiguous strings; result depends on which format succeeds first |
| F-06 | minor | adversarial-fail | 4 | T2 | `numbers_close` defaults `abs_tol=0.0`; comparisons near zero (e.g., `0` vs `1e-12`) report `mismatch`. Inconsistent with the "lenient default" philosophy declared in T2 packet. |
| F-07 | minor | adversarial-fail | 4 | T3 | `_load_golden_file_whole` writes JSON arrays (in `apply_golden_updates`) but accepts JSON objects; round-trip `--update-goldens` then re-load drifts representation between formats silently |
| F-08 | observation | — | 1 | — | Plan task statement faithfully maps roadmap Part A items; no intent narrowing or widening at the plan layer (drift happens later, see F-09) |
| F-09 | minor | undeclared-change | 1/3 | T7 (out of plan) | `validator.py`, `pipeline.py`, `prompts.py`, `vehicle_fleet.py` edited despite plan §1 listing them as non-goals. The coupling that triggered this work (validator coercing `{}` → `[{}]` defeating negative scoring) was a **real discovery during T3/T4 execution**, captured in `T7-abstention-decision-log.md`. The change is correct and necessary; the only gap is that no retroactive packet was added to the plan, so future audits cannot diff "approved spec" vs "implementation" for the T7 surface. **Recalibrated from major → minor on owner feedback (2026-04-16):** the discovery-then-decision-log path is the intended way to handle mid-flight couplings; "process violation" framing was overreach. |
| F-10 | observation | — | 3 | T1 | T1's kill criterion (2) said "flag and decide (PyYAML is standard but must be explicitly added)." The decision was flagged in the changelog entry and the dependency was added. T1 is standard tier, so a decision log is not required. **Recalibrated from minor → observation on owner feedback (2026-04-16):** "decide and document via changelog" is exactly what a standard-tier kill criterion demands; no further artifact required. |
| F-11 | observation | — | 5 | T2 | `normalize_value` test suite passes the cases declared in the T2 spec (`"$350,000.00"` vs `350000.0`, `"5%"` vs `0.05`, locale, whitespace) but does not cover the bidirectional percent/number ambiguity (F-01) or cross-locale date ambiguity (F-05) |
| F-12 | minor | contract-violation | 2 | T5 | T5 packet's CLI sketch declares `--from-results JOB_ID` accepting a positional-style value; the implemented runner additionally **requires `--manifest`** alongside it (decision log notes this). The CLI help text does not surface the requirement; users only learn it from a runtime red error message. Documented in decision log; not in the CLI help. |
| F-13 | observation | — | 4 | T4 | `tests/generate_fixtures.py` mutates the existing `sample_text.pdf` (page 2 was previously vehicle 3, now boilerplate). All consumers (`test_pipeline_integration.py`) were updated, but this is a fixture contract change beyond the scope of T4's stated mitigation ("modifying the existing fixture is too disruptive… use option 2") — option 1 was chosen and the disruption was absorbed. |
| F-14 | observation | — | 4 | T3 | Schema-agnostic field-key iteration (golden keys define the superset) means **fields the LLM emits but the golden does not** are silently ignored unless the golden record is empty. This is intentional per the T3 risk note, but worth noting: the scorer cannot detect "extra hallucinated fields" on positive chunks. |

---

## 4. Detailed findings (above minor)

### F-02 — Field diffs pair records by index; ordering changes cause false regressions

**Phase:** 4 (adversarial)
**Subtask:** T3
**Severity:** major
**Type:** adversarial-fail

**Expected behavior.** The scorer's contract (plan §T3) is to compare extraction output to goldens "schema-agnostic[ally]" via the golden keys. The pytest regression mocks the LLM to return the golden verbatim, so this works trivially. The roadmap and T5 packet both anticipate `hermes eval` running against **live LLMs** ("for local use, nightly CI with API key"). Live LLMs do not guarantee record ordering across runs, especially on long lists.

**Actual behavior.** `hermes/eval/scorer.py:119–140` (`_field_diffs_for_records`):

```119:140:hermes/eval/scorer.py
def _field_diffs_for_records(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> list[FieldDiff]:
    """Compare records pairwise; field keys come from expected rows (schema-agnostic)."""
    diffs: list[FieldDiff] = []
    n = max(len(expected), len(actual))
    for i in range(n):
        exp_row = expected[i] if i < len(expected) else {}
        act_row = actual[i] if i < len(actual) else {}
        keys = set(exp_row.keys()) | set(act_row.keys()) if exp_row or act_row else set()
        if not exp_row and not act_row:
            continue
        for key in sorted(keys):
            ...
```

Records are paired by **list index**. If the live LLM returns the same five vehicles but in a different order, every pair-wise diff is a mismatch and `field_level_accuracy` collapses to a small number — even though the extraction is semantically perfect.

**Impact.** The eval system cannot deliver on its primary stated goal ("make quality regressions visible and CI-blocking") for any real LLM run. Users will either (a) see continuous false-regression failures and disable the job, or (b) be forced to use `--update-goldens` after every run, which paper-overs real regressions — a risk the T5 packet explicitly identified and tried to mitigate via the confirmation flow.

**Evidence.** No test asserts ordering-invariant equality; `tests/test_eval_scorer.py:39` (`test_eval_scorer_positive_matching_golden`) uses one record. The regression test (`tests/test_eval_regression.py`) replays the golden bytes verbatim through the mocked LLM, so order matches by construction.

**Mitigation suggestion (not for this audit to apply).** Either: (a) match by a stable key (the schema's required-field anchor — for `VehicleRecord` that is `numero_serie`), or (b) Hungarian-match on best fit, or (c) document loudly that goldens must be deterministic and only support `--from-results`/`--from-jsonl` modes for live runs. Decision is for the orchestrator/owner.

---

### F-03 — `page_range` addressing is unusable end-to-end

**Phase:** 4–5 (adversarial + coverage)
**Subtask:** T1, T3, T5 (system-spanning)
**Severity:** major
**Type:** coverage-gap + adversarial-fail

**Expected behavior.** Plan §T1 risk mitigation: *"Manifest stores the addressing mode explicitly; scorer resolves at eval time using the job's actual chunk map. Chunk-index is primary; page-range is a convenience alias resolved before scoring."* T1's hidden coupling (§5.4) reaffirms that page-range is meant to be a working alternative.

**Actual behavior.**

1. `EvalManifest` accepts `addressing: page_range` and stores `PageRange` per chunk (`hermes/eval/manifest.py:46–88`).
2. The scorer treats every page-range expectation as `REASON_PAGE_RANGE_UNRESOLVED` and marks it failed (`hermes/eval/scorer.py:298–314`):

```298:314:hermes/eval/scorer.py
    for m_idx, exp in enumerate(manifest.chunks):
        if exp.page_range is not None:
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=None,
                    label=exp.label,
                    passed=False,
                    reason=REASON_PAGE_RANGE_UNRESOLVED,
                )
            )
            ...
            continue
```

3. The runner **never** maps page ranges to chunk indices. `hermes/eval/runner.py` has no such resolver; `score_manifest_with_results` calls `score_fixture` directly with the raw manifest (`hermes/eval/runner.py:227–232`).

T3's decision log acknowledges this: *"`page_range` expectations are not mapped to chunk indices here; they yield `page_range_unresolved` so the runner can pre-resolve to `chunk_index` later."* But the runner's decision log (T5) does **not** mention page-range resolution, and the code does not implement it.

**Impact.** Any user authoring a `page_range` manifest will see all chunks fail. The CI exit code logic (`eval_outcomes_ok`, `runner.py:462`) returns False on any failed expectation, so a CI pipeline using page-range manifests is permanently red. The committed fixtures use `chunk_index` so this never surfaces in CI.

**Evidence.** `tests/test_eval_scorer.py:161` (`test_eval_scorer_page_range_unresolved`) asserts the failure path, not a success path. No test exercises a successful page-range run because the runner cannot do it. `hermes/eval/runner.py` does not import or define any page-range → chunk-index resolver.

**Classification.** Drift (gradual, unintentional) — both decision logs hand off resolution responsibility to "later" or "the runner," and "later" never came.

---

### F-09 — T7 abstention work touched non-goal files; documented via decision log instead of retroactive packet

**Phase:** 1 + 3 (intent traceability + decision-log audit)
**Subtask:** T7 (which is not in the plan as a packet)
**Severity:** minor
**Type:** undeclared-change

**Owner clarification (2026-04-16):** The trigger was empirical — after the negative chunks were added to fixtures in T4, `hermes eval` was not catching them as `correct_abstention` because the validator coerced `{}` and all-null dicts into `[{spurious}]`. The four-layer fix was a deliberate, narrowly-scoped tightening to make the eval system measure what it claimed to measure. This is exactly what a decision log is for: capturing a discovery during execution.

**Original framing (overreach, retracted):** the first version of this finding called it a "process violation, executor should have HALTed and escalated for re-plan." That was too rigid. Discovery-then-decision-log is the intended way to handle mid-flight couplings that don't change the task statement; HALT-and-replan is reserved for ambiguous spec, contract drift, or scope expansion that *changes the deliverable*. The deliverable here was unchanged — the eval system still measures the same thing — the implementation just had to reach into adjacent code to make the measurement honest.

**What still stands as a (minor) finding.** A retroactive `T7-packet.md` would help future audits because:

- The plan's §1 Non-goals list now contains four items that *were* touched. Anyone reading the plan today still sees them as non-goals; only readers of `T7-abstention-decision-log.md` learn the truth. A one-paragraph addendum to the plan saying "T7 added 2026-04-16 — see decision log" closes that gap.
- The `record_json == "[]"` persistence semantics (`_process_chunk` now writes empty arrays as success) is a real contract change for `extraction_results`. It is correctly listed in the CHANGELOG, but is not captured anywhere in the plan's §2 contracts. If Part B (or any future eval work) reads from that table, it will need to know.
- `validation_passed` semantics on `llm_runs` shifted (now True for empty validated arrays). Same story — correct change, fully documented in CHANGELOG, not reflected in the plan's contracts.
- `vehicle_fleet.py` example schema is now strict; bundled vs. user-installed copies have diverged. CHANGELOG documents this; nothing in the plan or README does.

**Files affected.**

- `hermes/extraction/pipeline.py` (lines 939–948): `validation_passed=is_last and not result.error`; `if not result.error:` persists empty arrays.
- `hermes/extraction/validator.py` (lines 56–58, 90–96, 119–124): `{}` and all-null dict coercion to `[]`; `_drop_all_null_validated` filter.
- `hermes/extraction/prompts.py` (lines 8–14, 30–32): abstention instructions in `SYSTEM_PROMPT` + `USER_PROMPT_TEMPLATE`.
- `hermes/schemas/examples/vehicle_fleet.py` (line 10): `numero_serie: str` (required).
- `.dev/eval/T7-abstention-decision-log.md`: rationale, alternatives, assumptions, deferred items.

**Suggested follow-up (optional, low effort).** Add a "Plan amendments" section to `eval-plan.md` listing T7 with one-line summary and a pointer to the decision log. Costs a paragraph; pays back the next time someone audits this work.

---

### F-10 — Retracted (recalibrated to observation)

**Owner clarification (2026-04-16):** T1's kill criterion (2) read *"YAML parsing requires a new dependency not already in `pyproject.toml` — flag and decide (PyYAML is standard but must be explicitly added)."* The kill criterion fired, was evaluated, and the documented option ("PyYAML is standard but must be explicitly added") was chosen. The dependency add is captured in the CHANGELOG entry for the eval-manifests bullet.

T1 is **standard tier**. The plan's log-tier convention does not require a decision log for standard tier; the kill criterion's "flag and decide" instruction is satisfied by the changelog entry. There is no actual gap.

The original audit framing — *"silently bypassed instead of escalated"* — was wrong. Retracted.

---

## 5. Adversarial test log

### Focus 1 — `normalize.py` edge cases

| # | Scenario | Expected | Actual | Verdict |
|---|----------|----------|--------|---------|
| A1 | `normalize_value("$350,000.00", 350000.0)` (no hint) | `exact` | `exact` (currency fallback) | passes |
| A2 | `normalize_value("5%", 0.05)` (no hint) | `exact` | `exact` (percent fallback) | passes |
| A3 | `normalize_value(50, "50%")` (no hint) | `mismatch` (numeric 50 ≠ fraction 0.5) | **`exact`** — percent fallback rescales bare ints in (0, 100] to fraction. F-01. | **fails** |
| A4 | `normalize_value("200%", 2.0)` (no hint) | `exact` | **`mismatch`** — `parse_percent_value("200%")` = 2.0 but `parse_percent_value(2.0)` = 0.02 (rescaled). Asymmetric percent semantics. | **fails** |
| A5 | `normalize_value("01/15/2024", "15/01/2024")` (no hint) | unknown — depends on policy | `normalized` (both parse to 2024-01-15 via different format families). F-05. | passes (as coded) but ambiguous-by-design |
| A6 | `numbers_close(0, 1e-12)` (defaults) | True (intuitive) | **False** — `abs_tol=0.0` makes near-zero comparisons strict. F-06. | passes (as coded), surprising |
| A7 | `normalize_value(float("nan"), float("nan"))` | `exact` | `exact` (explicit NaN handling in `numbers_close`) | passes — well done |
| A8 | `normalize_value("Straße", "STRASSE")` | `normalized` (casefold) | `normalized` | passes |
| A9 | `normalize_value("", "  ")` | `exact` (both absent) | `exact` | passes |
| A10 | `normalize_value("0001", 1, "number")` | `exact` (1 == 1 numerically) | `exact` (`_parse_plain_number`) | passes |
| A11 | `normalize_value("1,000.5", 1000.5)` (no hint) | `exact` | `exact` (number path strips commas) | passes |
| A12 | `normalize_value("1.000,50", 1000.50)` (EU decimal — no hint) | unknown | `mismatch` (the comma-stripping assumes US thousands separator). Future risk for EU locales but not in current schema scope. | passes (as coded) |

### Focus 2 — Integration seams (manifest ↔ scorer ↔ runner)

| # | Scenario | Expected | Actual | Verdict |
|---|----------|----------|--------|---------|
| B1 | `score_fixture` with `goldens={0: [A, B, C]}` and `actual=[B, A, C]` (reordered) | All `exact` if matched semantically | All `mismatch` (paired by index). F-02. | **fails** |
| B2 | `EvalManifest(addressing="page_range", chunks=[PageRange(1,3)])` then full `run_eval_suite` | Score the chunk(s) on pages 1–3 | All `page_range_unresolved`, `eval_outcomes_ok = False` (CI red). F-03. | **fails** |
| B3 | `--from-results JOB_ID` without `--manifest` | Clear early error | ValueError raised (`hermes/eval/runner.py:257`) and CLI prints red message. | passes |
| B4 | `--update-goldens` non-interactive without `--yes` | Skip silently with warning | `_confirm_and_apply_goldens` warns & skips when stdin is not a TTY (`runner.py:447–453`). | passes |
| B5 | `--update-goldens` with both `--from-results` and `--from-jsonl` | Reject before doing anything | CLI rejects (`hermes/cli.py:729–731`); runner mode is mutually exclusive. | passes |
| B6 | Scorer output round-trip via `outcomes_to_json_blob` → JSON → consumer | Lossless | `result.model_dump(mode="json")`; tested in `test_runner_outcomes_json_roundtrip`. | passes |
| B7 | `apply_golden_updates` writes manifest-level JSONL line-by-line; line indexed by `chunk_index` ≠ manifest chunk position | Skip un-indexed expectations cleanly | Loops only over expectations with `chunk_index is not None and golden_path is None` (`runner.py:168–172`). | passes |
| B8 | Manifest sets `golden_path` per-chunk on a `chunk_index`; scorer resolves via `_load_golden_file_whole` (whole file, not line) | Consistent with `apply_golden_updates` write path | `apply_golden_updates` writes JSON array to whole file (`runner.py:152`); reader accepts both array and dict (`scorer.py:177–200`). Compatible but asymmetric — if a user authors a JSON-object golden manually, round-trip flips it to array. F-07. | passes (as coded), inconsistent |
| B9 | Pipeline mode runs the real pipeline. T5 decision log says `force_new_job=True` to avoid silent dedup reuse during eval. | Verify | `runner.py:391–398` passes `force_new_job=True`. | passes |

### Focus 3 — Regression on extraction pipeline / validator (the non-goal edits)

| # | Scenario | Expected | Actual | Verdict |
|---|----------|----------|--------|---------|
| C1 | LLM emits `[]` (legitimate abstention on negative chunk) | Persisted as success, scoreable as `correct_abstention` | `_process_chunk` writes `record_json="[]"`; `validate_with_repair` short-circuits without repair. Tested in `test_validate_with_repair_empty_array_no_repair`. | passes |
| C2 | LLM emits `{}` (empty wrapper hallucination) | `parse_json_array` coerces to `[]` (post-T7 behavior) | Tested in `test_parse_json_array_empty_dict_is_empty`. | passes |
| C3 | LLM emits `[{"a": null, "b": null}]` against an all-optional `BaseModel` | All-null row dropped to `[]` | Tested in `test_validate_with_repair_drops_all_null_records`. | passes |
| C4 | User has a custom schema with all-optional fields where "all-null" is a meaningful row | Row preserved | **Row silently dropped** — F-09 documented behavior; CHANGELOG warns but does not enforce. | regression for that user class |
| C5 | `validation_passed` field in `llm_runs` for a chunk with empty validated array (post-T7) | `True` (it validated, just empty) | `True` (`pipeline.py` change `validation_passed=is_last and not result.error`). Telemetry shifts. | passes (intentional change) |
| C6 | Existing `vehicle_fleet.py` consumers in user copies of `~/.hermes/hermes_user/examples/` | Backward-compatible | **Forked silently** — bundled example is now strict (`numero_serie: str`); `hermes init` does not refresh existing copies (CHANGELOG explicit). User running prior fixtures with the lenient copy still works; the same user re-installing gets stricter behavior. | passes (intentional) but undocumented in user-facing README |
| C7 | Prompt-version bump invalidates `contract_id` for prior runs | All new runs get a new contract id; dedup unaffected (key excludes prompt_version per existing decision) | T7 decision log notes this; `find_completed_dedup_job` doesn't include prompt_version (existing pre-T7 decision). | passes (no regression beyond the documented one) |
| C8 | `tests/test_pipeline_integration.py` after the fixture mutation (page 2 = boilerplate) | Existing assertions still hold | Tests updated to expect `len(results) >= 2`, mock returns `[]` for boilerplate marker. Both `test_full_pipeline_with_excel` and `_with_pdf` updated. | passes |
| C9 | Resume path (`resume_pipeline`) | Unaffected by T7 edits | `_process_chunk` is shared, so resumed jobs also persist empty arrays. No new test, but logically consistent. | unknown — manual smoke test recommended |

---

## 6. Coverage gap list (prioritized)

| Priority | Gap | What is untested | Why it matters |
|----------|-----|------------------|----------------|
| 1 (high) | F-02 | Order-invariant field matching for live LLM runs | This is the system's promise to live users; current tests only validate self-replay |
| 2 (high) | F-03 | Successful end-to-end `page_range` manifest run | A documented feature path that does not work end-to-end |
| 3 (med) | F-01 | Bare integer in (0, 100] vs `"N%"` string | Likely false-positive matches in real schemas with mixed numeric/percent fields |
| 4 (med) | F-05 | Cross-locale date ambiguity | Future fixtures with EU dates will hit this silently |
| 5 (med) | F-09 / C4 | All-optional user schema rows | The new validator filter changes behavior; no test asserts the user-facing semantic |
| 6 (low) | C9 | `resume_pipeline` after T7 changes | The persistence change affects resume; covered transitively but not directly |
| 7 (low) | F-12 | CLI help text for `--from-results`/`--from-jsonl` requiring `--manifest` | UX polish; runtime error suffices |

---

## 7. Verdict

**`fail`** — two **major** functional findings: F-02 (record ordering) and F-03 (`page_range` dead code). These are real gaps between what the plan promised (`hermes eval` works against live LLMs; page-range manifests are a supported alternative addressing mode) and what was built (works only for the mocked self-replay path; page-range manifests always fail). Neither is a code-quality complaint and neither is fixable by documentation alone without restricting the system's stated capability.

**Recalibration note (2026-04-16).** The first version of this audit framed F-09 as a third "major" process violation. On owner pushback, that was downgraded to minor — the abstention work was a *real coupling discovered during execution* (negative chunks weren't scoring because the validator coerced `{}` → `[{}]`), and a decision log is the appropriate artifact for that. F-10 (PyYAML dependency) was retracted entirely; "flag and decide" + changelog entry is exactly what a standard-tier kill criterion requires. Removing those left the spotlight where it belongs: F-02 and F-03.

**What must be resolved before merge — narrowed.**

1. **F-02 (record ordering).** Either (a) implement key-based or set-based matching in the scorer (the schema's required field — for `VehicleRecord` that's `numero_serie` — is a natural anchor); (b) document at the CLI/runner layer that `hermes eval` against live LLMs is **not supported** for fixtures with >1 record until F-02 is resolved; or (c) add an order-sensitivity warning when `len(actual) > 1` and `actual != expected` byte-for-byte. The status quo ships a feature that passes mocked CI and silently fails the moment a real LLM is used.

2. **F-03 (`page_range` dead code).** Either (a) implement page-range → chunk-index resolution in the runner (it would need access to the job's chunk map, which is recoverable from the pipeline output or the stored `chunks/` directory); or (b) reject `addressing: page_range` at manifest-load time with a clear "not yet supported — use chunk_index" error. Silent `page_range_unresolved` failure for any user who tries the documented feature is the worst of both worlds.

**Optional follow-ups (do not block merge).**

- F-09: add a "Plan amendments" section to `eval-plan.md` listing T7 with a pointer to the decision log. One paragraph, helps future audits.
- F-04: add `EvalResult`/`FieldDiff`/`EvalSummary` to `hermes/eval/__init__.py` exports for symmetry with the manifest types. Five-line change.
- F-01, F-05, F-06: capture in the per-field type-hint usage docs (lenient default has known surprises; recommend explicit `field_type_hint` in schemas where it matters).
- F-12: add CLI help text noting `--from-results`/`--from-jsonl` require `--manifest`.

**Net assessment.** The eval subsystem is **architecturally sound**. The code is clean, the contracts hold, the regression suite is honest about what it tests (mocked-LLM self-replay, not LLM quality), the CLI is well-formed, golden updates are guarded behind explicit confirmation, decision logs exist for both architectural-tier subtasks. The two major findings are about **scope of capability**, not correctness — the plan promised more than the implementation delivers in two specific places, and either the implementation needs to catch up or the documentation needs to walk back the promise. Owner's call which.

---

## 8. Notes for the retrospective skills

Findings to feed into `retrospective-methodology` (process):
- The plan's adversarial pass (§5) did not surface that negative-chunk scoring would interact with validator coercion (`{}` → `[{}]`). The discovery only landed once T4 added negative chunks to the fixtures and T5 wired up the runner. Add "trace each scoring rule back to the upstream contract that produces its input" as an adversarial-pass heuristic — this is the kind of cross-subtask coupling the orchestrator-planning skill exists to surface *before* execution.
- The decision-log path handled the resulting T7 work cleanly. But the plan itself was never amended to reflect that T7 happened — readers of `eval-plan.md` still see the original §1 non-goals as authoritative. Worth adding a "Plan amendments" convention so retroactive packets / decision-log-only adjustments are discoverable from the plan.
- The auditor's first pass over-indexed on process violations and under-indexed on the actual functional gaps (F-02, F-03). Add an auditor heuristic: "Before classifying a process finding as major, ask whether it points at a code defect or only at documentation; if only documentation, it is at most minor." The user's pushback caught this; the skill should have caught it on its own.

Findings to feed into `retrospective-learning` (domain/stack):
- Schema-agnostic field-level diff naturally pushes toward ordered list comparison; an "anchor field" pattern (use the schema's required field as the join key) is probably the right primitive — note for future eval/health work.
- Currency / percent / date normalization is a category of code where the **inverse function ambiguity** (50 → "50%" or 50 → "50") is the silent killer; a lenient default that auto-detects type from the *value* is fundamentally racy. Per-field type hints (already supported) should be the documented expected usage, not the escape hatch.
- A "non-goal" in a plan is only as enforceable as the executor's discipline; consider adding a code-side guard (e.g., a CI check that fails when files in a configurable "frozen during this PR" list are modified without explicit override).
