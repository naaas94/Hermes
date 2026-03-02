"""Hermes CLI — Typer application with all commands."""

from __future__ import annotations

import csv
import io
import json
import shutil
import sys
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


def app_entry() -> None:
    app()


@app.command()
def extract(
    path: Path = typer.Argument(..., help="File or directory to extract from."),
    schema: str = typer.Option(
        "", "--schema", "-s",
        help=(
            "Pydantic schema as module:Class "
            "(e.g. hermes.schemas.examples.vehicle_fleet:VehicleRecord)."
        ),
    ),
    model: str = typer.Option("", "--model", "-m", help="Override LLM model name."),
    workers: int = typer.Option(1, "--workers", "-w", help="Number of concurrent workers for LLM extraction."),
) -> None:
    """Extract structured data from documents using an LLM."""
    from hermes.extraction.pipeline import run_pipeline

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
            )
        except Exception as e:
            console.print(f"[red]Error processing {file.name}:[/red] {e}")


@app.command()
def test() -> None:
    """Run standard test datasets with telemetry output."""
    import time

    from hermes.config import load_config
    from hermes.db import get_llm_runs_for_job, get_stages_for_job, init_db
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
        f"mode=[bold]{mode_label}[/bold]  workers=[bold]{workers}[/bold]"
        f"thinking=[bold]{'on' if cfg.llm.enable_thinking else 'off'}[/bold]"
    )

    jobs: list[tuple[str, str, float]] = []

    # ── Test 1: Excel Accuracy ────────────────────────────────────────
    console.rule("[bold cyan]Test 1: Excel Accuracy & Stream Extraction[/bold cyan]")
    start = time.perf_counter()
    try:
        job_id = run_pipeline(excel_file, schema_ref=schema, max_workers=workers)
        jobs.append(("Excel Accuracy", job_id, time.perf_counter() - start))
    except Exception as e:
        console.print(f"[red]Excel test failed:[/red] {e}")

    # ── Test 2: PDF Stress ────────────────────────────────────────────
    console.rule("[bold cyan]Test 2: PDF Stress Test & Chunking[/bold cyan]")
    start = time.perf_counter()
    try:
        job_id = run_pipeline(pdf_file, schema_ref=schema, max_workers=workers)
        jobs.append(("PDF Stress", job_id, time.perf_counter() - start))
    except Exception as e:
        console.print(f"[red]PDF test failed:[/red] {e}")

    # ── Telemetry Report ──────────────────────────────────────────────
    console.rule("[bold magenta]Test Suite Telemetry & Stats[/bold magenta]")
    conn = init_db()

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

    conn.close()


@app.command()
def status(
    job_id: str = typer.Argument("", help="Job ID to inspect. Omit for all jobs."),
) -> None:
    """Show job status."""
    from hermes.db import (
        get_job,
        get_llm_runs_for_job,
        get_stages_for_job,
        init_db,
        list_jobs,
    )

    conn = init_db()

    if job_id:
        job = get_job(conn, job_id)
        if not job:
            console.print(f"[red]Job not found:[/red] {job_id}")
            conn.close()
            raise typer.Exit(1)

        table = Table(title=f"Job {job.id}")
        table.add_column("Field", style="bold")
        table.add_column("Value")
        table.add_row("File", job.file_name)
        table.add_row("Type", job.file_type.value)
        table.add_row("Pages", str(job.page_count))
        table.add_row("Schema", job.schema_class)
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
            conn.close()
            return

        table = Table(title="All Jobs")
        table.add_column("ID", style="bold")
        table.add_column("File")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Chunks")
        table.add_column("Errors")
        table.add_column("Created")

        for job in jobs:
            table.add_row(
                job.id, job.file_name, job.file_type.value,
                _status_color(job.status.value),
                f"{job.completed_chunks}/{job.total_chunks}",
                str(job.failed_chunks),
                str(job.created_at or ""),
            )
        console.print(table)

    conn.close()


