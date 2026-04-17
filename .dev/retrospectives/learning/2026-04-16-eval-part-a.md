# Learning retrospective — Eval Part A

**Original work:** 2026-04-16 · **Remediation & closure:** 2026-04-17  
**Plan:** `.dev/eval/eval-plan.md` v0.1 → **v0.2.2** (remediation complete; re-audit `pass`)  
**Audit:** `.dev/audits/2026-04-16-eval-part-a.md` (§1–§8 frozen 2026-04-16; **§9 addendum** 2026-04-17)  
**Methodology retro:** `.dev/retrospectives/methodology/2026-04-16-eval-part-a.md`

---

## 1. Task context

Built the first evaluation subsystem for Hermes — manifests for tagging chunks (positive / negative), a pure-function value normalizer, a scorer comparing extraction output against optional golden JSONL, a CLI + pytest runner, committed frozen fixtures, and supporting docs. T3 (scorer) and T5 (runner) were architectural tier in v0.1. The work introduced patterns that did not exist before: manifest-driven evaluation, schema-agnostic field-level diff, and golden regression. v0.1 execution also forced a four-layer tightening of the production extraction pipeline (**T7**, abstention / false-positive remediation) so the eval system measured what it claimed to measure.

**After the first audit (`fail` on F-02, F-03),** a second planning pass added **v0.2 remediation**: **T8** anchor-based record matching, **T9** page-range resolution via `chunk_page_map` and contained-in policy, **T10** package exports + CLI help + normalizer docstrings (document-only for known normalizer ambiguities). The plan gained **§Plan amendments** (A-1/A-2) for T7 and non-goals, **§R10** post-T8 contract emissions, and **§R11** closure. The audit document’s **§9 addendum** records a **re-audit `pass`** (2026-04-17).

This still qualifies for a learning retrospective because eval is a category of code where **wrong-but-passing is worse than wrong-and-failing**, and the arc from v0.1 ship → adversarial audit → scoped remediation → second pass is itself a lesson in how quality systems fail and recover.

---

## 2. What I now understand that I didn't before

**Schema-agnostic eval is fundamentally a sequencing problem, not a comparison problem.** The intuition at the start was that the hard part would be field-level comparison — currency, dates, locale. That part is tractable (~250 lines of normalizer, testable in isolation). The hard part is **how you pair records before comparing fields**. v0.1 paired by list index — fine for mocked-LLM self-replay, wrong for live LLM runs where order drifts (**F-02**). The right primitive is an **anchor**: join expected and actual on a stable field (`match_key` in the manifest), then field-diff matched pairs and surface unpaired rows as first-class signals (`extra`, `missing`, aggregates on `EvalSummary`). **T8 validated** the “anchor before normalize” ordering: the remediation did not rethink tolerance bands; it fixed **matching**.

**A “non-goal” in a plan is a load-bearing fence only if the adversarial pass can prove the deliverable doesn’t depend on the fenced surface.** Plan §1 originally said no pipeline/validator edits. That fence held until negative-chunk fixtures met validator coercion (`{}` → `[{}]`), which broke abstention scoring. The lesson is not “non-goals are useless” but that non-goals are **falsifiable claims about coupling** — they deserve the same trace-back as scoring rules. **T7 + §Plan amendments A-1/A-2** later made that honest in the plan text; the audit’s F-09 “minor” framing (discovery → decision log, not fake HALT) was right.

**Decision logs are the right artifact for mid-flight discovery; HALT-and-replan is for spec ambiguity or contract drift that changes the deliverable.** T7 was the textbook case: same goal, honest measurement required touching adjacent code. **Remediation** added a different rhythm: **T8/T9** had architectural decision logs *before* the code was “surprising,” because policy choices (FIFO duplicate anchors, contained-in page resolution, manifest immutability) were known design forks.

**The auditor’s first instinct can overweight process and underweight function — and the fix is a severity heuristic, not shame.** The original audit correctly elevated **F-02** and **F-03**; it briefly overweighted T7 as process failure until recalibration. **§9** then verified remediation against the same functional bar. **Net:** adversarial review is essential; **ranking** findings by “does this require code to fix user-visible wrongness?” keeps the verdict aligned with reality.

**“Later” in a decision log must become code or an explicit reject — not an eternal defer.** v0.1’s T3 log said the runner would eventually resolve `page_range`; v0.1 runner didn’t. That handoff created **F-03**. **T9** closed it by implementing resolution in the scorer with a **`chunk_page_map`** supplied by the runner, **without** mutating the manifest — and **superseded** the T3 log line in writing. That pattern — **chain integrity in logs** — matters when the same codebase is touched months apart.

**Documentation-only remediation for ambiguous normalizers can be the right scope.** T10 did not “fix” F-01/F-05/F-06 behavior; it documented inverse-function ambiguity (percent, dates, near-zero tolerance) and pointed authors at **`field_type_hint`**. For a v0.2 bump whose contract was “don’t silently change lenient defaults without a product decision,” that was consistent — and the plan’s §R1 non-goals explicitly excluded behavior churn.

**Implementation emits contracts the plan didn’t list until §R10.** Examples: `golden_base_dir` resolution for manifest validation when `match_key` is set; direct `EvalManifest(...)` construction requiring validation context; reason-code refinement under anchor mode when the LLM returns `[]` on a positive chunk. **Learning:** when Pydantic validation context becomes load-bearing, treat it like a public API and record it beside the plan, not only in code.

