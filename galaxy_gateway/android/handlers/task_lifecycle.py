"""
galaxy_gateway/android/handlers/task_lifecycle.py

Handles task result, task end, task progress, command result, and error messages.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.protocol.aip_v3 import TaskStatus

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

# OpenClawd memory backflow — top-level import so tests can patch() it.
try:
    from core.openclawd_memory_backflow import store_task_result
except ImportError:
    store_task_result = None  # type: ignore[assignment]

# PR-13: canonical host-side reconciliation binding — top-level import so
# tests can patch() it and so the import failure is handled gracefully.
try:
    from core.android_execution_signal_reconciler import reconcile_inbound_message as _reconcile_inbound_message
except ImportError:
    _reconcile_inbound_message = None  # type: ignore[assignment]


def _try_reconcile(message: Dict[str, Any]) -> None:
    """Best-effort reconcile *message* against the host-side execution tracker.

    Calls :func:`~core.android_execution_signal_reconciler.reconcile_inbound_message`
    when the reconciler is available and the message carries at least one of
    ``contract_id`` / ``session_id`` (otherwise a no-op).  Failures are logged
    at DEBUG level and never propagated so existing handler behaviour is
    unchanged when the reconciler is unavailable or the message is not
    associated with a tracked delegated execution.
    """
    if _reconcile_inbound_message is None:
        return
    payload = message.get("payload") or {}
    has_key = (
        bool(message.get("contract_id") or payload.get("contract_id"))
        or bool(
            message.get("session_id")
            or payload.get("session_id")
            or message.get("runtime_session_id")
            or payload.get("runtime_session_id")
        )
    )
    if not has_key:
        return
    try:
        outcome = _reconcile_inbound_message(message)
        if outcome.was_updated:
            logger.debug(
                "PR-13 reconcile: signal=%s contract_id=%r session_id=%r → phase=%s",
                outcome.envelope.signal_kind.value if outcome.envelope else "?",
                outcome.envelope.contract_id if outcome.envelope else "",
                outcome.envelope.session_id if outcome.envelope else "",
                outcome.record.phase.value if outcome.record else "?",
            )
        elif outcome.reject_reason:
            logger.debug(
                "PR-13 reconcile skipped: %s",
                outcome.reject_reason,
            )
    except Exception as exc:
        logger.debug("PR-13 reconcile failed (non-fatal): %s", exc)


async def handle_task_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理任务结果，完成 Future 并触发 OpenClawd 记忆回流"""
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    result_status = message.get("status", "unknown")
    route_mode = message.get("route_mode", "cross_device")

    logger.info(
        "Task result received: task_id=%s device_id=%s status=%s",
        task_id, device_id, result_status,
    )

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)

    # 完成等待的 Future
    if task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    # 更新设备状态
    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    # OpenClawd 记忆回流
    if task_id and device_id and store_task_result is not None:
        try:
            await store_task_result(
                task_id=task_id,
                device_id=device_id,
                route_mode=route_mode,
                result=message,
            )
            logger.debug(
                "Memory backflow stored: task_id=%s device_id=%s route_mode=%s",
                task_id, device_id, route_mode,
            )
        except Exception as bf_err:
            logger.warning(
                "Memory backflow failed (non-fatal): task_id=%s error=%s",
                task_id, bf_err,
            )


async def handle_task_end(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务结束通知"""
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    final_status = message.get("status", TaskStatus.COMPLETED.value)

    logger.info(
        "Task lifecycle ended: task_id=%s device_id=%s final_status=%s",
        task_id, device_id, final_status,
    )

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)

    # 清理残余 pending future
    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    async with bridge._lock:
        if device_id and device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    return {
        "version": "3.0",
        "type": "task_end_ack",
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "task_id": task_id,
        "timestamp": int(time.time() * 1000),
        "status": "acknowledged",
    }


async def handle_task_progress(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理任务进度"""
    task_id = message.get("task_id")
    progress = message.get("progress", 0)
    logger.debug("Task progress: %s - %s%%", task_id, progress)

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)


async def handle_command_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理命令结果"""
    message_id = message.get("message_id")

    if message_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(message_id)
        if not future.done():
            future.set_result(message)


async def handle_error(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理错误消息，使用结构化日志输出"""
    device_id = message.get("device_id")
    error_code = message.get("error_code")
    error_message = message.get("error_message")
    details = message.get("details")
    task_id = message.get("task_id")

    logger.error(
        "Error from device: device_id=%s error_code=%s error_message=%s task_id=%s details=%s",
        device_id, error_code, error_message, task_id, details,
    )

    # PR-13: reconcile inbound error signal against host-side execution tracker
    _try_reconcile(message)

