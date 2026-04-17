"""RSS sampling and stage timing at pipeline boundaries (Part B)."""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import ModuleType
from typing import Any

from hermes.obs.schema import (
    CURRENT_LOG_SCHEMA_VERSION,
    RssSampleEvent,
    StageEndEvent,
    StageName,
    StageStartEvent,
)

_psutil: ModuleType | None
try:
    import psutil as _psutil_mod
except ImportError:
    _psutil = None
else:
    _psutil = _psutil_mod

psutil = _psutil

_PSUTIL_UNAVAILABLE_WARNED: bool = False


def reset_sampling_warnings_for_tests() -> None:
    """Reset process-global fallback state (tests only)."""

    global _PSUTIL_UNAVAILABLE_WARNED
    _PSUTIL_UNAVAILABLE_WARNED = False


def _iso_ts() -> str:
    return (
        datetime.now(tz=UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _emit_json(logger: Any, payload: dict[str, Any]) -> None:
    try:
        logger.info(json.dumps(payload, ensure_ascii=False))
    except Exception:
        pass


def sample_rss(
    stage: StageName,
    job_id: str | None,
    logger: Any,
    *,
    note: str | None = None,
) -> None:
    """Emit ``rss.sample`` with current RSS, or one-time warn if ``psutil`` is absent."""
    global _PSUTIL_UNAVAILABLE_WARNED
    try:
        if psutil is None:
            if not _PSUTIL_UNAVAILABLE_WARNED:
                _PSUTIL_UNAVAILABLE_WARNED = True
                logger.warning("rss.sample.unavailable: psutil not installed")
            return
        proc = psutil.Process()
        rss = int(proc.memory_info().rss)
        if rss < 0:
            rss = 0
        evt = RssSampleEvent(
            schema_version=CURRENT_LOG_SCHEMA_VERSION,
            ts=_iso_ts(),
            event="rss.sample",
            job_id=job_id,
            stage=stage,
            rss_bytes=rss,
            note=note,
        )
        _emit_json(logger, evt.model_dump(mode="json"))
    except Exception:
        pass


@contextmanager
def stage_timer(
    stage: StageName,
    job_id: str | None,
    logger: Any,
    *,
    rss_sampling_interval_s: float = 0.0,
    rss_sampling_enabled: bool = True,
) -> Iterator[None]:
    """Emit ``stage.start`` / ``stage.end`` and RSS at boundaries; optional periodic samples."""
    start_ns = time.perf_counter_ns()
    stop_flag = threading.Event()
    periodic_thread: threading.Thread | None = None

    _emit_json(
        logger,
        StageStartEvent(
            schema_version=CURRENT_LOG_SCHEMA_VERSION,
            ts=_iso_ts(),
            event="stage.start",
            job_id=job_id,
            stage=stage,
        ).model_dump(mode="json"),
    )
    if rss_sampling_enabled:
        sample_rss(stage, job_id, logger, note="boundary_start")

    use_periodic = (
        rss_sampling_enabled
        and rss_sampling_interval_s > 0
        and stage == "normalization"
    )
    if use_periodic:

        def _periodic_loop() -> None:
            while not stop_flag.is_set():
                if stop_flag.wait(timeout=rss_sampling_interval_s):
                    break
                if stop_flag.is_set():
                    break
                sample_rss(stage, job_id, logger, note="periodic")

        periodic_thread = threading.Thread(
            target=_periodic_loop,
            name="hermes-rss-periodic",
            daemon=True,
        )
        periodic_thread.start()

    try:
        yield
    finally:
        stop_flag.set()
        if periodic_thread is not None:
            periodic_thread.join(timeout=10.0)

        end_ns = time.perf_counter_ns()
        duration_ms = int((end_ns - start_ns) / 1_000_000)
        exc = sys.exc_info()[1]
        detail: str | None = None
        if exc is not None:
            detail = f"status=error; error={type(exc).__name__}: {exc}"

        _emit_json(
            logger,
            StageEndEvent(
                schema_version=CURRENT_LOG_SCHEMA_VERSION,
                ts=_iso_ts(),
                event="stage.end",
                job_id=job_id,
                stage=stage,
                duration_ms=duration_ms,
                detail=detail,
            ).model_dump(mode="json"),
        )
        if rss_sampling_enabled:
            sample_rss(stage, job_id, logger, note="boundary_end")
