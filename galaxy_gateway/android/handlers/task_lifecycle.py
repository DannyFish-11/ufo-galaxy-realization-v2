"""
galaxy_gateway/android/handlers/task_lifecycle.py

Handles task result, task end, task progress, command result, and error messages.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.android.message_builder import MessageBuilder
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

# ---------------------------------------------------------------------------
# Compat lifecycle path signal guard
# ---------------------------------------------------------------------------
# Prevents the same lifecycle signal (identified by idempotency_key or
# message_id) from being processed more than once when the compat layer
# normalises v1/v2 messages before dispatch.  This is a process-local,
# in-memory bounded ordered dict — it acts as a 512-slot LRU seen-set.
# OrderedDict gives O(1) lookup and O(1) ordered eviction; entries older
# than the 512-slot window are automatically discarded.

_SIGNAL_GUARD_CAPACITY: int = 512
_processed_signals: OrderedDict = OrderedDict()


def _signal_guard_accept(message: Dict[str, Any]) -> bool:
    """Return True and record the signal if it has not been seen before.

    Returns False (reject / skip) if the idempotency_key or message_id of
    *message* was already processed within the current guard window.  This
    prevents the compat normalisation layer from causing the same lifecycle
    event to be reconciled or acted upon twice.

    The guard key prefers ``idempotency_key`` (injected by the compat layer)
    over ``message_id`` (supplied by the sender).  When neither is present the
    signal is always accepted so that the guard is never a blocking error path.
    """
    key = message.get("idempotency_key") or message.get("message_id")
    if not key:
        # No stable identity — cannot guard; allow through.
        return True
    key = str(key)
    if key in _processed_signals:
        logger.debug(
            "task_lifecycle signal guard: duplicate signal suppressed key=%r type=%s",
            key, message.get("type"),
        )
        return False
    # Record as seen; evict the oldest entry first when at capacity so the
    # dict never temporarily exceeds _SIGNAL_GUARD_CAPACITY.
    if len(_processed_signals) >= _SIGNAL_GUARD_CAPACITY:
        _processed_signals.popitem(last=False)
    _processed_signals[key] = True
    return True


def _try_reconcile(message: Dict[str, Any]) -> None:
    """Best-effort reconcile *message* against the host-side execution tracker.

    Calls :func:`~core.android_execution_signal_reconciler.reconcile_inbound_message`
    when the reconciler is available and the message carries at least one of
    ``contract_id`` / ``session_id`` (otherwise a no-op).  Failures are logged
    at DEBUG level and never propagated so existing handler behaviour is
    unchanged when the reconciler is unavailable or the message is not
    associated with a tracked delegated execution.

    A compat-path signal guard is applied first: if the same idempotency_key
    or message_id was already processed in this process session the reconcile
    call is skipped entirely, preventing duplicate processing when v1/v2 compat
    normalisation causes the same lifecycle event to be dispatched more than
    once.
    """
    # Compat lifecycle path signal guard — skip duplicates.
    if not _signal_guard_accept(message):
        return

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


async def handle_task_cancel(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务取消请求，查找 pending future 并取消，返回 task_cancel_ack。

    当 task_id 对应的 Future 存在于 _pending_responses 时，取消该 Future
    并在设备状态缓存中清除 current_task_id，返回 cancelled=True。
    若找不到对应任务，返回 cancelled=False 并附带 reason。
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task cancel request: task_id=%s device_id=%s",
        task_id, device_id,
    )

    cancelled = False
    reason: Optional[str] = None

    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.cancel()
            cancelled = True
            logger.info(
                "Task cancelled: task_id=%s device_id=%s",
                task_id, device_id,
            )
        else:
            reason = "task_already_done"
    else:
        reason = "task_not_found"
        logger.info(
            "Task cancel: task not found in pending_responses: task_id=%s device_id=%s",
            task_id, device_id,
        )

    # 清除设备缓存中的 current_task_id
    if cancelled:
        async with bridge._lock:
            if device_id and device_id in bridge._devices:
                if bridge._devices[device_id].current_task_id == task_id:
                    bridge._devices[device_id].current_task_id = None

    return MessageBuilder.task_cancel_ack(
        device_id=device_id,
        task_id=task_id,
        cancelled=cancelled,
        reason=reason,
        correlation_id=correlation_id,
    )


async def handle_task_status(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务状态查询，返回结构化 task_status_response。

    从 bridge._devices[device_id] 读取 current_task_id；
    若请求的 task_id 与当前任务一致或存在于 _pending_responses 则返回
    running 状态；否则返回 not_found。
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task status query: task_id=%s device_id=%s",
        task_id, device_id,
    )

    status: str = TaskStatus.FAILED.value
    progress: Optional[float] = None
    current_step: Optional[int] = None

    async with bridge._lock:
        device = bridge._devices.get(device_id) if device_id else None
        if device is not None:
            current_task_id = device.current_task_id
            if task_id and task_id == current_task_id:
                status = TaskStatus.RUNNING.value
            elif task_id and task_id in bridge._pending_responses:
                status = TaskStatus.PENDING.value
            elif not task_id and current_task_id:
                # 未指定 task_id — 返回当前正在执行任务的状态
                task_id = current_task_id
                status = TaskStatus.RUNNING.value
            else:
                status = "not_found"
        else:
            status = "not_found"

    logger.info(
        "Task status response: task_id=%s device_id=%s status=%s",
        task_id, device_id, status,
    )

    return MessageBuilder.task_status_response(
        device_id=device_id,
        task_id=task_id,
        status=status,
        progress=progress,
        current_step=current_step,
        correlation_id=correlation_id,
    )

