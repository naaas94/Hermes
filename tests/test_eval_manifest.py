"""Tests for eval manifest models and YAML loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hermes.eval.manifest import ChunkExpectation, ChunkLabel, infer_golden_base_dir, load_manifest


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


def test_manifest_loads_match_key(tmp_path: Path) -> None:
    g = tmp_path / "t.golden.jsonl"
    g.write_text(
        json.dumps([{"numero_serie": "VIN1", "make": "Ford"}]) + "\n[]\n",
        encoding="utf-8",
    )
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        f"""
fixture_path: x.xlsx
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
match_key: numero_serie
golden_path: {g.name}
chunks:
  - chunk_index: 0
    label: positive
  - chunk_index: 1
    label: negative
""",
    )
    m = load_manifest(path)
    assert m.match_key == "numero_serie"


def test_manifest_rejects_multi_record_golden_without_match_key(tmp_path: Path) -> None:
    g = tmp_path / "t.golden.jsonl"
    g.write_text(
        json.dumps([{"id": "a", "v": 1}, {"id": "b", "v": 2}]) + "\n[]\n",
        encoding="utf-8",
    )
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        f"""
fixture_path: x.xlsx
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
golden_path: {g.name}
chunks:
  - chunk_index: 0
    label: positive
  - chunk_index: 1
    label: negative
""",
    )
    with pytest.raises(
        ValidationError,
        match="match_key is required when a golden provides multiple records",
    ):
        load_manifest(path)


def test_manifest_rejects_match_key_missing_in_golden_row(tmp_path: Path) -> None:
    g = tmp_path / "t.golden.jsonl"
    g.write_text(json.dumps([{"make": "Ford"}]) + "\n[]\n", encoding="utf-8")
    path = _write(
        tmp_path,
        "f.manifest.yaml",
        f"""
fixture_path: x.xlsx
schema_ref: hermes.schemas.examples.vehicle_fleet:VehicleRecord
addressing: chunk_index
match_key: numero_serie
golden_path: {g.name}
chunks:
  - chunk_index: 0
    label: positive
  - chunk_index: 1
    label: negative
""",
    )
    with pytest.raises(ValidationError):
        load_manifest(path)


def test_manifest_match_key_requires_context_when_constructed_directly() -> None:
    with pytest.raises(ValidationError):
        from hermes.eval.manifest import EvalManifest

        EvalManifest(
            fixture_path="x",
            schema_ref="ref",
            addressing="chunk_index",
            match_key="numero_serie",
            chunks=[ChunkExpectation(chunk_index=0, label=ChunkLabel.POSITIVE)],
        )


def test_infer_golden_base_dir_finds_repo_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    p = sub / "m.manifest.yaml"
    p.write_text("{}", encoding="utf-8")
    assert infer_golden_base_dir(p) == tmp_path.resolve()


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
