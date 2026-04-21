"""Unit tests for hermes.eval.runner (no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, EvalManifest, load_manifest
from hermes.eval.runner import (
    ManifestEvalOutcome,
    ResultsMode,
    apply_golden_updates,
    build_chunk_page_map,
    discover_manifest_paths,
    eval_outcomes_ok,
    job_results_from_db_rows,
    load_job_results_from_jsonl,
    load_manifest_or_error,
    outcomes_to_json_blob,
    resolve_fixture_path,
    run_eval_suite,
    score_manifest_with_results,
)
from hermes.eval.scorer import REASON_PAGE_RANGE_UNRESOLVED


def test_runner_discover_manifest_paths(tmp_path: Path) -> None:
    d = tmp_path / "eval"
    d.mkdir()
    (d / "a.manifest.yaml").write_text(
        "fixture_path: x\nschema_ref: m:C\naddressing: chunk_index\n"
        "chunks:\n  - chunk_index: 0\n    label: positive\n",
        encoding="utf-8",
    )
    (d / "ignore.txt").write_text("n", encoding="utf-8")
    found = discover_manifest_paths(d)
    assert len(found) == 1
    assert found[0].name == "a.manifest.yaml"


def test_runner_load_job_results_from_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    p.write_text(
        '{"chunk_index": 0, "record_json": "[{\\"a\\": 1}]"}\n'
        '{"chunk_index": 1, "records": [{"b": 2}], "validation_passed": true}\n',
        encoding="utf-8",
    )
    rows = load_job_results_from_jsonl(p)
    assert len(rows) == 2
    assert rows[0]["chunk_index"] == 0
    assert rows[1]["chunk_index"] == 1


def test_runner_load_job_results_from_jsonl_errors(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_job_results_from_jsonl(p)


def test_runner_from_results_requires_manifest() -> None:
    with pytest.raises(ValueError, match="--from-results requires"):
        run_eval_suite(
            manifest_paths=[
                Path("a.manifest.yaml"),
                Path("b.manifest.yaml"),
            ],
            project_root=Path.cwd(),
            results_mode=ResultsMode.FROM_JOB,
            job_id="jid",
        )


def test_runner_job_results_from_db_rows() -> None:
    row = MagicMock()
    row.chunk_index = 2
    row.record_json = "[{}]"
    row.source_pages = "3,4"
    out = job_results_from_db_rows([row])
    assert out == [
        {
            "chunk_index": 2,
            "record_json": "[{}]",
            "validation_passed": True,
            "source_pages": "3,4",
        },
    ]


def test_runner_build_chunk_page_map() -> None:
    m = build_chunk_page_map(
        [
            {"chunk_index": 0, "source_pages": "1"},
            {"chunk_index": 1, "source_pages": ""},
            {"chunk_index": 2, "record_json": "[]"},
        ],
    )
    assert m == {0: (1, 1)}


def test_runner_page_range_manifest_jsonl_with_source_pages(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    man_path = repo / "tests/fixtures/eval/sample_pdf_text_by_pages.manifest.yaml"
    if not man_path.is_file():
        pytest.skip("page-range eval manifest missing")
    manifest = load_manifest(man_path)
    golden_file = repo / "tests/fixtures/eval/sample_pdf_text.golden.jsonl"
    line0 = golden_file.read_text(encoding="utf-8").splitlines()[0].strip()
    jpath = tmp_path / "rows.jsonl"
    jpath.write_text(
        json.dumps(
            {"chunk_index": 0, "record_json": line0, "source_pages": "1"},
        )
        + "\n",
        encoding="utf-8",
    )
    job = load_job_results_from_jsonl(jpath)
    res = score_manifest_with_results(manifest, man_path, job, project_root=repo)
    assert res.error is None
    assert res.summary is not None
    assert res.summary.passed_expectations == res.summary.total_expectations


def test_runner_page_range_manifest_jsonl_without_source_pages(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    man_path = repo / "tests/fixtures/eval/sample_pdf_text_by_pages.manifest.yaml"
    if not man_path.is_file():
        pytest.skip("page-range eval manifest missing")
    manifest = load_manifest(man_path)
    golden_file = repo / "tests/fixtures/eval/sample_pdf_text.golden.jsonl"
    line0 = golden_file.read_text(encoding="utf-8").splitlines()[0].strip()
    jpath = tmp_path / "rows.jsonl"
    jpath.write_text(
        json.dumps({"chunk_index": 0, "record_json": line0}) + "\n",
        encoding="utf-8",
    )
    job = load_job_results_from_jsonl(jpath)
    res = score_manifest_with_results(manifest, man_path, job, project_root=repo)
    assert res.error is None
    assert res.chunks
    assert res.chunks[0].passed is False
    assert res.chunks[0].reason == REASON_PAGE_RANGE_UNRESOLVED


def test_runner_page_range_db_mode_scores_with_source_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = Path(__file__).resolve().parents[1]
    man_path = repo / "tests/fixtures/eval/sample_pdf_text_by_pages.manifest.yaml"
    if not man_path.is_file():
        pytest.skip("page-range eval manifest missing")
    manifest = load_manifest(man_path)
    golden_file = repo / "tests/fixtures/eval/sample_pdf_text.golden.jsonl"
    line0 = golden_file.read_text(encoding="utf-8").splitlines()[0].strip()

    row = MagicMock()
    row.chunk_index = 0
    row.record_json = line0
    row.source_pages = "1"

    db_path = tmp_path / "t.db"
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)

    from hermes.db import create_job, init_db, save_result
    from hermes.models import ExtractionResult, FileType, Job, JobStatus

    conn = init_db(db_path)
    create_job(
        conn,
        Job(
            id="job-pr",
            file_name="sample_text.pdf",
            file_type=FileType.PDF_TEXT,
            page_count=2,
            has_text_layer=True,
            schema_class="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            status=JobStatus.COMPLETED,
            total_chunks=1,
            completed_chunks=1,
        ),
    )
    save_result(
        conn,
        ExtractionResult(
            job_id="job-pr",
            contract_id=None,
            chunk_index=0,
            source_pages="1",
            record_json=line0,
            model="m",
            prompt_version="p",
        ),
    )
    conn.close()

    from hermes.db import get_results_for_job, open_db

    with open_db() as conn:
        rows = get_results_for_job(conn, "job-pr")
    job_results = job_results_from_db_rows(rows)
    assert job_results[0].get("source_pages") == "1"
    res = score_manifest_with_results(manifest, man_path, job_results, project_root=repo)
    assert res.error is None
    assert res.summary is not None
    assert res.summary.passed_expectations == res.summary.total_expectations


def test_runner_load_manifest_or_error_missing(tmp_path: Path) -> None:
    m, err = load_manifest_or_error(tmp_path / "nope.yaml")
    assert m is None
    assert err is not None
    assert err.error and "not found" in err.error


def test_runner_score_manifest_missing_fixture(tmp_path: Path) -> None:
    p = tmp_path / "m.manifest.yaml"
    p.write_text(
        "fixture_path: does_not_exist.xlsx\n"
        "schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord\n"
        "addressing: chunk_index\n"
        "chunks:\n  - chunk_index: 0\n    label: positive\n",
        encoding="utf-8",
    )
    manifest = load_manifest(p)
    r = score_manifest_with_results(
        manifest,
        p,
        [{"chunk_index": 0, "record_json": "[]"}],
        project_root=tmp_path,
    )
    assert r.error and "fixture file missing" in r.error


def test_runner_resolve_fixture_path(tmp_path: Path) -> None:
    pr = tmp_path / "repo"
    pr.mkdir()
    m = EvalManifest(
        fixture_path="tests/fixtures/eval/sample.xlsx",
        schema_ref="x:Y",
        addressing="chunk_index",
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    assert resolve_fixture_path(m, pr) == pr / "tests/fixtures/eval/sample.xlsx"


def test_runner_apply_golden_updates_manifest_jsonl(
    tmp_path: Path,
) -> None:
    golden_rel = "out.golden.jsonl"
    m = EvalManifest(
        fixture_path="f.xlsx",
        schema_ref="x:Y",
        addressing="chunk_index",
        golden_path=golden_rel,
        chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
    )
    job = [{"chunk_index": 0, "record_json": json.dumps([{"k": "v"}])}]
    apply_golden_updates(m, job, project_root=tmp_path)
    text = (tmp_path / golden_rel).read_text(encoding="utf-8").strip()
    assert json.loads(text.splitlines()[0]) == [{"k": "v"}]


def test_runner_outcomes_json_roundtrip() -> None:
    from hermes.eval.scorer import EvalResult, EvalSummary

    o = ManifestEvalOutcome(
        manifest_path=Path("m.yaml"),
        fixture_resolved=Path("f.xlsx"),
        job_id="j1",
        result=EvalResult(
            summary=EvalSummary(
                fixture_path="f.xlsx",
                schema_ref="s",
                total_expectations=1,
                passed_expectations=1,
                positive_total=1,
                positive_passed=1,
                negative_total=0,
                negative_passed=0,
                negative_false_positive_rate=None,
                field_level_accuracy=1.0,
            ),
        ),
    )
    blob = outcomes_to_json_blob([o])
    assert blob[0]["job_id"] == "j1"
    assert blob[0]["result"]["summary"]["positive_passed"] == 1


def test_runner_eval_outcomes_ok_empty() -> None:
    assert eval_outcomes_ok([]) is False


@patch("hermes.extraction.pipeline.run_pipeline", return_value="job-a")
def test_runner_pipeline_mode_scores(
    _mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline is mocked; DB reads use a temp DB with one extraction row."""
    db_path = tmp_path / "t.db"
    storage_path = tmp_path / "st"
    storage_path.mkdir()
    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    fx = tmp_path / "sample.xlsx"
    fx.write_bytes(b"dummy")

    man = tmp_path / "t.manifest.yaml"
    man.write_text(
        f"fixture_path: {fx.as_posix()}\n"
        "schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord\n"
        "addressing: chunk_index\n"
        "chunks:\n  - chunk_index: 0\n    label: positive\n",
        encoding="utf-8",
    )

    from hermes.db import create_job, init_db, save_result
    from hermes.models import ExtractionResult, FileType, Job, JobStatus

    conn = init_db(db_path)
    create_job(
        conn,
        Job(
            id="job-a",
            file_name="sample.xlsx",
            file_type=FileType.EXCEL,
            page_count=1,
            has_text_layer=True,
            schema_class="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            status=JobStatus.COMPLETED,
            total_chunks=1,
            completed_chunks=1,
        ),
    )
    save_result(
        conn,
        ExtractionResult(
            job_id="job-a",
            contract_id=None,
            chunk_index=0,
            record_json=json.dumps([{"marca": "X"}]),
            model="m",
            prompt_version="p",
        ),
    )
    conn.close()

    outcomes = run_eval_suite(
        manifest_paths=[man],
        project_root=tmp_path,
        results_mode=ResultsMode.PIPELINE,
    )
    _mock_run.assert_called_once()
    assert _mock_run.call_args.kwargs.get("force_new_job") is True

    assert len(outcomes) == 1
    assert outcomes[0].job_id == "job-a"
    r = outcomes[0].result
    assert r.error is None
    assert r.summary is not None
    assert r.summary.positive_passed == r.summary.positive_total
    assert eval_outcomes_ok(outcomes) is True
