"""SQLite database layer with WAL mode and migration support."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from hermes.config import get_db_path, get_migrations_dir
from hermes.models import (
    DLQStatus,
    ExtractionResult,
    FailedExtraction,
    Job,
    JobStatus,
    LLMRun,
    PipelineStage,
)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending SQL migrations in order."""
    migrations_dir = get_migrations_dir()
    if not migrations_dir.exists():
        return

    sql_files = sorted(migrations_dir.glob("*.sql"))
    for sql_file in sql_files:
        version = int(sql_file.stem.split("_")[0])
        cur = conn.execute(
            "SELECT 1 FROM schema_version WHERE version = ?", (version,)
        )
        if cur.fetchone():
            continue
        script = sql_file.read_text(encoding="utf-8")
        conn.executescript(script)


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    conn = get_connection(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    run_migrations(conn)
    return conn


# ── Job CRUD ──────────────────────────────────────────────────────────

def create_job(conn: sqlite3.Connection, job: Job) -> Job:
    conn.execute(
        "INSERT INTO jobs (id, file_name, file_type, page_count, has_text_layer, "
        "schema_class, normalization_error, status, total_chunks, completed_chunks, "
        "failed_chunks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            job.id, job.file_name, job.file_type.value, job.page_count,
            int(job.has_text_layer), job.schema_class, job.normalization_error, job.status.value,
            job.total_chunks, job.completed_chunks, job.failed_chunks,
        ),
    )
    conn.commit()
    return job


def update_job_status(
    conn: sqlite3.Connection,
    job_id: str,
    status: JobStatus,
    **kwargs: int | datetime | str | None,
) -> None:
    sets = ["status = ?"]
    vals: list[object] = [status.value]
    for col in (
        "total_chunks",
        "completed_chunks",
        "failed_chunks",
        "completed_at",
        "normalization_error",
    ):
        if col in kwargs:
            sets.append(f"{col} = ?")
            vals.append(kwargs[col])
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()


def get_job(conn: sqlite3.Connection, job_id: str) -> Job | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    return _row_to_job(row)


def list_jobs(conn: sqlite3.Connection) -> list[Job]:
    rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    return [_row_to_job(r) for r in rows]


