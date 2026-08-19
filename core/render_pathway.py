"""core/render_pathway.py — 渲染契约的两位:走哪条通路、在哪儿想
==================================================================

三态呈现里有两件事,后端一直知道、契约里一直没有:

**一、走的是原生还是桥**(:class:`ModalityPathwayView`)
    "它在听" 这件事有两种完全不同的实现:模型原生吃音频,还是本机 ASR 把音频转成
    文字再喂进去。前者是一条通路,后者是两段。第一态那两侧的氛围光要画的正是
    "此刻哪几条通路是通的、是原生还是接了桥" —— 契约里只有 ``perception``
    (有没有信号),没有"这条信号是怎么进去的"。

**二、这一轮在哪儿想**(:class:`ThinkingLocusView`)
    manifest 那一段,本地推理与云端推理是完全不同的两件事:一个在这台机器上耗电、
    延迟由显存决定,一个在网络另一头、延迟由链路决定。渲染上它们不该长一个样,
    而契约里此前没有任何一位能把它们分开。

两位是同一件事的两面
--------------------
"在哪儿想"决定"走哪条通路":本地档位没有视觉模型,但这一轮交给一家能看的云端时,
视觉是**可用**的。所以 :func:`resolve_pathway_view` 把回执里的 locus 交给
``core.modality_capability.negotiate(locus=...)``(那一层的第四维),而不是各算各的。

**这两位是描述,不是控制。** 它们回答"此刻看上去是什么样",不决定任何一条链路
真的怎么走 —— 语音与注意力循环仍按本地那份能力源走(理由见协商层模块头"谁该传
locus")。把它们当开关用,会让一次与音频毫不相干的角色路由改变麦克风的走法。

只读,绝不构造
-------------
与 ``core.phase_contract.last_perception_status`` 同一条纪律:用
``sys.modules.get`` 只看**已经被导入过**的模块。没导入过 = 这个进程里没有这套东西,
如实报 unwired,而不是为了填一格去 import 一串重模块 —— 在场桥是每 200ms 一拍的
热路径。

为什么要缓存
------------
``negotiate()`` 每次要读档位状态文件、跑几次 ``importlib.util.find_spec``。这些东西
以秒计都不会变,而在场桥以 5Hz 调它。这里按 (locus) 缓存 :data:`PATHWAY_TTL_S`
秒 —— 时间窗刻意做得比人眼分辨得出的变化还短,所以缓存永远不会让画面停在旧结论上。
"""

from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

#: 通路缓存的存活时间(秒)。见模块头"为什么要缓存"。
PATHWAY_TTL_S: float = 2.0

#: 契约里出现的模态通路名 —— 与 ``core.modality_capability`` 的四个模态一一对应。
#: 不从那边 import 常量:本模块要在那边**没被导入**时也能给出空态。一致性由
#: ``tests/test_render_pathway_contract.py`` 机器校验。
PATHWAY_MODALITIES: Tuple[str, ...] = ("vision_in", "audio_in", "audio_out", "video_in")

#: 每条通路的走法。与 ``ModalityResolution.mode`` 同域。
PATHWAY_MODES: Tuple[str, ...] = ("native", "bridge", "unavailable")

#: 通路被谁限制住。与 ``ModalityResolution.limited_by`` 同域,``""`` 表示没被限制。
PATHWAY_LIMITS: Tuple[str, ...] = ("", "model", "serving", "device", "provider")

#: 档位形态:单模型 / 双位分工。与 ``core.model_catalog`` 的 ``TierSpec.kind`` 同域,
#: ``unknown`` 是本模块独有的一档 —— 取不到档位表时不能假装知道。
TIER_KINDS: Tuple[str, ...] = ("unknown", "single", "composite")

#: 想这件事发生在哪一侧。与 ``core.thinking_locus.THINKING_LOCI`` 同域。
THINKING_LOCI: Tuple[str, ...] = ("unknown", "local", "cloud")

