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
    "in_deliberation_window",
    "commit_to_manifest",
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


def in_deliberation_window() -> bool:
    """现在是否处在**审议窗口**里——即可以做沙盘推演的那一段。

    这是「相位闸门驱动预演」的判据本身。语义严格对齐 ``TriState.LIMINAL``：
    *主体在过渡中，认知与执行分支正在这一相里进行*。推演只在这段里成立——
    一旦主体已经落手（MANIFEST），"在动手前先推演一遍"这句话就不再有意义。

    三种情形，返回值刻意不同：

    * **没有在场运行时**（直接调 OpenClawd、ambient 自发注意力回路、测试裸跑）
      → ``True``。此时根本没有生命周期可闸，判 ``False`` 会把预演在这些路径上
      **静默关掉** —— 那是比不闸门更糟的结果。闸门管的是"相位不对时别推演"，
      不是"没有相位时别推演"。
    * **处在 LIMINAL** → ``True``。
    * **处在 SILENT / MANIFEST** → ``False``，并留 warning。这是闸门真正起作用的
      那一支：审议窗口已经关上了。

    Returns:
        当前是否允许进入沙盘推演。
    """
    session = _current_runtime_session.get()
    if session is None:
        return True  # 没有生命周期可闸 —— 见上面第一种情形
    phase = getattr(getattr(session, "tristate", None), "value", None)
    if phase == "liminal":
        return True
    logger.warning(
        "审议窗口已关闭，跳过沙盘推演 | runtime_session_id=%s tristate=%s "
        "—— 预演只在 LIMINAL 段内成立；若这条频繁出现，说明 advance(MANIFEST) "
        "的触发点早于认知段，需要检查 desktop_presence_runtime 的相位时序",
        getattr(session, "runtime_session_id", "?"),
        phase,
    )
    return False


def commit_to_manifest(reason: str = "") -> bool:
    """宣告审议结束、开始真实落手 —— 由此驱动 LIMINAL → MANIFEST。

    Args:
        reason: 触发原因（如 ``"react_loop"``），进日志便于回溯。

    Returns:
        ``True`` 表示信号送达且相位确实前进了。

    为什么相位要由认知层驱动
    ------------------------
    LIMINAL→MANIFEST 的那条界线是**认知层才知道**的事实：审议（意图解析、沙盘推演、
    消息装配）结束、真实工具执行开始。在场运行时那一层看不见它。

    此前流式路径靠"第一个 token 流出"这个**代理信号**近似它——那是个好信号，但
    只有流式才有。非流式路径没有代理信号，于是保守地在派发**之前**就进了 MANIFEST，
    结果同一段认知工作在流式下算 LIMINAL、在非流式下算 MANIFEST，**审议窗口在
    非流式路径上宽度为零**。相位闸门在那种路径上会把预演整个关掉。

    现在改成认知层显式宣告，两条路径的窗口一致。流式的首 token 钩子保留——它与
    本信号驱动的是同一个幂等入口（``_enter_manifest`` 自带
    ``if tristate is not LIMINAL: return`` 守卫），谁先到算谁。

    信号没送达也不会坏事：``handle_request`` 的 finally 里有兜底，
    ``LIMINAL → MANIFEST → SILENT`` 的三段轨迹对下游（审计、跨设备同步）始终完整。
    """
    session = _current_runtime_session.get()
    if session is None:
        return False
    hook = getattr(session, "manifest_hook", None)
    if hook is None:
        return False
    try:
        hook()
        logger.debug(
            "审议结束，进入落手 | runtime_session_id=%s reason=%s",
            getattr(session, "runtime_session_id", "?"),
            reason,
        )
        return getattr(getattr(session, "tristate", None), "value", None) == "manifest"
    except Exception:  # noqa: BLE001 — 相位推进失败不该拖垮请求，finally 有兜底
        logger.debug("commit_to_manifest failed (non-fatal)", exc_info=True)
        return False
