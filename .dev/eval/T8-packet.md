# T8 — Anchor-based record matching (F-02)

**Plan:** `.dev/eval/eval-plan.md` v0.2 · **Audit:** `.dev/audits/2026-04-16-eval-part-a.md` · **Log tier:** architectural

This packet is self-contained. An executor running against `executor-subtask-execution` SKILL.md plus this file has everything needed.

---

## 1. Task statement (from plan §1 + §R1 + §Plan amendments)

Build a layered evaluation subsystem for Hermes that can measure extraction quality across schema-agnostic workloads. v0.1 shipped a manifest format, a value normalizer, a scorer, a runner, and frozen fixtures. v0.2's remediation closes the two **major** audit findings that block merge and three optional follow-ups. **This subtask (T8) addresses F-02: the scorer's `_field_diffs_for_records` pairs records by list index; a live LLM returning the same records in a different order produces 100% field mismatch even when content is semantically identical.**

**v0.2 non-goals (verbatim from §R1):**

- New fixture content, new schemas, new CLI modes beyond help-text tweaks.
- LLM-as-judge, external eval vendor adapters (still deferred from v0.1).
- F-07 (golden read/write asymmetry) — observation-tier; out of scope.
- F-14 (extra-hallucinated-field detection on positive chunks) — falls out as a side-effect of T8 if we choose to surface it; not the primary deliverable.
- Rewriting or widening any v0.1 contract except the additive deltas in §2 below.

### Amendments in force (from plan §Plan amendments A-1, relevant subset for T8)

The scoring pathway depends on these implicit behavioral contracts that were previously undocumented:

| Contract | Semantics |
|----------|-----------|
| `extraction_results.record_json == "[]"` is a legitimate success state (not a missing result). |
| `llm_runs.validation_passed == True` for empty validated arrays (last-attempt + no error). |
| `parse_json_array({}) == []` and `parse_json_array([{all null}]) == []`. |
| `vehicle_fleet.VehicleRecord.numero_serie` is required (bundled copy only). |

The last row is the anchor T8 relies on: `numero_serie` is guaranteed present on every validated `VehicleRecord`.

---

## 2. Shared contracts (v0.1 §2 + v0.2 §R2 delta, relevant subset)

All v0.1 contracts remain in force. The additions below are what T8 introduces or respects.

