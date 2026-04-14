"""Hermes CLI — Typer application with all commands."""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import shutil
import sqlite3
import sys
from itertools import chain
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hermes import __version__

app = typer.Typer(
    name="hermes",
    help="Local-first, memory-safe, LLM-powered document extraction engine.",
    no_args_is_help=True,
)
console = Console()

SUPPORTED_EXTENSIONS = {".xlsx", ".xlsm", ".xltx", ".xltm", ".pdf"}


@app.callback()
def main(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable debug logging."
    ),
) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level, format="%(name)s %(levelname)s: %(message)s"
    )


def app_entry() -> None:
    app()


@app.command()
def extract(
    path: Path | None = typer.Argument(
        None,
        help="File or directory to extract from (omit when using --resume).",
    ),
    schema: str = typer.Option(
        "", "--schema", "-s",
        help=(
            "Pydantic schema as module:Class "
            "(e.g. hermes_user.examples.vehicle_fleet:VehicleRecord "
            "or hermes.schemas.examples.vehicle_fleet:VehicleRecord)."
        ),
    ),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model name."),
    workers: int = typer.Option(
        1,
        "--workers",
        "-w",
        help="Number of concurrent workers for LLM extraction.",
    ),
    pages: str = typer.Option(
        "",
        "--pages",
        help=(
            "Optional subset to normalize and extract, using 1-based indices. "
            "For PDFs, page numbers (e.g. 1-10 or 3,5,7). "
            "For Excel, sheet indices only (first sheet is 1), not rows. "
            "Omit to process the whole document."
        ),
    ),
    resume: str = typer.Option(
        "",
        "--resume",
        help=(
            "Resume LLM extraction for an existing job id after interrupt or crash "
            "(requires prior chunking; uses stored raw + normalized files)."
        ),
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help=(
            "Always create a new job; do not reuse a completed job for the same file "
            "content, schema, pages, and model."
        ),
    ),
) -> None:
    """Extract structured data from documents using an LLM."""
    from hermes.extraction.pipeline import resume_pipeline, run_pipeline

    resume_id = resume.strip()
    if resume_id:
        if path is not None:
            console.print(
                "[yellow]Ignoring PATH when --resume is set "
                "(source file is read from Hermes storage).[/yellow]"
            )
        try:
            resume_pipeline(
                resume_id,
                model_override=model or None,
                max_workers=workers,
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        return

    if path is None:
        console.print(
            "[red]Missing path: provide a file or directory, or use --resume JOB_ID.[/red]"
        )
        raise typer.Exit(1)

    if not path.exists():
        console.print(f"[red]Path not found:[/red] {path}")
        raise typer.Exit(1)

    files: list[Path] = []
    if path.is_dir():
        for f in sorted(path.iterdir()):
            if f.suffix.lower() in SUPPORTED_EXTENSIONS:
                files.append(f)
        if not files:
            console.print(f"[yellow]No supported files found in {path}[/yellow]")
            raise typer.Exit(1)
        console.print(f"[bold]Found {len(files)} file(s) in {path}[/bold]")
    else:
        files = [path]

    for file in files:
        console.rule(f"[bold]{file.name}[/bold]")
        try:
            run_pipeline(
                file,
                schema_ref=schema or None,
                model_override=model or None,
                max_workers=workers,
                pages_spec=pages.strip() or None,
                force_new_job=force,
            )
        except Exception as e:
            console.print(f"[red]Error processing {file.name}:[/red] {e}")


@app.command()
def test(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help=(
            "Always run a full extraction for each fixture. Without this flag, a prior "
            "completed job for the same file content (same schema, pages, and model) may "
            "be reused."
        ),
    ),
) -> None:
    """Run standard test datasets with telemetry output."""
    import time

    from hermes.config import load_config
    from hermes.db import get_llm_runs_for_job, get_stages_for_job, open_db
    from hermes.extraction.pipeline import run_pipeline

    excel_file = Path("test_excel_accuracy_synthetic.xlsx")
    pdf_file = Path("test_pdf_stress_riscbac.pdf")

    if not excel_file.exists() or not pdf_file.exists():
        console.print(
            "[red]Test files not found! Run generate_test_datasets.py first.[/red]"
        )
        raise typer.Exit(1)

    cfg = load_config()
    is_cloud = cfg.llm.provider == "litellm"
    workers = 4 if is_cloud else 1
    mode_label = "cloud/parallel" if is_cloud else "local/sequential"

    schema = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"

    console.print(
        f"[bold blue]Hermes Test Suite[/bold blue]  "
        f"provider=[bold]{cfg.llm.provider}[/bold]  "
        f"model=[bold]{cfg.llm.model if not is_cloud else cfg.llm.litellm.model}[/bold]  "
        f"mode=[bold]{mode_label}[/bold]  workers=[bold]{workers}[/bold]  "
        f"thinking=[bold]{'on' if cfg.llm.enable_thinking else 'off'}[/bold]"
    )

    jobs: list[tuple[str, str, float]] = []

    # ── Test 1: Excel Accuracy ────────────────────────────────────────
    console.rule("[bold cyan]Test 1: Excel Accuracy & Stream Extraction[/bold cyan]")
    start = time.perf_counter()
    try:
        job_id = run_pipeline(
            excel_file,
            schema_ref=schema,
            max_workers=workers,
            force_new_job=force,
        )
        jobs.append(("Excel Accuracy", job_id, time.perf_counter() - start))
    except Exception as e:
        console.print(f"[red]Excel test failed:[/red] {e}")

    # ── Test 2: PDF Stress ────────────────────────────────────────────
    console.rule("[bold cyan]Test 2: PDF Stress Test & Chunking[/bold cyan]")
    start = time.perf_counter()
    try:
        job_id = run_pipeline(
            pdf_file,
            schema_ref=schema,
            max_workers=workers,
            force_new_job=force,
        )
        jobs.append(("PDF Stress", job_id, time.perf_counter() - start))
    except Exception as e:
        console.print(f"[red]PDF test failed:[/red] {e}")

    # ── Telemetry Report ──────────────────────────────────────────────
    console.rule("[bold magenta]Test Suite Telemetry & Stats[/bold magenta]")
    with open_db() as conn:
        suite_wall = sum(e for _, _, e in jobs)
        suite_tokens_in = 0
        suite_tokens_out = 0
        suite_llm_runs = 0

        for test_name, job_id, elapsed in jobs:
            console.print(
                f"\n[bold]{test_name}[/bold]  job=[dim]{job_id}[/dim]  "
                f"wall=[bold]{elapsed:.2f}s[/bold]"
            )

            # Stage breakdown
            stages = get_stages_for_job(conn, job_id)
            stage_table = Table(title="Pipeline Stages", show_edge=False)
            stage_table.add_column("Stage", style="bold")
            stage_table.add_column("Duration", justify="right")
            stage_table.add_column("Detail")
            for stage in stages:
                stage_table.add_row(stage.stage, f"{stage.duration_ms}ms", stage.detail)
            console.print(stage_table)

            # LLM run aggregates
            runs = get_llm_runs_for_job(conn, job_id)
            if runs:
                tokens_in = sum(r.tokens_in for r in runs)
                tokens_out = sum(r.tokens_out for r in runs)
                total_latency = sum(r.total_latency_ms for r in runs)
                repairs = sum(1 for r in runs if r.run_type == "repair")
                failures = sum(1 for r in runs if not r.validation_passed)
                latencies = [r.total_latency_ms for r in runs]

                suite_tokens_in += tokens_in
                suite_tokens_out += tokens_out
                suite_llm_runs += len(runs)

                run_table = Table(title="LLM Stats", show_edge=False)
                run_table.add_column("Metric", style="bold")
                run_table.add_column("Value", justify="right")
                run_table.add_row("LLM Calls", str(len(runs)))
                run_table.add_row("Repair Attempts", str(repairs))
                run_table.add_row("Tokens In", f"{tokens_in:,}")
                run_table.add_row("Tokens Out", f"{tokens_out:,}")
                run_table.add_row("Total LLM Time", f"{total_latency:,}ms")
                run_table.add_row("Avg Latency/call", f"{total_latency / len(runs):,.0f}ms")
                run_table.add_row("Min Latency", f"{min(latencies):,}ms")
                run_table.add_row("Max Latency", f"{max(latencies):,}ms")
                run_table.add_row("Validation Failures", str(failures))
                console.print(run_table)

        # Suite-wide summary
        console.rule("[bold green]Suite Summary[/bold green]")
        summary = Table(show_edge=False, show_header=False)
        summary.add_column(style="bold")
        summary.add_column(justify="right")
        summary.add_row("Provider", cfg.llm.provider)
        summary.add_row("Concurrency Mode", mode_label)
        summary.add_row("Workers", str(workers))
        summary.add_row("Tests Run", str(len(jobs)))
        summary.add_row("Total Wall Time", f"{suite_wall:.2f}s")
        summary.add_row("Total LLM Calls", str(suite_llm_runs))
        summary.add_row("Total Tokens In", f"{suite_tokens_in:,}")
        summary.add_row("Total Tokens Out", f"{suite_tokens_out:,}")
        console.print(summary)


