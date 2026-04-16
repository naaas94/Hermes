"""Orchestrator: the main extraction pipeline called by the CLI."""

from __future__ import annotations

import json
import logging
import signal
import sqlite3
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

from hermes.config import HermesConfig, load_config
from hermes.db import (
    create_job,
    find_completed_dedup_job,
    get_failed_for_job,
    get_job,
    get_stages_for_job,
    get_successful_chunk_indices,
    open_connection,
    open_db,
    resolve_or_create_extraction_contract,
    save_failed,
    save_llm_run,
    save_pipeline_stage,
    save_result,
    update_job_contract_id,
    update_job_status,
)
from hermes.dedup import effective_llm_model, sha256_file_hex
from hermes.extraction.llm_client import BaseLLMClient, create_llm_client
from hermes.extraction.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    get_current_prompt_version,
)
from hermes.extraction.validator import validate_with_repair
from hermes.ingestion.pages_spec import resolve_page_indices_0
from hermes.ingestion.preflight import run_preflight
from hermes.ingestion.storage import (
    get_chunk_dir,
    get_raw_path,
    load_normalized_pages_from_store,
    save_raw,
)
from hermes.models import (
    Chunk,
    ExtractionResult,
    FailedExtraction,
    FileType,
    Job,
    JobStatus,
    LLMRun,
    PipelineStage,
    PreflightResult,
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
    pages_spec: str | None = None,
    force_new_job: bool = False,
) -> str:
    """Execute the full extraction pipeline on a single file. Returns the job ID."""
    cfg = load_config()
    stop_requested = threading.Event()

    def _sigint_handler(_signum: int, _frame: Any) -> None:
        stop_requested.set()

    prev_sigint: Any | None
    try:
        prev_sigint = signal.signal(signal.SIGINT, _sigint_handler)
    except ValueError:
        # Not the main thread; graceful shutdown via SIGINT is unavailable.
        prev_sigint = None

    try:
        return _run_pipeline_inner(
            file_path=file_path,
            cfg=cfg,
            schema_ref=schema_ref,
            model_override=model_override,
            max_workers=max_workers,
            pages_spec=pages_spec,
            force_new_job=force_new_job,
            stop_requested=stop_requested,
        )
    finally:
        if prev_sigint is not None:
            signal.signal(signal.SIGINT, prev_sigint)


def resume_pipeline(
    job_id: str,
    model_override: str | None = None,
    max_workers: int = 1,
) -> str:
    """Continue LLM extraction for a job after interrupt or crash (chunking already done).

    Rebuilds chunks from on-disk normalized Markdown and skips indices that already
    have rows in ``extraction_results``.
    """
    cfg = load_config()
    stop_requested = threading.Event()

    def _sigint_handler(_signum: int, _frame: Any) -> None:
        stop_requested.set()

    prev_sigint: Any | None
    try:
        prev_sigint = signal.signal(signal.SIGINT, _sigint_handler)
    except ValueError:
        prev_sigint = None

    try:
        return _resume_pipeline_inner(
            job_id=job_id,
            cfg=cfg,
            model_override=model_override,
            max_workers=max_workers,
            stop_requested=stop_requested,
        )
    finally:
        if prev_sigint is not None:
            signal.signal(signal.SIGINT, prev_sigint)


