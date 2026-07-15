"""core/worker_runtime.py — NATS worker 消费循环(补上缺失的执行端)
=====================================================================

勘察发现:``nats_bus.subscribe_task_dispatches`` 全仓**零调用** —— 有派发端、
有主脑订阅结果,却**没有任何 worker 真正接收并执行被派发的任务**。跨设备执行
此前只能靠网关转发到 WS 直连设备,不是 NATS worker 网格。本模块补上这条:

  worker 订阅 ``galaxy.tasks.dispatch.{worker_id}``
    → 收到派发(含 node_id/action/params/ui_graph)
    → 经**规范执行器** core.node_invocation.invoke_node 本机执行(结构优先:带 ui_graph)
    → 把结果(含动作后界面态)publish_task_result 回主脑 → 闭环

**opt-in**:仅当 GALAXY_MASTER_BRAIN_ENABLED 打开(多设备总开关)时由启动序列拉起;
默认关 = 单机,不启用、零行为变化。执行与回传逻辑抽成 :meth:`execute_dispatch`
纯方法(注入 bus 即可单测,不触网)。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.WorkerRuntime")


def worker_enabled() -> bool:
    """worker 消费循环是否启用(跟随多设备总开关)。"""
    return str(os.getenv("GALAXY_MASTER_BRAIN_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")


def default_worker_id() -> str:
    wid = os.getenv("GALAXY_WORKER_ID", "").strip()
    if wid:
        return wid
    return f"worker-{uuid.uuid4().hex[:8]}"


class WorkerRuntime:
    """一个 NATS worker:订阅派发 → 规范执行器执行 → 回传结果。"""

    def __init__(self, worker_id: Optional[str] = None, nats_bus: Any = None):
        self.worker_id = worker_id or default_worker_id()
        self._nats = nats_bus
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def execute_dispatch(self, msg: Dict[str, Any]) -> "Any":
        """执行一条派发,返回 TaskResultMsg(不发送 —— 便于单测)。

        派发 dict 形如 {task_id, node_id, action, params, ui_graph, trace_id}。
        node_id 缺省从 params.target_node 或 action 前缀推断失败则原样;执行经
        invoke_node(结构优先:透传 ui_graph)。"""
        from core.node_invocation import InvocationSource, invoke_node
        from core.schemas.aip_v3 import TaskResultMsg

        task_id = str(msg.get("task_id") or msg.get("request_id") or "")
        trace_id = str(msg.get("trace_id") or "")
        node_id = str(msg.get("node_id") or (msg.get("params") or {}).get("node_id") or "")
        action = str(msg.get("action") or "")
        params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
        ui_graph = msg.get("ui_graph")

        if not node_id or not action:
            return TaskResultMsg(
                device_id=self.worker_id,
                task_id=task_id,
                trace_id=trace_id,
                status="failed",
                error="worker: 派发缺 node_id/action",
            )

        # 派发侧幂等守卫(默认开):NATS 是 at-least-once,ack 在回调之后(nats_bus
        # ._subscribe),worker 执行副作用后若崩在 ack 前 → JetStream 重投 → 同一动作
        # (安卓点按/桌面控制)被执行第二次。这里在【执行副作用之前】用可持久化的
        # 键(idempotency_key/task_id)判重:已派发过就直接短路返回"去重"结果、绝不
        # 二次执行;否则悲观地先记键、再执行,只有执行器抛异常(没干净跑成)才回滚
        # 键以便重投重试。GALAXY_DISPATCH_IDEMPOTENCY=0 可关。见
        # core.durable_dispatch_idempotency 的完整语义说明。
        from core.durable_dispatch_idempotency import (
            already_dispatched,
            dispatch_idempotency_enabled,
            dispatch_key_for,
            mark_dispatched,
            unmark_dispatched,
        )

        _idem_on = dispatch_idempotency_enabled()
        _idem_key = dispatch_key_for(msg) if _idem_on else ""
        if _idem_key and already_dispatched(_idem_key):
            logger.info("worker: 派发已执行过(幂等去重,不二次执行) task=%s key=%s", task_id, _idem_key)
            return TaskResultMsg(
                device_id=self.worker_id,
                task_id=task_id,
                trace_id=trace_id,
                status="completed",
                result={"deduplicated": True, "reason": "dispatch already executed (idempotency guard)"},
            )
        if _idem_key:
            mark_dispatched(_idem_key)  # 悲观:执行前先记,重投永不二次触发副作用

        # 观测(未激活时零成本 no-op):给 worker 执行开一个 span,把 bespoke trace_id 作为
        # 属性带上,使跨设备派发在 OTel 后端可关联。默认无条件开(GALAXY_OTEL_ENABLED=0 才关)。
        from core.otel_tracing import record_exception, start_span

        with start_span(
            "galaxy.worker.execute_dispatch",
            {
                "galaxy.trace_id": trace_id,
                "galaxy.task_id": task_id,
                "galaxy.node_id": node_id,
                "galaxy.action": action,
                "galaxy.worker_id": self.worker_id,
            },
        ) as _span:
            try:
                result = await invoke_node(
                    node_id,
                    action,
                    params,
                    invocation_source=InvocationSource.UNKNOWN,
                    task_id=task_id,
                    trace_id=trace_id,
                    ui_graph=ui_graph,
                )
                return TaskResultMsg(
                    device_id=self.worker_id,
                    task_id=task_id,
                    trace_id=trace_id,
                    status="completed" if getattr(result, "success", False) else "failed",
                    result=(
                        getattr(result, "result", None)
                        if isinstance(getattr(result, "result", None), dict)
                        else {"value": getattr(result, "result", None)}
                    ),
                    error=getattr(result, "error", "") or "",
                    duration_ms=int(getattr(result, "duration_ms", 0)),
                )
            except Exception as exc:  # noqa: BLE001 — 单个任务失败不拖垮 worker
                # 执行器抛异常 = 副作用没干净跑成 → 回滚幂等键,允许重投重试(不留"标了
                # 已做、其实没做"的空洞)。节点【返回】失败(非抛异常)则视为已尝试、保留键。
                if _idem_key:
                    unmark_dispatched(_idem_key)
                record_exception(_span, exc)
                logger.warning("worker 执行派发失败 task=%s: %s", task_id, exc)
                return TaskResultMsg(
                    device_id=self.worker_id,
                    task_id=task_id,
                    trace_id=trace_id,
                    status="failed",
                    error=f"worker 执行异常: {exc}",
                )

    async def _on_dispatch(self, msg: Dict[str, Any]) -> None:
        """NATS 回调:执行派发并把结果回传主脑。"""
        result = await self.execute_dispatch(msg if isinstance(msg, dict) else {})
        try:
            await self._get_bus().publish_task_result(result)
        except Exception as exc:  # noqa: BLE001
            logger.warning("worker 回传结果失败: %s", exc)

    def _get_bus(self) -> Any:
        if self._nats is None:
            from core.nats_bus import get_nats_bus

            self._nats = get_nats_bus()
        return self._nats

    async def start(self) -> Dict[str, Any]:
        """连接 NATS、注册 worker、订阅派发。best-effort:不可用则返回 not-started。"""
        if self._running:
            return {"started": True, "already": True, "worker_id": self.worker_id}
        bus = self._get_bus()
        try:
            if not bus.is_connected():
                await bus.connect()
            if not bus.is_connected():
                return {"started": False, "reason": "nats_unavailable"}
            # 注册 worker(best-effort)
            try:
                from core.schemas.contracts import WorkerRegistrationModel

                await bus.publish_worker_registration(
                    WorkerRegistrationModel(worker_id=self.worker_id, worker_version="v2")
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("worker 注册跳过(非致命): %s", exc)
            await bus.subscribe_task_dispatches(self.worker_id, self._on_dispatch)
            self._running = True
            logger.info(
                "WorkerRuntime 启动 worker_id=%s(订阅 galaxy.tasks.dispatch.%s)", self.worker_id, self.worker_id
            )
            return {"started": True, "worker_id": self.worker_id}
        except Exception as exc:  # noqa: BLE001
            logger.warning("WorkerRuntime 启动失败: %s", exc)
            return {"started": False, "reason": str(exc)}

    async def stop(self) -> None:
        self._running = False


_runtime: Optional[WorkerRuntime] = None


def get_worker_runtime() -> WorkerRuntime:
    global _runtime
    if _runtime is None:
        _runtime = WorkerRuntime()
    return _runtime


def reset_worker_runtime() -> None:
    """测试用。"""
    global _runtime
    _runtime = None


async def start_worker_runtime() -> Dict[str, Any]:
    """opt-in 启动入口(启动序列在多设备总开关开时调用)。"""
    if not worker_enabled():
        return {"started": False, "reason": "disabled"}
    return await get_worker_runtime().start()