@app.command()
def status(
    job_id: str = typer.Argument("", help="Job ID to inspect. Omit for all jobs."),
) -> None:
    """Show job status."""
    from hermes.db import (
        get_job,
        get_llm_runs_for_job,
        get_stages_for_job,
        list_jobs,
        open_db,
    )

    with open_db() as conn:
        if job_id:
            job = get_job(conn, job_id)
            if not job:
                console.print(f"[red]Job not found:[/red] {job_id}")
                raise typer.Exit(1)

            table = Table(title=f"Job {job.id}")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("File", job.file_name)
            table.add_row("Type", job.file_type.value)
            table.add_row("Pages", str(job.page_count))
            table.add_row("Schema", job.schema_class)
            table.add_row(
                "Contract",
                job.contract_id if job.contract_id else "[dim]-[/dim]",
            )
            if job.normalization_error:
                table.add_row("Normalization Error", job.normalization_error)
            table.add_row("Status", _status_color(job.status.value))
            chunks_str = (
                f"{job.completed_chunks}/{job.total_chunks} completed, "
                f"{job.failed_chunks} failed"
            )
            table.add_row("Chunks", chunks_str)
            table.add_row("Created", str(job.created_at or ""))
            table.add_row("Completed", str(job.completed_at or "-"))
            console.print(table)

            runs = get_llm_runs_for_job(conn, job_id)
            if runs:
                run_table = Table(title="LLM Runs")
                run_table.add_column("Chunk")
                run_table.add_column("Type")
                run_table.add_column("Model")
                run_table.add_column("Tokens In")
                run_table.add_column("Tokens Out")
                run_table.add_column("Latency")
                run_table.add_column("Valid")
                for r in runs:
                    run_table.add_row(
                        str(r.chunk_index), r.run_type, r.model,
                        str(r.tokens_in), str(r.tokens_out),
                        f"{r.total_latency_ms}ms",
                        "[green]Yes[/green]" if r.validation_passed else "[red]No[/red]",
                    )
                console.print(run_table)

            stages = get_stages_for_job(conn, job_id)
            if stages:
                stage_table = Table(title="Pipeline Stages")
                stage_table.add_column("Stage")
                stage_table.add_column("Duration (ms)")
                stage_table.add_column("Detail")
                stage_table.add_column("Started")
                stage_table.add_column("Ended")

                for stage in stages:
                    stage_table.add_row(
                        stage.stage,
                        str(stage.duration_ms),
                        stage.detail,
                        stage.started_at,
                        stage.ended_at,
                    )
                console.print(stage_table)
        else:
            jobs = list_jobs(conn)
            if not jobs:
                console.print("[dim]No jobs found.[/dim]")
                return

            table = Table(title="All Jobs")
            table.add_column("ID", style="bold")
            table.add_column("File")
            table.add_column("Type")
            table.add_column("Contract")
            table.add_column("Status")
            table.add_column("Chunks")
            table.add_column("Errors")
            table.add_column("Created")

            for job in jobs:
                table.add_row(
                    job.id, job.file_name, job.file_type.value,
                    _format_contract_list_cell(job.contract_id),
                    _status_color(job.status.value),
                    f"{job.completed_chunks}/{job.total_chunks}",
                    str(job.failed_chunks),
                    str(job.created_at or ""),
                )
            console.print(table)


