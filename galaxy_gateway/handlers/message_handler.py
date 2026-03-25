"""
galaxy_gateway.handlers.message_handler — Legacy Chain-B Ingress Handler (PR-S6)
==================================================================================

负责:
1. 路由不同类型的消息
2. 调用相应的处理逻辑
3. 生成响应消息

.. note:: PR-S6 — Legacy chain-B ingress; NOT a canonical server-side runtime entry

    ``MessageHandler`` is the **chain B ingress handler** in the legacy
    dual-entry architecture:

    * **Chain A (canonical)**: ``websocket_handler → DeviceRouter``
      This is the canonical server pipeline.
    * **Chain B (legacy)**: ``MessageHandler → TaskOrchestrator``
      This path is retained for backward compatibility only.

    Chain B was identified in PR-S5 (via ``ParallelGroupTracker`` demotion)
    as the legacy side of a split-entry design.  This PR-S6 demotion makes
    the ingress boundary of chain B explicit: ``MessageHandler`` **must not**
    be used as a primary server-side runtime entry point.  New task dispatch
    **must** enter through the canonical pipeline:

        ``OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter``

    ``MessageHandler`` is retained as a **compatibility shim** so that legacy
    chain-B callers are not broken, but it carries **no independent runtime
    authority**.  It must not be extended with new execution logic.

    See :mod:`core.orchestration_authority.legacy_paths` for the registry
    entry (``galaxy_gateway.handlers.message_handler.MessageHandler``).
"""

import logging
import uuid
from typing import Optional, Callable, Dict, Any, Set, Tuple
from datetime import datetime

from ..protocol import (
    AIPMessage, MessageType, TaskStatus, ResultStatus,
    create_error_message
)
from .device_manager import DeviceManager

logger = logging.getLogger(__name__)


def _publish_m2_safe(event_type: str, device_id: str, payload: dict, **kw) -> None:
    """发布 M2 事件的轻量辅助函数（失败不崩溃）。"""
    try:
        from integration.event_bus import build_m2_event, publish_m2_event
        evt = build_m2_event(event_type, device_id, payload, **kw)
        publish_m2_event(evt)
    except Exception as _exc:
        logger.debug("MessageHandler: M2 发布失败（非致命）: %s", _exc)


