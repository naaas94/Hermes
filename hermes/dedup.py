"""Content hashing and LLM identity for job deduplication."""

from __future__ import annotations

import hashlib
from pathlib import Path

from hermes.config import HermesConfig

_READ_CHUNK = 1024 * 1024


def sha256_file_hex(file_path: Path) -> str:
    """Streaming SHA-256 of file contents; returns lowercase hex digest."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            block = f.read(_READ_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def effective_llm_model(cfg: HermesConfig, model_override: str | None) -> str:
    """Model string used for extraction and for dedup key matching."""
    if model_override and model_override.strip():
        return model_override.strip()
    if cfg.llm.provider == "litellm":
        return cfg.llm.litellm.model
    return cfg.llm.model
