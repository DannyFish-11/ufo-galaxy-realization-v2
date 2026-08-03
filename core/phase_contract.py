"""core.phase_contract — 面板侧相位契约的唯一事实源（SSOT）

要解决什么
----------
后端**早就在算**一整套连续量。``core/continuum/types.py`` 的 ``ContinuumState``
每拍产出：

    presence_intensity   EMA 平滑的在场强度
    coherence/ambiguity  信号成意图的程度 / 其反面
    collapse_tendency    "推向相位塌缩的概率质量 (liminal → manifest)"
    retreat_tendency     推向回撤的概率质量
    stability            时间稳定度，低值表示最近发生过相位振荡

而 ``ContinuumPhase`` 内部是**四档**（formless / liminal / manifest / receding）。
实测它是活的：连跑四拍 presence_intensity 为 0.0375 → 0.0656 → 0.0867 → 0.1025，
``degraded=False``。

但这一整套到了面板边界全部消失。``core/lumiv_websocket_bridge.py`` 订阅三个
离散事件 ``phase.silent/liminal/manifest``，每次把渲染深度设成查表得到的
**三个硬编码常数**：

    MODE_DEPTH_MAP = {"static": 0.05, "liminal": 0.62, "manifest": 0.92}

于是面板收到的 ``depth_factor`` 不是算出来的，是三选一。"三态边缘模糊"这件事
所需的模型一直都在，只是在最后一步被丢掉了。

本模块做的事
------------
1. 提供**只读**的取数口 :func:`last_continuum_posture`，拿最近一拍 ContinuumState；
2. 把"相位 + 连续量"合成面板真正需要的 :class:`PhasePosture`；
3. 作为 ``scripts/gen_ts_types.py`` 的输入，让前端类型从这里生成，而不是各写一份。

刻意的边界
----------
* **绝不构造任何东西**。取数口只看进程里**已经存在**的实例：OpenClawd 还没被
  import、还没建实例、还没跑过 continuum —— 三种情况都直接返回 None。
  （``core.openclawd.get_openclawd()`` 会**创建** OpenClawd，在在场桥的每一拍
  里调它是错的。）
* **相位仍然是权威**。连续量只在相位自己的带内漂移，最多漂到与邻带的中点，
  绝不越过邻带的锚点。否则会出现"面板说 liminal、深度却已是 manifest 的值"
  这种自相矛盾的帧。
* **拿不到连续量时如实降级**，并在 ``source`` 字段里说明是哪一种，而不是
  假装深度是算出来的。面板可以据此决定要不要显示"精确态/估计态"。
"""

from __future__ import annotations

import dataclasses
import sys
from typing import Any, Dict, Optional

__all__ = [
    "PHASE_ANCHORS",
    "PHASE_ORDER",
    "EDGE_BLEND",
    "PhasePosture",
    "PostureSource",
    "last_continuum_posture",
    "resolve_phase_posture",
    "phase_contract_schema",
]


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

#: 三态在渲染深度轴上的锚点。沿用 lumiv_websocket_bridge.MODE_DEPTH_MAP 的既有取值
#: —— 前端的过渡编排（灵动岛淡出线 0.65 等）是按这几个数调出来的，改锚点会连带
#: 改动外壳观感，那是另一件事。本模块只在锚点【之间】增加连续性。
PHASE_ANCHORS: Dict[str, float] = {
    "static": 0.05,
    "liminal": 0.62,
    "manifest": 0.92,
}

#: 相位在深度轴上的先后顺序。用于确定某个相位的"上一档/下一档"是谁。
PHASE_ORDER = ("static", "liminal", "manifest")

#: 边缘混合上限。塌缩/回撤倾向为 1.0 时，深度最多向邻档锚点漂移两档间距的这个比例。
#:
#: 取 0.5 会正好漂到两个锚点的中点 —— 那已经是"相位归属存疑"的极限；再大就会
#: 越过中线，出现"相位说 A、深度更像 B"的自相矛盾帧。留一点余量取 0.45。
EDGE_BLEND: float = 0.45


