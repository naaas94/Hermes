"""Versioned NDJSON log schema for Hermes observability (Part B).

**Versioning policy**

- **Additive** changes (new optional fields on an event, or a new ``event`` value
  added to :data:`EventName`) → **no** ``schema_version`` bump for the same major
  line; prefer bumping the **minor** segment when you need to signal new optional
  data (e.g. ``2.0`` → ``2.1``).
- **Breaking** changes (field removed or renamed, type narrowed, or meaning of a
  field changed) → bump **major** (e.g. ``1.x`` → ``2.0``) and document in the
  changelog.

:data:`StageName` literals match the strings persisted by ``save_pipeline_stage``
(``pipeline_stages.stage`` in SQLite) — one vocabulary, no emit-time alias map.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Final, Literal, get_args

from pydantic import BaseModel, Field, TypeAdapter, ValidationError


class HermesObsExtraRequired(RuntimeError):
    """Raised when NDJSON JSON logging is requested without the optional ``[obs]`` extra."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "JSON structured logging requires the optional [obs] extra "
            "(install with: pip install 'hermes[obs]')"
        )


def _literal_union_args(alias: object) -> tuple[Any, ...]:
    """``typing.get_args`` on PEP 695 ``type Alias = Literal[...]`` needs the inner value."""
    inner = getattr(alias, "__value__", alias)
    return get_args(inner)

# -----------------------------------------------------------------------------
# Version
# -----------------------------------------------------------------------------

type LogSchemaVersion = Literal["2.0"]
"""Supported ``schema_version`` strings for this module (semver-ish major.minor)."""

CURRENT_LOG_SCHEMA_VERSION: Final[LogSchemaVersion] = "2.0"
"""Default schema version emitted by Hermes for NDJSON observability events."""

_SCHEMA_VERSION_RE = re.compile(r"^\d+\.\d+$")

# -----------------------------------------------------------------------------
# Names
# -----------------------------------------------------------------------------

type EventName = Literal[
    "stage.start",
    "stage.end",
    "rss.sample",
    "chunk.done",
    "llm.call",
    "job.start",
    "job.end",
    "bench.workload.start",
    "bench.workload.end",
    "bench.summary",
]

type StageName = Literal["preflight", "normalization", "chunking", "extraction"]

type LlmCallRunType = Literal["extraction", "retry", "repair"]

_EVENT_NAMES: tuple[str, ...] = tuple(
    str(x) for x in _literal_union_args(EventName)
)
_STAGE_NAMES: tuple[str, ...] = tuple(
    str(x) for x in _literal_union_args(StageName)
)


# -----------------------------------------------------------------------------
# Field catalog (documentation + tests)
# -----------------------------------------------------------------------------

# Keys are ``EventName`` values; values describe required and optional payload keys
# (beyond :class:`BaseEvent` common fields).
EVENT_FIELD_CATALOG: dict[str, dict[str, Any]] = {
    "stage.start": {
        "required": ("stage",),
        "optional": ("detail",),
        "notes": "Emitted at the beginning of a pipeline stage.",
    },
    "stage.end": {
        "required": ("stage",),
        "optional": ("duration_ms", "detail"),
        "notes": "Emitted when a pipeline stage finishes.",
    },
    "rss.sample": {
        "required": ("stage", "rss_bytes"),
        "optional": ("note",),
        "notes": "Resident set size sample for a stage boundary or timer tick.",
    },
    "chunk.done": {
        "required": ("chunk_index",),
        "optional": ("total_chunks", "page_span"),
        "notes": "Chunking produced another chunk (0-based index).",
    },
    "llm.call": {
        "required": ("model", "tokens_in", "tokens_out"),
        "optional": ("chunk_index", "latency_ms", "run_type"),
        "notes": "LLM invocation; run_type defaults to extraction; no prompts/secrets.",
    },
    "job.start": {
        "required": (),
        "optional": ("input_fingerprint", "schema_ref", "file_type"),
        "notes": "A document job began (paths logged as fingerprints, not raw secrets).",
    },
    "job.end": {
        "required": ("status",),
        "optional": ("duration_ms", "error"),
        "notes": "Job terminal state.",
    },
    "bench.workload.start": {
        "required": ("bench_run_id", "workload"),
        "optional": ("input_fingerprint",),
        "notes": "Benchmark harness started one workload.",
    },
    "bench.workload.end": {
        "required": ("bench_run_id", "status"),
        "optional": ("duration_s", "error"),
        "notes": "status is one of ok, error, skipped.",
    },
    "bench.summary": {
        "required": ("bench_run_id",),
        "optional": ("workload_count", "commit", "timestamp"),
        "notes": "Aggregate bench run metadata (per-result rows live in bench JSON output).",
    },
}


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------


