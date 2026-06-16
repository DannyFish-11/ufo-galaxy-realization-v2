"""core/memory/omni_simplemem_provider.py — SimpleMem 文本终身记忆后端（可选）。

⚠️ 重要事实校正（实测 `pip install simplemem==0.1.0` 后）：
PyPI 上的 `simplemem` 是 **纯文本** 的 SimpleMem(`SimpleMemSystem`: add_dialogue/ask)，
**不是论文里的多模态 Omni-SimpleMem**(后者未发布到 PyPI)。因此本后端提供的是
**文本终身记忆**(选择性摄入 + 反思/规划),不是图像/音频原生记忆。真正的跨模态需要
另接图像/音频 embedding(如 CLIP)或从 GitHub 源码装 Omni-SimpleMem。

依赖为可选：未安装 `simplemem` 或未配置 LLM key 时 available()=False，上层自动跳过，
绝不影响主流程。需要一个 OpenAI 兼容 key（SimpleMem 用 LLM 构建记忆并回答 ask）。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from core.memory.base import MemoryHit, MemoryProvider

logger = logging.getLogger("Galaxy.Memory.SimpleMem")


def _api_key() -> str:
    return (
        os.getenv("GALAXY_SIMPLEMEM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
        or ""
    )


class OmniSimpleMemProvider(MemoryProvider):
    # 名称保留 backend_name="omni_simplemem" 以兼容配置，但实为 SimpleMem 文本后端。
    backend_name = "omni_simplemem"

    def __init__(self) -> None:
        self._mem = None
        self._available: Optional[bool] = None
        self._dirty = False

    def available(self) -> bool:
        if self._available is None:
            ok = False
            try:
                import simplemem  # noqa: F401
                ok = hasattr(simplemem, "SimpleMemSystem") and bool(_api_key())
            except Exception:  # noqa: BLE001
                ok = False
            if not ok:
                logger.debug(
                    "SimpleMem backend unavailable (need `pip install simplemem` + an LLM key)"
                )
            self._available = ok
        return self._available

    def _ensure(self):
        if self._mem is None:
            from simplemem import SimpleMemSystem
            db_dir = os.getenv("GALAXY_OMNIMEM_DIR", "./data/omni_simplemem")
            try:
                os.makedirs(db_dir, exist_ok=True)
            except Exception:  # noqa: BLE001
                pass
            self._mem = SimpleMemSystem(
                api_key=_api_key(),
                model=os.getenv("GALAXY_SIMPLEMEM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
                base_url=os.getenv("GALAXY_SIMPLEMEM_BASE_URL") or os.getenv("OPENAI_API_BASE"),
                db_path=os.path.join(db_dir, "simplemem.db"),
            )
        return self._mem

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        # SimpleMem 是文本后端：媒体只能以其文字说明(caption=content)写入。
        if not content or not self.available():
            return
        try:
            speaker = (tags[0] if tags else None) or "user"
            self._ensure().add_dialogue(speaker, content)
            self._dirty = True
        except Exception as exc:  # noqa: BLE001 — 写入失败不影响主流程
            logger.debug("simplemem remember failed: %s", exc)

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:
        if not query or not self.available():
            return []
        try:
            mem = self._ensure()
            if self._dirty:
                # 把累积的对话固化成记忆（涉及 LLM 处理，故批量在召回时做）
                try:
                    mem.finalize()
                finally:
                    self._dirty = False
            answer = mem.ask(query)
        except Exception as exc:  # noqa: BLE001
            logger.debug("simplemem recall failed: %s", exc)
            return []
        if not answer:
            return []
        return [MemoryHit(content=str(answer), score=0.6, source=self.backend_name, modality="text")]
