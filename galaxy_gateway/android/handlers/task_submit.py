"""
galaxy_gateway/android/handlers/task_submit.py

Handles task_execute and task_submit messages.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_task_execute(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理 task_execute 请求"""
    device_id = message.get("device_id")
    # task_id 优先；若客户端未提供则回退到 message_id（兼容旧版协议）
    task_id = message.get("task_id") or message.get("message_id")
    task_type = message.get("task_type", "generic")
    payload = message.get("payload", {})
    logger.info(
        "Task execute request from %s: task_id=%s, type=%s",
        device_id, task_id, task_type,
    )

    async with bridge._lock:
        if device_id in bridge._devices:
            bridge._devices[device_id].current_task_id = task_id

    return MessageBuilder.task_assign(
        device_id=device_id,
        task_id=task_id,
        task_type=task_type,
        payload=payload,
    )


async def handle_task_submit(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理 TASK_SUBMIT — Android → Gateway 的自然语言任务提交。

    AIP v3 链路：Step 3 (Android → Gateway) — Android 发送 task_submit，
    Gateway 内部通过 DesktopPresenceRuntime → OpenClawd 处理，
    然后返回 task_assign（Step 6: Gateway → Android）。
    """
    payload = message.get("payload", {})
    device_id = message.get("device_id") or payload.get("device_id", "unknown")
    session_id = payload.get("session_id") or message.get("session_id") or "android_default"
    trace_id = message.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}"
    task_id = payload.get("task_id") or message.get("task_id") or str(uuid.uuid4())
    task_text = payload.get("task_text", "").strip()

    if not task_text:
        return MessageBuilder.error(
            device_id,
            "INVALID_TASK_SUBMIT",
            "task_submit missing or empty 'task_text' field",
            correlation_id=task_id,
        )

    logger.info(
        "TASK_SUBMIT received: task_id=%s device_id=%s session_id=%s text=%r",
        task_id, device_id, session_id, task_text[:80],
    )

    # entry_mode 决定是否允许 Android 桥接到远程 Agent Runtime
    entry_mode = str(message.get("entry_mode", "local")).lower()
    require_local_agent = (entry_mode == "local")

    result: Dict[str, Any] = {"success": False, "response": "Processing failed"}

    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        result = await runtime.handle_request(
            message=task_text,
            source="chat",
            device_id=device_id,
            session_id=session_id,
            runtime_session_id=trace_id,
            entry_mode=entry_mode,
        )
    except Exception as runtime_err:
        logger.error(
            "TASK_SUBMIT: DesktopPresenceRuntime 处理失败 | task_id=%s error=%s",
            task_id, runtime_err, exc_info=True,
        )
        return MessageBuilder.error(
            device_id,
            "RUNTIME_ERROR",
            f"Subject core processing error: {runtime_err}",
            correlation_id=task_id,
        )

    success = result.get("success", False)
    response_text = result.get("response", "") or str(result.get("reply", ""))
    runtime_session_id = result.get("runtime_session_id", "")

    # 当本地执行失败或 OpenClawd 无响应时，fallback 到 Android 本地执行
    if not success or response_text == "":
        require_local_agent = True

    goal = response_text if response_text else task_text
    constraints: List[str] = []
    if not success:
        constraints.append(f"Processing failed: {result.get('error', 'unknown error')}")
    if runtime_session_id:
        constraints.append(f"session: {runtime_session_id}")

    task_assign_payload: Dict[str, Any] = {
        "task_id": task_id,
        "goal": goal,
        "constraints": constraints,
        "max_steps": 10,
        "require_local_agent": require_local_agent,
        "trace_id": trace_id,
        "session_id": session_id,
        "runtime_session_id": runtime_session_id,
        "success": success,
    }

    logger.info(
        "TASK_SUBMIT → task_assign: task_id=%s require_local_agent=%s goal=%r",
        task_id, require_local_agent, goal[:80],
    )

    return MessageBuilder.task_assign(
        device_id=device_id,
        task_id=task_id,
        task_type="task_submit",
        payload=task_assign_payload,
    )
