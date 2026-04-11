"""Tests for schema discovery (list_schema_refs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes.schemas.discover import list_schema_refs


def test_list_schema_refs_packaged_examples():
    refs, errors = list_schema_refs(
        include_packaged=True,
        include_user=False,
    )
    assert not errors
    assert "hermes.schemas.examples.generic_table:GenericRow" in refs
    assert "hermes.schemas.examples.vehicle_fleet:VehicleRecord" in refs


def test_list_schema_refs_user_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    hermes_dir = fake_home / ".hermes"
    pkg = hermes_dir / "hermes_user"
    ex = pkg / "examples"
    ex.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""u"""\n', encoding="utf-8")
    (ex / "__init__.py").write_text('"""e"""\n', encoding="utf-8")
    (ex / "custom.py").write_text(
        "from pydantic import BaseModel\n"
        "class M(BaseModel):\n"
        "    x: int\n",
        encoding="utf-8",
    )

    refs, errors = list_schema_refs(
        include_packaged=False,
        include_user=True,
        hermes_home=hermes_dir,
    )
    assert not errors
    assert "hermes_user.examples.custom:M" in refs


def test_list_schema_refs_skips_broken_user_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))

    hermes_dir = fake_home / ".hermes"
    pkg = hermes_dir / "hermes_user"
    ex = pkg / "examples"
    ex.mkdir(parents=True)
    (pkg / "__init__.py").write_text('"""u"""\n', encoding="utf-8")
    (ex / "__init__.py").write_text('"""e"""\n', encoding="utf-8")
    (ex / "broken.py").write_text("this is not valid python\n", encoding="utf-8")

    refs, errors = list_schema_refs(
        include_packaged=False,
        include_user=True,
        hermes_home=hermes_dir,
    )
    assert not refs
    assert len(errors) == 1
    assert "hermes_user.examples.broken" in errors[0]
