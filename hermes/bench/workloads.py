"""Standard benchmark workloads (versioned fixtures under ``tests/fixtures``)."""

from __future__ import annotations

import os
from pathlib import Path

from hermes.bench.runner import BenchWorkload

DEFAULT_SCHEMA_REF = "hermes.schemas.examples.vehicle_fleet:VehicleRecord"
DEFAULT_MODEL = "qwen3:4b"


def resolve_repo_root() -> Path:
    """Return repository root (``HERMES_REPO_ROOT`` env, else parents of this package)."""

    raw = os.environ.get("HERMES_REPO_ROOT", "").strip()
    if raw:
        return Path(raw).resolve()
    return Path(__file__).resolve().parents[2]


def _fixture_path(repo: Path, name: str) -> Path:
    """Prefer committed ``eval/`` copy; fall back to generated top-level fixture."""

    eval_path = repo / "tests" / "fixtures" / "eval" / name
    if eval_path.is_file():
        return eval_path
    gen = repo / "tests" / "fixtures" / name
    return gen


def default_workloads(
    repo_root: Path | None = None,
    *,
    include_large_pdf: bool = False,
) -> list[BenchWorkload]:
    """Return 2–3 standard workloads using committed eval fixtures and optional stress PDF."""

    root = repo_root or resolve_repo_root()
    pdf_small = _fixture_path(root, "sample_text.pdf")
    xlsx_small = _fixture_path(root, "sample.xlsx")

    workloads: list[BenchWorkload] = [
        BenchWorkload(
            name="pdf_text_small",
            input_path=pdf_small,
            schema_ref=DEFAULT_SCHEMA_REF,
            file_type="pdf",
            expected_page_count=None,
            workers=1,
            model=DEFAULT_MODEL,
            compare_log_format=True,
        ),
        BenchWorkload(
            name="excel_small",
            input_path=xlsx_small,
            schema_ref=DEFAULT_SCHEMA_REF,
            file_type="excel",
            expected_page_count=None,
            workers=1,
            model=DEFAULT_MODEL,
            compare_log_format=False,
        ),
    ]

    large_path = root / "test_pdf_stress_riscbac.pdf"
    if include_large_pdf and large_path.is_file():
        workloads.append(
            BenchWorkload(
                name="pdf_text_large",
                input_path=large_path,
                schema_ref=DEFAULT_SCHEMA_REF,
                file_type="pdf",
                expected_page_count=None,
                workers=1,
                model=DEFAULT_MODEL,
                compare_log_format=False,
            )
        )

    return workloads
