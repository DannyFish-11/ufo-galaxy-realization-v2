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
    "SimulationSummary",
    "ExecutionChainView",
    "HybridExecutionView",
    "WorldModelView",
    "CHAIN_KINDS",
    "HYBRID_EXECUTION_MODES",
    "WORLD_MODEL_SOURCES",
    "TRANSITION_KINDS",
    "TRANSITION_KIND_OF",
    "transition_kind_of",
    "LIFECYCLE_STATES",
    "LIMINAL_ACTIVITIES",
    "SIMULATION_KINDS",
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


#: **主轴**：主体生命周期，取自 ``core.desktop_presence_runtime.TriState``。
#:
#: 这是渲染端的**首要依据**，因为它就是用户能直接感知的那条节奏：
#:
#:     silent   —— 主体休息；宿主原生多模态摄入仍在后台跑，无活跃认知请求
#:     liminal  —— 主体过渡中；OpenClawd 的认知与执行分支正在这一相里进行
#:     manifest —— 主体对外表达：出字、控设备、或展开跨设备回路
#:
#: 与下面的 :data:`RENDER_PHASES` 是**两根不同的轴**，``TriState`` 的类文档明确
#: 禁止混淆（"not a UI state and not the internal continuum posture"）。桥广播的
#: ``payload.phase`` 一直是这一根。
LIFECYCLE_STATES: Tuple[str, ...] = ("silent", "liminal", "manifest")

#: **副轴**：内部连续体姿态，取自 ``core.continuum.types.ContinuumPhase``。
#:
#: 它比主轴多一相 ``receding``（返回弧），提供主轴给不出的内部纹理：主轴回到
#: ``silent`` 时，副轴能区分「刚做完正在消散」与「静息，什么都没发生过」。
RENDER_PHASES: Tuple[str, ...] = ("formless", "liminal", "manifest", "receding")

#: 阈限态里**正在发生什么**。主轴说「在过渡」，这一项说「过渡里在干嘛」。
#:
#: 这是一条**有顺序的递进链**，不是一组平行标签——渲染端可以据此编排一段连续的
#: 「正在成形」动画，而不是四个互不相干的状态图标::
#:
#:     none          —— 不在阈限态
#:     understanding —— 刚进阈限，正在理解这句话要什么
#:     thinking      —— 已理解，正在规划怎么做
#:     rehearsing    —— 正在 core.liminal_rehearsal 的影子沙盘里推演候选路径
#:
#: 典型轨迹：``understanding → thinking → rehearsing → thinking →`` 进 manifest。
#: 推演不触发时就是 ``understanding → thinking →`` 进 manifest，**同样不空**。
#:
#: ``understanding`` 为什么必须存在
#: --------------------------------
#: 阈限态在面板上一直「什么都没有」，根因不是动画简陋，是**它的内容从没送出来过**。
#: 但只补 ``rehearsing`` 只解决了一半：``should_rehearse()`` 要求**有工具可调**且
#: **复杂度 ≥ 0.55**，于是纯对话和简单请求永远不推演，此前那两类请求的阈限态全程
#: 是 ``none``——面板照样空白。``understanding`` 由 ``advance(LIMINAL)`` 本身驱动
#: （见 ``RuntimeSession.advance``），**不经任何闸门**，所以「进了阈限就一定有内容」
#: 是结构保证，不是某条分支恰好登记了。
LIMINAL_ACTIVITIES: Tuple[str, ...] = ("none", "understanding", "thinking", "rehearsing")

#: ``SimulationSummary.simulation_kind`` 的取值域，与
#: ``core.liminal_space_mapping.build_simulation_summary`` 的 ``valid_kinds`` 同源。
SIMULATION_KINDS: Tuple[str, ...] = ("none", "speculative", "sandbox")

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

#: 执行链的种类。阈限空间装三类内容，其中两类是执行链，见 :class:`ExecutionChainView`。
CHAIN_KINDS: Tuple[str, ...] = ("local", "cross_device")

