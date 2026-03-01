"""Unified LLM client interface supporting Ollama (/api/chat) and LiteLLM."""

from __future__ import annotations

import abc
import logging
import time
from typing import Any

import httpx

from hermes.config import HermesConfig, load_config
from hermes.models import LLMResponse

logger = logging.getLogger(__name__)


class BaseLLMClient(abc.ABC):
    @abc.abstractmethod
    def chat(self, system_prompt: str, user_prompt: str) -> LLMResponse: ...

    @abc.abstractmethod
    def check_ready(self) -> bool: ...


class OllamaClient(BaseLLMClient):
    """Direct HTTP client for Ollama's /api/chat endpoint."""

    def __init__(self, config: HermesConfig) -> None:
        self.base_url = config.llm.base_url.rstrip("/")
        self.model = config.llm.model
        self.temperature = config.llm.temperature
        self.timeout = config.llm.timeout_seconds

    def chat(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {"temperature": self.temperature},
        }

        start = time.perf_counter_ns()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()

        elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000
        data = resp.json()

        content = data.get("message", {}).get("content", "")
        tokens_in = data.get("prompt_eval_count", 0)
        tokens_out = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            model=data.get("model", self.model),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=elapsed_ms,
            raw_response=data,
        )

    def check_ready(self) -> bool:
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False


class LiteLLMClient(BaseLLMClient):
    """Client using litellm.completion() for cloud LLM providers."""

    def __init__(self, config: HermesConfig) -> None:
        import os

        self.model = config.llm.litellm.model
        self.temperature = config.llm.litellm.temperature
        self.timeout = config.llm.litellm.timeout_seconds

        api_key_env = config.llm.litellm.api_key_env
        self.api_key = os.environ.get(api_key_env, "")
        if not self.api_key:
            logger.warning("API key env var '%s' is not set", api_key_env)

    def chat(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        import litellm

        start = time.perf_counter_ns()
        response = litellm.completion(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self.temperature,
            response_format={"type": "json_object"},
            timeout=self.timeout,
            api_key=self.api_key,
        )
        elapsed_ms = (time.perf_counter_ns() - start) // 1_000_000

        content = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=elapsed_ms,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else {},
        )

    def check_ready(self) -> bool:
        return bool(self.api_key)


def create_llm_client(config: HermesConfig | None = None) -> BaseLLMClient:
    """Factory: return the appropriate LLM client based on config."""
    if config is None:
        config = load_config()

    if config.llm.provider == "litellm":
        return LiteLLMClient(config)
    return OllamaClient(config)
