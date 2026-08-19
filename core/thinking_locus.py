"""core/thinking_locus.py — 这一轮是谁在想(路由结论的只读回执)
================================================================

``select_brain_for_role()`` 每次都得出一个明确结论:这个角色的活交给
``provider:model``,理由是什么。**这个结论此前没有任何人能事后问到** —— 它只作为
返回值流向调用方,用完即弃。

于是两件事做不了:

1. **渲染端画不出"它在哪儿想"**。三态呈现里 manifest 那一段,本地推理和云端推理
   是完全不同的两件事(一个在这台机器上耗电,一个在网络另一头),而契约里没有任何
   一位能把它们分开。
2. **模态协商拿不到 locus**。``core.modality_capability.negotiate(locus=...)`` 的
   第四维要的正是这个 —— 本地档位瞎着但这轮交给一家能看的云端时,视觉是可用的。
   没有回执,那个参数就永远只能靠调用方自己猜着传。

本模块只做一件事:把**最近一次角色路由结论**记在进程内,供只读回执。

刻意不做的
----------
* **不做历史**:只留最后一次。要审计走遥测,不要在渲染热路径上翻列表。
* **不做推断**:``route_type`` / ``is_fallback`` 由路由那一侧**当场按角色意图**填,
  不在这里从中文 reason 里正则反解 —— 那种反解会在改一句措辞时静默失效。
* **不主动构造**:读的一侧用 ``sys.modules.get`` 看本模块是否被导入过(见
  ``core.render_pathway``),没有路由发生过就是没有,不是"本地"。

"没决策过" 与 "决策成本地" 必须分得开
-------------------------------------
默认 locus 是 ``"unknown"`` 而不是 ``"local"``。把没发生过的事报成本地,渲染端会在
一个还没开始想的时刻画出"本地在想",而那正是三态里最不该乱画的那一段。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

#: 想这件事发生在哪一侧。``unknown`` = 本进程还没路由过任何角色。
THINKING_LOCI: tuple = ("unknown", "local", "cloud")

#: 这次路由属于哪一类角色意图 —— 与 ``ROLE_BRAIN_HINTS`` 的三分完全对应。
#: dispatch=派活(本地硬优先) / produce=产出(按能力选) / gatekeep=把关(常驻云端)。
ROUTE_TYPES: tuple = ("unknown", "dispatch", "produce", "gatekeep")


@dataclass(frozen=True)
class ThinkingLocusRecord:
    """一次角色路由的结论回执。"""

    locus: str = "unknown"
    provider: str = ""
    model: str = ""
    role: str = ""
    route_type: str = "unknown"
    reason: str = ""
    #: 角色意图没被满足 —— 派活角色落到了云端,或把关角色回落到了本地。
    #:
    #: 这一位单独存在,是因为它对渲染和排障都有意义而 locus 本身说不出来:
    #: 「把关角色在本地」既可能是纯本地方案的正常形态,也可能是云端全挂了的降级,
    #: 两者画出来该不一样。
    is_fallback: bool = False
    #: 记录时刻(``time.time()``)。0 = 从没记录过。
    decided_at: float = 0.0

    @property
    def is_decided(self) -> bool:
        return self.locus in ("local", "cloud")


_UNDECIDED = ThinkingLocusRecord()

_lock = threading.Lock()
_last: ThinkingLocusRecord = _UNDECIDED


def record(
    *,
    provider: str,
    model: str,
    role: str,
    is_local: bool,
    route_type: str,
    reason: str = "",
    is_fallback: bool = False,
) -> ThinkingLocusRecord:
    """记下这一次的路由结论并返回它。

    ``provider`` 为空或 ``"none"`` 时记成"没选出来"(locus 仍是 unknown)——
    路由失败不是"在本地想",把它记成本地会让渲染端画出一个不存在的推理过程。
    """
    global _last
    name = str(provider or "").strip()
    if not name or name == "none":
        rec = ThinkingLocusRecord(
            role=str(role or ""),
            route_type=route_type if route_type in ROUTE_TYPES else "unknown",
            reason=str(reason or ""),
            decided_at=time.time(),
        )
    else:
        rec = ThinkingLocusRecord(
            locus="local" if is_local else "cloud",
            provider=name,
            model=str(model or ""),
            role=str(role or ""),
            route_type=route_type if route_type in ROUTE_TYPES else "unknown",
            reason=str(reason or ""),
            is_fallback=bool(is_fallback),
            decided_at=time.time(),
        )
    with _lock:
        _last = rec
    return rec


def last() -> ThinkingLocusRecord:
    """最近一次结论;从没路由过时返回 ``locus="unknown"`` 的那一份(不是 None)。

    返回一个**语义明确的空态**而不是 None:调用方读到 ``unknown`` 知道"还没想过",
    读到 None 只能知道"这个函数没给我东西",而后者会诱导它去补一个默认值。
    """
    with _lock:
        return _last


def reset() -> None:
    """清回"从没路由过"。给测试用 —— 本模块是进程级状态,不清会串味。"""
    global _last
    with _lock:
        _last = _UNDECIDED


def locus_provider() -> Optional[str]:
    """最近一次结论里的 provider 名,供 ``negotiate(locus=...)`` 直接传。

    本地或未决策时返回 None —— ``negotiate`` 的 locus 参数只接受**远端**归属,
    本地那一侧的能力源本来就是它的默认。
    """
    rec = last()
    return rec.provider if rec.locus == "cloud" and rec.provider else None


THINKING_LOCUS_AUTHORITY: str = (
    "THINKING_LOCUS_V1: core/thinking_locus.py | 角色路由结论的唯一只读回执. "
    "record() 由 multi_llm_router.select_brain_for_role 单一漏斗调用; "
    "last() → ThinkingLocusRecord(locus/provider/model/role/route_type/is_fallback). "
    "locus 默认 unknown 而非 local(没决策过≠决策成本地); route_type/is_fallback "
    "由路由侧按角色意图当场填, 不从 reason 文本反解."
)

__all__ = [
    "THINKING_LOCI",
    "ROUTE_TYPES",
    "ThinkingLocusRecord",
    "record",
    "last",
    "reset",
    "locus_provider",
    "THINKING_LOCUS_AUTHORITY",
]
