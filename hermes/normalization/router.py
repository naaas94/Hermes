"""Format router: dispatches to the correct normalizer based on preflight results."""

from __future__ import annotations

from pathlib import Path

from hermes.models import FileType, NormalizedPage, PreflightResult
from hermes.normalization.excel import normalize_excel
from hermes.normalization.pdf_ocr import normalize_pdf_ocr
from hermes.normalization.pdf_text import normalize_pdf_text

_NORMALIZERS = {
    FileType.EXCEL: normalize_excel,
    FileType.PDF_TEXT: normalize_pdf_text,
    FileType.PDF_SCANNED: normalize_pdf_ocr,
}


def route_normalizer(
    file_path: Path, job_id: str, preflight: PreflightResult
) -> list[NormalizedPage]:
    """Route to the correct normalizer and return normalized pages."""
    normalizer = _NORMALIZERS.get(preflight.file_type)
    if normalizer is None:
        raise ValueError(f"No normalizer for file type: {preflight.file_type}")
    return normalizer(file_path, job_id)
