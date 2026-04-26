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

from galaxy_gateway.protocol.aip_v3 import TaskStatus
from galaxy_gateway.android.message_builder import MessageBuilder

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

# PR-4V2: Android participant/session/runtime truth ingress — top-level import
# so tests can patch() it and import failures are handled gracefully.
try:
    from core.android_participant_truth_ingress import ingest_android_participant_truth_message as _ingest_participant_truth
except ImportError:
    _ingest_participant_truth = None  # type: ignore[assignment]

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


def _try_ingest_participant_truth(message: Dict[str, Any], truth_kind: str) -> None:
    """Best-effort ingest *message* as Android participant truth into V2 canonical state.

    Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
    when the ingress module is available.  The *message* dict is enriched with
    the caller-supplied *truth_kind* value (which maps to
    :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`)
    before passing to the ingress function.

    Failures are logged at DEBUG level and never propagated — this is an
    additive PR-4V2 path that complements the existing PR-13 ``_try_reconcile``
    path; it must not disrupt existing handler behaviour.
    """
    if _ingest_participant_truth is None:
        return
    try:
        enriched = dict(message)
        # Inject truth_kind so the ingress envelope extractor classifies it
        # correctly even if the raw Android message does not carry the field.
        enriched.setdefault("truth_kind", truth_kind)
        outcome = _ingest_participant_truth(enriched)
        if outcome.was_reconciled:
            logger.debug(
                "PR-4V2 participant truth ingested: truth_kind=%s contract_id=%r "
                "session_id=%r was_reconciled=True canonical_update=%r phase=%r",
                truth_kind,
                outcome.envelope.contract_id if outcome.envelope else "",
                outcome.envelope.session_id if outcome.envelope else "",
                outcome.canonical_update,
                outcome.tracking_record_phase,
            )
        elif outcome.reject_reason:
            logger.debug(
                "PR-4V2 participant truth skipped: truth_kind=%s reason=%r",
                truth_kind,
                outcome.reject_reason,
            )
    except Exception as exc:
        logger.debug("PR-4V2 participant truth ingest failed (non-fatal): %s", exc)