def _resume_pipeline_inner(
    job_id: str,
    cfg: HermesConfig,
    model_override: str | None,
    max_workers: int,
    stop_requested: threading.Event,
) -> str:
    with open_db() as conn:
        job = get_job(conn, job_id)
        if job is None:
            raise ValueError(f"No job found with id {job_id!r}.")

        if job.status == JobStatus.COMPLETED:
            console.print(
                f"[dim]Job {job_id} is already completed; nothing to resume.[/dim]"
            )
            return job_id

        stages = get_stages_for_job(conn, job_id)
        if not any(s.stage == "chunking" for s in stages):
            raise ValueError(
                f"Job {job_id} has no recorded chunking stage; cannot resume extraction. "
                "Run a new extract instead."
            )

        raw_path = get_raw_path(job_id, job.file_name)
        if not raw_path.is_file():
            raise ValueError(
                f"Stored raw file missing for job {job_id}: {raw_path}. "
                "Cannot resume without the copy under the Hermes storage directory."
            )

        normalized_pages = load_normalized_pages_from_store(job_id, job.file_type)
        if not normalized_pages:
            raise ValueError(
                f"No normalized Markdown found under job {job_id}; "
                "cannot resume extraction."
            )

        preflight = run_preflight(raw_path)
        if (
            preflight.file_name != job.file_name
            or preflight.file_type != job.file_type
        ):
            raise ValueError(
                "The file in storage does not match this job's metadata "
                f"({job.file_name!r}, {job.file_type.value}). Refusing to resume."
            )

        schema_ref = job.schema_class
        schema_class = load_schema(schema_ref)
        json_schema = get_json_schema(schema_class)

        chunks = chunk_pages(normalized_pages)
        if len(chunks) != job.total_chunks or job.total_chunks <= 0:
            raise ValueError(
                f"Chunk layout mismatch: job expects {job.total_chunks} chunk(s), "
                f"but rebuilding from stored pages produced {len(chunks)}. "
                "Your extraction config may have changed, or normalized files are incomplete. "
                "Start a new extract with a matching config."
            )

        chunk_dir = get_chunk_dir(job_id)
        for chunk in chunks:
            chunk_path = chunk_dir / f"chunk_{chunk.chunk_index}.md"
            chunk_path.write_text(chunk.text, encoding="utf-8")

        done = get_successful_chunk_indices(conn, job_id)
        pending = [c for c in chunks if c.chunk_index not in done]

        if not pending:
            _sync_job_status_after_extraction(conn, job_id, total_chunks=len(chunks))
            console.print(
                f"[dim]Job {job_id}: all {len(chunks)} chunk(s) already extracted.[/dim]"
            )
            return job_id

        console.print(
            f"[bold]Resume extraction[/bold] for job {job_id}: "
            f"{len(pending)} pending chunk(s) "
            f"({len(done)} already done)."
        )

        update_job_status(conn, job_id, JobStatus.EXTRACTING, total_chunks=len(chunks))

        if job.contract_id:
            contract_id = job.contract_id
        else:
            prompt_ver = get_current_prompt_version()
            contract_id = resolve_or_create_extraction_contract(
                conn, schema_ref, json_schema, prompt_ver
            )
            update_job_contract_id(conn, job_id, contract_id)

        base_completed = len(done)
        base_failed = job.failed_chunks

        ext = _run_extraction_phase(
            conn=conn,
            job_id=job_id,
            contract_id=contract_id,
            work_chunks=pending,
            schema_class=schema_class,
            json_schema=json_schema,
            cfg=cfg,
            model_override=model_override,
            max_workers=max_workers,
            stop_requested=stop_requested,
            base_completed=base_completed,
            base_failed=base_failed,
            progress_total=len(pending),
        )
        if ext is None:
            extraction_start_ns = time.perf_counter_ns()
            extraction_started_at = _now_iso()
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
                    detail="llm provider not reachable (resume)",
                ),
            )
            console.print("[red]LLM provider is not reachable. Aborting.[/red]")
            update_job_status(conn, job_id, JobStatus.FAILED)
            return job_id

        (
            extraction_interrupted,
            sess_completed,
            sess_failed,
            extraction_started_at,
            extraction_start_ns,
        ) = ext
        completed = base_completed + sess_completed
        failed = base_failed + sess_failed

        extraction_duration_ms = _elapsed_ms(extraction_start_ns)
        extraction_ended_at = _now_iso()
        stage_detail = (
            f"resume interrupted; completed_chunks={completed}, failed_chunks={failed}"
            if extraction_interrupted
            else f"resume completed_chunks={completed}, failed_chunks={failed}"
        )
        save_pipeline_stage(
            conn,
            PipelineStage(
                job_id=job_id,
                stage="extraction",
                started_at=extraction_started_at,
                ended_at=extraction_ended_at,
                duration_ms=extraction_duration_ms,
                detail=stage_detail,
            ),
        )

        if extraction_interrupted:
            final_status = JobStatus.PARTIAL if completed > 0 else JobStatus.FAILED
            update_job_status(
                conn,
                job_id,
                final_status,
                completed_chunks=completed,
                failed_chunks=failed,
                completed_at=datetime.now(),
            )
            pending_in_run = max(0, len(pending) - sess_completed - sess_failed)
            console.print(
                f"\n[yellow]Interrupted[/yellow] (SIGINT). Job {job_id}: "
                f"{sess_completed} succeeded, {sess_failed} failed, "
                f"{pending_in_run} not started or in flight in this resume; "
                f"{len(pending)} chunk(s) in this run. "
                f"Status: {final_status.value}"
            )
            return job_id

        if failed == 0:
            final_status = JobStatus.COMPLETED
        elif completed > 0:
            final_status = JobStatus.PARTIAL
        else:
            final_status = JobStatus.FAILED

        update_job_status(
            conn,
            job_id,
            final_status,
            completed_chunks=completed,
            failed_chunks=failed,
            completed_at=datetime.now(),
        )

        console.print(
            f"\n[bold green]Resume done![/bold green] Job {job_id}: "
            f"{completed} chunk(s) extracted total, {failed} failed. "
            f"Status: {final_status.value}"
        )
        return job_id


