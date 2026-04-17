"""Smoke test for hermes.eval package exports (T10)."""

from __future__ import annotations

import hermes.eval as hermes_eval


def test_eval_all_exports_importable() -> None:
    for name in hermes_eval.__all__:
        getattr(hermes_eval, name)
