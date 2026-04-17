"""Tests for ``hermes.obs.sampling`` — RSS samples and stage timers."""

from __future__ import annotations

import importlib.util
import json
import logging
import threading
import time

import pytest

from hermes.obs.logging import _StructlogShim, get_logger
from hermes.obs.sampling import (
    reset_sampling_warnings_for_tests,
    sample_rss,
    stage_timer,
)
from hermes.obs.schema import validate_event


@pytest.fixture(autouse=True)
def _reset_sampling_warn() -> None:
    reset_sampling_warnings_for_tests()
    yield
    reset_sampling_warnings_for_tests()


def _capture_json_records(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for rec in caplog.records:
        msg = rec.getMessage()
        try:
            out.append(json.loads(msg))
        except json.JSONDecodeError:
            continue
    return out


def test_sample_rss_positive_when_psutil_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    if importlib.util.find_spec("psutil") is None:
        pytest.skip("psutil not installed")
    caplog.set_level(logging.INFO)
    log = get_logger("hermes.obs.sampling.test")
    sample_rss("preflight", "job_x", log, note="t")
    records = _capture_json_records(caplog)
    assert len(records) >= 1
    payload = records[-1]
    assert validate_event(payload) is True
    assert payload["event"] == "rss.sample"
    assert payload["stage"] == "preflight"
    assert int(payload["rss_bytes"]) > 0


def test_sample_rss_no_psutil_warns_once_then_no_ops(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.WARNING)
    monkeypatch.setitem(__import__("sys").modules, "psutil", None)
    import hermes.obs.sampling as s

    monkeypatch.setattr(s, "psutil", None)
    log = get_logger("hermes.obs.sampling.test")
    sample_rss("chunking", "j1", log)
    sample_rss("chunking", "j1", log)
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warns) == 1
    assert "rss.sample.unavailable" in warns[0].getMessage()


def test_stage_timer_emits_start_end_and_rss_boundaries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    if importlib.util.find_spec("psutil") is None:
        pytest.skip("psutil not installed")
    caplog.set_level(logging.INFO)
    log = get_logger("hermes.obs.sampling.test")
    with stage_timer("preflight", "job_a", log):
        pass
    recs = _capture_json_records(caplog)
    kinds = [r["event"] for r in recs if isinstance(r.get("event"), str)]
    assert kinds[0] == "stage.start"
    assert "stage.end" in kinds
    end_i = kinds.index("stage.end")
    assert end_i + 1 < len(kinds) and kinds[end_i + 1] == "rss.sample"
    assert kinds.count("rss.sample") >= 2


def test_stage_timer_end_on_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    log = get_logger("hermes.obs.sampling.test")

    with pytest.raises(RuntimeError, match="boom"):
        with stage_timer("normalization", "job_b", log, rss_sampling_enabled=False):
            raise RuntimeError("boom")

    recs = _capture_json_records(caplog)
    assert recs[0]["event"] == "stage.start"
    end = [r for r in recs if r.get("event") == "stage.end"]
    assert len(end) == 1
    assert "status=error" in str(end[0].get("detail", ""))


def test_periodic_sampler_stops_and_no_extra_threads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    if importlib.util.find_spec("psutil") is None:
        pytest.skip("psutil not installed")
    caplog.set_level(logging.INFO)
    log = get_logger("hermes.obs.sampling.test")
    before = threading.active_count()
    with stage_timer(
        "normalization",
        "job_c",
        log,
        rss_sampling_interval_s=0.05,
    ):
        time.sleep(0.22)
    after = threading.active_count()
    assert after <= before + 1
    recs = _capture_json_records(caplog)
    periodic = [r for r in recs if r.get("note") == "periodic"]
    assert len(periodic) >= 1


def test_emit_suppresses_logger_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    shim = _StructlogShim(logging.getLogger("hermes.obs.broken"))

    def _boom(_msg: str) -> None:
        raise OSError("disk")

    monkeypatch.setattr(shim, "info", _boom)
    # Must not raise
    sample_rss("extraction", "j", shim)
    with stage_timer("chunking", "j", shim, rss_sampling_enabled=False):
        pass
