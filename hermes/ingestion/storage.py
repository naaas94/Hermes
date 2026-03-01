"""Local object store for raw and normalized files."""

from __future__ import annotations

import shutil
from pathlib import Path

from hermes.config import get_storage_base

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


def read_raw(uri: Path) -> Path:
    """Return the path if it exists, raise otherwise."""
    if not uri.exists():
        raise FileNotFoundError(f"Raw file not found: {uri}")
    return uri


def get_normalized_dir(job_id: str) -> Path:
    d = _job_dir(job_id) / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_chunk_dir(job_id: str) -> Path:
    d = _job_dir(job_id) / "chunks"
    d.mkdir(parents=True, exist_ok=True)
    return d
