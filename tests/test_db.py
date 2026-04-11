"""Tests for database initialization and CRUD operations."""

from __future__ import annotations

import sqlite3

from hermes.db import (
    count_distinct_extraction_chunk_indices,
    create_job,
    get_job,
    get_llm_runs_for_job,
    get_results_for_job,
    get_stages_for_job,
    get_successful_chunk_indices,
    insert_extraction_contract,
    list_jobs,
    resolve_or_create_extraction_contract,
    save_failed,
    save_llm_run,
    save_pipeline_stage,
    save_result,
    update_job_status,
)
from hermes.extraction.contract_identity import canonical_json_schema, compute_contract_id
from hermes.models import (
    ExtractionResult,
    FailedExtraction,
    FileType,
    Job,
    JobStatus,
    LLMRun,
    PipelineStage,
)


def test_init_db_creates_tables(tmp_db: sqlite3.Connection):
    tables = tmp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r["name"] for r in tables}
    assert "jobs" in table_names
    assert "extraction_results" in table_names
    assert "llm_runs" in table_names
    assert "failed_extractions" in table_names
    assert "pipeline_stages" in table_names
    assert "schema_version" in table_names
    assert "extraction_contracts" in table_names


def test_schema_version_applied(tmp_db: sqlite3.Connection):
    for v in (1, 2, 3, 4, 5):
        row = tmp_db.execute(
            "SELECT version FROM schema_version WHERE version = ?", (v,)
        ).fetchone()
        assert row is not None


def test_create_and_get_job(tmp_db: sqlite3.Connection):
    job = Job(
        id="abc123",
        file_name="test.xlsx",
        file_type=FileType.EXCEL,
        page_count=3,
        has_text_layer=False,
        schema_class="hermes.schemas.examples.generic_table:GenericRow",
    )
    create_job(tmp_db, job)

    fetched = get_job(tmp_db, "abc123")
    assert fetched is not None
    assert fetched.file_name == "test.xlsx"
    assert fetched.file_type == FileType.EXCEL
    assert fetched.status == JobStatus.QUEUED
    assert fetched.pages_spec == ""


def test_get_successful_chunk_indices(tmp_db: sqlite3.Connection):
    job = Job(
        id="chunks1",
        file_name="a.xlsx",
        file_type=FileType.EXCEL,
        schema_class="x:Y",
    )
    create_job(tmp_db, job)
    save_result(
        tmp_db,
        ExtractionResult(
            job_id="chunks1",
            chunk_index=0,
            record_json="[]",
        ),
    )
    save_result(
        tmp_db,
        ExtractionResult(
            job_id="chunks1",
            chunk_index=2,
            record_json="[]",
        ),
    )
    assert get_successful_chunk_indices(tmp_db, "chunks1") == {0, 2}


