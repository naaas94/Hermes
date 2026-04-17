"""Benchmark runner: workloads, NDJSON-aware metrics, summary export."""

from __future__ import annotations

import csv
import json
import logging
import platform
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable, Sequence
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, Field

from hermes.config import HermesConfig, load_config
from hermes.db import get_job, get_llm_runs_for_job, get_results_for_job, open_db
from hermes.extraction.pipeline import run_pipeline
from hermes.models import LLMResponse
from hermes.obs.logging import configure_logging, get_logger, reset_logging_for_tests
from hermes.obs.schema import (
    CURRENT_LOG_SCHEMA_VERSION,
    BenchSummaryEvent,
    BenchWorkloadEndEvent,
    BenchWorkloadStartEvent,
)

_LOG = logging.getLogger(__name__)
_BENCH_LOG = get_logger("hermes.bench.harness")

_BOILERPLATE_MARKER = "BOILERPLATE_EVAL_NEGATIVE"


class BenchWorkload(BaseModel):
    """Single benchmark scenario."""

    name: str
    input_path: Path
    schema_ref: str
    file_type: Literal["pdf", "excel"]
    expected_page_count: int | None = None
    workers: int = 1
    model: str = "qwen3:4b"
    compare_log_format: bool = Field(
        default=False,
        description="Run once with console and once with json NDJSON when supported.",
    )


class BenchResult(BaseModel):
    """One benchmark attempt (one pipeline run with a given log sink mode)."""

    workload: str
    commit: str
    machine: dict[str, str]
    duration_s: float
    peak_rss_bytes: int
    pages_per_minute: float | None = None
    rows_per_minute: float | None = None
    chunks_per_minute: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_proxy_usd: float | None = None
    validation_pass_rate: float = 1.0
    timestamp: str
    log_format: Literal["console", "json"]
    dual_sink_overhead_pct: float | None = None


class BenchSummary(BaseModel):
    """Full bench run: ordered results and metadata."""

    bench_run_id: str
    commit: str
    timestamp: str
    environment: dict[str, str]
    results: list[BenchResult]
    dual_sink_regression: bool = False


