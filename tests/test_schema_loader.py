"""Tests for dynamic schema loading."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from hermes.schemas.loader import get_json_schema, load_schema


def test_load_vehicle_fleet_schema():
    cls = load_schema("hermes.schemas.examples.vehicle_fleet:VehicleRecord")
    assert issubclass(cls, BaseModel)
    assert "marca" in cls.model_fields


def test_load_generic_table_schema():
    cls = load_schema("hermes.schemas.examples.generic_table:GenericRow")
    assert issubclass(cls, BaseModel)
    assert "row_data" in cls.model_fields


def test_load_schema_invalid_format():
    with pytest.raises(ValueError, match="Expected format"):
        load_schema("no_colon_here")


def test_load_schema_missing_module():
    with pytest.raises(ValueError, match="Cannot import module"):
        load_schema("nonexistent.module:SomeClass")


def test_load_schema_missing_class():
    with pytest.raises(ValueError, match="not found in module"):
        load_schema("hermes.schemas.examples.vehicle_fleet:NoSuchClass")


def test_json_schema_generation():
    cls = load_schema("hermes.schemas.examples.vehicle_fleet:VehicleRecord")
    schema = get_json_schema(cls)
    assert "properties" in schema
    assert "marca" in schema["properties"]


def test_load_empty_model():
    """A model with no fields should be rejected."""

    class EmptyModel(BaseModel):
        pass

    # We can't easily test via load_schema since we'd need a module path,
    # but we can verify the validation logic directly
    import types

    mod = types.ModuleType("test_empty")
    mod.EmptyModel = EmptyModel  # type: ignore[attr-defined]

    import sys
    sys.modules["test_empty"] = mod
    try:
        with pytest.raises(ValueError, match="no fields"):
            load_schema("test_empty:EmptyModel")
    finally:
        del sys.modules["test_empty"]
