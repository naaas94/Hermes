"""Configuration loading from TOML files."""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass(frozen=True)
class LiteLLMConfig:
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.0
    context_window_tokens: int = 128_000
    max_retries: int = 2
    timeout_seconds: int = 30


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    model: str = "qwen3:4b"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.1
    context_window_tokens: int = 8192
    max_retries: int = 2
    timeout_seconds: int = 120
    enable_thinking: bool = False  # set false for extraction to avoid long reasoning phases
    litellm: LiteLLMConfig = field(default_factory=LiteLLMConfig)


@dataclass(frozen=True)
class NormalizationConfig:
    ocr_engine: str = "surya"
    ocr_dpi: int = 150
    ocr_max_dpi: int = 300
    ocr_confidence_threshold: float = 0.7


@dataclass(frozen=True)
class StorageConfig:
    base_path: str = "./storage"


@dataclass(frozen=True)
class ExtractionConfig:
    default_schema: str = "hermes.schemas.examples.generic_table:GenericRow"
    chunk_overlap_ratio: float = 0.1


@dataclass(frozen=True)
class HermesConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    normalization: NormalizationConfig = field(default_factory=NormalizationConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)


_CONFIG_SEARCH_PATHS = [
    Path("./config.toml"),
    Path.home() / ".hermes" / "config.toml",
]


def _find_config_file() -> Path | None:
    for p in _CONFIG_SEARCH_PATHS:
        if p.exists():
            return p
    return None


def _parse_config(raw: dict) -> HermesConfig:  # type: ignore[type-arg]
    llm_raw = raw.get("llm", {})
    litellm_raw = llm_raw.pop("litellm", {})
    litellm_fields = {
        k: v for k, v in litellm_raw.items()
        if k in LiteLLMConfig.__dataclass_fields__
    }
    litellm_cfg = LiteLLMConfig(**litellm_fields)
    llm_fields = {k: v for k, v in llm_raw.items() if k in LLMConfig.__dataclass_fields__}
    llm_cfg = LLMConfig(**llm_fields, litellm=litellm_cfg)

    norm_raw = raw.get("normalization", {})
    norm_fields = {
        k: v for k, v in norm_raw.items()
        if k in NormalizationConfig.__dataclass_fields__
    }
    norm_cfg = NormalizationConfig(**norm_fields)

    stor_raw = raw.get("storage", {})
    stor_fields = {
        k: v for k, v in stor_raw.items()
        if k in StorageConfig.__dataclass_fields__
    }
    stor_cfg = StorageConfig(**stor_fields)

    ext_raw = raw.get("extraction", {})
    ext_fields = {
        k: v for k, v in ext_raw.items()
        if k in ExtractionConfig.__dataclass_fields__
    }
    ext_cfg = ExtractionConfig(**ext_fields)

    return HermesConfig(llm=llm_cfg, normalization=norm_cfg, storage=stor_cfg, extraction=ext_cfg)


@functools.lru_cache(maxsize=1)
def load_config() -> HermesConfig:
    """Load configuration from the first available config.toml, or return defaults."""
    config_path = _find_config_file()
    if config_path is None:
        return HermesConfig()
    with open(config_path, "rb") as f:
        raw = tomllib.load(f)
    return _parse_config(raw)


def get_storage_base() -> Path:
    cfg = load_config()
    p = Path(cfg.storage.base_path).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_db_path() -> Path:
    home = Path.home() / ".hermes"
    home.mkdir(parents=True, exist_ok=True)
    return home / "hermes.db"


def get_migrations_dir() -> Path:
    return Path(__file__).parent.parent / "migrations"
