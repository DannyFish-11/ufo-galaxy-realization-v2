"""core/memory/vector_backend_provider.py — 路 A：复用已有 core/vector_backend。

把仓库里已经写好但 dormant 的向量后端(Chroma/Qdrant，自动降级本地关键词)接成
统一记忆 provider。文本语义记忆；本地后端零依赖、永远可用，因此本 provider 始终
available。非文本模态在此后端只存其文本描述（真正跨模态走 OmniSimpleMemProvider）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.Vector")


class VectorBackendProvider(MemoryProvider):
    backend_name = "vector_backend"

    def __init__(self) -> None:
        self._backend = None

    def _get(self):
        if self._backend is None:
            from core.vector_backend import get_shared_backend
            self._backend = get_shared_backend()
        return self._backend

    def available(self) -> bool:
        try:
            return self._get() is not None
        except Exception as exc:  # noqa: BLE001
            logger.debug("vector backend unavailable: %s", exc)
            return False

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not content:
            return
        try:
            md: Dict[str, Any] = dict(metadata or {})
            if tags:
                md["tags"] = tags
            md.setdefault("modality", modality)
            doc_id = str(md.get("id") or f"mem_{uuid.uuid4().hex[:12]}")
            self._get().add_document(doc_id, content, md)
        except Exception as exc:  # noqa: BLE001 — 记忆写入失败不影响主流程
            logger.debug("vector remember failed: %s", exc)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        if not query:
            return []
        try:
            results = self._get().search(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.debug("vector recall failed: %s", exc)
            return []
        hits: List[MemoryHit] = []
        for r in results or []:
            hits.append(MemoryHit(
                content=getattr(r, "content", "") or "",
                score=float(getattr(r, "score", 0.0) or 0.0),
                source=self.backend_name,
                modality=str((getattr(r, "metadata", {}) or {}).get("modality", "text")),
                metadata=getattr(r, "metadata", {}) or {},
            ))
        return hits
