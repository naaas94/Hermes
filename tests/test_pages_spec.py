"""Tests for --pages parsing and validation."""

from __future__ import annotations

import pytest

from hermes.ingestion.pages_spec import (
    parse_pages_spec,
    resolve_page_indices_0,
    validate_pages_against_total,
)


def test_parse_range_and_list():
    assert parse_pages_spec("1-3") == frozenset({1, 2, 3})
    assert parse_pages_spec("3,5,7") == frozenset({3, 5, 7})
    assert parse_pages_spec("1,3-5,10") == frozenset({1, 3, 4, 5, 10})


def test_parse_whitespace_and_none():
    assert parse_pages_spec(None) is None
    assert parse_pages_spec("") is None
    assert parse_pages_spec("  ") is None
    assert parse_pages_spec(" 1 , 2 ") == frozenset({1, 2})


def test_parse_single_page():
    assert parse_pages_spec("5") == frozenset({5})


def test_parse_errors():
    with pytest.raises(ValueError, match="at least 1"):
        parse_pages_spec("0")
    with pytest.raises(ValueError, match="end must be"):
        parse_pages_spec("5-3")
    with pytest.raises(ValueError, match="Invalid"):
        parse_pages_spec("x")


def test_validate_total():
    validate_pages_against_total(frozenset({1, 2}), 5)
    with pytest.raises(ValueError, match="out of range"):
        validate_pages_against_total(frozenset({1, 99}), 10)


def test_resolve():
    assert resolve_page_indices_0(None, 100) is None
    assert resolve_page_indices_0("1", 5) == frozenset({0})
    assert resolve_page_indices_0("2-3", 5) == frozenset({1, 2})
