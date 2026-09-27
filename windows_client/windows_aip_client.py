"""
Windows AIP v3.0 客户端
=======================

将 Windows 主机作为设备注册到 Galaxy 服务端，
使其与 Android 端一致可被 ReAct Agent 调度。

功能:
  1. 通过 WebSocket 连接服务端 /ws/device/{device_id}
  2. 发送 device_register（AIP v3.0 握手）
  3. 发送 capability_report（supported_actions 列表）
  4. 维护心跳保活
  5. 接收并执行服务端下发的任务命令（统一通过 WindowsExecutionArbiter）

执行管道
--------
所有入站命令经由统一执行仲裁器路由::

    AIP ingress (this file)
        ↓
    WindowsExecutionArbiter.route_command()      ← 唯一执行入口
        ↓  fallback chain: system_api → UIA → GUI → VLM
    WindowsAutonomyManager  (UIA adapter)

旧版本的多路命令分支（bespoke action_types 字典）已被替换。
遗留路径（windows_mcp_server.py、ui_sidebar.py、client.py、
desktop_automation.py）已被弃用，不再是主执行路径。

启动方式(与 Linux / macOS 相同):
    python -m device_client --pair 123456      第一次;同网段自动找主脑
    python -m device_client                    之后
    本文件仍可直接运行,等同于上面的命令。连接层见 device_client/。

Author: Galaxy Team
Version: 2.0.0
"""

import logging
import sys
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("windows-aip-client")


# ============================================================================
# Windows 设备支持的 actions（与 Arbiter fallback chain 对齐）
# ============================================================================

WINDOWS_SUPPORTED_ACTIONS = [
    "get_screen_state",
    "click",
    "type",
    "press_key",
    "press_keys",
    "scroll",
    "find_and_click",
    "find_and_type",
    "screenshot",
]


# ============================================================================
# 懒加载 WindowsExecutionArbiter（统一执行仲裁器）
# ============================================================================

_arbiter = None


def _get_arbiter():
    """Return the singleton :class:`WindowsExecutionArbiter`.

    This is the **only** execution entry point for the AIP client.
    All task_type / command routing goes through ``arbiter.route_command()``.
    """
    global _arbiter
    if _arbiter is None:
        try:
            _client_dir = os.path.dirname(os.path.abspath(__file__))
            _root_dir = os.path.dirname(_client_dir)
            for p in [_client_dir, _root_dir]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from core.windows_execution_arbiter import get_windows_arbiter
            _arbiter = get_windows_arbiter()
            logger.info("WindowsExecutionArbiter 已就绪")
        except Exception as e:
            logger.warning(f"WindowsExecutionArbiter 不可用: {e}")
    return _arbiter


# ============================================================================
# 命令执行 — 统一通过仲裁器路由
# ============================================================================

def _execute_command(task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Route a device command through :class:`WindowsExecutionArbiter`.

    This replaces the previous bespoke per-action branching logic.
    The arbiter applies its strict fallback chain:
    system_api → UIA (via WindowsAutonomyManager) → GUI → VLM.
    """
    arbiter = _get_arbiter()
    if arbiter is None:
        return {"success": False, "error": "execution arbiter unavailable"}

    try:
        result = arbiter.route_command(
            action=task_type,
            params=payload,
            device_id="local",
        )
    except Exception as exc:  # noqa: BLE001
        # 设备端契约(Acceptance Gate A):执行器崩溃绝不外抛——回错误信封,
        # 关联 ID 由上层补齐,消息处理循环保持存活。否则一次执行器故障就会
        # 炸断整个 WS 消息处理。
        logger.error("[%s] 执行仲裁器异常(已兜住): %s", task_type, exc)
        return {"success": False, "error": str(exc)}
    # Normalise to the flat dict shape callers expect
    if isinstance(result, dict) and "result" in result:
        merged = {"success": result.get("success", False)}
        merged.update(result.get("result", {}))
        return merged
    return result


def _execute_agent_task(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a remote ``agent_execute`` payload on the local Windows device.

    Routes through :class:`WindowsExecutionArbiter` as a generic
    ``agent_task`` action, preserving all correlation IDs for end-to-end
    tracing (PR155/PR158).

    Supports the extended **SwarmAgentManifest** context keys introduced in
    PR158: ``system_prompt``, ``tool_schemas``, ``memory_snapshot``, and
    ``manifest_id`` are extracted from the ``context`` sub-dict and forwarded
    to the arbiter when present.

    Parameters
    ----------
    payload:
        Dict from the ``agent_execute`` message body; expected keys::

            agent_id, agent_template, task, session_id, trace_id, task_id, context

        The ``context`` dict may additionally carry::

            system_prompt, tool_schemas, memory_snapshot, manifest_id, member_name
    """
    agent_id = payload.get("agent_id", "")
    task_id = payload.get("task_id", "")
    trace_id = payload.get("trace_id", "")
    session_id = payload.get("session_id", "")
    task_text = payload.get("task", "")
    agent_template = payload.get("agent_template", "")
    context = payload.get("context", {})

    # PR158: manifest_id is carried inside context and forwarded via context dict
    manifest_id = context.get("manifest_id", "")

    logger.info(
        "[agent_execute] agent_id=%s task_id=%s trace_id=%s template=%s "
        "manifest_id=%s task=%.80s",
        agent_id, task_id, trace_id, agent_template, manifest_id, task_text,
    )

    result = _execute_command(
        "agent_task",
        {
            "task": task_text,
            "agent_template": agent_template,
            "context": context,
        },
    )

    # Ensure result is always a plain dict before setting correlation IDs
    if not isinstance(result, dict):
        result = {"success": True, "output": str(result)}

    # Ensure correlation IDs are preserved in the returned result
    result["agent_id"] = agent_id
    result["task_id"] = task_id
    result["trace_id"] = trace_id
    result["session_id"] = session_id
    if manifest_id:
        result["manifest_id"] = manifest_id
    return result


# ============================================================================
# AIP 客户端 —— 连接层三个系统共用(device_client),这里只是配上 Windows 执行插件
# ============================================================================

from device_client.client import DeviceClient  # noqa: E402


class WindowsAIPClient(DeviceClient):
    """Windows 电脑接主脑:``device_client`` 的连接层 + Windows 执行插件(本模块的 ``_execute_command``)。"""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8000,
        device_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        state_file: Optional[str] = None,
    ):
        from device_client.executors.windows import WindowsExecutor

        super().__init__(WindowsExecutor(), host=host, port=port, device_id=device_id, state=state, state_file=state_file)


def _get_os_version() -> str:
    try:
        import platform

        return platform.version()
    except Exception:
        return "unknown"


def main():
    """兼容旧的启动方式;等同于 ``python -m device_client``(固定用 Windows 执行插件)。"""
    from device_client.__main__ import main as _main

    sys.exit(_main(default_executor="windows"))


if __name__ == "__main__":
    main()
