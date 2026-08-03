"""
任务编排器 (Orchestrator)

核心功能:
1. 接收用户任务请求
2. 分解任务为子任务
3. 分配任务到合适的设备
4. 协调多设备执行
5. 汇总执行结果

内部唯一任务格式：TaskEnvelope（PR-2）。
外部入口（user_request/AIP）进入后立即转换为 TaskEnvelope。

PR-507: Canonical task front-loading — submit_task() now calls
adapt_to_canonical_task() before constructing a TaskEnvelope so that
CanonicalTask is the primary ontology object.  TaskEnvelope is projected
from the canonical task via project_to_task_envelope().
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from ..handlers import DeviceManager, MessageHandler
from ..protocol import AIPMessage, Command, CommandResult, ResultStatus, TaskStatus, create_task_message
from ..transport import WebSocketManager

logger = logging.getLogger(__name__)

# PR-507: Canonical task front-loading — TaskOrchestrator.submit_task() now
# creates a CanonicalTask via adapt_to_canonical_task() before constructing a
# TaskEnvelope.  TaskEnvelope is projected from the canonical task so that
# CanonicalTask is always the primary ontology object in this ingress path.
CANONICAL_TASK_ORCHESTRATOR_FRONT_LOADED: str = (
    "CANONICAL_TASK_ORCHESTRATOR_V1: "
    "galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator.submit_task() "
    "calls adapt_to_canonical_task() before TaskEnvelope construction."
)

# PR-513 / GAP-512-006: TaskOrchestrator now emits audit_task_dispatched after
# successful orchestration handoff so audit lineage is complete for
# gateway-orchestrated tasks.
TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED: str = (
    "TASK_ORCHESTRATOR_AUDIT_DISPATCH_V1: "
    "galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator._process_task() "
    "emits AuditEventSemantics.audit_task_dispatched after device selection and "
    "task dispatch so gateway-orchestrated tasks appear in the audit trail "
    "(GAP-512-006)."
)


class TaskPriority(Enum):
    """任务优先级"""

    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


class Task:
    """任务定义"""

    def __init__(
        self, task_id: str, user_request: str, priority: TaskPriority = TaskPriority.NORMAL, timeout: int = 300
    ):
        self.task_id = task_id
        self.user_request = user_request
        self.priority = priority
        self.timeout = timeout
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now(timezone.utc)
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.assigned_device: Optional[str] = None
        self.commands: List[Command] = []
        self.results: List[CommandResult] = []
        self.error: Optional[str] = None
        self.metadata: Dict[str, Any] = {}


class TaskOrchestrator:
    """任务编排器 — Legacy gateway-level task dispatch layer.

    .. deprecated:: PR-7 (demoted), PR-S5 (clarified)
        ``TaskOrchestrator`` is a **legacy gateway-level transport layer**.
        The canonical cross-device execution chain is:

        OpenClawd → CommandRouter → TaskEnvelope → TaskGraph (core.task_graph)
        → DeviceRouter.route_task → Worker/Device → ResultEnvelope → OpenClawd feedback

        ``TaskOrchestrator`` is retained only as a compatibility fallback for
        existing integrations (e.g. ``galaxy_gateway.app`` startup).
        It must not be invoked as a new primary cross-device entrypoint.

        Preferred replacement:
            ``core.e2e_orchestrator.process_user_input()``
            or ``galaxy_gateway.device_router.DeviceRouter.route_task()``

        See :mod:`core.orchestration_authority.legacy_paths` for the registry entry.
    """

    def __init__(
        self, device_manager: DeviceManager, message_handler: MessageHandler, websocket_manager: WebSocketManager
    ):
        self.device_manager = device_manager
        self.message_handler = message_handler
        self.websocket_manager = websocket_manager

        self.tasks: Dict[str, Task] = {}
        # 原为无界 asyncio.Queue() + 单 worker 串行。换 AsyncTaskQueue：有界队列 +
        # 并发 worker 池；满时 reject_new 如实回「系统忙」。per-device 计数锁本就支持并发。
        self._pool_max_size = int(os.environ.get("GALAXY_TASK_QUEUE_MAX", "500"))
        self._pool_concurrency = int(os.environ.get("GALAXY_TASK_CONCURRENCY", "4"))
        self._task_pool: Optional[Any] = None
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        # Round-robin index for distributing tasks across connected devices.
        self._device_rr_index: int = -1
        # PR-CONCURRENT-DEVICE-CONTROL: per-device task count with lock
        self._device_task_counts: Dict[str, int] = {}
        self._device_count_lock = asyncio.Lock()
        # PR-2: TaskEnvelope registry — each submitted task is wrapped in an
        # envelope immediately so all internal processing uses the unified format.
        self._task_envelopes: Dict[str, Any] = {}

        # PR-S5: emit legacy guardrail — TaskOrchestrator is a compatibility
        # transport layer only.  The canonical dispatch chain is:
        # OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter.route_task.
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail

            emit_legacy_guardrail(
                caller="galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator",
            )
        except Exception:
            pass

    async def start(self):
        """启动编排器"""
        self._running = True
        from core.queueing.async_queue import AsyncTaskQueue

        self._task_pool = AsyncTaskQueue(
            max_queue_size=self._pool_max_size,
            max_concurrent=self._pool_concurrency,
            shed_strategy="reject_new",
        )
        await self._task_pool.start()
        logger.info(
            "Task Orchestrator started (pool: max_queue=%d, concurrency=%d)",
            self._pool_max_size,
            self._pool_concurrency,
        )

    async def stop(self):
        """停止编排器"""
        self._running = False
        if self._task_pool is not None:
            await self._task_pool.stop()
            self._task_pool = None
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Task Orchestrator stopped")

    async def submit_task(
        self,
        user_request: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        target_device: Optional[str] = None,
        timeout: int = 300,
        openclawd_decision: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """提交新任务（PR-2：立即转换为 TaskEnvelope，内部唯一任务格式）。

        PR-507: CanonicalTask is now front-loaded — adapt_to_canonical_task()
        is called first so that CanonicalTask is the primary ontology object.
        TaskEnvelope is then projected from canonical task state.

        PR-2 constraint: The TaskOrchestrator is an **orchestration/transport**
        component.  It schedules and dispatches the plan it receives; it must
        NOT re-interpret the user request, re-score plans, or produce a new
        primary decision.

        Args:
            user_request:       Natural-language request string (forwarded,
                                not re-evaluated here).
            priority:           Task queue priority.
            target_device:      Optional explicit device assignment.
            timeout:            Task timeout in seconds.
            openclawd_decision: Optional dict containing the pre-formed
                                decision from OpenClawd (e.g. intent, model
                                used, trace_id).  When present it is stored in
                                the task envelope's metadata so the full trace
                                remains auditable.
        """
        # PR-507: Front-load CanonicalTask creation — establish task ontology
        # before constructing Task or TaskEnvelope objects.
        canonical_task_id: Optional[str] = None
        canonical_trace_id: Optional[str] = None
        try:
            from core.canonical_task import TaskOrigin
            from core.task_adapter import adapt_to_canonical_task

            _canonical = adapt_to_canonical_task(
                {
                    "goal": user_request,
                    "tool_name": "orchestrate",
                    "args": {"user_request": user_request},
                    "targets": [target_device] if target_device else [],
                },
                origin=TaskOrigin.ORCHESTRATOR_TASK,
            )
            canonical_task_id = _canonical.identity.task_id
            canonical_trace_id = _canonical.identity.trace_id
            logger.debug(
                "TaskOrchestrator.submit_task: CanonicalTask front-loaded " "task_id=%s trace_id=%s",
                canonical_task_id,
                canonical_trace_id,
            )
        except Exception as _ct_err:
            logger.debug(
                "TaskOrchestrator.submit_task: CanonicalTask front-load unavailable "
                "(graceful degradation — envelope will be built directly): %s",
                _ct_err,
            )

        task_id = canonical_task_id or str(uuid.uuid4())
        task = Task(task_id=task_id, user_request=user_request, priority=priority, timeout=timeout)

        if target_device:
            task.assigned_device = target_device

        self.tasks[task_id] = task

        # PR-2 / PR-507: wrap the incoming request in a TaskEnvelope.
        # When CanonicalTask was successfully front-loaded, project the
        # envelope from it so TaskEnvelope is a downstream projection.
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope

            _meta: Dict[str, Any] = {
                "priority_label": priority.name if hasattr(priority, "name") else "",
            }
            if openclawd_decision:
                _meta["openclawd_decision"] = openclawd_decision
            if canonical_trace_id:
                _meta["canonical_trace_id"] = canonical_trace_id
            _envelope = _TaskEnvelope(
                task_id=task_id,
                source="task_orchestrator",
                targets=[target_device] if target_device else [],
                tool_name="orchestrate",
                args={"user_request": user_request},
                priority=priority.value if hasattr(priority, "value") else 5,
                timeout=float(timeout),
                metadata=_meta,
            )
            self._task_envelopes[task_id] = _envelope
            logger.debug(
                "TaskOrchestrator.submit_task envelope | task_id=%s trace_id=%s",
                _envelope.task_id,
                _envelope.trace_id,
            )
        except Exception as _env_err:
            logger.debug("TaskOrchestrator: TaskEnvelope construction skipped — %s", _env_err)

        from core.queueing.async_queue import QueueFullError

        try:
            if self._task_pool is None:
                raise RuntimeError("orchestrator not started")
            await self._task_pool.submit(self._process_task, task, timeout=float(timeout), task_id=task_id)
        except QueueFullError as exc:
            # 背压：如实拒绝而不是无限积压。调用方拿到 FAILED + 明确原因。
            task.status = TaskStatus.FAILED
            task.error = f"任务队列已满（背压生效）：{exc}"
            logger.warning("Task rejected by backpressure: %s — %s", task_id, exc)
            return task

        logger.info(f"Task submitted: {task_id} - {user_request[:50]}...")
        return task

    async def _task_worker(self):
        """（已由 AsyncTaskQueue worker 池取代；保留空循环仅为兼容旧引用。）"""
        while self._running and self._task_pool is None:
            await asyncio.sleep(1.0)

    async def _process_task(self, task: Task):
        """处理单个任务（PR-2：通过 TaskEnvelope 追踪生命周期）。

        PR-2 constraint: _process_task is **orchestration-only**.  It selects
        a device and dispatches the task as received.  It must NOT re-evaluate
        the user intent, re-score the plan, or produce a new primary decision.
        """
        logger.info(f"Processing task: {task.task_id}")
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)

        # PR-2: retrieve or construct the envelope for this task.
        envelope = self._task_envelopes.get(task.task_id)
        if envelope is not None:
            # PR-2: log the authority recorded in the envelope so the trace
            # shows that TaskOrchestrator is acting as transport, not decider.
            _oc_decision = (envelope.metadata or {}).get("openclawd_decision")
            logger.debug(
                "TaskOrchestrator._process_task | task_id=%s trace_id=%s request='%.50s' "
                "device=%s openclawd_authority=%s",
                envelope.task_id,
                envelope.trace_id,
                task.user_request,
                task.assigned_device or "unassigned",
                bool(_oc_decision),
            )
            # PR-5 Cap 1: lifecycle created → running
            try:
                from core.task_lifecycle import get_lifecycle_manager

                envelope = get_lifecycle_manager().mark_running(envelope)
                self._task_envelopes[task.task_id] = envelope
            except Exception as _e:
                logger.debug("Orchestrator lifecycle mark_running skipped: %s", _e)

        try:
            # 1. 选择目标设备
            device_id = await self._select_device(task)
            if not device_id:
                task.status = TaskStatus.FAILED
                task.error = "No suitable device available"
                # PR-5 Cap 1: lifecycle → failed
                if envelope is not None:
                    try:
                        from core.task_lifecycle import get_lifecycle_manager

                        get_lifecycle_manager().mark_failed(envelope, error=task.error)
                    except Exception:
                        pass
                return

            task.assigned_device = device_id

            # 2. 分解任务为命令
            commands = await self._decompose_task(task)
            task.commands = commands

            # 3. 发送任务到设备
            await self._send_task_to_device(task)

            # PR-513 / GAP-512-006: Emit audit_task_dispatched after successful
            # orchestration handoff so gateway-orchestrated tasks appear in the
            # canonical audit trail.
            try:
                from core.audit_event_semantics import audit_task_dispatched as _aud_disp

                _envelope_for_audit = self._task_envelopes.get(task.task_id)
                _trace_id_audit = getattr(_envelope_for_audit, "trace_id", None) or ""
                _aud_disp(
                    task.task_id,
                    trace_id=_trace_id_audit,
                    source="task_orchestrator._process_task",
                    targets=[device_id] if device_id else [],
                    transport="orchestrator",
                )
            except Exception as _aud_exc:
                logger.debug(
                    "TaskOrchestrator._process_task: audit_task_dispatched skipped: %s",
                    _aud_exc,
                )

            # 4. 等待结果（带超时）
            await self._wait_for_completion(task)

            # PR-5 Cap 1: lifecycle → done/failed based on final status
            if envelope is not None:
                try:
                    from core.task_lifecycle import get_lifecycle_manager

                    _lcm = get_lifecycle_manager()
                    if task.status == TaskStatus.COMPLETED:
                        _lcm.mark_done(envelope, result_summary=f"task {task.task_id} completed")
                    elif task.status == TaskStatus.FAILED:
                        _lcm.mark_failed(envelope, error=task.error or "unknown")
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Task processing error: {e}")
            task.status = TaskStatus.FAILED
            task.error = str(e)
            # PR-5 Cap 1: lifecycle → failed
            if envelope is not None:
                try:
                    from core.task_lifecycle import get_lifecycle_manager

                    get_lifecycle_manager().mark_failed(envelope, error=str(e))
                except Exception:
                    pass
        finally:
            task.completed_at = datetime.now(timezone.utc)
            # PR-CONCURRENT-DEVICE-CONTROL: release device task count
            if task.assigned_device:
                try:
                    await self.release_device_task(task.assigned_device)
                except Exception:
                    pass

    # ── 连通性视图 ────────────────────────────────────────────────────────
    #
    # 生产实况:注入本类的 WebSocketManager 虽然被 bootstrap/lifecycle.py 完整
    # 装配并 start(),但它的 connections 永远是空的 —— 唯一会调用
    # WebSocketManager.connect() 的是同文件的 handle_connection(),而 PR-25 之后
    # 全部设备 WS 入口(/ws/device/{device_id} 及各 compat 面)都收敛到
    # routes/websocket.py::_handle_android_ws → android_bridge,没有任何路由再走
    # handle_connection。于是 get_connected_devices() 恒为 []、
    # is_device_connected() 恒为 False,_select_device() 对每个任务都返回 None,
    # broadcast_command() 也永远广播给零台设备 —— 而 routes/tasks.py 仍在对外
    # 暴露这些端点。
    #
    # 修法不是把 handle_connection 挂成第二个 ingress(那会直接违反 PR-25
    # "exactly one canonical ingress"),而是让编排器去读真正的权威在线视图。
    # 按 android_bridge.get_android_devices() 里 PR-UDM-UNIFY 的既定方向,
    # 权威来源是 UDM;WebSocketManager 的视图继续保留并取并集,这样测试里
    # 注入的假 manager 仍然有效,真实部署里也能看到设备。

    def _authoritative_online_ids(self) -> List[str]:
        """UDM 中处于 ONLINE/BUSY 的设备 id。UDM 不可用时返回空列表。"""
        try:
            from core.unified.device_manager import get_unified_device_manager

            return [
                str(d.device_id)
                for d in get_unified_device_manager().get_online_devices()
                if getattr(d, "device_id", None)
            ]
        except Exception as exc:
            logger.warning(
                "TaskOrchestrator: UDM online-device lookup failed (%s); " "falling back to transport view only",
                exc,
            )
            return []

    def _connected_device_ids(self) -> List[str]:
        """传输层视图 ∪ UDM 权威在线视图(保序去重)。"""
        ordered: Dict[str, None] = {}
        try:
            for dev in self.websocket_manager.get_connected_devices() or []:
                ordered.setdefault(str(dev), None)
        except Exception as exc:
            logger.warning("TaskOrchestrator: transport connected-device view failed: %s", exc)
        for device_id in self._authoritative_online_ids():
            ordered.setdefault(device_id, None)
        return list(ordered)

    def _device_type_of(self, device_id: str) -> Optional[str]:
        """设备类型小写字面量;查不到返回 None。"""
        getter = getattr(self.websocket_manager, "get_device_type", None)
        if callable(getter):
            try:
                dtype = getter(device_id)
                if dtype:
                    return str(dtype).lower()
            except Exception as exc:
                logger.debug("TaskOrchestrator: transport device-type lookup failed for %r: %s", device_id, exc)
        try:
            from core.unified.device_manager import get_unified_device_manager

            device = get_unified_device_manager().get_device(device_id)
            # UnifiedDevice 用了 use_enum_values,device_type 已是 str;
            # 但对直接塞进枚举的调用方也要能正确取到 .value。
            raw = getattr(device, "device_type", None) if device is not None else None
            if raw is None:
                return None
            return str(getattr(raw, "value", raw)).lower()
        except Exception as exc:
            logger.debug("TaskOrchestrator: UDM device-type lookup failed for %r: %s", device_id, exc)
            return None

    def _is_device_connected(self, device_id: str) -> bool:
        """单设备连通性:传输层说通就算通,否则回退 UDM 权威视图。"""
        try:
            if self.websocket_manager.is_device_connected(device_id):
                return True
        except Exception as exc:
            logger.warning("TaskOrchestrator: transport connectivity probe failed for %r: %s", device_id, exc)
        return device_id in self._authoritative_online_ids()

    async def _select_device(self, task: Task) -> Optional[str]:
        """选择执行任务的设备（优先选择自主执行能力的设备）"""
        # 如果已指定设备
        if task.assigned_device:
            if self._is_device_connected(task.assigned_device):
                # 显式指定设备的任务同样【占用】该设备,必须一并计数。
                # 计数原本只在下面的自动选设备分支(第 472 行)里 +1,而释放是在
                # execute 的 finally 里对【任何】有 assigned_device 的任务无条件调用
                # release_device_task() —— 于是显式指定的任务只减不加。
                # release 里的 `if current > 0` 只能防止计数变负,防不住它把同一台
                # 设备上另一个并发任务的计数偷偷减掉:计数被低估后,最少负载选择
                # 会把新任务继续往这台已经很忙的设备上堆。
                async with self._device_count_lock:
                    self._device_task_counts[task.assigned_device] = (
                        self._device_task_counts.get(task.assigned_device, 0) + 1
                    )
                return task.assigned_device
            else:
                logger.warning(f"Assigned device {task.assigned_device} not connected")

        # 获取所有在线设备
        connected_devices = self._connected_device_ids()
        if not connected_devices:
            return None

        # ── 自主优先过滤器 ──
        # 尝试从 DeviceRouter 获取设备元数据，筛选自主设备
        try:
            from galaxy_gateway.autonomous_filter import filter_autonomous_devices
            from galaxy_gateway.device_router import device_router as _dr

            def _get_meta(device_id: str):
                d = _dr.get_device(device_id)
                return d.metadata if d is not None else {}

            def _get_status(device_id: str):
                # Treat all websocket-connected devices as online
                return "online"

            preferred = filter_autonomous_devices(
                connected_devices,
                get_metadata=_get_meta,
                get_status=_get_status,
            )
        except Exception as _fe:
            logger.debug("autonomous_filter unavailable in orchestrator: %s", _fe)
            preferred = list(connected_devices)

        if not preferred:
            return None

        # 负载均衡策略
        # 1. 类型匹配: 优先选择与任务类型匹配的设备
        request_lower = (task.user_request or "").lower()
        preferred_type = None
        if any(kw in request_lower for kw in ("安卓", "手机", "android", "app")):
            preferred_type = "android"
        elif any(kw in request_lower for kw in ("windows", "电脑", "桌面", "desktop")):
            preferred_type = "windows"

        # 类型偏好此前挂在 hasattr(self.websocket_manager, "get_device_type") 上,
        # 而 WebSocketManager 从来没有这个方法(其 DeviceConnection 模型里也没有
        # device_type 字段,见 transport/websocket_server.py:40-53),所以这一段
        # 一直是死代码 —— "安卓/手机/windows/桌面" 这些关键词的设备类型偏好
        # 从未生效过。改为查真实类型来源:先问 manager(测试可注入),再回退
        # UDM(UnifiedDeviceType 的取值就是 "android"/"windows",与上面
        # preferred_type 的词表是同一套字面量)。
        if preferred_type:
            typed_devices = [d for d in preferred if self._device_type_of(d) == preferred_type]
            if typed_devices:
                preferred = typed_devices

        # 2. 最少任务优先: 选择当前负载最低的设备 (async-safe)
        async with self._device_count_lock:
            preferred_sorted = sorted(preferred, key=lambda d: self._device_task_counts.get(d, 0))

            # 3. 轮询 (在同等负载中轮询)
            selected = preferred_sorted[self._device_rr_index % len(preferred_sorted)]
            self._device_rr_index += 1
            self._device_task_counts[selected] = self._device_task_counts.get(selected, 0) + 1

        return selected

    async def release_device_task(self, device_id: str) -> None:
        """Decrement task count when a task completes. Call this after task done/failed.

        PR-CONCURRENT-DEVICE-CONTROL: prevents _device_task_counts from growing
        indefinitely and breaking load balancing.
        """
        async with self._device_count_lock:
            current = self._device_task_counts.get(device_id, 0)
            if current > 0:
                self._device_task_counts[device_id] = current - 1

    async def reset_device_counts(self) -> None:
        """Reset all device task counts. Useful when topology changes dramatically."""
        async with self._device_count_lock:
            self._device_task_counts.clear()
            self._device_rr_index = -1

    async def _decompose_task(self, task: Task) -> List[Command]:
        """分解任务为命令序列。

        PR-2: This method translates the *already-decided* action (as expressed
        in ``task.user_request``) into low-level device commands.  It performs
        **structural decomposition only** — it does NOT re-evaluate intent,
        re-score plans, or replace the primary decision produced by OpenClawd.
        """
        commands = []
        request = task.user_request.lower()

        # 简单的任务分解逻辑（可以扩展为 LLM 驱动）
        if "截图" in request or "screenshot" in request:
            commands.append(Command(tool_name="screenshot", tool_type="data_collection", parameters={}))

        if "点击" in request or "click" in request:
            # 解析点击目标
            commands.append(Command(tool_name="click", tool_type="action", parameters={"target": request}))

        if "输入" in request or "input" in request or "type" in request:
            commands.append(Command(tool_name="input_text", tool_type="action", parameters={"text": request}))

        if "滑动" in request or "swipe" in request:
            commands.append(Command(tool_name="swipe", tool_type="action", parameters={"direction": "down"}))

        # 如果没有识别到具体命令，默认先截图获取屏幕信息
        if not commands:
            commands.append(Command(tool_name="get_screen_content", tool_type="data_collection", parameters={}))

        return commands

    async def _send_task_to_device(self, task: Task):
        """发送任务到设备（PR-2：使用 TaskEnvelope 字段构造消息）。"""
        # PR-2: retrieve the envelope constructed at submit_task; fall back to
        # the legacy AIP message path when the envelope is unavailable.
        envelope = self._task_envelopes.get(task.task_id)
        trace_id = envelope.trace_id if envelope is not None else task.task_id

        message = create_task_message(device_id=task.assigned_device, task_id=task.task_id, commands=task.commands)
        message.payload["user_request"] = task.user_request
        # PR-2: attach envelope trace_id for unified cross-component correlation.
        message.payload["trace_id"] = trace_id

        # 注册任务回调
        self.message_handler.create_task(
            task_id=task.task_id, device_id=task.assigned_device, task_type="user_task", callback=self._on_task_result
        )

        # PR-28: Route through AIPTransport with auto transport selection.
        # AIPTransport will automatically prefer tailscale_p2p for same-tailnet
        # devices, fallback to tcp/websocket as needed.
        try:
            from core.aip_transport import get_aip_transport

            result = await get_aip_transport().send(
                message,
                task.assigned_device,
                transport="auto",
            )
            success = result.get("success", False)
        except Exception as exc:
            logger.warning("AIPTransport send failed for %s: %s", task.assigned_device, exc)
            success = False

        if not success:
            raise Exception(f"Failed to send task to device {task.assigned_device}")

    async def _wait_for_completion(self, task: Task):
        """等待任务完成"""
        start_time = datetime.now(timezone.utc)

        while True:
            # 检查超时
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            if elapsed > task.timeout:
                task.status = TaskStatus.FAILED
                task.error = "Task timeout"
                return

            # 检查任务状态
            task_info = self.message_handler.get_task(task.task_id)
            if task_info:
                if task_info["status"] == TaskStatus.COMPLETED:
                    task.status = TaskStatus.COMPLETED
                    task.results = task_info.get("results", [])
                    return
                elif task_info["status"] == TaskStatus.FAILED:
                    task.status = TaskStatus.FAILED
                    return

            await asyncio.sleep(0.5)

    async def _on_task_result(self, task_id: str, message: AIPMessage):
        """任务结果回调"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.results = message.results
            logger.info(f"Task {task_id} received results")

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[Task]:
        """获取所有任务"""
        return list(self.tasks.values())

    def get_pending_tasks(self) -> List[Task]:
        """获取待处理任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.PENDING]

    def get_running_tasks(self) -> List[Task]:
        """获取运行中任务"""
        return [t for t in self.tasks.values() if t.status == TaskStatus.RUNNING]

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        if task_id not in self.tasks:
            return False

        task = self.tasks[task_id]
        if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return False

        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now(timezone.utc)

        # PR-28: 统一走 AIPTransport，自动选择最优传输
        if task.assigned_device:
            cancel_message = {
                "type": "task_cancel",
                "device_id": task.assigned_device,
                "task_id": task_id,
                "_transport": "auto",
                "version": "3.0",
            }
            try:
                from core.aip_transport import get_aip_transport

                await get_aip_transport().send(
                    cancel_message,
                    task.assigned_device,
                )
            except Exception as exc:
                logger.warning("AIPTransport cancel send failed for %s: %s", task.assigned_device, exc)

        logger.info(f"Task cancelled: {task_id}")
        return True

    # ------------------------------------------------------------------
    # PR-5: DAG-based multi-device task execution
    # ------------------------------------------------------------------

    async def submit_dag_task(
        self,
        subtasks: List[Any],
        *,
        trace_id: str = "",
        runtime_session_id: str = "",
        context: Optional[Dict[str, Any]] = None,
        continue_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """Execute a list of subtask objects as a TaskGraph DAG.

        This is the PR-5 DAG integration point for the gateway orchestrator.
        Each subtask is mapped to a ``TaskNode``; nodes without explicit
        dependencies run concurrently.  Nodes that reference a ``device_id``
        will have that ID available inside the handler context.

        Falls back to sequential execution if DAG compilation fails.

        Args:
            subtasks:            Subtask objects (must expose ``task_id``,
                                 ``name``, ``description``, ``depends_on``,
                                 ``device_id``).
            trace_id:            Trace ID propagated into every node.
            runtime_session_id:  Session ID propagated into every node.
            context:             Additional context for handlers.
            continue_on_failure: Keep independent branches running on failure.

        Returns:
            Dict with ``success``, ``done``, ``failed``, ``skipped``,
            ``elapsed_ms``, ``graph_id``, ``trace_id``, ``node_statuses``.
        """
        if not subtasks:
            return {
                "success": True,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "elapsed_ms": 0.0,
                "graph_id": "",
                "trace_id": trace_id,
                "node_statuses": {},
            }

        try:
            from core.task_graph import RetryPolicy, compile_subtasks_to_graph
        except ImportError as exc:
            logger.warning(
                "TaskOrchestrator.submit_dag_task: core.task_graph unavailable (%s). "
                "Falling back to sequential submission.",
                exc,
            )
            return await self._sequential_fallback(subtasks, trace_id=trace_id)

        policy = RetryPolicy(max_retries=1, retry_delay_seconds=1.0)

        # Named constants for task-completion polling
        _TASK_COMPLETION_TIMEOUT_SECONDS = 60.0
        _POLLING_INTERVAL_SECONDS = 0.5

        # Build a handler that submits each subtask as a regular Task
        orchestrator_ref = self

        async def _device_handler(node: Any, ctx: Dict[str, Any]) -> Dict[str, Any]:
            """Submit the subtask to the appropriate device and await completion."""
            device_id: str = node.device_id or ctx.get("default_device_id", "")
            task = await orchestrator_ref.submit_task(
                user_request=node.description or node.node_id,
                target_device=device_id if device_id else None,
            )
            # Best-effort: wait up to _TASK_COMPLETION_TIMEOUT_SECONDS for completion
            deadline = _TASK_COMPLETION_TIMEOUT_SECONDS
            elapsed = 0.0
            interval = _POLLING_INTERVAL_SECONDS
            while elapsed < deadline:
                t = orchestrator_ref.tasks.get(task.task_id)
                if t and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    break
                await asyncio.sleep(interval)
                elapsed += interval
            final = orchestrator_ref.tasks.get(task.task_id)
            if final and final.status == TaskStatus.FAILED:
                raise RuntimeError(final.error or f"task {task.task_id} failed")
            return {"task_id": task.task_id, "status": final.status.value if final else "unknown"}

        try:
            graph = compile_subtasks_to_graph(
                subtasks,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
                default_retry_policy=policy,
                node_handler=_device_handler,
            )
        except ValueError as exc:
            logger.warning(
                "TaskOrchestrator.submit_dag_task: DAG compilation failed (%s). "
                "Falling back to sequential submission.",
                exc,
            )
            return await self._sequential_fallback(subtasks, trace_id=trace_id)

        logger.info(
            "TaskOrchestrator: executing %d-node TaskGraph | trace_id=%s",
            len(subtasks),
            trace_id or graph.trace_id,
        )
        exec_ctx = dict(context or {})
        result = await graph.execute(
            context=exec_ctx,
            continue_on_failure=continue_on_failure,
        )
        return {
            "success": result.success,
            "graph_id": result.graph_id,
            "trace_id": result.trace_id,
            "done": result.done_nodes,
            "failed": result.failed_nodes,
            "skipped": result.skipped_nodes,
            "elapsed_ms": result.elapsed_ms,
            "node_statuses": result.node_statuses,
        }

    async def _sequential_fallback(
        self,
        subtasks: List[Any],
        *,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Fallback: submit subtasks one-by-one in declaration order."""
        logger.info(
            "TaskOrchestrator._sequential_fallback: submitting %d tasks linearly | trace_id=%s",
            len(subtasks),
            trace_id,
        )
        done = 0
        failed = 0
        for st in subtasks:
            try:
                desc = getattr(st, "description", "") or getattr(st, "name", "")
                device_id = getattr(st, "device_id", "") or ""
                await self.submit_task(
                    user_request=desc,
                    target_device=device_id if device_id else None,
                )
                done += 1
            except Exception as exc:
                logger.warning("Sequential fallback subtask failed: %s", exc)
                failed += 1
        return {
            "success": failed == 0,
            "graph_id": "",
            "trace_id": trace_id,
            "done": done,
            "failed": failed,
            "skipped": 0,
            "elapsed_ms": 0.0,
            "node_statuses": {},
        }


