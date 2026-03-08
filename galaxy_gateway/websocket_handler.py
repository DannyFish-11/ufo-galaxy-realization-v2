"""
WebSocket Handler - WebSocket 连接处理器

处理与 Android Agent 和其他设备的 WebSocket 连接。
所有 incoming 消息通过 :func:`parse_message_compat` 规范化为 AIP v3
格式后再分发给各处理器。响应消息也使用 AIP v3 字段。

支持的 incoming 协议版本：AIP/1.0、AIP/2.0、AIP/3.0（向后兼容）。

Author: Manus AI
Version: 2.0
Date: 2026-03-07
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set
import uuid
from fastapi import WebSocket, WebSocketDisconnect
from galaxy_gateway.device_router import device_router, map_device_type_to_platform
from galaxy_gateway.protocol.compat import parse_message_compat
from galaxy_gateway.protocol.aip_v3 import MessageType

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.device_connections: Dict[str, str] = {}  # device_id -> connection_id
    
    async def connect(self, websocket: WebSocket, connection_id: str):
        """接受新连接"""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        logger.info(f"✅ WebSocket 连接建立: {connection_id}")
    
    def disconnect(self, connection_id: str):
        """断开连接"""
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
            
            # 注销设备
            device_id = None
            for did, cid in self.device_connections.items():
                if cid == connection_id:
                    device_id = did
                    break
            
            if device_id:
                device_router.unregister_device(device_id)
                del self.device_connections[device_id]

                # 同步到 core 的 registered_devices
                try:
                    from core.routes._shared import registered_devices as core_registered_devices
                    if device_id in core_registered_devices:
                        core_registered_devices[device_id]["status"] = "offline"
                        core_registered_devices[device_id]["online"] = False
                except Exception:
                    pass

            logger.info(f"✅ WebSocket 连接断开: {connection_id}")
    
    async def send_message(self, connection_id: str, message: Dict):
        """发送消息到指定连接"""
        if connection_id in self.active_connections:
            websocket = self.active_connections[connection_id]
            await websocket.send_json(message)
    
    async def send_to_device(self, device_id: str, message: Dict):
        """发送消息到指定设备"""
        if device_id in self.device_connections:
            connection_id = self.device_connections[device_id]
            await self.send_message(connection_id, message)
    
    async def broadcast(self, message: Dict):
        """广播消息到所有连接"""
        for connection_id in list(self.active_connections.keys()):
            try:
                await self.send_message(connection_id, message)
            except Exception as e:
                logger.error(f"❌ 广播消息失败: {e}")


# 全局连接管理器
connection_manager = ConnectionManager()


async def handle_websocket(websocket: WebSocket, connection_id: str):
    """处理 WebSocket 连接"""
    await connection_manager.connect(websocket, connection_id)
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理消息
            await handle_message(connection_id, message, websocket)
            
    except WebSocketDisconnect:
        logger.info(f"📡 WebSocket 连接断开: {connection_id}")
        connection_manager.disconnect(connection_id)
    except Exception as e:
        logger.error(f"❌ WebSocket 处理异常: {e}")
        connection_manager.disconnect(connection_id)


async def handle_message(connection_id: str, message: Dict, websocket: WebSocket):
    """处理接收到的消息。

    使用 :func:`parse_message_compat` 将 AIP/1.0、AIP/2.0、AIP/3.0 消息统一
    规范化为 v3 格式后再路由到具体处理器。
    """
    try:
        if "type" not in message:
            logger.warning("⚠️ 收到缺少 type 字段的消息，已忽略")
            return

        # 规范化为 AIP v3
        try:
            aip_msg = parse_message_compat(message)
        except Exception as parse_err:
            logger.warning(f"⚠️ 消息解析失败（type={message.get('type')}）: {parse_err}")
            return

        logger.info(
            f"📨 收到消息: type={aip_msg.type.value}, "
            f"device={aip_msg.device_id}, id={aip_msg.message_id}"
        )

        # 根据规范化后的 v3 MessageType 路由
        if aip_msg.type == MessageType.DEVICE_REGISTER:
            await handle_register(connection_id, aip_msg, websocket)
        elif aip_msg.type == MessageType.DEVICE_HEARTBEAT:
            await handle_heartbeat(connection_id, aip_msg)
        elif aip_msg.type in (MessageType.TASK_RESULT, MessageType.COMMAND_RESULT):
            await handle_response(connection_id, aip_msg)
        elif aip_msg.type == MessageType.COMMAND:
            await handle_command(connection_id, aip_msg)
        elif aip_msg.type == MessageType.DEVICE_STATUS:
            await handle_status(connection_id, aip_msg)
        else:
            logger.debug(f"ℹ️ 未处理的消息类型: {aip_msg.type.value}")

    except Exception as e:
        logger.error(f"❌ 消息处理失败: {e}")


async def handle_register(connection_id: str, aip_msg, websocket: WebSocket):
    """处理设备注册（接受 AIPMessage 对象）"""
    try:
        device_id = aip_msg.device_id
        device_info = aip_msg.payload.get("device_info", {})
        device_type_raw = (aip_msg.device_type.value if aip_msg.device_type else None) or device_info.get("device_type", "unknown")
        capabilities = device_info.get("capabilities", [])

        # 映射为路由层平台大类
        platform = map_device_type_to_platform(device_type_raw)

        # 注册设备
        success = device_router.register_device(
            device_id=device_id,
            device_type=platform,
            capabilities=capabilities,
            websocket=websocket
        )

        if success:
            connection_manager.device_connections[device_id] = connection_id

        # 发送 AIP v3 注册确认响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_REGISTER_ACK.value,
            "device_id": device_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {
                "status": "registered" if success else "failed",
                "message": "设备注册成功" if success else "设备注册失败",
                "registered_at": datetime.utcnow().isoformat(),
            },
        }

        await websocket.send_json(response)

        # 同步到 core 的 registered_devices，打通 chat→device 链路
        if success:
            try:
                from core.routes._shared import registered_devices as core_registered_devices
                core_registered_devices[device_id] = {
                    "device_id": device_id,
                    "device_type": device_type_raw,
                    "device_name": device_info.get("name", device_info.get("model", f"Device-{device_id[:8]}")),
                    "capabilities": capabilities,
                    "os_version": device_info.get("os_version", ""),
                    "registered_at": datetime.utcnow().isoformat(),
                    "last_seen": datetime.utcnow().isoformat(),
                    "status": "online",
                    "online": True,
                    "source": "gateway_ws",
                }
            except Exception as sync_err:
                logger.debug(f"同步设备到 core registered_devices 失败: {sync_err}")

        logger.info(f"✅ 设备注册完成: {device_id} (type={device_type_raw})")

    except Exception as e:
        logger.error(f"❌ 处理注册失败: {e}")


async def handle_heartbeat(connection_id: str, aip_msg):
    """处理心跳（接受 AIPMessage 对象）"""
    try:
        device_id = aip_msg.device_id

        # 更新设备最后活跃时间
        device = device_router.get_device(device_id)
        if device:
            device.last_seen = datetime.now()
            device.status = "online"

        # 发送 AIP v3 心跳确认响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_HEARTBEAT_ACK.value,
            "device_id": device_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": {"status": "ok"},
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理心跳失败: {e}")


async def handle_response(connection_id: str, aip_msg):
    """处理任务/命令执行结果（接受 AIPMessage 对象）"""
    try:
        task_id = aip_msg.task_id or aip_msg.correlation_id or aip_msg.message_id
        payload = {"results": [r.model_dump() for r in aip_msg.results], **aip_msg.payload}
        await device_router.handle_task_result(task_id, payload)
        logger.info(f"✅ 任务结果已处理: {task_id}")

    except Exception as e:
        logger.error(f"❌ 处理响应失败: {e}")


async def handle_command(connection_id: str, aip_msg):
    """处理命令（设备发起的命令，接受 AIPMessage 对象）"""
    try:
        command_text = aip_msg.payload.get("command", "")
        result = await device_router.route_task(command_text)

        # 发送 AIP v3 命令结果响应
        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.COMMAND_RESULT.value,
            "device_id": aip_msg.device_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": result,
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理命令失败: {e}")


async def handle_status(connection_id: str, aip_msg):
    """处理状态查询（接受 AIPMessage 对象）"""
    try:
        status = device_router.get_device_status()

        response = {
            "version": "3.0",
            "message_id": str(uuid.uuid4()),
            "correlation_id": aip_msg.message_id,
            "type": MessageType.DEVICE_STATUS.value,
            "device_id": aip_msg.device_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "payload": status,
        }

        await connection_manager.send_message(connection_id, response)

    except Exception as e:
        logger.error(f"❌ 处理状态查询失败: {e}")


async def push_command_result(request_id: str, status: str, results: Dict):
    """
    推送命令执行结果到所有订阅的 WebSocket 连接
    
    Args:
        request_id: 请求 ID
        status: 命令状态
        results: 执行结果
    """
    message = {
        "type": "command_result",
        "request_id": request_id,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results
    }
    
    await connection_manager.broadcast(message)
    logger.info(f"✅ 命令结果已推送: request_id={request_id}, status={status}")
