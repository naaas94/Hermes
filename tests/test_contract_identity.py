"""Tests for canonical JSON Schema serialization and contract_id derivation."""

from __future__ import annotations

from hermes.extraction.contract_identity import (
    canonical_json_schema,
    compute_contract_id,
)


def test_canonical_json_schema_stable_under_key_reorder():
    a = {"z": 1, "a": {"nested": True, "m": 2}}
    b = {"a": {"m": 2, "nested": True}, "z": 1}
    s1, h1 = canonical_json_schema(a)
    s2, h2 = canonical_json_schema(b)
    assert s1 == s2
    assert h1 == h2


def test_compute_contract_id_includes_metadata():
    b = b'{"a":1}'
    c1 = compute_contract_id(b, "pv1", "mod:Cls")
    c2 = compute_contract_id(b, "pv2", "mod:Cls")
    c3 = compute_contract_id(b, "pv1", "mod:Other")
    assert c1 != c2
    assert c1 != c3
    assert c1.startswith("ctr_")
    assert len(c1) == len("ctr_") + 32
