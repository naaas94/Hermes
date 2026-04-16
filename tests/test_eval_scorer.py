"""Tests for eval scoring (manifest + job results + goldens)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, EvalManifest
from hermes.eval.scorer import (
    REASON_CORRECT_ABSTENTION,
    REASON_FALSE_POSITIVE,
    REASON_FIELD_MISMATCH,
    REASON_GOLDEN_PARSE_ERROR,
    REASON_MATCH,
    REASON_MISSING_CHUNK_IN_RESULTS,
    REASON_MISSING_OUTPUT,
    REASON_PAGE_RANGE_UNRESOLVED,
    REASON_RECORD_JSON_PARSE_ERROR,
    REASON_SCHEMA_PASS_NO_GOLDEN,
    REASON_SCHEMA_REJECT,
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