---

## 3. Decisions I made and would make again

- **Splitting T1 and T2 as parallel roots; scorer consuming both.** Keeps normalization reusable (Part B will care) and tests small.

- **Scorer `job_results` as `list[dict]`; I/O at runner edge.** Keeps T3 testable without DB/LLM.

- **`force_new_job=True` in pipeline eval mode (T5).** Prevents silent dedup reuse from defeating eval runs.

- **Mocked-LLM regression for CI, live LLM for local/nightly.** Preserves CI determinism.

- **v0.2: anchor matching with optional `match_key` and backward-compatible index path when unset.** Pragmatic: old manifests behave as v0.1; committed fixtures set `match_key` so CI exercises the real fix.

- **v0.2: contained-in page-range resolution + ambiguous vs unresolved reasons.** More robust than exact-coverage-only for real PDF chunk geometry.

- **v0.2: multiset FIFO + one WARNING per duplicate anchor value.** Rejects “fail the manifest on duplicates” while still making duplicates visible in logs.

- **v0.2: plan amendments + versioned plan (0.2, 0.2.1, 0.2.2) instead of silent edits to v0.1 narrative.** Preserves post-mortem diffability while closing F-09 traceability.

- **Parallel remediation subtasks (T8, T9, T10) with explicit merge hazards in the plan.** Small merge cost; clean audit trail.

---

## 4. Decisions I made that I would change

- **Pairing records by list index in v0.1.** Already dissected in the first retro: match rule should precede comparison rule. **Mitigated in v0.2** when `match_key` is set; **residual (A-01):** multi-record goldens without `match_key` remain order-sensitive — acceptable if documented and rare.

- **Accepting `page_range` in the manifest before the runner could resolve it.** “Model supports it” fooled me into thinking “system supports it.” **Closed in T9**; would still prefer earlier either/or: implement resolution or reject at load — v0.1 split the worst outcome (silent unresolved).

- **Not amending the plan immediately when T7 landed.** v0.2’s §Plan amendments fix this retroactively; the error was treating the plan as immutable after orchestration.

- **Auditor over-weighting process on the first pass.** Recalibrated; **§9** stayed focused on functional closure.

- **Potential under-spec of post-T8 ergonomics until §R10.** If I did it again, I’d budget one “contract emission” pass after the first architectural subtask in aRemediation chain, so E-1/E-2/E-3 land with the code, not as a patch bump.

---

## 5. Patterns in my own thinking

- **Clean separation vs. usefulness.** Pure `score_fixture` was elegant; v0.1 pushed matching policy too far down the stack. T8 pulled matching back into the scorer where manifest-level `match_key` belongs — a better balance.

- **Extensible models before a second use case.** `page_range` before resolution was YAGNI debt; remediation paid it down deliberately.

- **Trusting the adversarial pass completely.** v0.1 §5 missed validator ↔ negative-chunk coupling; the lesson stands: **trace each rule to upstream behavior**, even outside the “eval” package.

- **Confusing map and territory.** Process artifacts (verdicts, non-goals) vs. code behavior — same meta-error as before; remediation trained checking §9 against running tests, not only documents.

- **Satisfaction after `pass`.** Closure is a milestone, not proof there are no more edge cases (A-01–A-04 residuals). Guard against complacency on resume, golden round-trip, extra-field detection.

---

## 6. Open questions

- **Generic anchor inference** when a schema has no single required field, or composite keys — `match_key` is manual; is introspection or Hungarian fallback worth it on demand?

- **Deterministic live-LLM eval:** variance across runs, tolerance bands, multi-sample aggregation — still open for nightly jobs.

- **Where behavioral contracts live** in plans (`record_json`, `validation_passed`, `source_pages`) — Part A now has A-1 and §R10; does a template row for “implicit persistence contracts” generalize?

- **Factoring `scorer.py`** when Part B needs similar comparison — still “resist until second use case,” but file size is a signal.

- **`resume_pipeline` + eval (A-04)** — still not directly integration-tested; revisit if resume semantics change.

---

## 7. Single paragraph synthesis

The deepest lesson of Part A eval is that **systems whose job is to catch regressions can themselves regress invisibly** — v0.1 had crisp comparison code and a blind spot in **record matching** and **page-range handoffs**, which the first audit surfaced as major functional gaps, not style issues. **Remediation** confirmed the fix wasn’t “more tests of the same mock,” but **explicit matching policy** (anchors, duplicates, aggregates) and **wiring deferred seams** (`chunk_page_map`, contained-in resolution, decision-log supersession). **Plans must absorb discoveries** (T7 amendments, v0.2 deltas, §R10 emissions) so the next reader doesn’t mistake old non-goals for current truth. Six months out, remember: **for anything that claims to measure truth, validate the measurement path end-to-end — including order, pages, and the code that shapes the JSON before the scorer runs — and when an audit fails, prioritize the user-visible gap over the paperwork gap.**

---

## Document history

| Version | Date | Notes |
|---------|------|-------|
| 1 | 2026-04-16 | Initial learning retro (v0.1 + audit §1–§8). |
| 2 | 2026-04-17 | Updated for v0.2 remediation (T8–T10), plan v0.2.2, audit §9 re-audit `pass`, closure residuals A-01–A-04. |