#: 路由的角色意图类别。与 ``core.thinking_locus.ROUTE_TYPES`` 同域。
ROUTE_TYPES: Tuple[str, ...] = ("unknown", "dispatch", "produce", "gatekeep")


@dataclass(frozen=True)
class PathwayLane:
    """一条模态通路此刻的走法。"""

    modality: str
    mode: str = "unavailable"
    limited_by: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"modality": self.modality, "mode": self.mode, "limited_by": self.limited_by}


@dataclass(frozen=True)
class ModalityPathwayView:
    """四条模态通路 + 这份结论是在什么前提下得出的。

    ``lanes`` **恒定四条**,不可用的以 ``unavailable`` 出现 —— 渲染端要能把"这一侧
    不亮"画出来,而不是遍历一个长度会变的数组(与 ``PerceptionView.modalities``
    同一条理由)。
    """

    #: 这份结论是照着谁算的:``"local"`` 或某家 provider 名。空 = 没协商过。
    locus: str = ""
    #: 本地档位的形态,决定"能不能一边听一边想"这类编排。
    tier_kind: str = "unknown"
    #: ``False`` = 这个进程里没有协商层,四条全是占位空态。
    is_wired: bool = False
    lanes: Tuple[PathwayLane, ...] = field(default_factory=tuple)

    @classmethod
    def unwired(cls) -> "ModalityPathwayView":
        """协商层不在这个进程里 —— 四条通路一概不可知,如实报出来。"""
        return cls(
            locus="",
            tier_kind="unknown",
            is_wired=False,
            lanes=tuple(PathwayLane(m) for m in PATHWAY_MODALITIES),
        )

    @property
    def native_count(self) -> int:
        return sum(1 for lane in self.lanes if lane.mode == "native")

    @property
    def bridged_count(self) -> int:
        return sum(1 for lane in self.lanes if lane.mode == "bridge")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "locus": self.locus,
            "tier_kind": self.tier_kind,
            "is_wired": self.is_wired,
            "lanes": [lane.to_dict() for lane in self.lanes],
            "native_count": self.native_count,
            "bridged_count": self.bridged_count,
        }


@dataclass(frozen=True)
class ThinkingLocusView:
    """这一轮的推理落在哪一侧。

    ``is_decided=False`` 说的是"本进程还没路由过任何角色",不是"落在本地"——
    把没发生过的事画成"本地在想",正是三态里最不该乱画的那一段。
    """

    is_decided: bool = False
    locus: str = "unknown"
    provider: str = ""
    model: str = ""
    role: str = ""
    route_type: str = "unknown"
    reason: str = ""
    #: 角色意图没被满足(派活落到云端 / 把关回落本地)。见 ``ThinkingLocusRecord``。
    is_fallback: bool = False
    #: 本地这一轮有没有开**投机解码的草稿位**。见 :mod:`core.speculative_draft`。
    #:
    #: 只在 ``locus == "local"`` 时有意义 —— 云端怎么解码不归这边管,也看不见。
    #: 它是 HUD 态势层唯一需要的那一位:"本地正在被加速"跟"本地在硬扛"画出来
    #: 该不一样,而这件事从 provider/model 上完全看不出来。
    draft_active: bool = False
    #: 这台机器上实测的倍数(``0`` = 没测过)。**小于 1 表示更慢** —— 那种情况
    #: ``draft_active`` 本来就是 False,但数字仍然带着,因为"测过、结论是别开"
    #: 与"没测过"在面板上该分得开。
    draft_speedup: float = 0.0

    @classmethod
    def undecided(cls) -> "ThinkingLocusView":
        return cls()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_decided": self.is_decided,
            "locus": self.locus,
            "provider": self.provider,
            "model": self.model,
            "role": self.role,
            "route_type": self.route_type,
            "reason": self.reason,
            "is_fallback": self.is_fallback,
            "draft_active": self.draft_active,
            "draft_speedup": round(float(self.draft_speedup), 3),
        }


