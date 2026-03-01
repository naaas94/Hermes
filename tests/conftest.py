"""Shared pytest fixtures for Hermes tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hermes.db import init_db


@pytest.fixture()
def tmp_db(tmp_path: Path) -> sqlite3.Connection:
    """Create a temporary SQLite database with migrations applied."""
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    yield conn
    conn.close()


@pytest.fixture()
def tmp_storage(tmp_path: Path) -> Path:
    """Create a temporary storage directory."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture()
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture()
def sample_excel(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample.xlsx"


@pytest.fixture()
def sample_pdf_text(fixtures_dir: Path) -> Path:
    return fixtures_dir / "sample_text.pdf"
