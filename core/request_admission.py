"""core.request_admission — 请求层准入：唯一的一道，三条轴各守一条

为什么需要这一层
================
本仓在「谁能跑、能跑几个」这件事上装了三套东西，而请求路径上真正生效的是最弱的
那一套：

===============================  ==========================  ====================
组件                              管的是                       实况
===============================  ==========================  ====================
``SessionExecutionLane``          **序** —— 同一会话不并发      ✅ 唯一在跑的
``ConcurrencyManager``            **量** —— 全局/分类并发上限   ❌ 启动了零流量
``GlobalArbiter``                 **序位** —— 优先级/配额/抢占  ❌ 从不可达
===============================  ==========================  ====================

``ConcurrencyManager`` 在 ``core/startup.py`` 里被 ``start()`` / ``stop()``、被诊断
接口读状态，但 ``acquire_slot`` / ``run_with_concurrency`` / ``run_with_lock`` /
``ResourceQueue.request`` **全仓没有任何调用方**。``CONCURRENCY_GLOBAL_MAX`` 读进去，
作用在一个没人用的限流器上。

于是请求层的实况是：**N 个并发会话 = N 条并发请求流水线，每条都在跑 LLM 与工具执行，
没有任何全局上限。**

为什么是「挑一个」而不是「三个都融」
====================================
先说清楚，因为这是刻意的：``ConcurrencyLimiter`` 与 ``GlobalArbiter`` 在请求层
**不是互补的，是冗余的** —— 二者都只在「同时跑几个」这一个轴上使用，把两个都接上
等于给同一份资源开两个计数器，而两个计数器迟早会不一致（其中一个被绕过、或者一边
release 失败），到时候症状是"明明没满却拒绝"或"明明满了还放行"，而两边各自看都对。

所以量与序位合并由 ``GlobalArbiter`` 一家管（它本来就同时具备全局上限、按来源配额
与抢占，且是原子判定）。``SessionExecutionLane`` 留着不动 —— 它守的是**序**，是正确性
属性（同一会话的请求必须串行），跟"跑几个"是两回事，不构成第二个权威。

抢占为什么需要这一层，而不是直接用仲裁器
========================================
``GlobalArbiter.admit()`` 的抢占**只是记账**：它把受害者从 ``_running`` 里删掉，
然后就没有了。受害者那个协程照跑不误，只是它的槽位被人顶了、它自己后面的
``release()`` 会返回 False。也就是说单靠仲裁器，抢占既不省资源也不产生任何可观测
后果 —— 净效果是把并发上限**悄悄突破**一个。

真正的抢占需要一条取消通道。本模块登记每个在飞任务的 ``asyncio.Event``，被抢占时
点亮它；被抢占方在自己的等待点上抛 :class:`ArbiterPreemptedError`（AR_001）。

默认取值
========
* **全局上限 16**（``GlobalArbiter`` 自己的默认）。刻意**不**沿用
  ``CONCURRENCY_GLOBAL_MAX``（默认 50）—— 那个数是给通用槽位限流器定的，而这里一个
  槽位是**一整条请求流水线**（LLM 调用 + 工具执行）。两者不是同一种资源，把 50 搬
  过来是拿一个从未生效过的数字当真闸。
* **按来源配额 4**（仲裁器默认）。防的是单一来源把全局槽位吃光。
* **可被抢占 = 由来源决定**。用户发起的请求 ``preemptable=False`` —— 中途被杀掉对
  用户是不可解释的；自发注意力（``source="ambient"``）等后台自发行为
  ``preemptable=True``，并给更低的优先级，让它在排序上也先让路。这是本模块唯一
  「凭判断定」的取值，其余都取模块自己的默认。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional, Set

logger = logging.getLogger("Galaxy.RequestAdmission")

__all__ = [
    "AMBIENT_ORIGINS",
    "mark_uninterruptible",
    "PRIORITY_AMBIENT",
    "PRIORITY_USER",
    "admission_snapshot",
    "admit_request",
    "origin_is_preemptable",
    "priority_for_origin",
]

#: 自发行为的来源标记。这些不是用户在等的请求，可以被抢占、优先级更低。
#: ``desktop_presence_runtime.handle_request`` 的 ``source`` 参数用的就是这套词。
AMBIENT_ORIGINS: frozenset = frozenset({"ambient"})

PRIORITY_USER: int = 10
PRIORITY_AMBIENT: int = 1

#: 在飞任务的取消信号。抢占时点亮对应的 Event —— 仲裁器自己只会把受害者从账上划掉，
#: 不会让它停下来。
_preemption_signals: Dict[str, asyncio.Event] = {}
_signals_lock = asyncio.Lock()


def origin_is_preemptable(origin: str) -> bool:
    """自发行为可被抢占；用户发起的请求不可。

    这条判断是本模块的核心取值：把一个用户正在等的请求中途杀掉，对用户是不可解释的
    ——他看到的是「它突然不说话了」。而后台自发注意力被让路，用户根本感知不到。
    """
    return str(origin or "").strip().lower() in AMBIENT_ORIGINS


def priority_for_origin(origin: str) -> int:
    """自发行为的优先级低于用户请求 —— 让它在排序上也先让路，而不只是可被抢。"""
    return PRIORITY_AMBIENT if origin_is_preemptable(origin) else PRIORITY_USER


async def _signal_preemption(task_id: str) -> None:
    """点亮受害者的取消信号。取不到就只留 warning —— 那说明它已经跑完了。"""
    async with _signals_lock:
        event = _preemption_signals.get(task_id)
    if event is None:
        logger.warning(
            "抢占目标 %s 没有登记取消信号：它的槽位已被划走，但它不会停下来 —— " "并发上限在这一拍被悄悄突破了一个",
            task_id,
        )
        return
    event.set()
    logger.info("已向被抢占任务 %s 发出取消信号", task_id)


@asynccontextmanager
async def admit_request(
    task_id: str,
    *,
    origin: str = "unknown",
    metadata: Optional[Dict[str, Any]] = None,
) -> AsyncIterator[Any]:
    """请求层准入。被拒绝时抛 ``ArbiterQuotaError`` / ``ArbiterNoSlotError``。

    Args:
        task_id: 本次请求的唯一标识（用 ``runtime_session_id``）。
        origin: 来源（``"ambient"`` / ``"desktop"`` / ``"api"`` …）。决定优先级与
            是否可被抢占，见模块头。
        metadata: 附带上下文，进仲裁器的决策日志。

    Yields:
        本次请求的抢占信号 ``asyncio.Event``。调用方可以在自己的等待点上查它 ——
        ``event.is_set()`` 为真表示这次请求已被更高优先级的请求顶掉，应当尽快收手。

    Raises:
        ArbiterQuotaError: AR_002，同来源在飞数超配额。
        ArbiterNoSlotError: AR_003，全局已满且没有可抢占的目标。

    仲裁器不可用时**放行**并留 warning：准入层挂掉不该让整个系统停摆，那比没有上限
    更糟。降级是响的，不是静默的。
    """
    try:
        from core.orchestration.global_arbiter import get_global_arbiter
    except Exception as exc:  # noqa: BLE001
        logger.warning("准入层不可用，本次请求不受全局上限约束: %s", exc)
        yield asyncio.Event()
        return

    arbiter = get_global_arbiter()
    decision = arbiter.admit(
        task_id,
        priority=priority_for_origin(origin),
        origin=origin,
        preemptable=origin_is_preemptable(origin),
        metadata=metadata or {},
    )

    if not decision.admitted:
        from core.orchestration.global_arbiter import ArbiterNoSlotError, ArbiterQuotaError

        arbiter_stats = arbiter.stats()
        logger.info(
            "请求被准入层拒绝 | task=%s origin=%s outcome=%s reason=%s running=%s",
            task_id,
            origin,
            decision.outcome.value,
            decision.reason,
            arbiter_stats.get("running_count"),
        )
        if decision.outcome.value == "rejected_quota":
            raise ArbiterQuotaError(decision.reason)
        raise ArbiterNoSlotError(decision.reason)

    # 抢占是**记账 + 取消**两件事。仲裁器只做了前一半：它把受害者从 _running 划掉，
    # 受害者那个协程照跑不误。不补后一半的话，抢占的净效果是把并发上限悄悄突破一个。
    if decision.preempted_task_id:
        await _signal_preemption(decision.preempted_task_id)

    event = asyncio.Event()
    async with _signals_lock:
        _preemption_signals[task_id] = event
    try:
        yield event
    finally:
        async with _signals_lock:
            _preemption_signals.pop(task_id, None)
        arbiter.release(task_id)


def mark_uninterruptible(task_id: str) -> bool:
    """宣告本次请求已越过最后一道等待、开始真正干活，此后不可被抢占。

    为什么必须有这一步
    ------------------
    抢占在仲裁器那一侧只是**记账**：把受害者从 ``_running`` 划掉、让新任务顶上。它
    不会让受害者停下来，而在本仓的真实路径上受害者往往是被**内联 await** 的（自发
    注意力循环就是这样），从外面 cancel 等于把整条循环一起杀掉 —— 而且
    ``CancelledError`` 继承 ``BaseException``，调用点的 ``except Exception`` 也接不住。

    所以「可抢占」只能限定在**尚未开工**的那一段。实测：不做这件事时，占满之后来的
    用户请求会"抢占成功"，而被抢的 ambient 请求照跑到底、一个 AR_001 都发不出去 ——
    净效果就是并发悄悄超出上限一个，正是抢占本来要避免的事。

    代价是诚实的：当在飞的全是已开工的任务时，新来的高优先级请求会拿到 AR_003 而不是
    "抢占成功"。系统确实被不可中断的工作占满了，如实说比悄悄超限好。
    """
    try:
        from core.orchestration.global_arbiter import get_global_arbiter

        return bool(get_global_arbiter().mark_non_preemptable(task_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("标记不可抢占失败，本次请求在开工后仍可能被划走槽位: %s", exc)
        return False


def admission_snapshot() -> Dict[str, Any]:
    """准入层的可观测快照，供诊断接口取用。"""
    try:
        from core.orchestration.global_arbiter import get_global_arbiter

        arbiter = get_global_arbiter()
        snap: Dict[str, Any] = dict(arbiter.stats())
        snap["running_tasks"] = arbiter.list_running()
        snap["recent_decisions"] = arbiter.recent_decisions(20)  # 已是 dict 列表
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": str(exc)}
    snap["available"] = True
    snap["pending_preemption_signals"] = sorted(_preemption_signals)
    return snap


def _known_task_ids() -> Set[str]:
    """测试用：当前登记了取消信号的任务。"""
    return set(_preemption_signals)
