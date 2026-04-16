"""Tests for eval field-value normalization."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from hermes.eval.normalize import (
    MatchType,
    normalize_date,
    normalize_string,
    normalize_value,
    numbers_close,
)


def test_normalize_string_strips_and_casefolds() -> None:
    assert normalize_string("  Foo BAR  ") == "foo bar"
    # casefold maps German ß to "ss" (Unicode semantics)
    assert normalize_string("Straße") == "strasse"


def test_numbers_close_defaults_and_tolerance() -> None:
    assert numbers_close(1.0, 1.0)
    assert numbers_close(1.0, 1.0 + 1e-12)
    assert not numbers_close(1.0, 2.0)
    assert numbers_close(1.0, 1.01, rel_tol=0.02, abs_tol=0.0)
    assert numbers_close(1e-9, 2e-9, rel_tol=1.0, abs_tol=0.0)
    assert numbers_close(float("nan"), float("nan"))


def test_normalize_date_iso_and_us_formats() -> None:
    assert normalize_date("2024-01-15") == "2024-01-15"
    assert normalize_date("2024-01-15T14:30:00") == "2024-01-15T14:30:00"
    assert normalize_date("01/15/2024") == "2024-01-15"
    d = date(2024, 6, 1)
    assert normalize_date(d) == "2024-06-01"
    dt = datetime(2024, 3, 2, 9, 0, 0)
    assert normalize_date(dt) == "2024-03-02T09:00:00"


def test_normalize_date_rejects_garbage() -> None:
    assert normalize_date("not a date") is None
    assert normalize_date("") is None


def test_normalize_value_absent_and_strict() -> None:
    assert normalize_value(None, None) == "exact"
    assert normalize_value("x", None) == "missing"
    assert normalize_value(None, "x") == "mismatch"
    assert normalize_value("", "  ") == "exact"
    assert normalize_value(1, 2, "strict") == "mismatch"
    assert normalize_value(1, 1, "strict") == "exact"


def test_normalize_value_number_and_string_auto() -> None:
    assert normalize_value(5, 5) == "exact"
    assert normalize_value("5", 5.0) == "exact"
    assert normalize_value("1,000.5", 1000.5) == "exact"
    assert normalize_value("  Toyota ", "toyota") == "normalized"
    assert normalize_value("a", "b") == "mismatch"


def test_normalize_value_currency_us_vs_float() -> None:
    assert normalize_value("$350,000.00", 350000.0, "currency") == "exact"


def test_normalize_value_percent_vs_fraction() -> None:
    assert normalize_value("5%", 0.05) == "exact"
    assert normalize_value("5%", 0.05, "percent") == "exact"
    assert normalize_value(0.05, "5%") == "exact"


def test_normalize_value_date_cross_format() -> None:
    r = normalize_value("2024-01-15", "01/15/2024")
    assert r == "normalized"


def test_normalize_value_typed_hints() -> None:
    assert normalize_value("2", "3", "number") == "mismatch"
    assert normalize_value("x", "y", "date") == "mismatch"
    assert normalize_value("same", "same", "string") == "exact"


def test_match_type_literal_exhaustive() -> None:
    m: MatchType = normalize_value(1, 1)
    assert m in ("exact", "normalized", "mismatch", "missing")


def test_numbers_close_non_numeric() -> None:
    assert not numbers_close("x", 1.0)


def test_normalize_value_float_tolerance_near_one() -> None:
    a = 1.0000000001
    b = 1.0000000002
    assert normalize_value(a, b) == "normalized"
