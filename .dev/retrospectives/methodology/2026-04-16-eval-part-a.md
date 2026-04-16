# Methodology retrospective — Eval Part A

**Date:** 2026-04-16
**Plan:** `.dev/eval/eval-plan.md` v0.1
**Audit:** `.dev/audits/2026-04-16-eval-part-a.md`

## 1. Task identifier

Eval subsystem (Part A of `evaluation-and-health-metrics-roadmap.md`): manifest schema (T1), value normalizer (T2), scorer (T3, architectural), frozen fixtures + goldens (T4), runner with CLI + pytest (T5, architectural), naming + docs (T6). Plus an unplanned T7 (abstention / false-positive remediation) that surfaced during T4/T5 wiring.

## 2. Plan vs reality

- **DAG match.** The planned DAG (T1, T2 parallel → T3 → T5; T4 in parallel; T6 last) executed essentially as drawn. No subtasks were resequenced. The soft "T6 → T5" dependency held (docs were written after the runner was stable).
- **Contracts held — with one extension.** §2 type/interface contracts (`EvalManifest`, `ChunkExpectation`, `ChunkLabel`, `EvalResult`, `FieldDiff`, `EvalSummary`) shipped as named, in the named modules. The error-envelope contract (eval never raises into the pipeline; errors as structured data) held. The naming convention held (modules, test files, fixture dir, manifest extension, golden extension, CLI subcommand). **The implicit pipeline contract did drift:** `extraction_results.record_json` can now be `"[]"` (empty array as success), and `llm_runs.validation_passed` is True for empty validated arrays. Both were necessary for negative-chunk scoring; both were captured in `T7-abstention-decision-log.md` and the changelog; neither was added back into the plan's §2 contracts. That's the cleanest contract drift to point at.
- **Log tier calibration.** T3 and T5 (architectural) both produced decision logs that proved useful in the audit. T1, T2, T4, T6 (standard / standard / standard / trivial) didn't write decision logs and didn't need to. The one near-miss was T1's PyYAML kill criterion firing — a standard-tier subtask hit a "flag and decide" condition. The decision was captured in the changelog entry, which is fine for standard tier; the auditor first flagged this as a process gap and was corrected. Lesson: the kill-criterion convention works as intended; the auditor's heuristic for "kill criterion fired without decision log = gap" was wrong.

## 3. HALTs and re-plans

- **Zero HALTs fired.** Genuine ambiguity didn't surface in T1–T6.
- **One discovered coupling that should have triggered HALT consideration but didn't:** the validator's `{}` → `[{}]` coercion defeating negative scoring. This was discovered during T4/T5 (when negative chunks were added to fixtures and the runner started scoring them). The chosen path was a decision log (T7) capturing a four-layer fix in non-goal files, rather than a HALT-and-replan that would have produced a T7 packet.
- **Was the no-HALT path correct?** On reflection, yes for this specific coupling. The deliverable didn't change — the eval system still measures the same thing — and the fix was narrow and well-scoped. HALT-and-replan would have added ceremony without changing the outcome. **But the decision-log-only path leaves the plan stale:** anyone reading `eval-plan.md` today still sees those four files as non-goals. A "Plan amendments" section pointing at `T7-abstention-decision-log.md` would have closed that gap with one paragraph.
- **Zero HALTs is plausible here, not suspicious.** The plan was well-scoped, the contracts were specific, the dependency graph was accurate. T7 is the only "should I have HALTed?" judgment call, and it was reasonable.

## 4. Adversarial pass calibration

