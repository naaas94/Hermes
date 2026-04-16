"""Smoke tests for committed eval fixtures (manifests + goldens)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes.eval.manifest import load_manifest
from hermes.eval.scorer import REASON_MATCH, score_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sample_excel_manifest():
    p = REPO_ROOT / "tests/fixtures/eval/sample_excel.manifest.yaml"
    if not p.is_file():
        pytest.skip("committed eval manifest missing")
    return load_manifest(p)


@pytest.fixture(scope="module")
def sample_pdf_manifest():
    p = REPO_ROOT / "tests/fixtures/eval/sample_pdf_text.manifest.yaml"
    if not p.is_file():
        pytest.skip("committed eval manifest missing")
    return load_manifest(p)


def test_eval_fixture_files_exist(sample_excel_manifest, sample_pdf_manifest) -> None:
    for m in (sample_excel_manifest, sample_pdf_manifest):
        assert (REPO_ROOT / m.fixture_path).is_file()
        assert m.golden_path is not None
        assert (REPO_ROOT / m.golden_path).is_file()


def test_eval_fixture_golden_lines_are_json_arrays(sample_excel_manifest, sample_pdf_manifest) -> None:
    for m in (sample_excel_manifest, sample_pdf_manifest):
        assert m.golden_path is not None
        text = (REPO_ROOT / m.golden_path).read_text(encoding="utf-8").strip()
        for line in text.splitlines():
            val = json.loads(line)
            assert isinstance(val, list)
            assert all(isinstance(x, dict) for x in val)


def test_eval_fixture_golden_self_match_excel(sample_excel_manifest) -> None:
    assert sample_excel_manifest.golden_path is not None
    raw = (REPO_ROOT / sample_excel_manifest.golden_path).read_text(encoding="utf-8")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    expected0 = json.loads(lines[0])
    expected1 = json.loads(lines[1])
    job = [
        {"chunk_index": 0, "record_json": json.dumps(expected0)},
        {"chunk_index": 1, "record_json": json.dumps(expected1)},
    ]
    r = score_fixture(sample_excel_manifest, job, None, golden_base_dir=REPO_ROOT)
    assert r.error is None
    assert r.chunks[0].passed is True
    assert r.chunks[0].reason == REASON_MATCH
    assert r.chunks[1].passed is True


def test_eval_fixture_golden_self_match_pdf(sample_pdf_manifest) -> None:
    assert sample_pdf_manifest.golden_path is not None
    raw = (REPO_ROOT / sample_pdf_manifest.golden_path).read_text(encoding="utf-8")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    expected0 = json.loads(lines[0])
    expected1 = json.loads(lines[1])
    job = [
        {"chunk_index": 0, "record_json": json.dumps(expected0)},
        {"chunk_index": 1, "record_json": json.dumps(expected1)},
    ]
    r = score_fixture(sample_pdf_manifest, job, None, golden_base_dir=REPO_ROOT)
    assert r.error is None
    assert r.chunks[0].passed is True
    assert r.chunks[0].reason == REASON_MATCH
    assert r.chunks[1].passed is True