@app.command()
def retry(
    job_id: str = typer.Argument("", help="Job ID to retry. Omit for all pending DLQ items."),
    schema: str = typer.Option("", "--schema", "-s", help="Override schema for retry."),
    model: str = typer.Option("", "--model", "-m", help="Override model for retry."),
) -> None:
    """Replay failed extractions from the dead-letter queue."""
    from hermes.config import get_storage_base, load_config
    from hermes.db import (
        count_distinct_extraction_chunk_indices,
        get_failed_for_job,
        get_job,
        open_db,
        resolve_or_create_extraction_contract,
        save_llm_run,
        save_result,
        update_failed_status,
        update_job_contract_id,
        update_job_status,
    )
    from hermes.extraction.llm_client import create_llm_client
    from hermes.extraction.prompts import (
        SYSTEM_PROMPT,
        build_user_prompt,
        get_current_prompt_version,
    )
    from hermes.extraction.validator import validate_with_repair
    from hermes.models import DLQStatus, ExtractionResult, JobStatus, LLMRun
    from hermes.schemas.loader import get_json_schema, load_schema

    cfg = load_config()

    with open_db() as conn:
        failures = get_failed_for_job(conn, job_id or None)
        if not failures:
            console.print("[dim]No pending failures to retry.[/dim]")
            return

        console.print(f"[bold]Retrying {len(failures)} failed chunk(s)...[/bold]")

        llm_client = create_llm_client(cfg)
        if model:
            if hasattr(llm_client, "model"):
                setattr(llm_client, "model", model)

        if not llm_client.check_ready():
            console.print("[red]LLM provider is not reachable.[/red]")
            raise typer.Exit(1)

        prompt_ver = get_current_prompt_version()
        replayed = 0

        for fail in failures:
            job = get_job(conn, fail.job_id)
            if not job:
                continue

            schema_ref = schema or job.schema_class
            schema_class = load_schema(schema_ref)
            json_schema = get_json_schema(schema_class)
            contract_id = resolve_or_create_extraction_contract(
                conn, schema_ref, json_schema, prompt_ver
            )
            update_job_contract_id(conn, fail.job_id, contract_id)

            storage_base = get_storage_base()
            chunk_path = storage_base / fail.job_id / fail.chunk_text_uri
            if not chunk_path.exists():
                msg = (
                    f"[yellow]Chunk file missing for job {fail.job_id}, "
                    f"chunk {fail.chunk_index}[/yellow]"
                )
                console.print(msg)
                continue

            chunk_text = chunk_path.read_text(encoding="utf-8")
            user_prompt = build_user_prompt(json_schema, chunk_text)

            try:
                llm_response = llm_client.chat(SYSTEM_PROMPT, user_prompt)
            except Exception as e:
                console.print(f"[red]LLM call failed:[/red] {e}")
                continue

            result = validate_with_repair(
                llm_response, schema_class, json_schema, llm_client, cfg.llm.max_retries
            )

            for i, resp in enumerate(result.all_responses):
                is_last = i == len(result.all_responses) - 1
                run = LLMRun(
                    job_id=fail.job_id,
                    contract_id=contract_id,
                    chunk_index=fail.chunk_index,
                    run_type="retry" if i == 0 else "repair",
                    model=resp.model, prompt_version=prompt_ver,
                    tokens_in=resp.tokens_in, tokens_out=resp.tokens_out,
                    total_latency_ms=resp.latency_ms,
                    validation_passed=is_last and bool(result.validated) and not result.error,
                    validation_error=result.error if is_last else "",
                    raw_output=resp.content,
                )
                save_llm_run(conn, run)

            if result.validated:
                import json as _json
                records_json = _json.dumps([r.model_dump(mode="json") for r in result.validated])
                extraction = ExtractionResult(
                    job_id=fail.job_id,
                    contract_id=contract_id,
                    chunk_index=fail.chunk_index,
                    source_pages="", record_json=records_json,
                    model=llm_response.model, prompt_version=prompt_ver,
                )
                save_result(conn, extraction)
                if fail.id is not None:
                    update_failed_status(conn, fail.id, DLQStatus.REPLAYED)
                replayed += 1
                console.print(f"  [green]Chunk {fail.chunk_index} replayed successfully[/green]")
            else:
                err = result.error
                console.print(
                    f"  [red]Chunk {fail.chunk_index} still failing: {err}[/red]"
                )

        console.print(f"\n[bold]{replayed}/{len(failures)} chunk(s) replayed successfully.[/bold]")

        for jid in {f.job_id for f in failures}:
            job = get_job(conn, jid)
            if not job:
                continue
            total_pending = len(get_failed_for_job(conn, jid))
            if job.status not in (JobStatus.PARTIAL, JobStatus.FAILED):
                continue
            if total_pending != 0:
                continue
            chunks_with_results = count_distinct_extraction_chunk_indices(conn, jid)
            if job.total_chunks > 0 and chunks_with_results == job.total_chunks:
                update_job_status(
                    conn,
                    jid,
                    JobStatus.COMPLETED,
                    completed_chunks=job.total_chunks,
                    failed_chunks=0,
                )
            elif job.total_chunks > 0 and chunks_with_results < job.total_chunks:
                console.print(
                    f"[yellow]Job {jid}: DLQ is empty but only "
                    f"{chunks_with_results}/{job.total_chunks} chunk(s) have extraction "
                    f"results (e.g. interrupted run). Job status left unchanged.[/yellow]"
                )


