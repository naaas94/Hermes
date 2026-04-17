"""Tests for ``hermes.obs.schema`` — event catalog and ``validate_event``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hermes.obs.schema import (
    CURRENT_LOG_SCHEMA_VERSION,
    EVENT_FIELD_CATALOG,
    HermesObsExtraRequired,
    LlmCallEvent,
    StageStartEvent,
    event_names,
    stage_names,
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


def test_current_log_schema_version_is_2_0() -> None:
    assert CURRENT_LOG_SCHEMA_VERSION == "2.0"


def test_stage_name_literals_are_four_pipeline_stages() -> None:
    assert stage_names() == ("preflight", "normalization", "chunking", "extraction")


def test_stage_names_match_save_pipeline_stage_string_literals() -> None:
    pipeline_text = (
        Path(__file__).resolve().parent.parent / "hermes" / "extraction" / "pipeline.py"
    ).read_text(encoding="utf-8")
    literal_stages = set(re.findall(r'stage\s*=\s*"([^"]+)"', pipeline_text))
    assert literal_stages == set(stage_names())


@pytest.mark.parametrize(
    "bad_stage",
    ["normalize", "chunk", "extract", "repair", "export"],
)
def test_validate_event_rejects_non_v2_stage_literals(bad_stage: str) -> None:
    payload = {
        "schema_version": CURRENT_LOG_SCHEMA_VERSION,
        "ts": "2026-04-16T12:00:00Z",
        "event": "stage.start",
        "stage": bad_stage,
        "job_id": "job_1",
    }
    assert validate_event(payload) is False


def test_validate_event_accepts_llm_call_with_run_type_repair() -> None:
    payload = {
        "schema_version": CURRENT_LOG_SCHEMA_VERSION,
        "ts": "2026-04-16T12:00:00Z",
        "event": "llm.call",
        "job_id": "job_1",
        "model": "gpt-4o-mini",
        "tokens_in": 1,
        "tokens_out": 2,
        "run_type": "repair",
    }
    assert validate_event(payload) is True
    parsed = LlmCallEvent.model_validate(payload)
    assert parsed.run_type == "repair"


def test_llm_call_run_type_defaults_to_extraction() -> None:
    payload = {
        "schema_version": CURRENT_LOG_SCHEMA_VERSION,
        "ts": "2026-04-16T12:00:00Z",
        "event": "llm.call",
        "model": "gpt-4o-mini",
        "tokens_in": 1,
        "tokens_out": 2,
    }
    parsed = LlmCallEvent.model_validate(payload)
    assert parsed.run_type == "extraction"


def test_hermes_obs_extra_required_default_message() -> None:
    exc = HermesObsExtraRequired()
    assert "hermes[obs]" in str(exc).lower() or "[obs]" in str(exc)