#: ``HybridExecutionView.mode`` 的取值域，与 ``core.hybrid_execution_policy.HybridExecutionMode``
#: 同源，外加一个 ``none`` 表示尚未决策。
#:
#: 不 import 那个模块来拼这份列表：实测导入它 ~72ms，而本模块被每一次相位事件调用
#: （自身导入 ~6ms）。``tests/test_render_chain_contract.py`` 里有一条把两边逐字对齐，
#: 那边可以慢慢 import。
HYBRID_EXECUTION_MODES: Tuple[str, ...] = (
    "none",
    "sequential_degrade",
    "parallel_race",
    "staged_hybrid",
    "local_preferred",
    "remote_preferred",
)

#: ``WorldModelView.source`` 的取值域。见该类的文档说明为什么要显式区分这两者。
WORLD_MODEL_SOURCES: Tuple[str, ...] = ("unwired", "live")

#: 主轴上最近一次转移的**性质**。渲染端据此选退场／进场的编排，而不是从深度差里猜。
#:
#: 为什么要有这一项
#: ----------------
#: 覆盖层此前唯一能依据的是一个标量深度。深度从 0.92 走回 0.05 时，画面上放的就是
#: 进场动画倒着播 —— 因为「正在返回」这件事根本没有独立的表示。这份取值域把它变成
#: 一个显式的事实，退场于是可以有自己的语汇。
#:
#: ``handoff`` 与 ``dissolving`` 都是**合法**出口
#: ----------------------------------------------
#: 后端有两套三态描述，一度看起来在打架：
#:
#: * continuum 副轴（四相）的 :data:`FORBIDDEN_TRANSITIONS` 说 ``manifest → liminal``
#:   禁止 —— 那说的是**内部连续体的相位图**，结构不能不经 receding 就解体。
#: * 在场层 ``core/desktop_presence_system.py`` 的转移策略里有一条
#:   ``MANIFEST → LIMINAL``，触发条件是 ``execution_completed_or_result_committed``
#:   —— 那说的是**主体生命周期**：这一轮结果已提交，还有后续。
#:
#: 两者是**不同的轴**上的两件事，不是同一件事的两种说法。所以这里不去选一台状态机，
#: 而是照实带上刚才发生的是哪一种转移，让渲染端按实际情况编排：做完就散（dissolving）
#: 与做完接着下一轮（handoff）本就该长得不一样。
TRANSITION_KINDS: Tuple[str, ...] = (
    "none",
    "emerging",
    "committing",
    "handoff",
    "dissolving",
)

#: (上一档主轴, 当前主轴) → 转移性质。缺失的组合按 ``none`` 处理。
TRANSITION_KIND_OF: Dict[Tuple[str, str], str] = {
    ("silent", "liminal"): "emerging",
    ("silent", "manifest"): "committing",
    ("liminal", "manifest"): "committing",
    ("manifest", "liminal"): "handoff",
    ("manifest", "silent"): "dissolving",
    ("liminal", "silent"): "dissolving",
}


def transition_kind_of(previous: Optional[str], current: str) -> str:
    """(上一档, 当前档) → 转移性质。

    Args:
        previous: 上一档主轴。``None``（本进程还没发生过转移）或与 ``current``
            相同（同档内的重复广播）时返回 ``none``。
        current: 当前主轴。

    ``silent → manifest`` 归入 ``committing`` 而不是单开一档：它只在
    ``allow_emergency_jump`` 的紧急路径上出现，渲染上仍然是「落手」，
    只是没有过渡段可编排。
    """
    if not previous or previous == current:
        return "none"
    return TRANSITION_KIND_OF.get((previous, current), "none")


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
class SimulationSummary:
    """阈限态沙盘推演的可渲染摘要。

    形状与 ``core.liminal_space_mapping.build_simulation_summary`` 一致——那是既有
    的投影层定义，本类刻意不另造一套，只是把它搬到渲染契约里，好让它能跨 JSON
    边界到前端（原类型在 core 里，前端拿不到）。

    那个投影层此前"零生产调用方"（一度因此被误删、随 #1587 撤回）。本契约是它第一个
    真正接到线上的消费面。
    """

    is_active: bool
    """当前是否有推演在跑。"""

    simulation_kind: str
    """none / speculative / sandbox，见 :data:`SIMULATION_KINDS`。"""

    candidate_paths: Tuple[str, ...]
    """正在评估的候选执行路径标签。这就是「阈限态在权衡什么」的可视内容。"""

    committed_path: Optional[str]
    """已提交的那条；仍在推演/全部失败时为 ``None``。"""

    is_committed: bool
    """``committed_path is not None``。单独给一位，省得前端各自判空。"""

    step_count: int
    """已完成的推演步数。"""

    scenario_label: Optional[str]
    """场景的人类可读标签（通常是用户那句话的前缀）。"""

    @staticmethod
    def inactive() -> "SimulationSummary":
        """没有推演在跑时的空摘要。"""
        return SimulationSummary(
            is_active=False,
            simulation_kind="none",
            candidate_paths=(),
            committed_path=None,
            is_committed=False,
            step_count=0,
            scenario_label=None,
        )


