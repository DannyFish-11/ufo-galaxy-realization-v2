"""core/memory/base.py — 统一记忆层的接口与数据类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryHit:
    """一次召回的结果条目（跨后端统一形状）。"""

    content: str
    score: float = 0.0
    source: str = ""          # 产出该条的后端名（vector_backend / omni_simplemem）
    modality: str = "text"    # text / image / audio / video
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content[:400],
            "score": round(self.score, 4),
            "source": self.source,
            "modality": self.modality,
            "metadata": self.metadata,
        }


class MemoryProvider:
    """记忆后端接口（同步）。

    实现需保证：``available()`` 为 False 时，``remember``/``recall`` 被上层跳过；
    任何内部异常都不应抛出到上层（由 UnifiedMemory 兜底，但 provider 自身也应稳健）。
    """

    backend_name: str = "base"

    def available(self) -> bool:  # pragma: no cover - interface
        return False

    def remember(
        self,
        content: str,
        *,
        modality: str = "text",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def recall(self, query: str, *, top_k: int = 5) -> List[MemoryHit]:  # pragma: no cover
        raise NotImplementedError
