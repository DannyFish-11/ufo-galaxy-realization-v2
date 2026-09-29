"""core/periodic_maintenance.py — 只在被读到时才发现过期的状态，按时清掉。

一批注册表各自写好了「清扫过期项」的方法，整个进程里却没有一个循环去调它们：

- 超时的待办信封永远挂着（``TaskEnvelopeLifecycleRegistry.cancel_timed_out``）；
- 待决项只在被读到时才判超时（``PendingDecisionRegistry.sweep_expired``）；
- 任务记忆热区的 TTL 配了、从不执行（``TaskMemory.evict_expired``）；
- 改安全策略文件、模型路由策略文件要重启才生效（``reload_security_policy`` / ``reload_policy``）；
- 委托流四类对象从不落盘，于是重启恢复读到的永远是空（``persist_all``）；
- 混合执行的终态记录只增不减。

每一处单看都「有方法」，合起来是没人按时去做。这里就是那个按时去做的：一个 asyncio 循环，
按各项自己的周期调已登记的清扫。每项独立吞异常，一项出错不连累其它项；每项最近一次的结果
与错误留在 :meth:`PeriodicMaintenance.status`（``GET /api/v1/observability/maintenance``）。

- core 自己的清扫由 :func:`register_core_sweeps` 登记；
- core 不能 import 的上层（网关）经 :func:`register_sweep` 把自己的清扫挂进来。

``core.startup.bootstrap_subsystems`` 启动它，``shutdown_subsystems`` 停它（停之前再落一次委托流）。
清扫在事件循环里同步执行 —— 被清的注册表大多不是线程安全的，挪到线程里反而会和写入方抢。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_TICK_S = 5.0


def _summarize(value: Any) -> Any:
    if isinstance(value, (list, tuple, set, frozenset)):
        return len(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value if not isinstance(value, str) else value[:80]
    if isinstance(value, dict):
        return {str(k): _summarize(v) for k, v in list(value.items())[:8]}
    return str(value)[:80]


@dataclass
class _Sweep:
    name: str
    fn: Callable[[], Any]
    every_s: float
    next_at: float
    final: bool = False
    runs: int = 0
    errors: int = 0
    last_outcome: Any = None
    last_error: str = ""
    last_run_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "every_s": self.every_s,
            "runs": self.runs,
            "errors": self.errors,
            "last_outcome": self.last_outcome,
            "last_error": self.last_error,
            "last_run_at": self.last_run_at,
        }


@dataclass
class PeriodicMaintenance:
    tick_s: float = _TICK_S
    _sweeps: Dict[str, _Sweep] = field(default_factory=dict)
    _task: Optional["asyncio.Task"] = None

    def register(
        self, name: str, fn: Callable[[], Any], *, every_s: float, run_first: bool = False, final: bool = False
    ) -> None:
        """登记一项清扫；同名覆盖。

        ``run_first``：循环起来后先跑一次（否则等满一个周期）；``final``：停的时候再跑最后一次。
        """
        now = time.monotonic()
        self._sweeps[name] = _Sweep(
            name=name, fn=fn, every_s=float(every_s), next_at=now if run_first else now + every_s, final=final
        )

    async def run_due(self, now: Optional[float] = None) -> List[str]:
        """跑到点的清扫，返回这次跑了哪些。"""
        now = time.monotonic() if now is None else now
        due = [s for s in list(self._sweeps.values()) if now >= s.next_at]
        for sweep in due:
            sweep.next_at = now + sweep.every_s
            await self._run(sweep)
        return [s.name for s in due]

    @staticmethod
    async def _run(sweep: _Sweep) -> None:
        sweep.runs += 1
        sweep.last_run_at = time.time()
        try:
            outcome = sweep.fn()
            if inspect.isawaitable(outcome):
                outcome = await outcome
            sweep.last_outcome = _summarize(outcome)
            sweep.last_error = ""
        except Exception as exc:  # noqa: BLE001 — 一项出错不连累其它项
            sweep.errors += 1
            sweep.last_error = f"{type(exc).__name__}: {exc}"[:200]
            logger.debug("periodic sweep %s failed: %s", sweep.name, exc)

    async def _loop(self) -> None:
        while True:
            await self.run_due()
            await asyncio.sleep(self.tick_s)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> bool:
        if self.running:
            return False
        self._task = asyncio.get_running_loop().create_task(self._loop(), name="galaxy_periodic_maintenance")
        return True

    async def stop(self) -> None:
        """停循环，再把标了 ``final`` 的清扫各跑最后一次（比如关机前把委托流落盘）。"""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for sweep in [s for s in list(self._sweeps.values()) if s.final]:
            await self._run(sweep)

    def status(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "tick_s": self.tick_s,
            "sweeps": [s.to_dict() for s in sorted(self._sweeps.values(), key=lambda s: s.name)],
        }


_maintenance: Optional[PeriodicMaintenance] = None


def get_periodic_maintenance() -> PeriodicMaintenance:
    global _maintenance
    if _maintenance is None:
        _maintenance = PeriodicMaintenance()
    return _maintenance


def register_sweep(name: str, fn: Callable[[], Any], *, every_s: float, run_first: bool = False) -> None:
    """上层（网关等 core 不能 import 的层）把自己的清扫挂进同一个循环。"""
    get_periodic_maintenance().register(name, fn, every_s=every_s, run_first=run_first)


# ---------------------------------------------------------------------------
# core 自己的清扫
# ---------------------------------------------------------------------------


# 刻意**不**在这里的：按心跳年龄判离线 / 过期的三项（NodeFabricRegistry.mark_offline_if_stale、
# expire_stale_capabilities、CapabilityAssimilationLayer.mark_stale_if_expired）。启动器拉起的节点、
# 本机的 MCP / 技能提供方，存活由进程与 HTTP 健康判，**从不**往这两张表发心跳 —— 按心跳年龄扫，
# 60 秒后它们会被全部判离线、5 分钟后节点能力被全部清掉，路由随之失效。它们要等有了真实的心跳来源
# 才能按时扫（见 config/unwired_placement.json 里的说明）。

# 超时信封留一点余量再收：等待方（gateway_nats_adapter 的 wait_for）用的是同一个超时，
# 让它先按 TimeoutError 收场；这里只收没人再等的残留记录，免得把等待方的 future 抢先取消掉。
_ENVELOPE_TIMEOUT_GRACE_S = 5.0


def _envelopes_timed_out() -> List[str]:
    from core.task_envelope_lifecycle_registry import get_lifecycle_registry

    return get_lifecycle_registry().cancel_timed_out(grace_s=_ENVELOPE_TIMEOUT_GRACE_S)


def _pending_decisions_expired() -> List[str]:
    from core.interaction.pending_decision_registry import get_pending_decision_registry

    return get_pending_decision_registry().sweep_expired()


def _task_memory_expired() -> int:
    import core.task_memory as task_memory

    # 只清已经在用的那一个；没人建过就不替它建（建的时候要读盘、定数据目录）
    memory = task_memory._instance
    return memory.evict_expired() if memory is not None else 0


_HYBRID_TERMINAL_KEEP = 256
_HYBRID_DISK_RETENTION_S = 7 * 24 * 3600.0


def _hybrid_executions() -> Dict[str, int]:
    from core.hybrid_orchestration_continuity import get_continuity_registry, get_hybrid_persistence_store

    registry = get_continuity_registry()
    cleared = registry.clear_terminal() if len(registry.list_terminal()) > _HYBRID_TERMINAL_KEEP else 0
    pruned = get_hybrid_persistence_store().prune_settled(older_than_s=_HYBRID_DISK_RETENTION_S)
    return {"cleared_in_memory": cleared, "pruned_on_disk": pruned}


def _security_policy_hot_reload() -> bool:
    from core.security_policy_loader import check_policy_file_changed, get_security_policy, reload_security_policy

    # 只重载已经加载过的那份；从没人加载过就不替它加载（openclawd 初始化时才加载）
    if get_security_policy() is None or not check_policy_file_changed():
        return False
    reload_security_policy()
    return True


class LLMRoutingPolicyHotReload:
    """``config/llm_routing_policy.yaml`` 改了就让在用的模型路由重读（此前只在构造时读一次，改了要重启）。

    第一次只记下当时的修改时间，不重载；只对已经建起来的路由单例生效，没人建过就不替它建。
    """

    def __init__(self) -> None:
        self._seen_mtime: Optional[float] = None

    def __call__(self) -> bool:
        import os

        from core.unified import llm_router

        try:
            mtime = os.path.getmtime(llm_router._POLICY_PATH)
        except OSError:
            return False
        previous, self._seen_mtime = self._seen_mtime, mtime
        router = llm_router.UnifiedLLMRouter._instance
        if previous is None or mtime <= previous or router is None:
            return False
        router.reload_policy()
        return True


class DelegatedFlowCheckpoint:
    """把委托流四类对象定期落盘，恢复协调器重启后读的正是这份快照。

    一类对象在本进程里还从没出现过时不写它 —— 否则重启后第一次落盘就拿空表盖掉了上一个
    进程留下、恢复协调器还没来得及读的快照。出现过之后照实写（包括又清空了的情况）。
    """

    def __init__(self) -> None:
        self._seen: Set[str] = set()

    def __call__(self) -> Dict[str, bool]:
        from core.android_runtime_dispatch_binding import get_dispatch_binding_runtime
        from core.attached_runtime_session_registry import get_session_registry
        from core.delegated_flow_entity import get_delegated_flow_entity_runtime
        from core.delegated_flow_persistence import get_delegated_flow_persistence_bundle
        from core.delegated_runtime_handoff_contract import get_handoff_contract_runtime

        current = {
            "session": get_session_registry().list_all(),
            "contract": get_handoff_contract_runtime().list_all(),
            "binding": get_dispatch_binding_runtime().list_all(),
            "flow_entity": get_delegated_flow_entity_runtime().list_all(),
        }
        self._seen.update(name for name, objects in current.items() if objects)
        if not self._seen:
            return {}
        return get_delegated_flow_persistence_bundle().persist_all(
            sessions=current["session"],
            contracts=current["contract"],
            bindings=current["binding"],
            flow_entities=current["flow_entity"],
            categories=sorted(self._seen),
        )


def register_core_sweeps(maintenance: Optional[PeriodicMaintenance] = None) -> PeriodicMaintenance:
    """登记 core 自己的各项清扫（周期按各注册表自己的时间尺度定）。"""
    m = maintenance or get_periodic_maintenance()
    m.register("task_envelopes.cancel_timed_out", _envelopes_timed_out, every_s=10)
    m.register("pending_decisions.sweep_expired", _pending_decisions_expired, every_s=15)
    m.register("task_memory.evict_expired", _task_memory_expired, every_s=600)
    m.register("hybrid_executions.prune", _hybrid_executions, every_s=600)
    m.register("security_policy.hot_reload", _security_policy_hot_reload, every_s=15)
    m.register("llm_routing_policy.hot_reload", LLMRoutingPolicyHotReload(), every_s=15, run_first=True)
    m.register("delegated_flows.checkpoint", DelegatedFlowCheckpoint(), every_s=120, final=True)
    return m


__all__ = [
    "DelegatedFlowCheckpoint",
    "LLMRoutingPolicyHotReload",
    "PeriodicMaintenance",
    "get_periodic_maintenance",
    "register_core_sweeps",
    "register_sweep",
]