| Topic | T8-relevant rule |
|-------|------------------|
| **Types** | Add `EvalManifest.match_key: str \| None = None`. When set, scorer pairs expected vs. actual records by this field instead of by list index. |
| **Types** | `FieldMatch` widens to `MatchType \| Literal["error", "extra"]`. `"extra"` is emitted for actual records with no golden counterpart under anchor-based matching. `MatchType` itself (in `normalize.py`) is **unchanged**. |
| **Types** | `EvalSummary` gains three optional fields: `records_matched: int \| None`, `records_extra: int \| None`, `records_missing: int \| None`. Set only when the manifest had a `match_key`; `None` in v0.1-compat mode. |
| **Error envelope** | Scorer never raises. Policy violations (duplicate anchors, anchor missing in golden) surface as `FieldDiff(match="error", error_detail=...)` entries with a clear message. |
| **Naming** | `hermes/eval/` package, `tests/test_eval_*.py`, fixture dir `tests/fixtures/eval/`, `.manifest.yaml` / `.golden.jsonl` extensions. |
| **Logging** | `hermes.eval.scorer` logger. Emit a `WARNING` for duplicate anchor values; structured fields `fixture=`, `chunk_index=`, `match_key=`, `duplicate_value=`. |
| **Tests** | pytest, files at `tests/test_eval_scorer.py`, `tests/test_eval_manifest.py`. Add multi-record reorder-invariant, missing-record, extra-record, duplicate-anchor, absent-anchor scenarios. |
| **Backwards compat** | v0.1 manifests without `match_key` must score identically to their v0.1 results. The existing `tests/test_eval_regression.py` must pass unchanged. This is a kill criterion (#4 below). |

---

## 3. Subtask block (from plan §R4 T8, verbatim)

| Field | Content |
|-------|---------|
| **ID** | T8 |
| **Scope** | Replace index-based pairing in `_field_diffs_for_records` with anchor-based pairing when `EvalManifest.match_key` is set. Add `match_key` to the manifest schema as an optional top-level field. Emit `FieldDiff(match="missing")` for golden records with no actual counterpart and `FieldDiff(match="extra")` for actual records with no golden counterpart. Preserve v0.1 behavior exactly when `match_key` is `None` (default). Update existing fixtures' manifests to set `match_key: numero_serie` (the schema's required anchor) so the regression suite exercises the new path. |
| **Files to touch** | `hermes/eval/manifest.py` (add `match_key` field + validator that errors if set but any golden record is missing it), `hermes/eval/scorer.py` (pairing logic in `_field_diffs_for_records` + extend `FieldMatch` with `"extra"`), `tests/test_eval_manifest.py` (field load + validation), `tests/test_eval_scorer.py` (reorder-invariant matching, missing records, extra records, duplicate anchor values, absent-anchor-in-row), `tests/fixtures/eval/sample_excel.manifest.yaml` + `tests/fixtures/eval/sample_pdf_text.manifest.yaml` (add `match_key: numero_serie`). |
| **Contract bindings** | All shared contracts from v0.1 §2 **and** v0.2 §R2. Specifically: the `FieldMatch` extension and `match_key` field are load-bearing. |
| **Inputs** | None (independent of T9/T10). Reads the v0.1 scorer/manifest as starting point. |
| **Outputs** | Updated manifest model with `match_key`; scorer that pairs by anchor when set; fixture manifests using `match_key`; test cases (see §Kill criteria for the four mandatory scenarios); decision log (tier = architectural). |
| **Kill criteria** | HALT and report if: (1) The chosen anchor field (`numero_serie`) is not present on all records in an existing golden file — escalate; the fixture may need a different anchor or a `match_key_fallback` contract. (2) Anchor-based matching would require schema introspection (importing the Pydantic model from `schema_ref`) rather than just reading golden keys — this widens the scorer's coupling surface; escalate. (3) Duplicate anchor values exist within a single golden record list — decide policy (first-wins + warn, or error) before proceeding. (4) Backwards-compat test (existing `test_eval_regression.py`) fails under any code path where `match_key is None`. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** A live LLM omits the anchor field for some records; those rows can't be paired. **Mitigation:** rows missing the anchor land in the "extra" bucket (reported as FieldDiff with match="extra"), counted as mismatches in the aggregate; this is strictly better than silently failing on order. **Risk:** Multiple records share the same anchor value (the field isn't really unique). **Mitigation:** first-wins pairing + warning log; second+ duplicates land as "extra." Decision log must capture this choice. **Risk:** `match_key` optional means tests pass trivially on v0.1 manifests. **Mitigation:** the T8 deliverable includes flipping both v0.1 fixture manifests to use `match_key: numero_serie`, so the regression suite actually exercises the anchor path going forward. |

### Design decisions (decision log required)

1. **Policy for duplicate anchor values** — recommend first-wins + warning log. Alternative: raise at manifest-load validation if goldens have duplicates.
2. **Policy for rows missing the anchor on the actual side** — recommend unpaired → "extra" bucket.
3. **Policy for rows missing the anchor on the golden side** — recommend error at manifest-load validator.
4. **`EvalSummary` expansion** — recommend adding `records_matched`, `records_extra`, `records_missing`; set only when anchor mode is active.

Capture the chosen policy for each in `.dev/eval/T8-decision-log.md` per the executor SKILL.

---

## 4. Filtered load-bearing assumptions (from plan §R5.2)

Assumptions that reference T8 by ID or scope:

- **#2:** `numero_serie` is a reliable anchor for the `VehicleRecord` schema's goldens. Verified by T7 — it was made required during T7. If a future schema has no natural anchor, T8's `match_key` is optional and those manifests fall back to v0.1 index behavior.
- **#3:** v0.1 manifests have `match_key: null` (or unset) and continue to score identically after T8 lands. This is the backwards-compat promise. The existing `tests/test_eval_regression.py` is the contract test; it must pass unchanged.
- **#5:** The `EvalSummary` schema can grow fields (`records_matched`, etc.) without breaking consumers. Consumers: `outcomes_to_json_blob` (uses `model_dump(mode="json")`) and the CLI table printer. Adding fields to a Pydantic `BaseModel` is additive.

---

## 5. Filtered hidden couplings (from plan §R5.4)

Couplings that involve T8:

- **T8 × T10 → `__init__.py` exports.** If T8 adds `"extra"` to `FieldMatch` but T10 lands first with a frozen `__all__`, T8's executor must append to `__all__` (add `"FieldMatch"`, `"FieldDiff"`, `"ChunkScore"`, `"EvalResult"`, `"EvalSummary"` if they aren't already exported — T10 normally handles this, but T8 is independent and may land first).
- **T8 × T3 positional pairing in existing tests.** `tests/test_eval_scorer.py::test_eval_scorer_positive_matching_golden` and friends use one record, so positional vs. anchor pairing look identical. T8 must add **multi-record** tests with **shuffled order** to prove the new behavior; existing tests continue to pass but no longer prove F-02 is fixed. Kill criterion #4 plus the explicit "add reorder-invariant test" output item guard against this.
- **T8 × live-LLM abstention (Plan amendments A-1).** Anchor-based matching relies on the actual side having the anchor populated. If the LLM legitimately abstains (empty array) on a positive chunk, T8 still reports all golden rows as "missing" — correct (it *is* a failure) but the failure mode changes from v0.1's `missing_output` to `field_mismatch` with N `missing` diffs. Decision log should call out this reason-code shift so CLI output readers aren't surprised.

---

## 6. Resolved inputs

None. T8 reads the v0.1 codebase (`hermes/eval/scorer.py`, `hermes/eval/manifest.py`) as starting point; no prior-subtask artifacts are consumed at execution time.

---

## 7. Definition of done

- [ ] `EvalManifest.match_key: str | None = None` added, with a model_validator that rejects manifests whose golden records are missing the key (A-3 recommendation) — unless the executor decides otherwise and captures the reason in the decision log.
- [ ] `_field_diffs_for_records` (or a new helper) pairs by anchor when `match_key` is set, else falls back to v0.1 index pairing.
- [ ] `FieldMatch` extended with `"extra"`; `ChunkScore.field_diffs` can include `match="extra"` and `match="missing"` entries under anchor mode.
- [ ] `EvalSummary` gains `records_matched`, `records_extra`, `records_missing` (nullable; set only in anchor mode).
- [ ] `tests/test_eval_scorer.py` includes: reorder-invariant pass; one missing golden record; one extra actual record; duplicate anchor value in goldens (policy per decision log); actual-side row missing the anchor.
- [ ] `tests/test_eval_manifest.py` covers `match_key` field load + golden-validation rule.
- [ ] `tests/fixtures/eval/sample_excel.manifest.yaml` and `sample_pdf_text.manifest.yaml` both set `match_key: numero_serie`.
- [ ] `tests/test_eval_regression.py` passes **unchanged** (kill criterion #4).
- [ ] Decision log at `.dev/eval/T8-decision-log.md` covering the four policy choices in §3.
- [ ] Changelog entry under today's date describing what + brief why (architectural tier).

HALT instead of guessing if any kill criterion (§3) fires.