async def handle_task_result(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> None:
    """处理任务结果，完成 Future 并触发 OpenClawd 记忆回流

    Durable idempotency guard
    -------------------------
    Before processing, the task_id is checked against the cross-restart durable
    result-ID store.  If the result was already processed in a previous V2
    process lifetime (e.g. Android reconnects after a V2 restart and replays
    the same task_result), the message is suppressed here so that the Future
    is not double-resolved and memory backflow is not duplicated.
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    result_status = message.get("status", "unknown")
    route_mode = message.get("route_mode", "cross_device")

    logger.info(
        "Task result received: task_id=%s device_id=%s status=%s",
        task_id, device_id, result_status,
    )

    # ── Durable idempotency: suppress cross-restart duplicate results ──
    if task_id:
        try:
            from core.durable_result_idempotency import (
                check_result_idempotency,
                record_result_idempotency,
            )
            if check_result_idempotency(task_id):
                logger.info(
                    "task_lifecycle: duplicate task result suppressed (durable store): "
                    "task_id=%s device_id=%s",
                    task_id,
                    device_id,
                )
                return
            record_result_idempotency(task_id)
        except Exception as _idem_exc:
            logger.debug(
                "task_lifecycle: durable idempotency check skipped (non-fatal): %s",
                _idem_exc,
            )

    # PR-13: reconcile inbound signal against host-side execution tracker
    _try_reconcile(message)
    # PR-4V2: ingest Android participant truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "result")

    # 完成等待的 Future
    if task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    # 更新设备状态
    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    # PR-1 P0 Completion Closure: notify DeviceRouter so that any
    # dispatch_to_websocket awaiter blocked on task_events[task_id].wait()
    # is woken immediately by a real completion event rather than a timeout.
    if task_id:
        try:
            from galaxy_gateway.device_router import device_router as _device_router

            _dr_result = {
                **message,
                "success": result_status not in ("failed", "error", "cancelled"),
                "via": "task_lifecycle.handle_task_result",
            }
            await _device_router.handle_task_result(task_id, _dr_result)
            logger.debug(
                "PR-1 P0: task_result → device_router.handle_task_result task_id=%r",
                task_id,
            )
        except Exception as _dr_exc:
            logger.debug(
                "PR-1 P0: device_router.handle_task_result skipped (non-fatal): "
                "task_id=%r exc=%s",
                task_id,
                _dr_exc,
            )

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
    # PR-4V2: ingest Android task_phase truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "task_phase")

    # 清理残余 pending future
    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses.pop(task_id)
        if not future.done():
            future.set_result(message)

    async with bridge._lock:
        if device_id and device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = None

    # PR-1 P0 Completion Closure: notify DeviceRouter so that any
    # dispatch_to_websocket awaiter blocked on task_events[task_id].wait()
    # is woken immediately by a real completion event rather than a timeout.
    if task_id:
        try:
            from galaxy_gateway.device_router import device_router as _device_router

            _dr_result = {
                **message,
                "success": final_status not in ("failed", "error", "cancelled"),
                "via": "task_lifecycle.handle_task_end",
            }
            await _device_router.handle_task_result(task_id, _dr_result)
            logger.debug(
                "PR-1 P0: task_end → device_router.handle_task_result task_id=%r",
                task_id,
            )
        except Exception as _dr_exc:
            logger.debug(
                "PR-1 P0: device_router.handle_task_result (task_end) skipped "
                "(non-fatal): task_id=%r exc=%s",
                task_id,
                _dr_exc,
            )

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
    # PR-4V2: ingest Android progress as status truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "status")


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
    # PR-4V2: ingest Android failure truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "failure")


async def handle_task_cancel(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务取消请求，取消待处理 Future 并返回 task_cancel_ack。

    链路：Android → task_cancel → 查找 _pending_responses[task_id]
    → 标记 Future 为已取消 → 更新设备 current_task_id → 返回 task_cancel_ack
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task cancel requested: task_id=%s device_id=%s",
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
                "Task cancelled successfully: task_id=%s device_id=%s",
                task_id, device_id,
            )
        else:
            reason = "task_already_completed"
            logger.info(
                "Task cancel: future already done: task_id=%s device_id=%s",
                task_id, device_id,
            )
    else:
        reason = "task_not_found"
        logger.info(
            "Task cancel: task not found in pending_responses: task_id=%s device_id=%s",
            task_id, device_id,
        )

    # 清理设备端 current_task_id
    async with bridge._lock:
        if device_id and device_id in bridge._devices:
            if bridge._devices[device_id].current_task_id == task_id:
                bridge._devices[device_id].current_task_id = None

    # PR-4V2: ingest Android cancel truth into V2 canonical orchestration
    _try_ingest_participant_truth(message, "cancel")

    return MessageBuilder.task_cancel_ack(
        device_id=device_id or "",
        task_id=task_id,
        cancelled=cancelled,
        reason=reason,
        correlation_id=correlation_id,
    )


async def handle_task_status(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """处理任务状态查询，返回结构化 task_status_response。

    链路：Android → task_status → 查询 current_task_id / _pending_responses
    → 返回 task_status_response
    """
    task_id = message.get("task_id")
    device_id = message.get("device_id")
    correlation_id = message.get("message_id")

    logger.info(
        "Task status query: task_id=%s device_id=%s",
        task_id, device_id,
    )

    # 基于 _pending_responses 和设备缓存确定真实状态
    if task_id and task_id in bridge._pending_responses:
        future = bridge._pending_responses[task_id]
        if future.cancelled():
            status = TaskStatus.CANCELLED.value
        elif future.done():
            status = TaskStatus.COMPLETED.value
        else:
            status = TaskStatus.RUNNING.value
    else:
        # 检查设备当前任务
        async with bridge._lock:
            device = bridge._devices.get(device_id or "")
        if device and device.current_task_id == task_id and task_id:
            status = TaskStatus.RUNNING.value
        else:
            status = TaskStatus.COMPLETED.value

    logger.info(
        "Task status resolved: task_id=%s device_id=%s status=%s",
        task_id, device_id, status,
    )

    # PR-4V2: ingest Android status truth into V2 canonical orchestration.
    # Enrich the message with the resolved status so the ingress extractor
    # can read it as task_phase_value via payload.status.
    _status_enriched = dict(message)
    _status_enriched["payload"] = {**(message.get("payload") or {}), "status": status}
    _try_ingest_participant_truth(_status_enriched, "status")

    return MessageBuilder.task_status_response(
        device_id=device_id or "",
        task_id=task_id,
        status=status,
        correlation_id=correlation_id,
    )

