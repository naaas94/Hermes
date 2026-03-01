"""Scanned PDF -> OCR -> Markdown normalizer.

Fallback chain: surya-ocr -> easyocr -> skip with warning.
Each page is rendered to a pixmap, OCR'd, and the pixmap is deleted immediately.
"""

from __future__ import annotations

import logging
from pathlib import Path

from hermes.config import load_config
from hermes.ingestion.storage import get_normalized_dir
from hermes.models import FileType, NormalizedPage

logger = logging.getLogger(__name__)


def normalize_pdf_ocr(file_path: Path, job_id: str) -> list[NormalizedPage]:
    """OCR each page of a scanned PDF and write Markdown to disk."""
    import pymupdf

    cfg = load_config().normalization
    out_dir = get_normalized_dir(job_id)
    pages: list[NormalizedPage] = []
    ocr_fn = _get_ocr_function(cfg.ocr_engine)

    doc = pymupdf.open(str(file_path))
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text, confidence = _ocr_page(
                page, ocr_fn, cfg.ocr_dpi, cfg.ocr_max_dpi, cfg.ocr_confidence_threshold
            )
            del page

            md_path = out_dir / f"page_{page_idx}.md"
            if text:
                content = f"# Page {page_idx + 1}\n\n{text}\n"
            else:
                content = f"# Page {page_idx + 1}\n\n*OCR unavailable or empty page*\n"

            md_path.write_text(content, encoding="utf-8")
            pages.append(
                NormalizedPage(
                    page_index=page_idx,
                    markdown_path=md_path,
                    source_type=FileType.PDF_SCANNED,
                    char_count=len(content),
                )
            )
    finally:
        doc.close()

    return pages


def _ocr_page(
    page,  # type: ignore[no-untyped-def]
    ocr_fn,  # type: ignore[no-untyped-def]
    start_dpi: int,
    max_dpi: int,
    confidence_threshold: float,
) -> tuple[str, float]:
    """Render a page at start_dpi, run OCR; retry at max_dpi if confidence is low."""
    text, confidence = _render_and_ocr(page, ocr_fn, start_dpi)

    if confidence < confidence_threshold and start_dpi < max_dpi:
        logger.info(
            "OCR confidence %.2f below threshold %.2f, retrying page at %d DPI",
            confidence, confidence_threshold, max_dpi,
        )
        text, confidence = _render_and_ocr(page, ocr_fn, max_dpi)

    return text, confidence


def _render_and_ocr(page, ocr_fn, dpi: int) -> tuple[str, float]:  # type: ignore[no-untyped-def]
    """Render page to pixmap and run OCR. Cleans up pixmap immediately."""
    mat = __import__("pymupdf").Matrix(dpi / 72, dpi / 72)
    pixmap = page.get_pixmap(matrix=mat)
    try:
        img_bytes = pixmap.tobytes("png")
    finally:
        del pixmap

    if ocr_fn is None:
        return "", 0.0

    return ocr_fn(img_bytes)


def _get_ocr_function(engine: str):  # type: ignore[no-untyped-def]
    """Return an OCR callable based on the configured engine, or None."""
    if engine == "none":
        return None

    if engine == "surya":
        try:
            return _ocr_with_surya
        except Exception:
            logger.warning("surya-ocr not available, trying easyocr fallback")
            engine = "easyocr"

    if engine == "easyocr":
        try:
            import easyocr  # noqa: F401
            return _ocr_with_easyocr
        except ImportError:
            logger.warning("easyocr not available, OCR disabled")
            return None

    logger.warning("Unknown OCR engine '%s', OCR disabled", engine)
    return None


def _ocr_with_surya(img_bytes: bytes) -> tuple[str, float]:
    """Run OCR using surya-ocr."""
    import io

    from PIL import Image
    from surya.model.detection.model import load_model as load_det_model
    from surya.model.detection.processor import load_processor as load_det_processor
    from surya.model.recognition.model import load_model as load_rec_model
    from surya.model.recognition.processor import load_processor as load_rec_processor
    from surya.ocr import run_ocr

    image = Image.open(io.BytesIO(img_bytes))

    det_model = load_det_model()
    det_processor = load_det_processor()
    rec_model = load_rec_model()
    rec_processor = load_rec_processor()

    results = run_ocr(
        [image], [["en", "es"]], det_model, det_processor, rec_model, rec_processor
    )

    lines: list[str] = []
    confidences: list[float] = []
    for page_result in results:
        for line in page_result.text_lines:
            lines.append(line.text)
            confidences.append(line.confidence)

    text = "\n".join(lines)
    avg_confidence = sum(confidences) / max(len(confidences), 1)
    return text, avg_confidence


def _ocr_with_easyocr(img_bytes: bytes) -> tuple[str, float]:
    """Run OCR using easyocr."""
    import easyocr

    reader = easyocr.Reader(["en", "es"], gpu=False)
    results = reader.readtext(img_bytes)

    lines: list[str] = []
    confidences: list[float] = []
    for _, text, conf in results:
        lines.append(text)
        confidences.append(conf)

    full_text = "\n".join(lines)
    avg_confidence = sum(confidences) / max(len(confidences), 1)
    return full_text, avg_confidence
