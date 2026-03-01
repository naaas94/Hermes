"""Prompt builder with SHA-256 versioning."""

from __future__ import annotations

import hashlib
from typing import Any

SYSTEM_PROMPT = (
    "You are a document data extractor. Given raw text from a document, extract all "
    "records that match the provided JSON schema. Return a JSON array of objects. "
    "Do not invent data not present in the text. If a field cannot be determined, use null."
)

USER_PROMPT_TEMPLATE = """\
## Target Schema

```json
{json_schema}
```

## Document Text

{chunk_text}

## Instructions

Extract all records from the document text above that match the target schema.
Return ONLY a JSON array of objects. Each object must conform to the schema.
If a field's value cannot be determined from the text, set it to null.
Do not include any explanation — only the JSON array."""

REPAIR_PROMPT_TEMPLATE = """\
The following JSON output did not match the required schema.

## Error
{error}

## Original Output
```json
{raw_output}
```

## Target Schema
```json
{json_schema}
```

Fix the JSON so it conforms to the schema. Return ONLY the corrected JSON array."""


def build_user_prompt(json_schema: dict[str, Any], chunk_text: str) -> str:
    import json
    schema_str = json.dumps(json_schema, indent=2)
    return USER_PROMPT_TEMPLATE.format(json_schema=schema_str, chunk_text=chunk_text)


def build_repair_prompt(
    error: str, raw_output: str, json_schema: dict[str, Any]
) -> str:
    import json
    schema_str = json.dumps(json_schema, indent=2)
    return REPAIR_PROMPT_TEMPLATE.format(
        error=error, raw_output=raw_output, json_schema=schema_str
    )


def prompt_version(system_prompt: str, user_prompt_template: str) -> str:
    """SHA-256 hash of the combined prompt templates for versioning."""
    combined = system_prompt + "\n---\n" + user_prompt_template
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def get_current_prompt_version() -> str:
    return prompt_version(SYSTEM_PROMPT, USER_PROMPT_TEMPLATE)
