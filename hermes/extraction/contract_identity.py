"""Canonical JSON Schema serialization and content-addressed extraction contract IDs.

``contract_id`` is ``"ctr_"`` plus the first 32 hex digits of::

    SHA256(
        utf8(canonical_json_string)
        + NUL
        + utf8(prompt_version)
        + NUL
        + utf8(schema_class)
    )

where ``canonical_json_string`` is produced with sorted keys and compact separators
so logically identical schemas hash the same regardless of key order in memory.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_schema(schema: dict[str, Any]) -> tuple[str, str]:
    """Return ``(canonical_json_string, sha256_hex)`` for a JSON Schema dict.

    Canonical form: sorted keys, no extra whitespace, non-ASCII preserved (ensure_ascii=False).
    The digest is SHA-256 over UTF-8 bytes of the canonical string.
    """
    s = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    b = s.encode("utf-8")
    digest = hashlib.sha256(b).hexdigest()
    return s, digest


def compute_contract_id(
    canonical_json_utf8: bytes, prompt_version: str, schema_class: str
) -> str:
    """Derive a stable ``contract_id`` from canonical schema bytes and metadata."""
    h = hashlib.sha256()
    h.update(canonical_json_utf8)
    h.update(b"\0")
    h.update(prompt_version.encode("utf-8"))
    h.update(b"\0")
    h.update(schema_class.encode("utf-8"))
    return "ctr_" + h.hexdigest()[:32]