class MultiDeviceOrchestrator(TaskOrchestrator):
    """多设备协同编排器 — Legacy compat subclass of TaskOrchestrator.

    .. deprecated:: PR-S5
        ``MultiDeviceOrchestrator`` inherits the legacy status of
        :class:`TaskOrchestrator` (PR-7).  It is a **compatibility subclass**
        retained so that existing callers that reference it directly do not
        immediately break.  All multi-device execution is now routed through
        ``submit_dag_task()`` which delegates to :mod:`core.task_graph` and
        :class:`~galaxy_gateway.device_router.DeviceRouter`.

        Preferred canonical path:
            ``core.e2e_orchestrator.process_user_input(targets=[…])``

        See :mod:`core.orchestration_authority.legacy_paths` for the registry
        entry (``galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator``).
    """

    async def submit_multi_device_task(
        self,
        user_request: str,
        device_ids: List[str],
        coordination_mode: str = "parallel",  # parallel, sequential, conditional
        trace_id: str = "",
        runtime_session_id: str = "",
    ) -> Dict[str, Any]:
        """提交多设备协同任务 — PR-2: 所有多设备任务强制经过 TaskGraph.

        All multi-device tasks are routed through :meth:`submit_dag_task` so
        that execution is fully traced and no bypass path exists.  The legacy
        ``List[Task]`` return type has been replaced with the canonical
        ``Dict[str, Any]`` result from the TaskGraph executor.

        Legacy callers that expected ``List[Task]`` should migrate to
        inspecting ``result["node_statuses"]`` instead.
        """
        if not device_ids:
            return {
                "success": True,
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "elapsed_ms": 0.0,
                "graph_id": "",
                "trace_id": trace_id,
                "node_statuses": {},
            }

        import uuid as _uuid_lib

        trace_id = trace_id or f"trace_{_uuid_lib.uuid4().hex[:12]}"
        runtime_session_id = runtime_session_id or f"session_{_uuid_lib.uuid4().hex[:12]}"

        # Build lightweight subtask objects that compile_subtasks_to_graph understands.
        # Pre-generate every task_id so a sequential depends_on can reference the
        # PREVIOUS subtask's *actual* id. Previously task_id was
        # "subtask_{idx}_{random}" but depends_on used "subtask_{idx-1}" (no random
        # suffix), so the dependency never matched a real id and sequential
        # ordering was silently dropped.
        import types

        task_ids = [f"subtask_{idx}_{_uuid_lib.uuid4().hex[:8]}" for idx in range(len(device_ids))]
        subtasks = []
        for idx, device_id in enumerate(device_ids):
            st = types.SimpleNamespace(
                task_id=task_ids[idx],
                name=f"task_on_{device_id}",
                description=user_request,
                device_id=device_id,
                depends_on=[task_ids[idx - 1]] if coordination_mode == "sequential" and idx > 0 else [],
            )
            subtasks.append(st)

        logger.info(
            "PR-2 submit_multi_device_task: routing %d devices through TaskGraph " "| mode=%s trace_id=%s",
            len(device_ids),
            coordination_mode,
            trace_id,
        )

        # Log command envelope for observability
        try:
            from core.unified.command_envelope import CommandEnvelope, log_command_envelope

            env = CommandEnvelope(
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
                task_id=f"multi_{_uuid_lib.uuid4().hex[:8]}",
                device_id=",".join(device_ids),
                payload={"coordination_mode": coordination_mode, "device_count": len(device_ids)},
            )
            log_command_envelope(env, event="multi_device_task_submitted")
        except Exception:
            pass

        return await self.submit_dag_task(
            subtasks,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            continue_on_failure=(coordination_mode != "sequential"),
        )

    async def broadcast_command(self, command: Command) -> Dict[str, CommandResult]:
        """向所有设备广播命令"""
        results = {}
        connected_devices = self._connected_device_ids()

        for device_id in connected_devices:
            task = await self.submit_task(user_request=f"Execute command: {command.tool_name}", target_device=device_id)
            task.commands = [command]
            await self._send_task_to_device(task)
            # Populate the declared Dict[str, CommandResult] return.  The
            # broadcast is fire-and-forget (the real outcome arrives later via
            # the task lifecycle), so the synchronously-knowable per-device
            # result is "dispatched, outcome pending" (ResultStatus.NONE).
            # Previously `results` was returned empty regardless of dispatch.
            results[device_id] = CommandResult(
                command_id=getattr(command, "command_id", "") or task.task_id,
                status=ResultStatus.NONE,
                result={"dispatched": True, "task_id": task.task_id},
            )

        return results
