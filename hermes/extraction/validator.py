"""Pydantic validation of LLM output with repair loop."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from hermes.extraction.llm_client import BaseLLMClient
from hermes.extraction.prompts import (
    SYSTEM_PROMPT,
    build_repair_prompt,
)
from hermes.models import LLMResponse

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


@dataclass
class ValidationResult:
    validated: list[BaseModel] = field(default_factory=list)
    failed_raw: str = ""
    error: str = ""
    attempts: int = 0
    all_responses: list[LLMResponse] = field(default_factory=list)


def strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def parse_json_array(text: str) -> list[dict[str, Any]]:
    """Parse text as a JSON array, handling both array and single-object responses."""
    cleaned = strip_fences(text)
    parsed = json.loads(cleaned)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return [parsed]
    raise ValueError(f"Expected JSON array or object, got {type(parsed).__name__}")


def validate_records(
    raw_text: str,
    schema_class: type[BaseModel],
) -> tuple[list[BaseModel], list[dict[str, Any]], str]:
    """Validate parsed JSON records against a Pydantic schema.

    Returns (valid_records, invalid_dicts, error_message).
    """
    try:
        records = parse_json_array(raw_text)
    except (json.JSONDecodeError, ValueError) as e:
        return [], [], f"JSON parse error: {e}"

    valid: list[BaseModel] = []
    invalid: list[dict[str, Any]] = []
    errors: list[str] = []

    for record in records:
        try:
            valid.append(schema_class.model_validate(record))
        except ValidationError as e:
            invalid.append(record)
            errors.append(str(e))

    error_msg = "; ".join(errors) if errors else ""
    return valid, invalid, error_msg


def validate_with_repair(
    llm_response: LLMResponse,
    schema_class: type[BaseModel],
    json_schema: dict[str, Any],
    llm_client: BaseLLMClient,
    max_retries: int = 2,
) -> ValidationResult:
    """Validate LLM output, retrying with repair prompts on failure.

    max_retries=2 means up to 3 total attempts (1 initial + 2 retries).
    """
    result = ValidationResult()
    result.all_responses.append(llm_response)

    current_text = llm_response.content
    attempt = 0

    while attempt <= max_retries:
        result.attempts = attempt + 1
        valid, invalid, error = validate_records(current_text, schema_class)

        if valid and not invalid and not error:
            result.validated = valid
            return result

        if valid and not error:
            result.validated = valid
            return result

        if attempt == max_retries:
            result.failed_raw = current_text
            result.error = error or "Validation failed after all retries"
            result.validated = valid
            return result

        logger.info("Validation failed (attempt %d/%d): %s", attempt + 1, max_retries + 1, error)
        repair_prompt = build_repair_prompt(error, current_text, json_schema)

        try:
            repair_response = llm_client.chat(SYSTEM_PROMPT, repair_prompt)
            result.all_responses.append(repair_response)
            current_text = repair_response.content
        except Exception as e:
            result.failed_raw = current_text
            result.error = f"Repair call failed: {e}"
            return result

        attempt += 1

    return result