def _sync_job_status_after_extraction(
    conn: sqlite3.Connection, job_id: str, total_chunks: int
) -> None:
    """Set terminal status when all chunks already have extraction results."""
    row = get_job(conn, job_id)
    if row is None:
        return
    n_ok = len(get_successful_chunk_indices(conn, job_id))
    dlq = get_failed_for_job(conn, job_id)
    if n_ok >= total_chunks and not dlq:
        st = JobStatus.COMPLETED
        failed = 0
    elif n_ok > 0:
        st = JobStatus.PARTIAL
        failed = row.failed_chunks
    else:
        st = JobStatus.FAILED
        failed = row.failed_chunks
    update_job_status(
        conn,
        job_id,
        st,
        completed_chunks=n_ok,
        failed_chunks=failed,
        completed_at=datetime.now(),
    )


def _run_pipeline_inner(
    file_path: Path,
    cfg: HermesConfig,
    schema_ref: str | None,
    model_override: str | None,
    max_workers: int,
    pages_spec: str | None,
    force_new_job: bool,
    stop_requested: threading.Event,
) -> str:
    with open_db() as conn:
        schema_ref = schema_ref or cfg.extraction.default_schema
        pages_spec_stored = pages_spec.strip() if pages_spec else ""
        content_sha256 = sha256_file_hex(file_path)
        llm_model_key = effective_llm_model(cfg, model_override)
        if not force_new_job:
            existing_id = find_completed_dedup_job(
                conn,
                content_sha256,
                schema_ref,
                pages_spec_stored,
                llm_model_key,
            )
            if existing_id:
                console.print(
                    f"[cyan]Reusing completed job[/cyan] [bold]{existing_id}[/bold] "
                    f"[dim](same file content, schema, pages, and model)[/dim]"
                )
                return existing_id

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

        page_indices_0: frozenset[int] | None = None
        if pages_spec is not None and pages_spec.strip():
            if preflight.file_type == FileType.UNKNOWN:
                console.print(
                    "[red]--pages applies only to Excel and PDF files.[/red]"
                )
                raise ValueError("Incompatible --pages option for this file type.")
            try:
                page_indices_0 = resolve_page_indices_0(pages_spec, preflight.page_count)
            except ValueError as e:
                console.print(f"[red]{e}[/red]")
                raise

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
            pages_spec=pages_spec_stored,
            content_sha256=content_sha256,
            llm_model_key=llm_model_key,
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
                detail=_preflight_detail(
                    preflight, page_indices_0
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
            _fail_job(conn, job_id, "normalization", error_msg, failed_at, 0)
            return job_id

        # 4. Normalize
        normalize_started_at = _now_iso()
        normalize_start_ns = time.perf_counter_ns()
        normalize_total = (
            len(page_indices_0)
            if page_indices_0 is not None
            else preflight.page_count
        )
        try:
            if normalize_total > 0:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TaskProgressColumn(),
                    console=console,
                ) as progress:
                    norm_task = progress.add_task("Normalizing", total=normalize_total)

                    def _on_norm_page(_page_idx: int) -> None:
                        progress.advance(norm_task)

                    normalized_pages = route_normalizer(
                        file_path,
                        job_id,
                        preflight,
                        page_indices=page_indices_0,
                        on_page_done=_on_norm_page,
                    )
            else:
                normalized_pages = route_normalizer(
                    file_path,
                    job_id,
                    preflight,
                    page_indices=page_indices_0,
                )
        except Exception as e:
            error_msg = f"Normalization failed: {e}"
            normalize_duration_ms = _elapsed_ms(normalize_start_ns)
            _fail_job(
                conn,
                job_id,
                "normalization",
                error_msg,
                normalize_started_at,
                normalize_duration_ms,
            )
            return job_id

        if not normalized_pages:
            error_msg = "Normalization produced no pages; check --pages or the source file."
            normalize_duration_ms = _elapsed_ms(normalize_start_ns)
            _fail_job(
                conn,
                job_id,
                "normalization",
                error_msg,
                normalize_started_at,
                normalize_duration_ms,
            )
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
                detail=_normalization_detail(
                    preflight, len(normalized_pages), page_indices_0
                ),
            ),
        )

        # 5. Chunk
        console.print("[bold]Chunking...[/bold]")
        chunking_started_at = _now_iso()
        chunking_start_ns = time.perf_counter_ns()
        chunks = chunk_pages(normalized_pages)
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
                detail=f"chunks={len(chunks)}, normalized_pages={len(normalized_pages)}",
            ),
        )
        update_job_status(conn, job_id, JobStatus.EXTRACTING, total_chunks=len(chunks))
        console.print(f"  {len(chunks)} chunk(s) ready")

        # Save chunk texts to disk for DLQ replay
        chunk_dir = get_chunk_dir(job_id)
        for chunk in chunks:
            chunk_path = chunk_dir / f"chunk_{chunk.chunk_index}.md"
            chunk_path.write_text(chunk.text, encoding="utf-8")

        prompt_ver = get_current_prompt_version()
        contract_id = resolve_or_create_extraction_contract(
            conn, schema_ref, json_schema, prompt_ver
        )
        update_job_contract_id(conn, job_id, contract_id)

        # 6. LLM extraction
        ext = _run_extraction_phase(
            conn=conn,
            job_id=job_id,
            contract_id=contract_id,
            work_chunks=chunks,
            schema_class=schema_class,
            json_schema=json_schema,
            cfg=cfg,
            model_override=model_override,
            max_workers=max_workers,
            stop_requested=stop_requested,
            base_completed=0,
            base_failed=0,
            progress_total=len(chunks),
        )
        if ext is None:
            extraction_start_ns = time.perf_counter_ns()
            extraction_started_at = _now_iso()
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
            return job_id

        (
            extraction_interrupted,
            sess_completed,
            sess_failed,
            extraction_started_at,
            extraction_start_ns,
        ) = ext
        completed = sess_completed
        failed = sess_failed

        extraction_duration_ms = _elapsed_ms(extraction_start_ns)
        extraction_ended_at = _now_iso()
        stage_detail = (
            f"interrupted; completed_chunks={completed}, failed_chunks={failed}"
            if extraction_interrupted
            else f"completed_chunks={completed}, failed_chunks={failed}"
        )
        save_pipeline_stage(
            conn,
            PipelineStage(
                job_id=job_id,
                stage="extraction",
                started_at=extraction_started_at,
                ended_at=extraction_ended_at,
                duration_ms=extraction_duration_ms,
                detail=stage_detail,
            ),
        )

        if extraction_interrupted:
            final_status = JobStatus.PARTIAL if completed > 0 else JobStatus.FAILED
            update_job_status(
                conn,
                job_id,
                final_status,
                completed_chunks=completed,
                failed_chunks=failed,
                completed_at=datetime.now(),
            )
            pending_in_run = max(0, len(chunks) - sess_completed - sess_failed)
            console.print(
                f"\n[yellow]Interrupted[/yellow] (SIGINT). Job {job_id}: "
                f"{sess_completed} succeeded, {sess_failed} failed, "
                f"{pending_in_run} not started or in flight; "
                f"{len(chunks)} chunk(s) total. Status: {final_status.value}"
            )
            return job_id

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
        return job_id