# ── 只读取数:绝不构造、绝不导入 ─────────────────────────────────────────────

_REASON_MAX = 160


def last_thinking_record() -> Optional[Any]:
    """取路由回执;本进程没路由过(或回执模块没被导入过)返回 None。"""
    mod = sys.modules.get("core.thinking_locus")
    if mod is None:
        return None
    try:
        return mod.last()
    except Exception:  # noqa: BLE001 — 可见性绝不该拖垮广播
        return None


def _draft_readout(locus: str, model: str) -> Tuple[bool, float]:
    """本地这一轮开没开草稿位、实测多少倍。取不到一律 ``(False, 0.0)``。

    与本模块其余部分同一条纪律:``sys.modules.get`` 只看**已经导入过**的模块,
    绝不为了填这一位去 import 一串东西。而且它读的是一个 JSON 文件 ——
    在场桥是 5Hz,所以走 :data:`PATHWAY_TTL_S` 那套缓存,不是每帧去敲盘。

    云端归属直接返回零值:云端怎么解码这边既管不着也看不见,报一个"没开"会被
    读成"云端没被加速",那是无中生有。
    """
    if locus != "local" or not model:
        return False, 0.0
    mod = sys.modules.get("core.speculative_draft")
    if mod is None:
        return False, 0.0
    hit = _draft_cached(model)
    if hit is not None:
        return hit
    try:
        active = bool(mod.is_enabled(model))
        speedup = float(getattr(mod.load_measurement(model), "speedup", 0.0) or 0.0)
    except Exception:  # noqa: BLE001 — 可见性绝不该拖垮广播
        return False, 0.0
    _draft_store(model, (active, speedup))
    return active, speedup


def resolve_thinking_locus_view() -> ThinkingLocusView:
    """路由回执 → 契约视图。没有回执时是 :meth:`ThinkingLocusView.undecided`。"""
    rec = last_thinking_record()
    if rec is None:
        return ThinkingLocusView.undecided()
    locus = getattr(rec, "locus", "unknown")
    if locus not in THINKING_LOCI:
        locus = "unknown"
    route_type = getattr(rec, "route_type", "unknown")
    if route_type not in ROUTE_TYPES:
        route_type = "unknown"
    model = str(getattr(rec, "model", "") or "")
    draft_active, draft_speedup = _draft_readout(locus, model)
    return ThinkingLocusView(
        is_decided=locus in ("local", "cloud"),
        locus=locus,
        provider=str(getattr(rec, "provider", "") or ""),
        model=str(getattr(rec, "model", "") or ""),
        role=str(getattr(rec, "role", "") or ""),
        route_type=route_type,
        # 理由是后端原文，可能很长；截断而不是丢弃 —— 丢了就没法在面板上排障。
        reason=str(getattr(rec, "reason", "") or "")[:_REASON_MAX],
        is_fallback=bool(getattr(rec, "is_fallback", False)),
        draft_active=draft_active,
        draft_speedup=draft_speedup,
    )


def _tier_kind() -> str:
    """当前档位是单模型还是双位分工;取不到报 ``unknown``(不猜)。"""
    mod = sys.modules.get("core.model_catalog")
    if mod is None:
        return "unknown"
    try:
        spec = mod.get_tier(mod.load_tier())
        kind = str(getattr(spec, "kind", "") or "")
    except Exception:  # noqa: BLE001
        return "unknown"
    return kind if kind in TIER_KINDS else "unknown"


_cache_lock = threading.Lock()
_cache: Dict[str, Tuple[float, ModalityPathwayView]] = {}
#: 草稿位读数的缓存 —— 它读的是一个 JSON 文件,同样不能每帧敲盘。与通路缓存
#: 分开放而不是塞同一个字典:两者的键空间不同(一个是 locus、一个是型号 tag),
#: 混在一起会在某个型号恰好叫 "local" 的那天出事。
_draft_cache: Dict[str, Tuple[float, Tuple[bool, float]]] = {}


