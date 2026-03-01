"""Tests for LLM output validation and repair loop."""

from __future__ import annotations

import json

from pydantic import BaseModel

from hermes.extraction.validator import parse_json_array, strip_fences, validate_records
from hermes.models import LLMResponse


class SampleModel(BaseModel):
    name: str
    value: int | None = None


def test_strip_fences_json():
    text = '```json\n[{"name": "a"}]\n```'
    assert strip_fences(text) == '[{"name": "a"}]'


def test_strip_fences_no_lang():
    text = '```\n{"x": 1}\n```'
    assert strip_fences(text) == '{"x": 1}'


def test_strip_fences_clean():
    text = '[{"name": "b"}]'
    assert strip_fences(text) == '[{"name": "b"}]'


def test_parse_json_array():
    records = parse_json_array('[{"name": "a"}, {"name": "b"}]')
    assert len(records) == 2


def test_parse_json_single_object():
    records = parse_json_array('{"name": "solo"}')
    assert len(records) == 1
    assert records[0]["name"] == "solo"


def test_validate_records_valid():
    raw = json.dumps([{"name": "Alice", "value": 42}])
    valid, invalid, error = validate_records(raw, SampleModel)
    assert len(valid) == 1
    assert len(invalid) == 0
    assert error == ""


def test_validate_records_partial():
    raw = json.dumps([
        {"name": "Good", "value": 1},
        {"value": "not_a_name"},  # missing required 'name'
    ])
    valid, invalid, error = validate_records(raw, SampleModel)
    assert len(valid) == 1
    assert len(invalid) == 1
    assert error != ""


def test_validate_records_bad_json():
    valid, invalid, error = validate_records("not json at all", SampleModel)
    assert len(valid) == 0
    assert "JSON parse error" in error


def test_validate_with_repair_happy_path():
    from unittest.mock import MagicMock

    from hermes.extraction.validator import validate_with_repair

    response = LLMResponse(
        content=json.dumps([{"name": "OK", "value": 1}]),
        model="test", tokens_in=10, tokens_out=20, latency_ms=100,
    )
    mock_client = MagicMock()

    result = validate_with_repair(
        response, SampleModel, SampleModel.model_json_schema(), mock_client, max_retries=2
    )
    assert len(result.validated) == 1
    assert result.error == ""
    mock_client.chat.assert_not_called()


def test_validate_with_repair_needs_retry():
    from unittest.mock import MagicMock

    from hermes.extraction.validator import validate_with_repair

    bad_response = LLMResponse(
        content="not json", model="test",
        tokens_in=10, tokens_out=5, latency_ms=50,
    )
    good_content = json.dumps([{"name": "Fixed"}])
    good_response = LLMResponse(
        content=good_content, model="test",
        tokens_in=10, tokens_out=20, latency_ms=100,
    )
    mock_client = MagicMock()
    mock_client.chat.return_value = good_response

    result = validate_with_repair(
        bad_response, SampleModel, SampleModel.model_json_schema(), mock_client, max_retries=2
    )
    assert len(result.validated) == 1
    assert result.attempts == 2
    mock_client.chat.assert_called_once()


def test_validate_with_repair_exhausted():
    from unittest.mock import MagicMock

    from hermes.extraction.validator import validate_with_repair

    bad_response = LLMResponse(
        content="broken", model="test",
        tokens_in=10, tokens_out=5, latency_ms=50,
    )
    mock_client = MagicMock()
    mock_client.chat.return_value = LLMResponse(
        content="still broken", model="test",
        tokens_in=10, tokens_out=5, latency_ms=50,
    )

    result = validate_with_repair(
        bad_response, SampleModel, SampleModel.model_json_schema(), mock_client, max_retries=2
    )
    assert len(result.validated) == 0
    assert result.error != ""
    assert result.attempts == 3
