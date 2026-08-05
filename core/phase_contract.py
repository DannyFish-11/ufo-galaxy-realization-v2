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
from typing import Any, Dict, Optional, Tuple

__all__ = [
    # ── 忠实契约（新，渲染端应当消费这一套）──
    "RENDER_PHASES",
    "PHASE_TRANSITIONS",
    "FORBIDDEN_TRANSITIONS",
    "RUNTIME_DOMAINS",
    "FORM_SIGNATURES",
    "SPATIAL_PRESENCES",
    "RenderPosture",
    "resolve_render_posture",
    "render_contract_schema",
    "tri_state_of",
    # ── 一维遗留投影（旧，仅供既有覆盖层）──
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
            {
                "name": "retreat_tendency",
                "ts": "number",
                "doc": (
                    "推向 receding 的概率质量 [0,1]。注意：在本【遗留】投影里它被当作"
                    "「向上一档锚点漂移」，那是语义误读，见 RenderPosture 的同名字段"
                ),
            },
            {"name": "stability", "ts": "number", "doc": "时间稳定度 [0,1]，低值表示刚发生过振荡"},
            {"name": "source", "ts": "PhasePostureSource", "doc": "深度来自实算还是锚点兜底"},
        ],
    }


# ===========================================================================
# 忠实契约：按 continuum 实际形状长出来的渲染姿态
# ===========================================================================
#
# 上面那套（PhasePosture / PHASE_ANCHORS / PHASE_ORDER）是**一维遗留投影**：
# 三个锚点串在一条 depth 轴上。它的身世写在本模块开头——沿用
# ``lumiv_websocket_bridge.MODE_DEPTH_MAP`` 的既有取值，「只在锚点【之间】增加
# 连续性」。也就是说它是**给一个既有的三档硬编码动画补插值**，不是从 continuum
# 的形状推导出来的契约。既有覆盖层（electron/renderer/presence_motion.js）按它
# 调过参，所以原样保留、继续广播。
#
# 但它表达不了后端真正的模型，差三处，每一处都能被 continuum 的源码证实：
#
# 1. **相数**：内部生命周期是四相 formless → liminal → manifest → receding →
#    formless（``ContinuumPhase``）。``continuum_to_tri_state`` 把 receding 折叠成
#    silent，理由是「externally … functionally indistinguishable from a gradual
#    return to silent」。那对 API 消费者成立，**对渲染器恰恰相反**：
#    ``ExpressionEngine`` 对这两相给出的表达状态截然不同——
#        formless → form=none,             spatial=absent,     motion=0.0
#        receding → form=collapsing_field, spatial=peripheral, texture=soft_dissolve
#    折叠之后两者在渲染端变成同一个数，「做完了正在退场」与「压根没启动」不可分辨。
#    闭环的那段返回弧就是在这里丢掉的。
#
# 2. **维数**：公共模型是二维的——``TriStatePhase`` 说「在做什么」，
#    ``RuntimeDomain`` 说「在哪儿跑」（local / cross_device / transition）。
#    第二维在遗留投影里完全不存在。
#
# 3. **retreat_tendency 的语义**：``ContinuumState`` 的字段说明是
#    「Probability mass pushing toward retreat (manifest/liminal → **receding**)」
#    ——推向 receding 这个**相**。遗留投影把它当成「向上一档锚点漂移」，
#    于是 manifest 会朝 liminal 的锚点漂，而 ``manifest → liminal`` 在
#    docs/PHASE_TRANSITION_TABLE.md 里是**明令禁止**的
#    （"Structure cannot un-collapse without receding first"）。
#    也就是说遗留契约能表达状态机禁止的转移，却表达不了它要求的那个。
#
# 下面这套是**忠实契约**。刻意的取舍：
#
# * **不带 depth 标量**。位置不是一个数——形态由 ``ExpressionEngine`` 已经算好的
#   form/spatial/motion/intensity 描述，「离下一次转移有多近」由 collapse/retreat
#   倾向描述。再给一个 depth 只会诱使渲染端重新自己推导一遍。
# * **不发明任何字段**。每一项都能在 core/continuum/ 里找到出处；ExpressionState
#   是后端自己写明「Consumers (rendering layers, audio engines, haptics)」的那套
#   媒介无关渲染参数，本契约只是把它送出来。
# * **降级如实标注**，与遗留投影同一条纪律。


#: 渲染端看到的四相。**这是真相**，不是三态投影。
#: 与 ``core.continuum.types.ContinuumPhase`` 的取值一一对应。
RENDER_PHASES: Tuple[str, ...] = ("formless", "liminal", "manifest", "receding")

