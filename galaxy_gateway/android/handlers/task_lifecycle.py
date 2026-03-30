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
