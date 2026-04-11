"""Tests for scanned-PDF OCR path (mocked OCR; no surya/easyocr required)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes.config import HermesConfig, NormalizationConfig


def _one_page_blank_pdf(path: Path) -> None:
    import pymupdf

    doc = pymupdf.open()
    doc.new_page(width=200, height=200)
    doc.save(path)
    doc.close()


def test_normalize_pdf_ocr_with_mock_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    pdf_path = tmp_path / "blank.pdf"
    _one_page_blank_pdf(pdf_path)

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: tmp_path)

    def fake_ocr(_engine: str):
        def _run(img: bytes) -> tuple[str, float]:
            assert isinstance(img, bytes)
            assert len(img) > 0
            return ("Recognized line", 0.99)

        return _run

    monkeypatch.setattr("hermes.normalization.pdf_ocr._get_ocr_function", fake_ocr)

    cfg = HermesConfig(
        normalization=NormalizationConfig(ocr_engine="surya", ocr_timeout_seconds=0),
    )
    monkeypatch.setattr("hermes.normalization.pdf_ocr.load_config", lambda: cfg)

    from hermes.normalization.pdf_ocr import normalize_pdf_ocr

    pages = normalize_pdf_ocr(pdf_path, "job_ocr_mock")
    assert len(pages) == 1
    assert pages[0].page_index == 0
    text = pages[0].markdown_path.read_text(encoding="utf-8")
    assert "# Page 1" in text
    assert "Recognized line" in text


def test_ocr_timeout_returns_placeholder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    pdf_path = tmp_path / "blank.pdf"
    _one_page_blank_pdf(pdf_path)

    monkeypatch.setattr("hermes.config.get_storage_base", lambda: tmp_path)

    def slow_ocr(_engine: str):
        def _run(_img: bytes) -> tuple[str, float]:
            time.sleep(30.0)
            return ("never", 1.0)

        return _run

    monkeypatch.setattr("hermes.normalization.pdf_ocr._get_ocr_function", slow_ocr)

    cfg = HermesConfig(
        normalization=NormalizationConfig(ocr_engine="surya", ocr_timeout_seconds=1),
    )
    monkeypatch.setattr("hermes.normalization.pdf_ocr.load_config", lambda: cfg)

    from hermes.normalization.pdf_ocr import normalize_pdf_ocr

    t0 = time.perf_counter()
    with patch("hermes.normalization.pdf_ocr.logger.warning"):
        pages = normalize_pdf_ocr(pdf_path, "job_ocr_timeout")
    elapsed = time.perf_counter() - t0

    assert elapsed < 4.0, "should return soon after OCR timeout, not when sleep() ends"
    assert len(pages) == 1
    body = pages[0].markdown_path.read_text(encoding="utf-8")
    assert "timed out" in body.lower()
