# Retrospective — Methodology: Part B (`b-plan.md`)

**Date:** 2026-04-17 · **Plan versions:** v0.1 → **v0.5** (final banner *Complete*) · **Skills:** [orchestrator-planning](file:///C:/Users/Ale/.cursor/skills/orchestrator-planning/SKILL.md), [executor-subtask-execution](file:///C:/Users/Ale/.cursor/skills/executor-subtask-execution/SKILL.md), [auditor-review](file:///C:/Users/Ale/.cursor/skills/auditor-review/SKILL.md)

**One line:** Part B delivered versioned NDJSON observability, `hermes bench`, README + CI artifacts, and a **closed loop** where an adversarial audit `**fail`** (with pytest green) drove a bounded amendment subtask (**T7**) and plan/packet revisions—exposing gaps in **typed-config completeness**, **row-scoped packet cascades**, and **post-fix narrative drift** in the orchestrator doc itself.

**Sources:** `.dev/part_b/b-plan.md` (v0.5), `.dev/audits/2026-04-17-part-b-b-plan.md` (Part I frozen + Part II rerun), `.dev/part_b/decisions/T1.md` / `T2.md` / `T4.md`, packets T1–T7, learning retro `.dev/retrospectives/learning/2026-04-17-part-b-memory-safe-scalable.md` (cross-check; methodology file is the process audit).

---

## 1. Task identifier

- **Task name:** Part B — Memory-safe & scalable (`Hermes` observability + benchmark harness).
- **Plan:** `.dev/part_b/b-plan.md`; packet set under `.dev/part_b/packets/`; audit `.dev/audits/2026-04-17-part-b-b-plan.md`.
- **What it was:** Contract-first decomposition (T1 → T1.1 → T2–T4 → T5/T6 → post-audit **T7**), architectural-tier logging schema, standard/ trivial tiers for wiring and docs/CI.

---

## 2. Plan vs reality

**DAG vs execution**

- **Matched in spirit:** T1.1 blocker after T1 KC2; T2∥T3 soft-parallel; T5∥T6 after T4; adversarial prediction that **T4** sits at the integration choke point held.
- **Differs from initial graph:** Plan declared **v0.3 Complete**, then **audit Part I `fail`** forced **Active** + amendments (**v0.4**): new **T7**, new edges **T5 → T7**, **T6 → T7**. Execution order became “finish declared scope → external audit → remediation subtask → plan/changelog alignment,” not only the forward DAG.
- **Parallelization safety:** No reported unsafe parallelization; the risky edge was **contract truth** (plan/packet text vs shipped CLI and config), not race conditions.

**Contracts**

- **Held after remediation:** `StageName` / schema **2.0**, dual-sink behavior, WARN-string `bench.dualsink.regression` as documented **override** (not silent drift).
- **Drifted then repaired:** **F1** — §2 promised `rss_sampling_*` on the observability surface; code used `**getattr` defaults** and `_parse_config` **dropped** unknown keys—**tests passed**, user TOML did not. Fixed by **T7** (typed `ObservabilityConfig`, pipeline attribute access, `tests/test_obs_config.py`, `config.toml.example`).
- **Drifted as documentation:** **F2** — plan/T6 packet cited `**--workload`**; T4 shipped `**--include-large**` and workload defaults. Fixed by **v0.4** plan + packet amendments.
- **Row-scoped cascade miss:** **F6** — T1.1 cascaded packet §2 tables but **T2 packet Outputs** still said stdlib fallback—superseded by v0.2 error envelope. Fixed by targeted packet edit, not full re-cascade.

**Log tiers**

- **T5 (`trivial`)** owned README + roadmap checkboxes but anchored **CLI flag truth** consumed by T6/CI—surface area was larger than “mechanical single-file.” Tier was not *wrong*, but **downstream coupling** was under-emphasized in the tier rubric (see §5).

---

## 3. HALTs and re-plans

**Kill criteria / escalation**

- **T1 KC2** (stage vocabulary vs pipeline): **fired correctly** → **T1.1** + schema **1.0 → 2.0**—appropriate HALT-shaped outcome.
- **T2 KC3** (dual-sink >10%): **deferred** to T4 measurement—not a false HALT; **closed-with-evidence** on reference run; gate remains runtime-armed.
- **T4 KC4** (overhead >10% smoke): **did not fire** on reference; T5/T6 unblocked as planned.

**Audit-driven cycle (not in original DAG)**

- **Part I `fail**` on **F1** (major contract) and **F2** (major intent/traceability): correct classification—**green pytest did not prove §2 config contract**.
- **Re-plan:** **T7** spec + **v0.4** plan/packet edits; **Part II `pass-with-conditions**` with non-blocking hygiene (**F3**/`decisions/T4.md` Deferred, **F4**/`decisions/T1.md` preamble, **F8** §2 row—**F8** later closed in **b-plan v0.5**).

**False HALTs / silent improvise**

- **T4** avoiding `EventName` for `bench.dualsink.regression` was a **documented override** (files-to-touch boundary), not silent improvisation—plan §2 and decision log capture it.
- No evidence in this chain that executors **skipped** HALT where the spec required it; the bigger signal is **contract completeness without a failing test** (F1), which executors reasonably “satisfied” with runtime defaults until audit.

---

## 4. Adversarial pass calibration

- **Rejected decompositions** (e.g. not merging T1+T2): **mattered**—isolated schema work made T1.1’s cascade and audit targeting tractable.
- **Load-bearing assumptions:** **#6 (config extensibility)** was the weak link in practice: narrative and pipeline behavior assumed configurable RSS fields; the **typed loader surface** lagged until T7. **#1 (mechanical T3 wrapping)** held.
- **Highest re-plan risk (T4):** **Correct**—bench + CLI + dual-run was the integration beast. **Additional trouble** came from **plan/CI/doc vs shipped flags** (F2) and **config table vs implementation** (F1)—orthogonal to “bench surprises” but same **traceability** failure mode the auditor skill is meant to catch.

---

## 5. Methodology gaps surfaced (skills — notes only; do not edit skills here)

**Orchestrator skill**

- §2 **shared contracts** need an explicit **“implementation binding”** rule: every user-visible key listed must either (a) land in the owning subtask’s typed config + parse path + test, or (b) be explicitly marked deferred with a **blocking** follow-up ID—**not** only prose + `getattr`.
- **Packet cascade** must include **grep for retired cross-cutting phrases** (error envelope, CLI verbs) outside the narrow “§2 three rows” instruction when policy flips mid-plan (**F6**).
- **CLI surface** should be **verified against code** (or a single generated manifest) before freezing **T6**-class specs—assumed flags bit **F2**.
- **Post-“complete” amendments:** T7 pattern worked; the skill should bless **audit-scoped follow-up subtasks** with explicit DAG edges so “complete” does not mean “immune to contract audit.”

**Executor skill**

- If the contract lists **config keys**, **HALT or escalate** when the dataclass/parser does not admit them—**do not paper over with `getattr**` while claiming full contract compliance.
- **Architectural decision logs:** when a later **contract refresh** contradicts an older **“Alternatives rejected”** preamble, **edit or banner** the stale block—else **F4**-style confusion persists (**auditor** also flags this).
- **Deferred** sections must be **closed or rewritten** when T5/T6 (or equivalent) ship—else **F3** debt.

**Contracts schema (plan document as artifact)**

- The plan’s §2 **row** is a **versioned artifact**: after T7, the Config row still described pre-T7 F1 analysis until **v0.5** (**F8**)—**mirror-image drift** (code fixed first, narrative stale). “Shared contracts” needs a **post-remediation doc pass** in the amendment changelog or DoD.

**Auditor skill**

- Validated: caught **F1/F2** with tests green—**config round-trip** and **plan literal vs implementation** deserve explicit phase weighting.
- `**pass-with-conditions**` correctly separated **merge-blocking** vs **orchestrator hygiene**—keep that distinction; track **documentation-only** `contract-violation** (F8) as a first-class pattern.

---

## 6. Single sentence verdict

**Partially yes:** the DAG, kill-criteria discipline, and amendment subtask (**T7**) held the methodology together, but the process **leaked** on **typed surface completeness** (plan said what code did not parse), **incomplete packet cascade** after a policy flip, and **stale orchestrator rows / decision-log preambles** until a second audit pass and **v0.5** plan edits—exactly the class of leak **contract + audit** are supposed to prevent earlier.

---

## 7. Distillation — what to fold into the three skills (future edits; not done in this file)

These are **candidates** for manual skill bumps after pattern review across retrospectives—not instructions to change skills now.

### Orchestrator-planning

1. **Config row completeness:** For each key in §2 “Types/interfaces,” require a **subtask line** that owns **dataclass + `_parse_config` (or equivalent) + round-trip test**, or an explicit “not user-configurable until Tn” exception.
2. **Cascade completeness:** When v0.x **error-envelope** or **CLI** semantics change, orchestrator runs a **retired-string grep** across **all** packets that quote outputs, kill criteria, or examples—not only §2 tables (**F6**).
3. **CLI as contract:** Freeze **flag names** from implementation (or a single source of truth) before writing **CI/docs** subtasks; treat **drift** as contract violation, not docs polish.
4. **Audit remediation subtask:** Document the **T7-shaped** pattern: scope = close auditor majors without reopening architecture; edges from doc/CI consumers; **DoD** includes updating §2 rows that referenced the old gap (**F8**).

### Executor-subtask-execution

1. **No silent `getattr` for contract keys:** If §2 names a field and **Files to touch** include config, **verify** the field exists on the typed config and is parsed; otherwise **HALT** (contract vs implementation gap)—**F1** class.
2. **Decision log hygiene:** After downstream tasks ship, **edit Deferred** and **supersede or label historical** “Alternatives rejected” that conflict with a later contract refresh (**F3**, **F4**).
3. **Packet self-review:** After T1.1-style cascades, **spot-check** one’s own packet for lines that contradict the new envelope (executor-owned sanity check).

### Auditor-review

1. **Green-tests blind spot:** Keep explicit checks for **(a)** user TOML keys ↔ typed config ↔ parse filter, **(b)** plan/packet **CLI strings** ↔ `hermes --help` or code, **(c)** §2 narrative ↔ post-fix code after remediation (**F8**).
2. **Severity taxonomy:** Treat **stale plan §2 after code fix** as **documentation drift** with clear owner (orchestrator), distinct from **runtime** contract violation—still merits `**pass-with-conditions`** when behavior is correct.
3. **Conditions:** Non-blocking items should name **artifact + owner** (plan author vs decision-log author) to reduce orphan hygiene.

---

*Skill: retrospective-methodology · Filed notes, not for sharing.*