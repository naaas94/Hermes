"""PDF text-layer -> Markdown normalizer using pymupdf (page-by-page)."""

from __future__ import annotations

from pathlib import Path

from hermes.ingestion.storage import get_normalized_dir
from hermes.models import FileType, NormalizedPage


def normalize_pdf_text(file_path: Path, job_id: str) -> list[NormalizedPage]:
    """Extract text from each PDF page and write to individual Markdown files.

    Pages are processed one at a time and the page object is released immediately
    to keep memory bounded.
    """
    import pymupdf

    out_dir = get_normalized_dir(job_id)
    pages: list[NormalizedPage] = []

    doc = pymupdf.open(str(file_path))
    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            text = page.get_text("text").strip()
            del page

            md_path = out_dir / f"page_{page_idx}.md"
            content = f"# Page {page_idx + 1}\n\n{text}\n"
            md_path.write_text(content, encoding="utf-8")

            pages.append(
                NormalizedPage(
                    page_index=page_idx,
                    markdown_path=md_path,
                    source_type=FileType.PDF_TEXT,
                    char_count=len(content),
                )
            )
    finally:
        doc.close()

    return pages