def _cached(key: str) -> Optional[ModalityPathwayView]:
    with _cache_lock:
        hit = _cache.get(key)
    if hit is None:
        return None
    at, view = hit
    return view if (time.monotonic() - at) < PATHWAY_TTL_S else None


def _store(key: str, view: ModalityPathwayView) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic(), view)


def _draft_cached(model: str) -> Optional[Tuple[bool, float]]:
    with _cache_lock:
        hit = _draft_cache.get(model)
    if hit is None:
        return None
    at, val = hit
    return val if (time.monotonic() - at) < PATHWAY_TTL_S else None


def _draft_store(model: str, val: Tuple[bool, float]) -> None:
    with _cache_lock:
        _draft_cache[model] = (time.monotonic(), val)


def reset_pathway_cache() -> None:
    """丢掉通路与草稿位缓存。给测试用 —— 不清的话上一条用例的结论会漏到下一条。"""
    with _cache_lock:
        _cache.clear()
        _draft_cache.clear()


def resolve_pathway_view(*, locus: Optional[str] = None) -> ModalityPathwayView:
    """协商当前通路;协商层不在这个进程里时是 :meth:`ModalityPathwayView.unwired`。

    Args:
        locus: 照着谁算。``None`` 时从路由回执里取(云端归属才有值,见
            ``core.thinking_locus.locus_provider``),取不到就按本地算。
    """
    mod = sys.modules.get("core.modality_capability")
    if mod is None:
        return ModalityPathwayView.unwired()

    if locus is None:
        tl = sys.modules.get("core.thinking_locus")
        if tl is not None:
            try:
                locus = tl.locus_provider()
            except Exception:  # noqa: BLE001
                locus = None

    key = str(locus or "local")
    hit = _cached(key)
    if hit is not None:
        return hit

    try:
        plan = mod.negotiate(locus=locus)
        lanes = []
        for name in PATHWAY_MODALITIES:
            res = plan.get(name)
            mode = str(getattr(res, "mode", "") or "")
            limited = str(getattr(res, "limited_by", "") or "")
            lanes.append(
                PathwayLane(
                    modality=name,
                    mode=mode if mode in PATHWAY_MODES else "unavailable",
                    limited_by=limited if limited in PATHWAY_LIMITS else "",
                )
            )
        view = ModalityPathwayView(
            locus=str(getattr(plan, "locus", "") or "local"),
            tier_kind=_tier_kind(),
            is_wired=True,
            lanes=tuple(lanes),
        )
    except Exception:  # noqa: BLE001 — 可见性绝不该拖垮广播
        return ModalityPathwayView.unwired()

    _store(key, view)
    return view


RENDER_PATHWAY_AUTHORITY: str = (
    "RENDER_PATHWAY_V1: core/render_pathway.py | 渲染契约的通路位与推理归属位. "
    "resolve_pathway_view() → ModalityPathwayView(恒四条 lane: mode+limited_by, "
    "带 locus/tier_kind/is_wired); resolve_thinking_locus_view() → ThinkingLocusView. "
    "两者只读: sys.modules.get 取 core.modality_capability / core.thinking_locus, "
    "绝不 import 也不构造. locus 由路由回执给出并转交 negotiate() 的第四维. "
    "通路结论按 locus 缓存 PATHWAY_TTL_S 秒(在场桥 5Hz, negotiate 要读档位文件)."
)

__all__ = [
    "PATHWAY_TTL_S",
    "PATHWAY_MODALITIES",
    "PATHWAY_MODES",
    "PATHWAY_LIMITS",
    "TIER_KINDS",
    "THINKING_LOCI",
    "ROUTE_TYPES",
    "PathwayLane",
    "ModalityPathwayView",
    "ThinkingLocusView",
    "last_thinking_record",
    "resolve_thinking_locus_view",
    "resolve_pathway_view",
    "reset_pathway_cache",
    "RENDER_PATHWAY_AUTHORITY",
]
