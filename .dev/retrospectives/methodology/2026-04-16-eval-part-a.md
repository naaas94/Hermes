# Methodology retrospective — Eval Part A (full arc)

**Dates:** 2026-04-16 (initial delivery + first audit) through **2026-04-17** (v0.2 remediation + re-audit `pass`).  
**Plans:** `.dev/eval/eval-plan.md` **v0.1** (T1–T6) → **v0.2 / v0.2.1 / v0.2.2** (remediation + §R10 + closure annotations).  
**Audit:** `.dev/audits/2026-04-16-eval-part-a.md` (§1–§8 frozen 2026-04-16; **§9 addendum** 2026-04-17).

## 1. Task identifier

Eval subsystem (Part A of `evaluation-and-health-metrics-roadmap.md`): manifest (T1), normalizer (T2), scorer (T3, architectural), fixtures (T4), runner (T5, architectural), naming/docs (T6). Mid-flight **T7** (abstention / validator–scorer coupling) via decision log only. Post–first-audit **`fail`** on **F-02** / **F-03**: remediation **T8** anchor matching, **T9** page-range resolution (both architectural logs), **T10** exports + CLI help + normalizer/README documentation (trivial packet). Part A eval reported **merge-ready** after re-audit.

## 2. Plan vs reality

- **Original DAG (v0.1).** T1∥T2 → T3 → T5; T4 parallel where possible; T6 soft after T5. Executed as drawn; T6 trailing T5 held. Nothing notable on unsafe parallelization.
- **Remediation wave (not on the original DAG).** Triggered by auditor blocking findings, not the initial orchestrator graph. **T8 → T9 → T10** matches natural dependencies (scorer semantics and manifest validation before runner map wiring; T10 polish last). Treat this as a **second planning cycle** glued to the same audit artifact, not a rewrite of the v0.1 mermaid DAG.
- **Contracts.** v0.1 §2 held for named types and envelopes; **T7** changed upstream behavioral semantics (`record_json`, `validation_passed`) captured in changelog + decision log — **plan amendments (v0.2)** and **§R10** later made implicit construction paths explicit (**E-1/E-2/E-3**), especially **`EvalManifest.model_validate(..., context={"golden_base_dir": ...})`** when `match_key` is set. Re-audit §9.4 accepts **E-2** as **contract fill-in**, not violation.
- **Plan narrative vs landed policy.** §R4 T8 narrative initially suggested “first-wins + warn”; **T8 decision log** landed **multiset FIFO** — both defensible; the decision log is authoritative. Stale plan text persisted until **v0.2.2** back-annotated §R4 with **Landed** bullets — reconciliation came from **re-audit / closure bump**, not from a standing orchestrator step after each subtask.
- **Log tiers.** T3, T5, T8, T9 architectural — decision logs used. T10 trivial + packet; appropriate. T1 PyYAML kill criterion + changelog without separate decision log: correct for standard tier (auditor F-10 retraction stands).

## 3. HALTs and re-plans

- **HALTs.** None fired across **T1–T6** or **T8–T10** in the artifacts reviewed.
- **T7 (no HALT).** Validator `{}` → `[{}]` vs negative-chunk scoring: discovery during T4/T5; **decision log** path was appropriate — deliverable unchanged, scope narrow. Plan staleness afterward was the process cost; **v0.2 plan amendments** addressed traceability retroactively.
- **Remediation (no re-orchestrator HALT).** Executors implemented T8/T9/T10 against expanded plan; implicit **Pydantic validation context** surfaced during T8 and became **§R10 E-2** — contract completion, not a HALT trigger in practice.
- **Silent improvisation?** Nothing suggests executors bypassed HALT-worthy ambiguity; the gap was **plan narrative lag** and **implicit construction contracts** not being in the first v0.2 §R2 text.

## 4. Adversarial pass calibration

- **v0.1 plan §5 rejected alternatives (A/B/C).** Did not resurface; manifest-first remained the right fork.
- **Load-bearing assumptions.** Largely held; chunker/fixture coupling (T4 boilerplate) was the predicted friction surface and **did** surface T7 — same “fixtures” risk family, different mechanism (validator input to scorer rules) than §5.4’s explicit T3 ↔ `record_json` list.
- **First audit (2026-04-16).** Correctly weighted **F-02** / **F-03** as major capability gaps; initially **over-weighted** process findings (**F-09**, **F-10**) — owner pushback and recalibration were right. Candidate auditor heuristic: before **`major`** on process-only issues, ask whether a **code defect** is implied.
- **Re-audit (§9).** Focused verification of remediation; **§R4 vs T8** duplicate-anchor policy classified as **documented override** until plan v0.2.2 aligned narrative. **Predicted “highest re-plan risk”** in v0.2 materials pointed at duplicate anchors in goldens; real merge blockers had been **index pairing** and **page_range** — caught by adversarial **audit**, not only by the plan’s internal risk bullets.

## 5. Methodology gaps surfaced

- **Plan amendments after decision-log-only work.** Partially closed: **eval-plan** now has **§Plan amendments**, **§v0.2**, **§R10**, and v0.2.2 **§R4 Landed** annotations. Candidate for **orchestrator-planning** after a second task confirms: when a decision log **refines** a §R narrative, **post-land back-annotate** the plan (or add a one-line **Landed** stub) so narrative does not stay stale until audit.
- **“Trace scoring rules to upstream behavior.”** Still a strong candidate adversarial heuristic (validator coercion vs negative-chunk rules); first audit §8 notes this. Watch one more cycle before skill edit.
- **Pydantic models with cross-file / context validators.** v0.2 §R2 stated **`match_key`** type-level contract; **construction contract** (file load vs `model_validate` + **context**) appeared as **§R10 E-2** only after T8. Candidate orchestrator prompt: for any new field with **context-dependent validation**, specify **which code paths** construct instances and how. Watch one more task before editing the skill.
- **“Behavioral contracts depended on”** (upstream semantics not in §2 types row). Still nothing notable beyond what T7/changelog/plan amendments now cover; optional future §2 row.
- **Auditor calibration** (documentation-only process findings capped at minor / observation). Validated by this task’s recalibration and addendum.

**Do not edit orchestrator / executor / auditor skills from this file** — skill changes stay deliberate after pattern confirmation.

## 6. Single sentence verdict

**Partially yes:** the orchestrator/executor loop delivered Part A and closed blocking audit findings with decision logs and tests, but the methodology **leaked twice in documentation mechanics** — **plan narrative vs authoritative decision log** until a closure pass, and **implicit Pydantic construction contracts** until §R10 — both now captured as **watchlist heuristics** rather than urgent skill edits.

## 7. Artifact pointers (authoritative)

- Audit: `.dev/audits/2026-04-16-eval-part-a.md` (addendum **§9** = re-audit `pass`, 2026-04-17).  
- Plan: `.dev/eval/eval-plan.md` **v0.2.2**.  
- Decision logs: `.dev/eval/T8-decision-log.md`, `T9-decision-log.md`; T10 packet `T10-packet.md`.  
- Domain/ stack learning belongs in **retrospective-learning**, not here.
