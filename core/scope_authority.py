"""core/scope_authority.py —— 这个作用域下,谁说了算

一句话
------
**本地的事本地说了算,跨设备的事中心说了算,判不出来的时候谁都不许说了算。**

为什么不是全局二选一
--------------------
"Android 本地状态以谁为准"这个问题(路线图 Q4)一直被写成三选一:V2 权威 /
Android 权威 / 显式双向同步。三个答案都不对,因为它们都假设**权威是全局属性**。

不是。同一台设备,在两种情形下该由不同的一方说了算:

* 它自己单机跑一件事 —— 中心根本不在场。这时候要求"以中心为准"等于让一台离线
  设备等一个不会来的答复;而 ``core/network/OfflineTaskQueue`` 的存在恰恰说明
  单机运行是这个系统的正常形态,不是异常。
* 它在编队里跨设备执行 —— 真值链、幂等、受理裁决整套判据都在 V2 侧。这时候
  让 Android 权威,等于把那套判据再搬一份到 Android 上,也就是第二份定义。

所以权威跟着**作用域**走,不跟着设备走。作用域这根轴是
``core.continuum.types.RuntimeDomain``(连续体的第二公共维度),由
``core.continuum.runtime_domain_resolver`` 唯一判定。本模块不新造作用域,
只回答"给定这个作用域,谁说了算"。

四种情形
--------
============  ==========  ==============  ==============================
作用域        权威        迁移语义        接受本地写入
============  ==========  ==============  ==============================
local         本地        漫游            是
cross_device  中心        共享            否(Android 发 delta,中心裁决)
transition    沿用上一档  **拒绝**        沿用上一档
null          **无人**    共享(降级留痕)  **否**
============  ==========  ==============  ==============================

最后一行的两格**故意不一样**,这处不对称是想清楚的
--------------------------------------------------
判不出来时,"拒绝写入"与"拒绝迁移"的代价完全不同:

* **写入**:接受一条说不出归属的状态,等于把一个来路不明的事实写进真值。
  拒绝是对的,而且拒绝可见(调用方拿到原因)。
* **迁移**:作用域判不出来是**常态之一**,不是异常 —— 没有桌面在场运行时的纯服务端
  部署里,连续体根本不跑,``runtime_domain`` 本来就没有值。在一个常态上装拒绝,
  等于把会话迁移整个关掉。

所以迁移这一格降级到**共享**语义:两种语义里只有漫游是破坏性的(把源设备移出会话),
共享是非破坏性的(源设备保留)。判不出来时选不丢东西的那一种,并且
``migration_degraded`` 置真、原因写进返回值 —— 降级留痕,不是静默换挡。

``transition`` 那一格仍然是**真拒绝**:它与 null 不同,含义是"正在决定要不要扩到
跨设备",迁移撞进一个正在建立的编队是真实的危险,而且这一档是**短暂的** ——
拒绝一次,等它定下来再迁。

两种迁移语义不是实现差异,是产品行为差异(实测见
``tests/test_session_migration_consistency.py``):

* **漫游** —— 会话跟着人走,同一时刻只在一台设备上,旧映射删掉。
  对应 ``galaxy_gateway/session_roaming.py``。
* **共享** —— 一个会话同时挂在几台设备上,当前活跃的是某一台,源设备保留。
  对应 ``core/routes/sessions.py`` 的 canonical manager。

单机场景要的是前者(一个人换一台设备继续),编队场景要的是后者(几台设备一起做
一件事)。用错语义的后果不是报错,是**行为悄悄变了**:该跟着走的会话留在了原地,
或者该共享的会话被独占转移走。

``transition`` 为什么是"沿用"而不是"选一个"
-------------------------------------------
``transition`` 的含义是"正在决定要不要扩到跨设备"。这一档下**没有正确答案** ——
按 local 判会在编队即将建立时把权威留在本地;按 cross_device 判会在编队最终没建
成时把权威交给一个不该管的地方。

沿用进入 transition 之前那一档是唯一不引入新错误的选择:权威不变,直到作用域真的
定下来。代价是要记住"之前是哪一档",所以本模块带一个按会话的已定作用域表 ——
这也正好是交接留痕的落点。

如果一个会话从来没有过已定作用域(第一次见到它就是 transition),那就是
``undecidable`` —— 沿用不了一个从来不存在的东西,不能假装沿用。

``null`` 为什么不许当成"本地"
-----------------------------
判不出来的时刻,常常正是连接刚抖动、编队刚建立、注册表还没同步的时刻 ——
也就是最需要仲裁的时刻。把 ``None`` 静默读成 ``local``,等于在最不该的时候把权威
交给本地,而且**没有任何一处会显示这件事发生过**。

所以 ``authority`` 这一位在判不出来时是 ``undecidable``,不是 ``local``;
本地写入一律不收。至于迁移那一格为什么降级而不是拒绝,见上面那处不对称。

一句话:**说不出来就说说不出来,但降级要挑不丢东西的那一档,并且留痕。**

交接留痕
--------
一个会话从 ``local`` 变成 ``cross_device``(或反过来)的那一刻,**权威易手**。
不把这一刻显式记下来,事后就没有任何一处能回答"那次冲突发生时到底谁说了算" ——
而冲突恰恰最常发生在交接前后。

``record_scope(session_id, scope)`` 每次都会比对上一次的已定作用域,变了就往
账本里记一条 :class:`ScopeHandover`。账本有界(见 :data:`HANDOVER_LEDGER_MAX`)——
无界的账本本身就是一次内存泄漏。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.ScopeAuthority")

#: 谁说了算。``undecidable`` = 说不出来,**不是**"默认本地"。
AUTHORITIES: Tuple[str, ...] = ("local", "center", "undecidable")

#: 迁移语义。``refused`` = 这一档下不许迁移(不是"迁移失败",是"不该在这时候迁")。
MIGRATION_SEMANTICS: Tuple[str, ...] = ("roaming", "shared", "refused")

#: 判不出来时迁移降级到的语义。取**非破坏性**的那一种(共享:源设备保留);
#: 漫游会把源设备移出会话,判不出来时不能做这种事。
DEGRADED_MIGRATION = "shared"

#: 交接账本上限。有界 —— 无界账本本身就是一次内存泄漏。
HANDOVER_LEDGER_MAX = 200

_ledger: Deque["ScopeHandover"] = deque(maxlen=HANDOVER_LEDGER_MAX)
#: 按会话记住"最后一次**定下来**的作用域"(transition / null 不算定下来)。
_settled: Dict[str, str] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class ScopeAuthority:
    """给定作用域下的权威归属。"""

    #: 作用域取值;``None`` = 判不出来。
    scope: Optional[str]
    authority: str
    migration: str
    #: 允不允许把本地(设备侧)上报的状态直接当真。
    accepts_local_writes: bool
    reason: str
    #: ``transition`` 档下沿用的是哪一档;其余情形为空串。
    carried_from: str = ""
    #: 迁移语义是不是**降级来的**(作用域判不出来时的非破坏性兜底),不是判出来的。
    migration_degraded: bool = False

    @property
    def decided(self) -> bool:
        """判出来了没有。``undecidable`` 一律为假。"""
        return self.authority != "undecidable"

    @property
    def may_migrate(self) -> bool:
        return self.migration != "refused"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scope": self.scope,
            "authority": self.authority,
            "migration": self.migration,
            "accepts_local_writes": self.accepts_local_writes,
            "decided": self.decided,
            "may_migrate": self.may_migrate,
            "carried_from": self.carried_from,
            "migration_degraded": self.migration_degraded,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ScopeHandover:
    """一次权威易手。"""

    at: float
    session_id: str
    previous: str
    current: str
    previous_authority: str
    current_authority: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "at": self.at,
            "session_id": self.session_id,
            "previous": self.previous,
            "current": self.current,
            "previous_authority": self.previous_authority,
            "current_authority": self.current_authority,
        }


class ScopeAuthorityRefused(RuntimeError):
    """这一档下不许做这件事。显式拒绝,不静默放行。"""


# ══════════════════════════════════════════════════════════════════════════
# 判据
# ══════════════════════════════════════════════════════════════════════════

_UNDECIDABLE = ScopeAuthority(
    scope=None,
    authority="undecidable",
    migration=DEGRADED_MIGRATION,
    accepts_local_writes=False,
    migration_degraded=True,
    reason=(
        "作用域判不出来 —— 说不准谁说了算,所以**不接受本地写入**;"
        f"迁移降级到非破坏性的 {DEGRADED_MIGRATION} 语义(源设备保留),"
        "见模块头「这处不对称是想清楚的」"
    ),
)


def _scope_value(scope: Any) -> Optional[str]:
    """把作用域归一成字符串。认不出来返回 ``None``(不猜一个)。"""
    from core.continuum.types import RuntimeDomain  # noqa: PLC0415

    if scope is None:
        return None
    raw = getattr(scope, "value", scope)
    if not isinstance(raw, str):
        return None
    raw = raw.strip().lower()
    try:
        return RuntimeDomain(raw).value
    except ValueError:
        return None


def authority_for(scope: Any, *, carried_from: str = "") -> ScopeAuthority:
    """给定作用域,谁说了算。**唯一判据处,不抛异常。**

    Args:
        scope: ``RuntimeDomain`` 或其字符串值;``None`` = 判不出来。
        carried_from: ``transition`` 档下沿用的那一档。调用方一般不直接传 ——
                      用 :func:`authority_for_session` 让它自己查。
    """
    value = _scope_value(scope)
    if value is None:
        return _UNDECIDABLE

    if value == "local":
        return ScopeAuthority(
            scope="local",
            authority="local",
            migration="roaming",
            accepts_local_writes=True,
            reason="本机作用域:中心不在场,本地自己说了算;会话迁移按漫游语义(跟着人走)",
        )

    if value == "cross_device":
        return ScopeAuthority(
            scope="cross_device",
            authority="center",
            migration="shared",
            accepts_local_writes=False,
            reason=("跨设备作用域:真值链/幂等/受理裁决都在中心侧,由中心裁决;" "会话迁移按共享语义(源设备保留)"),
        )

    # transition —— 沿用进入这一档之前的那一档
    if not carried_from:
        return ScopeAuthority(
            scope="transition",
            authority="undecidable",
            migration="refused",
            accepts_local_writes=False,
            reason="过渡档,但这个会话没有已定作用域可沿用 —— 沿用不了一个从来不存在的东西",
        )
    carried = authority_for(carried_from)
    return ScopeAuthority(
        scope="transition",
        authority=carried.authority,
        migration="refused",
        accepts_local_writes=carried.accepts_local_writes,
        carried_from=carried.scope or "",
        reason=(
            f"过渡档:正在决定要不要扩到跨设备。权威沿用上一档({carried.scope}),"
            "但**这一档下不迁移** —— 迁移会撞上编队建立"
        ),
    )


def record_scope(session_id: str, scope: Any) -> Optional[ScopeHandover]:
    """记下这个会话当前的作用域;定下来的档位变了就记一条交接。

    ``transition`` 与 ``None`` **不算定下来**,不覆盖已定值 —— 否则一次短暂的
    判不出来就会把"之前是哪一档"擦掉,transition 的沿用也就没了依据。

    Returns:
        发生了交接就返回那条记录,否则 ``None``。
    """
    value = _scope_value(scope)
    if value is None or value == "transition":
        return None

    key = str(session_id or "")
    if not key:
        return None

    with _lock:
        previous = _settled.get(key, "")
        _settled[key] = value
        if not previous or previous == value:
            return None
        handover = ScopeHandover(
            at=time.time(),
            session_id=key,
            previous=previous,
            current=value,
            previous_authority=authority_for(previous).authority,
            current_authority=authority_for(value).authority,
        )
        _ledger.append(handover)

    logger.info(
        "作用域交接 | session=%s %s(%s) → %s(%s)",
        key,
        handover.previous,
        handover.previous_authority,
        handover.current,
        handover.current_authority,
    )
    return handover


def settled_scope(session_id: str) -> str:
    """这个会话最后一次**定下来**的作用域;从来没定过返回空串。"""
    with _lock:
        return _settled.get(str(session_id or ""), "")


def authority_for_session(session_id: str, scope: Any) -> ScopeAuthority:
    """按会话判权威 —— ``transition`` 档会自动沿用它自己的上一档。

    这是调用方该用的那个入口;:func:`authority_for` 是它的纯函数内核。
    """
    record_scope(session_id, scope)
    value = _scope_value(scope)
    if value == "transition":
        return authority_for(scope, carried_from=settled_scope(session_id))
    return authority_for(scope)


def current_scope() -> Optional[str]:
    """当前这一拍的作用域;拿不到返回 ``None``(**判不出来**)。

    直接读连续体状态上那一位 —— 它由 ``ContinuumOrchestrator`` 每拍盖章、由
    ``core.continuum.runtime_domain_resolver`` 唯一判定。这里不重算,重算就是
    第二份定义。

    刻意**不**走 ``lumiv_websocket_bridge.get_current_phase()``:那个函数拿不到
    相位时返回 ``"silent"``,把"判不出来"变成了"就是静默" —— 用它当作用域的来源,
    等于把一个兜底值当成事实,而这正是本模块要防的东西。

    连续体没在跑(例如没有桌面在场运行时的纯服务端部署)时返回 ``None``。
    那是**常态之一**,不是故障 —— 见模块头那处不对称。
    """
    try:
        from core.desktop_presence_runtime import DesktopPresenceRuntime  # noqa: PLC0415

        runtime = getattr(DesktopPresenceRuntime, "_instance", None)
        state = getattr(runtime, "_continuum_state", None) if runtime is not None else None
        return _scope_value(getattr(state, "runtime_domain", None) if state is not None else None)
    except Exception as exc:  # noqa: BLE001 — 问不到就是判不出来
        logger.debug("当前作用域问不到: %s", exc)
        return None


def current_authority(session_id: str = "") -> ScopeAuthority:
    """用**当前这一拍**的作用域判权威。"""
    scope = current_scope()
    if session_id:
        return authority_for_session(session_id, scope)
    return authority_for(scope)


def require_migration(session_id: str, scope: Any) -> ScopeAuthority:
    """迁移前问这一句。这一档不许迁就抛 :class:`ScopeAuthorityRefused`。

    抛而不是返回布尔,是因为迁移是**有副作用的动作** —— 返回值会被忽略,
    异常不会。会话迁移一旦漏判,后果是会话跑到不该去的地方。
    """
    verdict = authority_for_session(session_id, scope)
    if not verdict.may_migrate:
        raise ScopeAuthorityRefused(verdict.reason)
    return verdict


def recent_handovers(limit: int = 50) -> List[Dict[str, Any]]:
    """最近的权威易手。"""
    with _lock:
        items = list(_ledger)
    return [h.to_dict() for h in items[-max(0, int(limit)) :]]


def clear_registry() -> None:
    """清空已定作用域与交接账本。**测试用**;生产路径不该调它。"""
    with _lock:
        _settled.clear()
        _ledger.clear()


def authority_report() -> Dict[str, Any]:
    """当前姿态,给诊断面。"""
    now = current_authority()
    with _lock:
        tracked = len(_settled)
        handovers = len(_ledger)
    return {
        "authorities": list(AUTHORITIES),
        "migration_semantics": list(MIGRATION_SEMANTICS),
        "current": now.to_dict(),
        "sessions_tracked": tracked,
        "handovers_recorded": handovers,
        "ledger_max": HANDOVER_LEDGER_MAX,
        "undecidable_means": (
            "authority=undecidable 表示**说不出来谁说了算**,不是默认本地;" "这一档下迁移与本地写入都不放行"
        ),
    }
