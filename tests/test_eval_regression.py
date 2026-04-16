"""Regression: eval infrastructure stays aligned with committed manifests + goldens."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes.eval.manifest import load_manifest
from hermes.eval.runner import ResultsMode, eval_outcomes_ok, run_eval_suite
from hermes.models import LLMResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "tests/fixtures/eval"

# Must match boilerplate in tests/generate_fixtures.py (negative chunk user prompt).
_BOILERPLATE_MARKER = "BOILERPLATE_EVAL_NEGATIVE"


@pytest.mark.parametrize(
    "manifest_name",
    ["sample_excel.manifest.yaml", "sample_pdf_text.manifest.yaml"],
)
def test_eval_regression_mocked_pipeline_matches_golden(
    manifest_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = EVAL_DIR / manifest_name
    if not manifest_path.is_file():
        pytest.skip("committed eval manifest missing")

    manifest = load_manifest(manifest_path)
    assert manifest.golden_path is not None
    golden_file = REPO_ROOT / manifest.golden_path
    if not golden_file.is_file():
        pytest.skip("golden file missing")
    lines = [ln.strip() for ln in golden_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records_pos = json.loads(lines[0])

    db_path = tmp_path / "reg.db"
    storage_path = tmp_path / "storage"
    storage_path.mkdir()
    monkeypatch.setattr("hermes.config.get_storage_base", lambda: storage_path)
    monkeypatch.setattr("hermes.config.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.db.get_db_path", lambda: db_path)
    monkeypatch.setattr("hermes.ingestion.storage.get_storage_base", lambda: storage_path)

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

    with patch("hermes.extraction.pipeline.create_llm_client", return_value=mock_client):
        outcomes = run_eval_suite(
            manifest_paths=[manifest_path],
            project_root=REPO_ROOT,
            results_mode=ResultsMode.PIPELINE,
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
