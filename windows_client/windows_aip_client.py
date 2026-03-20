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

启动方式:
    python windows_client/windows_aip_client.py --host 127.0.0.1 --port 8000

Author: Galaxy Team
Version: 2.0.0
"""

import asyncio
import json
import logging
import sys
import os
import socket
import time
import uuid
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

    result = arbiter.route_command(
        action=task_type,
        params=payload,
        device_id="local",
    )
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
# AIP 客户端
# ============================================================================

class WindowsAIPClient:
    """Windows AIP v3.0 客户端"""

    PROTOCOL_VERSION = "3.0"
    HEARTBEAT_INTERVAL = 30  # 秒

    def __init__(self, host: str = "127.0.0.1", port: int = 8000, device_id: str = None):
        self.host = host
        self.port = port
        self.device_id = device_id or f"windows_{socket.gethostname()}_{uuid.uuid4().hex[:6]}"
        self._ws = None
        self._running = False
        self._on_event_stream = None

    def set_event_stream_callback(self, callback):
        """Set callback for event_stream messages from the EventBus."""
        self._on_event_stream = callback

    # ------------------------------------------------------------------
    # 消息构建
    # ------------------------------------------------------------------

    def _base_message(self, msg_type: str) -> Dict[str, Any]:
        return {
            "type": msg_type,
            "version": self.PROTOCOL_VERSION,
            "device_id": self.device_id,
            "timestamp": time.time(),
            "message_id": uuid.uuid4().hex,
        }

    def _device_register_msg(self) -> Dict[str, Any]:
        msg = self._base_message("device_register")
        msg.update({
            "device_type": "windows_desktop",
            "platform": "windows",
            "name": socket.gethostname(),
            "model": "Windows PC",
            "os_version": _get_os_version(),
            "capabilities": WINDOWS_SUPPORTED_ACTIONS,
            "supported_actions": WINDOWS_SUPPORTED_ACTIONS,
        })
        return msg

    def _capability_report_msg(self) -> Dict[str, Any]:
        msg = self._base_message("capability_report")
        msg.update({
            "platform": "windows",
            "device_type": "windows_desktop",
            "supported_actions": WINDOWS_SUPPORTED_ACTIONS,
        })
        return msg

    def _heartbeat_msg(self) -> Dict[str, Any]:
        return self._base_message("heartbeat")

    def _task_result_msg(self, task_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("task_result")
        msg.update({
            "task_id": task_id,
            "status": "completed" if result.get("success") else "failed",
            "result": result,
        })
        return msg

    def _command_result_msg(self, command_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
        msg = self._base_message("command_result")
        msg.update({
            "command_id": command_id,
            "payload": result,
        })
        return msg

    def _agent_execute_result_msg(
        self,
        command_id: str,
        agent_payload: Dict[str, Any],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Build an ``agent_execute_result`` message preserving all correlation IDs (PR155/PR158)."""
        msg = self._base_message("agent_execute_result")
        msg.update({
            "command_id": command_id,
            "agent_id": result.get("agent_id") or agent_payload.get("agent_id", ""),
            "task_id": result.get("task_id") or agent_payload.get("task_id", ""),
            "trace_id": result.get("trace_id") or agent_payload.get("trace_id", ""),
            "session_id": result.get("session_id") or agent_payload.get("session_id", ""),
            "status": "completed" if result.get("success", True) else "failed",
            "result": result,
        })
        # PR158: propagate manifest_id when present
        manifest_id = result.get("manifest_id") or agent_payload.get("context", {}).get("manifest_id", "")
        if manifest_id:
            msg["manifest_id"] = manifest_id
        return msg

    # ------------------------------------------------------------------
    # 消息处理
    # ------------------------------------------------------------------

    async def _handle_message(self, data: Dict[str, Any]):
        msg_type = data.get("type", "")

        if msg_type == "event_stream":
            # Log events from the unified EventBus
            event_type = data.get("event_type", "")
            source = data.get("source", "")
            event_data = data.get("data", {})
            logger.info(f"[EventStream] {event_type} from {source}: {json.dumps(event_data, ensure_ascii=False)[:200]}")
            # Invoke callback if set
            if self._on_event_stream:
                self._on_event_stream(data)
            return

        if msg_type in ("device_register_ack", "heartbeat_ack", "capability_report_ack"):
            logger.debug(f"收到 ACK: {msg_type}")
            return

        if msg_type in ("task_assign", "task_execute"):
            task_id = data.get("task_id") or data.get("message_id", "")
            task_type = data.get("task_type", "")
            payload = data.get("payload", {})
            logger.info(f"收到任务: {task_id} type={task_type}")
            result = await asyncio.get_event_loop().run_in_executor(
                None, _execute_command, task_type, payload
            )
            await self._send(self._task_result_msg(task_id, result))
            return

        if msg_type == "command":
            cmd_id = data.get("command_id", "")
            command = data.get("command", "")
            params = data.get("params", {})
            # PR155: agent_execute dispatched via route_command arrives as
            # a "command" envelope with command="agent_execute"
            if command == "agent_execute":
                agent_payload = params if isinstance(params, dict) else {}
                # Merge top-level correlation fields from the envelope
                for field in ("agent_id", "task_id", "trace_id", "session_id"):
                    if field not in agent_payload and data.get(field):
                        agent_payload[field] = data[field]
                agent_payload.setdefault("task_id", cmd_id)
                logger.info(
                    f"收到 agent_execute: agent_id={agent_payload.get('agent_id')} "
                    f"task_id={agent_payload.get('task_id')} "
                    f"trace_id={agent_payload.get('trace_id')}"
                )
                result = await asyncio.get_event_loop().run_in_executor(
                    None, _execute_agent_task, agent_payload
                )
                await self._send(self._agent_execute_result_msg(cmd_id, agent_payload, result))
                return
            logger.info(f"收到命令: {cmd_id} cmd={command}")
            result = await asyncio.get_event_loop().run_in_executor(
                None, _execute_command, command, params
            )
            await self._send(self._command_result_msg(cmd_id, result))
            return

        logger.debug(f"未处理的消息类型: {msg_type}")

    # ------------------------------------------------------------------
    # 网络层
    # ------------------------------------------------------------------

    async def _send(self, message: Dict[str, Any]):
        if self._ws:
            try:
                await self._ws.send(json.dumps(message, ensure_ascii=False))
            except Exception as e:
                logger.error(f"发送消息失败: {e}")

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)
            if self._running:
                await self._send(self._heartbeat_msg())

    async def run(self):
        """连接服务端并保持运行"""
        try:
            import websockets
        except ImportError:
            logger.error("缺少 websockets 库，请运行: pip install websockets")
            return

        uri = f"ws://{self.host}:{self.port}/ws/device/{self.device_id}"
        logger.info(f"连接服务端: {uri}")
        self._running = True

        while self._running:
            try:
                async with websockets.connect(uri) as ws:
                    self._ws = ws
                    logger.info(f"WebSocket 已连接，device_id={self.device_id}")

                    # AIP v3.0 握手
                    await self._send(self._device_register_msg())
                    await asyncio.sleep(0.5)
                    await self._send(self._capability_report_msg())

                    # 启动心跳
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop())

                    try:
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                                await self._handle_message(data)
                            except json.JSONDecodeError:
                                logger.warning(f"无效 JSON: {raw[:100]}")
                    finally:
                        heartbeat_task.cancel()
                        self._ws = None

            except Exception as e:
                logger.warning(f"连接断开: {e}，5 秒后重连…")
                await asyncio.sleep(5)

    def stop(self):
        self._running = False


# ============================================================================
# 工具函数
# ============================================================================

def _get_os_version() -> str:
    try:
        import platform
        return platform.version()
    except Exception:
        return "unknown"


# ============================================================================
# 入口
# ============================================================================

def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="Windows AIP v3.0 Client")
    parser.add_argument("--host", default="127.0.0.1", help="服务端地址")
    parser.add_argument("--port", type=int, default=8000, help="服务端端口")
    parser.add_argument("--device-id", default=None, help="自定义设备 ID")
    args = parser.parse_args()

    client = WindowsAIPClient(
        host=args.host,
        port=args.port,
        device_id=args.device_id,
    )

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        logger.info("客户端已停止")


if __name__ == "__main__":
    main()
