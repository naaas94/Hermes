"""Tests for ``hermes.obs.logging`` — bootstrap, dual sink, ``bind_job``."""

from __future__ import annotations

import importlib.util
import json
import logging
import warnings
from pathlib import Path

import pytest

from hermes.config import HermesConfig, ObservabilityConfig
from hermes.obs.logging import (
    HermesNDJSONHandler,
    _StructlogShim,
    bind_job,
    configure_logging,
    get_logger,
    reset_logging_for_tests,
)
from hermes.obs.schema import HermesObsExtraRequired


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    yield
    reset_logging_for_tests()


def test_configure_logging_console_human_readable(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(HermesConfig(), verbose=True)
    logging.getLogger("hermes.test").warning("hello_console")
    err = capsys.readouterr().err
    assert "hermes.test" in err
    assert "WARNING" in err
    assert "hello_console" in err


def test_ndjson_sink_one_json_object_per_line(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    cfg = HermesConfig(
        observability=ObservabilityConfig(
            log_format="console",
            log_dir=str(log_dir),
            log_ndjson=True,
        )
    )
    configure_logging(cfg, verbose=True)
    logging.getLogger("hermes.test.ndjson").info("line_check")
    reset_logging_for_tests()

    ndjson_files = list(log_dir.glob("hermes-*.ndjson"))
    assert len(ndjson_files) == 1
    raw = ndjson_files[0].read_text(encoding="utf-8").strip()
    obj = json.loads(raw)
    assert obj["schema_version"] == "2.0"
    assert obj["message"] == "line_check"
    assert "ts" in obj


def test_bind_job_propagates_job_id_to_ndjson(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs2"
    cfg = HermesConfig(
        observability=ObservabilityConfig(
            log_format="console",
            log_dir=str(log_dir),
            log_ndjson=True,
        )
    )
    configure_logging(cfg, verbose=True)
    with bind_job("job_abc", trace_id="tr_1"):
        logging.getLogger("hermes.test.job").info("with_job")
    reset_logging_for_tests()

    line = next(log_dir.glob("hermes-*.ndjson")).read_text(encoding="utf-8").strip()
    obj = json.loads(line)
    assert obj["job_id"] == "job_abc"
    assert obj["trace_id"] == "tr_1"


def test_get_logger_stdlib_shim_without_json_mode() -> None:
    configure_logging(HermesConfig(), verbose=False)
    log = get_logger("hermes.obs.shim")
    assert isinstance(log, _StructlogShim)
    log.info("ok")


def test_invalid_log_format_warns_and_falls_back_to_console() -> None:
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = HermesConfig(observability=ObservabilityConfig(log_format="bogus"))
        configure_logging(cfg, verbose=False)
        assert any("invalid" in str(x.message).lower() for x in w)


def test_json_log_format_requires_obs_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.obs.logging._HAVE_STRUCTLOG", False)
    monkeypatch.setattr("hermes.obs.logging.structlog", None)
    cfg = HermesConfig(observability=ObservabilityConfig(log_format="json"))
    with pytest.raises(HermesObsExtraRequired):
        configure_logging(cfg)


@pytest.mark.skipif(
    importlib.util.find_spec("structlog") is None,
    reason="log_format=json requires structlog from the [obs] extra",
)
def test_json_mode_configures_structlog_logger() -> None:
    cfg = HermesConfig(
        observability=ObservabilityConfig(log_format="json", log_dir="logs_json")
    )
    configure_logging(cfg, verbose=True)
    log = get_logger("hermes.obs.json")
    assert "BoundLogger" in type(log).__name__
    log.info("structlog_path")
    reset_logging_for_tests()


def test_configure_logging_is_idempotent_for_handlers() -> None:
    configure_logging(HermesConfig(), verbose=False)
    root = logging.getLogger()
    n1 = len(root.handlers)
    configure_logging(HermesConfig(), verbose=False)
    n2 = len(root.handlers)
    assert n1 == n2


def test_ndjson_handler_write_failure_degrades_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "out.ndjson"
    h = HermesNDJSONHandler(path)

    def _raise_open(*_a: object, **_k: object) -> None:
        raise OSError("simulated disk full")

    monkeypatch.setattr("builtins.open", _raise_open)
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", (), None)
    h.emit(record)
    h.emit(record)
    err = capsys.readouterr().err
    assert err.count("NDJSON sink unavailable") == 1