def _run_extraction_phase(
    conn: sqlite3.Connection,
    job_id: str,
    contract_id: str,
    work_chunks: list[Chunk],
    schema_class: type[Any],
    json_schema: dict[str, Any],
    cfg: HermesConfig,
    model_override: str | None,
    max_workers: int,
    stop_requested: threading.Event,
    base_completed: int,
    base_failed: int,
    progress_total: int,
) -> tuple[bool, int, int, str, int] | None:
    """Run LLM extraction for ``work_chunks``. Returns ``None`` if the LLM is unreachable.

    Session counters in the return tuple are **this run only**; callers combine with
    ``base_completed`` / ``base_failed`` for persisted job totals.
    """
    extraction_started_at = _now_iso()
    extraction_start_ns = time.perf_counter_ns()
    llm_client = create_llm_client(cfg)
    if model_override:
        if hasattr(llm_client, "model"):
            setattr(llm_client, "model", model_override)

    if not llm_client.check_ready():
        return None

    prompt_ver = get_current_prompt_version()
    max_retries = cfg.llm.max_retries
    sess_completed = 0
    sess_failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Extracting", total=progress_total)

        if max_workers > 1:
            executor = ThreadPoolExecutor(max_workers=max_workers)
            futures: dict[Any, Chunk] = {}
            chunk_idx = 0
            n_chunks = len(work_chunks)

            def _submit_pending() -> None:
                nonlocal chunk_idx
                while (
                    chunk_idx < n_chunks
                    and len(futures) < max_workers
                    and not stop_requested.is_set()
                ):
                    c = work_chunks[chunk_idx]
                    chunk_idx += 1
                    fut = executor.submit(
                        _process_chunk,
                        llm_client,
                        c,
                        job_id,
                        contract_id,
                        schema_class,
                        json_schema,
                        prompt_ver,
                        max_retries,
                    )
                    futures[fut] = c

            try:
                _submit_pending()
                while futures:
                    if stop_requested.is_set():
                        break
                    done_set, _ = wait(futures.keys(), return_when=FIRST_COMPLETED)
                    for fut in done_set:
                        futures.pop(fut)
                        try:
                            success = fut.result()
                            if success:
                                sess_completed += 1
                            else:
                                sess_failed += 1
                        except Exception as exc:
                            sess_failed += 1
                            logger.error(
                                "Chunk processing generated an exception: %s", exc
                            )

                        update_job_status(
                            conn,
                            job_id,
                            JobStatus.EXTRACTING,
                            completed_chunks=base_completed + sess_completed,
                            failed_chunks=base_failed + sess_failed,
                        )
                        progress.advance(task)
                    _submit_pending()
                    if stop_requested.is_set():
                        break
            finally:
                if stop_requested.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                else:
                    executor.shutdown(wait=True)
        else:
            for chunk in work_chunks:
                if stop_requested.is_set():
                    break
                success = _process_chunk(
                    llm_client,
                    chunk,
                    job_id,
                    contract_id,
                    schema_class,
                    json_schema,
                    prompt_ver,
                    max_retries,
                )
                if success:
                    sess_completed += 1
                else:
                    sess_failed += 1

                update_job_status(
                    conn,
                    job_id,
                    JobStatus.EXTRACTING,
                    completed_chunks=base_completed + sess_completed,
                    failed_chunks=base_failed + sess_failed,
                )
                progress.advance(task)

    extraction_interrupted = stop_requested.is_set()
    return (
        extraction_interrupted,
        sess_completed,
        sess_failed,
        extraction_started_at,
        extraction_start_ns,
    )


