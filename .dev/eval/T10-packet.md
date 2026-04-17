# T10 — Exports + CLI help + normalizer docstrings (F-04, F-12, F-01/F-05/F-06)

**Plan:** `.dev/eval/eval-plan.md` v0.2 · **Audit:** `.dev/audits/2026-04-16-eval-part-a.md` · **Log tier:** trivial

This packet is self-contained. An executor running against `executor-subtask-execution` SKILL.md plus this file has everything needed.

---

## 1. Task statement (from plan §1 + §R1)

Build a layered evaluation subsystem for Hermes that can measure extraction quality across schema-agnostic workloads. v0.1 shipped a manifest format, a value normalizer, a scorer, a runner, and frozen fixtures. v0.2's remediation closes the two **major** audit findings that block merge and three optional follow-ups. **This subtask (T10) bundles three small polish items the auditor recommended as "optional follow-ups (do not block merge)":**

- **F-04**: `hermes/eval/__init__.py` exports the manifest types but omits the scorer types (`EvalResult`, `FieldDiff`, `EvalSummary`) even though v0.1 §2 declared them as package-level contracts.
- **F-12**: `hermes eval --from-results` and `--from-jsonl` require `--manifest` at runtime, but the CLI help text doesn't say so; users only learn the requirement from a red error.
- **F-01, F-05, F-06**: documented normalizer ambiguities that the auditor recommends be surfaced in docstrings so downstream users reach for `field_type_hint` as the escape hatch. **No behavior changes** — v0.2 documents the existing behavior.

**v0.2 non-goals (verbatim from §R1):**

- New fixture content, new schemas, new CLI modes beyond help-text tweaks.
- LLM-as-judge, external eval vendor adapters (still deferred from v0.1).
- F-07 (golden read/write asymmetry) — observation-tier; out of scope.
- F-14 (extra-hallucinated-field detection on positive chunks) — not T10's surface.
- Rewriting or widening any v0.1 contract except the additive deltas in §2 below.
- **Fixing** F-01/F-05/F-06 in `normalize.py` — T10 documents only. Any code fix lands in a future task if the owner decides the current behavior is wrong.

---

## 2. Shared contracts (v0.1 §2 + v0.2 §R2 delta, relevant subset)

All v0.1 contracts remain in force. The additions below are what T10 introduces or respects.

| Topic | T10-relevant rule |
|-------|------------------|
| **Package exports** | `hermes/eval/__init__.py` additionally exports `EvalResult`, `FieldDiff`, `FieldMatch`, `ChunkScore`, `ChunkReason`, `EvalSummary`. Matches the contract v0.1 §2 already stated but `__init__` did not implement (F-04). |
| **CLI** | `hermes eval --help` must surface that `--from-results` and `--from-jsonl` require `--manifest`. Runtime error (`hermes/eval/runner.py:257` / `:262`) remains the source of truth; help text mirrors it. |
| **Docstrings** | `hermes/eval/normalize.py` module docstring + `normalize_value` docstring explicitly document the three known ambiguity classes (bare int vs. `"N%"`, US/EU date ambiguity, `abs_tol=0.0` near-zero behavior) and recommend `field_type_hint` as the escape hatch. |
| **README** | The existing "How we measure quality" section (README ~lines 253–270) gets a one-line note pointing at `field_type_hint` for ambiguous fields. |
| **Naming** | No new symbols introduced. `__all__` ordering follows existing convention (alphabetical). |
| **Logging** | No new log events. |
| **Tests** | Trivial tier does not require new tests. The executor **may** add a single smoke test `tests/test_eval_exports.py` asserting `from hermes.eval import EvalResult, FieldDiff, EvalSummary, ChunkScore, FieldMatch, ChunkReason` succeeds — optional. |
| **Backwards compat** | Nothing removed; everything additive. |

### Post-T8 contract emissions you must respect (plan §R10)

T8 landed before T10 and emitted three contracts that the v0.2 plan did not originally specify:

- **E-1 `golden_base_dir` resolution.** `hermes/eval/manifest.py::infer_golden_base_dir` walks up to `pyproject.toml` (12 levels), fallback = manifest parent. Only relevant to T10 if the optional smoke test at `tests/test_eval_exports.py` exercises a full `load_manifest` call — which it shouldn't need to.
- **E-2 `EvalManifest(...)` direct construction.** Same note as E-1 — only relevant if T10's smoke test constructs a manifest in code. If it does and sets `match_key`, use `EvalManifest.model_validate(data, context={"golden_base_dir": Path(...)})`. Otherwise ignore.
- **E-3 reason-code refinement (anchor mode).** Under anchor mode, an empty actual vs. a positive golden emits `reason=field_mismatch` + N `missing` FieldDiffs — strictly more informative than v0.1's `missing_output`. **Echo this in T10's normalizer/README guidance** as a short note: "When `match_key` is set on a manifest, failure detail is reported as per-record `missing` / `extra` FieldDiffs rather than a coarse chunk-level reason; callers that key off `reason` strings should look at `field_diffs` and the new `EvalSummary.records_matched`/`records_extra`/`records_missing` counts for specifics." One sentence in the README addition suffices.

