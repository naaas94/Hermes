"""Eval scoring: compare extraction job output to manifest expectations and optional goldens.

**A-03 / F-14 — “extra” fields and product limits**

- **No per-chunk golden (positive chunk):** when neither inline goldens nor ``golden_path``
  supply rows, a validated non-empty extraction yields ``schema_pass_no_golden`` — there is
  **no** field-level diff and **no** field accuracy; the harness cannot label model-only keys
  as hallucinations (see ``score_fixture`` / ``REASON_SCHEMA_PASS_NO_GOLDEN``).
- **Paired-row field diffs** (``_field_diffs_for_records``): for each aligned pair of golden
  vs actual dicts we walk the **union** of keys and compare values via ``normalize_value``.
  Keys present only on the actual side (expected absent / null) are scored with normal
  ``MatchType`` values such as ``"mismatch"`` — **not** with ``FieldMatch`` ``"extra"``.
- **``FieldMatch`` ``"extra"``** is reserved for **anchor** mode (``match_key`` set): an
  **entire actual record** that does not pair to any golden row after anchor matching. It
  does **not** mean “an extra field inside a matched record.”
- **Scorer changes** that add explicit hallucination flags, manifest switches, or different
  semantics need **product approval** and a **new plan version**; do not treat this
  docstring as a commitment to ship detection features.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hermes.eval.manifest import (
    ChunkLabel,
    EvalManifest,
    PageRange,
    resolve_golden_records,
)
from hermes.eval.normalize import MatchType, normalize_value

logger = logging.getLogger("hermes.eval.scorer")

# Pipeline stores ``record_json`` as ``json.dumps([r.model_dump(mode="json") for r in validated])``.
# See ``hermes.extraction.pipeline._process_chunk``.

FieldMatch = MatchType | Literal["error", "extra"]

ChunkReason = Literal[
    "match",
    "field_mismatch",
    "schema_reject",
    "missing_output",
    "schema_pass_no_golden",
    "correct_abstention",
    "false_positive",
    "page_range_unresolved",
    "page_range_ambiguous",
    "golden_parse_error",
    "record_json_parse_error",
    "missing_chunk_in_results",
]

REASON_MATCH: ChunkReason = "match"
REASON_FIELD_MISMATCH: ChunkReason = "field_mismatch"
REASON_SCHEMA_REJECT: ChunkReason = "schema_reject"
REASON_MISSING_OUTPUT: ChunkReason = "missing_output"
REASON_SCHEMA_PASS_NO_GOLDEN: ChunkReason = "schema_pass_no_golden"
REASON_CORRECT_ABSTENTION: ChunkReason = "correct_abstention"
REASON_FALSE_POSITIVE: ChunkReason = "false_positive"
REASON_PAGE_RANGE_UNRESOLVED: ChunkReason = "page_range_unresolved"
REASON_PAGE_RANGE_AMBIGUOUS: ChunkReason = "page_range_ambiguous"
REASON_GOLDEN_PARSE_ERROR: ChunkReason = "golden_parse_error"
REASON_RECORD_JSON_PARSE_ERROR: ChunkReason = "record_json_parse_error"
REASON_MISSING_CHUNK_IN_RESULTS: ChunkReason = "missing_chunk_in_results"


class FieldDiff(BaseModel):
    """Per-field comparison for a chunk (golden vs actual)."""

    field: str
    expected: Any = None
    actual: Any = None
    match: FieldMatch
    error_detail: str | None = None


class ChunkScore(BaseModel):
    """Score for one manifest chunk expectation."""

    manifest_chunk_index: int
    resolved_chunk_index: int | None
    label: ChunkLabel
    passed: bool
    reason: ChunkReason
    field_diffs: list[FieldDiff] = Field(default_factory=list)


class EvalSummary(BaseModel):
    """Aggregate metrics for a fixture eval run."""

    fixture_path: str
    schema_ref: str
    total_expectations: int
    passed_expectations: int
    positive_total: int
    positive_passed: int
    negative_total: int
    negative_passed: int
    negative_false_positive_rate: float | None
    field_level_accuracy: float | None
    modality: str | None = None
    notes: str | None = None
    records_matched: int | None = None
    records_extra: int | None = None
    records_missing: int | None = None


class EvalResult(BaseModel):
    """Full scoring outcome for one fixture (one manifest + job outputs)."""

    error: str | None = None
    chunks: list[ChunkScore] = Field(default_factory=list)
    summary: EvalSummary | None = None


def _parse_record_json(raw: str) -> tuple[list[dict[str, Any]], str | None]:
    """Parse ``record_json`` the same way as export/DB consumers."""
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], str(e)
    if isinstance(parsed, list):
        out: list[dict[str, Any]] = []
        for item in parsed:
            if isinstance(item, dict):
                out.append(item)
            else:
                return [], "record_json array elements must be objects"
        return out, None
    if isinstance(parsed, dict):
        return [parsed], None
    return [], "record_json must be a JSON array or object"


def _records_empty(records: list[dict[str, Any]]) -> bool:
    return len(records) == 0


def _anchor_val(row: dict[str, Any], mk: str) -> str | None:
    if mk not in row:
        return None
    v = row[mk]
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return str(v)


def _warn_duplicate_anchors(
    golden: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    mk: str,
    fixture_path: str,
    chunk_index: int,
) -> None:
    for label, rows in (("golden", golden), ("actual", actual)):
        counts: Counter[str] = Counter()
        for r in rows:
            av = _anchor_val(r, mk)
            if av is not None:
                counts[av] += 1
        for val, n in counts.items():
            if n > 1:
                logger.warning(
                    (
                        "duplicate anchor values in %s rows: fixture=%s chunk_index=%s "
                        "match_key=%s duplicate_value=%s"
                    ),
                    label,
                    fixture_path,
                    chunk_index,
                    mk,
                    val,
                )


def _pair_records_by_anchor(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    mk: str,
) -> tuple[
    list[tuple[int, int, dict[str, Any], dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
    list[tuple[int, dict[str, Any]]],
    set[int],
]:
    """Return pairings, orphan golden/actual rows, and golden row indices missing the anchor."""
    g_by: dict[str, deque[tuple[int, dict[str, Any]]]] = defaultdict(deque)
    g_missing_anchor: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(expected):
        av = _anchor_val(row, mk)
        if av is None:
            g_missing_anchor.append((i, row))
        else:
            g_by[av].append((i, row))

    a_by: dict[str, deque[tuple[int, dict[str, Any]]]] = defaultdict(deque)
    a_missing_anchor: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(actual):
        av = _anchor_val(row, mk)
        if av is None:
            a_missing_anchor.append((i, row))
        else:
            a_by[av].append((i, row))

    pairs: list[tuple[int, int, dict[str, Any], dict[str, Any]]] = []
    orphan_g: list[tuple[int, dict[str, Any]]] = list(g_missing_anchor)
    orphan_a: list[tuple[int, dict[str, Any]]] = []

    for k in set(g_by.keys()) | set(a_by.keys()):
        gq = g_by.get(k, deque())
        aq = a_by.get(k, deque())
        while gq and aq:
            gi, grow = gq.popleft()
            ai, arow = aq.popleft()
            pairs.append((gi, ai, grow, arow))
        orphan_g.extend(list(gq))
        orphan_a.extend(list(aq))

    orphan_a.extend(a_missing_anchor)
    g_missing_idx = {i for i, _ in g_missing_anchor}
    return pairs, orphan_g, orphan_a, g_missing_idx


def _field_diffs_for_records(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
    match_key: str | None = None,
    *,
    fixture_path: str = "",
    chunk_index: int | None = None,
) -> tuple[list[FieldDiff], int | None, int | None, int | None]:
    """Compare records pairwise (index order) or by anchor when ``match_key`` is set."""
    if not match_key:
        if len(expected) > 1 or len(actual) > 1:
            ci = chunk_index if chunk_index is not None else -1
            logger.warning(
                (
                    "index-only record pairing for multiset rows (fixture=%s chunk_index=%s); "
                    "set match_key on the manifest for anchor pairing, or use single-record goldens"
                ),
                fixture_path or "?",
                ci,
            )
        diffs: list[FieldDiff] = []
        n = max(len(expected), len(actual))
        for i in range(n):
            exp_row = expected[i] if i < len(expected) else {}
            act_row = actual[i] if i < len(actual) else {}
            keys = set(exp_row.keys()) | set(act_row.keys()) if exp_row or act_row else set()
            if not exp_row and not act_row:
                continue
            for key in sorted(keys):
                e_val = exp_row.get(key)
                a_val = act_row.get(key)
                mt = normalize_value(e_val, a_val)
                fname = f"[{i}].{key}" if n > 1 else key
                diffs.append(
                    FieldDiff(field=fname, expected=e_val, actual=a_val, match=mt),
                )
        return diffs, None, None, None

    mk = match_key
    ci = chunk_index if chunk_index is not None else -1
    _warn_duplicate_anchors(expected, actual, mk, fixture_path, ci)
    pairs, orphan_g, orphan_a, g_missing_idx = _pair_records_by_anchor(expected, actual, mk)

    out: list[FieldDiff] = []
    n = max(len(expected), len(actual))

    for gi, ai, grow, arow in pairs:
        keys = set(grow.keys()) | set(arow.keys()) if grow or arow else set()
        for key in sorted(keys):
            e_val = grow.get(key)
            a_val = arow.get(key)
            mt = normalize_value(e_val, a_val)
            fname = f"[{gi}].{key}" if n > 1 else key
            out.append(FieldDiff(field=fname, expected=e_val, actual=a_val, match=mt))

    for gi, grow in orphan_g:
        if gi in g_missing_idx:
            out.append(
                FieldDiff(
                    field=f"[{gi}].{mk}",
                    expected=grow.get(mk),
                    actual=None,
                    match="error",
                    error_detail=f"golden row missing non-empty match_key field {mk!r}",
                ),
            )
            continue
        sorted_keys = sorted(grow.keys())
        for key in sorted_keys:
            e_val = grow.get(key)
            fname = f"[{gi}].{key}" if n > 1 else key
            out.append(
                FieldDiff(field=fname, expected=e_val, actual=None, match="missing"),
            )

    for ai, arow in orphan_a:
        sorted_keys = sorted(arow.keys())
        for key in sorted_keys:
            a_val = arow.get(key)
            fname = f"[{ai}].{key}" if n > 1 else key
            out.append(
                FieldDiff(field=fname, expected=None, actual=a_val, match="extra"),
            )

    rec_matched = len(pairs)
    rec_missing = len(orphan_g)
    rec_extra = len(orphan_a)
    return out, rec_matched, rec_missing, rec_extra


def _all_fields_match(diffs: list[FieldDiff]) -> bool:
    return all(d.match in ("exact", "normalized") for d in diffs)


def _field_accuracy(diffs: list[FieldDiff]) -> float | None:
    if not diffs:
        return None
    ok = sum(1 for d in diffs if d.match in ("exact", "normalized"))
    return ok / len(diffs)


def _build_job_index(
    job_results: list[dict[str, Any]],
) -> dict[int, tuple[list[dict[str, Any]], bool, str | None]]:
    """
    Index job rows by ``chunk_index``.

    Each row may include:
    - ``chunk_index`` (required)
    - ``record_json`` (str) — same format as ``extraction_results.record_json``
    - ``records`` (list[dict]) — pre-parsed alternative to ``record_json``
    - ``validation_passed`` (bool, default True when parsing succeeds)
    """
    out: dict[int, tuple[list[dict[str, Any]], bool, str | None]] = {}
    for row in job_results:
        if "chunk_index" not in row:
            logger.warning("job result row missing chunk_index, skipping: %s", row)
            continue
        ci = int(row["chunk_index"])
        parse_err: str | None = None
        recs: list[dict[str, Any]] = []
        if "records" in row and row["records"] is not None:
            raw_recs = row["records"]
            if isinstance(raw_recs, list):
                recs = [x for x in raw_recs if isinstance(x, dict)]
            else:
                parse_err = "records must be a list of dicts"
        elif "record_json" in row and row["record_json"] is not None:
            recs, parse_err = _parse_record_json(str(row["record_json"]))
        else:
            recs, parse_err = [], None

        val_ok = bool(row.get("validation_passed", True))
        if parse_err is not None:
            val_ok = False
            recs = []

        out[ci] = (recs, val_ok, parse_err)
    return out


def parse_source_pages_to_pageset(source_pages: str | None) -> frozenset[int]:
    """Parse DB/pipeline ``source_pages`` (comma-separated 1-based page ints) to a set."""
    if source_pages is None:
        return frozenset()
    s = str(source_pages).strip()
    if not s:
        return frozenset()
    out: list[int] = []
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except ValueError:
            continue
    return frozenset(out)


def _chunk_pagesets_from_job_results(
    job_results: list[dict[str, Any]],
) -> dict[int, frozenset[int]]:
    """Per ``chunk_index``, pages from that row's ``source_pages`` string (if any)."""
    pagesets: dict[int, frozenset[int]] = {}
    for row in job_results:
        if "chunk_index" not in row:
            continue
        raw = row.get("source_pages")
        ps = parse_source_pages_to_pageset(raw if raw is None else str(raw))
        if not ps:
            continue
        pagesets[int(row["chunk_index"])] = ps
    return pagesets


