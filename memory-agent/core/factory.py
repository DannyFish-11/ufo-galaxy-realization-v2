"""按配置装配各层的工厂。FastAPI 服务与 MCP server 通过它复用同一 MemoryStore 实例。"""

from __future__ import annotations

from adapters.embedder import Embedder, build_embedder
from adapters.llm import LLMClient, VLLMOpenAIAdapter
from adapters.memory import MemoryStore, QdrantMemoryStore, SimpleMemAdapter
from adapters.vectordb import QdrantAdapter
from core.agent import MemoryAgent
from core.config import AppConfig, load_config
from core.errors import LayerError

_singletons: dict[str, object] = {}


def get_config() -> AppConfig:
    if "config" not in _singletons:
        _singletons["config"] = load_config()
    return _singletons["config"]  # type: ignore[return-value]


def build_llm(config: AppConfig) -> LLMClient:
    return VLLMOpenAIAdapter(
        base_url=config.llm.base_url,
        model=config.llm.model,
        api_key=config.llm.api_key,
        timeout_s=config.llm.timeout_s,
    )


def build_memory_store(config: AppConfig, embedder: Embedder | None = None,
                       llm: LLMClient | None = None) -> MemoryStore:
    if config.memory.backend == "simplemem":
        return SimpleMemAdapter(config)
    if config.memory.backend == "qdrant":
        embedder = embedder or build_embedder(config.embedder)
        llm = llm or build_llm(config)
        db = QdrantAdapter(config.vectordb, dim=config.embedder.effective_dim)
        return QdrantMemoryStore(embedder, llm, db, config)
    raise LayerError("L2", "factory", f"未知 memory.backend: {config.memory.backend}")


def get_shared_memory_store(config: AppConfig | None = None) -> MemoryStore:
    """进程级单例:API 与 MCP server 同进程时复用同一实例;跨进程时经由同一
    Qdrant collection / SimpleMem data_dir 共享状态。"""
    if "memory_store" not in _singletons:
        _singletons["memory_store"] = build_memory_store(config or get_config())
    return _singletons["memory_store"]  # type: ignore[return-value]


def build_agent(config: AppConfig, llm: LLMClient | None = None,
                memory: MemoryStore | None = None) -> MemoryAgent:
    llm = llm or build_llm(config)
    memory = memory or get_shared_memory_store(config)
    return MemoryAgent(llm, memory, config)