class PostureSource:
    """``PhasePosture.source`` 的取值。字符串常量而非 Enum：它要跨 JSON 边界到前端。"""

    CONTINUUM = "continuum"
    """连续量来自活的 ContinuumState —— 深度是算出来的。"""

    ANCHOR_ONLY = "anchor_only"
    """拿不到 ContinuumState，深度退回三档锚点 —— 与改造前行为一致，但如实标注。"""


# ---------------------------------------------------------------------------
# 契约对象
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PhasePosture:
    """面板侧的相位姿态：离散相位 + 它在带内的连续位置。

    这是**面板真正需要**的东西。只给相位，面板就只能在三个状态之间硬切；
    带上连续量，它才能表达"正在从阈限滑向显现"这种中间态。
    """

    phase: str
    """三态之一：static / liminal / manifest。仍然是权威。"""

    depth: float
    """渲染深度 [0,1]。有连续量时在相位带内漂移，否则等于锚点。"""

    presence_intensity: float
    """EMA 平滑的在场强度。无连续量时为 0.0。"""

    coherence: float
    """信号成意图的程度。无连续量时为 0.0。"""

    collapse_tendency: float
    """推向下一档（liminal → manifest）的概率质量。这就是"边缘"本身。"""

    retreat_tendency: float
    """推向上一档回撤的概率质量。"""

    stability: float
    """时间稳定度。低值表示最近发生过相位振荡，前端可据此加大阻尼。"""

    source: str
    """深度是怎么来的，见 :class:`PostureSource`。前端可据此区分精确态/估计态。"""

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        # 深度与倾向都是给渲染用的，保留 4 位足够，避免 JSON 里出现长浮点噪声。
        for k in ("depth", "presence_intensity", "coherence", "collapse_tendency", "retreat_tendency", "stability"):
            d[k] = round(float(d[k]), 4)
        return d


# ---------------------------------------------------------------------------
# 取数（只读，绝不构造）
# ---------------------------------------------------------------------------


def last_continuum_posture() -> Optional[Any]:
    """取最近一拍 :class:`~core.continuum.types.ContinuumState`，拿不到返回 None。

    **绝不构造任何东西**：只读进程里已经存在的实例。三种情况直接返回 None：

    * ``core.openclawd`` 还没被 import（例如只跑了在场桥的进程）；
    * OpenClawd 单例还没建；
    * 还没跑过一次 continuum（``_continuum_orchestrator`` 或 ``_last_state`` 为 None）。

    刻意用 ``sys.modules.get`` 而不是 ``import core.openclawd``：后者会真的执行
    模块导入（这个模块很重），而本函数可能在每一次相位事件里被调到。
    """
    mod = sys.modules.get("core.openclawd")
    if mod is None:
        return None
    inst = getattr(mod, "_openclawd_instance", None)
    if inst is None:
        return None
    orch = getattr(inst, "_continuum_orchestrator", None)
    if orch is None:
        return None
    return getattr(orch, "_last_state", None)


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def _neighbour_anchors(phase: str) -> tuple:
    """返回 (下一档锚点, 上一档锚点)；没有邻档时为 None。"""
    try:
        i = PHASE_ORDER.index(phase)
    except ValueError:
        return (None, None)
    nxt = PHASE_ANCHORS[PHASE_ORDER[i + 1]] if i + 1 < len(PHASE_ORDER) else None
    prv = PHASE_ANCHORS[PHASE_ORDER[i - 1]] if i - 1 >= 0 else None
    return (nxt, prv)


