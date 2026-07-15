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


def _core_markers() -> tuple:
    """热核工具名标记(每轮几乎必用的元能力)。可用 GALAXY_TOOLS_CORE 覆盖
    (逗号分隔的名字子串);留空则用内置默认。"""
    raw = os.environ.get("GALAXY_TOOLS_CORE", "").strip()
    if raw:
        markers = tuple(m.strip() for m in raw.split(",") if m.strip())
        if markers:
            return markers
    return _CORE_TOOL_MARKERS


def _tool_name(t: Dict[str, Any]) -> str:
    return str((t.get("function") or {}).get("name", ""))


def _is_core(name: str, markers: tuple) -> bool:
    return any(m in name for m in markers)


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
    *,
    session_unlocked: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """工具数 ≤ 阈值时原样返回(零行为变化);超了才挑 top-K。

    GALAXY_TOOLS_SLIM=auto(默认)|off;阈值 GALAXY_TOOLS_MAX=24。
    核心工具(memory__/ask_human__)始终入选。

    session_unlocked: 调用方按 session 持有的【已解锁工具名】列表。传入且
      GALAXY_TOOLS_JIT=on 时,改走单调追加式 JIT(见 select_tools_jit)——
      热核以外的工具默认不下发、按需逐轮解锁,专治首轮 56s 预填。默认不传 →
      沿用下面的粘滞/相关性逻辑,零行为变化。

    选取策略(GALAXY_TOOLS_STICKY=auto(默认)|on|off):
    - 粘滞(本地主脑场景):按【静态优先级】挑——核心工具 + 目录原序
      前 K 个,与 query 无关 → 逐回合字节级同一子集。这是 CPU 本地模型
      的关键:按 query 挑会让每回合工具子集不同 → 提示词前缀不同 →
      Ollama KV 前缀缓存每回合失效 → 每回合全量重预填(数千 token,
      CPU 上十几秒)。粘滞牺牲少量相关性,换回"prefill 只发生一次"。
    - 非粘滞(云端场景,prefill 便宜):按与本次请求的词法相关性挑
      top-K,排序稳定(同分保持原序)。
    auto = 已选本地主脑(OLLAMA_MODEL 非空)时粘滞,否则按相关性。
    """
    mode = os.environ.get("GALAXY_TOOLS_SLIM", "auto").strip().lower()
    if mode in ("0", "off", "false", "no"):
        return tools

    # ── 单调追加式 JIT(会话级前缀缓存友好，见 select_tools_jit)──────────
    # 调用方传入本会话持有的 unlocked 列表且开关开启时走这条:不受下面 24 阈值
    # 约束(热核以外的工具默认不下发,按需逐轮解锁)。默认关闭,零行为变化。
    if session_unlocked is not None and _jit_enabled():
        return select_tools_jit(tools, query, session_unlocked, max_tools=max_tools)

    limit = max_tools or _env_int("GALAXY_TOOLS_MAX", 24)
    if limit <= 0 or len(tools) <= limit:
        return tools

    sticky_mode = os.environ.get("GALAXY_TOOLS_STICKY", "auto").strip().lower()
    sticky = sticky_mode in ("1", "on", "true", "yes") or (
        sticky_mode == "auto" and bool(os.environ.get("OLLAMA_MODEL", "").strip())
    )
    if sticky:
        core = [
            t for t in tools if any(m in str((t.get("function") or {}).get("name", "")) for m in _CORE_TOOL_MARKERS)
        ]
        rest = [t for t in tools if t not in core]
        picked_sticky = core + rest[: max(0, limit - len(core))]
        # 保持目录原序(与 core/rest 拼接后的顺序已是原序稳定的)
        return picked_sticky

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


# ---------------------------------------------------------------------------
# 4. 单调追加式 JIT 工具加载(会话级前缀缓存友好)
# ---------------------------------------------------------------------------


