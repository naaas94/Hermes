"""Example schema: Generic table row extraction."""

from typing import Any

from pydantic import BaseModel


class GenericRow(BaseModel):
    row_data: dict[str, Any]