def _preflight_detail(
    preflight: PreflightResult,
    page_indices_0: frozenset[int] | None,
) -> str:
    base = (
        f"type={preflight.file_type.value}, pages={preflight.page_count}, "
        f"est_tokens={preflight.estimated_tokens}"
    )
    if page_indices_0 is not None:
        return f"{base}, page_filter={len(page_indices_0)} of {preflight.page_count}"
    return base


def _normalization_detail(
    preflight: PreflightResult,
    normalized_count: int,
    page_indices_0: frozenset[int] | None,
) -> str:
    base = (
        f"normalized_pages={normalized_count}, source={preflight.file_type.value}"
    )
    if page_indices_0 is not None:
        return (
            f"{base}, subset_of_total={preflight.page_count}, "
            f"page_filter={len(page_indices_0)}"
        )
    return base


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _elapsed_ms(start_ns: int) -> int:
    elapsed_ns = time.perf_counter_ns() - start_ns
    return int(elapsed_ns / 1_000_000)


def _fail_job(
    conn: sqlite3.Connection,
    job_id: str,
    stage_name: str,
    error_msg: str,
    started_at: str,
    duration_ms: int,
) -> None:
    ended_at = _now_iso()
    save_pipeline_stage(
        conn,
        PipelineStage(
            job_id=job_id,
            stage=stage_name,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            detail=error_msg,
        ),
    )
    update_job_status(conn, job_id, JobStatus.FAILED, normalization_error=error_msg)
    console.print(f"[red]{error_msg}[/red]")