#: 相位之间**允许**的转移，抄自 docs/PHASE_TRANSITION_TABLE.md 的 Allowed 表。
#:
#: 渲染端据此可以预先知道「从当前相位只可能去哪」，于是能提前编排动作，而不是
#: 等相位跳变之后才反应。注意 manifest 的唯一出口是 receding —— 所以从 manifest
#: 出来的动作永远是「消散」，绝不是「退回 liminal」。
PHASE_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "formless": ("liminal",),
    "liminal": ("manifest", "formless"),
    "manifest": ("receding",),
    "receding": ("formless",),
}

#: 明令禁止的转移，抄自同一张表的 Forbidden 表。带上理由，渲染端不该为它们编排动作。
#:
#: 例外：``flags.allow_emergency_jump = True`` 时 formless → manifest 被允许
#: （紧急/中断场景）。契约把它留在禁止表里并注明，因为那是异常路径，不是常态编排。
FORBIDDEN_TRANSITIONS: Dict[Tuple[str, str], str] = {
    ("formless", "manifest"): "跳过了 liminal 闸门，没有结构成型过（allow_emergency_jump 时例外）",
    ("formless", "receding"): "receding 要求先有过在场",
    ("manifest", "liminal"): "结构不能不经 receding 就解体",
    ("receding", "manifest"): "必须先回到 formless 才能重新进入 manifest",
    ("receding", "liminal"): "必须先回到 formless 才能重新进入 liminal",
}

#: 第二维：执行发生在哪儿。``None`` 表示尚未判定（formless 早期）。
RUNTIME_DOMAINS: Tuple[str, ...] = ("local", "cross_device", "transition")

#: ``ExpressionState.form_signature`` 的取值域——后端给渲染端的**形态**提示。
FORM_SIGNATURES: Tuple[str, ...] = (
    "none",
    "diffuse_cluster",
    "focused_point",
    "expanding_ring",
    "collapsing_field",
)

#: ``ExpressionState.spatial_presence`` 的取值域——抽象空间权重／贴近度。
SPATIAL_PRESENCES: Tuple[str, ...] = ("absent", "peripheral", "ambient", "foreground")

#: 四相 → 三态的公共投影。与 ``continuum_to_tri_state`` 同表，在这里复刻一份是为了
#: **不必导入 core.continuum.types**（实测 ~690ms，而本模块在每次相位事件里都被调）。
_TRI_STATE_MAP: Dict[str, str] = {
    "formless": "silent",
    "liminal": "liminal",
    "manifest": "manifest",
    "receding": "silent",
}


def tri_state_of(phase: str) -> str:
    """四相 → 三态公共投影。未知相位按 ``silent`` 处理。

    渲染端**不应该**用它来决定画什么——那正是把 receding 抹平的那一步。
    它只是给「必须使用公共三态词汇」的消费者（状态板、API、文档）准备的。
    """
    return _TRI_STATE_MAP.get(phase, "silent")


