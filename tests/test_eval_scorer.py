"""Tests for eval scoring (manifest + job results + goldens)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, EvalManifest, PageRange
from hermes.eval.scorer import (
    REASON_CORRECT_ABSTENTION,
    REASON_FALSE_POSITIVE,
    REASON_FIELD_MISMATCH,
    REASON_GOLDEN_PARSE_ERROR,
    REASON_MATCH,
    REASON_MISSING_CHUNK_IN_RESULTS,
    REASON_MISSING_OUTPUT,
    REASON_PAGE_RANGE_AMBIGUOUS,
    REASON_PAGE_RANGE_UNRESOLVED,
    REASON_RECORD_JSON_PARSE_ERROR,
    REASON_SCHEMA_PASS_NO_GOLDEN,
    REASON_SCHEMA_REJECT,
    _field_diffs_for_records,
    score_fixture,
)


def _manifest_pos_neg() -> EvalManifest:
    return EvalManifest(
        fixture_path="tests/fixtures/eval/sample.xlsx",
        schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
        addressing="chunk_index",
        chunks=[
            ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE),
            ChunkExpectation(chunk_index=1, label=ChunkLabel.NEGATIVE, allow_empty=True),
        ],
    )


def test_eval_scorer_positive_matching_golden() -> None:
    manifest = _manifest_pos_neg()
    job = [
        {"chunk_index": 0, "record_json": json.dumps([{"make": "Ford", "year": 2020}])},
        {"chunk_index": 1, "record_json": "[]"},
    ]
    goldens = {0: [{"make": "Ford", "year": 2020}]}
    r = score_fixture(manifest, job, goldens)
    assert r.error is None
    assert r.summary is not None
    assert r.summary.field_level_accuracy == 1.0
    c0 = r.chunks[0]
    assert c0.passed is True
    assert c0.reason == REASON_MATCH
    assert c0.field_diffs


def test_eval_scorer_positive_mismatched_golden() -> None:
    manifest = _manifest_pos_neg()
    job = [{"chunk_index": 0, "record_json": json.dumps([{"make": "GM", "year": 2020}])}]
    goldens = {0: [{"make": "Ford", "year": 2020}]}
    r = score_fixture(manifest, job, goldens)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_FIELD_MISMATCH
    assert r.summary is not None
    assert r.summary.field_level_accuracy is not None
    assert r.summary.field_level_accuracy < 1.0


def test_eval_scorer_negative_no_output_passes() -> None:
    manifest = _manifest_pos_neg()
    job = [{"chunk_index": 0, "record_json": json.dumps([{"make": "Ford"}])}]
    r = score_fixture(manifest, job, None)
    assert r.chunks[1].passed is True
    assert r.chunks[1].reason == REASON_CORRECT_ABSTENTION


def test_eval_scorer_negative_hallucinated_output_fails() -> None:
    manifest = _manifest_pos_neg()
    job = [
        {"chunk_index": 0, "record_json": json.dumps([{"make": "Ford"}])},
        {"chunk_index": 1, "record_json": json.dumps([{"make": "Ghost"}])},
    ]
    r = score_fixture(manifest, job, None)
    neg = r.chunks[1]
    assert neg.passed is False
    assert neg.reason == REASON_FALSE_POSITIVE


def test_eval_scorer_missing_chunk_in_results() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=2, label=ChunkLabel.POSITIVE)],
    )
    r = score_fixture(manifest, [], None)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_MISSING_CHUNK_IN_RESULTS


def test_eval_scorer_schema_reject_positive() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [
        {
            "chunk_index": 0,
            "record_json": json.dumps([{"x": 1}]),
            "validation_passed": False,
        }
    ]
    goldens = {0: [{"x": 1}]}
    r = score_fixture(manifest, job, goldens)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_SCHEMA_REJECT


def test_eval_scorer_positive_no_golden_schema_pass() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": json.dumps([{"a": 1}])}]
    r = score_fixture(manifest, job, None)
    assert r.chunks[0].passed is True
    assert r.chunks[0].reason == REASON_SCHEMA_PASS_NO_GOLDEN
    assert r.summary is not None
    assert r.summary.field_level_accuracy is None


def test_eval_scorer_positive_missing_output() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": "[]"}]
    r = score_fixture(manifest, job, None)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_MISSING_OUTPUT


def test_eval_scorer_record_json_malformed() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": "not-json"}]
    r = score_fixture(manifest, job, None)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_RECORD_JSON_PARSE_ERROR


def test_eval_scorer_page_range_unresolved() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="page_range",
        chunks=[
            ChunkExpectation(
                page_range={"start": 1, "end": 1},
                label=ChunkLabel.POSITIVE,
            )
        ],
    )
    r = score_fixture(manifest, [], None)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_PAGE_RANGE_UNRESOLVED


def test_eval_scorer_page_range_resolves_with_chunk_page_map() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="page_range",
        chunks=[
            ChunkExpectation(
                page_range=PageRange(start=1, end=1),
                label=ChunkLabel.POSITIVE,
            )
        ],
    )
    job = [
        {
            "chunk_index": 0,
            "record_json": json.dumps([{"k": 1}]),
            "source_pages": "1",
        },
    ]
    r = score_fixture(manifest, job, None, chunk_page_map={0: (1, 1)})
    c0 = r.chunks[0]
    assert c0.passed is True
    assert c0.resolved_chunk_index == 0
    assert c0.reason == REASON_SCHEMA_PASS_NO_GOLDEN


def test_eval_scorer_page_range_ambiguous() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="page_range",
        chunks=[
            ChunkExpectation(
                page_range=PageRange(start=1, end=2),
                label=ChunkLabel.POSITIVE,
            )
        ],
    )
    job = [
        {"chunk_index": 0, "record_json": "[]", "source_pages": "1"},
        {"chunk_index": 1, "record_json": "[]", "source_pages": "2"},
    ]
    r = score_fixture(manifest, job, None, chunk_page_map={0: (1, 1), 1: (2, 2)})
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_PAGE_RANGE_AMBIGUOUS


def test_eval_scorer_page_range_unresolvable_no_candidate() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="page_range",
        chunks=[
            ChunkExpectation(
                page_range=PageRange(start=9, end=9),
                label=ChunkLabel.POSITIVE,
            )
        ],
    )
    job = [{"chunk_index": 0, "record_json": json.dumps([{"k": 1}]), "source_pages": "1"}]
    r = score_fixture(manifest, job, None, chunk_page_map={0: (1, 1)})
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_PAGE_RANGE_UNRESOLVED


def test_eval_scorer_golden_file_line(tmp_path: Path) -> None:
    g = tmp_path / "job.golden.jsonl"
    g.write_text(json.dumps({"sku": "A", "qty": 1}) + "\n", encoding="utf-8")
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        golden_path=str(g),
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": json.dumps([{"sku": "A", "qty": 1}])}]
    r = score_fixture(manifest, job, None, golden_base_dir=tmp_path)
    assert r.chunks[0].passed is True
    assert r.chunks[0].reason == REASON_MATCH


def test_eval_scorer_golden_parse_error_field_diff(tmp_path: Path) -> None:
    g = tmp_path / "bad.golden.jsonl"
    g.write_text("not json\n", encoding="utf-8")
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        golden_path=str(g.name),
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": json.dumps([{"a": 1}])}]
    r = score_fixture(manifest, job, None, golden_base_dir=tmp_path)
    assert r.chunks[0].passed is False
    assert r.chunks[0].reason == REASON_GOLDEN_PARSE_ERROR
    assert r.chunks[0].field_diffs[0].match == "error"


def _manifest_anchor(**kwargs: object) -> EvalManifest:
    base = {
        "fixture_path": "x.pdf",
        "schema_ref": "ref",
        "addressing": "chunk_index",
        "match_key": "numero_serie",
        "chunks": [{"chunk_index": 0, "label": "positive"}],
    }
    base.update(kwargs)
    return EvalManifest.model_validate(
        base,
        context={"golden_base_dir": Path(__file__).resolve().parents[1]},
    )


def test_eval_scorer_warns_index_pairing_without_match_key_multi_record(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    gold = [{"k": "a", "n": 1}, {"k": "b", "n": 2}]
    job = [{"chunk_index": 0, "record_json": json.dumps(gold)}]
    caplog.set_level(logging.WARNING, logger="hermes.eval.scorer")
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is True
    assert "index-only record pairing for multiset rows" in caplog.text


def test_eval_scorer_anchor_mode_reorder_invariant() -> None:
    manifest = _manifest_anchor()
    gold = [
        {"numero_serie": "A", "make": "Ford"},
        {"numero_serie": "B", "make": "GM"},
    ]
    shuffled = [gold[1], gold[0]]
    job = [{"chunk_index": 0, "record_json": json.dumps(shuffled)}]
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is True
    assert r.chunks[0].reason == REASON_MATCH
    assert r.summary is not None
    assert r.summary.records_matched == 2
    assert r.summary.records_missing == 0
    assert r.summary.records_extra == 0


def test_eval_scorer_anchor_mode_missing_actual_record() -> None:
    manifest = _manifest_anchor()
    gold = [
        {"numero_serie": "A", "make": "Ford"},
        {"numero_serie": "B", "make": "GM"},
    ]
    job = [{"chunk_index": 0, "record_json": json.dumps([gold[0]])}]
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is False
    assert r.summary is not None
    assert r.summary.records_matched == 1
    assert r.summary.records_missing == 1
    assert r.summary.records_extra == 0
    assert any(d.match == "missing" for d in r.chunks[0].field_diffs)


def test_eval_scorer_anchor_mode_extra_actual_record() -> None:
    manifest = _manifest_anchor()
    gold = [{"numero_serie": "A", "make": "Ford"}]
    actual = [
        {"numero_serie": "A", "make": "Ford"},
        {"numero_serie": "X", "make": "Extra"},
    ]
    job = [{"chunk_index": 0, "record_json": json.dumps(actual)}]
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is False
    assert r.summary is not None
    assert r.summary.records_matched == 1
    assert r.summary.records_extra == 1
    assert r.summary.records_missing == 0
    assert any(d.match == "extra" for d in r.chunks[0].field_diffs)


def test_f14_unexpected_field_is_mismatch_not_fieldmatch_extra() -> None:
    """F-14: key-only surprises use MatchType mismatch; ``extra`` is for orphan records (anchor)."""
    diffs, _, _, _ = _field_diffs_for_records(
        [{"a": 1}],
        [{"a": 1, "unexpected": 2}],
    )
    assert any(d.field == "unexpected" and d.match == "mismatch" for d in diffs)
    assert not any(d.match == "extra" for d in diffs)


def test_eval_scorer_anchor_mode_duplicate_anchor_warning(caplog: pytest.LogCaptureFixture) -> None:
    manifest = _manifest_anchor()
    gold = [
        {"numero_serie": "SAME", "make": "A"},
        {"numero_serie": "SAME", "make": "B"},
    ]
    actual = [{"numero_serie": "SAME", "make": "A"}]
    job = [{"chunk_index": 0, "record_json": json.dumps(actual)}]
    caplog.set_level(logging.WARNING, logger="hermes.eval.scorer")
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is False
    assert "duplicate anchor" in caplog.text.lower()
    assert r.summary is not None
    assert r.summary.records_matched == 1
    assert r.summary.records_missing == 1


def test_eval_scorer_anchor_mode_actual_row_missing_anchor() -> None:
    manifest = _manifest_anchor()
    gold = [{"numero_serie": "A", "make": "Ford"}]
    actual = [{"make": "Ford"}]
    job = [{"chunk_index": 0, "record_json": json.dumps(actual)}]
    r = score_fixture(manifest, job, {0: gold})
    assert r.chunks[0].passed is False
    assert r.summary is not None
    assert r.summary.records_matched == 0
    assert r.summary.records_extra == 1
    assert r.summary.records_missing == 1
    assert any(d.match == "extra" for d in r.chunks[0].field_diffs)


def test_eval_scorer_negative_false_positive_rate_in_summary() -> None:
    manifest = EvalManifest(
        fixture_path="x.pdf",
        schema_ref="ref",
        addressing="chunk_index",
        chunks=[
            ChunkExpectation(chunk_index=0, label=ChunkLabel.NEGATIVE),
            ChunkExpectation(chunk_index=1, label=ChunkLabel.NEGATIVE),
        ],
    )
    job = [
        {"chunk_index": 0, "record_json": "[]"},
        {"chunk_index": 1, "record_json": json.dumps([{"x": 1}])},
    ]
    r = score_fixture(manifest, job, None)
    assert r.summary is not None
    assert r.summary.negative_false_positive_rate == pytest.approx(0.5)
