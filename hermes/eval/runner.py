"""Eval runner: load manifests, obtain job results, score, optional golden updates."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from hermes.eval.manifest import EvalManifest, load_manifest
from hermes.eval.scorer import EvalResult, score_fixture

logger = logging.getLogger("hermes.eval.runner")


class ResultsMode(str, Enum):
    """How job results are obtained for scoring."""

    PIPELINE = "pipeline"
    FROM_JOB = "from_job"
    FROM_JSONL = "from_jsonl"


@dataclass(frozen=True)
class ManifestEvalOutcome:
    """One manifest evaluated end-to-end."""

    manifest_path: Path
    fixture_resolved: Path | None
    job_id: str | None
    result: EvalResult


def discover_manifest_paths(fixture_dir: Path) -> list[Path]:
    """Return sorted paths to ``*.manifest.yaml`` under ``fixture_dir``."""
    if not fixture_dir.is_dir():
        return []
    return sorted(fixture_dir.glob("*.manifest.yaml"))


def resolve_fixture_path(manifest: EvalManifest, project_root: Path) -> Path:
    """Resolve ``manifest.fixture_path`` against ``project_root``."""
    p = Path(manifest.fixture_path)
    if p.is_absolute():
        return p
    return (project_root / p).resolve()


def resolve_golden_base_dir(manifest_path: Path, project_root: Path) -> Path:
    """Directory used as ``golden_base_dir`` for relative golden paths in manifests."""
    _ = manifest_path  # reserved for future manifest-adjacent resolution
    return project_root


def job_results_from_db_rows(rows: list[Any]) -> list[dict[str, Any]]:
    """Build ``score_fixture`` job rows from ``ExtractionResult``-like objects."""
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "chunk_index": int(r.chunk_index),
                "record_json": r.record_json,
                "validation_passed": True,
            },
        )
    return out


def load_job_results_from_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    Load job-result rows from a JSONL file.

    Each non-empty line must be a JSON object with ``chunk_index`` and either
    ``record_json`` (string) or ``records`` (list of dicts). Optional
    ``validation_passed`` (bool) is honored.
    """
    text = path.read_text(encoding="utf-8")
    out: list[dict[str, Any]] = []
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            msg = f"JSONL line {i + 1} invalid JSON: {e}"
            raise ValueError(msg) from e
        if not isinstance(row, dict):
            msg = f"JSONL line {i + 1} must be a JSON object"
            raise ValueError(msg)
        if "chunk_index" not in row:
            msg = f"JSONL line {i + 1} missing chunk_index"
            raise ValueError(msg)
        out.append(row)
    return out


def _parse_records_from_job_row(row: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    from hermes.eval.scorer import _parse_record_json

    if "records" in row and row["records"] is not None:
        raw = row["records"]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)], None
        return [], "records must be a list"
    if "record_json" in row and row["record_json"] is not None:
        return _parse_record_json(str(row["record_json"]))
    return [], None


