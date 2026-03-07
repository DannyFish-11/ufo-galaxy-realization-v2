"""
UFO Galaxy - Shared Route State
================================

Module-level singletons shared across all route modules:
  - ConnectionManager  (WebSocket connection pool)
  - registered_devices (device registry)
  - task_queue         (in-memory task store)
  - node_status_cache  (node health cache)
  - command_results    (unified-command result store)
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("UFO-Galaxy.API")


# ============================================================================
# WebSocket Connection Manager
# ============================================================================

class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_devices: Dict[str, WebSocket] = {}
        self.status_subscribers: Set[WebSocket] = set()
        # 命令响应等待器: command_id → asyncio.Future
        self._pending_responses: Dict[str, asyncio.Future] = {}

    async def connect_device(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_devices[device_id] = websocket
        logger.info(f"设备已连接: {device_id}")
        await self.broadcast_status({
            "type": "device_connected",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat()
        })

    def disconnect_device(self, device_id: str):
        self.active_devices.pop(device_id, None)
        logger.info(f"设备已断开: {device_id}")

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        ws = self.active_devices.get(device_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"发送消息到设备 {device_id} 失败: {e}")
                self.disconnect_device(device_id)
        return False

    async def broadcast_to_devices(self, message: dict):
        disconnected = []
        for device_id, ws in self.active_devices.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(device_id)
        for d in disconnected:
            self.disconnect_device(d)

    async def subscribe_status(self, websocket: WebSocket):
        await websocket.accept()
        self.status_subscribers.add(websocket)

    def unsubscribe_status(self, websocket: WebSocket):
        self.status_subscribers.discard(websocket)

    async def broadcast_status(self, status: dict):
        disconnected = []
        for ws in self.status_subscribers:
            try:
                await ws.send_json(status)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.status_subscribers.discard(ws)

    async def send_command_and_wait(
        self, device_id: str, command: str, params: dict, timeout: float = 15.0
    ) -> dict:
        """发送命令到设备并等待设备回传结果 (request-response 模式)"""
        command_id = f"cmd_{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_responses[command_id] = future

        message = {
            "type": "command",
            "command_id": command_id,
            "command": command,
            "params": params,
            "timestamp": datetime.now().isoformat(),
        }

        sent = await self.send_to_device(device_id, message)
        if not sent:
            self._pending_responses.pop(command_id, None)
            return {"error": f"Failed to send command to device {device_id}"}

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return {"error": f"Command {command_id} timed out after {timeout}s"}
        finally:
            self._pending_responses.pop(command_id, None)

    def resolve_command_response(self, command_id: str, payload: dict):
        """设备回传 command_result 时调用，唤醒等待中的 Future"""
        future = self._pending_responses.get(command_id)
        if future and not future.done():
            future.set_result(payload)
            logger.debug(f"命令响应已匹配: {command_id}")
        else:
            logger.debug(f"收到无人等待的命令响应: {command_id}")

    async def push_command_result(self, command_result_dict: dict):
        """推送命令执行结果到所有 status 订阅者和相关设备"""
        cmd_id = command_result_dict.get("command_id")
        if cmd_id:
            self.resolve_command_response(cmd_id, command_result_dict)

        payload = {
            "type": "command_result",
            "data": command_result_dict,
            "timestamp": datetime.now().isoformat(),
        }
        await self.broadcast_status(payload)
        for target in command_result_dict.get("targets", {}).keys():
            if target in self.active_devices:
                await self.send_to_device(target, payload)


# ============================================================================
# Global Shared State
# ============================================================================

connection_manager = ConnectionManager()

# 设备注册表
registered_devices: Dict[str, Dict[str, Any]] = {}

# 任务队列
task_queue: Dict[str, Dict[str, Any]] = {}

# 节点状态缓存
node_status_cache: Dict[str, Dict[str, Any]] = {}

# 统一命令结果存储
command_results: Dict[str, Dict[str, Any]] = {}
