"""单一配置源 config.yaml + 环境变量覆盖(pydantic-settings)。

覆盖规则:前缀 MEMORY_AGENT_,嵌套键用 __,如 MEMORY_AGENT_LLM__BASE_URL。
配置文件路径可用 MEMORY_AGENT_CONFIG 指定,默认取项目根 config.yaml。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class HardwareSettings(BaseModel):
    tier: Literal["A", "B", "C", "unset"] = "unset"


class LLMSettings(BaseModel):
    base_url: str = "http://localhost:8000/v1"
    model: str = "gemma-4"
    model_by_tier: dict[str, str] = Field(default_factory=dict)
    api_key: str = "EMPTY"
    timeout_s: float = 120.0


class EmbedderSettings(BaseModel):
    backend: Literal["local", "remote", "jina_api", "fake"] = "local"
    model_name: str = "jinaai/jina-embeddings-v5-omni-small"
    model_by_tier: dict[str, str] = Field(default_factory=dict)
    dim: int = 1024
    matryoshka_dim: int | None = None
    base_url: str = "http://localhost:8001"
    device: str = "auto"
    jina_api_key: str | None = None

    @property
    def effective_dim(self) -> int:
        return self.matryoshka_dim or self.dim


class VectorDBSettings(BaseModel):
    mode: Literal["memory", "local", "server"] = "server"
    url: str = "http://localhost:6333"
    path: str = "./data/qdrant"
    collection: str = "memories"


class ConsolidationSettings(BaseModel):
    similarity_threshold: float = 0.92


class SimpleMemSettings(BaseModel):
    data_dir: str = "./data/simplemem"
    gateway_base_url: str = "http://localhost:8001/v1"


class MemorySettings(BaseModel):
    backend: Literal["qdrant", "simplemem"] = "qdrant"
    extraction: Literal["llm", "verbatim"] = "llm"
    consolidation: ConsolidationSettings = Field(default_factory=ConsolidationSettings)
    simplemem: SimpleMemSettings = Field(default_factory=SimpleMemSettings)


class ServiceSettings(BaseModel):
    embed_host: str = "0.0.0.0"
    embed_port: int = 8001
    api_host: str = "0.0.0.0"
    api_port: int = 8002


class AgentSettings(BaseModel):
    top_k: int = 5
    system_prompt: str = "你是一个拥有长期记忆的助手。"


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORY_AGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    hardware: HardwareSettings = Field(default_factory=HardwareSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    embedder: EmbedderSettings = Field(default_factory=EmbedderSettings)
    vectordb: VectorDBSettings = Field(default_factory=VectorDBSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    services: ServiceSettings = Field(default_factory=ServiceSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_path = Path(os.environ.get("MEMORY_AGENT_CONFIG", PROJECT_ROOT / "config.yaml"))
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        if yaml_path.exists():
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path))
        return tuple(sources)


def load_config(**overrides) -> AppConfig:
    return AppConfig(**overrides)
