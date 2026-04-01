"""
core/unified/connection_manager.py
===================================
Galaxy 系统统一连接管理器（单例）。

职责：
  - 管理所有设备的 WebSocket 连接
  - 提供带超时控制和指数退避重试的消息发送
  - 支持 WebSocket 直连与 HTTP fallback
  - 提供结构化日志
  - 维护 last_seen / routable 在线态（presence backbone）

所有旧 ConnectionManager 实现（core/routes/_shared.py、
galaxy_gateway/websocket_handler.py、integration/websocket_server.py）
均应委托此类处理实际的连接状态与消息发送。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# PR-2 canonical connection authority sentinel.
# UCM is the sole canonical source of connection/presence truth in Galaxy.
# Importing this sentinel from outside this module signals that the caller
# is reading or writing connection/presence state through the canonical path.
#
# Acceptable roles for external connection maps:
#   - websocket/socket lookup cache (transport layer)
#   - compatibility response helper
#   - transport-layer handle registry
#
# NOT acceptable roles after PR-2:
#   - canonical online/offline truth
#   - canonical readiness truth
#   - canonical device-state write source
# ---------------------------------------------------------------------------
UCM_CONNECTION_AUTHORITY = "UCM::CANONICAL_CONNECTION_AND_PRESENCE_AUTHORITY"

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import WebSocket

from .exceptions import DeviceNotFoundError, DeviceSendError, DeviceTimeoutError
from .models import UnifiedConnectionInfo, UnifiedConnectionState, UnifiedDevice, UnifiedDeviceStatus

logger = logging.getLogger("Galaxy.Unified.ConnectionManager")


class UnifiedConnectionManager:
    """
    统一 WebSocket 连接管理器（进程级单例）。

    公开 API：
        register_connection(device_id, websocket, metadata)
        unregister_connection(device_id)
        send_to_device(device_id, message, *, retries, timeout)
        broadcast(message)
        get_all_devices()
        get_connection(device_id)
    """

    _instance: Optional["UnifiedConnectionManager"] = None

    # 发送重试参数
    _DEFAULT_RETRIES: int = 3
    _DEFAULT_TIMEOUT: float = 10.0
    _BACKOFF_BASE: float = 0.5     # 指数退避基数（秒）
    _MAX_BACKOFF_DELAY: float = 30.0  # 最大退避延迟（秒）

    def __new__(cls) -> "UnifiedConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return

        # device_id → WebSocket
        self._websockets: Dict[str, WebSocket] = {}
        # device_id → UnifiedConnectionInfo
        self._connections: Dict[str, UnifiedConnectionInfo] = {}
        # 命令响应 future: command_id → asyncio.Future
        self._pending_responses: Dict[str, asyncio.Future] = {}
        # 状态订阅者
        self._status_subscribers: List[WebSocket] = []
        self._lock = asyncio.Lock()
        self._initialized = True

        logger.info(
            "UnifiedConnectionManager initialized",
            extra={"event": "init"},
        )

    # ------------------------------------------------------------------
    # 连接注册 / 注销
    # ------------------------------------------------------------------

    async def register_connection(
        self,
        device_id: str,
        websocket: WebSocket,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """注册设备 WebSocket 连接。"""
        async with self._lock:
            self._websockets[device_id] = websocket
            now = time.time()
            self._connections[device_id] = UnifiedConnectionInfo(
                device_id=device_id,
                state=UnifiedConnectionState.CONNECTED,
                connected_at=datetime.utcnow(),
                last_seen=now,
                routable=True,
                metadata=metadata or {},
            )
        logger.info(
            "Device connection registered",
            extra={"event": "register_connection", "device_id": device_id},
        )
        await self._broadcast_status(
            {
                "type": "device_connected",
                "device_id": device_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    async def unregister_connection(self, device_id: str) -> None:
        """注销设备 WebSocket 连接。"""
        async with self._lock:
            self._websockets.pop(device_id, None)
            info = self._connections.get(device_id)
            if info:
                info.state = UnifiedConnectionState.DISCONNECTED
                info.routable = False
                self._connections.pop(device_id, None)

        logger.info(
            "Device connection unregistered",
            extra={"event": "unregister_connection", "device_id": device_id},
        )
        await self._broadcast_status(
            {
                "type": "device_disconnected",
                "device_id": device_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def get_connection(self, device_id: str) -> Optional[UnifiedConnectionInfo]:
        """返回连接信息，不存在则返回 None。"""
        return self._connections.get(device_id)

    def is_device_connected(self, device_id: str) -> bool:
        """判断设备是否有活跃 WebSocket 连接。"""
        return device_id in self._websockets

    # ------------------------------------------------------------------
    # Presence backbone: heartbeat / routable / reconnect / offline
    # ------------------------------------------------------------------

    def update_heartbeat(self, device_id: str) -> bool:
        """记录设备心跳，更新 last_seen 并确保 routable=True。

        若设备不在本地连接表中（仅通过 gateway fallback 连接），静默忽略并返回 False。

        Returns:
            True — 心跳已记录；False — 设备不在本地连接表中。
        """
        info = self._connections.get(device_id)
        if info is None:
            return False
        now = time.time()
        info.last_seen = now
        info.last_heartbeat = datetime.utcnow()
        info.routable = True
        if info.state not in (
            UnifiedConnectionState.CONNECTED,
            UnifiedConnectionState.CONNECTED.value,
        ):
            info.state = UnifiedConnectionState.CONNECTED
        logger.debug(
            "Heartbeat recorded",
            extra={"event": "heartbeat_recorded", "device_id": device_id, "last_seen": now},
        )
        return True

    def mark_offline(self, device_id: str) -> None:
        """将设备标记为不可路由（保留连接记录，但 routable=False）。

        不删除 _connections 条目，保留历史 last_seen；仅用于心跳超时等
        软性下线场景。若要完全移除请调用 unregister_connection()。
        """
        info = self._connections.get(device_id)
        if info is not None:
            info.routable = False
            info.state = UnifiedConnectionState.DISCONNECTED
        # Always remove from active websocket map on soft-offline
        self._websockets.pop(device_id, None)
        logger.info(
            "Device marked offline",
            extra={"event": "mark_offline", "device_id": device_id},
        )

    async def reconnect_patch(
        self,
        device_id: str,
        websocket: WebSocket,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """设备重连时修补现有连接记录（不创建重复 identity）。

        与 register_connection 的区别：重连路径会增加 total_reconnects 计数器
        并将 state 置为 RECONNECTING → CONNECTED，而不是全新注册。
        """
        async with self._lock:
            self._websockets[device_id] = websocket
            now = time.time()
            existing = self._connections.get(device_id)
            if existing is not None:
                existing.state = UnifiedConnectionState.CONNECTED
                existing.last_seen = now
                existing.last_heartbeat = datetime.utcnow()
                existing.routable = True
                existing.total_reconnects += 1
                if metadata:
                    existing.metadata.update(metadata)
            else:
                self._connections[device_id] = UnifiedConnectionInfo(
                    device_id=device_id,
                    state=UnifiedConnectionState.CONNECTED,
                    connected_at=datetime.utcnow(),
                    last_seen=now,
                    routable=True,
                    metadata=metadata or {},
                )
        logger.info(
            "Device connection reconnect-patched",
            extra={"event": "reconnect_patch", "device_id": device_id},
        )
        await self._broadcast_status(
            {
                "type": "device_reconnected",
                "device_id": device_id,
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

    def check_heartbeat_timeouts(self, timeout_seconds: float = 60.0) -> List[str]:
        """扫描所有连接，将超时设备标记为 offline 并返回其 device_id 列表。

        Args:
            timeout_seconds: 超过此秒数未收到心跳则标记 offline。

        Returns:
            被标记为 offline 的设备 ID 列表。
        """
        now = time.time()
        timed_out: List[str] = []
        for device_id, info in list(self._connections.items()):
            if info.last_seen > 0 and (now - info.last_seen) > timeout_seconds:
                self.mark_offline(device_id)
                timed_out.append(device_id)
                logger.warning(
                    "Device heartbeat timeout — marked offline",
                    extra={
                        "event": "heartbeat_timeout",
                        "device_id": device_id,
                        "idle_seconds": now - info.last_seen,
                    },
                )
        return timed_out

    def get_presence_view(self) -> Dict[str, Dict[str, Any]]:
        """返回所有已知设备的 presence 快照。

        键为 device_id，值包含：online、routable、last_seen、state。
        这是 UCM 的 authoritative presence projection。
        """
        result: Dict[str, Dict[str, Any]] = {}
        for device_id, info in self._connections.items():
            connected = device_id in self._websockets
            result[device_id] = {
                "device_id": device_id,
                "online": connected and info.routable,
                "routable": info.routable,
                "last_seen": info.last_seen,
                "state": info.state if isinstance(info.state, str) else info.state.value,
                "total_reconnects": info.total_reconnects,
            }
        return result

    # ------------------------------------------------------------------
    # 消息发送（带超时控制 + 指数退避重试）
    # ------------------------------------------------------------------

    async def send_to_device(
        self,
        device_id: str,
        message: Dict[str, Any],
        *,
        retries: int = _DEFAULT_RETRIES,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> bool:
        """
        向指定设备发送消息。

        优先使用直连 WebSocket；若设备不在本地注册表，尝试通过
        gateway 的 device_router 或 websocket_manager 发送（HTTP fallback）。

        Returns:
            True 表示发送成功，False 表示发送失败。
        """
        # 1. 本地直连 WebSocket
        ws = self._websockets.get(device_id)
        if ws is not None:
            success = await self._send_with_retry(ws, device_id, message, retries, timeout)
            if success:
                return True
            # 直连失败，清理
            await self.unregister_connection(device_id)

        # 2. 尝试通过 gateway websocket_manager 发送
        try:
            from galaxy_gateway.app import websocket_manager as gw_ws_manager  # type: ignore
            if gw_ws_manager and gw_ws_manager.is_device_connected(device_id):
                from galaxy_gateway.protocol import AIPMessage, MessageType  # type: ignore
                aip_msg = AIPMessage(
                    type=MessageType.COMMAND,
                    device_id=device_id,
                    payload=message,
                )
                return await asyncio.wait_for(
                    gw_ws_manager.send_message(device_id, aip_msg),
                    timeout=timeout,
                )
        except Exception as exc:
            logger.debug(
                "Gateway websocket_manager unavailable",
                extra={"event": "fallback_gw_ws", "device_id": device_id, "reason": str(exc)},
            )

        # 3. 尝试通过 device_router 发送（保底）
        try:
            from galaxy_gateway.device_router import device_router  # type: ignore
            device = device_router.get_device(device_id)
            if device and getattr(device, "websocket", None):
                await asyncio.wait_for(
                    device.websocket.send_json(message),
                    timeout=timeout,
                )
                return True
        except Exception as exc:
            logger.debug(
                "device_router fallback failed",
                extra={"event": "fallback_device_router", "device_id": device_id, "reason": str(exc)},
            )

        logger.warning(
            "Failed to send message to device — device not reachable",
            extra={"event": "send_failed", "device_id": device_id},
        )
        return False

    async def _send_with_retry(
        self,
        websocket: WebSocket,
        device_id: str,
        message: Dict[str, Any],
        retries: int,
        timeout: float,
    ) -> bool:
        """带指数退避的 WebSocket 发送。"""
        delay = self._BACKOFF_BASE
        for attempt in range(1, retries + 1):
            try:
                await asyncio.wait_for(websocket.send_json(message), timeout=timeout)
                logger.debug(
                    "Message sent",
                    extra={"event": "send_ok", "device_id": device_id, "attempt": attempt},
                )
                return True
            except asyncio.TimeoutError:
                logger.warning(
                    "Send timeout",
                    extra={"event": "send_timeout", "device_id": device_id, "attempt": attempt},
                )
            except Exception as exc:
                logger.warning(
                    "Send error",
                    extra={"event": "send_error", "device_id": device_id, "attempt": attempt, "reason": str(exc)},
                )
            if attempt < retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._MAX_BACKOFF_DELAY)
        return False

    # ------------------------------------------------------------------
    # 广播
    # ------------------------------------------------------------------

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """广播消息给所有已连接设备。"""
        failed: List[str] = []
        for device_id, ws in list(self._websockets.items()):
            try:
                await ws.send_json(message)
            except Exception as exc:
                logger.warning(
                    "Broadcast to device failed",
                    extra={"event": "broadcast_fail", "device_id": device_id, "reason": str(exc)},
                )
                failed.append(device_id)
        for device_id in failed:
            await self.unregister_connection(device_id)

    # ------------------------------------------------------------------
    # 设备查询
    # ------------------------------------------------------------------

    def get_all_devices(self) -> Dict[str, Any]:
        """
        返回所有已知设备的合并字典（本地 + gateway + device_router）。

        键为 device_id，值为设备信息 dict。
        """
        result: Dict[str, Any] = {}

        # 本地已注册 WebSocket 连接
        for device_id, info in self._connections.items():
            result[device_id] = {
                "device_id": device_id,
                "status": "online",
                "online": True,
                "source": "unified_ws",
                "connected_at": info.connected_at.isoformat() if info.connected_at else None,
                **info.metadata,
            }

        # 合并 gateway websocket_manager 设备
        try:
            from galaxy_gateway.app import websocket_manager as gw_ws_manager  # type: ignore
            if gw_ws_manager:
                for did in gw_ws_manager.get_connected_devices():
                    if did not in result:
                        result[did] = {
                            "device_id": did,
                            "device_type": "unknown",
                            "status": "online",
                            "online": True,
                            "source": "gateway_ws",
                        }
        except Exception:
            pass

        # 合并 device_router 设备
        try:
            from galaxy_gateway.device_router import device_router  # type: ignore
            for did, device in device_router.devices.items():
                if did not in result:
                    result[did] = device.to_dict()
                    result[did]["online"] = True
                    result[did]["source"] = "device_router"
                else:
                    result[did]["online"] = True
                    result[did]["status"] = "online"
        except Exception:
            pass

        return result

    def get_connected_device_ids(self) -> List[str]:
        """返回当前直连的设备 ID 列表。"""
        return list(self._websockets.keys())

    # ------------------------------------------------------------------
    # 状态订阅（供 Dashboard WebSocket 使用）
    # ------------------------------------------------------------------

    async def subscribe_status(self, websocket: WebSocket) -> None:
        """订阅状态推送。"""
        await websocket.accept()
        self._status_subscribers.append(websocket)

    def unsubscribe_status(self, websocket: WebSocket) -> None:
        """取消状态推送订阅。"""
        try:
            self._status_subscribers.remove(websocket)
        except ValueError:
            pass

    async def _broadcast_status(self, status: Dict[str, Any]) -> None:
        failed = []
        for ws in list(self._status_subscribers):
            try:
                await ws.send_json(status)
            except Exception:
                failed.append(ws)
        for ws in failed:
            self.unsubscribe_status(ws)

    # ------------------------------------------------------------------
    # Request-Response 模式（命令 + 等待设备回传）
    # ------------------------------------------------------------------

    async def send_command_and_wait(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any],
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """发送命令并等待设备回传结果（request-response 模式）。"""
        command_id = f"cmd_{uuid.uuid4().hex[:12]}"
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending_responses[command_id] = future

        message = {
            "type": "command",
            "command_id": command_id,
            "command": command,
            "params": params,
            "timestamp": datetime.utcnow().isoformat(),
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

    def resolve_command_response(self, command_id: str, payload: Dict[str, Any]) -> None:
        """设备回传 command_result 时调用，唤醒等待中的 Future。"""
        future = self._pending_responses.get(command_id)
        if future and not future.done():
            future.set_result(payload)
            logger.debug(
                "Command response resolved",
                extra={"event": "cmd_resolved", "command_id": command_id},
            )

    async def push_command_result(self, command_result_dict: Dict[str, Any]) -> None:
        """推送命令执行结果到所有 status 订阅者。"""
        cmd_id = command_result_dict.get("command_id")
        if cmd_id:
            self.resolve_command_response(cmd_id, command_result_dict)

        payload = {
            "type": "command_result",
            "data": command_result_dict,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self._broadcast_status(payload)


# ============================================================================
# 进程级单例访问函数
# ============================================================================


_manager: Optional[UnifiedConnectionManager] = None


def get_unified_connection_manager() -> UnifiedConnectionManager:
    """返回进程级 UnifiedConnectionManager 单例。"""
    global _manager
    if _manager is None:
        _manager = UnifiedConnectionManager()
    return _manager