@dataclasses.dataclass(frozen=True)
class ExecutionChainView:
    """阈限空间三类内容里的**执行链**那两类，收成同一个渲染面形状。

    ``core/liminal_space_mapping.py`` 开篇把阈限空间定义为「运行时的空间执行场」，
    恰好装三类内容：本机执行链、跨设备执行链、沙盘推演。第三类早就上了线
    （:class:`SimulationSummary`），前两类此前只到 ``continuum.state`` 事件为止 ——
    ``RuntimeSession._build_chain_views()`` 每 200ms 都在产，而在场桥的
    ``_on_continuum_state`` 只取 ``liminal_activity`` / ``simulation`` 两项，
    这两条链就在那一步被丢掉了。本类是它们的上线形状。

    为什么两条链共用一个形状
    ------------------------
    源侧是两个类（``LocalChainView`` / ``CrossDeviceChainView``），字段逐一对应，
    唯一的差别是「最近这次的对象是谁」：本机是 ``last_task_id``，跨设备是
    ``last_device_id``。渲染端画的是同一件事——一条链走到第几步——所以这里收成
    :attr:`last_target` 加一个 :attr:`kind` 说明它指的是什么。

    ``tests/test_render_chain_contract.py`` 把这个映射逐字段钉住：源侧任何一个
    字段改名，都会在那里红，而不是在这里静默变成零。
    """

    kind: str
    """local / cross_device，见 :data:`CHAIN_KINDS`。决定 :attr:`last_target` 的含义。"""

    is_active: bool
    """这条链是否跑过至少一次。**零态是有意义的信号**（「还没跑过」），不是「没有这条链」。"""

    total_executions: int
    """本会话内这条链上的总执行次数。"""

    canonical_executions: int
    """其中走完整规范链的次数。"""

    legacy_executions: int
    """其中走遗留／非规范路径的次数。渲染端可据此提示「这次绕开了主链」。"""

    chain_order: Tuple[str, ...]
    """规范链的步骤名，按顺序。这就是「空间里该画几段」的依据。"""

    last_step: Optional[str]
    """最近一次到达的步骤名；没跑过时 ``None``。"""

    last_target: Optional[str]
    """最近一次的对象：``kind == "local"`` 时是 task_id，``cross_device`` 时是 device_id。"""

    @staticmethod
    def empty(kind: str) -> "ExecutionChainView":
        """零态视图 —— 「这条链存在但还没动」。

        刻意不返回 ``None``：下游必须能把「还没跑过」与「拿不到这条链」分开，
        前者是常态、后者是故障。
        """
        return ExecutionChainView(
            kind=kind if kind in CHAIN_KINDS else "local",
            is_active=False,
            total_executions=0,
            canonical_executions=0,
            legacy_executions=0,
            chain_order=(),
            last_step=None,
            last_target=None,
        )

    @staticmethod
    def from_view_dict(kind: str, raw: Optional[Dict[str, Any]]) -> "ExecutionChainView":
        """从 ``LocalChainView.to_dict()`` / ``CrossDeviceChainView.to_dict()`` 收形。

        ``raw`` 为空（该拍没带这条链）时返回 :meth:`empty` —— 见上面为什么不给 ``None``。
        """
        k = kind if kind in CHAIN_KINDS else "local"
        if not isinstance(raw, dict) or not raw:
            return ExecutionChainView.empty(k)

        def _int(name: str) -> int:
            try:
                return int(raw.get(name, 0) or 0)
            except (TypeError, ValueError):
                return 0

        # 源侧字段名按链种类分叉，这是两个源类唯一的形状差异。
        target_field = "last_task_id" if k == "local" else "last_device_id"
        target = raw.get(target_field)
        order = raw.get("canonical_chain_order") or []
        last_step = raw.get("last_step")
        return ExecutionChainView(
            kind=k,
            is_active=bool(raw.get("is_active", False)),
            total_executions=_int("total_executions"),
            canonical_executions=_int("canonical_executions"),
            legacy_executions=_int("legacy_executions"),
            chain_order=tuple(str(s) for s in order),
            last_step=str(last_step) if last_step else None,
            last_target=str(target) if target else None,
        )


