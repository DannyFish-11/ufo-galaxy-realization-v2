"""
core/openclawd_memory_backflow.py
==================================

OpenClawd 记忆回流 — 跨设备任务完成后将结果存入记忆 DB。

当 AndroidBridge 收到 ``task_result`` 消息时调用 ``store_task_result()``，
将 task_id / device_id / route_mode 等上下文持久化到 TaskMemory，供后续
LLM 上下文注入与历史查询。

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