class BaseEvent(BaseModel):
    """Common fields carried by every Hermes NDJSON event."""

    schema_version: str = Field(
        ...,
        description="Log schema version; must match :data:`CURRENT_LOG_SCHEMA_VERSION`.",
    )
    ts: str = Field(..., description="ISO8601 timestamp in UTC (with Z or explicit offset).")
    event: EventName
    job_id: str | None = None
    trace_id: str | None = Field(
        default=None,
        description="Optional correlation id; reserved for future OTel alignment.",
    )


class StageStartEvent(BaseEvent):
    event: Literal["stage.start"] = "stage.start"
    stage: StageName
    detail: str | None = None


class StageEndEvent(BaseEvent):
    event: Literal["stage.end"] = "stage.end"
    stage: StageName
    duration_ms: int | None = None
    detail: str | None = None


class RssSampleEvent(BaseEvent):
    event: Literal["rss.sample"] = "rss.sample"
    stage: StageName
    rss_bytes: int
    note: str | None = None


class ChunkDoneEvent(BaseEvent):
    event: Literal["chunk.done"] = "chunk.done"
    chunk_index: int
    total_chunks: int | None = None
    page_span: str | None = None


class LlmCallEvent(BaseEvent):
    event: Literal["llm.call"] = "llm.call"
    model: str
    tokens_in: int
    tokens_out: int
    chunk_index: int | None = None
    latency_ms: int | None = None
    run_type: LlmCallRunType = Field(
        default="extraction",
        description="Mirrors LLMRun.run_type; repair/retry are not pipeline stages.",
    )


class JobStartEvent(BaseEvent):
    event: Literal["job.start"] = "job.start"
    input_fingerprint: str | None = None
    schema_ref: str | None = None
    file_type: str | None = None


class JobEndEvent(BaseEvent):
    event: Literal["job.end"] = "job.end"
    status: str
    duration_ms: int | None = None
    error: str | None = None


class BenchWorkloadStartEvent(BaseEvent):
    event: Literal["bench.workload.start"] = "bench.workload.start"
    bench_run_id: str
    workload: str
    input_fingerprint: str | None = None


class BenchWorkloadEndEvent(BaseEvent):
    event: Literal["bench.workload.end"] = "bench.workload.end"
    bench_run_id: str
    status: str
    duration_s: float | None = None
    error: str | None = None


class BenchSummaryEvent(BaseEvent):
    event: Literal["bench.summary"] = "bench.summary"
    bench_run_id: str
    workload_count: int | None = None
    commit: str | None = None
    timestamp: str | None = None


HermesLogEvent = Annotated[
    (
        StageStartEvent
        | StageEndEvent
        | RssSampleEvent
        | ChunkDoneEvent
        | LlmCallEvent
        | JobStartEvent
        | JobEndEvent
        | BenchWorkloadStartEvent
        | BenchWorkloadEndEvent
        | BenchSummaryEvent
    ),
    Field(discriminator="event"),
]

_event_adapter: TypeAdapter[HermesLogEvent] = TypeAdapter(HermesLogEvent)


def validate_event(data: dict[str, Any]) -> bool:
    """Return True if ``data`` is a valid Hermes log event for the current schema.

    Invalid or incomplete dicts (missing ``schema_version`` / ``event``, wrong types,
    or unknown ``event``) return False. Validation never raises.
    """
    if not isinstance(data, dict):
        return False
    if "schema_version" not in data or "event" not in data:
        return False
    version = data.get("schema_version")
    if not isinstance(version, str) or not _SCHEMA_VERSION_RE.fullmatch(version):
        return False
    event = data.get("event")
    if not isinstance(event, str) or event not in _EVENT_NAMES:
        return False
    if event in EVENT_FIELD_CATALOG:
        spec = EVENT_FIELD_CATALOG[event]
        for key in spec.get("required", ()):
            if key not in data:
                return False
    try:
        _event_adapter.validate_python(data)
    except ValidationError:
        return False
    return True


def stage_names() -> tuple[str, ...]:
    """Return all defined :data:`StageName` values (for consumers and tests)."""

    return _STAGE_NAMES


def event_names() -> tuple[str, ...]:
    """Return all defined :data:`EventName` values."""

    return _EVENT_NAMES