def _jit_enabled() -> bool:
    """GALAXY_TOOLS_JIT=on|1|true|yes 开启;默认关闭(零行为变化)。"""
    return os.environ.get("GALAXY_TOOLS_JIT", "off").strip().lower() in ("1", "on", "true", "yes")


def select_tools_jit(
    tools: List[Dict[str, Any]],
    query: str,
    unlocked: List[str],
    max_tools: int = 0,
) -> List[Dict[str, Any]]:
    """单调追加式 JIT 工具选择 —— 专治 CPU 本地模型的首轮预填。

    与 slim_tools 的"每轮重挑"不同:本函数维护一个【只增不减】的已解锁集合
    ``unlocked``(调用方按 session 持有并复用,函数原地 mutate 它)。每轮:

      1. 热核工具(``_core_markers()``)始终入选 —— 每轮几乎必用的元能力;
      2. 本轮 ``query`` 词法命中的非核心工具 → 追加进 ``unlocked``(去重、保序,
         只在末尾追加、从不删除或重排);
      3. 输出 = ``[热核(目录序)] + [unlocked(解锁序)]``,映射回当前 ``tools``。

    因为 ``unlocked`` 单调增长,跨轮的提示词工具前缀也单调增长 → 只有"解锁到
    新工具的那一轮"付一次局部重预填,其余轮次(不解锁新工具)全命中 Ollama 的
    KV 前缀缓存 → 首轮从"全量 24 个 ≈3.2k token"降到"热核几百 token",同时不像
    naive JIT 那样每轮砸缓存。

    参数
    ----
    unlocked:
        有序、可变的【工具名】列表(调用方按 session 持有)。原地更新:
        追加本轮命中的新工具名;顺带剔除已从目录消失的名字(能力下线)。
    max_tools:
        已解锁工具的总量上限(含热核),默认 ``GALAXY_TOOLS_MAX``。达上限即
        冻结,不再解锁新工具(宁可漏召回也不无界膨胀/砸缓存)。

    返回选中的 ``tools`` 子列表,可直接下发给模型。
    """
    limit = max_tools or _env_int("GALAXY_TOOLS_MAX", 24)
    markers = _core_markers()

    # 目录:名字 → 工具(去重,保留首个出现顺序)
    by_name: Dict[str, Dict[str, Any]] = {}
    order: Dict[str, int] = {}
    for i, t in enumerate(tools):
        nm = _tool_name(t)
        if nm and nm not in by_name:
            by_name[nm] = t
            order[nm] = i

    core_names = [nm for nm in by_name if _is_core(nm, markers)]
    core_set = set(core_names)

    # 剔除已消失/已被归类为核心的陈旧解锁项(原地,保持其余项的相对顺序)
    unlocked[:] = [nm for nm in unlocked if nm in by_name and nm not in core_set]
    # 去重(防御:调用方若重复传入)——保序保留首次
    if len(set(unlocked)) != len(unlocked):
        _seen: set = set()
        unlocked[:] = [nm for nm in unlocked if not (nm in _seen or _seen.add(nm))]

    unlocked_budget = max(0, limit - len(core_names))
    q_terms = _terms_of(query)
    if q_terms and len(unlocked) < unlocked_budget:
        already = set(unlocked)
        candidates = []
        for nm, t in by_name.items():
            if nm in core_set or nm in already:
                continue
            fn = t.get("function") or {}
            blob = _terms_of(f"{nm} {fn.get('description', '')}")
            score = len(q_terms & blob)
            if score > 0:
                candidates.append((score, order[nm], nm))
        # 命中分高者优先解锁;同分按目录原序(确定性,便于测试与复现)
        candidates.sort(key=lambda x: (-x[0], x[1]))
        for _, _, nm in candidates:
            if len(unlocked) >= unlocked_budget:
                break
            unlocked.append(nm)

    # 输出:热核(目录序)+ 已解锁(解锁序)——前缀单调、字节稳定
    picked = [by_name[nm] for nm in by_name if nm in core_set]
    picked += [by_name[nm] for nm in unlocked]
    return picked