@app.command(name="export")
def export_cmd(
    job_id: str = typer.Argument(..., help="Job ID to export."),
    format: str = typer.Option("jsonl", "--format", "-f", help="Output format: jsonl or csv."),
    output: Path = typer.Option(
        None, "--output", "-o",
        help="Output file path. Defaults to stdout.",
    ),
) -> None:
    """Export extracted records as JSONL or CSV."""
    from hermes.db import export_results_as_records, open_db

    if format not in ("jsonl", "csv"):
        console.print(f"[red]Unknown format:[/red] {format}. Use 'jsonl' or 'csv'.")
        raise typer.Exit(1)

    with open_db() as conn:
        records_iter = export_results_as_records(conn, job_id)
        try:
            first = next(records_iter)
        except StopIteration:
            console.print(f"[yellow]No records found for job {job_id}[/yellow]")
            raise typer.Exit(1)

        out_cm = (
            output.open("w", encoding="utf-8")
            if output
            else contextlib.nullcontext(sys.stdout)
        )
        with out_cm as out_f:
            if format == "jsonl":
                count = 0
                for rec in chain([first], records_iter):
                    count += 1
                    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            else:
                fieldnames = list(first.keys())
                writer = csv.DictWriter(out_f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(first)
                count = 1
                for rec in records_iter:
                    count += 1
                    writer.writerow(rec)

    if output:
        console.print(f"[green]Exported {count} records to {output}[/green]")


@app.command()
def init() -> None:
    """Initialize Hermes config directory and default configuration."""
    from hermes.user_schemas import (
        DEFAULT_USER_SCHEMA_REF,
        install_example_schemas_if_missing,
    )

    hermes_dir = Path.home() / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)

    config_dest = hermes_dir / "config.toml"
    if not config_dest.exists():
        example = Path(__file__).parent.parent / "config.toml.example"
        if example.exists():
            shutil.copy2(example, config_dest)
            text = config_dest.read_text(encoding="utf-8")
            text = text.replace(
                'default_schema = "hermes.schemas.examples.generic_table:GenericRow"',
                f'default_schema = "{DEFAULT_USER_SCHEMA_REF}"',
            )
            config_dest.write_text(text, encoding="utf-8")
            console.print(f"[green]Created config:[/green] {config_dest}")
        else:
            console.print("[yellow]config.toml.example not found, creating minimal config[/yellow]")
            default_config = (
                '[llm]\nprovider = "ollama"\nmodel = "qwen3:4b"\n\n'
                '[storage]\nbase_path = "~/.hermes/storage"\n\n'
                f'[extraction]\ndefault_schema = "{DEFAULT_USER_SCHEMA_REF}"\n'
            )
            config_dest.write_text(default_config, encoding="utf-8")
            console.print(f"[green]Created config:[/green] {config_dest}")
    else:
        console.print(f"[dim]Config already exists:[/dim] {config_dest}")

    written = install_example_schemas_if_missing(hermes_dir)
    for p in written:
        console.print(f"[green]Installed example schema:[/green] {p}")
    examples_root = hermes_dir / "hermes_user" / "examples"
    if examples_root.exists():
        console.print(
            "[dim]Use --schema hermes_user.examples.vehicle_fleet:VehicleRecord "
            "or hermes_user.examples.generic_table:GenericRow (after init; files are "
            "created only if missing).[/dim]"
        )

    from hermes.db import open_db

    with open_db():
        pass
    console.print("[green]Database initialized.[/green]")
    console.print("[bold]Hermes is ready.[/bold]")