def test_update_job_status(tmp_db: sqlite3.Connection):
    job = Job(id="def456", file_name="a.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    update_job_status(tmp_db, "def456", JobStatus.EXTRACTING, total_chunks=5)
    fetched = get_job(tmp_db, "def456")
    assert fetched is not None
    assert fetched.status == JobStatus.EXTRACTING
    assert fetched.total_chunks == 5


def test_update_job_status_with_normalization_error(tmp_db: sqlite3.Connection):
    job = Job(id="def457", file_name="bad.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    error_msg = "Normalization failed: malformed xref table"
    update_job_status(
        tmp_db,
        "def457",
        JobStatus.FAILED,
        normalization_error=error_msg,
    )
    fetched = get_job(tmp_db, "def457")
    assert fetched is not None
    assert fetched.status == JobStatus.FAILED
    assert fetched.normalization_error == error_msg


def test_list_jobs(tmp_db: sqlite3.Connection):
    for i in range(3):
        job = Job(
            id=f"job{i}", file_name=f"f{i}.xlsx",
            file_type=FileType.EXCEL, schema_class="x:Y",
        )
        create_job(tmp_db, job)

    jobs = list_jobs(tmp_db)
    assert len(jobs) == 3


def test_save_and_get_results(tmp_db: sqlite3.Connection):
    job = Job(id="res_job", file_name="t.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    result = ExtractionResult(
        job_id="res_job", chunk_index=0,
        source_pages="0,1", record_json='[{"key": "val"}]',
        model="qwen3:4b", prompt_version="abc",
    )
    save_result(tmp_db, result)

    fetched = get_results_for_job(tmp_db, "res_job")
    assert len(fetched) == 1
    assert fetched[0].record_json == '[{"key": "val"}]'

    assert count_distinct_extraction_chunk_indices(tmp_db, "res_job") == 1

    save_result(
        tmp_db,
        ExtractionResult(
            job_id="res_job",
            chunk_index=1,
            source_pages="2",
            record_json="[]",
            model="qwen3:4b",
            prompt_version="abc",
        ),
    )
    assert count_distinct_extraction_chunk_indices(tmp_db, "res_job") == 2

    save_result(
        tmp_db,
        ExtractionResult(
            job_id="res_job",
            chunk_index=1,
            source_pages="2",
            record_json="[]",
            model="qwen3:4b",
            prompt_version="abc",
        ),
    )
    assert count_distinct_extraction_chunk_indices(tmp_db, "res_job") == 2


def test_save_llm_run(tmp_db: sqlite3.Connection):
    job = Job(id="run_job", file_name="t.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    run = LLMRun(
        job_id="run_job", chunk_index=0, model="qwen3:4b",
        prompt_version="v1", tokens_in=100, tokens_out=50,
        total_latency_ms=1500, validation_passed=True,
    )
    save_llm_run(tmp_db, run)


def test_save_failed_extraction(tmp_db: sqlite3.Connection):
    job = Job(id="fail_job", file_name="t.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    fail = FailedExtraction(
        job_id="fail_job", chunk_index=2,
        chunk_text_uri="chunks/chunk_2.md",
        last_error="JSON parse error", retry_count=3,
    )
    save_failed(tmp_db, fail)


def test_extraction_contract_round_trip(tmp_db: sqlite3.Connection):
    schema_dict = {"type": "object", "properties": {"x": {"type": "string"}}}
    pv = "prompt_v_test"
    sref = "some.module:Row"
    canonical, sha = canonical_json_schema(schema_dict)
    cid = compute_contract_id(canonical.encode("utf-8"), pv, sref)
    insert_extraction_contract(tmp_db, cid, pv, sref, canonical, sha)

    job = Job(
        id="contract_job",
        file_name="f.xlsx",
        file_type=FileType.EXCEL,
        schema_class=sref,
        contract_id=cid,
    )
    create_job(tmp_db, job)

    run = LLMRun(
        job_id="contract_job",
        contract_id=cid,
        chunk_index=0,
        model="m",
        prompt_version=pv,
    )
    save_llm_run(tmp_db, run)

    res = ExtractionResult(
        job_id="contract_job",
        contract_id=cid,
        chunk_index=0,
        record_json="[]",
        model="m",
        prompt_version=pv,
    )
    save_result(tmp_db, res)

    got = get_job(tmp_db, "contract_job")
    assert got is not None
    assert got.contract_id == cid

    runs = get_llm_runs_for_job(tmp_db, "contract_job")
    assert len(runs) == 1
    assert runs[0].contract_id == cid

    results = get_results_for_job(tmp_db, "contract_job")
    assert len(results) == 1
    assert results[0].contract_id == cid


def test_resolve_or_create_extraction_contract_dedup(tmp_db: sqlite3.Connection):
    d = {"type": "object"}
    pv = "pv_dedup"
    ref = "m:C"
    c1 = resolve_or_create_extraction_contract(tmp_db, ref, d, pv)
    c2 = resolve_or_create_extraction_contract(tmp_db, ref, d, pv)
    assert c1 == c2


def test_save_and_get_pipeline_stage(tmp_db: sqlite3.Connection):
    job = Job(id="stage_job", file_name="t.pdf", file_type=FileType.PDF_TEXT, schema_class="x:Y")
    create_job(tmp_db, job)

    stage = PipelineStage(
        job_id="stage_job",
        stage="normalization",
        started_at="2026-01-01T10:00:00.000",
        ended_at="2026-01-01T10:00:01.100",
        duration_ms=1100,
        detail="normalized_pages=3, source=pdf_text",
    )
    save_pipeline_stage(tmp_db, stage)

    stages = get_stages_for_job(tmp_db, "stage_job")
    assert len(stages) == 1
    assert stages[0].stage == "normalization"
    assert stages[0].duration_ms == 1100
    assert stages[0].detail == "normalized_pages=3, source=pdf_text"
