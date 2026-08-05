"""core.liminal_activity — 阈限相位与阈限内容之间的那根线

要解决什么
----------
系统里「主体在过渡」和「过渡里正在发生什么」是两件事，而后者此前**没有任何链路**。

``core/desktop_presence_runtime.py`` 的 ``TriState.LIMINAL`` 说的是前者：主体在
过渡中，OpenClawd 的认知与执行分支正在这一相里进行。``core/liminal_rehearsal.py``
的沙盘推演说的是后者：智能体在真正落手之前，先在影子沙盘里推演若干条候选路径。

**两者在时间上早就重合了** —— 推演就跑在 ``advance(LIMINAL)`` 与
``_enter_manifest()`` 之间的认知段里，而且那个时序是有人专门调过的（见
desktop_presence_runtime 里 ``_enter_manifest`` 上方的注释：此前拿到执行车道就
立刻 advance，"阈限态几毫秒就被跳过，推演/认知期在视觉上不存在"）。

缺的是**生命周期不知道它内部在发生什么**。于是阈限态在面板上永远只是一个空标签：
相位对了，内容是空的。本模块就是这根线。

为什么用 contextvar
-------------------
登记点在请求链路深处（``core/openclawd.py`` 的认知段），那里拿不到
``RuntimeSession``，而为此改一路函数签名代价太大。一次请求跑在一条 asyncio 任务
里，``contextvars`` 的 Context 天然按请求隔离。这是本仓库的既定模式 ——
``core/task_cost_ledger.py`` 与 ``core/llm_stream.py`` 用的是同一套，那两处的注释
写的是"零签名侵入"。

刻意的边界
----------
* **可见性绝不拖垮请求**。所有登记失败都静默降级，只留 debug 日志。
* **不在请求里就是空操作**，返回 ``False``。直接调 OpenClawd、或在测试里裸跑
  预演，都不该因为没有在场运行时而报错。
* **不变量可验证**。只有处在 ``LIMINAL`` 时登记内容才有意义；在别的相位登记会留
  warning。这让「预演跑在阈限态里」这件事从"靠时序巧合"变成"有断言在盯"。
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.LiminalActivity")

__all__ = [
    "LIMINAL_ACTIVITIES",
    "current_runtime_session",
    "bind_runtime_session",
    "unbind_runtime_session",
    "note_liminal_activity",
]

#: 阈限态里正在发生什么。与 ``core.phase_contract.LIMINAL_ACTIVITIES`` 同源；
#: 在这里复刻一份是为了不让本模块反向依赖渲染契约（它是被契约消费的一方）。
LIMINAL_ACTIVITIES: Tuple[str, ...] = ("none", "thinking", "rehearsing")

#: 当前请求的 ``RuntimeSession``。类型刻意写成 ``Any`` —— 本模块被
#: ``desktop_presence_runtime`` 导入，标注具体类型会形成循环导入。
_current_runtime_session: "contextvars.ContextVar[Optional[Any]]" = contextvars.ContextVar(
    "galaxy_current_runtime_session", default=None
)


def current_runtime_session() -> Optional[Any]:
    """取当前请求的 ``RuntimeSession``；不在请求里返回 ``None``。"""
    return _current_runtime_session.get()


def bind_runtime_session(session: Any) -> "contextvars.Token":
    """把会话挂进当前 Context。由 ``handle_request`` 在建会话后调用。"""
    return _current_runtime_session.set(session)


def unbind_runtime_session(token: "contextvars.Token") -> None:
    """复位。跨任务复位会抛 ``ValueError``（token 属于别的 Context），那种情况下
    该 Context 本来就随任务一起消失，忽略即可。"""
    try:
        _current_runtime_session.reset(token)
    except ValueError:
        pass


def note_liminal_activity(activity: str, summary: Optional[Dict[str, Any]] = None) -> bool:
    """从请求链路的任意深处登记「阈限态里正在发生什么」。

    Args:
        activity: ``thinking`` / ``rehearsing`` / ``none``；未知值按 ``none`` 处理。
        summary: 沙盘推演摘要（``MultiCandidateOutcome.simulation_summary_kwargs()``
            的产物）。``None`` 表示不更新摘要——纯思考期不该把上一段的候选抹掉。

    Returns:
        ``True`` 登记成功；``False`` 表示当前不在一次 ``handle_request`` 里。
    """
    session = _current_runtime_session.get()
    if session is None:
        return False
    try:
        session.enter_liminal_activity(activity, summary)
        return True
    except Exception:  # noqa: BLE001 — 可见性绝不该拖垮请求
        logger.debug("note_liminal_activity failed (non-fatal)", exc_info=True)
        return False
