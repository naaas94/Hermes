"""Integration test: full pipeline end-to-end with mocked LLM."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor as RealThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.db import get_connection
from hermes.models import Chunk, LLMResponse


@pytest.fixture()
def mock_llm_response():
    return LLMResponse(
        content=json.dumps([
            {
                "marca": "Toyota",
                "descripcion": "Corolla SE",
                "modelo": 2023,
                "numero_serie": "JTDS4RCE1P0000001",
                "tipo_vehiculo": "Sedan",
                "cobertura": "Amplia",
                "suma_asegurada": 350000.0,
                "deducible": "5%",
            },
            {
                "marca": "Honda",
                "descripcion": "Civic EX",
                "modelo": 2022,
                "numero_serie": "2HGFC2F60NH000002",
                "tipo_vehiculo": "Sedan",
                "cobertura": "Basica",
                "suma_asegurada": 280000.0,
                "deducible": "10%",
            },
        ]),
        model="qwen3:4b",
        tokens_in=500,
        tokens_out=200,
        latency_ms=2000,
    )


def test_full_pipeline_with_excel(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
):
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    with patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client):
        from hermes.extraction.pipeline import run_pipeline
        job_id = run_pipeline(
            sample_excel,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
        )

    assert job_id

    from hermes.db import get_job, get_llm_runs_for_job, get_results_for_job, get_stages_for_job
    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status.value in ("completed", "partial")
    assert job.contract_id is not None

    results = get_results_for_job(conn, job_id)
    assert len(results) >= 1
    assert all(r.contract_id == job.contract_id for r in results)

    runs = get_llm_runs_for_job(conn, job_id)
    assert runs
    assert all(r.contract_id == job.contract_id for r in runs)

    records = json.loads(results[0].record_json)
    assert len(records) == 2
    assert records[0]["marca"] == "Toyota"

    stages = get_stages_for_job(conn, job_id)
    stage_names = {s.stage for s in stages}
    assert {"preflight", "normalization", "chunking", "extraction"}.issubset(stage_names)

    conn.close()


def test_full_pipeline_with_pdf(
    sample_pdf_text: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
):
    if not sample_pdf_text.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    with patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client):
        from hermes.extraction.pipeline import run_pipeline
        job_id = run_pipeline(
            sample_pdf_text,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
        )

    assert job_id

    from hermes.db import get_job, get_llm_runs_for_job, get_results_for_job, get_stages_for_job
    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status.value in ("completed", "partial")
    assert job.contract_id is not None

    results = get_results_for_job(conn, job_id)
    assert results
    assert all(r.contract_id == job.contract_id for r in results)
    runs = get_llm_runs_for_job(conn, job_id)
    assert runs
    assert all(r.contract_id == job.contract_id for r in runs)

    stages = get_stages_for_job(conn, job_id)
    stage_names = {s.stage for s in stages}
    assert {"preflight", "normalization", "chunking", "extraction"}.issubset(stage_names)

    conn.close()


def test_pipeline_parallel_workers_processes_multiple_chunks(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
):
    """Two chunks + max_workers=2 exercises the ThreadPoolExecutor extraction path."""
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="chunk zero text",
                source_pages=[0],
                estimated_tokens=50,
            ),
            Chunk(
                chunk_index=1,
                text="chunk one text",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    pool_kwargs: dict[str, int] = {}

    def thread_pool_spy(*args: object, **kwargs: object) -> RealThreadPoolExecutor:
        pool_kwargs["max_workers"] = int(kwargs.get("max_workers", 0))
        return RealThreadPoolExecutor(*args, **kwargs)

    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
        patch(
            "hermes.extraction.pipeline.ThreadPoolExecutor",
            side_effect=thread_pool_spy,
        ),
    ):
        from hermes.extraction.pipeline import run_pipeline

        job_id = run_pipeline(
            sample_excel,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
            max_workers=2,
        )

    assert job_id
    assert mock_client.chat.call_count == 2
    assert pool_kwargs.get("max_workers") == 2

    from hermes.db import get_job, get_llm_runs_for_job, get_results_for_job
    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status.value in ("completed", "partial")
    assert job.contract_id is not None
    for r in get_results_for_job(conn, job_id):
        assert r.contract_id == job.contract_id
    for r in get_llm_runs_for_job(conn, job_id):
        assert r.contract_id == job.contract_id
    conn.close()


def test_resume_pipeline_finishes_remaining_chunks(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
):
    """Delete one chunk result and resume; only the missing chunk should call the LLM."""
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="chunk zero text",
                source_pages=[0],
                estimated_tokens=50,
            ),
            Chunk(
                chunk_index=1,
                text="chunk one text",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        job_id = run_pipeline(
            sample_excel,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
        )

    assert mock_client.chat.call_count == 2

    from hermes.db import get_job, get_results_for_job, update_job_status
    from hermes.models import JobStatus

    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM extraction_results WHERE job_id = ? AND chunk_index = 1",
        (job_id,),
    )
    conn.commit()
    update_job_status(
        conn,
        job_id,
        JobStatus.PARTIAL,
        completed_chunks=1,
        failed_chunks=0,
    )
    conn.close()

    mock_client.reset_mock()
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import resume_pipeline

        resume_pipeline(job_id)

    assert mock_client.chat.call_count == 1

    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    results = get_results_for_job(conn, job_id)
    assert len(results) == 2
    conn.close()


def test_unknown_file_graceful_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("hello from plain text", encoding="utf-8")

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    from hermes.extraction.pipeline import run_pipeline

    job_id = run_pipeline(
        txt_path,
        schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
    )
    assert job_id

    from hermes.db import get_job, get_results_for_job, get_stages_for_job
    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status.value == "failed"
    assert "Unsupported file type" in job.normalization_error

    results = get_results_for_job(conn, job_id)
    assert len(results) == 0

    stages = get_stages_for_job(conn, job_id)
    stage_names = {s.stage for s in stages}
    assert "preflight" in stage_names
    assert "normalization" in stage_names
    conn.close()
