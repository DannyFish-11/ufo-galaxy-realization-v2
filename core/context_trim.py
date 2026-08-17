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

import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.ContextTrim")

# 始终保留的核心工具(与具体任务无关的"元能力")
_CORE_TOOL_MARKERS = ("memory__", "ask_human__")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


#: 字符 → token 的换算分母。**刻意取小**(即高估 token 数)。
#:
#: 混合中英文本大致 2.5–3.5 字符/token(中文更接近 1.5,英文更接近 4)。这里取保守的
#: 一端:估多了只是把上下文开大一点,估少了是**装不下却以为装得下**,而装不下的后果
#: 是在 llama.cpp 那层**静默截断**——用户看到的是"它怎么忘了前面说的",不是报错。
_CHARS_PER_TOKEN = 2.5

#: **兜底**:一条工具定义折多少 token —— 只在真工具表拿不到时才用。
#:
#: 这个数原来是主判据,而它纯粹是拍的。工具表其实是**可以枚举的**(见
#: :func:`_real_tool_table_tokens`):技能加载器和能力注册表在加载模型之前就装配好了,
#: 序列化一遍数字符就是真值,不需要猜"一条大概多少"。拿不到时才退回这里。
_TOKENS_PER_TOOL_DEF_FALLBACK = 180

#: 系统提示 + 人格 + 留给模型回复的余量。
#:
#: **这里刻意不含会话历史。** 历史是唯一无界、且每轮都在长的一项,把它折进一个常数
#: 是这个公式最弱的地方 —— 而更要命的是,这个函数的结果曾被当成 ``n_ctx`` 的**上限**,
#: 于是"唯一真正会变的东西"反而说了不算。现在它只当**下限**(见
#: ``ComputeScheduler.context_budget_for``):历史往上涨的空间由显存决定,由
#: 压缩层(:mod:`core.context_compaction`)负责在涨到头之前把它收敛掉。
_TOKENS_BASELINE = 2048


def _real_tool_table_tokens() -> int:
    """按**真实工具表**算它折多少 token；拿不到返回 0。

    比 ``条数 × 180`` 强在两点:数的是真名字、真描述、真 JSON Schema;而且工具表
    变了它自己会变,不需要谁记得回来调那个 180。

    枚举点用技能加载器的 MCP 工具视图 —— 它在**加载模型之前**就装配好了,所以
    这个数在决定 ``n_ctx`` 的那一刻确实拿得到,不存在"运行时才知道"的问题。
    """
    try:
        from core.skill_loader import skill_loader  # noqa: PLC0415

        tools = skill_loader.list_as_mcp_tools()
    except Exception as exc:  # noqa: BLE001 — 拿不到就退回兜底估算，不是错误
        logger.debug("真实工具表不可枚举(退回按条数估算): %s", exc)
        return 0
    if not tools:
        return 0
    try:
        import json as _json  # noqa: PLC0415

        chars = len(_json.dumps(tools, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        logger.debug("工具表序列化失败(退回按条数估算): %s", exc)
        return 0
    return count_tokens(chars_or_text=chars)


def count_tokens(chars_or_text) -> int:
    """把字符数(或一段文本)折成 token 数 —— 换算只此一处。

    有真 tokenizer 就用真的(已加载的 llama.cpp 模型自带一个);没有就按
    ``_CHARS_PER_TOKEN`` 折算。**分成两条路而不是只留估算**,是因为估算的方向性
    后果不对称:估少了是静默截断,估多了只是多开一点上下文。
    """
    if isinstance(chars_or_text, str):
        text, chars = chars_or_text, len(chars_or_text)
        try:
            from core.local_model_backends import tokenize_with_loaded_model  # noqa: PLC0415

            real = tokenize_with_loaded_model(text)
            if real > 0:
                return real
        except Exception as exc:  # noqa: BLE001
            logger.debug("真 tokenizer 不可用(按字符折算): %s", exc)
    else:
        chars = int(chars_or_text or 0)
    return int(chars / _CHARS_PER_TOKEN)


def assembled_token_demand() -> int:
    """按**本仓库自己配的那几个预算**推出:一次请求最多会装配多少 token。

    为什么要有这个函数
    ==================
    ``n_ctx`` 原来写死 4096,而这个仓库实际会装配多少,从来没有一处算过。两头是断的:

    * 这里按**字符数**和**工具条数**裁(``GALAXY_TOOL_RESULT_MAX_CHARS`` /
      ``GALAXY_TOOLS_MAX``),完全不知道模型的 token 窗口有多大;
    * ``LlamaCppBackend`` 按 **token** 分配 4096,完全不知道上面装了多少。

    两个数没有任何一处核对。装配量超了就在 llama.cpp 那层被悄悄截断 —— 表现是
    "它记不住前面说的",而不是任何一条错误。**这个函数就是把"需要多长"这一端
    变成一个说得出来的数**,好让分配那一端能拿它去比。

    判据全部取自本模块已有的那几个 env 预算,不新造配置项 —— 改 ``GALAXY_TOOLS_MAX``
    之类的时候,这里跟着变,不需要谁记得同步。

    Returns:
        这次装配的 token 上界(保守估计,宁可估多)。
    """
    tools = max(0, _env_int("GALAXY_TOOLS_MAX", 24))
    result_chars = max(0, _env_int("GALAXY_TOOL_RESULT_MAX_CHARS", 4000))
    keep_rounds = max(0, _env_int("GALAXY_TOOL_PRUNE_KEEP_ROUNDS", 3))

    # 工具定义:先数真表,数不到才按条数估。真表可能比 GALAXY_TOOLS_MAX 多,
    # 但装配时会被 slim_tools 裁到那个上限,所以取两者的小者才是真实装配量。
    real_tool_tokens = _real_tool_table_tokens()
    if real_tool_tokens > 0:
        per_tool = max(1, real_tool_tokens // max(1, _tool_table_size()))
        tool_defs = min(real_tool_tokens, tools * per_tool)
    else:
        tool_defs = tools * _TOKENS_PER_TOOL_DEF_FALLBACK

    tool_results = count_tokens(chars_or_text=result_chars * keep_rounds)
    return int(tool_defs + tool_results + _TOKENS_BASELINE)


def _tool_table_size() -> int:
    """真实工具表有几条；拿不到返回 0。"""
    try:
        from core.skill_loader import skill_loader  # noqa: PLC0415

        return len(skill_loader.list_as_mcp_tools() or [])
    except Exception:  # noqa: BLE001
        return 0


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