def _resolve_page_range_to_chunk_index(
    page_range: PageRange,
    pagesets: Mapping[int, frozenset[int]],
) -> tuple[int | None, ChunkReason | None]:
    """
    Contained-in policy: prefer chunk(s) whose pages are a subset of the requested range;
    if none, fall back to the unique chunk whose pages fully contain the requested range.
    """
    R = frozenset(range(page_range.start, page_range.end + 1))
    if not pagesets:
        return None, REASON_PAGE_RANGE_UNRESOLVED

    primary = [ci for ci, S in sorted(pagesets.items()) if S <= R]
    if len(primary) == 1:
        return primary[0], None
    if len(primary) > 1:
        return None, REASON_PAGE_RANGE_AMBIGUOUS

    secondary = [ci for ci, S in sorted(pagesets.items()) if R <= S]
    if len(secondary) == 1:
        return secondary[0], None
    if len(secondary) > 1:
        return None, REASON_PAGE_RANGE_AMBIGUOUS
    return None, REASON_PAGE_RANGE_UNRESOLVED


def score_fixture(
    manifest: EvalManifest,
    job_results: list[dict[str, Any]],
    goldens: Mapping[int, Sequence[dict[str, Any]]] | None = None,
    *,
    golden_base_dir: Path | None = None,
    chunk_page_map: Mapping[int, tuple[int, int]] | None = None,
) -> EvalResult:
    """
    Score extraction output against a manifest and optional per-chunk goldens.

    ``job_results`` rows must include ``chunk_index``. Provide ``record_json`` (pipeline format),
    or pre-parsed ``records``. Set ``validation_passed`` false to represent schema validation
    failure while still supplying raw output (not normally present for DB-backed rows).

    **Positive + no golden:** when there is no per-chunk golden and no manifest golden line,
    a validated non-empty output yields ``schema_pass_no_golden`` — pass with no field accuracy.

    **page_range** expectations: when ``chunk_page_map`` is ``None`` (default), they surface as
    ``page_range_unresolved``. When the runner passes ``chunk_page_map`` (and job rows include
    ``source_pages``), ranges resolve via ``_resolve_page_range_to_chunk_index`` before scoring.

    ``golden_base_dir``: when golden paths in the manifest are relative, resolve under this
    directory (e.g. repo root).

    ``chunk_page_map``: optional per-``chunk_index`` inclusive ``(min_page, max_page)`` from
    ``source_pages``; when provided, enables page-range resolution (see runner
    ``build_chunk_page_map``). Callers omitting it keep v0.1 behavior.
    """
    job_index = _build_job_index(job_results)
    chunk_scores: list[ChunkScore] = []
    all_field_diffs: list[FieldDiff] = []
    rec_matched_total = 0
    rec_missing_total = 0
    rec_extra_total = 0
    anchor_mode = manifest.match_key is not None

    for m_idx, exp in enumerate(manifest.chunks):
        ci: int
        if exp.page_range is not None:
            if chunk_page_map is None:
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=None,
                        label=exp.label,
                        passed=False,
                        reason=REASON_PAGE_RANGE_UNRESOLVED,
                    )
                )
                logger.info(
                    "fixture=%s page_range=%s-%s reason=%s",
                    manifest.fixture_path,
                    exp.page_range.start,
                    exp.page_range.end,
                    REASON_PAGE_RANGE_UNRESOLVED,
                )
                continue
            pagesets = _chunk_pagesets_from_job_results(job_results)
            resolved_ci, pr_err = _resolve_page_range_to_chunk_index(exp.page_range, pagesets)
            if resolved_ci is None:
                fail_reason = pr_err if pr_err is not None else REASON_PAGE_RANGE_UNRESOLVED
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=None,
                        label=exp.label,
                        passed=False,
                        reason=fail_reason,
                    )
                )
                logger.info(
                    "fixture=%s page_range=%s-%s reason=%s",
                    manifest.fixture_path,
                    exp.page_range.start,
                    exp.page_range.end,
                    fail_reason,
                )
                continue
            ci = resolved_ci
            logger.info(
                "fixture=%s page_range=%s-%s resolved_chunk_index=%s",
                manifest.fixture_path,
                exp.page_range.start,
                exp.page_range.end,
                ci,
            )
        else:
            assert exp.chunk_index is not None
            ci = exp.chunk_index

        if exp.label == ChunkLabel.NEGATIVE:
            if ci not in job_index:
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=ci,
                        label=exp.label,
                        passed=True,
                        reason=REASON_CORRECT_ABSTENTION,
                    )
                )
                logger.info(
                    "fixture=%s chunk_index=%s label=%s score=pass reason=abstention",
                    manifest.fixture_path,
                    ci,
                    exp.label,
                )
                continue

            recs, val_ok, parse_err = job_index[ci]
            if parse_err is not None:
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=ci,
                        label=exp.label,
                        passed=False,
                        reason=REASON_RECORD_JSON_PARSE_ERROR,
                    )
                )
                logger.info(
                    "fixture=%s chunk_index=%s label=%s score=fail reason=parse_error",
                    manifest.fixture_path,
                    ci,
                    exp.label,
                )
                continue

            if not val_ok:
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=ci,
                        label=exp.label,
                        passed=True,
                        reason=REASON_CORRECT_ABSTENTION,
                    )
                )
                continue

            empty = _records_empty(recs)
            if empty:
                passed = bool(exp.allow_empty)
                chunk_scores.append(
                    ChunkScore(
                        manifest_chunk_index=m_idx,
                        resolved_chunk_index=ci,
                        label=exp.label,
                        passed=passed,
                        reason=REASON_CORRECT_ABSTENTION if passed else REASON_FALSE_POSITIVE,
                    )
                )
                logger.info(
                    "fixture=%s chunk_index=%s label=%s score=%s",
                    manifest.fixture_path,
                    ci,
                    exp.label,
                    "pass" if passed else "fail",
                )
                continue

            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_FALSE_POSITIVE,
                )
            )
            logger.info(
                "fixture=%s chunk_index=%s label=%s score=fail reason=false_positive",
                manifest.fixture_path,
                ci,
                exp.label,
            )
            continue

        # Positive
        if ci not in job_index:
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_MISSING_CHUNK_IN_RESULTS,
                )
            )
            logger.info(
                "fixture=%s chunk_index=%s label=%s score=fail reason=missing_chunk",
                manifest.fixture_path,
                ci,
                exp.label,
            )
            continue

        recs, val_ok, parse_err = job_index[ci]

        if parse_err is not None:
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_RECORD_JSON_PARSE_ERROR,
                    field_diffs=[
                        FieldDiff(
                            field="*",
                            expected=None,
                            actual=None,
                            match="error",
                            error_detail=parse_err,
                        )
                    ],
                )
            )
            continue

        if not val_ok:
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_SCHEMA_REJECT,
                )
            )
            logger.info(
                "fixture=%s chunk_index=%s label=%s score=fail reason=schema_reject",
                manifest.fixture_path,
                ci,
                exp.label,
            )
            continue

        if _records_empty(recs):
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_MISSING_OUTPUT,
                )
            )
            continue

        exp_records, golden_err = resolve_golden_records(
            manifest,
            exp,
            goldens,
            golden_base_dir,
        )
        if golden_err is not None:
            fd = FieldDiff(
                field="*",
                expected=None,
                actual=None,
                match="error",
                error_detail=golden_err,
            )
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=False,
                    reason=REASON_GOLDEN_PARSE_ERROR,
                    field_diffs=[fd],
                )
            )
            continue

        if exp_records is None:
            chunk_scores.append(
                ChunkScore(
                    manifest_chunk_index=m_idx,
                    resolved_chunk_index=ci,
                    label=exp.label,
                    passed=True,
                    reason=REASON_SCHEMA_PASS_NO_GOLDEN,
                )
            )
            logger.info(
                "fixture=%s chunk_index=%s label=%s score=pass reason=schema_pass_no_golden",
                manifest.fixture_path,
                ci,
                exp.label,
            )
            continue

        diffs, r_m, r_miss, r_ext = _field_diffs_for_records(
            list(exp_records),
            recs,
            manifest.match_key,
            fixture_path=manifest.fixture_path,
            chunk_index=ci,
        )
        all_field_diffs.extend(diffs)
        if anchor_mode and r_m is not None and r_miss is not None and r_ext is not None:
            rec_matched_total += r_m
            rec_missing_total += r_miss
            rec_extra_total += r_ext
        ok = _all_fields_match(diffs)
        chunk_scores.append(
            ChunkScore(
                manifest_chunk_index=m_idx,
                resolved_chunk_index=ci,
                label=exp.label,
                passed=ok,
                reason=REASON_MATCH if ok else REASON_FIELD_MISMATCH,
                field_diffs=diffs,
            )
        )
        logger.info(
            "fixture=%s chunk_index=%s label=%s score=%s",
            manifest.fixture_path,
            ci,
            exp.label,
            "pass" if ok else "fail",
        )

    summary = _summarize(
        manifest,
        chunk_scores,
        all_field_diffs,
        rec_matched_total,
        rec_missing_total,
        rec_extra_total,
    )
    return EvalResult(chunks=chunk_scores, summary=summary)


