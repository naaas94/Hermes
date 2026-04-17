# T9 — Page-range resolution in runner (F-03)

**Plan:** `.dev/eval/eval-plan.md` v0.2 · **Audit:** `.dev/audits/2026-04-16-eval-part-a.md` · **Log tier:** architectural

This packet is self-contained. An executor running against `executor-subtask-execution` SKILL.md plus this file has everything needed.

---

## 1. Task statement (from plan §1 + §R1 + §Plan amendments)

Build a layered evaluation subsystem for Hermes that can measure extraction quality across schema-agnostic workloads. v0.1 shipped a manifest format, a value normalizer, a scorer, a runner, and frozen fixtures. v0.2's remediation closes the two **major** audit findings that block merge and three optional follow-ups. **This subtask (T9) addresses F-03: manifests with `addressing: page_range` are accepted at load time, scored as `page_range_unresolved` (always fail), and the runner never resolves them — the entire feature path is unusable end-to-end.**

**v0.2 non-goals (verbatim from §R1):**

- New fixture content, new schemas, new CLI modes beyond help-text tweaks.
- LLM-as-judge, external eval vendor adapters (still deferred from v0.1).
- F-07 (golden read/write asymmetry) — observation-tier; out of scope.
- F-14 (extra-hallucinated-field detection on positive chunks) — not T9's surface.
- Rewriting or widening any v0.1 contract except the additive deltas in §2 below.

### Amendments in force (from plan §Plan amendments A-1, relevant subset for T9)

T9's resolver reads `extraction_results.source_pages` — a previously-undocumented but long-standing contract:

| Contract | Semantics |
|----------|-----------|
| `extraction_results.source_pages` is a comma-separated string of 1-based page integers (e.g. `"1,2,3"`). Persisted by `hermes/extraction/pipeline.py:991` and stored at `hermes/db.py:305`. Parsed via `",".join(str(p) for p in chunk.source_pages)` on write. |

T9 treats this as a read-only upstream contract.

---

## 2. Shared contracts (v0.1 §2 + v0.2 §R2 delta, relevant subset)

All v0.1 contracts remain in force. The additions below are what T9 introduces or respects.

