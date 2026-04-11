"""Local object store for raw and normalized files."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from hermes.config import get_storage_base
from hermes.models import FileType, NormalizedPage

COPY_BUFFER = 8192


def _job_dir(job_id: str) -> Path:
    base = get_storage_base()
    d = base / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_raw(file_path: Path, job_id: str) -> Path:
    """Copy a file into the object store under {job_id}/raw/. Returns stored path."""
    raw_dir = _job_dir(job_id) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / file_path.name
    with open(file_path, "rb") as src, open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst, length=COPY_BUFFER)
    return dest


def get_normalized_dir(job_id: str) -> Path:
    d = _job_dir(job_id) / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_chunk_dir(job_id: str) -> Path:
    d = _job_dir(job_id) / "chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_raw_path(job_id: str, file_name: str) -> Path:
    """Path to the copied source file under `{storage}/{job_id}/raw/`."""
    return _job_dir(job_id) / "raw" / file_name


_NUM_SUFFIX = re.compile(r"^(\w+)_(\d+)\.md$")


def load_normalized_pages_from_store(
    job_id: str, file_type: FileType
) -> list[NormalizedPage]:
    """Rebuild `NormalizedPage` list from on-disk markdown (after a completed normalize).

    PDF normalizers write `page_{idx}.md`; Excel writes `sheet_{idx}.md`.
    """
    norm_dir = get_normalized_dir(job_id)
    if not norm_dir.is_dir():
        return []

    pages: list[NormalizedPage] = []
    if file_type == FileType.EXCEL:
        paths = sorted(
            norm_dir.glob("sheet_*.md"),
            key=lambda p: int(p.stem.split("_", 1)[1]),
        )
        for md_path in paths:
            m = _NUM_SUFFIX.match(md_path.name)
            if not m:
                continue
            idx = int(m.group(2))
            text = md_path.read_text(encoding="utf-8")
            pages.append(
                NormalizedPage(
                    page_index=idx,
                    markdown_path=md_path,
                    source_type=FileType.EXCEL,
                    char_count=len(text),
                )
            )
    elif file_type in (FileType.PDF_TEXT, FileType.PDF_SCANNED):
        paths = sorted(
            norm_dir.glob("page_*.md"),
            key=lambda p: int(p.stem.split("_", 1)[1]),
        )
        for md_path in paths:
            m = _NUM_SUFFIX.match(md_path.name)
            if not m:
                continue
            idx = int(m.group(2))
            text = md_path.read_text(encoding="utf-8")
            pages.append(
                NormalizedPage(
                    page_index=idx,
                    markdown_path=md_path,
                    source_type=file_type,
                    char_count=len(text),
                )
            )
    return pages