@dataclasses.dataclass(frozen=True)
class HybridExecutionView:
    """表达期**用什么手法**在动手。

    ``core/hybrid_execution_policy.py`` 早就把这件事显式化了：不再是一条隐式的
    A2A → GUI → VLM 降级链，而是有名字的几种模式加一句选它的理由。但那个决策在
    ``core/`` 之外**零消费方** —— 系统知道自己正在并行赛跑还是分阶段混合，却从没
    对外说过一个字。这是它第一个上线的消费面。

    没有决策时不是「空对象」而是 :meth:`undecided`：``mode="none"`` 且
    ``is_decided=False``，与「决定了但没给理由」可区分。
    """

    is_decided: bool
    """本轮是否真的做过模式选择。``False`` 时 :attr:`mode` 恒为 ``none``。"""

    mode: str
    """见 :data:`HYBRID_EXECUTION_MODES`。``none`` = 尚未决策。"""

    reason: str
    """选它的理由（后端策略引擎给的原文）。未决策时为空串。"""

    confidence: float
    """[0,1]。1.0=精确命中规则，0.5=启发式，0.0=兜底默认。"""

    @staticmethod
    def undecided() -> "HybridExecutionView":
        """尚未做出模式选择时的视图。"""
        return HybridExecutionView(is_decided=False, mode="none", reason="", confidence=0.0)


@dataclasses.dataclass(frozen=True)
class WorldModelView:
    """世界模型在阈限空间里的位置 —— **目前是占位，但刻意可区分**。

    ``enhancements/reasoning/world_model.py`` 是存在的，维护着实体（device / node /
    service / user / task / goal）及其状态。但它只在 ``core/startup.py`` 与
    ``galaxy_main_loop_l4_enhanced.py`` 里被实例化，**没有任何通向渲染层的投影通路**。

    为什么现在就把位置留出来，而不是等接上了再加字段
    ------------------------------------------------
    因为「留一个空档」和「这一格恒为 null」是两件事。恒 null 的字段在前端只能被
    当成「后端没给」，等真接上时前端还得改判断；而 :attr:`source` 明确区分
    ``unwired``（这条链路还没建）与 ``live``（建好了，数就是这个），前端一次写对，
    Layer 3 落地时**只有构造函数需要改**。

    这也是仓库既有的纪律：空返回必须可区分（见 ``tests/test_empty_return_is_distinguishable.py``）。
    """

    is_wired: bool
    """世界模型是否已经接到渲染链路上。当前恒为 ``False``。"""

    source: str
    """``unwired`` / ``live``，见 :data:`WORLD_MODEL_SOURCES`。"""

    entity_count: int
    """已知实体数。``is_wired=False`` 时恒 0 —— 那是「不知道」，不是「零个」。"""

    entity_kinds: Tuple[str, ...]
    """出现过的实体种类。``is_wired=False`` 时为空元组。"""

    @staticmethod
    def unwired() -> "WorldModelView":
        """世界模型尚未接入渲染链路时的视图 —— 如实标注，不假装是零。"""
        return WorldModelView(is_wired=False, source="unwired", entity_count=0, entity_kinds=())


