"""Eval fixture manifest schema and YAML loader."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationInfo, model_validator

logger = logging.getLogger("hermes.eval.manifest")

AddressingMode = Literal["chunk_index", "page_range", "mixed"]


def infer_golden_base_dir(manifest_path: Path) -> Path:
    """Directory used to resolve relative ``golden_path`` values (repo root or manifest parent)."""
    mp = manifest_path.resolve()
    cur = mp.parent
    for _ in range(12):
        if (cur / "pyproject.toml").is_file():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return mp.parent


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
    match_key: str | None = None

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

    @model_validator(mode="after")
    def match_key_requires_anchor_in_goldens(self, info: ValidationInfo) -> EvalManifest:
        if not self.match_key:
            return self
        ctx = info.context
        if not isinstance(ctx, dict):
            ctx = {}
        base = ctx.get("golden_base_dir")
        if base is None:
            msg = "golden_base_dir is required in validation context when match_key is set"
            raise ValueError(msg)
        err = validate_match_key_in_golden_files(self, Path(base))
        if err is not None:
            raise ValueError(err)
        return self

    @model_validator(mode="after")
    def multi_record_goldens_require_match_key(self, info: ValidationInfo) -> EvalManifest:
        """Reject manifests where multiset goldens would fall back to index-only pairing."""
        if self.match_key:
            return self
        ctx = info.context
        if not isinstance(ctx, dict):
            return self
        base = ctx.get("golden_base_dir")
        if base is None:
            return self
        base_dir = Path(base)
        for exp in self.chunks:
            recs, err = resolve_golden_records(self, exp, None, base_dir)
            if err is not None:
                continue
            if not recs:
                continue
            if len(recs) > 1:
                addr = (
                    f"chunk_index={exp.chunk_index}"
                    if exp.chunk_index is not None
                    else f"page_range={exp.page_range.start}-{exp.page_range.end}"
                )
                msg = (
                    "match_key is required when a golden provides multiple records "
                    f"({addr}); index-only pairing is not allowed for multiset goldens"
                )
                raise ValueError(msg)
        return self


def load_golden_line(path: Path, line_index: int) -> tuple[list[dict[str, Any]], str | None]:
    if not path.is_file():
        return [], f"golden file not found: {path}"
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_index < 0 or line_index >= len(lines):
        return [], f"golden line {line_index} missing in {path}"
    line = lines[line_index].strip()
    if not line:
        return [], f"empty golden line at index {line_index}"
    try:
        val: Any = json.loads(line)
    except json.JSONDecodeError as e:
        return [], str(e)
    if isinstance(val, list):
        rows = [x for x in val if isinstance(x, dict)]
        if len(rows) != len(val):
            return [], "golden array must contain only objects"
        return rows, None
    if isinstance(val, dict):
        return [val], None
    return [], "golden line must be a JSON object or array of objects"


def load_golden_file_whole(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load a chunk-specific golden file (single JSON object or one-line JSONL)."""
    if not path.is_file():
        return [], f"golden file not found: {path}"
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return [], "empty golden file"
    try:
        val: Any = json.loads(text)
    except json.JSONDecodeError:
        line = text.splitlines()[0].strip()
        try:
            val = json.loads(line)
        except json.JSONDecodeError as e:
            return [], str(e)
    if isinstance(val, list):
        rows = [x for x in val if isinstance(x, dict)]
        if len(rows) != len(val):
            return [], "golden array must contain only objects"
        return rows, None
    if isinstance(val, dict):
        return [val], None
    return [], "golden must be a JSON object or array of objects"


def resolve_golden_records(
    manifest: EvalManifest,
    expectation: ChunkExpectation,
    goldens: Mapping[int, Sequence[dict[str, Any]]] | None,
    base_dir: Path | None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Return expected records for this chunk, or None if no golden.

    On parse failure, returns an error string instead.
    """
    if goldens is not None and expectation.chunk_index is not None:
        if expectation.chunk_index in goldens:
            return list(goldens[expectation.chunk_index]), None

    rel: str | None = expectation.golden_path or manifest.golden_path
    if rel is None:
        return None, None

    path = Path(rel)
    if not path.is_file() and base_dir is not None:
        path = base_dir / rel
    if expectation.golden_path is not None:
        return load_golden_file_whole(path)
    if expectation.chunk_index is not None:
        return load_golden_line(path, expectation.chunk_index)
    return None, "golden_path requires chunk_index addressing"


def _anchor_absent(row: dict[str, Any], key: str) -> bool:
    if key not in row:
        return True
    v = row[key]
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def validate_match_key_in_golden_files(manifest: EvalManifest, base_dir: Path) -> str | None:
    """Return an error message if ``match_key`` is set but a golden row lacks that anchor."""
    mk = manifest.match_key
    if not mk:
        return None
    for exp in manifest.chunks:
        if exp.page_range is not None:
            continue
        recs, err = resolve_golden_records(manifest, exp, None, base_dir)
        if err is not None:
            return err
        if not recs:
            continue
        for i, row in enumerate(recs):
            if _anchor_absent(row, mk):
                return (
                    f"golden records for chunk_index={exp.chunk_index} row {i}: "
                    f"missing non-empty value for match_key={mk!r}"
                )
    return None


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
    gbase = infer_golden_base_dir(p)
    manifest = EvalManifest.model_validate(data, context={"golden_base_dir": gbase})
    logger.debug("Loaded eval manifest fixture_path=%s", manifest.fixture_path)
    return manifest
