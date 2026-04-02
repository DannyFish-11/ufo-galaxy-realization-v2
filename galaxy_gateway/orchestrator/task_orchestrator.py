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
import uuid
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from enum import Enum

from ..protocol import (
    AIPMessage, MessageType, Command, CommandResult,
    TaskStatus, ResultStatus, DeviceCapability,
    create_task_message, create_gui_click_message,
    create_gui_input_message, create_screenshot_message
)
from ..handlers import DeviceManager, MessageHandler
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
        self,
        task_id: str,
        user_request: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: int = 300
    ):
        self.task_id = task_id
        self.user_request = user_request
        self.priority = priority
        self.timeout = timeout
        self.status = TaskStatus.PENDING
        self.created_at = datetime.utcnow()
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
        self,
        device_manager: DeviceManager,
        message_handler: MessageHandler,
        websocket_manager: WebSocketManager
    ):
        self.device_manager = device_manager
        self.message_handler = message_handler
        self.websocket_manager = websocket_manager

        self.tasks: Dict[str, Task] = {}
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        # Round-robin index for distributing tasks across connected devices.
        self._device_rr_index: int = -1
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
        self._worker_task = asyncio.create_task(self._task_worker())
        logger.info("Task Orchestrator started")
    
    async def stop(self):
        """停止编排器"""
        self._running = False
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
            from core.task_adapter import adapt_to_canonical_task
            from core.canonical_task import TaskOrigin
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
                "TaskOrchestrator.submit_task: CanonicalTask front-loaded "
                "task_id=%s trace_id=%s",
                canonical_task_id, canonical_trace_id,
            )
        except Exception as _ct_err:
            logger.debug(
                "TaskOrchestrator.submit_task: CanonicalTask front-load unavailable "
                "(graceful degradation — envelope will be built directly): %s",
                _ct_err,
            )

        task_id = canonical_task_id or str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            user_request=user_request,
            priority=priority,
            timeout=timeout
        )
        
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

        await self.task_queue.put(task)
        
        logger.info(f"Task submitted: {task_id} - {user_request[:50]}...")
        return task
    
    async def _task_worker(self):
        """任务处理工作线程"""
        while self._running:
            try:
                task = await asyncio.wait_for(
                    self.task_queue.get(),
                    timeout=1.0
                )
                await self._process_task(task)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Task worker error: {e}")
    
    async def _process_task(self, task: Task):
        """处理单个任务（PR-2：通过 TaskEnvelope 追踪生命周期）。

        PR-2 constraint: _process_task is **orchestration-only**.  It selects
        a device and dispatches the task as received.  It must NOT re-evaluate
        the user intent, re-score the plan, or produce a new primary decision.
        """
        logger.info(f"Processing task: {task.task_id}")
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()

        # PR-2: retrieve or construct the envelope for this task.
        envelope = self._task_envelopes.get(task.task_id)
        if envelope is not None:
            # PR-2: log the authority recorded in the envelope so the trace
            # shows that TaskOrchestrator is acting as transport, not decider.
            _oc_decision = (envelope.metadata or {}).get("openclawd_decision")
            logger.debug(
                "TaskOrchestrator._process_task | task_id=%s trace_id=%s request='%.50s' device=%s openclawd_authority=%s",
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
                _trace_id_audit = (
                    getattr(_envelope_for_audit, "trace_id", None) or ""
                )
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
            task.completed_at = datetime.utcnow()
    
    async def _select_device(self, task: Task) -> Optional[str]:
        """选择执行任务的设备（优先选择自主执行能力的设备）"""
        # 如果已指定设备
        if task.assigned_device:
            if self.websocket_manager.is_device_connected(task.assigned_device):
                return task.assigned_device
            else:
                logger.warning(f"Assigned device {task.assigned_device} not connected")

        # 获取所有在线设备
        connected_devices = self.websocket_manager.get_connected_devices()
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

        if preferred_type and hasattr(self.websocket_manager, "get_device_type"):
            typed_devices = [
                d for d in preferred
                if self.websocket_manager.get_device_type(d) == preferred_type
            ]
            if typed_devices:
                preferred = typed_devices

        # 2. 最少任务优先: 选择当前负载最低的设备
        if not hasattr(self, "_device_task_counts"):
            self._device_task_counts = {}
            self._rr_index = 0

        preferred_sorted = sorted(
            preferred,
            key=lambda d: self._device_task_counts.get(d, 0)
        )

        # 3. 轮询 (在同等负载中轮询)
        selected = preferred_sorted[self._rr_index % len(preferred_sorted)]
        self._rr_index += 1
        self._device_task_counts[selected] = self._device_task_counts.get(selected, 0) + 1

        return selected
    
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
            commands.append(Command(
                tool_name="screenshot",
                tool_type="data_collection",
                parameters={}
            ))
        
        if "点击" in request or "click" in request:
            # 解析点击目标
            commands.append(Command(
                tool_name="click",
                tool_type="action",
                parameters={"target": request}
            ))
        
        if "输入" in request or "input" in request or "type" in request:
            commands.append(Command(
                tool_name="input_text",
                tool_type="action",
                parameters={"text": request}
            ))
        
        if "滑动" in request or "swipe" in request:
            commands.append(Command(
                tool_name="swipe",
                tool_type="action",
                parameters={"direction": "down"}
            ))
        
        # 如果没有识别到具体命令，默认先截图获取屏幕信息
        if not commands:
            commands.append(Command(
                tool_name="get_screen_content",
                tool_type="data_collection",
                parameters={}
            ))
        
        return commands
    
    async def _send_task_to_device(self, task: Task):
        """发送任务到设备（PR-2：使用 TaskEnvelope 字段构造消息）。"""
        # PR-2: retrieve the envelope constructed at submit_task; fall back to
        # the legacy AIP message path when the envelope is unavailable.
        envelope = self._task_envelopes.get(task.task_id)
        trace_id = envelope.trace_id if envelope is not None else task.task_id

        message = create_task_message(
            device_id=task.assigned_device,
            task_id=task.task_id,
            commands=task.commands
        )
        message.payload["user_request"] = task.user_request
        # PR-2: attach envelope trace_id for unified cross-component correlation.
        message.payload["trace_id"] = trace_id
        
        # 注册任务回调
        self.message_handler.create_task(
            task_id=task.task_id,
            device_id=task.assigned_device,
            task_type="user_task",
            callback=self._on_task_result
        )
        
        success = await self.websocket_manager.send_message(
            task.assigned_device,
            message
        )
        
        if not success:
            raise Exception(f"Failed to send task to device {task.assigned_device}")
    
    async def _wait_for_completion(self, task: Task):
        """等待任务完成"""
        start_time = datetime.utcnow()
        
        while True:
            # 检查超时
            elapsed = (datetime.utcnow() - start_time).total_seconds()
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
        task.completed_at = datetime.utcnow()
        
        # 发送取消消息到设备
        if task.assigned_device:
            cancel_message = AIPMessage(
                type=MessageType.TASK_CANCEL,
                device_id=task.assigned_device,
                task_id=task_id
            )
            await self.websocket_manager.send_message(
                task.assigned_device,
                cancel_message
            )
        
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
            return {"success": True, "done": 0, "failed": 0, "skipped": 0,
                    "elapsed_ms": 0.0, "graph_id": "", "trace_id": trace_id,
                    "node_statuses": {}}

        try:
            from core.task_graph import compile_subtasks_to_graph, RetryPolicy
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
                if t and t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED,
                                      TaskStatus.CANCELLED):
                    break
                await asyncio.sleep(interval)
                elapsed += interval
            final = orchestrator_ref.tasks.get(task.task_id)
            if final and final.status == TaskStatus.FAILED:
                raise RuntimeError(final.error or f"task {task.task_id} failed")
            return {"task_id": task.task_id,
                    "status": final.status.value if final else "unknown"}

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
                task = await self.submit_task(
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

        # Build lightweight subtask objects that compile_subtasks_to_graph understands
        import types
        subtasks = []
        for idx, device_id in enumerate(device_ids):
            st = types.SimpleNamespace(
                task_id=f"subtask_{idx}_{_uuid_lib.uuid4().hex[:8]}",
                name=f"task_on_{device_id}",
                description=user_request,
                device_id=device_id,
                depends_on=[f"subtask_{idx - 1}"] if coordination_mode == "sequential" and idx > 0 else [],
            )
            subtasks.append(st)

        logger.info(
            "PR-2 submit_multi_device_task: routing %d devices through TaskGraph "
            "| mode=%s trace_id=%s",
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
        connected_devices = self.websocket_manager.get_connected_devices()
        
        for device_id in connected_devices:
            task = await self.submit_task(
                user_request=f"Execute command: {command.tool_name}",
                target_device=device_id
            )
            task.commands = [command]
            await self._send_task_to_device(task)
        
        return results
