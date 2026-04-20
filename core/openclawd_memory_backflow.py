"""
core/openclawd_memory_backflow.py
==================================

OpenClawd 记忆回流 — 跨设备任务完成后将结果存入记忆 DB。

当 AndroidBridge 收到 ``task_result`` 消息时调用 ``store_task_result()``，
将 task_id / device_id / route_mode 等上下文持久化到 TaskMemory，供后续
LLM 上下文注入与历史查询。

PR-7 — Canonical chain result backflow
---------------------------------------
:func:`store_result_envelope` is the **canonical backflow entry point** for
cross-device results that have been normalised into a
:class:`~core.cross_device_execution_chain.ResultEnvelope`.  It:

1. Writes the result to TaskMemory (same as :func:`store_task_result`).
2. Records the execution in the canonical chain singleton via
   :func:`~core.cross_device_execution_chain.record_chain_execution`.
3. Marks the envelope as ``memory_backflow_stored=True`` so downstream
   consumers (projection, audit) can detect whether backflow has occurred.

The original :func:`store_task_result` is retained for backward compatibility
with the AndroidBridge path that delivers raw ``task_result`` dicts before
they have been wrapped in a ``ResultEnvelope``.

设计原则:
  - 轻量：尽量不阻塞 WebSocket 消息处理循环。
  - 容错：TaskMemory 不可用时静默忽略（非关键路径）。
  - SSOT：直接复用 ``core.task_memory.TaskMemory``，不重复定义存储格式。
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.MemoryBackflow")

# 顶层导入，使测试可通过 patch("core.openclawd_memory_backflow.get_task_memory") 模拟
try:
    from core.task_memory import get_task_memory
except ImportError:
    get_task_memory = None  # type: ignore[assignment]

# PR-7: canonical chain import — non-fatal if not available
try:
    from core.cross_device_execution_chain import (
        ResultEnvelope as _ResultEnvelope,
        record_chain_execution as _record_chain_execution,
        CANONICAL_CHAIN_ORDER as _CANONICAL_CHAIN_ORDER,
    )
    _CHAIN_AVAILABLE = True
except ImportError:
    _CHAIN_AVAILABLE = False


async def store_task_result(
    task_id: str,
    device_id: str,
    route_mode: str,
    result: Dict[str, Any],
    session_id: Optional[str] = None,
) -> None:
    """
    将已完成的跨设备任务结果写入 TaskMemory。

    Parameters
    ----------
    task_id:
        任务唯一标识符（来自 AIP v3 task_result 消息）。
    device_id:
        执行设备 ID（来自 AIP v3 task_result 消息的 device_id 字段）。
    route_mode:
        路由模式，例如 ``"cross_device"``、``"local"``（来自消息的
        ``route_mode`` 字段，缺省为 ``"cross_device"``）。
    result:
        完整的 task_result 消息字典（作为 extra 元数据存储）。
    session_id:
        会话 ID（可选）；若消息中含有则一并透传。
    """
    if get_task_memory is None:
        return

    try:
        mem = get_task_memory()

        # 从 result 消息中提取摘要信息
        status = result.get("status", "unknown")
        # Accept both string status values and the boolean True (some clients send bool)
        if isinstance(status, bool):
            success = status
        else:
            success = str(status).lower() in ("success", "completed", "done")
        task_type = result.get("task_type") or result.get("type", "task_result")
        task_description = result.get("task_description") or f"[{task_type}] task_id={task_id}"
        result_summary = result.get("result_summary") or f"device={device_id} status={status}"

        mem.record_task(
            task=task_description,
            result_summary=result_summary,
            success=success,
            strategy=route_mode,
            session_id=session_id or result.get("session_id", ""),
            tags=["cross_device", route_mode, device_id],
            extra={
                "task_id": task_id,
                "device_id": device_id,
                "route_mode": route_mode,
                "raw_result": {
                    k: v for k, v in result.items()
                    if k not in ("image_base64",)  # 排除大字段
                },
            },
        )

        logger.debug(
            "Memory backflow recorded: task_id=%s device_id=%s route_mode=%s success=%s",
            task_id, device_id, route_mode, success,
        )

    except Exception as exc:
        logger.warning(
            "Memory backflow store failed (non-fatal): task_id=%s error=%s",
            task_id, exc,
        )


async def store_goal_execution_result(
    task_id: str,
    device_id: str,
    status: str,
    result: str,
    *,
    trace_id: str = "",
    route_mode: str = "cross_device",
    session_id: Optional[str] = None,
    group_id: Optional[str] = None,
    subtask_index: Optional[int] = None,
    latency_ms: int = 0,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Canonical backflow entry point for ``GOAL_EXECUTION_RESULT`` messages.

    Writes the result to TaskMemory using the same schema as
    :func:`store_task_result` so that ``goal_execution_result`` and
    ``task_result`` converge to the same canonical result family in storage.

    Parameters
    ----------
    task_id:
        Task identifier from the inbound ``GOAL_EXECUTION_RESULT`` message.
    device_id:
        Source Android device ID.
    status:
        Result status string (e.g. ``"completed"``, ``"failed"``).
    result:
        Human-readable result summary text returned by the device.
    trace_id:
        Distributed trace / runtime session correlation ID.
    route_mode:
        Routing mode, e.g. ``"cross_device"`` (default) or ``"local"``.
    session_id:
        Optional session ID to correlate with an active runtime session.
    group_id:
        Optional parallel group identifier (present for parallel subtasks).
    subtask_index:
        Optional subtask index within the parallel group.
    latency_ms:
        Execution latency in milliseconds reported by the device.
    extra_payload:
        Additional payload fields to include in the ``extra`` metadata.
    """
    if get_task_memory is None:
        return

    try:
        mem = get_task_memory()

        success = str(status).lower() in ("success", "completed", "done", "true")
        task_description = (
            f"[goal_execution_result] task_id={task_id}"
            + (f" group={group_id}[{subtask_index}]" if group_id is not None else "")
        )
        result_summary = (
            f"device={device_id} status={status}"
            + (f" latency={latency_ms}ms" if latency_ms else "")
            + (f" result={str(result)[:120]}" if result else "")
        )

        tags = ["goal_execution_result", route_mode, device_id]
        if group_id:
            tags.append(f"group:{group_id}")

        extra: Dict[str, Any] = {
            "task_id": task_id,
            "device_id": device_id,
            "route_mode": route_mode,
            "trace_id": trace_id,
            "status": status,
            "result": result,
            "latency_ms": latency_ms,
        }
        if group_id is not None:
            extra["group_id"] = group_id
        if subtask_index is not None:
            extra["subtask_index"] = subtask_index
        if extra_payload:
            # Exclude large binary/image fields to prevent bloating TaskMemory records.
            extra["raw_payload"] = {
                k: v for k, v in extra_payload.items()
                if k not in ("image_base64", "screenshot_base64")
            }

        mem.record_task(
            task=task_description,
            result_summary=result_summary,
            success=success,
            strategy=route_mode,
            session_id=session_id or trace_id or "",
            tags=tags,
            extra=extra,
            task_type="goal_execution_result",
        )

        logger.debug(
            "store_goal_execution_result: recorded task_id=%s device_id=%s "
            "status=%s success=%s group_id=%s subtask_index=%s",
            task_id, device_id, status, success, group_id, subtask_index,
        )

    except Exception as exc:
        logger.warning(
            "store_goal_execution_result: memory write failed (non-fatal): "
            "task_id=%s error=%s",
            task_id, exc,
        )


