"""Smoke tests for Typer CLI (no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hermes import __version__
from hermes.db import create_job, init_db, save_result
from hermes.models import ExtractionResult, FileType, Job, JobStatus


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


def test_cli_version(cli_runner: CliRunner):
    from hermes.cli import app

    result = cli_runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert f"Hermes v{__version__}" in result.stdout


def test_cli_init_creates_config_and_db(
    cli_runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    db_path = fake_home / ".hermes" / "hermes.db"
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)

    from hermes.cli import app

    result = cli_runner.invoke(app, ["init"])
    assert result.exit_code == 0
    assert (fake_home / ".hermes" / "config.toml").exists()
    assert db_path.exists()


def test_cli_export_jsonl(
    cli_runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "hermes.db"
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)

    conn = init_db(db_path)
    job = Job(
        id="export_cli_job",
        file_name="t.pdf",
        file_type=FileType.PDF_TEXT,
        schema_class="x:Y",
        status=JobStatus.COMPLETED,
    )
    create_job(conn, job)
    save_result(
        conn,
        ExtractionResult(
            job_id="export_cli_job",
            chunk_index=0,
            source_pages="0",
            record_json=json.dumps([{"sku": "A1", "qty": 2}]),
            model="m",
            prompt_version="v",
        ),
    )
    conn.close()

    from hermes.cli import app

    out_file = tmp_path / "out.jsonl"
    result = cli_runner.invoke(
        app,
        ["export", "export_cli_job", "-o", str(out_file), "-f", "jsonl"],
    )
    assert result.exit_code == 0
    lines = out_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"sku": "A1", "qty": 2}


def test_cli_export_unknown_format_exits_nonzero(cli_runner: CliRunner):
    from hermes.cli import app

    result = cli_runner.invoke(
        app,
        ["export", "any-id", "-f", "xml"],
    )
    assert result.exit_code == 1
    assert "Unknown format" in result.stdout