### Exports to add (confirmed against current `__init__.py` after T8)

`hermes/eval/__init__.py` as of T8 still exports only: `ChunkExpectation`, `ChunkLabel`, `EvalManifest`, `PageRange`, `load_manifest`. T10 must add:

- `ChunkReason` (from `scorer.py`)
- `ChunkScore`
- `EvalResult`
- `EvalSummary` (with T8's new optional `records_matched`, `records_extra`, `records_missing` fields already defined on the model — additive, nothing extra to do)
- `FieldDiff`
- `FieldMatch` (T8 widened this to include `"extra"` — export the alias as-is; consumers get the updated union)

Append to `__all__` alphabetically; do not reorder existing entries.

---

## 3. Subtask block (from plan §R4 T10, verbatim)

| Field | Content |
|-------|---------|
| **ID** | T10 |
| **Scope** | Three small, related polish items bundled into one trivial-tier task. (a) Extend `hermes/eval/__init__.py` to export `EvalResult`, `FieldDiff`, `FieldMatch`, `ChunkScore`, `ChunkReason`, `EvalSummary` (contracted in v0.1 §2, never exported — F-04). (b) Update `hermes eval` CLI help text so `--from-results` and `--from-jsonl` explicitly note "requires --manifest" (F-12). (c) Add docstring warnings to `normalize.py` covering the three known ambiguity classes the auditor surfaced (bare int vs. `"N%"` — F-01; US/EU date ambiguity — F-05; `abs_tol=0.0` near-zero behavior — F-06) and recommend explicit `field_type_hint` usage in the `normalize_value` docstring. **No behavior changes in normalize.py** — v0.2 documents the existing behavior; any code fix lands in a future task if the owner decides the current behavior is wrong. |
| **Files to touch** | `hermes/eval/__init__.py` (add exports), `hermes/cli.py` (help text for the `eval` Typer command — locate the options in the existing `eval` subcommand, roughly `cli.py` lines 660–836), `hermes/eval/normalize.py` (docstring additions only), `README.md` ("How we measure quality" section — add a one-line note pointing at `field_type_hint` as the recommended escape hatch for ambiguous fields), `CHANGELOG.md` (one bullet under the 2026-04-17 entry the v0.2 executor creates). No test changes required; the trivial tier means the executor may add a single smoke test for the new `__init__` exports if it feels warranted. |
| **Contract bindings** | v0.1 §2 + v0.2 §R2 (specifically: the exports list matches §R2's "Package exports" row). |
| **Inputs** | None. **Soft dependency on T8:** if T8 adds `FieldMatch = ... \| "extra"` and/or introduces `records_matched`/`records_extra`/`records_missing` on `EvalSummary`, T10 re-exports should include those. If T10 lands before T8, T8's executor appends the new type to the `__all__` list. |
| **Outputs** | Updated exports, updated help text, updated docstrings, one-line README addition, one changelog bullet. No decision log (trivial tier). |
| **Kill criteria** | HALT and report if: (1) Adding an export creates a circular import (unlikely; flagged for safety). (2) The CLI help text can't be updated without restructuring the Typer command (Typer options carry their own `help=`; should be a one-line change per option). (3) The README's "How we measure quality" section has already been rewritten by an unrelated PR and the guidance no longer fits — escalate; do not rewrite the section wholesale in a trivial-tier task. |
| **Log tier** | trivial |
| **Risks & mitigations** | **Risk:** The normalizer docstring warnings drift from the actual behavior if T8 or a future task changes normalize.py. **Mitigation:** add a one-line comment at the top of each warning block saying "verified against `tests/test_eval_normalize.py::<test_name>`" so future edits know what to re-verify. **Risk:** Export additions break `from hermes.eval import *` semantics for downstream code. **Mitigation:** this package currently uses explicit `__all__`; appending to `__all__` is additive and safe. |

### Specific docstring content to add (F-01, F-05, F-06)

For the executor's convenience — substance to include in `normalize.py` docstrings without prescribing exact wording:

1. **Percent/number ambiguity (F-01/A3/A4).** `normalize_value(50, "50%")` returns `"exact"` because the percent fallback rescales bare integers in `(0, 100]` to fractions. Similarly, `normalize_value("200%", 2.0)` returns `"mismatch"` because `parse_percent_value("200%") == 2.0` but `parse_percent_value(2.0) == 0.02` (rescaled). Recommendation: when a field is semantically numeric but may appear as a percent in source data, set `field_type_hint` explicitly to `"number"` or `"percent"` in the manifest/golden.

2. **Date ambiguity (F-05/A5).** `normalize_value("01/15/2024", "15/01/2024")` returns `"normalized"` because both parse to `2024-01-15` via different format families (US `%m/%d/%Y` vs. EU `%d/%m/%Y`); the first family that parses wins. Recommendation: use ISO (`YYYY-MM-DD`) in goldens, and set `field_type_hint="date"` to disable the numeric fallback.

3. **Near-zero tolerance (F-06/A6).** `numbers_close(0, 1e-12)` returns `False` because `abs_tol` defaults to `0.0`. This is intentional strictness but surprising for "close to zero" intuition. Callers who want lenient near-zero comparisons should pass an explicit `abs_tol` or normalize through `normalize_value(..., field_type_hint="number")` which applies the lenient default.

Each block should note which test file case demonstrates the behavior (e.g., `tests/test_eval_normalize.py::test_normalize_value_percent_fallback` — executor may need to look up the actual test names).

### CLI help text tweaks (F-12)

In `hermes/cli.py`'s `eval` Typer command, the options declared roughly at lines 660–836:

- `--from-results` help should end with "requires --manifest" (or similar wording).
- `--from-jsonl` help should end with "requires --manifest".

One-line additions per option. Do not restructure the command.

### README addition

In the "How we measure quality" section (~README lines 253–270), add one sentence after the existing normalization paragraph: something equivalent to "For fields where the lenient default might match too eagerly (bare integers vs. percent strings, ambiguous dates, near-zero comparisons), set `field_type_hint` explicitly in the manifest to disable the relevant fallback." Link to `hermes/eval/normalize.py` for details if the section already cross-references source.

---

## 4. Filtered load-bearing assumptions (from plan §R5.2)

Assumptions that reference T10 by ID or scope:

- **#5:** The `EvalSummary` schema can grow fields (`records_matched`, etc. — added by T8) without breaking consumers. T10's re-exports include `EvalSummary`; any growth from T8 is transitively visible, which is fine because Pydantic additions are non-breaking for JSON consumers.

---

## 5. Filtered hidden couplings (from plan §R5.4)

Couplings that involve T10:

- **T8 × T10 → `__init__.py` exports.** If T8 adds `"extra"` to `FieldMatch` but T10 lands first with a frozen `__all__`, T8's executor must append to `__all__`. Not a real conflict, just a merge ordering note. **Executor guidance for T10:** include `"FieldMatch"` in the exports list regardless of T8's landing order — the symbol already exists in v0.1 `scorer.py` as `FieldMatch = MatchType | Literal["error"]`.

---

## 6. Resolved inputs

None. T10 reads the v0.1 codebase (`hermes/eval/__init__.py`, `hermes/eval/normalize.py`, `hermes/eval/scorer.py`, `hermes/cli.py`, `README.md`) as starting point. No prior-subtask artifacts are consumed at execution time.

---

## 7. Definition of done

- [ ] `hermes/eval/__init__.py` `__all__` includes (in addition to v0.1 entries): `"ChunkReason"`, `"ChunkScore"`, `"EvalResult"`, `"EvalSummary"`, `"FieldDiff"`, `"FieldMatch"`.
- [ ] Corresponding imports added at the top of `__init__.py`.
- [ ] `hermes eval --help` output surfaces "requires --manifest" on both `--from-results` and `--from-jsonl`.
- [ ] `hermes/eval/normalize.py` module docstring (or `normalize_value` docstring) includes the three ambiguity-class warnings from §3 with at least one test-name pointer each.
- [ ] README "How we measure quality" section includes a one-sentence note about `field_type_hint` as the escape hatch for ambiguous fields.
- [ ] CHANGELOG has one bullet under today's date describing the three polish items (trivial tier, what-only suffices).
- [ ] Optional: `tests/test_eval_exports.py` smoke test asserting all new exports are importable.
- [ ] All existing tests pass unchanged.

No decision log required (trivial tier). HALT instead of guessing if any kill criterion (§3) fires.