@dataclasses.dataclass(frozen=True)
class RenderPosture:
    """渲染端的完整姿态：四相 × 第二维 × 后端已算好的表达参数。

    这是 ``ContinuumState`` 面向渲染的忠实投影。每个字段的出处都在
    core/continuum/ 里，本类不做任何新的推导——只做搬运和如实标注。
    """

    # ── 相位：四相是真相 ────────────────────────────────────────────────
    phase: str
    """四相之一（formless/liminal/manifest/receding）。**渲染端应当消费这个。**"""

    tri_state: str
    """三态公共投影。仅供必须用公共词汇的消费者；用它画图会丢掉返回弧。"""

    is_returning: bool
    """是否处在返回弧上（phase == receding）。

    单独提出来是因为它是渲染上最要紧的一个 bit：``formless`` 与 ``receding``
    的 tri_state 都是 ``silent``，只有这一位能把「刚做完，正在消散」跟
    「静息，什么都没发生」分开。
    """

    next_phases: Tuple[str, ...]
    """从当前相位【合法】能去的下一相，见 :data:`PHASE_TRANSITIONS`。

    渲染端可以据此提前编排：处在 manifest 时唯一出口是 receding，那么退场动作
    就该按「消散」准备，而不是按「退回上一档」。
    """

    # ── 第二维：在哪儿跑 ────────────────────────────────────────────────
    runtime_domain: Optional[str]
    """local / cross_device / transition；``None`` = 尚未判定。"""

    # ── 表达参数：后端 ExpressionEngine 已经算好的，直接用 ──────────────
    motion: float
    """抽象运动能量 [0,1]（0=静止，1=full kinetic）。"""

    intensity: float
    """整体在场强度 [0,1]。"""

    form_signature: str
    """形态提示，见 :data:`FORM_SIGNATURES`。receding 对应 ``collapsing_field``。"""

    spatial_presence: str
    """空间权重／贴近度，见 :data:`SPATIAL_PRESENCES`。"""

    texture_hint: str
    """自由文本质感描述（``soft_granular`` / ``crisp_edge`` / ``soft_dissolve``）。空串=无提示。"""

    # ── 连续量：描述「离下一次转移有多近」──────────────────────────────
    presence_intensity: float
    """EMA 平滑的在场强度 [0,1]。"""

    coherence: float
    """信号成意图的程度 [0,1]。"""

    ambiguity: float
    """coherence 的反面 [0,1]，意图未定时高。"""

    collapse_tendency: float
    """推向**塌缩**（liminal → manifest）的概率质量 [0,1]。"""

    retreat_tendency: float
    """推向 **receding** 的概率质量 [0,1]。

    注意这**不是**「退回上一档」——``ContinuumState`` 的原文是
    "pushing toward retreat (manifest/liminal → receding)"。遗留投影
    :class:`PhasePosture` 把它当成向上一档锚点漂移，那是语义误读，且会表达出
    ``manifest → liminal`` 这个被转移表禁止的动作。
    """

    stability: float
    """时间稳定度 [0,1]，低值表示最近发生过相位振荡（渲染端可据此加大阻尼）。"""

    # ── 如实标注 ────────────────────────────────────────────────────────
    source: str
    """姿态是实算的还是兜底的，见 :class:`PostureSource`。"""

    degraded: bool
    """continuum 本拍是否跑在降级模式。"""

    degrade_reason: Optional[str]
    """仅在 ``degraded=True`` 时有值。"""

    def to_dict(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["next_phases"] = list(self.next_phases)
        for k in (
            "motion",
            "intensity",
            "presence_intensity",
            "coherence",
            "ambiguity",
            "collapse_tendency",
            "retreat_tendency",
            "stability",
        ):
            d[k] = round(float(d[k]), 4)
        return d


def _anchor_only_render_posture(phase: str = "formless") -> RenderPosture:
    """拿不到 ContinuumState 时的兜底姿态——如实标注，不假装是算出来的。"""
    token = phase if phase in RENDER_PHASES else "formless"
    return RenderPosture(
        phase=token,
        tri_state=tri_state_of(token),
        is_returning=token == "receding",
        next_phases=PHASE_TRANSITIONS.get(token, ()),
        runtime_domain=None,
        motion=0.0,
        intensity=0.0,
        form_signature="none",
        spatial_presence="absent",
        texture_hint="",
        presence_intensity=0.0,
        coherence=0.0,
        ambiguity=1.0,
        collapse_tendency=0.0,
        retreat_tendency=0.0,
        stability=1.0,
        source=PostureSource.ANCHOR_ONLY,
        degraded=False,
        degrade_reason=None,
    )


def resolve_render_posture(state: Optional[Any] = None) -> RenderPosture:
    """把一拍 ``ContinuumState`` 投影成渲染姿态。

    Args:
        state: ``ContinuumState``；省略时取 :func:`last_continuum_posture`。
               拿不到（进程里还没有 continuum）时返回 anchor_only 兜底。

    与 :func:`resolve_phase_posture` 的关键差别：**不接受外部传入的相位 token**。
    相位从 ``state.phase`` 读——那是四相真值。遗留函数拿桥的三值字符串当权威，
    于是即便它手里的 ``state`` 对象带着 ``receding``，也会被外面那个 ``static``
    覆盖掉。真相就在手里却用了投影，返回弧就是这么丢的。

    表达参数取 ``state.expression``。若它的 ``phase_signature`` 与 ``state.phase``
    对不上（说明这份 expression 是默认值或上一拍的残留），就用 ``ExpressionEngine``
    按当前 state 重算一份。这不违反本模块「绝不构造」的纪律——那条纪律针对的是
    ``core.openclawd``（很重、有副作用）；``ExpressionEngine`` 是**无状态纯函数**，
    对同一个 state 重算得到的结果与流水线里那一份逐位相同。
    """
    if state is None:
        state = last_continuum_posture()
    if state is None:
        return _anchor_only_render_posture()

    raw_phase = getattr(getattr(state, "phase", None), "value", None) or str(getattr(state, "phase", "formless"))
    phase = raw_phase if raw_phase in RENDER_PHASES else "formless"

    def _f(name: str, default: float = 0.0) -> float:
        try:
            return _clamp(float(getattr(state, name, default) or 0.0), 0.0, 1.0)
        except (TypeError, ValueError):
            return default

    expr = getattr(state, "expression", None)
    expr_phase = getattr(getattr(expr, "phase_signature", None), "value", None)
    if expr is None or expr_phase != phase:
        try:
            from core.continuum.expression_engine import ExpressionEngine

            expr = ExpressionEngine().compute(state)
        except Exception:  # noqa: BLE001 — 表达参数拿不到不该拖垮整条广播
            expr = None

    def _enum_str(obj: Any, attr: str, allowed: Tuple[str, ...], fallback: str) -> str:
        v = getattr(getattr(obj, attr, None), "value", None) if obj is not None else None
        return v if v in allowed else fallback

    domain = getattr(getattr(state, "runtime_domain", None), "value", None)

    return RenderPosture(
        phase=phase,
        tri_state=tri_state_of(phase),
        is_returning=phase == "receding",
        next_phases=PHASE_TRANSITIONS.get(phase, ()),
        runtime_domain=domain if domain in RUNTIME_DOMAINS else None,
        motion=_clamp(float(getattr(expr, "motion", 0.0) or 0.0), 0.0, 1.0) if expr is not None else 0.0,
        intensity=_clamp(float(getattr(expr, "intensity", 0.0) or 0.0), 0.0, 1.0) if expr is not None else 0.0,
        form_signature=_enum_str(expr, "form_signature", FORM_SIGNATURES, "none"),
        spatial_presence=_enum_str(expr, "spatial_presence", SPATIAL_PRESENCES, "absent"),
        texture_hint=str(getattr(expr, "texture_hint", "") or "") if expr is not None else "",
        presence_intensity=_f("presence_intensity"),
        coherence=_f("coherence"),
        ambiguity=_f("ambiguity", 1.0),
        collapse_tendency=_f("collapse_tendency"),
        retreat_tendency=_f("retreat_tendency"),
        stability=_f("stability", 1.0),
        source=PostureSource.CONTINUUM,
        degraded=bool(getattr(state, "degraded", False)),
        degrade_reason=getattr(state, "degrade_reason", None),
    )


def render_contract_schema() -> Dict[str, Any]:
    """机器可读的忠实契约描述 —— ``scripts/gen_ts_types.py`` 据此生成 TS 类型。"""
    return {
        "phases": list(RENDER_PHASES),
        "transitions": {k: list(v) for k, v in PHASE_TRANSITIONS.items()},
        "forbidden": [{"from": a, "to": b, "why": why} for (a, b), why in FORBIDDEN_TRANSITIONS.items()],
        "tri_state_map": dict(_TRI_STATE_MAP),
        "runtime_domains": list(RUNTIME_DOMAINS),
        "form_signatures": list(FORM_SIGNATURES),
        "spatial_presences": list(SPATIAL_PRESENCES),
        "sources": [PostureSource.CONTINUUM, PostureSource.ANCHOR_ONLY],
        "fields": [
            {"name": "phase", "ts": "RenderPhase", "doc": "四相之一 —— 渲染端应当消费这个"},
            {"name": "tri_state", "ts": "WirePhaseTri", "doc": "三态公共投影；用它画图会丢掉返回弧"},
            {
                "name": "is_returning",
                "ts": "boolean",
                "doc": "是否在返回弧上（receding）——把「刚做完」与「静息」分开的那一位",
            },
            {"name": "next_phases", "ts": "RenderPhase[]", "doc": "从当前相位合法能去的下一相"},
            {"name": "runtime_domain", "ts": "RuntimeDomain | null", "doc": "第二维：在哪儿跑；null=尚未判定"},
            {"name": "motion", "ts": "number", "doc": "抽象运动能量 [0,1]"},
            {"name": "intensity", "ts": "number", "doc": "整体在场强度 [0,1]"},
            {"name": "form_signature", "ts": "FormSignature", "doc": "形态提示；receding 对应 collapsing_field"},
            {"name": "spatial_presence", "ts": "SpatialPresence", "doc": "空间权重／贴近度"},
            {"name": "texture_hint", "ts": "string", "doc": "质感描述（soft_dissolve 等）；空串=无提示"},
            {"name": "presence_intensity", "ts": "number", "doc": "EMA 平滑的在场强度 [0,1]"},
            {"name": "coherence", "ts": "number", "doc": "信号成意图的程度 [0,1]"},
            {"name": "ambiguity", "ts": "number", "doc": "coherence 的反面 [0,1]"},
            {"name": "collapse_tendency", "ts": "number", "doc": "推向塌缩（liminal→manifest）的概率质量 [0,1]"},
            {"name": "retreat_tendency", "ts": "number", "doc": "推向 receding 的概率质量 [0,1]（不是退回上一档）"},
            {"name": "stability", "ts": "number", "doc": "时间稳定度 [0,1]，低值表示刚振荡过"},
            {"name": "source", "ts": "PhasePostureSource", "doc": "实算还是兜底"},
            {"name": "degraded", "ts": "boolean", "doc": "continuum 本拍是否降级"},
            {"name": "degrade_reason", "ts": "string | null", "doc": "仅 degraded=true 时有值"},
        ],
    }
