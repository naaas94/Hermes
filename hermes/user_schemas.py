"""Install user-local example schemas under ~/.hermes/hermes_user/."""

from __future__ import annotations

import shutil
from pathlib import Path

import hermes as hermes_pkg

USER_SCHEMA_PACKAGE = "hermes_user"
DEFAULT_USER_SCHEMA_REF = f"{USER_SCHEMA_PACKAGE}.examples.generic_table:GenericRow"


def get_hermes_home() -> Path:
    return Path.home() / ".hermes"


def package_examples_dir() -> Path:
    return Path(hermes_pkg.__file__).resolve().parent / "schemas" / "examples"


def install_example_schemas_if_missing(hermes_home: Path | None = None) -> list[Path]:
    """Create hermes_user.examples.* from packaged examples; skip existing files.

    Returns paths of schema files written (not __init__.py).
    """
    root = hermes_home or get_hermes_home()
    root.mkdir(parents=True, exist_ok=True)

    pkg_root = root / USER_SCHEMA_PACKAGE
    examples = pkg_root / "examples"
    examples.mkdir(parents=True, exist_ok=True)

    for init in (pkg_root / "__init__.py", examples / "__init__.py"):
        if not init.exists():
            init.write_text('"""User-local Hermes example schemas."""\n', encoding="utf-8")

    src = package_examples_dir()
    written: list[Path] = []
    for name in ("vehicle_fleet.py", "generic_table.py"):
        dest = examples / name
        if not dest.exists():
            shutil.copy2(src / name, dest)
            written.append(dest)
    return written
