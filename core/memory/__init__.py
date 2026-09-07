"""
core/memory/ — 统一记忆层（Unified Memory Layer）
==================================================

把仓库里散落、重复、且大多 dormant 的记忆/向量子系统收敛成**一个接口**，
并真正接进 live 路径（SessionMemoryFacade 单点读写）。

四个后端，按 GALAXY_MEMORY_BACKENDS 选择（可同时启用）：
- "vector"  → VectorBackendProvider：复用已有的 core/vector_backend
              (Chroma/Qdrant，自动降级到本地关键词后端；零依赖即可用)。文本语义。
- "omni"    → OmniSimpleMemProvider：Omni-SimpleMem(`pip install simplemem`)
              跨模态(文/图/音/视频)终身记忆；未安装则自动 no-op。

- "clip"    → ClipMemoryProvider：CLIP 把文本与图像编进同一向量空间，于是**一句话
              能召回一张截图**（需 sentence-transformers + chromadb + pillow）
- "clap"    → ClapMemoryProvider：CLAP 对声音同理

设计原则：默认安全（默认仅 "vector"，本地后端零依赖永远可用）、可选叠加、
任何后端异常都吞掉、绝不影响主请求流程；同步接口（底层 search/add 均同步）。
"""

from __future__ import annotations

from core.memory.base import MemoryHit, MemoryProvider
from core.memory.unified import UnifiedMemory, get_unified_memory

__all__ = [
    "MemoryHit",
    "MemoryProvider",
    "UnifiedMemory",
    "get_unified_memory",
]