def resolve_phase_posture(phase: str, state: Optional[Any] = None) -> PhasePosture:
    """把相位 token 与（可选的）ContinuumState 合成一份面板姿态。

    Args:
        phase: 三态 token。传入未知值时按 ``static`` 处理并如实标注 anchor_only
               —— 未知相位没有可信的连续位置。
        state: ContinuumState；省略时自动取 :func:`last_continuum_posture`。
               显式传入用于测试与离线合成。

    深度的算法
    ----------
    以本相位的锚点为基准，按塌缩/回撤倾向向邻档**漂移**，漂移量上限为
    两档间距的 :data:`EDGE_BLEND`：

        depth = anchor
              + (next_anchor - anchor) * collapse_tendency * EDGE_BLEND
              + (prev_anchor - anchor) * retreat_tendency  * EDGE_BLEND

    两个倾向可以同时非零（信号矛盾时），此时两个漂移相互抵消 —— 这正是想要的：
    拿不准的时候待在原地。
    """
    known = phase in PHASE_ANCHORS
    token = phase if known else "static"
    anchor = PHASE_ANCHORS[token]

    if state is None:
        state = last_continuum_posture()
    # 未知相位一律走兜底：塌缩/回撤倾向是**相对于本相位的邻档**定义的，
    # 相位都认不出来时，把它们套到 static 带上算出的深度没有意义 ——
    # 那会给出一个看着精确、实则无依据的数。
    if state is None or not known:
        return PhasePosture(
            phase=token,
            depth=anchor,
            presence_intensity=0.0,
            coherence=0.0,
            collapse_tendency=0.0,
            retreat_tendency=0.0,
            stability=1.0,
            source=PostureSource.ANCHOR_ONLY,
        )

    def _f(name: str, default: float = 0.0) -> float:
        try:
            return float(getattr(state, name, default) or 0.0)
        except (TypeError, ValueError):
            return default

    collapse = _clamp(_f("collapse_tendency"), 0.0, 1.0)
    retreat = _clamp(_f("retreat_tendency"), 0.0, 1.0)
    nxt, prv = _neighbour_anchors(token)

    depth = anchor
    if nxt is not None:
        depth += (nxt - anchor) * collapse * EDGE_BLEND
    if prv is not None:
        depth += (prv - anchor) * retreat * EDGE_BLEND

    return PhasePosture(
        phase=token,
        depth=_clamp(depth, 0.0, 1.0),
        presence_intensity=_clamp(_f("presence_intensity"), 0.0, 1.0),
        coherence=_clamp(_f("coherence"), 0.0, 1.0),
        collapse_tendency=collapse,
        retreat_tendency=retreat,
        stability=_clamp(_f("stability", 1.0), 0.0, 1.0),
        source=PostureSource.CONTINUUM,
    )


# ---------------------------------------------------------------------------
# 供 gen_ts_types 使用的 schema 描述
# ---------------------------------------------------------------------------


def phase_contract_schema() -> Dict[str, Any]:
    """机器可读的契约描述 —— ``scripts/gen_ts_types.py`` 据此生成 TS 类型。

    刻意不用 pydantic 的 ``model_json_schema()``：本契约是 dataclass，且生成器
    需要的信息（哪些字段是 [0,1] 归一量、source 的取值域）比 JSON Schema 更具体。
    """
    return {
        "phases": list(PHASE_ORDER),
        "anchors": dict(PHASE_ANCHORS),
        "edge_blend": EDGE_BLEND,
        "sources": [PostureSource.CONTINUUM, PostureSource.ANCHOR_ONLY],
        "fields": [
            {
                "name": "phase",
                "ts": "WirePhase",
                "doc": "后端线上传输的三态 token（static/liminal/manifest），仍然是权威",
            },
            {"name": "depth", "ts": "number", "doc": "渲染深度 [0,1]，在相位带内漂移"},
            {"name": "presence_intensity", "ts": "number", "doc": "EMA 平滑的在场强度 [0,1]"},
            {"name": "coherence", "ts": "number", "doc": "信号成意图的程度 [0,1]"},
            {"name": "collapse_tendency", "ts": "number", "doc": "推向下一档的概率质量 [0,1]"},
            {"name": "retreat_tendency", "ts": "number", "doc": "推向上一档回撤的概率质量 [0,1]"},
            {"name": "stability", "ts": "number", "doc": "时间稳定度 [0,1]，低值表示刚发生过振荡"},
            {"name": "source", "ts": "PhasePostureSource", "doc": "深度来自实算还是锚点兜底"},
        ],
    }
