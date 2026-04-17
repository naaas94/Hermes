"""Tests for eval manifest models and YAML loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, load_manifest


def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


def test_manifest_loads_valid_chunk_index(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: tests/fixtures/eval/sample.xlsx
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
golden_path: tests/fixtures/eval/sample.golden.jsonl
modality: excel
notes: smoke
chunks:
  - chunk_index: 0
    label: positive
  - chunk_index: 1
    label: negative
    allow_empty: true
""",
    )
    m = load_manifest(path)
    assert m.fixture_path == "tests/fixtures/eval/sample.xlsx"
    assert m.schema_ref == "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
    assert m.golden_path == "tests/fixtures/eval/sample.golden.jsonl"
    assert m.modality == "excel"
    assert m.notes == "smoke"
    assert m.addressing == "chunk_index"
    assert len(m.chunks) == 2
    assert m.chunks[0].chunk_index == 0
    assert m.chunks[0].label == ChunkLabel.POSITIVE
    assert m.chunks[1].label == ChunkLabel.NEGATIVE
    assert m.chunks[1].allow_empty is True


def test_manifest_loads_valid_page_range(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: tests/fixtures/eval/sample_text.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: page_range
chunks:
  - page_range: [1, 3]
    label: positive
""",
    )
    m = load_manifest(path)
    assert m.addressing == "page_range"
    assert m.chunks[0].page_range is not None
    assert m.chunks[0].page_range.start == 1
    assert m.chunks[0].page_range.end == 3


def test_manifest_loads_mixed_addressing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: a.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: mixed
chunks:
  - chunk_index: 0
    label: positive
  - page_range:
        start: 2
        end: 2
    label: negative
""",
    )
    m = load_manifest(path)
    assert m.addressing == "mixed"
    assert m.chunks[0].chunk_index == 0
    assert m.chunks[1].page_range is not None
    assert m.chunks[1].page_range.end == 2


def test_manifest_load_manifest_rejects_empty_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "empty.manifest.yaml", "")
    with pytest.raises(ValueError, match="empty"):
        load_manifest(path)


def test_manifest_load_manifest_rejects_non_mapping(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.manifest.yaml", "- not a mapping")
    with pytest.raises(ValueError, match="mapping"):
        load_manifest(path)


def test_manifest_load_manifest_rejects_invalid_yaml(tmp_path: Path) -> None:
    path = _write(tmp_path, "broken.manifest.yaml", "chunks: [\n")
    with pytest.raises(yaml.YAMLError):
        load_manifest(path)


def test_manifest_rejects_both_chunk_index_and_page_range() -> None:
    with pytest.raises(ValidationError):
        ChunkExpectation(
            chunk_index=0,
            page_range={"start": 1, "end": 1},
            label=ChunkLabel.POSITIVE,
        )


def test_manifest_rejects_neither_chunk_index_nor_page_range() -> None:
    with pytest.raises(ValidationError):
        ChunkExpectation(label=ChunkLabel.POSITIVE)


def test_manifest_rejects_page_range_end_before_start() -> None:
    with pytest.raises(ValidationError):
        ChunkExpectation(
            page_range={"start": 3, "end": 1},
            label=ChunkLabel.POSITIVE,
        )


def test_manifest_rejects_addressing_chunk_index_with_page_range_chunk(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: x.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
chunks:
  - page_range: [1, 1]
    label: positive
""",
    )
    with pytest.raises(ValidationError):
        load_manifest(path)


def test_manifest_rejects_addressing_page_range_with_chunk_index_chunk(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: x.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: page_range
chunks:
  - chunk_index: 0
    label: positive
""",
    )
    with pytest.raises(ValidationError):
        load_manifest(path)


def test_manifest_eval_manifest_requires_chunks(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: x.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
chunks: []
""",
    )
    with pytest.raises(ValidationError):
        load_manifest(path)


def test_manifest_chunk_golden_path_override(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        """
fixture_path: x.pdf
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
chunks:
  - chunk_index: 0
    label: positive
    golden_path: override.jsonl
""",
    )
    m = load_manifest(path)
    assert m.chunks[0].golden_path == "override.jsonl"
