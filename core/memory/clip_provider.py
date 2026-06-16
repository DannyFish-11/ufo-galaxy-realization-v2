"""core/memory/clip_provider.py — 真·跨模态记忆(CLIP 文↔图同空间)。

用 CLIP(`sentence-transformers` 的 'clip-ViT-B-32')把**文本和图像编码进同一向量
空间**，于是"用一句话召回相关画面"成为可能——这才是真正的跨模态记忆(不是把图片
转成 caption 文本)。图像向量持久化在独立的 Chroma 集合(cosine)。

职责边界：
- 只存**图像**(modality=image，经 media_path 读取)；文本由 vector 后端负责，
  本后端不重复存文本。
- recall(query)：把查询文本 CLIP-编码，去图像集合里按视觉语义召回 → 返回图像条目。
- 音频/视频不在此处(音频需 CLAP，另接)；非图像 remember 直接跳过。

依赖可选：缺 sentence-transformers / chromadb / PIL 时 available()=False，上层跳过。
模型较重(首次会下 ~600MB)，故惰性加载，且只在真正用到图像/召回时才加载。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.CLIP")

_COLLECTION = "galaxy_clip_memory"


class ClipMemoryProvider(MemoryProvider):
    backend_name = "clip"

    def __init__(self) -> None:
        self._model = None
        self._col = None
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if self._available is None:
            try:
                import sentence_transformers  # noqa: F401
                import chromadb  # noqa: F401
                from PIL import Image  # noqa: F401
                self._available = True
            except Exception:  # noqa: BLE001
                self._available = False
            if not self._available:
                logger.debug("CLIP backend unavailable (need sentence-transformers + chromadb + pillow)")
        return self._available

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            name = os.getenv("GALAXY_CLIP_MODEL", "clip-ViT-B-32")
            logger.info("Loading CLIP model %s (first run downloads weights)…", name)
            self._model = SentenceTransformer(name)
        return self._model

    def _get_col(self):
        if self._col is None:
            import chromadb
            persist = os.getenv("GALAXY_CLIP_DIR", os.path.join(
                os.getenv("CHROMA_PERSIST_DIR", "./data/clip_memory")))
            try:
                os.makedirs(persist, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            client = chromadb.PersistentClient(path=persist)
            self._col = client.get_or_create_collection(
                _COLLECTION, metadata={"hnsw:space": "cosine"}
            )
        return self._col

    def _embed_text(self, text: str):
        return self._get_model().encode(text, normalize_embeddings=True).tolist()

    def _embed_image(self, path: str):
        from PIL import Image
        with Image.open(path) as im:
            return self._get_model().encode(im.convert("RGB"), normalize_embeddings=True).tolist()

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        # 只处理图像；文本/音频/视频交给别的后端。
        if modality != "image" or not self.available():
            return
        md = metadata or {}
        path = md.get("media_path")
        if not path or not os.path.exists(path):
            return
        try:
            vec = self._embed_image(path)
            doc = content or md.get("caption") or "[image]"
            store_md = {"modality": "image"}
            for k, v in md.items():
                if k != "media_path" and isinstance(v, (str, int, float, bool)):
                    store_md[k] = v
            if tags:
                store_md["tags"] = ",".join(tags)
            self._get_col().add(
                ids=[str(md.get("id") or f"img_{uuid.uuid4().hex[:12]}")],
                embeddings=[vec],
                documents=[doc],
                metadatas=[store_md],
            )
        except Exception as exc:  # noqa: BLE001 — 写入失败不影响主流程
            logger.debug("clip remember failed: %s", exc)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        if not query or not self.available():
            return []
        try:
            col = self._get_col()
            if col.count() == 0:
                return []
            qvec = self._embed_text(query)
            res = col.query(query_embeddings=[qvec], n_results=min(top_k, col.count()))
        except Exception as exc:  # noqa: BLE001
            logger.debug("clip recall failed: %s", exc)
            return []
        hits: List[MemoryHit] = []
        docs = (res.get("documents") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        for i, doc in enumerate(docs):
            dist = dists[i] if i < len(dists) else 1.0
            hits.append(MemoryHit(
                content=str(doc),
                score=round(1.0 - float(dist), 4),   # cosine distance → similarity
                source=self.backend_name,
                modality="image",
                metadata=metas[i] if i < len(metas) else {},
            ))
        return hits
