"""Dynamic Pydantic model loader from Python module paths."""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from pydantic import BaseModel


def load_schema(schema_ref: str) -> type[BaseModel]:
    """Load a Pydantic model class from a 'module.path:ClassName' reference.

    Raises ValueError if the reference is malformed, the class is not a BaseModel
    subclass, or the model has no fields.
    """
    if ":" not in schema_ref:
        raise ValueError(
            f"Invalid schema reference '{schema_ref}'. "
            f"Expected format: 'module.path:ClassName'"
        )

    module_path, class_name = schema_ref.rsplit(":", 1)

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ValueError(f"Cannot import module '{module_path}': {e}") from e

    cls = getattr(module, class_name, None)
    if cls is None:
        raise ValueError(f"Class '{class_name}' not found in module '{module_path}'")

    if not (inspect.isclass(cls) and issubclass(cls, BaseModel)):
        raise ValueError(f"'{class_name}' is not a Pydantic BaseModel subclass")

    if not cls.model_fields:
        raise ValueError(f"'{class_name}' has no fields defined")

    return cls


def get_json_schema(schema_class: type[BaseModel]) -> dict[str, Any]:
    """Generate the JSON Schema for a Pydantic model."""
    return schema_class.model_json_schema()


def discover_schemas(module_path: str) -> list[type[BaseModel]]:
    """Find all BaseModel subclasses in a given module."""
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        raise ValueError(f"Cannot import module '{module_path}': {e}") from e

    models: list[type[BaseModel]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseModel) and obj is not BaseModel:
            models.append(obj)
    return models
