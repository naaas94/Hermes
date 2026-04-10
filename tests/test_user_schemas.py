"""Tests for ~/.hermes hermes_user example schema installation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from hermes.user_schemas import (
    DEFAULT_USER_SCHEMA_REF,
    install_example_schemas_if_missing,
)


def _clear_hermes_user_modules() -> None:
    for k in list(sys.modules):
        if k == "hermes_user" or k.startswith("hermes_user."):
            del sys.modules[k]


def test_install_example_schemas_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hh = tmp_path / ".hermes"
    w1 = install_example_schemas_if_missing()
    w2 = install_example_schemas_if_missing()
    assert len(w1) == 2
    assert len(w2) == 0
    vf = hh / "hermes_user" / "examples" / "vehicle_fleet.py"
    assert vf.exists()
    content = vf.read_text(encoding="utf-8")
    assert "VehicleRecord" in content


def test_load_user_installed_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _clear_hermes_user_modules()
    install_example_schemas_if_missing()

    from pydantic import BaseModel

    from hermes.schemas.loader import load_schema

    cls = load_schema(DEFAULT_USER_SCHEMA_REF)
    assert issubclass(cls, BaseModel)
    assert "row_data" in cls.model_fields

    cls2 = load_schema("hermes_user.examples.vehicle_fleet:VehicleRecord")
    assert "marca" in cls2.model_fields


def test_default_user_schema_ref_format() -> None:
    assert DEFAULT_USER_SCHEMA_REF == "hermes_user.examples.generic_table:GenericRow"