class _ObsJsonCollector(logging.Handler):
    """Capture ``logger.info(json.dumps({..., \"event\": ...}))`` lines from the obs stack."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.events: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
            if not msg.startswith("{"):
                return
            data = json.loads(msg)
            if isinstance(data, dict) and data.get("event"):
                self.events.append(data)
        except Exception:
            return

    def clear(self) -> None:
        self.events.clear()


def _iso_ts() -> str:
    return (
        datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _git_short_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _machine_dict() -> dict[str, str]:
    return {
        "os": platform.system(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
    }


def _rusage_peak_rss_bytes() -> int:
    try:
        import resource
    except ImportError:
        return 0
    getrusage = getattr(resource, "getrusage", None)
    rusage_self = getattr(resource, "RUSAGE_SELF", None)
    if getrusage is None or rusage_self is None:
        return 0
    try:
        u = getrusage(rusage_self)
        if sys.platform == "darwin":
            return max(0, int(u.ru_maxrss))
        return max(0, int(u.ru_maxrss) * 1024)
    except Exception:
        return 0


def _peak_rss_from_events(events: Iterable[dict[str, Any]]) -> int:
    peak = 0
    for e in events:
        if e.get("event") == "rss.sample":
            try:
                b = int(e.get("rss_bytes", 0))
                peak = max(peak, b)
            except (TypeError, ValueError):
                continue
    return peak


def _emit_bench_json(payload: dict[str, Any]) -> None:
    try:
        _BENCH_LOG.info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def _mock_llm_client(mock_llm_response: LLMResponse) -> MagicMock:
    mock_client = MagicMock()

    def _chat(_system_prompt: str, user_prompt: str) -> LLMResponse:
        if _BOILERPLATE_MARKER in user_prompt:
            return LLMResponse(
                content="[]",
                model=mock_llm_response.model,
                tokens_in=20,
                tokens_out=5,
                latency_ms=1,
            )
        return mock_llm_response

    mock_client.chat.side_effect = _chat
    mock_client.check_ready.return_value = True
    return mock_client


def _rows_total_from_results(conn: sqlite3.Connection, job_id: str) -> int:
    total = 0
    for ex in get_results_for_job(conn, job_id):
        try:
            arr = json.loads(ex.record_json)
            if isinstance(arr, list):
                total += len(arr)
        except (json.JSONDecodeError, TypeError):
            continue
    return total


def _default_mock_response() -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            [
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
            ]
        ),
        model="qwen3:4b",
        tokens_in=500,
        tokens_out=200,
        latency_ms=2000,
    )


def _configure_obs(cfg: HermesConfig, log_format: Literal["console", "json"]) -> HermesConfig:
    obs = replace(cfg.observability)
    obs = replace(obs, log_format=log_format, log_ndjson=log_format == "json")
    return replace(cfg, observability=obs)


def _run_single_attempt(
    *,
    workload: BenchWorkload,
    cfg: HermesConfig,
    log_format: Literal["console", "json"],
    bench_run_id: str,
    commit: str,
    mock_llm: bool,
    mock_response: LLMResponse | None,
    collector: _ObsJsonCollector,
) -> BenchResult:
    reset_logging_for_tests()
    root = logging.getLogger()
    collector.clear()
    root.addHandler(collector)

    eff_cfg = _configure_obs(cfg, log_format)
    configure_logging(eff_cfg, verbose=False)

    t0 = time.perf_counter()
    job_id: str | None = None

    llm_ctx = (
        patch(
            "hermes.extraction.pipeline.create_llm_client",
            return_value=_mock_llm_client(mock_response or _default_mock_response()),
        )
        if mock_llm
        else nullcontext()
    )

    with llm_ctx:
        job_id = run_pipeline(
            workload.input_path,
            schema_ref=workload.schema_ref,
            model_override=workload.model,
            max_workers=workload.workers,
            force_new_job=True,
        )
    elapsed = max(0.0, time.perf_counter() - t0)

    ru = _rusage_peak_rss_bytes()
    obs_peak = _peak_rss_from_events(collector.events)
    peak = max(obs_peak, ru)

    tokens_in = tokens_out = 0
    val_rate = 1.0
    pages_pm: float | None = None
    rows_pm: float | None = None
    chunks_pm: float | None = None

    if job_id:
        with open_db() as conn:
            job = get_job(conn, job_id)
            runs = get_llm_runs_for_job(conn, job_id)
            if runs:
                tokens_in = sum(r.tokens_in for r in runs)
                tokens_out = sum(r.tokens_out for r in runs)
                passed = sum(1 for r in runs if r.validation_passed)
                val_rate = passed / len(runs)
            if job and elapsed > 0:
                if workload.file_type == "pdf" and job.page_count:
                    pages_pm = (job.page_count / elapsed) * 60.0
                if workload.file_type == "excel":
                    nrows = _rows_total_from_results(conn, job_id)
                    rows_pm = (nrows / elapsed) * 60.0
                if job.total_chunks:
                    chunks_pm = (job.total_chunks / elapsed) * 60.0

    root.removeHandler(collector)

    return BenchResult(
        workload=workload.name,
        commit=commit,
        machine=_machine_dict(),
        duration_s=elapsed,
        peak_rss_bytes=peak,
        pages_per_minute=pages_pm,
        rows_per_minute=rows_pm,
        chunks_per_minute=chunks_pm,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_proxy_usd=None,
        validation_pass_rate=val_rate,
        timestamp=_iso_ts(),
        log_format=log_format,
        dual_sink_overhead_pct=None,
    )


def _emit_workload_start(bench_run_id: str, workload: str, fingerprint: str | None) -> None:
    _emit_bench_json(
        BenchWorkloadStartEvent(
            schema_version=CURRENT_LOG_SCHEMA_VERSION,
            ts=_iso_ts(),
            event="bench.workload.start",
            job_id=None,
            bench_run_id=bench_run_id,
            workload=workload,
            input_fingerprint=fingerprint,
        ).model_dump(mode="json")
    )


def _emit_workload_end(
    bench_run_id: str,
    status: str,
    duration_s: float | None = None,
    error: str | None = None,
) -> None:
    _emit_bench_json(
        BenchWorkloadEndEvent(
            schema_version=CURRENT_LOG_SCHEMA_VERSION,
            ts=_iso_ts(),
            event="bench.workload.end",
            job_id=None,
            bench_run_id=bench_run_id,
            status=status,
            duration_s=duration_s,
            error=error,
        ).model_dump(mode="json")
    )


def _emit_summary(
    bench_run_id: str,
    workload_count: int,
    commit: str,
) -> None:
    _emit_bench_json(
        BenchSummaryEvent(
            schema_version=CURRENT_LOG_SCHEMA_VERSION,
            ts=_iso_ts(),
            event="bench.summary",
            job_id=None,
            bench_run_id=bench_run_id,
            workload_count=workload_count,
            commit=commit,
            timestamp=_iso_ts(),
        ).model_dump(mode="json")
    )


def _fingerprint_path(path: Path) -> str | None:
    try:
        from hermes.dedup import sha256_file_hex

        return sha256_file_hex(path)
    except Exception:
        return None


def _dual_overhead_pct(console_s: float, json_s: float) -> float:
    if console_s <= 0:
        return 0.0
    return ((json_s - console_s) / console_s) * 100.0


def _warn_dual_sink_regression(workload: str, pct: float) -> None:
    _BENCH_LOG.warning(
        "bench.dualsink.regression workload=%s dual_sink_overhead_pct=%.4f",
        workload,
        pct,
    )


def dual_sink_regression_triggered(workload_name: str, overhead_pct: float) -> bool:
    """Return True when overhead exceeds the acceptance threshold (``pdf_text_small`` only)."""

    return workload_name == "pdf_text_small" and overhead_pct > 10.0


def _structlog_available() -> bool:
    try:
        import structlog  # noqa: F401
    except ImportError:
        return False
    return True


def run_bench(
    workloads: Sequence[BenchWorkload],
    output_dir: Path,
    model: str,
    workers: int,
    *,
    mock_llm: bool = False,
    log_format_compare: bool | None = None,
    write_csv: bool = False,
    project_root: Path | None = None,
) -> BenchSummary:
    """Run workloads (optionally console+json), aggregate summary, write JSON/CSV."""

    cfg = load_config()
    repo = project_root or Path(__file__).resolve().parents[2]
    commit = _git_short_sha(repo)
    bench_run_id = str(uuid.uuid4())
    results: list[BenchResult] = []
    dual_sink_regression = False
    collector = _ObsJsonCollector()

    wloads = [w.model_copy(update={"model": model, "workers": workers}) for w in workloads]

    for w in wloads:
        if not w.input_path.is_file():
            _emit_workload_start(bench_run_id, w.name, None)
            _emit_workload_end(bench_run_id, "skipped", duration_s=0.0, error="fixture_missing")
            continue

        fp = _fingerprint_path(w.input_path)
        _emit_workload_start(bench_run_id, w.name, fp)

        do_compare = w.compare_log_format
        if log_format_compare is True:
            do_compare = True
        elif log_format_compare is False:
            do_compare = False

        t_wall0 = time.perf_counter()
        err_note: str | None = None

        try:
            if do_compare and not _structlog_available():
                _LOG.warning(
                    "bench.log_format_compare.skipped: structlog not installed; "
                    "install hermes[obs] for dual console/json runs"
                )
                do_compare = False

            if do_compare:
                res_console = _run_single_attempt(
                    workload=w,
                    cfg=cfg,
                    log_format="console",
                    bench_run_id=bench_run_id,
                    commit=commit,
                    mock_llm=mock_llm,
                    mock_response=None,
                    collector=collector,
                )
                results.append(res_console)

                res_json = _run_single_attempt(
                    workload=w,
                    cfg=cfg,
                    log_format="json",
                    bench_run_id=bench_run_id,
                    commit=commit,
                    mock_llm=mock_llm,
                    mock_response=None,
                    collector=collector,
                )
                pct = _dual_overhead_pct(res_console.duration_s, res_json.duration_s)
                res_json = res_json.model_copy(update={"dual_sink_overhead_pct": pct})
                if dual_sink_regression_triggered(w.name, pct):
                    dual_sink_regression = True
                    _warn_dual_sink_regression(w.name, pct)

                results.append(res_json)
            else:
                r = _run_single_attempt(
                    workload=w,
                    cfg=cfg,
                    log_format="console",
                    bench_run_id=bench_run_id,
                    commit=commit,
                    mock_llm=mock_llm,
                    mock_response=None,
                    collector=collector,
                )
                results.append(r)
        except Exception as e:
            err_note = f"{type(e).__name__}: {e}"
            _LOG.exception("bench workload %s", w.name)

        wall = max(0.0, time.perf_counter() - t_wall0)
        st = "error" if err_note else "ok"
        _emit_workload_end(
            bench_run_id,
            st,
            duration_s=wall,
            error=err_note,
        )

    summary = BenchSummary(
        bench_run_id=bench_run_id,
        commit=commit,
        timestamp=_iso_ts(),
        environment=_machine_dict(),
        results=results,
        dual_sink_regression=dual_sink_regression,
    )

    _emit_summary(bench_run_id, len(wloads), commit)

    output_dir.mkdir(parents=True, exist_ok=True)
    day = datetime.now(tz=UTC).strftime("%Y%m%d")
    out_json = output_dir / f"{day}_{commit}.json"
    out_json.write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if write_csv:
        out_csv = output_dir / f"{day}_{commit}.csv"
        _write_csv(summary, out_csv)

    reset_logging_for_tests()
    return summary


def _write_csv(summary: BenchSummary, path: Path) -> None:
    if not summary.results:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(BenchResult.model_fields.keys()) + ["bench_run_id", "summary_commit"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in summary.results:
            row = r.model_dump(mode="json")
            row["bench_run_id"] = summary.bench_run_id
            row["summary_commit"] = summary.commit
            w.writerow(row)