def _row_to_job(row: sqlite3.Row) -> Job:
    from hermes.models import FileType
    normalization_error = ""
    if "normalization_error" in row.keys():
        normalization_error = row["normalization_error"] or ""

    return Job(
        id=row["id"],
        file_name=row["file_name"],
        file_type=FileType(row["file_type"]),
        page_count=row["page_count"] or 0,
        has_text_layer=bool(row["has_text_layer"]),
        schema_class=row["schema_class"],
        normalization_error=normalization_error,
        status=JobStatus(row["status"]),
        total_chunks=row["total_chunks"] or 0,
        completed_chunks=row["completed_chunks"] or 0,
        failed_chunks=row["failed_chunks"] or 0,
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


# ── Extraction Results ────────────────────────────────────────────────

def save_result(conn: sqlite3.Connection, result: ExtractionResult) -> None:
    conn.execute(
        "INSERT INTO extraction_results (job_id, chunk_index, source_pages, "
        "record_json, model, prompt_version) VALUES (?, ?, ?, ?, ?, ?)",
        (
            result.job_id, result.chunk_index, result.source_pages,
            result.record_json, result.model, result.prompt_version,
        ),
    )
    conn.commit()


def get_results_for_job(conn: sqlite3.Connection, job_id: str) -> list[ExtractionResult]:
    rows = conn.execute(
        "SELECT * FROM extraction_results WHERE job_id = ? ORDER BY chunk_index",
        (job_id,),
    ).fetchall()
    return [
        ExtractionResult(
            id=r["id"], job_id=r["job_id"], chunk_index=r["chunk_index"],
            source_pages=r["source_pages"] or "", record_json=r["record_json"],
            model=r["model"] or "", prompt_version=r["prompt_version"] or "",
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── LLM Runs ─────────────────────────────────────────────────────────

def save_llm_run(conn: sqlite3.Connection, run: LLMRun) -> None:
    conn.execute(
        "INSERT INTO llm_runs (job_id, chunk_index, run_type, model, prompt_version, "
        "tokens_in, tokens_out, total_latency_ms, validation_passed, "
        "validation_error, raw_output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run.job_id, run.chunk_index, run.run_type, run.model,
            run.prompt_version, run.tokens_in, run.tokens_out,
            run.total_latency_ms, int(run.validation_passed),
            run.validation_error, run.raw_output,
        ),
    )
    conn.commit()


# ── Pipeline Stage Telemetry ─────────────────────────────────────────

def save_pipeline_stage(conn: sqlite3.Connection, stage: PipelineStage) -> None:
    conn.execute(
        "INSERT INTO pipeline_stages (job_id, stage, started_at, ended_at, "
        "duration_ms, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (
            stage.job_id,
            stage.stage,
            stage.started_at,
            stage.ended_at,
            stage.duration_ms,
            stage.detail,
        ),
    )
    conn.commit()


def get_stages_for_job(conn: sqlite3.Connection, job_id: str) -> list[PipelineStage]:
    rows = conn.execute(
        "SELECT * FROM pipeline_stages WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    return [
        PipelineStage(
            id=r["id"],
            job_id=r["job_id"],
            stage=r["stage"],
            started_at=r["started_at"] or "",
            ended_at=r["ended_at"] or "",
            duration_ms=r["duration_ms"] or 0,
            detail=r["detail"] or "",
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ── Failed Extractions (DLQ) ─────────────────────────────────────────

def save_failed(conn: sqlite3.Connection, fail: FailedExtraction) -> None:
    conn.execute(
        "INSERT INTO failed_extractions (job_id, chunk_index, chunk_text_uri, "
        "last_error, retry_count, status) VALUES (?, ?, ?, ?, ?, ?)",
        (
            fail.job_id, fail.chunk_index, fail.chunk_text_uri,
            fail.last_error, fail.retry_count, fail.status.value,
        ),
    )
    conn.commit()


def get_failed_for_job(
    conn: sqlite3.Connection, job_id: str | None = None
) -> list[FailedExtraction]:
    if job_id:
        rows = conn.execute(
            "SELECT * FROM failed_extractions WHERE job_id = ? AND status = 'pending' "
            "ORDER BY chunk_index",
            (job_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM failed_extractions WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    return [
        FailedExtraction(
            id=r["id"], job_id=r["job_id"], chunk_index=r["chunk_index"],
            chunk_text_uri=r["chunk_text_uri"] or "", last_error=r["last_error"] or "",
            retry_count=r["retry_count"], status=DLQStatus(r["status"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


def update_failed_status(
    conn: sqlite3.Connection, fail_id: int, status: DLQStatus
) -> None:
    conn.execute(
        "UPDATE failed_extractions SET status = ? WHERE id = ?",
        (status.value, fail_id),
    )
    conn.commit()


def get_llm_runs_for_job(conn: sqlite3.Connection, job_id: str) -> list[LLMRun]:
    rows = conn.execute(
        "SELECT * FROM llm_runs WHERE job_id = ? ORDER BY chunk_index, created_at",
        (job_id,),
    ).fetchall()
    return [
        LLMRun(
            id=r["id"], job_id=r["job_id"], chunk_index=r["chunk_index"],
            run_type=r["run_type"], model=r["model"] or "",
            prompt_version=r["prompt_version"] or "",
            tokens_in=r["tokens_in"] or 0, tokens_out=r["tokens_out"] or 0,
            total_latency_ms=r["total_latency_ms"] or 0,
            validation_passed=bool(r["validation_passed"]),
            validation_error=r["validation_error"] or "",
            raw_output=r["raw_output"] or "",
            created_at=r["created_at"],
        )
        for r in rows
    ]


def export_results_as_records(
    conn: sqlite3.Connection, job_id: str
) -> list[dict]:  # type: ignore[type-arg]
    """Return all extraction results for a job as a list of parsed dicts."""
    results = get_results_for_job(conn, job_id)
    records: list[dict] = []  # type: ignore[type-arg]
    for r in results:
        try:
            parsed = json.loads(r.record_json)
            if isinstance(parsed, list):
                records.extend(parsed)
            else:
                records.append(parsed)
        except json.JSONDecodeError:
            continue
    return records
