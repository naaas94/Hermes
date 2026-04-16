"""Eval fixture manifest schema and YAML loader."""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("hermes.eval.manifest")

AddressingMode = Literal["chunk_index", "page_range", "mixed"]


class ChunkLabel(StrEnum):
    """Expected outcome class for a chunk."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class PageRange(BaseModel):
    """Inclusive 1-based PDF page interval (start <= end)."""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def coerce_from_sequence(cls, data: Any) -> Any:
        if isinstance(data, (list, tuple)) and len(data) == 2:
            return {"start": data[0], "end": data[1]}
        return data

    @model_validator(mode="after")
    def ordered(self) -> PageRange:
        if self.end < self.start:
            msg = "page_range end must be >= start"
            raise ValueError(msg)
        return self


class ChunkExpectation(BaseModel):
    """Per-chunk eval expectation; addressed by chunk index or page range."""

    chunk_index: int | None = Field(default=None, ge=0)
    page_range: PageRange | None = None
    label: ChunkLabel
    allow_empty: bool = True
    golden_path: str | None = None

    @model_validator(mode="after")
    def exactly_one_address(self) -> ChunkExpectation:
        has_ci = self.chunk_index is not None
        has_pr = self.page_range is not None
        if has_ci == has_pr:
            msg = "chunk expectation must set exactly one of chunk_index or page_range"
            raise ValueError(msg)
        return self


class EvalManifest(BaseModel):
    """YAML manifest describing a frozen eval fixture and chunk-level labels."""

    fixture_path: str
    schema_ref: str
    chunks: list[ChunkExpectation] = Field(min_length=1)
    golden_path: str | None = None
    modality: str | None = None
    notes: str | None = None
    addressing: AddressingMode = "mixed"

    @model_validator(mode="after")
    def addressing_matches_chunks(self) -> EvalManifest:
        if self.addressing == "chunk_index":
            for i, ch in enumerate(self.chunks):
                if ch.chunk_index is None:
                    msg = f"chunk {i}: addressing is chunk_index but page_range is set"
                    raise ValueError(msg)
        elif self.addressing == "page_range":
            for i, ch in enumerate(self.chunks):
                if ch.page_range is None:
                    msg = f"chunk {i}: addressing is page_range but chunk_index is set"
                    raise ValueError(msg)
        return self


def load_manifest(path: str | Path) -> EvalManifest:
    """Load and validate a ``.manifest.yaml`` file."""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        msg = "manifest is empty"
        raise ValueError(msg)
    if not isinstance(data, dict):
        msg = "manifest root must be a mapping"
        raise ValueError(msg)
    manifest = EvalManifest.model_validate(data)
    logger.debug("Loaded eval manifest fixture_path=%s", manifest.fixture_path)
    return manifest
