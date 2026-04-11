"""Discover Pydantic schema references under packaged examples and ~/.hermes/hermes_user."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel

import hermes as hermes_pkg
from hermes.schemas.loader import ensure_user_hermes_on_sys_path


def _module_paths_from_packaged_examples() -> list[str]:
    pkg_root = Path(hermes_pkg.__file__).resolve().parent
    examples = pkg_root / "schemas" / "examples"
    if not examples.is_dir():
        return []
    out: list[str] = []
    for py in sorted(examples.glob("*.py")):
        if py.name == "__init__.py":
            continue
        rel = py.relative_to(pkg_root)
        parts = rel.with_suffix("").parts
        out.append("hermes." + ".".join(parts))
    return out


def _module_paths_from_user_tree(hermes_user_root: Path) -> list[str]:
    if not hermes_user_root.is_dir():
        return []
    out: list[str] = []
    for py in sorted(hermes_user_root.rglob("*.py")):
        if py.name == "__init__.py":
            continue
        rel = py.relative_to(hermes_user_root)
        parts = ("hermes_user",) + rel.with_suffix("").parts
        out.append(".".join(parts))
    return out


def _refs_from_imported_module(module: ModuleType) -> list[str]:
    refs: list[str] = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, BaseModel) or obj is BaseModel:
            continue
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        if "." in obj.__qualname__:
            continue
        if not obj.model_fields:
            continue
        refs.append(f"{module.__name__}:{name}")
    return refs


def _refs_for_module(module_name: str) -> tuple[list[str], str | None]:
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        return [], f"{module_name}: {e}"
    try:
        return _refs_from_imported_module(mod), None
    except Exception as e:
        return [], f"{module_name}: {e}"


def list_schema_refs(
    *,
    include_packaged: bool = True,
    include_user: bool = True,
    hermes_home: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Return sorted ``module:Class`` refs and import error messages.

    Uses the same ``sys.path`` and model rules as :func:`hermes.schemas.loader.load_schema`.
    """
    ensure_user_hermes_on_sys_path()
    home = hermes_home if hermes_home is not None else Path.home() / ".hermes"
    module_names: list[str] = []
    if include_packaged:
        module_names.extend(_module_paths_from_packaged_examples())
    if include_user:
        module_names.extend(_module_paths_from_user_tree(home / "hermes_user"))

    seen: set[str] = set()
    ordered_unique = []
    for m in module_names:
        if m not in seen:
            seen.add(m)
            ordered_unique.append(m)

    refs: list[str] = []
    errors: list[str] = []
    for name in ordered_unique:
        mod_refs, err = _refs_for_module(name)
        refs.extend(mod_refs)
        if err:
            errors.append(err)

    refs.sort()
    return refs, errors
