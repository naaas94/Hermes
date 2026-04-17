# T8 — Anchor-based record matching — decision log

**Subtask:** T8 (eval F-02) · **Tier:** architectural · **Date:** 2026-04-17

## Chosen approach

1. **Duplicate anchor values (within golden or actual lists):** Multiset FIFO pairing per anchor string (`collections.deque` per anchor). If an anchor appears more than once on the golden side or more than once on the actual side, emit one **`hermes.eval.scorer`** **`WARNING`** with structured fields **`fixture=`**, **`chunk_index=`**, **`match_key=`**, **`duplicate_value=`**. Pairing still consumes rows in order per anchor bucket.

2. **Actual row missing the anchor:** The row cannot join a golden pair; it is treated as an **unpaired actual** and surfaced as per-field **`FieldDiff`** entries with **`match="extra"`** (and aggregate **`records_extra`**).

3. **Golden row missing the anchor:** Rejected at **manifest load** when **`match_key`** is set: **`load_manifest`** validates all file-backed golden records via **`EvalManifest.model_validate(..., context={"golden_base_dir": ...})`**. Missing or absent anchor values in goldens raise **`ValidationError`** with a clear message (policy: fail fast at manifest, not at score time).

4. **`EvalSummary`:** Add optional **`records_matched`**, **`records_extra`**, **`records_missing`**, set only when the manifest has a non-null **`match_key`**; values are totals summed across positive chunks that compared against goldens.

## Alternatives rejected

- **Raise on duplicate anchors in goldens at manifest load:** Would reject valid fixtures where multiset pairing is well-defined; duplicates are handled at score time with first-in-order pairing plus **`WARNING`**.
- **Schema introspection for anchors:** Avoided; pairing uses only golden/actual dict keys and the manifest **`match_key`** string.

## Assumptions (if wrong, revisit)

- **`numero_serie`** remains present on every committed **`VehicleRecord`** golden row for **`tests/fixtures/eval/*.golden.jsonl`** (T7).
- Consumers of **`EvalSummary`** tolerate additive optional fields (**`model_dump`** / JSON).

## Items deferred

- **Reason-code shift when LLM returns `[]` on a positive chunk with goldens:** Under anchor mode, comparison yields per-record **`missing`** field diffs instead of only a chunk-level **`missing_output`**-style signal; orchestrator/CLI readers should treat **`reason=field_mismatch`** plus missing diffs as the detailed form of that failure (called out in plan §5).
