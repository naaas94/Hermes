"""Tests for observability-related config loading from TOML."""

from __future__ import annotations

import tomllib

from hermes.config import HermesConfig, ObservabilityConfig, _parse_config


def test_observability_rss_fields_round_trip_from_toml() -> None:
    toml = """
[observability]
rss_sampling_enabled = false
rss_sampling_interval_s = 0.25
"""
    raw = tomllib.loads(toml)
    cfg = _parse_config(raw)
    assert cfg.observability.rss_sampling_enabled is False
    assert cfg.observability.rss_sampling_interval_s == 0.25


def test_observability_config_has_five_documented_fields() -> None:
    keys = frozenset(ObservabilityConfig.__dataclass_fields__)
    assert keys == frozenset(
        {
            "log_format",
            "log_dir",
            "log_ndjson",
            "rss_sampling_enabled",
            "rss_sampling_interval_s",
        }
    )


def test_hermes_config_defaults_include_rss_observability_fields() -> None:
    cfg = HermesConfig()
    assert cfg.observability.rss_sampling_enabled is True
    assert cfg.observability.rss_sampling_interval_s == 0.0
