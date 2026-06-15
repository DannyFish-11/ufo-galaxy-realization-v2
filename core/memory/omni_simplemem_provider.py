"""core/memory/omni_simplemem_provider.py — 路 B：Omni-SimpleMem 跨模态终身记忆。

封装 `simplemem`(Omni-SimpleMem, arXiv 2604.01007)：原生支持文/图/音/视频的
终身记忆，选择性摄入 + FAISS/BM25 渐进检索 + 知识图谱多跳。

依赖为**可选**：未 `pip install simplemem` 时 available()=False，上层自动跳过，
绝不影响主流程。需要嵌入模型(Qwen3-Embedding)+LanceDB+一个 OpenAI 兼容 key。

注意：simplemem 的 add_image/add_audio/add_video 接收**文件路径**；本系统的摄像头/
麦克风是 base64 内存数据，因此媒体写入需先落临时文件（media_path 经 metadata 传入）。
纯文本路径(add_text/query)是当前 live 主用法。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.Omni")


class OmniSimpleMemProvider(MemoryProvider):
    backend_name = "omni_simplemem"

    def __init__(self) -> None:
        self._mem = None
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if self._available is None:
            try:
                import simplemem  # noqa: F401
                self._available = True
            except Exception:  # noqa: BLE001 — 未安装即不可用
                self._available = False
        return self._available

    def _ensure(self):
        if self._mem is None:
            from simplemem import SimpleMem  # 可选依赖
            # 持久化目录可经环境变量配置；其余走 simplemem 默认（嵌入模型/向量库）
            workdir = os.getenv("GALAXY_OMNIMEM_DIR", "./data/omni_simplemem")
            try:
                os.makedirs(workdir, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self._mem = SimpleMem(workdir=workdir)
        return self._mem

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.available():
            return
        try:
            mem = self._ensure()
            _tags = tags or []
            md = metadata or {}
            if modality == "image" and md.get("media_path"):
                mem.add_image(md["media_path"], tags=_tags)
            elif modality == "audio" and md.get("media_path"):
                mem.add_audio(md["media_path"], tags=_tags)
            elif modality == "video" and md.get("media_path"):
                mem.add_video(md["media_path"], tags=_tags)
            elif content:
                mem.add_text(content, tags=_tags)
        except Exception as exc:  # noqa: BLE001 — 写入失败不影响主流程
            logger.debug("omni remember failed: %s", exc)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        if not query or not self.available():
            return []
        try:
            mem = self._ensure()
            items = mem.query(query, top_k=top_k) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug("omni recall failed: %s", exc)
            return []
        hits: List[MemoryHit] = []
        for it in items:
            if isinstance(it, dict):
                hits.append(MemoryHit(
                    content=str(it.get("summary") or it.get("content") or ""),
                    score=float(it.get("score", 0.0) or 0.0),
                    source=self.backend_name,
                    modality=str(it.get("modality", "text")),
                    metadata=it,
                ))
            else:
                hits.append(MemoryHit(content=str(it), source=self.backend_name))
        return hits