@app.command()
def version() -> None:
    """Show Hermes version."""
    console.print(f"Hermes v{__version__}")


@app.command("list-schemas")
def list_schemas_cmd(
    no_packaged: bool = typer.Option(
        False,
        "--no-packaged",
        help="Do not list bundled hermes.schemas.examples.* models.",
    ),
    no_user: bool = typer.Option(
        False,
        "--no-user",
        help="Do not list models under ~/.hermes/hermes_user/.",
    ),
) -> None:
    """Print module:Class references usable with --schema."""
    from hermes.schemas.discover import list_schema_refs

    refs, errors = list_schema_refs(
        include_packaged=not no_packaged,
        include_user=not no_user,
    )
    err_out = Console(stderr=True)
    for msg in errors:
        err_out.print(f"[yellow]Skipping:[/yellow] {msg}")
    for line in refs:
        console.print(line)


@app.command()
def clean(
    job_id: str | None = typer.Argument(
        None,
        metavar="JOB_ID",
        help="Job ID to remove. Omit when using --all.",
    ),
    all_jobs: bool = typer.Option(
        False,
        "--all",
        help="Remove every job's on-disk storage and database rows.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation (for non-interactive use).",
    ),
) -> None:
    """Remove a job's storage directory and all related database rows."""
    from hermes.config import get_storage_base
    from hermes.db import delete_job, get_job, list_jobs, open_db

    if job_id and all_jobs:
        console.print("[red]Specify either JOB_ID or --all, not both.[/red]")
        raise typer.Exit(1)
    if not job_id and not all_jobs:
        console.print("[red]Provide a JOB_ID or use --all.[/red]")
        raise typer.Exit(1)

    storage_base = get_storage_base()

    with open_db() as conn:
        if all_jobs:
            jobs = list_jobs(conn)
            if not jobs:
                console.print("[dim]No jobs to clean.[/dim]")
                return
            target_ids = [j.id for j in jobs]
            prompt = (
                f"Delete all {len(target_ids)} job(s) and their files under "
                f"{storage_base}?"
            )
        else:
            assert job_id is not None
            job = get_job(conn, job_id)
            if not job:
                console.print(f"[red]Job not found:[/red] {job_id}")
                raise typer.Exit(1)
            target_ids = [job_id]
            prompt = (
                f"Delete job {job_id!r} and remove its storage and database rows?"
            )

    if not force and not typer.confirm(prompt):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    removed = 0
    errors: list[str] = []
    with open_db() as conn:
        for jid in target_ids:
            job_dir = storage_base / jid
            try:
                if job_dir.exists():
                    shutil.rmtree(job_dir)
            except OSError as e:
                errors.append(f"{jid} (storage): {e}")
            try:
                delete_job(conn, jid)
                removed += 1
            except sqlite3.Error as e:
                errors.append(f"{jid} (database): {e}")

    if removed:
        console.print(
            f"[green]Removed {removed} job(s) from the database"
            + (" and deleted on-disk data where possible." if not errors else ".")
            + "[/green]"
        )
    for err in errors:
        console.print(f"[yellow]Warning:[/yellow] {err}")


_CONTRACT_LIST_MAX_LEN = 28


def _format_contract_list_cell(contract_id: str | None) -> str:
    if not contract_id:
        return "-"
    if len(contract_id) <= _CONTRACT_LIST_MAX_LEN:
        return contract_id
    return contract_id[: _CONTRACT_LIST_MAX_LEN - 1] + "…"


def _status_color(status: str) -> str:
    colors = {
        "queued": "[dim]queued[/dim]",
        "normalizing": "[blue]normalizing[/blue]",
        "extracting": "[cyan]extracting[/cyan]",
        "completed": "[green]completed[/green]",
        "partial": "[yellow]partial[/yellow]",
        "failed": "[red]failed[/red]",
    }
    return colors.get(status, status)
