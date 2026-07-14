"""core/eval/memory_eval.py — 统一记忆层召回质量评估(L4 标尺的记忆专项)。

量化"记忆到底记得准不准":给一组(记忆, 查询, 期望命中)三元组,把记忆全部写入一个
独立的 UnifiedMemory,逐个查询,统计 recall@1 / recall@3 / MRR。用真实后端(默认
vector→chroma 真嵌入)即可跑出真实语义召回数字。

刻意用**低词面重合**的中英文配对,这样关键词后端会差、真嵌入语义后端才能召回——
正好用来验证"语义"是不是真的。
"""

from __future__ import annotations

import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class MemoryEvalCase:
    memory: str  # 要写入的一条记忆
    query: str  # 检索用查询(与记忆低词面重合)
    mem_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


def builtin_memory_cases() -> List[MemoryEvalCase]:
    return [
        MemoryEvalCase("猫是独立的动物，喜欢独处并发出呼噜声", "feline pet behaviour purring"),
        MemoryEvalCase("Automobiles run on internal combustion engines", "汽车的动力来自什么"),
        MemoryEvalCase("巴黎是法国的首都，有埃菲尔铁塔", "what is the capital city of France"),
        MemoryEvalCase("团队会议从上午改到了下午三点", "when does the meeting start"),
        MemoryEvalCase("光合作用把阳光转化为植物的能量", "how do plants make energy from sunlight"),
        MemoryEvalCase("部署服务时端口 9229 被占用导致崩溃", "service crash because a port was already in use"),
        MemoryEvalCase("The Great Wall of China is over 13000 miles long", "中国那道很长的古代城墙有多长"),
        MemoryEvalCase("用户偏好用中文回答并且语气简洁", "language and tone the user prefers"),
    ]


@dataclass
class MemoryEvalReport:
    total: int
    recall_at_1: float
    recall_at_3: float
    mrr: float
    backends: List[str]
    per_case: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "total": self.total,
            "recall@1": round(self.recall_at_1, 4),
            "recall@3": round(self.recall_at_3, 4),
            "mrr": round(self.mrr, 4),
            "backends": self.backends,
            "per_case": self.per_case,
        }


def run_memory_eval(backends: str = "", cases: List[MemoryEvalCase] = None) -> MemoryEvalReport:
    """把用例写入一个全新的 UnifiedMemory 并评估召回。backends 默认取环境变量。"""
    from core.memory.unified import UnifiedMemory
    from core.memory.vector_backend_provider import VectorBackendProvider

    cases = cases or builtin_memory_cases()
    # 用独立目录,避免污染线上记忆
    os.environ.setdefault("CHROMA_PERSIST_DIR", tempfile.mkdtemp(prefix="memeval_"))
    # 评估只用向量后端(文本语义);跨模态后端不参与文本召回评估
    um = UnifiedMemory([VectorBackendProvider()])

    for c in cases:
        um.remember(c.memory, tags=["memeval"], metadata={"id": c.mem_id})

    hit1 = hit3 = 0
    rr_sum = 0.0
    per_case: List[Dict] = []
    for c in cases:
        hits = um.recall(c.query, top_k=3)
        # 命中判定:召回内容包含该记忆原文(或其前缀)
        rank = 0
        for i, h in enumerate(hits, 1):
            if c.memory[:24] in (h.content or "") or (h.content or "")[:24] in c.memory:
                rank = i
                break
        if rank == 1:
            hit1 += 1
        if 1 <= rank <= 3:
            hit3 += 1
        if rank:
            rr_sum += 1.0 / rank
        per_case.append({"query": c.query, "rank": rank or None})

    n = len(cases) or 1
    return MemoryEvalReport(
        total=len(cases),
        recall_at_1=hit1 / n,
        recall_at_3=hit3 / n,
        mrr=rr_sum / n,
        backends=um.backend_names,
        per_case=per_case,
    )
