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
  5. 接收并执行服务端下发的任务命令（使用 autonomy_manager）

启动方式:
    python windows_client/windows_aip_client.py --host 127.0.0.1 --port 8000

Author: Galaxy Team
Version: 1.0.0
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
# Windows 设备支持的 actions（与 MCP Server 工具对齐）
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
# 懒加载 WindowsAutonomyManager
# ============================================================================

_manager = None


def _get_manager():
    global _manager
    if _manager is None:
        try:
            _client_dir = os.path.dirname(os.path.abspath(__file__))
            _root_dir = os.path.dirname(_client_dir)
            for p in [_client_dir, _root_dir]:
                if p not in sys.path:
                    sys.path.insert(0, p)
            from windows_client.autonomy.autonomy_manager import WindowsAutonomyManager
            _manager = WindowsAutonomyManager()
            logger.info("WindowsAutonomyManager 已就绪")
        except Exception as e:
            logger.warning(f"WindowsAutonomyManager 不可用: {e}")
    return _manager


# ============================================================================
# 命令执行
# ============================================================================

def _execute_command(task_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """根据 task_type 调用本地能力"""
    if task_type == "screenshot":
        try:
            import PIL.ImageGrab as ImageGrab
            import io, base64
            img = ImageGrab.grab()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {"success": True, "image_base64": b64}
        except Exception as e:
            return {"success": False, "error": str(e)}

    manager = _get_manager()
    if manager is None:
        return {"success": False, "error": "autonomy manager unavailable"}

    action_types = {
        "get_screen_state": lambda p: manager.get_screen_state(),
        "click": lambda p: manager.execute_action({"type": "click", "params": p}),
        "type": lambda p: manager.execute_action({"type": "type", "params": p}),
        "press_key": lambda p: manager.execute_action({"type": "press_key", "params": p}),
        "press_keys": lambda p: manager.execute_action({"type": "press_keys", "params": p}),
        "scroll": lambda p: manager.execute_action({"type": "scroll", "params": p}),
        "find_and_click": lambda p: manager.execute_action({"type": "find_and_click", "params": p}),
        "find_and_type": lambda p: manager.execute_action({"type": "find_and_type", "params": p}),
    }

    handler = action_types.get(task_type)
    if handler:
        return handler(payload)

    # 通用 execute_task 兼容
    return manager.execute_action({"type": task_type, "params": payload})


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
