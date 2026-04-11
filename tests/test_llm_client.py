"""Unit tests for LLM clients (mocked; no network)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes.config import HermesConfig, LiteLLMConfig, LLMConfig


def test_litellm_client_chat_calls_completion_with_expected_args(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    captured: dict[str, object] = {}

    def fake_completion(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        resp = MagicMock()
        resp.choices = [MagicMock(message=MagicMock(content='{"x": 1}'))]
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        resp.model = "gpt-4o-mini"
        resp.model_dump = lambda: {"model": "gpt-4o-mini"}
        return resp

    litellm = LiteLLMConfig(
        model="gpt-4o-mini",
        timeout_seconds=42,
        temperature=0.1,
        api_key_env="OPENAI_API_KEY",
    )
    cfg = HermesConfig(llm=LLMConfig(provider="litellm", litellm=litellm))

    with patch("litellm.completion", side_effect=fake_completion):
        from hermes.extraction.llm_client import LiteLLMClient

        client = LiteLLMClient(cfg)
        out = client.chat("sys here", "user here")

    assert captured["model"] == "gpt-4o-mini"
    assert captured["timeout"] == 42
    assert captured["temperature"] == 0.1
    assert captured["api_key"] == "sk-test"
    assert captured["num_retries"] == 3
    assert captured["retry_strategy"] == "exponential_backoff_retry"
    assert captured["response_format"] == {"type": "json_object"}
    msgs = captured["messages"]
    assert msgs[0] == {"role": "system", "content": "sys here"}
    assert msgs[1] == {"role": "user", "content": "user here"}

    assert out.content == '{"x": 1}'
    assert out.tokens_in == 10
    assert out.tokens_out == 5
    assert out.model == "gpt-4o-mini"


def test_litellm_client_check_ready_requires_api_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    litellm = LiteLLMConfig(api_key_env="OPENAI_API_KEY")
    cfg = HermesConfig(llm=LLMConfig(provider="litellm", litellm=litellm))
    from hermes.extraction.llm_client import LiteLLMClient

    client = LiteLLMClient(cfg)
    assert client.check_ready() is False

    monkeypatch.setenv("OPENAI_API_KEY", "x")
    client2 = LiteLLMClient(cfg)
    assert client2.check_ready() is True
