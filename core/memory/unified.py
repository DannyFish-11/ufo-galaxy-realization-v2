"""core/memory/unified.py — 统一记忆门面：路由读写到已启用的后端。"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.Unified")


class UnifiedMemory:
    """聚合多个 MemoryProvider；写入广播到全部，召回合并去重后按分数排序。"""

    def __init__(self, providers: List[MemoryProvider]) -> None:
        self.providers: List[MemoryProvider] = []
        for p in providers:
            try:
                if p.available():
                    self.providers.append(p)
            except Exception as exc:  # noqa: BLE001
                logger.debug("provider availability check failed: %s", exc)

    @property
    def enabled(self) -> bool:
        return bool(self.providers)

    @property
    def backend_names(self) -> List[str]:
        return [p.backend_name for p in self.providers]

    def remember(self, content: str, **kwargs) -> None:
        for p in self.providers:
            try:
                p.remember(content, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 单后端失败不影响其它
                logger.debug("remember via %s failed: %s", p.backend_name, exc)

    def remember_media(
        self,
        data_b64: str,
        *,
        modality: str,
        mime: str = "",
        tags: Optional[list] = None,
        metadata: Optional[dict] = None,
        caption: str = "",
    ) -> None:
        """记住一段 base64 媒体（摄像头帧/麦克风片段等）。

        base64 → 临时文件 → 各 provider：跨模态后端(Omni-SimpleMem)经 media_path
        原生摄入媒体；纯文本后端(vector)存其文字说明(caption)。摄入完即删临时文件。
        """
        if not self.providers or not data_b64:
            return
        from core.memory._media import write_temp_media, remove_temp

        path = write_temp_media(data_b64, mime, modality)
        try:
            md = dict(metadata or {})
            if path:
                md["media_path"] = path
            md.setdefault("modality", modality)
            text = caption or f"[{modality} memory]"
            self.remember(text, modality=modality, tags=tags, metadata=md)
        finally:
            remove_temp(path)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        hits: List[MemoryHit] = []
        for p in self.providers:
            try:
                hits.extend(p.recall(query, top_k=top_k) or [])
            except Exception as exc:  # noqa: BLE001
                logger.debug("recall via %s failed: %s", p.backend_name, exc)
        # 跨后端去重（按内容），保留高分
        seen: dict = {}
        for h in hits:
            key = (h.content or "").strip()[:160]
            if key and (key not in seen or h.score > seen[key].score):
                seen[key] = h
        merged = sorted(seen.values(), key=lambda h: h.score, reverse=True)
        return merged[:top_k]


# ── 单例工厂 ────────────────────────────────────────────────────────────────

_instance: Optional[UnifiedMemory] = None


def _build() -> UnifiedMemory:
    # GALAXY_MEMORY_BACKENDS: 逗号分隔，默认 "vector"（本地后端零依赖永远可用）。
    # 加 "omni" 启用 Omni-SimpleMem 跨模态记忆（需 pip install simplemem）。
    raw = os.getenv("GALAXY_MEMORY_BACKENDS", "vector")
    wanted = {b.strip().lower() for b in raw.split(",") if b.strip()}
    providers: List[MemoryProvider] = []
    if {"vector", "vector_backend"} & wanted:
        from core.memory.vector_backend_provider import VectorBackendProvider
        providers.append(VectorBackendProvider())
    if {"omni", "omni_simplemem", "simplemem"} & wanted:
        from core.memory.omni_simplemem_provider import OmniSimpleMemProvider
        providers.append(OmniSimpleMemProvider())
    if {"clip", "crossmodal", "cross_modal"} & wanted:
        from core.memory.clip_provider import ClipMemoryProvider
        providers.append(ClipMemoryProvider())
    if {"clap", "audio"} & wanted:
        from core.memory.clap_provider import ClapMemoryProvider
        providers.append(ClapMemoryProvider())
    um = UnifiedMemory(providers)
    logger.info("UnifiedMemory initialised | backends=%s", um.backend_names or "none")
    return um


def get_unified_memory() -> UnifiedMemory:
    global _instance
    if _instance is None:
        _instance = _build()
    return _instance


def reset_unified_memory() -> None:
    """测试/重配用：清空单例。"""
    global _instance
    _instance = None
