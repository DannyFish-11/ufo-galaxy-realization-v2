"""core/context_trim.py — 对话上下文修剪(延迟优化·对话层)
================================================================

CPU 本地模型的延迟大头是 prompt 预填(prefill)。本模块提供三个纯函数,
把每轮喂给模型的字节数压到"刚好够用":

  1. :func:`clip_tool_result` — 工具结果**插入时**截断(头+尾保留,中段
     打标记丢弃)。只在插入时截,之后不再动它——事中改写历史会作废 Ollama
     的前缀 KV 缓存,省的不如重预填花的多。
  2. :func:`prune_stale_tool_results` — ReAct 长任务里,早期轮次的工具结果
     模型早已消化(结论体现在其后的推理里),第 N 轮还全文携带纯属浪费。
     保最近 K 轮完整,更早的大结果换成短存根(OpenClaw 的 TTL/Claude Code
     的 snip 思路)。只剪"够大"的,小结果不值得为它破坏前缀缓存。
  3. :func:`slim_tools` — 工具定义瘦身(auto 档):工具数超阈值才按与本次
     请求的词法相关性挑 top-K,核心工具(记忆召回/问人)始终保留。
     阈值内**原样返回**(零行为变化)——质量优先,只防御病态膨胀。

全部零 LLM 成本、零 IO;开关与阈值均可 env 调。
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

# 始终保留的核心工具(与具体任务无关的"元能力")
_CORE_TOOL_MARKERS = ("memory__", "ask_human__")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 1. 工具结果插入截断
# ---------------------------------------------------------------------------


def clip_tool_result(text: str, max_chars: int = 0) -> str:
    """头+尾保留式截断:长工具输出的结论常在末尾(exit code/汇总行),
    纯 ``[:N]`` 会把它切没。默认上限 GALAXY_TOOL_RESULT_MAX_CHARS=4000。"""
    limit = max_chars or _env_int("GALAXY_TOOL_RESULT_MAX_CHARS", 4000)
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.75)
    tail = limit - head
    return f"{text[:head]}\n…[中段已修剪,原文共 {len(text)} 字]…\n{text[-tail:]}"


# ---------------------------------------------------------------------------
# 2. ReAct 老轮次工具结果修剪
# ---------------------------------------------------------------------------


def prune_stale_tool_results(
    messages: List[Dict[str, Any]],
    keep_rounds: int = 0,
    min_chars: int = 500,
) -> int:
    """原地把"最近 keep_rounds 轮之外"的大工具结果换成短存根,返回修剪条数。

    轮次边界 = 带 tool_calls 的 assistant 消息。GALAXY_TOOL_PRUNE_KEEP_ROUNDS
    默认 3;设 0 关闭。只剪 >min_chars 的(小结果不值得作废前缀缓存);
    存根保留开头片段,模型仍知道"当时拿到过什么",需要时可重新调用。
    """
    keep = keep_rounds or _env_int("GALAXY_TOOL_PRUNE_KEEP_ROUNDS", 3)
    if keep <= 0:
        return 0
    round_starts = [
        i
        for i, m in enumerate(messages)
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("tool_calls")
    ]
    if len(round_starts) <= keep:
        return 0
    cutoff = round_starts[-keep]  # 此下标之前的轮次为"老轮次"
    pruned = 0
    for m in messages[:cutoff]:
        if not (isinstance(m, dict) and m.get("role") == "tool"):
            continue
        content = m.get("content")
        if not isinstance(content, str) or len(content) <= min_chars:
            continue
        m["content"] = (
            f"[早期工具结果已修剪·原 {len(content)} 字,要点见其后推理;" f"如需原文请重新调用] {content[:200]}…"
        )
        pruned += 1
    return pruned


# ---------------------------------------------------------------------------
# 3. 工具定义瘦身(auto 档)
# ---------------------------------------------------------------------------


def _terms_of(text: str) -> set:
    """查询/工具描述 → 词项集合:ASCII 词 + CJK 双字滑窗(零依赖轻量分词)。"""
    text = (text or "").lower()
    terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    cjk = re.findall(r"[一-鿿]", text)
    terms.update("".join(p) for p in zip(cjk, cjk[1:]))
    terms.update(cjk)
    return terms


def slim_tools(
    tools: List[Dict[str, Any]],
    query: str,
    max_tools: int = 0,
) -> List[Dict[str, Any]]:
    """工具数 ≤ 阈值时原样返回(零行为变化);超了才按词法相关性挑 top-K。

    GALAXY_TOOLS_SLIM=auto(默认)|off;阈值 GALAXY_TOOLS_MAX=24。
    核心工具(memory__/ask_human__)始终入选;排序稳定(同分保持原序),
    不破坏前缀缓存的字节稳定性。
    """
    mode = os.environ.get("GALAXY_TOOLS_SLIM", "auto").strip().lower()
    if mode in ("0", "off", "false", "no"):
        return tools
    limit = max_tools or _env_int("GALAXY_TOOLS_MAX", 24)
    if limit <= 0 or len(tools) <= limit:
        return tools

    q_terms = _terms_of(query)

    def _score(t: Dict[str, Any]) -> float:
        fn = t.get("function") or {}
        name = str(fn.get("name", ""))
        if any(marker in name for marker in _CORE_TOOL_MARKERS):
            return float("inf")  # 核心元能力永不裁
        blob = _terms_of(f"{name} {fn.get('description', '')}")
        if not q_terms or not blob:
            return 0.0
        return len(q_terms & blob) / (len(q_terms) ** 0.5)

    scored = [(_score(t), i, t) for i, t in enumerate(tools)]
    picked = sorted(scored, key=lambda x: (-x[0], x[1]))[:limit]
    picked.sort(key=lambda x: x[1])  # 恢复原始相对顺序(前缀字节稳定)
    return [t for _, _, t in picked]
