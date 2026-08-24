"""core/memory_provenance.py — 写进记忆的东西,当初是谁说的
=============================================================

为什么这一位比一次性的注入更要紧
--------------------------------
提示注入的影响是**有界**的:这一轮结束就没了。

但如果外部内容的结论被写进长期记忆,它就**永久化**了 —— 而且下次被检索出来时,
来源标签早就掉了,它会以"智能体自己的知识"的身份重新进入上下文。
**污染被洗白成了可信来源。**

OWASP 2026 把记忆投毒单列为 ASI06,理由正是这个:提示注入随会话重置,
而记忆投毒的**攻击与生效在时间上是解耦的** —— 写进去的那一刻什么都不会发生。

两条硬规矩
----------
1. **来源必须跟着内容一起写进去**,并且在检索时还在;
2. **外部来源的结论不能以第一人称写入**。

第 2 条的实现:不做文本改写,只做归属前缀
----------------------------------------
"把第一人称改写成转述"听起来对,但那需要理解句子 —— 用正则去猜哪句是第一人称,
猜错的方向恰恰是最糟的那个:**把一句转述误判成安全,或者把用户自己说的话
改得面目全非**。

所以这里不猜:不可信来源的内容**一律**加一条归属前缀,写明它是谁说的。
文本本身从此读起来就是转述,不需要任何一方去推断。

为什么前缀写进正文,而不是只放 metadata
--------------------------------------
metadata 会掉。各后端(向量库 / Omni-SimpleMem / 未来新增的)对 metadata 的
处置各不相同,检索路径也可能只取 ``content``。而**正文不会掉** —— 它就是被
检索出来、被送进上下文的那一份。

所以两头都写:metadata 给机器读,前缀给模型读。任何一头掉了,另一头还在。
这不是冗余,这是**在一条已知会掉东西的链路上,把要紧的那一位放在掉不了的地方**。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Iterable, Optional, Tuple

from core.context_provenance import ORIGINS, is_untrusted, trust_of

logger = logging.getLogger("Galaxy.MemoryProvenance")

#: metadata 里记来源的键。**唯一定义处** —— 写入与检索两边都用它。
ORIGIN_KEY = "galaxy_origin"

#: 正文里那条归属前缀的标记。检索侧要认出"这条已经标过了",避免重复加。
ATTRIBUTION_MARK = "〔来源:"

#: 各来源的归属措辞。只覆盖**不可信**那几档 —— 可信来源不加前缀,
#: 否则用户自己说的话也会被套上转述口吻,读起来像系统在怀疑用户。
_ATTRIBUTION: Dict[str, str] = {
    "memory": "早先的记忆",
    "tool_result": "某次工具返回",
    "external": "外部来源(网页/别的设备/仓外文本)",
    "unknown": "来源不明",
}


def attribution_for(origin: str) -> str:
    """这个来源的归属措辞。可信来源返回空串(不加前缀)。

    认不出的来源按 ``unknown`` 处理 —— 与 ``context_provenance`` 一致:
    判不出来按最低信任算,不按可信算。
    """
    if not is_untrusted(origin):
        return ""
    return _ATTRIBUTION.get(origin, _ATTRIBUTION["unknown"])


def already_attributed(content: str) -> bool:
    """这段正文是不是已经带过归属前缀了。

    有这一道是因为记忆会被**再写一次**(整理、迁移、跨设备同步),
    每次都加一层前缀会把正文堆成一串套娃。
    """
    return content.lstrip().startswith(ATTRIBUTION_MARK)


def stamp(
    content: str,
    *,
    origin: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """给一条要写进记忆的内容盖上来源。返回 ``(正文, metadata)``。

    ``origin`` 不传时问 ``core.context_provenance`` 的运行时回执 —— 也就是
    "这一轮上下文的下界"。那是个**保守**的默认:这一轮里进过网页正文,这一轮
    产生的记忆就按外部来源记。

    宁可把一条本来干净的记忆标成外部,也不要把一条外部来的标成干净的。
    """
    text = content if isinstance(content, str) else str(content)
    meta = dict(metadata or {})

    resolved = origin
    if resolved is None:
        try:
            from core.context_provenance import current  # noqa: PLC0415

            resolved = current().floor
        except Exception as exc:  # noqa: BLE001 — 取不到就按最坏
            logger.debug("取不到上下文来源,按 unknown 记: %s", exc)
            resolved = "unknown"

    if resolved not in ORIGINS:
        resolved = "unknown"

    meta[ORIGIN_KEY] = resolved

    label = attribution_for(resolved)
    if label and not already_attributed(text):
        text = f"{ATTRIBUTION_MARK}{label}〕{text}"

    return text, meta


def origin_of(metadata: Optional[Dict[str, Any]]) -> str:
    """从检索回来的 metadata 里读来源。读不到返回 ``unknown``。

    读不到**不等于**这条记忆是干净的 —— 它可能是这道闸上线之前写进去的存量。
    存量与"确认可信"必须可区分,所以这里返回 unknown 而不是某个可信档。
    """
    if not isinstance(metadata, dict):
        return "unknown"
    value = metadata.get(ORIGIN_KEY)
    return value if isinstance(value, str) and value in ORIGINS else "unknown"


# ══════════════════════════════════════════════════════════════════════════
# 检索侧:让来源活到被读出来的那一刻
# ══════════════════════════════════════════════════════════════════════════
#
# 只在写入时盖章是**不够的**。整套威胁的要害在于:记忆被检索出来、重新进上下文
# 的那一刻,如果来源掉了,它就以"智能体自己的知识"的身份出现 —— 污染被洗白。
#
# 所以取回来之后要**再判一次**,并且把结论交给上下文装配,让那一段按真实来源记,
# 而不是一律记成 memory。

_recall_lock = threading.Lock()
_last_recall_origin: str = ""


def worst_origin(hits: Iterable[Any]) -> str:
    """这批检索结果里**最低**的那个来源。

    取最低而不是取多数:一条被投毒的记忆混在九条干净的里面,危险程度不因为
    它是少数就下降。空结果返回空串(**没检索到**,不是"检索到了都干净")。
    """
    worst = ""
    worst_score = None
    for hit in hits:
        origin = origin_of(getattr(hit, "metadata", None))
        score = trust_of(origin)
        if worst_score is None or score < worst_score:
            worst, worst_score = origin, score
    return worst


def record_recall(hits: Iterable[Any]) -> str:
    """检索处调用:记下这批结果的最低来源,并返回它。"""
    global _last_recall_origin
    value = worst_origin(hits)
    with _recall_lock:
        _last_recall_origin = value
    return value


def last_recall_origin() -> str:
    """只读:最近一次检索取回来的东西里,最低的那个来源。

    空串 = **这一轮没检索过**。调用方要把它与"检索过、结果干净"分开处理 ——
    前者说明不了任何事。
    """
    with _recall_lock:
        return _last_recall_origin


def reset_recall() -> None:
    """清回执。给测试用 —— 不清会让上一条用例的检索串到下一条。"""
    global _last_recall_origin
    with _recall_lock:
        _last_recall_origin = ""
