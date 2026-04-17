"""Tests for ``hermes bench`` / :mod:`hermes.bench.runner`."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes.bench.runner import (
    BenchResult,
    BenchSummary,
    BenchWorkload,
    dual_sink_regression_triggered,
    run_bench,
)


def _have_structlog() -> bool:
    try:
        import structlog  # noqa: F401
    except ImportError:
        return False
    return True


@pytest.fixture()
def eval_pdf(fixtures_dir: Path) -> Path:
    p = fixtures_dir / "eval" / "sample_text.pdf"
    if not p.is_file():
        pytest.skip("Committed eval PDF missing")
    return p


@pytest.fixture()
def eval_xlsx(fixtures_dir: Path) -> Path:
    p = fixtures_dir / "eval" / "sample.xlsx"
    if not p.is_file():
        pytest.skip("Committed eval XLSX missing")
    return p


def _patch_storage_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "bench.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)


def test_run_bench_single_positive_duration_and_rss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            workers=1,
            model="qwen3:4b",
            compare_log_format=False,
        ),
    ]
    s = run_bench(
        w,
        out,
        "qwen3:4b",
        1,
        mock_llm=True,
        log_format_compare=False,
        project_root=tmp_path,
    )
    assert len(s.results) == 1
    r = s.results[0]
    assert r.duration_s > 0
    assert r.peak_rss_bytes >= 0
    assert list(out.glob("*.json")), "benchmark JSON should be written"


def test_run_bench_multi_ordered_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
    eval_xlsx: Path,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=False,
        ),
        BenchWorkload(
            name="excel_small",
            input_path=eval_xlsx,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="excel",
            compare_log_format=False,
        ),
    ]
    s = run_bench(w, out, "qwen3:4b", 1, mock_llm=True, project_root=tmp_path)
    assert [x.workload for x in s.results] == ["pdf_text_small", "excel_small"]


def test_missing_fixture_skipped_no_result_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="missing_pdf",
            input_path=tmp_path / "does_not_exist.pdf",
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=False,
        ),
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=False,
        ),
    ]
    s = run_bench(w, out, "qwen3:4b", 1, mock_llm=True, project_root=tmp_path)
    assert len(s.results) == 1
    assert s.results[0].workload == "pdf_text_small"


def test_workload_error_records_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
    eval_xlsx: Path,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="boom",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=False,
        ),
        BenchWorkload(
            name="excel_small",
            input_path=eval_xlsx,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="excel",
            compare_log_format=False,
        ),
    ]

    from hermes.extraction import pipeline as pipeline_mod

    real_run = pipeline_mod.run_pipeline
    calls: list[int] = []

    def _fail_once(*a: object, **k: object) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated pipeline failure")
        return real_run(*a, **k)

    with patch("hermes.bench.runner.run_pipeline", side_effect=_fail_once):
        s = run_bench(w, out, "qwen3:4b", 1, mock_llm=True, project_root=tmp_path)
    assert len(s.results) == 1
    assert s.results[0].workload == "excel_small"


def test_csv_headers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, eval_pdf: Path) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=False,
        ),
    ]
    run_bench(
        w,
        out,
        "qwen3:4b",
        1,
        mock_llm=True,
        write_csv=True,
        project_root=tmp_path,
    )
    csv_paths = list(out.glob("*.csv"))
    assert len(csv_paths) == 1
    text = csv_paths[0].read_text(encoding="utf-8")
    r = csv.reader(text.splitlines())
    header = next(r)
    assert "workload" in header
    assert "log_format" in header
    assert "bench_run_id" in header


@pytest.mark.skipif(not _have_structlog(), reason="Dual log-format run requires structlog ([obs])")
def test_dual_log_format_compare_two_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=True,
        ),
    ]
    s = run_bench(
        w,
        out,
        "qwen3:4b",
        1,
        mock_llm=True,
        log_format_compare=True,
        project_root=tmp_path,
    )
    assert len(s.results) == 2
    fmts = {r.log_format for r in s.results}
    assert fmts == {"console", "json"}
    json_row = next(r for r in s.results if r.log_format == "json")
    assert json_row.dual_sink_overhead_pct is not None


def test_dual_sink_regression_helper() -> None:
    assert dual_sink_regression_triggered("pdf_text_small", 10.1)
    assert not dual_sink_regression_triggered("pdf_text_small", 10.0)
    assert not dual_sink_regression_triggered("excel_small", 50.0)


@pytest.mark.skipif(not _have_structlog(), reason="Dual log-format run requires structlog ([obs])")
def test_dual_sink_regression_warn_and_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    eval_pdf: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_storage_db(tmp_path, monkeypatch)
    out = tmp_path / "bench_out"
    w = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=eval_pdf,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            file_type="pdf",
            compare_log_format=True,
        ),
    ]
    with patch("hermes.bench.runner._dual_overhead_pct", return_value=15.0):
        s = run_bench(
            w,
            out,
            "qwen3:4b",
            1,
            mock_llm=True,
            log_format_compare=True,
            project_root=tmp_path,
        )
    assert s.dual_sink_regression
    assert any("bench.dualsink.regression" in r.message for r in caplog.records)


def test_bench_summary_json_roundtrip() -> None:
    s = BenchSummary(
        bench_run_id="b1",
        commit="abc",
        timestamp="2026-01-01T00:00:00Z",
        environment={"os": "Linux"},
        results=[],
    )
    blob = s.model_dump(mode="json")
    s2 = BenchSummary.model_validate(blob)
    assert s2.bench_run_id == "b1"


def test_bench_result_optional_throughput() -> None:
    r = BenchResult(
        workload="excel_small",
        commit="x",
        machine={},
        duration_s=1.0,
        peak_rss_bytes=0,
        rows_per_minute=120.0,
        timestamp="2026-01-01T00:00:00Z",
        log_format="console",
    )
    d = json.loads(json.dumps(r.model_dump(mode="json")))
    assert d["pages_per_minute"] is None