def _summarize(
    manifest: EvalManifest,
    chunk_scores: list[ChunkScore],
    all_field_diffs: list[FieldDiff],
    rec_matched_total: int = 0,
    rec_missing_total: int = 0,
    rec_extra_total: int = 0,
) -> EvalSummary:
    pos_total = sum(1 for c in chunk_scores if c.label == ChunkLabel.POSITIVE)
    pos_pass = sum(1 for c in chunk_scores if c.label == ChunkLabel.POSITIVE and c.passed)
    neg_total = sum(1 for c in chunk_scores if c.label == ChunkLabel.NEGATIVE)
    neg_pass = sum(1 for c in chunk_scores if c.label == ChunkLabel.NEGATIVE and c.passed)
    fp_count = sum(
        1
        for c in chunk_scores
        if c.label == ChunkLabel.NEGATIVE and c.reason == REASON_FALSE_POSITIVE
    )
    neg_fpr: float | None = (fp_count / neg_total) if neg_total else None

    golden_diffs = [d for d in all_field_diffs if d.match != "error"]
    field_acc: float | None
    if golden_diffs:
        field_acc = _field_accuracy(golden_diffs)
    else:
        field_acc = None

    passed_n = sum(1 for c in chunk_scores if c.passed)

    anchor_mode = manifest.match_key is not None
    rec_matched: int | None = rec_matched_total if anchor_mode else None
    rec_missing: int | None = rec_missing_total if anchor_mode else None
    rec_extra: int | None = rec_extra_total if anchor_mode else None

    return EvalSummary(
        fixture_path=manifest.fixture_path,
        schema_ref=manifest.schema_ref,
        total_expectations=len(chunk_scores),
        passed_expectations=passed_n,
        positive_total=pos_total,
        positive_passed=pos_pass,
        negative_total=neg_total,
        negative_passed=neg_pass,
        negative_false_positive_rate=neg_fpr,
        field_level_accuracy=field_acc,
        modality=manifest.modality,
        notes=manifest.notes,
        records_matched=rec_matched,
        records_missing=rec_missing,
        records_extra=rec_extra,
    )
