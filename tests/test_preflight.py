"""Tests for preflight file classification."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.models import FileType


def test_detect_excel(sample_excel: Path):
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")
    from hermes.ingestion.preflight import detect_file_type
    assert detect_file_type(sample_excel) == FileType.EXCEL


def test_detect_pdf_text(sample_pdf_text: Path):
    if not sample_pdf_text.exists():
        pytest.skip("Run generate_fixtures.py first")
    from hermes.ingestion.preflight import detect_file_type
    assert detect_file_type(sample_pdf_text) == FileType.PDF_TEXT


def test_detect_unknown(tmp_path: Path):
    unknown = tmp_path / "file.txt"
    unknown.write_text("hello")
    from hermes.ingestion.preflight import detect_file_type
    assert detect_file_type(unknown) == FileType.UNKNOWN


def test_preflight_excel(sample_excel: Path):
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")
    from hermes.ingestion.preflight import run_preflight
    result = run_preflight(sample_excel)
    assert result.file_type == FileType.EXCEL
    assert result.page_count >= 1
    assert result.file_name == "sample.xlsx"


def test_preflight_pdf(sample_pdf_text: Path):
    if not sample_pdf_text.exists():
        pytest.skip("Run generate_fixtures.py first")
    from hermes.ingestion.preflight import run_preflight
    result = run_preflight(sample_pdf_text)
    assert result.file_type == FileType.PDF_TEXT
    assert result.page_count == 2
    assert result.has_text_layer is True


def test_preflight_missing_file():
    from hermes.ingestion.preflight import run_preflight
    with pytest.raises(FileNotFoundError):
        run_preflight(Path("/nonexistent/file.pdf"))
