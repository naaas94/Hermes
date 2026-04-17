# Retrospective — Learning: Part B (memory-safe & scalable)

**Date:** 2026-04-17 (updated through **`b-plan.md` v0.5**) · **Plan:** `.dev/part_b/b-plan.md` (Part B — observability, `hermes bench`, README, CI artifact)

## 1. Task context

**What shipped (initial Part B):** A versioned NDJSON log schema (`2.0`), structured logging with dual sink and `[obs]`-gated JSON mode, RSS sampling at pipeline stage boundaries, `hermes bench` with mock-LLM path and dual-run dual-sink overhead measurement, README “Benchmarks & memory,” and a main-branch CI step that uploads bench JSON artifacts.

**Audit Part I → T7 → Part II → plan v0.5:** `.dev/audits/2026-04-17-part-b-b-plan.md` **Part I** was **`fail`** (majors **F1** silent TOML drop for `rss_sampling_*`, **F2** plan/packets vs shipped CLI). **T7** closed F1/F5 in code and README; **v0.4** amended packets/plan for F2/F6. **Part II** returned **`pass-with-conditions`** at **206** pytest passes, with **F8** (plan §2 Config row still echoing pre-T7 / “T7 outstanding” prose) and **F3/F4** (stale subsections in `decisions/T4.md` / `decisions/T1.md`) listed as follow-ups.

**v0.5 (orchestrator closure):** `b-plan.md` is now **Version 0.5 · Status: Complete**. The **§2 Types → Config fields** row was amended to describe **post-T7 reality** (all five fields typed on `ObservabilityConfig`, `_parse_config` routing, direct `pipeline.py` attribute access, **F8 closed**). The plan banner records **remaining non-blocking** items: **F3/F4** still owned by decision-log authors; **F9** (CHANGELOG narrative overlap — T2 bullet vs T7 line) and **F7** (cosmetic stage-name prose in packets) left as **observation**-tier. Runtime-armed nets from earlier milestones (dual-sink gate, stage vocabulary, CI artifact behavior) stay noted in-plan.

**Why this qualified:** Architectural-tier work, a **failed** contract audit with green tests, then a **multi-wave** fix (code → audit rerun → orchestrator doc pass) that shows how “done” stacks in layers.

---

## 2. What I now understand that I didn't before

**Green tests are not a contract audit — typed round-trip tests are the right fix for silent config drops.** Part I: **203** passes, still **`fail`**, because `rss_sampling_*` were contractually promised but not parsed. **`tests/test_obs_config.py`** after T7 gives a **durable** guard for that failure mode.

**Documentation drifts in both directions, and it can take more than one amendment wave.** F2 was **code ahead of plan**; F8 was **plan still narrating a resolved failure** (“outstanding T7” / `getattr` story) after code matched the five-field contract. **v0.5** aligned the orchestrator’s **§2** row with `hermes/config.py` — so “stale docs” includes **meta-commentary about the bug**, not only missing API docs.

**Closure is layered:** executable + tests (T7) → auditor **`pass-with-conditions`** → orchestrator **status Complete** + §2 fix (v0.5). **Decision logs** (`T1.md` preamble, `T4.md` **Deferred**) can remain **explicitly** non-blocking while the plan is already Complete — that is a deliberate **debt acceptance**, not an accident.

**CHANGELOG can hold redundant narratives without breaking the product.** **F9**-style overlap (older T2 bullet listing three `ObservabilityConfig` fields vs T7 line listing five) is **historical chronology** vs **additive correction**; fine if readers understand bullets as timeline slices, confusing if someone reads only one bullet as current truth.

**File-allow-list trade** (WARN substring for `bench.dualsink.regression` vs `EventName`) stands; **F5** README **Programmatic consumers** closes the integrator gap.

**Cascade fragility** (packets, frozen Section 2 rows) remains real; v0.4/v0.5 amendments reduced audit noise but **F7** cosmetic drift in packets is still logged as observation-only.

---

## 3. Decisions I would make again

**StageName Option B + schema `2.0` major bump** — unchanged.

**Dual-sink perf routed to T4 bench** — unchanged.

**Adversarial audit taxonomy** — unchanged; it produced an ordered backlog (majors → T7, minors → F8/plan, optional → F3/F4).

**Doing T7 as a bounded amendment** instead of disputing the audit — unchanged.

**A dedicated orchestrator revision (v0.5) to close F8** — worth it: the **plan** is the contract hub; leaving §2 wrong would have trained the next reader to distrust it.

---

## 4. Decisions I would change (or handle differently next time)

**Original `getattr` + missing dataclass fields** — fixed in code; rule persists: **every §2 config key is typed and tested or explicitly excluded.**

**Append-only decision logs without reconciling superseded bullets** — still the weakest hygiene; **F3/F4** remain the concrete reminder. Next time: either **one “close deferred” pass** in the same PR window as T7 or an explicit **“historical”** label on obsolete sections.

**Forward-looking annotations inside living plans** (“T7 outstanding”) — useful during Active status but **they rot the day T7 merges**; v0.5’s fix was to **rewrite the row for steady-state truth**, not to carry forward the play-by-play of the bug.

---

## 5. Patterns in my own thinking

**Treating audit **`fail`** as shame** — misplaced. Here it was a **routing function** to T7 and doc amendments; emotion aside, the artifact was **inventory**.

**Equating “orchestrator Complete” with “every markdown file is consistent”** — false. v0.5 **Complete** coexists with **optional** F3/F4 decision-log edits; success criteria were **scoped**.

---

## 6. Open questions

- **Unknown `[observability]` keys:** still worth a dev warning, or strict mode in CI?
- **`bench.dualsink.regression` → `EventName` in `2.1`:** still optional forever?
- **GHA main bench** (T6 KC1–KC3): operational evidence still **unknown** in audit environments; periodic human check vs ignoring.
- **Decision logs:** will F3/F4 ever get trimmed, or is “plan is Complete, logs are messy” the stable equilibrium?

---

## 7. Single paragraph synthesis

Part B showed a **full stack of closure**: failing a **contract audit** while pytest stayed green, fixing **code and tests** (T7), getting a **pass-with-conditions** rerun, then still needing a **second orchestrator pass (v0.5)** so the **plan’s own §2** stopped narrating a bug that was already fixed (**F8**). The deepest lesson is that **orchestrator documents are living contracts** — they need the same “delete the workaround banner once the workaround ships” hygiene as code, and **team completion** can reasonably land before **every auxiliary log file** is reconciled, as long as that gap is **named** rather than denied.

---

*Skill: retrospective-learning · Sources: `b-plan.md` **v0.5** (§2 Config row, changelog §0.5), `.dev/audits/2026-04-17-part-b-b-plan.md` (Part I frozen + Part II rerun), `CHANGELOG.md` (schema 2.0 block / T7), T7 touchpoints (`hermes/config.py`, `hermes/extraction/pipeline.py`, `tests/test_obs_config.py`, README “Programmatic consumers”), `.dev/part_b/decisions/T1.md`, `T2.md`, `T4.md`.*