- **Rejected alternatives (plan §5.1):** A (scorer-first, manifest-later), B (monolith), C (external eval tool). None of these came back to bite in execution. The "manifest-first" choice paid off — T1's models drove every downstream subtask cleanly.
- **Load-bearing assumptions (plan §5.2):**
  - **#1 (`record_json` is stable JSON array of `model_dump(mode="json")`):** held. The scorer's `_parse_record_json` reads it identically to the export path.
  - **#2 (existing fixtures are deterministic):** held in CI; not stress-tested across `pymupdf` / `openpyxl` versions, but no failures observed.
  - **#3 (PyYAML can be added):** kill criterion fired and was resolved by adding the dep. Held.
  - **#4 (chunking algorithm is stable):** held during execution. T4 had to engineer the boilerplate chunk to be large enough that `_merge_segments` didn't fold it into the positive chunk (note in `tests/generate_fixtures.py:91`). That's an implicit dependency on chunker behavior that the plan called out as a risk; mitigation worked, but the manifest's `chunk_index` values are now coupled to chunker tuning constants. Worth flagging.
- **Predicted highest-risk subtask (T4 — fixtures):** broadly correct. T4 wasn't where the hardest problem hit, but it was the catalyst — adding negative chunks to fixtures is what surfaced the validator coercion problem (which became T7). The plan's adversarial pass anticipated "we need better fixtures" as the most likely re-scoping trigger; what actually happened was "we need stricter validator behavior to make the negative chunks scoreable." Same root (fixture adequacy), different surface.
- **What the adversarial pass missed entirely:** the cross-subtask coupling between **scorer rules** (T3, especially the negative-chunk rules in §T3 Scoring rules) and **upstream extraction behavior** (validator's empty/null-dict handling). The orchestrator's adversarial pass §5.4 (hidden couplings) listed T3 ↔ pipeline `record_json` serialization, but did not list T3 ↔ validator coercion semantics. That coupling was the only real re-plan-worthy surprise.

## 5. Methodology gaps surfaced

- **Plan-amendment convention is missing.** When mid-execution discovery produces a decision log instead of a HALT-replan, the plan itself doesn't reflect that. A "Plan amendments" appendix that lists post-hoc additions (T7 → see `T7-abstention-decision-log.md`) would close the gap without forcing every mid-flight insight into a full packet. **Recommendation (do not edit the skill yet):** add as a candidate convention; if a second eval/health task produces another decision-log-only adjustment, codify.
- **Adversarial pass needs a "trace each scoring/decision rule back to the upstream behavior that produces its input" heuristic.** The scoring rules table in T3 specified what the scorer should do for each (label × output × validation) cell, but nobody traced "for the negative chunk rule to reach `correct_abstention`, what must the validator return?" That backward trace would have caught the `{}` coercion problem at planning time. **Recommendation:** candidate addition to `orchestrator-planning` adversarial pass section, but only if a second task confirms the gap is general (not a one-off).
- **Auditor heuristic correction.** The auditor's first pass classified two process observations (F-09, F-10) as defects against the plan's process rules. They were either (a) the intended use of decision logs to handle mid-flight discovery, or (b) the documented "flag and decide" path for a kill criterion at standard tier. The auditor needed user pushback to correct. **Recommendation (for `auditor-review` itself):** add a check before classifying any process finding as `major`: "Does this point at a code defect, or only at documentation? If only documentation, max severity is minor." Skill edit is a separate, deliberate act; not editing now.
- **Contracts schema (plan §2) doesn't have a slot for "implicit upstream contracts the new system depends on."** The eval system's correct operation depends on `record_json` semantics, `validation_passed` semantics, and pipeline persistence rules — none of which were captured as contracts because they're not new types/interfaces, they're behavioral. When T7 changed two of those semantics, there was no contract to update. **Recommendation:** consider adding a "Behavioral contracts depended on" row to §2, listing existing system behaviors the new code reads against. Defer the skill edit.

## 6. Single sentence verdict

The methodology held up — the plan executed cleanly with no HALTs, contracts were honored, decision logs covered the architectural-tier work and the one discovered coupling — but two methodology gaps surfaced (no convention for amending the plan after a decision-log-only adjustment, and the adversarial pass missed a cross-subtask behavioral coupling) that are worth watching on the next task before any skill edits.
