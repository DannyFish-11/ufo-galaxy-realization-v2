"""
core.cognitive.bm25_index — 零依赖 BM25 词法检索
=================================================

为本地记忆检索提供一个**不需要任何第三方库、不需要 embedding 服务**的 BM25 Okapi
排序器。比朴素的 Jaccard（只看词集合的交并比、忽略词频与稀有度）准得多：

- **词频(TF) 饱和**：一个词出现多次有用，但收益递减（k1）；
- **文档长度归一**：长文档不因为词多而占便宜（b）；
- **逆文档频率(IDF)**：越稀有的词区分度越高，权重越大。

中英混排友好的分词：ASCII 走 `[a-z0-9]+`；CJK 走「单字 + 相邻双字」二元组（显著提升
中文检索召回）。无外部依赖、纯标准库，可在无 GPU / 离线环境直接用。

用法::

    from core.cognitive.bm25_index import bm25_rank, tokenize

    docs = [("d1", "打开微信 发消息"), ("d2", "查询天气 北京")]
    ranked = bm25_rank("微信消息", docs, top_k=5)   # → [("d1", score), ...]
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence, Tuple

__all__ = ["tokenize", "BM25Index", "bm25_rank"]

_ASCII_TOKEN = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[一-鿿぀-ヿ가-힯]")


def tokenize(text: str) -> List[str]:
    """中英混排分词：ASCII 词 + CJK 单字 + CJK 相邻双字（best-effort，永不抛错）。"""
    if not text:
        return []
    try:
        lowered = text.lower()
        tokens: List[str] = _ASCII_TOKEN.findall(lowered)
        cjk_chars = _CJK.findall(lowered)
        tokens.extend(cjk_chars)
        # 相邻双字二元组（在原始顺序上，仅对连续 CJK 串）：提升中文短语区分度。
        for run in re.findall(r"[一-鿿぀-ヿ가-힯]+", lowered):
            for i in range(len(run) - 1):
                tokens.append(run[i:i + 2])
        return tokens
    except Exception:
        return []


class BM25Index:
    """可增量构建的 BM25 Okapi 索引（标准库实现）。

    参数 k1/b 用经典默认值（k1=1.5, b=0.75）。文档量在数千以内时，``search`` 直接线性
    打分足够快；超大规模可换持久化后端（接口保持不变）。
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._doc_ids: List[str] = []
        self._doc_tokens: List[List[str]] = []
        self._doc_freqs: List[Counter] = []
        self._doc_len: List[int] = []
        self._df: Counter = Counter()      # term → 出现该词的文档数
        self._avgdl: float = 0.0

    def add(self, doc_id: str, text: str) -> None:
        toks = tokenize(text)
        self._doc_ids.append(doc_id)
        self._doc_tokens.append(toks)
        freqs = Counter(toks)
        self._doc_freqs.append(freqs)
        self._doc_len.append(len(toks))
        for term in freqs:
            self._df[term] += 1
        self._avgdl = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0

    @classmethod
    def build(cls, documents: Sequence[Tuple[str, str]], **kw) -> "BM25Index":
        idx = cls(**kw)
        for doc_id, text in documents:
            idx.add(doc_id, text)
        return idx

    def _idf(self, term: str) -> float:
        n = len(self._doc_ids)
        df = self._df.get(term, 0)
        # +1 形式的 IDF，保证非负，避免常见词产生负分。
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """返回按 BM25 分数降序的 ``[(doc_id, score), ...]``（仅含 score>0 的文档）。"""
        if not self._doc_ids:
            return []
        q_terms = [t for t in tokenize(query) if self._df.get(t)]
        if not q_terms:
            return []
        scored: List[Tuple[str, float]] = []
        for i, doc_id in enumerate(self._doc_ids):
            freqs = self._doc_freqs[i]
            dl = self._doc_len[i] or 1
            score = 0.0
            for term in q_terms:
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                idf = self._idf(term)
                denom = tf + self.k1 * (1.0 - self.b + self.b * dl / (self._avgdl or 1.0))
                score += idf * (tf * (self.k1 + 1.0)) / denom
            if score > 0.0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k] if top_k and top_k > 0 else scored


def bm25_rank(
    query: str,
    documents: Sequence[Tuple[str, str]],
    top_k: int = 5,
) -> List[Tuple[str, float]]:
    """一次性对一批 ``(id, text)`` 文档按 BM25 排序（构建即用，适合几百~几千条）。"""
    if not query or not documents:
        return []
    return BM25Index.build(documents).search(query, top_k=top_k)
