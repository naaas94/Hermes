"""Tests for ``hermes.obs.schema`` — event catalog and ``validate_event``."""

from __future__ import annotations

import re

import pytest

from hermes.obs.schema import (
    CURRENT_LOG_SCHEMA_VERSION,
    EVENT_FIELD_CATALOG,
    StageStartEvent,
    event_names,
    validate_event,
)


def test_every_event_name_has_documented_field_set() -> None:
    literal_events = event_names()
    assert set(literal_events) == set(EVENT_FIELD_CATALOG.keys())
    for name in literal_events:
        spec = EVENT_FIELD_CATALOG[name]
        assert "required" in spec and "optional" in spec and "notes" in spec
        assert isinstance(spec["required"], tuple)
        assert isinstance(spec["optional"], tuple)


def test_validate_event_accepts_minimal_stage_start() -> None:
    payload = {
        "schema_version": CURRENT_LOG_SCHEMA_VERSION,
        "ts": "2026-04-16T12:00:00Z",
        "event": "stage.start",
        "stage": "preflight",
        "job_id": "job_1",
    }
    assert validate_event(payload) is True
    parsed = StageStartEvent.model_validate(payload)
    assert parsed.event == "stage.start"
    assert parsed.stage == "preflight"


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"event": "stage.start"},
        {"schema_version": CURRENT_LOG_SCHEMA_VERSION},
        {"schema_version": CURRENT_LOG_SCHEMA_VERSION, "event": "stage.start"},
    ],
)
def test_validate_event_rejects_missing_schema_version_or_event(bad: dict[str, object]) -> None:
    assert validate_event(bad) is False


def test_validate_event_rejects_bad_schema_version_format() -> None:
    assert (
        validate_event(
            {
                "schema_version": "not-a-version",
                "ts": "2026-04-16T12:00:00Z",
                "event": "stage.start",
                "stage": "preflight",
            }
        )
        is False
    )


def test_validate_event_rejects_unknown_event_string() -> None:
    assert (
        validate_event(
            {
                "schema_version": CURRENT_LOG_SCHEMA_VERSION,
                "ts": "2026-04-16T12:00:00Z",
                "event": "unknown.thing",
                "stage": "preflight",
            }
        )
        is False
    )


def test_validate_event_rejects_missing_required_catalog_fields() -> None:
    assert (
        validate_event(
            {
                "schema_version": CURRENT_LOG_SCHEMA_VERSION,
                "ts": "2026-04-16T12:00:00Z",
                "event": "llm.call",
                # missing model, tokens_in, tokens_out
            }
        )
        is False
    )


def test_current_schema_version_matches_expected_format() -> None:
    assert re.fullmatch(r"\d+\.\d+", CURRENT_LOG_SCHEMA_VERSION) is not None