@app.command()
def retry(
    job_id: str = typer.Argument("", help="Job ID to retry. Omit for all pending DLQ items."),
    schema: str = typer.Option("", "--schema", "-s", help="Override schema for retry."),
    model: str = typer.Option("", "--model", "-m", help="Override model for retry."),
) -> None:
    """Replay failed extractions from the dead-letter queue."""
    from hermes.config import get_storage_base, load_config
    from hermes.db import (
        get_failed_for_job,
        get_job,
        init_db,
        save_llm_run,
        save_result,
        update_failed_status,
    )
    from hermes.extraction.llm_client import create_llm_client
    from hermes.extraction.prompts import (
        SYSTEM_PROMPT,
        build_user_prompt,
        get_current_prompt_version,
    )
    from hermes.extraction.validator import validate_with_repair
    from hermes.models import DLQStatus, ExtractionResult, LLMRun
    from hermes.schemas.loader import get_json_schema, load_schema

    cfg = load_config()
    conn = init_db()

    failures = get_failed_for_job(conn, job_id or None)
    if not failures:
        console.print("[dim]No pending failures to retry.[/dim]")
        conn.close()
        return

    console.print(f"[bold]Retrying {len(failures)} failed chunk(s)...[/bold]")

    llm_client = create_llm_client(cfg)
    if model:
        if hasattr(llm_client, "model"):
            llm_client.model = model  # type: ignore[attr-defined]

    if not llm_client.check_ready():
        console.print("[red]LLM provider is not reachable.[/red]")
        conn.close()
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
                job_id=fail.job_id, chunk_index=fail.chunk_index,
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
                job_id=fail.job_id, chunk_index=fail.chunk_index,
                source_pages="", record_json=records_json,
                model=llm_response.model, prompt_version=prompt_ver,
            )
            save_result(conn, extraction)
            update_failed_status(conn, fail.id, DLQStatus.REPLAYED)  # type: ignore[arg-type]
            replayed += 1
            console.print(f"  [green]Chunk {fail.chunk_index} replayed successfully[/green]")
        else:
            console.print(f"  [red]Chunk {fail.chunk_index} still failing: {result.error}[/red]")

    console.print(f"\n[bold]{replayed}/{len(failures)} chunk(s) replayed successfully.[/bold]")
    conn.close()


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
    from hermes.db import export_results_as_records, init_db

    conn = init_db()
    records = export_results_as_records(conn, job_id)
    conn.close()

    if not records:
        console.print(f"[yellow]No records found for job {job_id}[/yellow]")
        raise typer.Exit(1)

    if format == "jsonl":
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        text = "\n".join(lines) + "\n"
    elif format == "csv":
        if not records:
            return
        buf = io.StringIO()
        fieldnames = list(records[0].keys())
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r)
        text = buf.getvalue()
    else:
        console.print(f"[red]Unknown format:[/red] {format}. Use 'jsonl' or 'csv'.")
        raise typer.Exit(1)

    if output:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]Exported {len(records)} records to {output}[/green]")
    else:
        sys.stdout.write(text)


@app.command()
def init() -> None:
    """Initialize Hermes config directory and default configuration."""
    hermes_dir = Path.home() / ".hermes"
    hermes_dir.mkdir(parents=True, exist_ok=True)

    config_dest = hermes_dir / "config.toml"
    if not config_dest.exists():
        example = Path(__file__).parent.parent / "config.toml.example"
        if example.exists():
            shutil.copy2(example, config_dest)
            console.print(f"[green]Created config:[/green] {config_dest}")
        else:
            console.print("[yellow]config.toml.example not found, creating minimal config[/yellow]")
            default_config = (
                '[llm]\nprovider = "ollama"\nmodel = "qwen3:4b"\n\n'
                '[storage]\nbase_path = "./storage"\n'
            )
            config_dest.write_text(default_config, encoding="utf-8")
            console.print(f"[green]Created config:[/green] {config_dest}")
    else:
        console.print(f"[dim]Config already exists:[/dim] {config_dest}")

    from hermes.db import init_db
    conn = init_db()
    conn.close()
    console.print("[green]Database initialized.[/green]")
    console.print("[bold]Hermes is ready.[/bold]")


@app.command()
def version() -> None:
    """Show Hermes version."""
    console.print(f"Hermes v{__version__}")


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