async def store_result_envelope(
    envelope: "Any",
    *,
    chain_metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """Canonical PR-7 backflow entry point for :class:`ResultEnvelope` results.

    Writes the result to TaskMemory, records the execution in the canonical
    chain singleton, and marks the envelope as ``memory_backflow_stored=True``.

    Parameters
    ----------
    envelope:
        A :class:`~core.cross_device_execution_chain.ResultEnvelope` instance
        produced by the canonical cross-device execution chain.
    chain_metadata:
        Optional extra metadata to attach to the chain execution record
        (e.g. ``authority_role``, ``session_id``, ``projection_id``).

    Returns
    -------
    bool
        True if backflow storage succeeded; False if it was skipped or failed.
    """
    if not _CHAIN_AVAILABLE:
        # Degrade gracefully — log and return False rather than raising.
        logger.debug(
            "store_result_envelope: canonical chain module unavailable; "
            "falling back to store_task_result for task_id=%s",
            getattr(envelope, "task_id", "unknown"),
        )
        return False

    task_id = getattr(envelope, "task_id", "") or ""
    device_id = getattr(envelope, "device_id", "") or ""
    route_mode = getattr(envelope, "route_mode", "cross_device") or "cross_device"
    session_id = getattr(envelope, "session_id", None)
    trace_id = getattr(envelope, "trace_id", None)

    # Write to TaskMemory (non-fatal)
    if get_task_memory is not None:
        try:
            mem = get_task_memory()
            success = getattr(envelope, "success", False)
            status = getattr(envelope, "status", "unknown")
            error = getattr(envelope, "error", None)
            result_summary = (
                f"device={device_id} status={status}"
                + (f" error={error}" if error else "")
            )
            mem.record_task(
                task=f"[cross_device_chain] task_id={task_id}",
                result_summary=result_summary,
                success=success,
                strategy=route_mode,
                session_id=session_id or "",
                tags=["cross_device", route_mode, device_id, "result_envelope"],
                extra={
                    "task_id": task_id,
                    "device_id": device_id,
                    "route_mode": route_mode,
                    "trace_id": trace_id,
                    "result_envelope": {
                        k: v for k, v in envelope.to_dict().items()
                        if k not in ("image_base64", "screenshot_base64", "raw_bytes")
                    },
                    "chain_metadata": chain_metadata or {},
                },
            )
            # Mark the envelope so downstream consumers know backflow occurred.
            envelope.memory_backflow_stored = True
        except Exception as exc:
            logger.warning(
                "store_result_envelope: memory write failed (non-fatal): "
                "task_id=%s error=%s",
                task_id,
                exc,
            )

    # Record the full canonical chain execution in the chain singleton.
    try:
        _record_chain_execution(
            task_id=task_id,
            trace_id=trace_id,
            device_id=device_id,
            route_mode=route_mode,
            steps_completed=list(_CANONICAL_CHAIN_ORDER),
            result_envelope=envelope,
            extra=chain_metadata or {},
        )
    except Exception as exc:
        logger.warning(
            "store_result_envelope: chain record failed (non-fatal): "
            "task_id=%s error=%s",
            task_id,
            exc,
        )
        return False

    logger.debug(
        "store_result_envelope: backflow complete: "
        "task_id=%s device_id=%s route_mode=%s success=%s memory=%s",
        task_id,
        device_id,
        route_mode,
        getattr(envelope, "success", False),
        getattr(envelope, "memory_backflow_stored", False),
    )
    return True
