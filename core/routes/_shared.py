"""
Galaxy - Shared Route State
================================

Module-level singletons shared across all route modules:
  - RouteConnectionPool  (WebSocket connection pool)
  - registered_devices (device registry)
  - task_queue         (in-memory task store)
  - node_status_cache  (node health cache)
  - command_results    (unified-command result store)
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("Galaxy.API")

# ---------------------------------------------------------------------------
# Device registry persistence helpers
# ---------------------------------------------------------------------------

_DEVICE_REGISTRY_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "registered_devices.json"


def _load_registered_devices() -> Dict[str, Dict[str, Any]]:
    """Load persisted device registry from disk (best-effort)."""
    try:
        if _DEVICE_REGISTRY_FILE.exists():
            with open(_DEVICE_REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Mark all loaded devices as offline (they need to re-heartbeat)
            for dev in data.values():
                dev["status"] = "offline"
                dev["online"] = False
            logger.info(f"Loaded {len(data)} persisted devices from {_DEVICE_REGISTRY_FILE}")
            return data
    except Exception as e:
        logger.warning(f"Failed to load device registry: {e}")
    return {}


def _save_registered_devices(devices: Dict[str, Dict[str, Any]]) -> None:
    """Persist device registry to disk (best-effort, non-blocking intent)."""
    try:
        os.makedirs(_DEVICE_REGISTRY_FILE.parent, exist_ok=True)
        with open(_DEVICE_REGISTRY_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.warning(f"Failed to save device registry: {e}")


# ============================================================================
# WebSocket Connection Manager
# ============================================================================

class RouteConnectionPool:
    """
    WebSocket 连接管理器。

    委托 core.unified.UnifiedConnectionManager 管理实际连接状态，
    保留原有接口以维持向后兼容。
    """

    def __init__(self):
        # 保留 active_devices 供直接赋值的旧代码读取，但写操作会同步到统一管理器
        self.active_devices: Dict[str, WebSocket] = {}
        self.status_subscribers: Set[WebSocket] = set()
        # 命令响应等待器: command_id → asyncio.Future
        self._pending_responses: Dict[str, asyncio.Future] = {}

    # ------------------------------------------------------------------
    # 内部：懒加载统一管理器（避免循环导入）
    # ------------------------------------------------------------------

    @staticmethod
    def _unified() -> "UnifiedConnectionManager":  # type: ignore[name-defined]
        from core.unified.connection_manager import get_unified_connection_manager
        return get_unified_connection_manager()

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    async def connect_device(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_devices[device_id] = websocket
        logger.info(f"设备已连接: {device_id}")
        # 同步到统一连接管理器（不再重复 accept）
        ucm = self._unified()
        ucm._websockets[device_id] = websocket
        from core.unified.models import UnifiedConnectionInfo, UnifiedConnectionState
        from datetime import datetime as _dt
        ucm._connections[device_id] = UnifiedConnectionInfo(
            device_id=device_id,
            state=UnifiedConnectionState.CONNECTED,
            connected_at=_dt.utcnow(),
        )
        await self.broadcast_status({
            "type": "device_connected",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat()
        })

    def disconnect_device(self, device_id: str):
        self.active_devices.pop(device_id, None)
        logger.info(f"设备已断开: {device_id}")
        # 同步到统一连接管理器
        ucm = self._unified()
        ucm._websockets.pop(device_id, None)
        ucm._connections.pop(device_id, None)

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """委托统一连接管理器发送消息（含多路径 fallback）。"""
        # 1. 优先查本地 active_devices（存量旧路径兼容）
        ws = self.active_devices.get(device_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"发送消息到设备 {device_id} 失败: {e}")
                self.disconnect_device(device_id)

        # 2. 委托统一管理器（包含 gateway fallback 逻辑）
        return await self._unified().send_to_device(device_id, message)

    def get_all_devices(self) -> Dict[str, Dict[str, Any]]:
        """委托统一连接管理器合并所有来源的设备信息。"""
        all_devices = dict(registered_devices)
        unified_devices = self._unified().get_all_devices()
        for did, info in unified_devices.items():
            if did not in all_devices:
                all_devices[did] = info
            else:
                # 已有条目时，用统一管理器的在线状态覆盖
                all_devices[did]["online"] = info.get("online", all_devices[did].get("online", False))
                all_devices[did]["status"] = info.get("status", all_devices[did].get("status", "offline"))
        return all_devices

    async def broadcast_to_devices(self, message: dict):
        disconnected = []
        for device_id, ws in self.active_devices.items():
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.debug(f"广播消息到设备 {device_id} 失败: {e}")
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
            except Exception as e:
                logger.debug(f"状态推送到订阅者失败: {e}")
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


# 向后兼容别名 — 部分模块和测试通过此名称引用
ConnectionManager = RouteConnectionPool


# ============================================================================
# Global Shared State
# ============================================================================

connection_manager = RouteConnectionPool()

# 设备注册表（启动时从磁盘加载）
registered_devices: Dict[str, Dict[str, Any]] = _load_registered_devices()
registered_devices_lock = asyncio.Lock()

# 任务队列
task_queue: Dict[str, Dict[str, Any]] = {}
task_queue_lock = asyncio.Lock()

# 节点状态缓存
node_status_cache: Dict[str, Dict[str, Any]] = {}
node_status_cache_lock = asyncio.Lock()

# 统一命令结果存储
command_results: Dict[str, Dict[str, Any]] = {}
command_results_lock = asyncio.Lock()
