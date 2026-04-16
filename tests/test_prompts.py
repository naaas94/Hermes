"""Tests for prompt building and versioning."""

from __future__ import annotations

from hermes.extraction.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    build_repair_prompt,
    build_user_prompt,
    get_current_prompt_version,
    prompt_version,
)


def test_build_user_prompt():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    prompt = build_user_prompt(schema, "Some document text here")
    assert "name" in prompt
    assert "Some document text here" in prompt
    assert "JSON array" in prompt


def test_build_repair_prompt():
    schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    prompt = build_repair_prompt("Field x is required", '{"bad": true}', schema)
    assert "Field x is required" in prompt
    assert '{"bad": true}' in prompt


def test_prompt_version_stability():
    v1 = get_current_prompt_version()
    v2 = get_current_prompt_version()
    assert v1 == v2
    assert len(v1) == 16


def test_prompt_version_changes_with_template():
    v1 = prompt_version("system A", "user A")
    v2 = prompt_version("system B", "user A")
    assert v1 != v2


def test_system_prompt_has_abstention_rule():
    assert "empty array []" in SYSTEM_PROMPT
    assert "boilerplate" in SYSTEM_PROMPT
    assert "If no record in the text matches the schema" in USER_PROMPT_TEMPLATE
    assert "null-only rows" in USER_PROMPT_TEMPLATE
