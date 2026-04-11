"""Tests for Hermes local object store helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.ingestion.storage import load_normalized_pages_from_store
from hermes.models import FileType


def test_load_normalized_pages_excel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: tmp_path)
    job_id = "jobexcel"
    norm = tmp_path / job_id / "normalized"
    norm.mkdir(parents=True)
    (norm / "sheet_0.md").write_text("# Sheet\n\n|a|b|\n", encoding="utf-8")
    (norm / "sheet_1.md").write_text("# Other\n", encoding="utf-8")

    pages = load_normalized_pages_from_store(job_id, FileType.EXCEL)
    assert [p.page_index for p in pages] == [0, 1]
    assert pages[0].source_type == FileType.EXCEL


def test_load_normalized_pages_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: tmp_path)
    job_id = "jobpdf"
    norm = tmp_path / job_id / "normalized"
    norm.mkdir(parents=True)
    (norm / "page_0.md").write_text("# Page 1\n\nHello", encoding="utf-8")

    pages = load_normalized_pages_from_store(job_id, FileType.PDF_TEXT)
    assert len(pages) == 1
    assert pages[0].page_index == 0
    assert pages[0].source_type == FileType.PDF_TEXT


def test_load_normalized_empty_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: tmp_path)
    assert load_normalized_pages_from_store("none", FileType.EXCEL) == []
