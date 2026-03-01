"""Tests for normalization and chunking."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.models import FileType, NormalizedPage


def test_normalize_excel(sample_excel: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if not sample_excel.exists():
        pytest.skip("Run generate_fixtures.py first")

    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: tmp_path)

    from hermes.normalization.excel import normalize_excel
    pages = normalize_excel(sample_excel, "test_job")

    assert len(pages) >= 1
    assert pages[0].source_type == FileType.EXCEL
    assert pages[0].markdown_path.exists()

    content = pages[0].markdown_path.read_text(encoding="utf-8")
    assert "Toyota" in content
    assert "|" in content


def test_normalize_pdf_text(sample_pdf_text: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if not sample_pdf_text.exists():
        pytest.skip("Run generate_fixtures.py first")

    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: tmp_path)

    from hermes.normalization.pdf_text import normalize_pdf_text
    pages = normalize_pdf_text(sample_pdf_text, "test_job")

    assert len(pages) == 2
    assert pages[0].source_type == FileType.PDF_TEXT

    content = pages[0].markdown_path.read_text(encoding="utf-8")
    assert "Toyota" in content or "FLOTILLA" in content


def test_chunker_merges_small_pages(tmp_path: Path):
    from hermes.normalization.chunker import chunk_pages

    pages = []
    for i in range(5):
        p = tmp_path / f"page_{i}.md"
        p.write_text(f"Short content for page {i}.\n", encoding="utf-8")
        pages.append(NormalizedPage(
            page_index=i, markdown_path=p,
            source_type=FileType.PDF_TEXT, char_count=30,
        ))

    chunks = chunk_pages(pages, context_window=8192, overlap_ratio=0.1)
    assert len(chunks) == 1
    assert len(chunks[0].source_pages) == 5


def test_chunker_splits_large_page(tmp_path: Path):
    from hermes.normalization.chunker import chunk_pages

    p = tmp_path / "big_page.md"
    p.write_text("X" * 40000, encoding="utf-8")

    pages = [NormalizedPage(
        page_index=0, markdown_path=p,
        source_type=FileType.PDF_TEXT, char_count=40000,
    )]

    # context_window=1000 tokens = ~4000 chars, so 40000 chars should split
    chunks = chunk_pages(pages, context_window=1000, overlap_ratio=0.1)
    assert len(chunks) > 1


def test_chunker_empty_pages():
    from hermes.normalization.chunker import chunk_pages
    chunks = chunk_pages([], context_window=8192)
    assert chunks == []
