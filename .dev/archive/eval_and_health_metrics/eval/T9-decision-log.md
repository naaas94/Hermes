# T9 — Page-range resolution — decision log

## Chosen approach

- **`score_fixture`** accepts optional **`chunk_page_map: Mapping[int, tuple[int, int]] | None`** (default **`None`**). When **`None`**, **`addressing: page_range`** expectations behave as in v0.1 (**`page_range_unresolved`**). When the runner passes a map (from **`build_chunk_page_map(job_results)`**), resolution runs before field scoring; the manifest is never mutated.
- **Resolution policy (contained-in):** let **R** be the inclusive requested page set. Prefer chunk(s) whose persisted page set **S** satisfies **S ⊆ R**; if exactly one, use it. If more than one, **`page_range_ambiguous`**. If none, fall back to chunk(s) with **R ⊆ S**; if exactly one, use it; if more than one, **`page_range_ambiguous`**; if none, **`page_range_unresolved`**. Page sets **S** are parsed from each job row’s **`source_pages`** comma-separated string (same as **`extraction_results`**).
- **`build_chunk_page_map`** in **`hermes/eval/runner.py`** computes **`(min(S), max(S))`** per **`chunk_index`** for rows with non-empty **`source_pages`**; rows with missing/empty **`source_pages`** are omitted (expectations then tend toward **`page_range_unresolved`**).
- **`job_results_from_db_rows`** includes **`source_pages`** when present on each row. **`load_job_results_from_jsonl`** already returns full objects; **`source_pages`** is left on each line dict when present.

## Alternatives rejected

- **Exact-coverage only (S = R):** stricter and brittle for real PDFs where a chunk may span more pages than the manifest window; contained-in matches the audit remediation and tolerates “chunk spans 1–2, expect pages 1–1” via the fallback.
- **Runner rewrites `chunk_index` on the manifest:** would break immutability and complicate **`--update-goldens`** / retries; **`chunk_page_map`** + scorer-side resolution keeps one scoring path.

## Assumptions (load-bearing)

- **`extraction_results.source_pages`** remains comma-separated 1-based integers (**`hermes/db.py`** / pipeline write path). Non-contiguous page lists are represented by **min/max** in **`chunk_page_map`**; resolution uses full parsed sets from **`source_pages`** strings in **`job_results`**, not only those bounds.
- Chunking for **`tests/fixtures/eval/sample_text.pdf`** stays stable enough that **`page_range: [1, 1]`** resolves to the same **`chunk_index`** under the contained-in policy; retuning the chunker may require adjusting the manifest or golden.

## Supersedes (contract chain)

- Supersedes **`.dev/eval/T3-decision-log.md`** § “`page_range` expectations … yield `page_range_unresolved` so the runner can pre-resolve to `chunk_index` later”: **T9** is that “later,” implemented as **`chunk_page_map`** + scorer resolution **without** manifest mutation, not as a separate runner-only rewrite step.

## Items deferred

- **Non-contiguous pages encoded only as (min, max) in `chunk_page_map`:** callers relying on the tuple alone for other features could misread gaps; scoring uses parsed sets from **`job_results`**.
- **Stricter CI pinning** of chunk indices for page-range fixtures if chunker drift becomes noisy.
