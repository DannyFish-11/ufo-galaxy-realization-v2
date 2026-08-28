"""core.continuum.runtime_domain_resolver —— 现在到底在哪儿跑

这个模块存在的理由
------------------
``RuntimeDomain``(local / transition / cross_device)是连续体的**第二公共维度**,
``core/continuum/types.py`` 里那张表把它和三态的组合语义写得很清楚。
执行策略读它(``execution_policy.policy_resolver`` 的 "Domain upgrade" 一档)、
模型拓扑读它、投影读它、面板显示它、``RenderPosture`` 把它透给渲染端。

但在这个模块之前,**运行期没有任何一处给它赋过值**:

* ``ContinuumState.runtime_domain`` 的默认是 ``None``;
* 每拍真正产出状态的 ``TemporalEngine`` 里,``runtime_domain`` 出现 **0 次**;
* 唯一带值的构造点是 ``projection/runtime_truth_compiler.py`` 里那个
  "拿不到状态时的最小静默兜底",写死 ``LOCAL``。

也就是说:一根被下游当判据用的轴,上游从来没人填。所有读到的都是
"尚未判定",而各处兜底又各自把它变成了别的东西。

为什么不能兜底成 ``local``
--------------------------
这是整块设计的地基,单独说一遍。

按作用域分权威("本地的事本地说了算,跨设备的事中心说了算")成立的前提,是
**作用域本身说得准**。如果"判不出来"被静默读成"本地",那么每一次判不出来,
系统都会**默认把权威交给本地** —— 而判不出来的时刻,恰恰就是跨设备编队刚建立、
连接刚抖动、注册表还没同步的那些时刻,也就是最需要中心仲裁的时刻。

所以本模块的第一条规矩:**判不出来返回 ``None``,永不回落到 ``LOCAL``。**
``None`` 是一个下游必须显式处理的值,``LOCAL`` 是一个会被当成答案的值。

判据从哪儿来
------------
不新造事实。判定只用两样已经存在的东西:

1. **三态相位** —— 来自这一拍的 ``ContinuumState.phase``;
2. **有没有远端挂着** —— ``core.attached_runtime_session_registry.list_active_sessions()``,
   即当前处于 ``active`` 的挂载运行时会话。

组合规则直接照抄 ``types.py`` 里那张表,不做任何表外推导:

==========  ==============  ==================================================
相位        远端挂载        判定
==========  ==============  ==================================================
silent      —               ``LOCAL``   只在感知,按定义就是单机
liminal     无              ``LOCAL``   意图在本机成形
liminal     有              ``TRANSITION``  正在决定要不要扩到跨设备
manifest    无              ``LOCAL``   在本机执行
manifest    有              ``CROSS_DEVICE``  正在跨远端执行
任意        问不到          ``None``    判不出来
==========  ==============  ==================================================

``silent`` 那一行是唯一一处"有远端也判 LOCAL":静默态按定义只有感知,没有执行,
远端挂着不代表这一拍在跨设备做事。这一条是表里写死的,不是这里的发挥。

与 ``runtime_domain_intent`` 的关系(**两回事,别合并**)
--------------------------------------------------------
``core/device_formation/`` 与 ``core/cross_device_policy/`` 里有一个长得很像的
``runtime_domain_intent``。它**不是**本模块的重复定义:

* ``runtime_domain_intent`` 是**意图** —— 编队声明"我打算跨设备干这件事";
* ``runtime_domain`` 是**事实** —— 这一拍实际在哪儿跑。

两者可以不一致,而且不一致本身有信息量(声明了要跨设备,但远端一个都没挂上来)。
把它们合并成一处会把这个信息抹掉。它们各自的默认值也是各自语境里对的:
``FormationGroup`` 存在就意味着编队存在(默认 ``cross_device``),
``FormationSummary`` 的默认语境是 "no active formation"(默认 ``local``)。
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from core.continuum.types import ContinuumPhase, RuntimeDomain, TriStatePhase, continuum_to_tri_state

logger = logging.getLogger("Galaxy.Continuum.RuntimeDomain")

#: 判定来源,进判定对象也进诊断面 —— "凭什么这么判"必须说得出来。
DOMAIN_SOURCES = ("attached_sessions", "silent_by_definition", "unresolved")


class RuntimeDomainVerdict:
    """一次作用域判定:判成了什么,以及凭什么。

    刻意不是 ``NamedTuple``/``dataclass`` 里只有一个 domain 的形状 ——
    ``None`` 与 ``LOCAL`` 必须能从**理由**上区分开,不能只看结果。
    """

    __slots__ = ("domain", "source", "remote_count", "reason")

    def __init__(
        self,
        domain: Optional[RuntimeDomain],
        source: str,
        remote_count: Optional[int],
        reason: str,
    ) -> None:
        self.domain = domain
        self.source = source
        #: 判定时看到的活跃远端挂载数;``None`` = 问不到(与 0 台必须可区分)。
        self.remote_count = remote_count
        self.reason = reason

    @property
    def resolved(self) -> bool:
        """判出来了没有。``None`` 一律为假 —— 说不出来就不算数。"""
        return self.domain is not None

    def to_dict(self) -> dict:
        return {
            "domain": self.domain.value if self.domain is not None else None,
            "source": self.source,
            "remote_count": self.remote_count,
            "reason": self.reason,
            "resolved": self.resolved,
        }

    def __repr__(self) -> str:  # pragma: no cover — 诊断用
        return f"RuntimeDomainVerdict(domain={self.domain!r}, source={self.source!r}, remote={self.remote_count!r})"


def _active_remote_sessions() -> Optional[List[Any]]:
    """当前活跃的挂载运行时会话。

    返回 ``None`` 表示**问不到**(注册表不可用),与"问到了,是 0 台"必须可区分 ——
    前者判不出作用域,后者判得出(就是本地)。
    """
    try:
        from core.attached_runtime_session_registry import list_active_sessions  # noqa: PLC0415

        return list(list_active_sessions())
    except Exception as exc:  # noqa: BLE001 — 问不到就是问不到,不猜
        logger.debug("挂载会话注册表问不到,作用域判不出: %s", exc)
        return None


def resolve_runtime_domain(phase: Any) -> RuntimeDomainVerdict:
    """判定这一拍的作用域。**唯一判据处。**

    Args:
        phase: 这一拍的相位。接受 :class:`ContinuumPhase` 或 :class:`TriStatePhase`
               ——内部一律归一到三态,因为 ``types.py`` 那张表是按三态写的
               (``receding`` 在外部与 ``silent`` 不可区分,这里跟着表走)。

    Returns:
        :class:`RuntimeDomainVerdict`。``domain is None`` = 判不出来,
        **不是** "本地"。
    """
    tri = _to_tri_state(phase)
    if tri is None:
        return RuntimeDomainVerdict(
            domain=None,
            source="unresolved",
            remote_count=None,
            reason=f"相位读不出来({phase!r}),作用域无从判起",
        )

    if tri is TriStatePhase.SILENT:
        # 表里写死的一行:静默只在感知,没有执行,远端挂着也不算跨设备。
        # 这一档不去查注册表 —— 每拍都查一次一个不影响结果的东西,是白花钱。
        return RuntimeDomainVerdict(
            domain=RuntimeDomain.LOCAL,
            source="silent_by_definition",
            remote_count=None,
            reason="静默态只在感知,按定义单机",
        )

    sessions = _active_remote_sessions()
    if sessions is None:
        return RuntimeDomainVerdict(
            domain=None,
            source="unresolved",
            remote_count=None,
            reason="挂载会话注册表问不到 —— 判不出来,不回落到 local",
        )

    count = len(sessions)
    if count == 0:
        return RuntimeDomainVerdict(
            domain=RuntimeDomain.LOCAL,
            source="attached_sessions",
            remote_count=0,
            reason="没有活跃的远端挂载,在本机跑",
        )

    if tri is TriStatePhase.LIMINAL:
        return RuntimeDomainVerdict(
            domain=RuntimeDomain.TRANSITION,
            source="attached_sessions",
            remote_count=count,
            reason=f"阈限态且有 {count} 个远端挂着 —— 正在决定要不要扩到跨设备",
        )

    return RuntimeDomainVerdict(
        domain=RuntimeDomain.CROSS_DEVICE,
        source="attached_sessions",
        remote_count=count,
        reason=f"显现态且有 {count} 个远端挂着 —— 正在跨设备执行",
    )


def _to_tri_state(phase: Any) -> Optional[TriStatePhase]:
    """把相位归一到三态。读不出来返回 ``None``(不猜一个)。"""
    if isinstance(phase, TriStatePhase):
        return phase
    if isinstance(phase, ContinuumPhase):
        return continuum_to_tri_state(phase)
    # 字符串形态(跨进程/反序列化过来的)也认,但只认表里有的那几个。
    raw = getattr(phase, "value", phase)
    if not isinstance(raw, str):
        return None
    raw = raw.strip().lower()
    try:
        return continuum_to_tri_state(ContinuumPhase(raw))
    except ValueError:
        pass
    try:
        return TriStatePhase(raw)
    except ValueError:
        return None


def domain_report() -> dict:
    """当前作用域姿态,给诊断面。

    不缓存 —— 这个判定本来就是"此刻",缓存等于报一个过去的作用域,
    而作用域过期正是这套设计最怕的东西。
    """
    from core.continuum.types import ContinuumPhase as _CP  # noqa: PLC0415

    sessions = _active_remote_sessions()
    return {
        "axis": "runtime_domain",
        "values": [d.value for d in RuntimeDomain],
        "sources": list(DOMAIN_SOURCES),
        "remote_sessions": None if sessions is None else len(sessions),
        "remote_sessions_note": ("null = 注册表问不到(与 0 台不同)"),
        "sample_manifest": resolve_runtime_domain(_CP.MANIFEST).to_dict(),
        "unresolved_means": "domain=null 表示判不出来,**不是** local;下游必须显式处理",
    }
