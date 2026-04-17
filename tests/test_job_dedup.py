"""Tests for content-hash job deduplication and force_new_job."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.db import get_connection
from hermes.dedup import effective_llm_model, sha256_file_hex
from hermes.models import Chunk, LLMResponse


@pytest.fixture()
def mock_llm_response():
    # Minimal valid VehicleRecord (numero_serie is required).
    return LLMResponse(
        content=json.dumps([{"numero_serie": "JTDS4RCE1P0000001"}]),
        model="qwen3:4b",
        tokens_in=10,
        tokens_out=10,
        latency_ms=1,
    )


def test_sha256_file_hex_stable(tmp_path: Path) -> None:
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello")
    assert sha256_file_hex(p) == sha256_file_hex(p)


def test_effective_llm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from hermes.config import HermesConfig, LiteLLMConfig, LLMConfig

    base = HermesConfig(
        llm=LLMConfig(provider="ollama", model="m1"),
    )
    assert effective_llm_model(base, None) == "m1"
    assert effective_llm_model(base, "override") == "override"

    cloud = HermesConfig(
        llm=LLMConfig(
            provider="litellm",
            litellm=LiteLLMConfig(model="gpt-4o-mini"),
        ),
    )
    assert effective_llm_model(cloud, None) == "gpt-4o-mini"


def test_dedup_second_run_returns_same_job_id(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
) -> None:
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="only",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    schema = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        first = run_pipeline(sample_excel, schema_ref=schema)
        second = run_pipeline(sample_excel, schema_ref=schema)

    assert first == second
    assert mock_client.chat.call_count == 1

    conn = get_connection(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    conn.close()
    assert rows is not None and int(rows[0]) == 1


def test_force_new_job_creates_second_job(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
) -> None:
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="only",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    schema = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        first = run_pipeline(sample_excel, schema_ref=schema)
        second = run_pipeline(sample_excel, schema_ref=schema, force_new_job=True)

    assert first != second
    assert mock_client.chat.call_count == 2

    conn = get_connection(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
    conn.close()
    assert rows is not None and int(rows[0]) == 2


def test_dedup_different_pages_spec_not_reused(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
) -> None:
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="only",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    schema = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        a = run_pipeline(sample_excel, schema_ref=schema, pages_spec=None)
        b = run_pipeline(sample_excel, schema_ref=schema, pages_spec="1")

    assert a != b
    assert mock_client.chat.call_count == 2


def test_dedup_different_model_override_not_reused(
    sample_excel: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_llm_response: LLMResponse,
) -> None:
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    db_path = tmp_path / "test.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="only",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()
    mock_client.chat.return_value = mock_llm_response
    mock_client.check_ready.return_value = True

    schema = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        a = run_pipeline(sample_excel, schema_ref=schema, model_override="model-a")
        b = run_pipeline(sample_excel, schema_ref=schema, model_override="model-b")

    assert a != b
    assert mock_client.chat.call_count == 2