| Topic | T9-relevant rule |
|-------|------------------|
| **Types** | `score_fixture` signature gains an optional `chunk_page_map: Mapping[int, tuple[int, int]] \| None = None` — inclusive (start, end) page range per `chunk_index`. When provided and an expectation uses `page_range`, the scorer resolves it to `chunk_index` before scoring. When absent, page-range expectations continue to emit `page_range_unresolved` (v0.1 behavior preserved for callers that don't know page layout). |
| **Types** | `ChunkReason` literal widens to include `"page_range_ambiguous"`. `"page_range_unresolved"` is retained for the "no map provided / zero candidates" case. |
| **Runner** | `job_results_from_db_rows` must include `source_pages` per row. Runner derives `chunk_page_map` from these rows and passes it to `score_fixture`. `load_job_results_from_jsonl` passes `source_pages` through when present; tolerates absence. |
| **Error envelope** | Scorer never raises. Ambiguous or unresolvable page ranges surface as `ChunkScore(passed=False, reason="page_range_ambiguous" | "page_range_unresolved")` exactly as v0.1 did for the single-reason case. |
| **Logging** | `hermes.eval.scorer` and `hermes.eval.runner` loggers. Log `INFO` per resolution with fields `fixture=`, `page_range=`, `resolved_chunk_index=`; `INFO` per ambiguous/unresolvable with `reason=`. |
| **Tests** | pytest, files at `tests/test_eval_scorer.py`, `tests/test_eval_runner.py`. Add one successful resolution, one ambiguous (multiple candidate chunks), one unresolvable (no matching chunk), and one pass-through of `page_range_unresolved` when `chunk_page_map is None`. |
| **Backwards compat** | Callers that do not pass `chunk_page_map` see v0.1 behavior exactly. The v0.1 regression suite must pass unchanged. |

### Post-T8 contract emissions you must respect (plan §R10)

T8 landed and emitted three contracts that the v0.2 plan did not originally specify. They are binding on T9:

- **E-1 `golden_base_dir` resolution.** `hermes/eval/manifest.py::infer_golden_base_dir(manifest_path)` walks up to `pyproject.toml` (12 levels), fallback = manifest parent. `load_manifest` uses this for the validation context. Runner uses `project_root` (same place in-tree). **Do not invent a second policy** for the new `sample_pdf_text_by_pages.manifest.yaml` fixture or its tests — rely on `load_manifest` / `infer_golden_base_dir`, or pass `project_root` explicitly when scoring.
- **E-2 `EvalManifest(...)` direct construction.** If any T9 test constructs a manifest **with `match_key` set**, it **must** use `EvalManifest.model_validate(data, context={"golden_base_dir": Path(...)})` or `load_manifest(path)`. The bare `EvalManifest(**kwargs)` constructor raises when `match_key` is set without context. Since T9's focus is page-range (orthogonal to match_key), the simplest path is to author `sample_pdf_text_by_pages.manifest.yaml` **without `match_key`** and load it via `load_manifest`. If the T9 executor chooses to also exercise anchor mode in the new fixture, use `model_validate` with the context kwarg in any test that bypasses `load_manifest`.
- **E-3 reason-code refinement (informational).** Under anchor mode, an empty actual against a positive golden now emits `reason=field_mismatch` + N `missing` FieldDiffs, not `missing_output`. T9 does not create new reason codes beyond `"page_range_ambiguous"`; this note is only so T9 test assertions on reason codes for anchor-mode manifests use the current taxonomy, not v0.1's.

---

## 3. Subtask block (from plan §R4 T9, verbatim)

| Field | Content |
|-------|---------|
| **ID** | T9 |
| **Scope** | Implement page-range → chunk-index resolution so manifests using `addressing: page_range` can run end-to-end. The scorer gains an optional `chunk_page_map: Mapping[int, tuple[int, int]] \| None` parameter (see §2). The runner builds this map from each job row's `source_pages` (already stored in `extraction_results`) and passes it to `score_fixture`. A `page_range` expectation resolves to the single chunk whose page set **exactly covers** the requested range; ambiguous (multiple candidates) or unresolvable (zero candidates) ranges continue to emit `page_range_unresolved` (v0.1 behavior) with a more specific reason string. Add an end-to-end test using a page-range manifest variant. |
| **Files to touch** | `hermes/eval/scorer.py` (accept `chunk_page_map`, new resolution helper `_resolve_page_range_to_chunk_index`, extend `ChunkReason` literals with `"page_range_ambiguous"`), `hermes/eval/runner.py` (derive map in `job_results_from_db_rows` — or in a new `build_chunk_page_map(job_results) -> dict[int, tuple[int, int]]` helper; pass through `score_manifest_with_results`), `hermes/eval/__init__.py` (no change from T9 alone; T10 handles exports), `tests/test_eval_scorer.py` (page-range resolution success; ambiguous; unresolved), `tests/test_eval_runner.py` (page-range manifest, DB mode, JSONL mode), `tests/fixtures/eval/sample_pdf_text_by_pages.manifest.yaml` (new sibling manifest using `addressing: page_range` against the existing PDF fixture — no new PDF needed). |
| **Contract bindings** | v0.1 §2 + v0.2 §R2. Critical: `score_fixture` signature gains an optional kwarg; callers that don't pass it see identical v0.1 behavior. `source_pages` is parsed as a comma-separated list of 1-based page integers per `hermes/db.py:305` and `hermes/extraction/pipeline.py:991`. |
| **Inputs** | None (independent of T8/T10). Reads `extraction_results.source_pages` — an **implicit behavioral contract** already listed under §Plan amendments A-1. |
| **Outputs** | Working page-range manifest path; new sibling manifest fixture; tests covering resolution success, ambiguity, unresolvable; decision log (tier = architectural — new scoring contract parameter + new failure mode). |
| **Kill criteria** | HALT and report if: (1) `source_pages` is empty or absent for some job rows (possible on a partially-failed run) — decide whether to treat as "cannot resolve" or fail loudly. Recommend: rows with empty `source_pages` are omitted from `chunk_page_map`; the corresponding expectations surface `page_range_unresolved`. (2) No existing fixture has >1 chunk, making the new manifest pointless — escalate; may need to raise `MAX_CHUNK_TOKENS` down for the fixture or author a third fixture (out of scope per §R1). (3) Resolution policy "exact coverage" proves too strict for real fixtures (e.g., a `page_range: 1–3` that actually lands inside a chunk spanning pages 1–5) — decide before coding whether to support "contained-in" resolution and what reason string to emit. (4) The page-range manifest fixture's resolved chunk_index is not deterministic across chunker tuning changes (already-flagged dependency in v0.1 §5.2 #4) — accept the coupling or reject `addressing: page_range` at manifest-load time. |
| **Log tier** | architectural |
| **Risks & mitigations** | **Risk:** The chunker's behavior changes (merge thresholds, window size) and a previously-resolvable range becomes ambiguous. **Mitigation:** the runner's reason string distinguishes `page_range_ambiguous` (multiple matching chunks) from `page_range_unresolved` (zero or no map); CI failure message tells the maintainer which side of the coupling broke. **Risk:** `from_jsonl` mode omits `source_pages` (not required today). **Mitigation:** the JSONL loader in `load_job_results_from_jsonl` should pass `source_pages` through when present and tolerate its absence; if absent, map is incomplete and resolution fails gracefully with the same `page_range_unresolved` reason. **Risk:** Adding the new fixture manifest ties the `eval_outcomes_ok` CI signal to chunker determinism. **Mitigation:** the new manifest uses "contained-in" resolution (if adopted per kill-criterion #3) against a page range large enough to survive chunker-tuning noise. |

### Design decisions (decision log required)

1. **Resolution policy** — recommend contained-in: a `page_range: 2–3` resolves to any chunk whose `source_pages` is a subset of or equal to `{2, 3}`; if no such chunk exists, fall back to the chunk whose `source_pages` fully contains `{2, 3}` — but only if exactly one. Alternative: exact-coverage only (stricter, more deterministic; may not match real fixtures).
2. **Resolution strategy** — recommend the scorer resolves lazily via `chunk_page_map` and never mutates the manifest (keeps `EvalManifest` immutable as a Pydantic model; keeps resolution re-entrant for retries). Alternative: runner rewrites `expectation.chunk_index` in place before calling scorer.
3. **Behavior when `addressing: page_range` but `chunk_page_map is None`** — recommend keep soft behavior (v0.1 compat): scorer emits `page_range_unresolved` for each. Alternative: error at scorer entry.
4. **Where to build the map** — recommend a new `build_chunk_page_map(job_results: list[dict]) -> dict[int, tuple[int, int]]` in `runner.py` that consumes the `source_pages` string and returns `(min(pages), max(pages))` for each `chunk_index`. Parsing lives in one place; scorer doesn't know the string format.

Capture the chosen policy for each in `.dev/eval/T9-decision-log.md` per the executor SKILL. The decision log must also explicitly supersede the line in `.dev/eval/T3-decision-log.md` that said "`page_range` expectations… yield `page_range_unresolved` so the runner can pre-resolve to `chunk_index` later" — T9 is the "later" that line promised.

---

## 4. Filtered load-bearing assumptions (from plan §R5.2)

Assumptions that reference T9 by ID or scope:

- **#1:** `extraction_results.source_pages` format is `"1,2,3"` (comma-separated 1-based page integers). Verified at `hermes/db.py:305` and `hermes/extraction/pipeline.py:991`. If this format changes, T9's resolver breaks. Mitigated by T9's test reading from real pipeline output, not a hand-crafted string.
- **#4:** The chunker's behavior is stable across the v0.2 window. T9's new page-range fixture makes this coupling stricter. If the chunker is retuned during v0.2 execution, the fixture's resolved `chunk_index` may drift. Mitigation: T9's decision log must capture the chunker-tuning assumption and recommend using the "contained-in" resolution policy to tolerate small drifts.

---

## 5. Filtered hidden couplings (from plan §R5.4)

Couplings that involve T9:

- **T9 × v0.1 T3 decision log.** The v0.1 T3 log said "runner should pre-resolve page_range." T9 implements that, but instead of mutating the manifest, passes a `chunk_page_map` to the scorer. T9's decision log must explicitly supersede that line of the T3 log (decision-log chain integrity).
- **T9 × the v0.1 regression suite.** `tests/test_eval_regression.py` replays goldens with a mocked LLM that returns a single list verbatim. Mocked-LLM output has no `source_pages` of its own; the runner's DB read still populates `source_pages` from the real pipeline execution under mocked LLM calls. T9's new page-range fixture will exercise this path; T9's test must verify that the mocked pipeline still populates `source_pages` correctly (it should, since the mock is applied at the LLM layer, not the chunker layer — but this assumption is worth an explicit assertion in the test).

---

## 6. Resolved inputs

None. T9 reads the v0.1 codebase (`hermes/eval/scorer.py`, `hermes/eval/runner.py`, `hermes/db.py`, `hermes/extraction/pipeline.py`) as starting point; no prior-subtask artifacts are consumed at execution time. `source_pages` semantics are inlined in §1 and §2 of this packet.

---

## 7. Definition of done

- [ ] `score_fixture` accepts an optional `chunk_page_map: Mapping[int, tuple[int, int]] | None = None`.
- [ ] When set, `page_range` expectations resolve to `chunk_index` via the chosen policy (§3 decision #1) before scoring; unresolved/ambiguous cases surface as `ChunkScore(passed=False, reason=...)` with distinct reason strings.
- [ ] `ChunkReason` literal widened with `"page_range_ambiguous"`.
- [ ] `build_chunk_page_map(job_results)` helper in `runner.py` parses `source_pages` strings and returns `dict[int, tuple[int, int]]`.
- [ ] `job_results_from_db_rows` includes `source_pages` per row; `score_manifest_with_results` builds the map and passes it through.
- [ ] `load_job_results_from_jsonl` tolerates absent `source_pages` and passes it through when present.
- [ ] New manifest `tests/fixtures/eval/sample_pdf_text_by_pages.manifest.yaml` uses `addressing: page_range` against the existing `sample_text.pdf` fixture. At least one chunk must resolve successfully under the chosen policy.
- [ ] `tests/test_eval_scorer.py` covers: successful resolution, ambiguous, unresolvable (zero candidates), and pass-through when `chunk_page_map is None`.
- [ ] `tests/test_eval_runner.py` covers: DB-mode end-to-end with page-range manifest; JSONL-mode with `source_pages` present; JSONL-mode with `source_pages` absent (graceful `page_range_unresolved`).
- [ ] `tests/test_eval_regression.py` passes **unchanged** (backwards compat).
- [ ] Decision log at `.dev/eval/T9-decision-log.md` covering the four policy choices in §3, and explicitly superseding the relevant line of `.dev/eval/T3-decision-log.md`.
- [ ] Changelog entry under today's date (architectural tier).

HALT instead of guessing if any kill criterion (§3) fires.