class MessageHandler:
    """消息处理器 — Legacy Chain-B Ingress (PR-S6)

    .. deprecated:: PR-S6
        ``MessageHandler`` is the **legacy chain-B ingress handler** (PR-S6).
        Chain B (``MessageHandler → TaskOrchestrator``) is a legacy duplicate
        of the canonical chain A (``websocket_handler → DeviceRouter``).

        ``MessageHandler`` is retained as a **compatibility shim** only.  It
        carries **no independent runtime authority** and must not be extended
        with new execution or dispatch logic.  New server-side task dispatch
        **must** enter through the canonical pipeline:
        ``OpenClawd → CommandRouter → TaskEnvelope → DeviceRouter``.
    """

    def __init__(self, device_manager: DeviceManager):
        try:
            from core.orchestration_authority.legacy_paths import emit_legacy_guardrail
            emit_legacy_guardrail(
                caller="galaxy_gateway.handlers.message_handler.MessageHandler",
                recommendation=(
                    "MessageHandler is the LEGACY CHAIN-B INGRESS HANDLER (PR-S6).  "
                    "Chain B (MessageHandler → TaskOrchestrator) is the legacy side "
                    "of the split-entry design demoted in PR-S5/PR-S6.  "
                    "Canonical server task dispatch enters via chain A: "
                    "websocket_handler → DeviceRouter.  "
                    "Do not extend MessageHandler with new execution logic."
                ),
            )
        except Exception:
            pass
        self.device_manager = device_manager
        self.task_handlers: Dict[str, Callable] = {}
        self.pending_tasks: Dict[str, dict] = {}  # task_id -> task_info
        # Idempotency: seen task-result IDs and parallel subtask keys.
        self._seen_task_result_ids: Set[str] = set()
        self._seen_parallel_keys: Set[Tuple[str, int]] = set()  # (group_id, subtask_index)
        
    def register_task_handler(self, task_type: str, handler: Callable):
        """注册任务处理器"""
        self.task_handlers[task_type] = handler
        logger.info(f"Registered task handler for: {task_type}")
    
    async def handle_message(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理消息并返回响应"""
        logger.debug(f"Handling message from {device_id}: {message.type}")
        
        try:
            handler = self._get_handler(message.type)
            if handler:
                response = await handler(device_id, message)
                # Propagate trace_id and route_mode into every response so
                # downstream components always receive both fields.
                # Empty strings are intentional here: inject_trace_metadata()
                # guarantees non-empty values at WS/HTTP ingress, so empty
                # strings only arise in unit tests or internal direct calls
                # where injection is skipped — in those cases propagation is
                # a no-op (the `if trace_id` guard prevents writing empty values).
                if response is not None:
                    trace_id = message.payload.get("trace_id", "")
                    route_mode = message.payload.get("route_mode", "")
                    if trace_id:
                        response.payload.setdefault("trace_id", trace_id)
                    if route_mode:
                        response.payload.setdefault("route_mode", route_mode)
                return response
            else:
                logger.warning(f"No handler for message type: {message.type}")
                return None
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            return create_error_message(device_id, str(e), message.message_id)
    
    def _get_handler(self, message_type: MessageType) -> Optional[Callable]:
        """获取消息处理器"""
        handlers = {
            # --- 设备管理 ---
            MessageType.DEVICE_REGISTER: self._handle_register,
            MessageType.DEVICE_HEARTBEAT: self._handle_heartbeat,
            MessageType.DEVICE_STATUS: self._handle_device_status,
            MessageType.ERROR: self._handle_error,
            # --- 任务/命令结果（设备→服务端）---
            MessageType.TASK_RESULT: self._handle_task_result,
            MessageType.COMMAND_RESULT: self._handle_command_result,
            MessageType.GUI_SCREEN_CONTENT: self._handle_screen_content,
            # --- 任务提交/调度（Android 客户端发起）---
            MessageType.TASK_SUBMIT: self._handle_task_submit,
            MessageType.TASK_CANCEL: self._handle_task_cancel,
            MessageType.TASK_STATUS: self._handle_task_status_query,
            # --- Agent 控制 ---
            MessageType.AGENT_PING: self._handle_agent_ping,
            # --- GUI/操作请求 ---
            MessageType.UI_TREE_REQUEST: self._handle_forward_ack,
            MessageType.ACTION_EXECUTE: self._handle_forward_ack,
            MessageType.ACTION_SEQUENCE_EXECUTE: self._handle_forward_ack,
            MessageType.APP_START: self._handle_forward_ack,
            MessageType.APP_STOP: self._handle_forward_ack,
            MessageType.SYSTEM_COMMAND: self._handle_forward_ack,
            # --- 能力/诊断上报 ---
            MessageType.CAPABILITY_REPORT: self._handle_capability_report,
            MessageType.DIAGNOSTICS_PAYLOAD: self._handle_diagnostics_payload,
            # --- 视觉请求 ---
            MessageType.VISION_REQUEST: self._handle_vision_request,
        }
        return handlers.get(message_type)
    
    async def _handle_register(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理设备注册"""
        return self.device_manager.handle_register_message(message)
    
    async def _handle_heartbeat(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理心跳"""
        self.device_manager.update_device_status(device_id, "online")
        return AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT_ACK,
            device_id=device_id,
            correlation_id=message.message_id
        )
    
    async def _handle_device_status(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理设备状态更新"""
        status = message.payload.get("status", "unknown")
        self.device_manager.update_device_status(device_id, status)
        return None
    
    async def _handle_task_result(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理任务结果（幂等：同一 task_id 的重复回包将被忽略）。"""
        task_id = message.task_id
        if not task_id:
            return create_error_message(device_id, "Missing task_id", message.message_id)

        # ── Idempotency: check for duplicate task result ──
        if task_id in self._seen_task_result_ids:
            logger.info(
                "Duplicate task result ignored",
                extra={
                    "event": "task_result_duplicate_ignored",
                    "task_id": task_id,
                    "device_id": device_id,
                },
            )
            return None
        self._seen_task_result_ids.add(task_id)

        # ── Parallel subtask dedup (group_id + subtask_index) ──
        payload = message.payload or {}
        group_id = payload.get("group_id")
        subtask_index = payload.get("subtask_index")
        if group_id is not None and subtask_index is not None:
            parallel_key = (str(group_id), int(subtask_index))
            if parallel_key in self._seen_parallel_keys:
                logger.info(
                    "Duplicate parallel subtask result ignored",
                    extra={
                        "event": "parallel_subtask_result_duplicate_ignored",
                        "group_id": group_id,
                        "subtask_index": subtask_index,
                        "device_id": device_id,
                    },
                )
                return None
            self._seen_parallel_keys.add(parallel_key)

        if task_id in self.pending_tasks:
            task_info = self.pending_tasks[task_id]
            task_info["status"] = message.task_status or TaskStatus.COMPLETED
            task_info["results"] = message.results
            task_info["completed_at"] = datetime.utcnow()
            
            logger.info(f"Task {task_id} completed with status: {task_info['status']}")
            
            # 如果有回调，执行回调
            if "callback" in task_info and task_info["callback"]:
                try:
                    await task_info["callback"](task_id, message)
                except Exception as e:
                    logger.error(f"Task callback error: {e}")

        # M2 并行发布 — task.lifecycle (completed / failed)
        _ts = message.task_status or TaskStatus.COMPLETED
        _m2_status = "completed" if str(_ts).upper() in ("COMPLETED", "TASKSTATUS.COMPLETED", "SUCCESS") else "failed"
        _publish_m2_safe(
            "task.lifecycle",
            device_id,
            {
                "task_id": task_id,
                "status": _m2_status,
                "task_type": (message.payload or {}).get("task_type", "generic"),
                "target_device": device_id,
            },
            node="message_handler",
            task_id=task_id,
        )

        # ── 并行闭环：将子任务结果记录到共享 ParallelGroupTracker ──
        try:
            from galaxy_gateway.orchestrator.parallel_tracker import record_parallel_fields
            await record_parallel_fields(message.payload)
        except Exception as _pt_err:
            logger.warning("parallel_tracker[B/task]: record failed: %s", _pt_err)

        return None
    
    async def _handle_command_result(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理命令结果"""
        for result in message.results:
            logger.info(f"Command {result.command_id} result: {result.status}")

        # ── 并行闭环：将子任务结果记录到共享 ParallelGroupTracker ──
        try:
            from galaxy_gateway.orchestrator.parallel_tracker import record_parallel_fields
            await record_parallel_fields(message.payload)
        except Exception as _pt_err:
            logger.warning("parallel_tracker[B/cmd]: record failed: %s", _pt_err)

        return None
    
    async def _handle_screen_content(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理屏幕内容"""
        logger.debug(f"Received screen content from {device_id}")
        # 可以在这里进行 GUI 分析
        return None
    
    async def _handle_error(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """处理错误消息"""
        logger.error(f"Error from device {device_id}: {message.error}")
        return None

    # ------------------------------------------------------------------
    # 任务提交/调度（Android 客户端 task_execute → compat → task_submit）
    # ------------------------------------------------------------------

    async def _handle_task_submit(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理任务提交（task_submit / task_execute）"""
        task_id = message.task_id or str(uuid.uuid4())
        task_type = message.payload.get("task_type", "generic")
        logger.info(f"Task submit from {device_id}: task_id={task_id}, type={task_type}")

        self.create_task(task_id, device_id, task_type)

        # M2 并行发布 — task.lifecycle (created)
        _publish_m2_safe(
            "task.lifecycle",
            "gateway",
            {
                "task_id": task_id,
                "status": "created",
                "task_type": task_type,
                "target_device": device_id,
            },
            node="message_handler",
            task_id=task_id,
        )

        return AIPMessage(
            type=MessageType.TASK_ASSIGN,
            device_id=device_id,
            correlation_id=message.message_id,
            task_id=task_id,
            task_status=TaskStatus.PENDING,
            payload={"message": "Task accepted", "task_type": task_type},
        )

    async def _handle_task_cancel(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理任务取消"""
        task_id = message.task_id
        logger.info(f"Task cancel from {device_id}: task_id={task_id}")

        if task_id and task_id in self.pending_tasks:
            self.pending_tasks[task_id]["status"] = TaskStatus.COMPLETED
            self.pending_tasks[task_id]["completed_at"] = datetime.utcnow()

        return AIPMessage(
            type=MessageType.TASK_END,
            device_id=device_id,
            correlation_id=message.message_id,
            task_id=task_id,
            payload={"message": "Task cancelled"},
        )

    async def _handle_task_status_query(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理任务状态查询"""
        task_id = message.task_id
        task_info = self.pending_tasks.get(task_id) if task_id else None

        status = task_info["status"] if task_info else "not_found"
        return AIPMessage(
            type=MessageType.TASK_STATUS,
            device_id=device_id,
            correlation_id=message.message_id,
            task_id=task_id,
            payload={"status": str(status)},
        )

    # ------------------------------------------------------------------
    # Agent 控制
    # ------------------------------------------------------------------

    async def _handle_agent_ping(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理 agent_ping，返回 heartbeat_ack"""
        logger.debug(f"Agent ping from {device_id}")
        return AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT_ACK,
            device_id=device_id,
            correlation_id=message.message_id,
        )

    # ------------------------------------------------------------------
    # 通用转发 ACK（ui_tree_request, action_execute, app_start 等）
    # ------------------------------------------------------------------

    async def _handle_forward_ack(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """通用转发处理：记录日志并返回 ACK，后续可扩展为实际转发逻辑"""
        logger.info(f"Forward message {message.type.value} from {device_id}")
        return AIPMessage(
            type=MessageType.COMMAND_RESULT,
            device_id=device_id,
            correlation_id=message.message_id,
            payload={
                "original_type": message.type.value,
                "status": "received",
                "message": f"{message.type.value} acknowledged",
            },
        )

    # ------------------------------------------------------------------
    # 能力/诊断上报
    # ------------------------------------------------------------------

    async def _handle_capability_report(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理设备能力上报"""
        capabilities = message.payload.get("capabilities", [])
        supported_actions = message.payload.get("supported_actions", [])
        logger.info(f"Capability report from {device_id}: actions={supported_actions}")

        self.device_manager.update_device_status(device_id, "online")

        return AIPMessage(
            type=MessageType.CAPABILITY_REPORT_ACK,
            device_id=device_id,
            correlation_id=message.message_id,
            payload={"accepted": True, "message": "Capability report accepted"},
        )

    async def _handle_diagnostics_payload(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理诊断数据上报"""
        error_type = message.payload.get("error_type")
        logger.info(f"Diagnostics from {device_id}: error_type={error_type}")

        return AIPMessage(
            type=MessageType.DIAGNOSTICS_PAYLOAD_ACK,
            device_id=device_id,
            correlation_id=message.message_id,
            payload={"received": True},
        )

    # ------------------------------------------------------------------
    # 视觉请求
    # ------------------------------------------------------------------

    async def _handle_vision_request(self, device_id: str, message: AIPMessage) -> AIPMessage:
        """处理视觉分析请求"""
        logger.info(f"Vision request from {device_id}")

        return AIPMessage(
            type=MessageType.VISION_RESULT,
            device_id=device_id,
            correlation_id=message.message_id,
            payload={
                "status": "received",
                "message": "Vision request queued for processing",
            },
        )

    def create_task(
        self, 
        task_id: str, 
        device_id: str, 
        task_type: str,
        callback: Optional[Callable] = None
    ) -> dict:
        """创建任务记录"""
        task_info = {
            "task_id": task_id,
            "device_id": device_id,
            "task_type": task_type,
            "status": TaskStatus.PENDING,
            "created_at": datetime.utcnow(),
            "callback": callback
        }
        self.pending_tasks[task_id] = task_info
        return task_info
    
    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务信息"""
        return self.pending_tasks.get(task_id)
    
    def get_pending_tasks(self) -> list:
        """获取所有待处理任务"""
        return [
            t for t in self.pending_tasks.values()
            if t["status"] in [TaskStatus.PENDING, TaskStatus.RUNNING]
        ]
