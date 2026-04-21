# EVAL 

## Defer

### Defer / low urgency

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 5 | **Refactor `scorer.py` (defer)** | **Part B** “second use case” for shared comparison — **YAGNI** until then; size is only a **signal**. | `hermes/eval/scorer.py` (~800 LOC); `hermes/eval/normalize.py` already factored for reuse |

### Process / documentation (not “code pending” but still “open”)

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 4 | **Contract documentation template** | Retro asks whether **A-1 + §R10** pattern (**implicit persistence / construction contracts**: `record_json`, `validation_passed`, `source_pages`, Pydantic context) **generalizes** as a plan template row. | `.dev/archive/.../eval/eval-plan.md` (§Plan amendments A-1, §R10 E-1/E-2/E-3); `hermes/eval/scorer.py`, `hermes/eval/runner.py`, `hermes/extraction/pipeline.py` |

### Optional / exploratory

| # | Item | Rationale | Primary files / refs |
|---|------|-----------|----------------------|
| 2 | **Explore generic matching (optional)** | Retro asks: **introspection** vs **Hungarian** fallback “on demand” if schemas lack a single required field or use **composite** keys. | T8 decision explicitly avoided schema introspection (see `.dev/archive/.../eval/T8-decision-log.md`); any new approach touches same pairing code + manifest schema |
| 7 | **A-02 — golden object vs array (F-07)** | **Out of scope** v0.2 §R1; **revisit** if authors use object-form goldens and **round-trip** breaks. | Golden read/write paths in eval package + manifest resolution (see audit F-07) |

---