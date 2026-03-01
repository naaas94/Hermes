"""Tests for configuration loading."""

from __future__ import annotations

from hermes.config import HermesConfig, _parse_config


def test_default_config():
    cfg = HermesConfig()
    assert cfg.llm.provider == "ollama"
    assert cfg.llm.model == "qwen3:4b"
    assert cfg.llm.context_window_tokens == 8192
    assert cfg.llm.max_retries == 2
    assert cfg.llm.litellm.model == "gpt-4o-mini"
    assert cfg.storage.base_path == "./storage"
    assert cfg.extraction.default_schema == "hermes.schemas.examples.generic_table:GenericRow"


def test_parse_config_from_dict():
    raw = {
        "llm": {
            "provider": "litellm",
            "model": "custom-model",
            "temperature": 0.5,
            "litellm": {
                "model": "gpt-4o",
                "api_key_env": "MY_KEY",
            },
        },
        "storage": {"base_path": "/tmp/hermes"},
    }
    cfg = _parse_config(raw)
    assert cfg.llm.provider == "litellm"
    assert cfg.llm.model == "custom-model"
    assert cfg.llm.temperature == 0.5
    assert cfg.llm.litellm.model == "gpt-4o"
    assert cfg.llm.litellm.api_key_env == "MY_KEY"
    assert cfg.storage.base_path == "/tmp/hermes"
    assert cfg.normalization.ocr_engine == "surya"  # default preserved


def test_parse_config_empty_dict():
    cfg = _parse_config({})
    assert cfg.llm.provider == "ollama"
    assert cfg.storage.base_path == "./storage"
