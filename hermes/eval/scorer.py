"""Eval scoring: compare extraction job output to manifest expectations and optional goldens."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, EvalManifest
from hermes.eval.normalize import MatchType, normalize_value

logger = logging.getLogger("hermes.eval.scorer")

# Pipeline stores ``record_json`` as ``json.dumps([r.model_dump(mode="json") for r in validated])``.
# See ``hermes.extraction.pipeline._process_chunk``.

FieldMatch = MatchType | Literal["error"]

ChunkReason = Literal[
    "match",
    "field_mismatch",
    "schema_reject",
    "missing_output",
    "schema_pass_no_golden",
    "correct_abstention",
    "false_positive",
    "page_range_unresolved",
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


def _field_diffs_for_records(
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> list[FieldDiff]:
    """Compare records pairwise; field keys come from expected rows (schema-agnostic)."""
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
    return diffs


def _all_fields_match(diffs: list[FieldDiff]) -> bool:
    return all(d.match in ("exact", "normalized") for d in diffs)


def _field_accuracy(diffs: list[FieldDiff]) -> float | None:
    if not diffs:
        return None
    ok = sum(1 for d in diffs if d.match in ("exact", "normalized"))
    return ok / len(diffs)


def _load_golden_line(path: Path, line_index: int) -> tuple[list[dict[str, Any]], str | None]:
    if not path.is_file():
        return [], f"golden file not found: {path}"
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_index < 0 or line_index >= len(lines):
        return [], f"golden line {line_index} missing in {path}"
    line = lines[line_index].strip()
    if not line:
        return [], f"empty golden line at index {line_index}"
    try:
        val: Any = json.loads(line)
    except json.JSONDecodeError as e:
        return [], str(e)
    if isinstance(val, list):
        rows = [x for x in val if isinstance(x, dict)]
        if len(rows) != len(val):
            return [], "golden array must contain only objects"
        return rows, None
    if isinstance(val, dict):
        return [val], None
    return [], "golden line must be a JSON object or array of objects"


def _load_golden_file_whole(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load a chunk-specific golden file (single JSON object or one-line JSONL)."""
    if not path.is_file():
        return [], f"golden file not found: {path}"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return [], "empty golden file"
    try:
        val: Any = json.loads(text)
    except json.JSONDecodeError:
        # one line jsonl
        line = text.splitlines()[0].strip()
        try:
            val = json.loads(line)
        except json.JSONDecodeError as e:
            return [], str(e)
    if isinstance(val, list):
        rows = [x for x in val if isinstance(x, dict)]
        if len(rows) != len(val):
            return [], "golden array must contain only objects"
        return rows, None
    if isinstance(val, dict):
        return [val], None
    return [], "golden must be a JSON object or array of objects"


def _resolve_golden_records(
    manifest: EvalManifest,
    expectation: ChunkExpectation,
    goldens: Mapping[int, Sequence[dict[str, Any]]] | None,
    base_dir: Path | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return expected records for this chunk, or None if no golden.

    On parse failure, returns an error string instead.
    """
    if goldens is not None and expectation.chunk_index is not None:
        if expectation.chunk_index in goldens:
            return list(goldens[expectation.chunk_index]), None

    rel: str | None = expectation.golden_path or manifest.golden_path
    if rel is None:
        return None, None

    path = Path(rel)
    if not path.is_file() and base_dir is not None:
        path = base_dir / rel
    if expectation.golden_path is not None:
        return _load_golden_file_whole(path)
    if expectation.chunk_index is not None:
        return _load_golden_line(path, expectation.chunk_index)
    return None, "golden_path requires chunk_index addressing"


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


def score_fixture(
    manifest: EvalManifest,
    job_results: list[dict[str, Any]],
    goldens: Mapping[int, Sequence[dict[str, Any]]] | None = None,
    *,
    golden_base_dir: Path | None = None,
) -> EvalResult:
    """
    Score extraction output against a manifest and optional per-chunk goldens.

    ``job_results`` rows must include ``chunk_index``. Provide ``record_json`` (pipeline format),
    or pre-parsed ``records``. Set ``validation_passed`` false to represent schema validation
    failure while still supplying raw output (not normally present for DB-backed rows).

    **Positive + no golden:** when there is no per-chunk golden and no manifest golden line,
    a validated non-empty output yields ``schema_pass_no_golden`` — pass with no field accuracy.

    **page_range** expectations are not resolved to chunk indices here; they surface as
    ``page_range_unresolved`` (runner should map to ``chunk_index`` first).

    ``golden_base_dir``: when golden paths in the manifest are relative, resolve under this
    directory (e.g. repo root).
    """
    job_index = _build_job_index(job_results)
    chunk_scores: list[ChunkScore] = []
    all_field_diffs: list[FieldDiff] = []

    for m_idx, exp in enumerate(manifest.chunks):
        if exp.page_range is not None:
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
                "fixture=%s chunk_index=None label=%s score=fail reason=page_range",
                manifest.fixture_path,
                exp.label,
            )
            continue

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

        exp_records, golden_err = _resolve_golden_records(
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

        diffs = _field_diffs_for_records(list(exp_records), recs)
        all_field_diffs.extend(diffs)
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

    summary = _summarize(manifest, chunk_scores, all_field_diffs)
    return EvalResult(chunks=chunk_scores, summary=summary)


def _summarize(
    manifest: EvalManifest,
    chunk_scores: list[ChunkScore],
    all_field_diffs: list[FieldDiff],
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
    )
