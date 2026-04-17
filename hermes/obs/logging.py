"""Structured logging bootstrap: console + optional NDJSON, job binding (Part B)."""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import warnings
from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hermes.config import HermesConfig, get_storage_base
from hermes.obs.schema import CURRENT_LOG_SCHEMA_VERSION, HermesObsExtraRequired

try:
    import structlog
except ImportError:
    structlog = None  # type: ignore[assignment]

_HAVE_STRUCTLOG: Final[bool] = structlog is not None

_OBS_CTX: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "hermes_obs_ctx", default=None
)

_NDJSON_FAIL_WARNED: bool = False
_STRUCTLOG_JSON_MODE: bool = False

_CONSOLE_FORMAT: Final[str] = "%(name)s %(levelname)s: %(message)s"


class _HermesObsContextFilter(logging.Filter):
    """Merge ``bind_job`` context onto log records for NDJSON and filters."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _OBS_CTX.get()
        if ctx:
            for key, value in ctx.items():
                setattr(record, key, value)
        return True


class HermesNDJSONHandler(logging.Handler):
    """Append one JSON object per line; degrades silently on write failure (once)."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.DEBUG)
        self._path = path
        self._stream: Any = None

    def emit(self, record: logging.LogRecord) -> None:
        global _NDJSON_FAIL_WARNED
        try:
            if self._stream is None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._stream = open(self._path, "a", encoding="utf-8")
            payload: dict[str, Any] = {
                "schema_version": CURRENT_LOG_SCHEMA_VERSION,
                "ts": (
                    datetime.fromtimestamp(record.created, tz=UTC)
                    .replace(microsecond=0)
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            jid = getattr(record, "job_id", None)
            if jid is not None:
                payload["job_id"] = jid
            tid = getattr(record, "trace_id", None)
            if tid is not None:
                payload["trace_id"] = tid
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            self._stream.write(line)
            self._stream.flush()
        except OSError:
            if not _NDJSON_FAIL_WARNED:
                _NDJSON_FAIL_WARNED = True
                try:
                    print(
                        "hermes.obs: NDJSON sink unavailable (write failed); "
                        "continuing with console logging only.",
                        file=__import__("sys").stderr,
                    )
                except OSError:
                    pass

    def close(self) -> None:
        if self._stream is not None:
            with contextlib.suppress(OSError):
                self._stream.close()
            self._stream = None
        super().close()


def _effective_log_format(raw: str) -> tuple[str, bool]:
    """Return (format, warned_invalid)."""
    normalized = (raw or "").strip().lower()
    if normalized in ("json", "console"):
        return normalized, False
    warnings.warn(
        f"Invalid observability.log_format {raw!r}; falling back to 'console'.",
        UserWarning,
        stacklevel=2,
    )
    return "console", True


def _ndjson_enabled(cfg: HermesConfig, log_format: str) -> bool:
    return log_format == "json" or cfg.observability.log_ndjson


def _resolve_log_dir(cfg: HermesConfig) -> Path:
    raw = cfg.observability.log_dir
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    return get_storage_base() / p


def _daily_ndjson_path(log_dir: Path) -> Path:
    day = datetime.now(tz=UTC).strftime("%Y%m%d")
    return log_dir / f"hermes-{day}.ndjson"


def _clear_hermes_obs_handlers(root: logging.Logger) -> None:
    to_remove: list[logging.Handler] = []
    for h in root.handlers:
        if getattr(h, "name", None) in ("hermes_obs_stream", "hermes_obs_ndjson"):
            to_remove.append(h)
    for h in to_remove:
        root.removeHandler(h)
        with contextlib.suppress(Exception):
            h.close()


@dataclass
class _StructlogShim:
    """Minimal stand-in when structlog is not installed."""

    _logger: logging.Logger

    def bind(self, **_kwargs: Any) -> _StructlogShim:
        return self

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.error(msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._logger.debug(msg, *args, **kwargs)


def configure_logging(config: HermesConfig, *, verbose: bool = False) -> None:
    """Configure root logging: human console + optional NDJSON file. Idempotent."""
    global _NDJSON_FAIL_WARNED, _STRUCTLOG_JSON_MODE

    level = logging.DEBUG if verbose else logging.WARNING
    eff_format, _ = _effective_log_format(config.observability.log_format)
    want_ndjson = _ndjson_enabled(config, eff_format)

    if eff_format == "json" and not _HAVE_STRUCTLOG:
        raise HermesObsExtraRequired()

    root = logging.getLogger()
    root.setLevel(level)
    _clear_hermes_obs_handlers(root)
    _STRUCTLOG_JSON_MODE = False

    stream = logging.StreamHandler()
    stream.setLevel(level)
    stream.name = "hermes_obs_stream"
    stream.addFilter(_HermesObsContextFilter())

    if eff_format == "json" and structlog is not None:
        _STRUCTLOG_JSON_MODE = True
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                _add_schema_version_processor,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
        stream.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.dev.ConsoleRenderer(colors=False),
                foreign_pre_chain=[
                    structlog.stdlib.add_logger_name,
                    structlog.stdlib.add_log_level,
                    structlog.processors.TimeStamper(fmt="iso", utc=True),
                ],
            )
        )
    else:
        stream.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    if want_ndjson:
        log_dir = _resolve_log_dir(config)
        ndjson_path = _daily_ndjson_path(log_dir)
        ndjson_h = HermesNDJSONHandler(ndjson_path)
        ndjson_h.setLevel(level)
        ndjson_h.name = "hermes_obs_ndjson"
        ndjson_h.addFilter(_HermesObsContextFilter())
        root.addHandler(ndjson_h)

    root.addHandler(stream)


def _add_schema_version_processor(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    event_dict.setdefault("schema_version", CURRENT_LOG_SCHEMA_VERSION)
    return event_dict


def get_logger(name: str) -> Any:
    """Return a structlog ``BoundLogger`` when ``[obs]`` is used; else a stdlib-compatible shim."""
    if _STRUCTLOG_JSON_MODE and structlog is not None:
        return structlog.get_logger(name)
    return _StructlogShim(logging.getLogger(name))


@contextlib.contextmanager
def bind_job(job_id: str, **kwargs: Any) -> Iterator[None]:
    """Bind ``job_id`` (and optional keys like ``trace_id``) for nested logging."""
    payload = {"job_id": job_id, **kwargs}
    token = _OBS_CTX.set(payload)
    try:
        if _STRUCTLOG_JSON_MODE and structlog is not None:
            with structlog.contextvars.bound_contextvars(job_id=job_id, **kwargs):
                yield
        else:
            yield
    finally:
        _OBS_CTX.reset(token)


def reset_logging_for_tests() -> None:
    """Remove Hermes obs handlers and close NDJSON streams (tests only)."""
    global _NDJSON_FAIL_WARNED, _STRUCTLOG_JSON_MODE
    root = logging.getLogger()
    _clear_hermes_obs_handlers(root)
    _NDJSON_FAIL_WARNED = False
    _STRUCTLOG_JSON_MODE = False
