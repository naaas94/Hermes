"""Orchestrator: the main extraction pipeline called by the CLI."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from hermes.config import load_config
from hermes.db import (
    create_job,
    get_connection,
    init_db,
    save_failed,
    save_llm_run,
    save_pipeline_stage,
    save_result,
    update_job_status,
)
from hermes.extraction.llm_client import BaseLLMClient, create_llm_client
from hermes.extraction.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    get_current_prompt_version,
)
from hermes.extraction.validator import validate_with_repair
from hermes.ingestion.preflight import run_preflight
from hermes.ingestion.storage import get_chunk_dir, save_raw
from hermes.models import (
    Chunk,
    ExtractionResult,
    FailedExtraction,
    FileType,
    Job,
    JobStatus,
    LLMRun,
    PipelineStage,
)
from hermes.normalization.chunker import chunk_pages
from hermes.normalization.router import route_normalizer
from hermes.schemas.loader import get_json_schema, load_schema

logger = logging.getLogger(__name__)
console = Console()


def run_pipeline(
    file_path: Path,
    schema_ref: str | None = None,
    model_override: str | None = None,
    max_workers: int = 1,
) -> str:
    """Execute the full extraction pipeline on a single file. Returns the job ID."""
    cfg = load_config()
    conn = init_db()

    schema_ref = schema_ref or cfg.extraction.default_schema
    schema_class = load_schema(schema_ref)
    json_schema = get_json_schema(schema_class)

    job_id = uuid.uuid4().hex[:12]

    # 1. Preflight
    console.print(f"[bold]Preflight:[/bold] {file_path.name}")
    preflight_started_at = _now_iso()
    preflight_start_ns = time.perf_counter_ns()
    preflight = run_preflight(file_path)
    preflight_duration_ms = _elapsed_ms(preflight_start_ns)
    preflight_ended_at = _now_iso()
    console.print(
        f"  Type: {preflight.file_type.value} | Pages: {preflight.page_count} | "
        f"~{preflight.estimated_tokens} tokens"
    )

    # 2. Save raw file
    save_raw(file_path, job_id)

    # 3. Create job
    job = Job(
        id=job_id,
        file_name=preflight.file_name,
        file_type=preflight.file_type,
        page_count=preflight.page_count,
        has_text_layer=preflight.has_text_layer,
        schema_class=schema_ref,
        status=JobStatus.NORMALIZING,
    )
    create_job(conn, job)
    save_pipeline_stage(
        conn,
        PipelineStage(
            job_id=job_id,
            stage="preflight",
            started_at=preflight_started_at,
            ended_at=preflight_ended_at,
            duration_ms=preflight_duration_ms,
            detail=(
                f"type={preflight.file_type.value}, pages={preflight.page_count}, "
                f"est_tokens={preflight.estimated_tokens}"
            ),
        ),
    )

    if preflight.file_type == FileType.UNKNOWN:
        unsupported = file_path.suffix.lower() or "unknown"
        error_msg = (
            f"Unsupported file type: {unsupported}. Hermes supports Excel "
            "(.xlsx/.xlsm/.xltx/.xltm) and PDF (.pdf). Job marked as failed."
        )
        failed_at = _now_iso()
        save_pipeline_stage(
            conn,
            PipelineStage(
                job_id=job_id,
                stage="normalization",
                started_at=failed_at,
                ended_at=failed_at,
                duration_ms=0,
                detail=error_msg,
            ),
        )
        update_job_status(
            conn,
            job_id,
            JobStatus.FAILED,
            normalization_error=error_msg,
        )
        console.print(f"[red]{error_msg}[/red]")
        conn.close()
        return job_id

    # 4. Normalize
    console.print("[bold]Normalizing...[/bold]")
    normalize_started_at = _now_iso()
    normalize_start_ns = time.perf_counter_ns()
    try:
        pages = route_normalizer(file_path, job_id, preflight)
    except Exception as e:
        error_msg = f"Normalization failed: {e}"
        normalize_duration_ms = _elapsed_ms(normalize_start_ns)
        normalize_ended_at = _now_iso()
        save_pipeline_stage(
            conn,
            PipelineStage(
                job_id=job_id,
                stage="normalization",
                started_at=normalize_started_at,
                ended_at=normalize_ended_at,
                duration_ms=normalize_duration_ms,
                detail=error_msg,
            ),
        )
        update_job_status(
            conn,
            job_id,
            JobStatus.FAILED,
            normalization_error=error_msg,
        )
        console.print(f"[red]{error_msg}[/red]")
        conn.close()
        return job_id
    normalize_duration_ms = _elapsed_ms(normalize_start_ns)
    normalize_ended_at = _now_iso()
    save_pipeline_stage(
        conn,
        PipelineStage(
            job_id=job_id,
            stage="normalization",
            started_at=normalize_started_at,
            ended_at=normalize_ended_at,
            duration_ms=normalize_duration_ms,
            detail=f"normalized_pages={len(pages)}, source={preflight.file_type.value}",
        ),
    )

    # 5. Chunk
    console.print("[bold]Chunking...[/bold]")
    chunking_started_at = _now_iso()
    chunking_start_ns = time.perf_counter_ns()
    chunks = chunk_pages(pages)
    chunking_duration_ms = _elapsed_ms(chunking_start_ns)
    chunking_ended_at = _now_iso()
    save_pipeline_stage(
        conn,
        PipelineStage(
            job_id=job_id,
            stage="chunking",
            started_at=chunking_started_at,
            ended_at=chunking_ended_at,
            duration_ms=chunking_duration_ms,
            detail=f"chunks={len(chunks)}, pages={len(pages)}",
        ),
    )
    update_job_status(conn, job_id, JobStatus.EXTRACTING, total_chunks=len(chunks))
    console.print(f"  {len(chunks)} chunk(s) ready")

    # Save chunk texts to disk for DLQ replay
    chunk_dir = get_chunk_dir(job_id)
    for chunk in chunks:
        chunk_path = chunk_dir / f"chunk_{chunk.chunk_index}.md"
        chunk_path.write_text(chunk.text, encoding="utf-8")

    # 6. LLM extraction
    extraction_started_at = _now_iso()
    extraction_start_ns = time.perf_counter_ns()
    llm_client = create_llm_client(cfg)
    if model_override:
        if hasattr(llm_client, "model"):
            llm_client.model = model_override  # type: ignore[attr-defined]

    if not llm_client.check_ready():
        extraction_duration_ms = _elapsed_ms(extraction_start_ns)
        extraction_ended_at = _now_iso()
        save_pipeline_stage(
            conn,
            PipelineStage(
                job_id=job_id,
                stage="extraction",
                started_at=extraction_started_at,
                ended_at=extraction_ended_at,
                duration_ms=extraction_duration_ms,
                detail="llm provider not reachable",
            ),
        )
        console.print("[red]LLM provider is not reachable. Aborting.[/red]")
        update_job_status(conn, job_id, JobStatus.FAILED)
        conn.close()
        return job_id

    prompt_ver = get_current_prompt_version()
    max_retries = cfg.llm.max_retries
    completed = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting", total=len(chunks))

        if max_workers > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {
                    executor.submit(
                        _process_chunk,
                        llm_client, chunk, job_id, schema_class, json_schema,
                        prompt_ver, max_retries,
                    ): chunk for chunk in chunks
                }
                for future in as_completed(future_to_chunk):
                    try:
                        success = future.result()
                        if success:
                            completed += 1
                        else:
                            failed += 1
                    except Exception as exc:
                        failed += 1
                        logger.error("Chunk processing generated an exception: %s", exc)

                    update_job_status(
                        conn, job_id, JobStatus.EXTRACTING,
                        completed_chunks=completed, failed_chunks=failed,
                    )
                    progress.advance(task)
        else:
            for chunk in chunks:
                success = _process_chunk(
                    llm_client, chunk, job_id, schema_class, json_schema,
                    prompt_ver, max_retries,
                )
                if success:
                    completed += 1
                else:
                    failed += 1

                update_job_status(
                    conn, job_id, JobStatus.EXTRACTING,
                    completed_chunks=completed, failed_chunks=failed,
                )
                progress.advance(task)

    extraction_duration_ms = _elapsed_ms(extraction_start_ns)
    extraction_ended_at = _now_iso()
    save_pipeline_stage(
        conn,
        PipelineStage(
            job_id=job_id,
            stage="extraction",
            started_at=extraction_started_at,
            ended_at=extraction_ended_at,
            duration_ms=extraction_duration_ms,
            detail=f"completed_chunks={completed}, failed_chunks={failed}",
        ),
    )

    # 7. Final status
    if failed == 0:
        final_status = JobStatus.COMPLETED
    elif completed > 0:
        final_status = JobStatus.PARTIAL
    else:
        final_status = JobStatus.FAILED

    update_job_status(
        conn, job_id, final_status,
        completed_chunks=completed, failed_chunks=failed,
        completed_at=datetime.now(),
    )

    console.print(
        f"\n[bold green]Done![/bold green] Job {job_id}: "
        f"{completed} chunks extracted, {failed} failed. Status: {final_status.value}"
    )
    conn.close()
    return job_id


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _elapsed_ms(start_ns: int) -> int:
    elapsed_ns = time.perf_counter_ns() - start_ns
    return int(elapsed_ns / 1_000_000)


def _process_chunk(
    llm_client: BaseLLMClient,
    chunk: Chunk,
    job_id: str,
    schema_class: type,
    json_schema: dict,  # type: ignore[type-arg]
    prompt_version: str,
    max_retries: int,
) -> bool:
    """Process a single chunk: call LLM, validate, persist. Returns True on success."""
    conn = get_connection()
    user_prompt = build_user_prompt(json_schema, chunk.text)

    try:
        llm_response = llm_client.chat(SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.error("LLM call failed for chunk %d: %s", chunk.chunk_index, e)
        _save_failure(conn, job_id, chunk, str(e), 0)
        conn.close()
        return False

    result = validate_with_repair(
        llm_response, schema_class, json_schema, llm_client, max_retries
    )

    for i, resp in enumerate(result.all_responses):
        is_last = i == len(result.all_responses) - 1
        run = LLMRun(
            job_id=job_id,
            chunk_index=chunk.chunk_index,
            run_type="extraction" if i == 0 else "repair",
            model=resp.model,
            prompt_version=prompt_version,
            tokens_in=resp.tokens_in,
            tokens_out=resp.tokens_out,
            total_latency_ms=resp.latency_ms,
            validation_passed=is_last and bool(result.validated) and not result.error,
            validation_error=result.error if is_last else "",
            raw_output=resp.content,
        )
        save_llm_run(conn, run)

    if result.validated:
        records_json = json.dumps(
            [r.model_dump(mode="json") for r in result.validated]
        )
        source_pages = ",".join(str(p) for p in chunk.source_pages)
        extraction = ExtractionResult(
            job_id=job_id,
            chunk_index=chunk.chunk_index,
            source_pages=source_pages,
            record_json=records_json,
            model=llm_response.model,
            prompt_version=prompt_version,
        )
        save_result(conn, extraction)

    if result.error and not result.validated:
        _save_failure(conn, job_id, chunk, result.error, result.attempts)
        conn.close()
        return False

    conn.close()
    return True



def _save_failure(
    conn, job_id: str, chunk: Chunk, error: str, retry_count: int  # type: ignore[no-untyped-def]
) -> None:
    chunk_uri = f"chunks/chunk_{chunk.chunk_index}.md"
    fail = FailedExtraction(
        job_id=job_id,
        chunk_index=chunk.chunk_index,
        chunk_text_uri=chunk_uri,
        last_error=error,
        retry_count=retry_count,
    )
    save_failed(conn, fail)
