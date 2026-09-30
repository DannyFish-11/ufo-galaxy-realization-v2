"""OmniSimpleMem 缺失模块 omni_memory/core/config.py 的兼容重建(最小 patch)。

背景:上游 aiming-lab/SimpleMem 在 pinned commit(见项目 README)中,
OmniSimpleMem/omni_memory 全包 30+ 处 `from omni_memory.core.config import ...`,
但该文件未随仓库提交,包无法 import(上游 alpha 质量问题)。

本模块依据上游自带的规范测试 OmniSimpleMem/tests/test_config.py 与全包实际
引用的字段(grep 所得)逐字段重建,并在 import 上游前通过 install() 注册到
sys.modules["omni_memory.core.config"] —— 不修改上游任何文件。

BUILD_SPEC 停点声明:patch 上游属于须人类确认的动作。本 shim 是唯一使
simplemem 后端可用的途径,默认 memory.backend=qdrant(规格允许的兜底)不受
影响;是否采纳 simplemem 后端/是否向上游提 PR 由人类决策。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any, Optional


@dataclass
class EmbeddingConfig:
    model_name: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    visual_embedding_model: str = "openai/clip-vit-base-patch32"
    visual_embedding_dim: int = 512
    batch_size: int = 32
    api_key: Optional[str] = None
    doubao_base_url: Optional[str] = None


@dataclass
class RetrievalConfig:
    default_top_k: int = 10
    enable_hybrid_search: bool = True
    enable_graph_traversal: bool = True
    auto_expand_threshold: float = 0.5
    max_expanded_items: int = 20


@dataclass
class StorageConfig:
    base_dir: str = "./omni_memory_data"
    cold_storage_dir: str = "./omni_memory_data/cold_storage"
    index_dir: str = "./omni_memory_data/index"
    use_s3: bool = False
    s3_bucket: Optional[str] = None
    organize_by_date: bool = True
    organize_by_modality: bool = True
    auto_cleanup_enabled: bool = False


@dataclass
class LLMConfig:
    summary_model: str = "gpt-4o-mini"
    query_model: str = "gpt-4o"
    caption_model: str = "gpt-4o-mini"
    whisper_model: str = "whisper-1"
    temperature: float = 0.0
    max_tokens: int = 1000
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None

    def __post_init__(self) -> None:
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        if self.api_base_url is None:
            self.api_base_url = os.environ.get("OPENAI_API_BASE")


@dataclass
class EventConfig:
    auto_create_events: bool = True
    event_time_window_seconds: float = 300.0


@dataclass
class EntropyTriggerConfig:
    visual_similarity_threshold_high: float = 0.9
    visual_similarity_threshold_low: float = 0.5
    enable_visual_trigger: bool = True
    enable_audio_trigger: bool = True
    visual_model_name: str = "openai/clip-vit-base-patch32"


_SECTIONS = {
    "embedding": EmbeddingConfig,
    "retrieval": RetrievalConfig,
    "storage": StorageConfig,
    "llm": LLMConfig,
    "event": EventConfig,
    "entropy_trigger": EntropyTriggerConfig,
}


@dataclass
class OmniMemoryConfig:
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    event: EventConfig = field(default_factory=EventConfig)
    entropy_trigger: EntropyTriggerConfig = field(default_factory=EntropyTriggerConfig)
    debug_mode: bool = False
    log_level: str = "INFO"
    enable_self_evolution: bool = False
    evolution: Any = None
    router: Any = None

    # ---- factory / chaining ----

    @classmethod
    def create_default(cls) -> "OmniMemoryConfig":
        return cls()

    def set_unified_model(self, model: str) -> "OmniMemoryConfig":
        self.llm.summary_model = model
        self.llm.query_model = model
        self.llm.caption_model = model
        return self

    def enable_evolution(self) -> "OmniMemoryConfig":
        self.enable_self_evolution = True
        if self.evolution is None:
            self.evolution = SimpleNamespace()
        return self

    # ---- (de)serialization ----

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {name: asdict(getattr(self, name)) for name in _SECTIONS}
        d["debug_mode"] = self.debug_mode
        d["log_level"] = self.log_level
        d["enable_self_evolution"] = self.enable_self_evolution
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OmniMemoryConfig":
        kwargs: dict[str, Any] = {}
        for name, section_cls in _SECTIONS.items():
            if name in d and isinstance(d[name], dict):
                kwargs[name] = section_cls(**d[name])
        for key in ("debug_mode", "log_level", "enable_self_evolution"):
            if key in d:
                kwargs[key] = d[key]
        return cls(**kwargs)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, s: str) -> "OmniMemoryConfig":
        return cls.from_dict(json.loads(s))

    def save_to_file(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_json())

    @classmethod
    def from_file(cls, filepath: str) -> "OmniMemoryConfig":
        with open(filepath, encoding="utf-8") as f:
            return cls.from_json(f.read())

    # ---- filesystem ----

    def ensure_directories(self) -> None:
        for path in (self.storage.base_dir, self.storage.cold_storage_dir, self.storage.index_dir):
            os.makedirs(path, exist_ok=True)


def install() -> None:
    """在 import omni_memory 之前调用,把本模块注册为 omni_memory.core.config。"""
    sys.modules.setdefault("omni_memory.core.config", sys.modules[__name__])