@dataclasses.dataclass(frozen=True)
class RenderPosture:
    """渲染端的完整姿态：主轴生命周期 × 副轴连续体姿态 × 阈限内容 × 表达参数。

    **两根轴都是真的，回答不同问题**，``TriState`` 的类文档明确禁止把它们混为
    一谈。契约同时携带，并写死主次：

    * :attr:`lifecycle` 是**主轴** —— 用户能直接感知的节奏（休息／过渡／表达），
      也是在场桥一直广播的那一根。渲染端的整体编排应当跟它走。
    * :attr:`continuum_phase` 是**副轴** —— 内部连续体姿态，多一相 ``receding``。
      它不决定整体编排，只提供主轴给不出的纹理：主轴回到 ``silent`` 时，靠副轴
      才能区分「刚做完正在消散」与「静息」。

    每个字段的出处都在 core/ 里，本类不做任何新的推导——只做搬运和如实标注。
    """

    # ── 主轴：主体生命周期（渲染端的首要依据）──────────────────────────
    lifecycle: str
    """silent / liminal / manifest，见 :data:`LIFECYCLE_STATES`。**主轴。**"""

    previous_lifecycle: Optional[str]
    """主轴的上一档；``None`` = 本进程还没发生过转移。

    这是从在场桥订阅到的相位事件里**照实带上来**的（事件 payload 自带
    ``from_phase``，此前一直被丢掉），不是推导出来的。有了它，
    :attr:`transition_kind` 才能说清楚刚才发生的是哪一种转移。
    """

    transition_kind: str
    """刚才那次主轴转移的性质，见 :data:`TRANSITION_KINDS`。

    渲染端的退场编排应当看这一位，而不是看深度往哪边走 —— 深度倒着走只能
    把进场动画倒放，而 ``handoff``（做完接着下一轮）与 ``dissolving``（做完就散）
    本就该是两段不同的动作。
    """

    # ── 副轴：内部连续体姿态（提供纹理，不决定整体编排）────────────────
    continuum_phase: str
    """formless / liminal / manifest / receding，见 :data:`RENDER_PHASES`。"""

    is_returning: bool
    """副轴是否处在返回弧上（``continuum_phase == "receding"``）。

    渲染上最要紧的一位：主轴 ``silent`` 之下，``formless`` 与 ``receding`` 是
    截然不同的两件事，只有这一位能把「刚做完，正在消散」跟「静息，什么都没
    发生」分开。ExpressionEngine 对这两相给出的 form_signature 分别是
    ``none`` 与 ``collapsing_field``。
    """

    next_phases: Tuple[str, ...]
    """副轴从当前相位【合法】能去的下一相，见 :data:`PHASE_TRANSITIONS`。

    渲染端据此提前编排：处在 manifest 时唯一出口是 receding，那么退场动作就该
    按「消散」准备，而不是按「退回上一档」——后者是转移表明令禁止的。
    """

    # ── 阈限态的内容：过渡里到底在干嘛 ──────────────────────────────────
    liminal_activity: str
    """阈限态里正在干嘛。取值域见 :data:`LIMINAL_ACTIVITIES` —— 刻意不在这里重抄一遍，
    抄一遍就是第二份定义，加档时会漏改（``understanding`` 那一档就漏过一次）。"""

    simulation: SimulationSummary
    """沙盘推演摘要。没有推演在跑时是 :meth:`SimulationSummary.inactive`。"""

    local_chain: ExecutionChainView
    """本机执行链视图。阈限空间三类内容之一，见 :class:`ExecutionChainView`。"""

    cross_device_chain: ExecutionChainView
    """跨设备执行链视图。阈限空间三类内容之二。"""

    world_model: WorldModelView
    """世界模型视图 —— **留出的位置，当前恒为 unwired**。见 :class:`WorldModelView`。"""

    # ── 表达期：用什么手法在动手 ────────────────────────────────────────

    hybrid_execution: HybridExecutionView
    """混合执行模式决策。未决策时是 :meth:`HybridExecutionView.undecided`。"""

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
        d["simulation"] = dict(d["simulation"])
        d["simulation"]["candidate_paths"] = list(self.simulation.candidate_paths)
        # 嵌套视图里的元组要转 list —— asdict 会保留元组，json 虽然也能编码它，
        # 但下游拿到的类型会随序列化器而变。这里统一成 list。
        for key, order in (
            ("local_chain", self.local_chain.chain_order),
            ("cross_device_chain", self.cross_device_chain.chain_order),
        ):
            d[key] = dict(d[key])
            d[key]["chain_order"] = list(order)
        d["world_model"] = dict(d["world_model"])
        d["world_model"]["entity_kinds"] = list(self.world_model.entity_kinds)
        d["hybrid_execution"] = dict(d["hybrid_execution"])
        d["hybrid_execution"]["confidence"] = round(float(self.hybrid_execution.confidence), 4)
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


