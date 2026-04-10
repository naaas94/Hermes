"""Format router: dispatches to the correct normalizer based on preflight results."""

from __future__ import annotations

from collections.abc import Callable
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
    file_path: Path,
    job_id: str,
    preflight: PreflightResult,
    page_indices: frozenset[int] | None = None,
    on_page_done: Callable[[int], None] | None = None,
) -> list[NormalizedPage]:
    """Route to the correct normalizer and return normalized pages.

    ``page_indices`` is 0-based PDF page indices or Excel sheet indices to include.
    ``None`` means process every page/sheet.

    ``on_page_done`` is invoked with the 0-based page/sheet index after each unit is
    written (for progress reporting; optional).
    """
    normalizer = _NORMALIZERS.get(preflight.file_type)
    if normalizer is None:
        raise ValueError(f"No normalizer for file type: {preflight.file_type}")
    return normalizer(
        file_path, job_id, page_indices=page_indices, on_page_done=on_page_done
    )
