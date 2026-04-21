"""A-04 integration: eval can score ``ResultsMode.FROM_JOB`` after ``resume_pipeline``.

Eval regression normally exercises ``ResultsMode.PIPELINE`` (fresh jobs). Production flows
may leave jobs **partial** and finish them with ``resume_pipeline``. This module proves the
harness accepts the same ``job_id`` and reads persisted extraction rows that were filled
across the initial run plus resume—so DB-backed scoring matches committed goldens when the
mock LLM returns golden-aligned JSON (no live API).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.db import get_connection, get_job, get_results_for_job, update_job_status
from hermes.eval.runner import ResultsMode, eval_outcomes_ok, run_eval_suite
from hermes.models import Chunk, JobStatus, LLMResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "tests/fixtures/eval"

# Must match boilerplate in tests/generate_fixtures.py (negative chunk user prompt).
_BOILERPLATE_MARKER = "BOILERPLATE_EVAL_NEGATIVE"


def test_eval_from_job_after_resume_matches_goldens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete a partial job via ``resume_pipeline``, then score with ``FROM_JOB`` (A-04).

    Covers the gap where eval usually runs against a newly completed pipeline job; here we
    delete one chunk's row, resume, and assert ``run_eval_suite`` still sees full DB state
    and matches the committed golden for ``sample_excel.manifest.yaml``.
    """
    manifest_path = EVAL_DIR / "sample_excel.manifest.yaml"
    fixture_path = REPO_ROOT / "tests/fixtures/eval/sample.xlsx"
    golden_path = REPO_ROOT / "tests/fixtures/eval/sample_excel.golden.jsonl"

    if not manifest_path.is_file() or not fixture_path.is_file() or not golden_path.is_file():
        pytest.skip("committed eval fixture missing")

    text = golden_path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    records_pos = json.loads(lines[0])

    db_path = tmp_path / "resume_eval.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()
    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

    def fake_chunk_pages(
        pages: object,
        context_window: int | None = None,
        overlap_ratio: float | None = None,
    ) -> list[Chunk]:
        return [
            Chunk(
                chunk_index=0,
                text="chunk zero text",
                source_pages=[0],
                estimated_tokens=50,
            ),
            Chunk(
                chunk_index=1,
                text=f"boilerplate sheet {_BOILERPLATE_MARKER}",
                source_pages=[0],
                estimated_tokens=50,
            ),
        ]

    mock_client = MagicMock()

    def _chat(system_prompt: str, user_prompt: str) -> LLMResponse:
        if _BOILERPLATE_MARKER in user_prompt:
            return LLMResponse(
                content="[]",
                model="mock",
                tokens_in=50,
                tokens_out=5,
                latency_ms=5,
            )
        return LLMResponse(
            content=json.dumps(records_pos),
            model="mock",
            tokens_in=100,
            tokens_out=100,
            latency_ms=10,
        )

    mock_client.chat.side_effect = _chat
    mock_client.check_ready.return_value = True

    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import run_pipeline

        job_id = run_pipeline(
            fixture_path,
            schema_ref="hermes.schemas.examples.vehicle_fleet:VehicleRecord",
        )

    assert mock_client.chat.call_count == 2

    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM extraction_results WHERE job_id = ? AND chunk_index = 1",
        (job_id,),
    )
    conn.commit()
    update_job_status(
        conn,
        job_id,
        JobStatus.PARTIAL,
        completed_chunks=1,
        failed_chunks=0,
    )
    conn.close()

    mock_client.reset_mock()
    with (
        patch("hermes.extraction.pipeline.chunk_pages", fake_chunk_pages),
        patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client),
    ):
        from hermes.extraction.pipeline import resume_pipeline

        resume_pipeline(job_id)

    assert mock_client.chat.call_count == 1

    conn = get_connection(db_path)
    job = get_job(conn, job_id)
    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert len(get_results_for_job(conn, job_id)) == 2
    conn.close()

    outcomes = run_eval_suite(
        manifest_paths=[manifest_path],
        project_root=REPO_ROOT,
        results_mode=ResultsMode.FROM_JOB,
        job_id=job_id,
    )

    assert len(outcomes) == 1
    o = outcomes[0]
    assert o.result.error is None
    assert o.result.summary is not None
    s = o.result.summary
    assert s.positive_passed == s.positive_total
    assert s.negative_total >= 1
    assert s.negative_false_positive_rate == 0.0
    assert s.field_level_accuracy == 1.0
    assert eval_outcomes_ok(outcomes) is True