def _anchor_only_render_posture(
    lifecycle: str = "silent",
    previous_lifecycle: Optional[str] = None,
) -> RenderPosture:
    """拿不到 ContinuumState 时的兜底姿态——如实标注，不假装是算出来的。

    主轴仍然可信：``lifecycle`` 来自在场运行时的 ``TriState``，它跟 continuum
    是两条独立链路，continuum 没跑不代表主体生命周期不知道自己在哪。所以这里
    照实带上主轴，只把副轴与连续量退回中性值。

    转移性质同理：``previous_lifecycle`` 也来自相位事件而非 continuum，
    continuum 没跑不影响「刚才从哪一档来的」这个事实，照实带上。
    """
    life = lifecycle if lifecycle in LIFECYCLE_STATES else "silent"
    prev = previous_lifecycle if previous_lifecycle in LIFECYCLE_STATES else None
    # 副轴没有真值时，按主轴取语义上最接近的一相：主轴 silent 对应静息
    # (formless) 而**不是** receding —— 返回弧必须由真实的 continuum 相位证实，
    # 凭空猜一个「正在退场」会让渲染端播出一段根本没发生过的余辉。
    phase = {"silent": "formless", "liminal": "liminal", "manifest": "manifest"}[life]
    return RenderPosture(
        lifecycle=life,
        previous_lifecycle=prev,
        transition_kind=transition_kind_of(prev, life),
        continuum_phase=phase,
        is_returning=False,
        next_phases=PHASE_TRANSITIONS.get(phase, ()),
        liminal_activity="none",
        simulation=SimulationSummary.inactive(),
        local_chain=ExecutionChainView.empty("local"),
        cross_device_chain=ExecutionChainView.empty("cross_device"),
        world_model=WorldModelView.unwired(),
        hybrid_execution=HybridExecutionView.undecided(),
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


def resolve_render_posture(
    lifecycle: str = "silent",
    state: Optional[Any] = None,
    *,
    previous_lifecycle: Optional[str] = None,
    liminal_activity: str = "none",
    simulation: Optional[SimulationSummary] = None,
    local_chain: Optional[ExecutionChainView] = None,
    cross_device_chain: Optional[ExecutionChainView] = None,
    hybrid_execution: Optional[HybridExecutionView] = None,
) -> RenderPosture:
    """合成渲染姿态：主轴由调用方给，副轴与表达参数从 ``ContinuumState`` 读。

    Args:
        lifecycle: 主体生命周期（``TriState`` 的值）。这是**主轴**，由在场桥
            按它订阅到的相位事件传入——那条链路是权威，本函数不去猜。
        state: ``ContinuumState``；省略时取 :func:`last_continuum_posture`。
            拿不到时走 :func:`_anchor_only_render_posture` 兜底。
        previous_lifecycle: 主轴的上一档，同样来自相位事件（其 payload 自带
            ``from_phase``）。据此算出 :attr:`RenderPosture.transition_kind`。
        liminal_activity: 阈限态里正在发生什么，见 :data:`LIMINAL_ACTIVITIES`。
        simulation: 沙盘推演摘要；``None`` 时用空摘要。
        local_chain: 本机执行链视图；``None`` 时用零态（「还没跑过」）。
        cross_device_chain: 跨设备执行链视图；``None`` 时用零态。
        hybrid_execution: 混合执行模式决策；``None`` 时用「尚未决策」。

    三个视图为什么由外面传
    ----------------------
    和主轴同一个理由：它们**不在 ContinuumState 里**。执行链由
    ``RuntimeSession._build_chain_views()`` 在 200ms tick 上产、经
    ``continuum.state`` 事件到在场桥；混合执行决策由
    ``core.hybrid_execution_policy`` 产。本模块的纪律是「绝不构造」——
    在这里去调那些构造函数，等于在每一次相位事件里把它们全跑一遍。

    为什么主轴要由外面传
    --------------------
    因为它**不在 ContinuumState 里**。``TriState`` 由 ``DesktopPresenceRuntime``
    持有，描述主体生命周期；``ContinuumPhase`` 由 continuum 编排器持有，描述内部
    姿态。两者是不同的轴，``TriState`` 的类文档明确写着不要混淆。之前那版
    ``resolve_render_posture`` 只读 ``state.phase`` 就返回，等于用副轴冒充主轴——
    接到桥上会给出与 ``payload.phase`` 不一致的相位帧。

    与 :func:`resolve_phase_posture` 的差别
    ---------------------------------------
    遗留函数把外部传入的三态 token 当成唯一相位，于是即便它手里的 ``state``
    带着 ``receding``，也会被外面那个 ``static`` 覆盖掉——真相就在手里却用了投影。
    这里两根轴各归其位：主轴照实用传入值，副轴照实读 ``state.phase``。
    """
    life = lifecycle if lifecycle in LIFECYCLE_STATES else "silent"
    prev = previous_lifecycle if previous_lifecycle in LIFECYCLE_STATES else None
    activity = liminal_activity if liminal_activity in LIMINAL_ACTIVITIES else "none"
    sim = simulation if simulation is not None else SimulationSummary.inactive()
    local = local_chain if local_chain is not None else ExecutionChainView.empty("local")
    cross = cross_device_chain if cross_device_chain is not None else ExecutionChainView.empty("cross_device")
    hybrid = hybrid_execution if hybrid_execution is not None else HybridExecutionView.undecided()

    if state is None:
        state = last_continuum_posture()
    if state is None:
        base = _anchor_only_render_posture(life, prev)
        return dataclasses.replace(
            base,
            liminal_activity=activity,
            simulation=sim,
            local_chain=local,
            cross_device_chain=cross,
            hybrid_execution=hybrid,
        )

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
        # 表达参数与副轴对不上（默认值或上一拍残留）→ 用无状态引擎按当前 state
        # 重算。这不违反本模块「绝不构造」的纪律：那条针对的是 core.openclawd
        # （很重、有副作用）；ExpressionEngine 是纯函数，重算与流水线里那份逐位相同。
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
        lifecycle=life,
        previous_lifecycle=prev,
        transition_kind=transition_kind_of(prev, life),
        continuum_phase=phase,
        is_returning=phase == "receding",
        next_phases=PHASE_TRANSITIONS.get(phase, ()),
        liminal_activity=activity,
        simulation=sim,
        local_chain=local,
        cross_device_chain=cross,
        world_model=WorldModelView.unwired(),
        hybrid_execution=hybrid,
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
        "lifecycle_states": list(LIFECYCLE_STATES),
        "liminal_activities": list(LIMINAL_ACTIVITIES),
        "simulation_kinds": list(SIMULATION_KINDS),
        "runtime_domains": list(RUNTIME_DOMAINS),
        "form_signatures": list(FORM_SIGNATURES),
        "spatial_presences": list(SPATIAL_PRESENCES),
        "chain_kinds": list(CHAIN_KINDS),
        "hybrid_execution_modes": list(HYBRID_EXECUTION_MODES),
        "world_model_sources": list(WORLD_MODEL_SOURCES),
        "transition_kinds": list(TRANSITION_KINDS),
        "transition_kind_of": [{"from": a, "to": b, "kind": k} for (a, b), k in TRANSITION_KIND_OF.items()],
        "sources": [PostureSource.CONTINUUM, PostureSource.ANCHOR_ONLY],
        "chain_fields": [
            {"name": "kind", "ts": "ChainKind", "doc": "local / cross_device —— 决定 last_target 的含义"},
            {"name": "is_active", "ts": "boolean", "doc": "这条链是否跑过；false=还没跑过，不是「没有这条链」"},
            {"name": "total_executions", "ts": "number", "doc": "本会话内这条链上的总执行次数"},
            {"name": "canonical_executions", "ts": "number", "doc": "其中走完整规范链的次数"},
            {"name": "legacy_executions", "ts": "number", "doc": "其中走遗留／非规范路径的次数"},
            {"name": "chain_order", "ts": "string[]", "doc": "规范链的步骤名（有序）—— 空间里该画几段"},
            {"name": "last_step", "ts": "string | null", "doc": "最近一次到达的步骤名"},
            {"name": "last_target", "ts": "string | null", "doc": "local→task_id，cross_device→device_id"},
        ],
        "hybrid_fields": [
            {"name": "is_decided", "ts": "boolean", "doc": "本轮是否真的做过模式选择"},
            {"name": "mode", "ts": "HybridExecutionMode", "doc": "用什么手法动手；none=尚未决策"},
            {"name": "reason", "ts": "string", "doc": "选它的理由（后端策略引擎原文）"},
            {"name": "confidence", "ts": "number", "doc": "[0,1]：1=精确命中规则，0.5=启发式，0=兜底"},
        ],
        "world_model_fields": [
            {"name": "is_wired", "ts": "boolean", "doc": "世界模型是否已接到渲染链路；当前恒 false"},
            {"name": "source", "ts": "WorldModelSource", "doc": "unwired=链路还没建，live=数就是这个"},
            {"name": "entity_count", "ts": "number", "doc": "已知实体数；unwired 时的 0 是「不知道」"},
            {"name": "entity_kinds", "ts": "string[]", "doc": "出现过的实体种类"},
        ],
        "simulation_fields": [
            {"name": "is_active", "ts": "boolean", "doc": "当前是否有推演在跑"},
            {"name": "simulation_kind", "ts": "SimulationKind", "doc": "none / speculative / sandbox"},
            {"name": "candidate_paths", "ts": "string[]", "doc": "正在评估的候选执行路径 —— 阈限态在权衡什么"},
            {"name": "committed_path", "ts": "string | null", "doc": "已提交的那条；仍在推演/全失败时 null"},
            {"name": "is_committed", "ts": "boolean", "doc": "committed_path !== null"},
            {"name": "step_count", "ts": "number", "doc": "已完成的推演步数"},
            {"name": "scenario_label", "ts": "string | null", "doc": "场景的人类可读标签"},
        ],
        "fields": [
            {"name": "lifecycle", "ts": "Lifecycle", "doc": "【主轴】主体生命周期 —— 渲染端的整体编排跟它走"},
            {
                "name": "previous_lifecycle",
                "ts": "Lifecycle | null",
                "doc": "主轴的上一档（相位事件自带 from_phase）；null=还没发生过转移",
            },
            {
                "name": "transition_kind",
                "ts": "TransitionKind",
                "doc": "刚才那次转移的性质 —— 退场编排看这一位，别从深度差里猜",
            },
            {
                "name": "continuum_phase",
                "ts": "RenderPhase",
                "doc": "【副轴】内部连续体四相，提供主轴给不出的纹理",
            },
            {
                "name": "is_returning",
                "ts": "boolean",
                "doc": "副轴是否在返回弧上（receding）——把「刚做完」与「静息」分开的那一位",
            },
            {"name": "next_phases", "ts": "RenderPhase[]", "doc": "副轴从当前相位合法能去的下一相"},
            {
                "name": "liminal_activity",
                "ts": "LiminalActivity",
                # 取值列表由常量拼出，不手抄 —— 手抄那份漏掉过 understanding，而 TS 类型
                # 本身是从同一个常量生成的，于是【类型对、注释错】，评审时最难看出来。
                "doc": "阈限态里正在干嘛（有序递进）：" + " → ".join(LIMINAL_ACTIVITIES),
            },
            {"name": "simulation", "ts": "SimulationSummary", "doc": "沙盘推演摘要 —— 阈限态的可视内容之三"},
            {"name": "local_chain", "ts": "ExecutionChainView", "doc": "本机执行链 —— 阈限态的可视内容之一"},
            {
                "name": "cross_device_chain",
                "ts": "ExecutionChainView",
                "doc": "跨设备执行链 —— 阈限态的可视内容之二",
            },
            {"name": "world_model", "ts": "WorldModelView", "doc": "世界模型 —— 留出的位置，当前恒 unwired"},
            {
                "name": "hybrid_execution",
                "ts": "HybridExecutionView",
                "doc": "表达期用什么手法动手（GUI／API／混合）",
            },
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