def _process_chunk(
    llm_client: BaseLLMClient,
    chunk: Chunk,
    job_id: str,
    contract_id: str,
    schema_class: type[Any],
    json_schema: dict[str, Any],
    prompt_version: str,
    max_retries: int,
) -> bool:
    """Process a single chunk: call LLM, validate, persist. Returns True on success."""
    with open_connection() as conn:
        user_prompt = build_user_prompt(json_schema, chunk.text)

        try:
            llm_response = llm_client.chat(SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            logger.error("LLM call failed for chunk %d: %s", chunk.chunk_index, e)
            _save_failure(conn, job_id, chunk, str(e), 0, commit=False)
            conn.commit()
            return False

        result = validate_with_repair(
            llm_response, schema_class, json_schema, llm_client, max_retries
        )

        for i, resp in enumerate(result.all_responses):
            is_last = i == len(result.all_responses) - 1
            run = LLMRun(
                job_id=job_id,
                contract_id=contract_id,
                chunk_index=chunk.chunk_index,
                run_type="extraction" if i == 0 else "repair",
                model=resp.model,
                prompt_version=prompt_version,
                tokens_in=resp.tokens_in,
                tokens_out=resp.tokens_out,
                total_latency_ms=resp.latency_ms,
                validation_passed=is_last and not result.error,
                validation_error=result.error if is_last else "",
                raw_output=resp.content,
            )
            save_llm_run(conn, run, commit=False)

        if not result.error:
            records_json = json.dumps(
                [r.model_dump(mode="json") for r in result.validated]
            )
            source_pages = ",".join(str(p) for p in chunk.source_pages)
            extraction = ExtractionResult(
                job_id=job_id,
                contract_id=contract_id,
                chunk_index=chunk.chunk_index,
                source_pages=source_pages,
                record_json=records_json,
                model=llm_response.model,
                prompt_version=prompt_version,
            )
            save_result(conn, extraction, commit=False)

        if result.error and not result.validated:
            _save_failure(
                conn, job_id, chunk, result.error, result.attempts, commit=False
            )
            conn.commit()
            return False

        conn.commit()
        return True



def _save_failure(
    conn: sqlite3.Connection,
    job_id: str,
    chunk: Chunk,
    error: str,
    retry_count: int,
    *,
    commit: bool = True,
) -> None:
    chunk_uri = f"chunks/chunk_{chunk.chunk_index}.md"
    fail = FailedExtraction(
        job_id=job_id,
        chunk_index=chunk.chunk_index,
        chunk_text_uri=chunk_uri,
        last_error=error,
        retry_count=retry_count,
    )
    save_failed(conn, fail, commit=commit)