def apply_golden_updates(
    manifest: EvalManifest,
    job_results: list[dict[str, Any]],
    *,
    project_root: Path,
) -> None:
    """Overwrite golden files/lines from current job output (used with ``--update-goldens``)."""
    job_index: dict[int, dict[str, Any]] = {}
    for row in job_results:
        if "chunk_index" not in row:
            continue
        job_index[int(row["chunk_index"])] = row

    # Chunk-exclusive golden files (per-chunk ``golden_path``).
    for exp in manifest.chunks:
        if exp.chunk_index is None or exp.golden_path is None:
            continue
        ci = exp.chunk_index
        if ci not in job_index:
            logger.warning(
                "skip golden update: missing chunk_index=%s fixture=%s",
                ci,
                manifest.fixture_path,
            )
            continue
        p = Path(exp.golden_path)
        if not p.is_absolute():
            p = project_root / p
        recs, err = _parse_records_from_job_row(job_index[ci])
        if err:
            logger.warning(
                "skip golden update chunk_index=%s parse error=%s fixture=%s",
                ci,
                err,
                manifest.fixture_path,
            )
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(recs, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info(
            "updated golden file fixture=%s chunk_index=%s path=%s",
            manifest.fixture_path,
            ci,
            p,
        )

    # Shared ``manifest.golden_path`` JSONL: one line per ``chunk_index``.
    if manifest.golden_path is None:
        return

    mg_path = Path(manifest.golden_path)
    if not mg_path.is_absolute():
        mg_path = project_root / mg_path

    chunk_indices: list[int] = [
        int(exp.chunk_index)
        for exp in manifest.chunks
        if exp.chunk_index is not None and exp.golden_path is None
    ]
    if not chunk_indices:
        return

    max_line = max(chunk_indices)
    lines: list[str] = []
    if mg_path.is_file():
        lines = mg_path.read_text(encoding="utf-8").splitlines()
    while len(lines) <= max_line:
        lines.append("")

    for ci in chunk_indices:
        if ci not in job_index:
            continue
        recs, err = _parse_records_from_job_row(job_index[ci])
        if err:
            logger.warning(
                "skip manifest golden line update chunk_index=%s error=%s",
                ci,
                err,
            )
            continue
        lines[ci] = json.dumps(recs, ensure_ascii=False)

    mg_path.parent.mkdir(parents=True, exist_ok=True)
    mg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info(
        "updated manifest golden_path fixture=%s path=%s",
        manifest.fixture_path,
        mg_path,
    )


def load_manifest_or_error(path: Path) -> tuple[EvalManifest | None, EvalResult | None]:
    """Return ``(manifest, None)`` or ``(None, EvalResult(error=...))``."""
    try:
        m = load_manifest(path)
    except FileNotFoundError as e:
        return None, EvalResult(error=f"manifest not found: {e}")
    except (OSError, ValueError, TypeError) as e:
        return None, EvalResult(error=f"manifest invalid: {e}")
    return m, None


def score_manifest_with_results(
    manifest: EvalManifest,
    manifest_path: Path,
    job_results: list[dict[str, Any]],
    *,
    project_root: Path,
) -> EvalResult:
    """Run ``score_fixture`` with ``golden_base_dir`` set to ``project_root``."""
    fixture = resolve_fixture_path(manifest, project_root)
    if not fixture.is_file():
        return EvalResult(error=f"fixture file missing: {fixture}")
    return score_fixture(
        manifest,
        job_results,
        goldens=None,
        golden_base_dir=resolve_golden_base_dir(manifest_path, project_root),
    )


def run_eval_suite(
    *,
    manifest_paths: list[Path],
    project_root: Path,
    results_mode: ResultsMode,
    job_id: str | None = None,
    jsonl_path: Path | None = None,
    model_override: str | None = None,
    update_goldens: bool = False,
    skip_update_confirm: bool = False,
    confirm_fn: Any | None = None,
) -> list[ManifestEvalOutcome]:
    """
    Evaluate each manifest: obtain job results, score, optionally update goldens.

    ``confirm_fn`` is optional ``callable(str) -> bool`` for ``--update-goldens``
    (defaults to printing a warning and skipping update if unset and not
    ``skip_update_confirm``).
    """
    if results_mode is ResultsMode.FROM_JOB:
        if not job_id or not str(job_id).strip():
            raise ValueError("job_id is required when results_mode is FROM_JOB")
        if len(manifest_paths) != 1:
            raise ValueError("--from-results requires exactly one --manifest")
    if results_mode is ResultsMode.FROM_JSONL:
        if jsonl_path is None:
            raise ValueError("jsonl_path is required when results_mode is FROM_JSONL")
        if len(manifest_paths) != 1:
            raise ValueError("--from-jsonl requires exactly one --manifest")

    outcomes: list[ManifestEvalOutcome] = []

    if results_mode is ResultsMode.FROM_JOB:
        from hermes.db import get_results_for_job, open_db  # noqa: PLC0415

        mp = manifest_paths[0]
        loaded, err = load_manifest_or_error(mp)
        if err is not None:
            outcomes.append(
                ManifestEvalOutcome(
                    manifest_path=mp,
                    fixture_resolved=None,
                    job_id=job_id,
                    result=err,
                ),
            )
            return outcomes
        assert loaded is not None
        with open_db() as conn:
            rows = get_results_for_job(conn, str(job_id).strip())
        job_results = job_results_from_db_rows(rows)
        res = score_manifest_with_results(
            loaded,
            mp,
            job_results,
            project_root=project_root,
        )
        fix = resolve_fixture_path(loaded, project_root)
        outcomes.append(
            ManifestEvalOutcome(
                manifest_path=mp,
                fixture_resolved=fix,
                job_id=str(job_id).strip(),
                result=res,
            ),
        )
        if update_goldens and res.error is None:
            _confirm_and_apply_goldens(
                loaded,
                job_results,
                project_root=project_root,
                skip_update_confirm=skip_update_confirm,
                confirm_fn=confirm_fn,
            )
        return outcomes

    if results_mode is ResultsMode.FROM_JSONL:
        assert jsonl_path is not None
        mp = manifest_paths[0]
        loaded, err = load_manifest_or_error(mp)
        if err is not None:
            outcomes.append(
                ManifestEvalOutcome(
                    manifest_path=mp,
                    fixture_resolved=None,
                    job_id=None,
                    result=err,
                ),
            )
            return outcomes
        assert loaded is not None
        try:
            job_results = load_job_results_from_jsonl(jsonl_path)
        except ValueError as e:
            outcomes.append(
                ManifestEvalOutcome(
                    manifest_path=mp,
                    fixture_resolved=None,
                    job_id=None,
                    result=EvalResult(error=str(e)),
                ),
            )
            return outcomes
        res = score_manifest_with_results(
            loaded,
            mp,
            job_results,
            project_root=project_root,
        )
        fix = resolve_fixture_path(loaded, project_root)
        outcomes.append(
            ManifestEvalOutcome(
                manifest_path=mp,
                fixture_resolved=fix,
                job_id=None,
                result=res,
            ),
        )
        if update_goldens and res.error is None:
            _confirm_and_apply_goldens(
                loaded,
                job_results,
                project_root=project_root,
                skip_update_confirm=skip_update_confirm,
                confirm_fn=confirm_fn,
            )
        return outcomes

    # PIPELINE
    for mp in manifest_paths:
        loaded, err = load_manifest_or_error(mp)
        if err is not None:
            outcomes.append(
                ManifestEvalOutcome(
                    manifest_path=mp,
                    fixture_resolved=None,
                    job_id=None,
                    result=err,
                ),
            )
            continue
        assert loaded is not None
        fix = resolve_fixture_path(loaded, project_root)
        if not fix.is_file():
            outcomes.append(
                ManifestEvalOutcome(
                    manifest_path=mp,
                    fixture_resolved=fix,
                    job_id=None,
                    result=EvalResult(error=f"fixture file missing: {fix}"),
                ),
            )
            continue

        from hermes.extraction.pipeline import run_pipeline  # noqa: PLC0415

        jid = run_pipeline(
            fix,
            schema_ref=loaded.schema_ref,
            model_override=model_override,
            max_workers=1,
            pages_spec=None,
            force_new_job=True,
        )
        from hermes.db import get_results_for_job, open_db  # noqa: PLC0415

        with open_db() as conn:
            rows = get_results_for_job(conn, jid)
        job_results = job_results_from_db_rows(rows)
        res = score_manifest_with_results(
            loaded,
            mp,
            job_results,
            project_root=project_root,
        )
        outcomes.append(
            ManifestEvalOutcome(
                manifest_path=mp,
                fixture_resolved=fix,
                job_id=jid,
                result=res,
            ),
        )
        if update_goldens and res.error is None:
            _confirm_and_apply_goldens(
                loaded,
                job_results,
                project_root=project_root,
                skip_update_confirm=skip_update_confirm,
                confirm_fn=confirm_fn,
            )
    return outcomes


def _confirm_and_apply_goldens(
    manifest: EvalManifest,
    job_results: list[dict[str, Any]],
    *,
    project_root: Path,
    skip_update_confirm: bool,
    confirm_fn: Any | None,
) -> None:
    if skip_update_confirm:
        apply_golden_updates(manifest, job_results, project_root=project_root)
        return
    msg = (
        f"Overwrite golden files for fixture {manifest.fixture_path!r} under "
        f"{project_root}?"
    )
    if confirm_fn is not None:
        if confirm_fn(msg):
            apply_golden_updates(manifest, job_results, project_root=project_root)
        return
    if not sys.stdin.isatty():
        logger.warning(
            "Skipping golden update (non-interactive stdin); use --yes to confirm. %s",
            manifest.fixture_path,
        )
        return
    try:
        ans = input(f"{msg} [y/N] ").strip().lower()
    except EOFError:
        return
    if ans in ("y", "yes"):
        apply_golden_updates(manifest, job_results, project_root=project_root)


def eval_outcomes_ok(outcomes: list[ManifestEvalOutcome]) -> bool:
    """Return False if any outcome has an error or a failed chunk expectation."""
    if not outcomes:
        return False
    for o in outcomes:
        if o.result.error:
            return False
        if o.result.summary is None:
            return False
        if o.result.summary.passed_expectations < o.result.summary.total_expectations:
            return False
    return True


def outcomes_to_json_blob(outcomes: list[ManifestEvalOutcome]) -> list[dict[str, Any]]:
    """Serialize outcomes for ``--output``."""
    out: list[dict[str, Any]] = []
    for o in outcomes:
        item: dict[str, Any] = {
            "manifest_path": str(o.manifest_path),
            "fixture_resolved": str(o.fixture_resolved) if o.fixture_resolved else None,
            "job_id": o.job_id,
            "result": o.result.model_dump(mode="json"),
        }
        out.append(item)
    return out
