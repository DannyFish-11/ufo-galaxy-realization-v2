"""
WebSocket Handler - WebSocket 连接处理器

处理与 Android Agent 和其他设备的 WebSocket 连接
实现 AIP/1.0 协议通信

Author: Manus AI
Version: 1.0
Date: 2026-01-22
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from device_router import device_router

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
    """处理接收到的消息"""
    try:
        # 验证 AIP/1.0 协议
        if not validate_aip_message(message):
            logger.warning(f"⚠️ 无效的 AIP/1.0 消息")
            return
        
        message_type = message.get("type")
        message_id = message.get("message_id")
        
        logger.info(f"📨 收到消息: type={message_type}, id={message_id}")
        
        # 根据消息类型处理
        if message_type == "register":
            await handle_register(connection_id, message, websocket)
        elif message_type == "heartbeat":
            await handle_heartbeat(connection_id, message)
        elif message_type == "response":
            await handle_response(connection_id, message)
        elif message_type == "command":
            await handle_command(connection_id, message)
        elif message_type == "status":
            await handle_status(connection_id, message)
        else:
            logger.warning(f"⚠️ 未知消息类型: {message_type}")
    
    except Exception as e:
        logger.error(f"❌ 消息处理失败: {e}")


def validate_aip_message(message: Dict) -> bool:
    """验证 AIP/1.0 消息格式"""
    required_fields = ["protocol", "message_id", "timestamp", "from", "to", "type"]
    return all(field in message for field in required_fields)


async def handle_register(connection_id: str, message: Dict, websocket: WebSocket):
    """处理设备注册"""
    try:
        payload = message.get("payload", {})
        device_id = payload.get("device_id", message.get("from"))
        device_type = payload.get("device_type", "unknown")
        capabilities = payload.get("capabilities", [])
        
        # 注册设备
        success = device_router.register_device(
            device_id=device_id,
            device_type=device_type,
            capabilities=capabilities,
            websocket=websocket
        )
        
        if success:
            connection_manager.device_connections[device_id] = connection_id
        
        # 发送注册响应
        response = {
            "protocol": "AIP/1.0",
            "message_id": f"node50_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": datetime.now().isoformat() + "Z",
            "from": "Node_50",
            "to": device_id,
            "type": "response",
            "payload": {
                "success": success,
                "message": "设备注册成功" if success else "设备注册失败",
                "registered_at": datetime.now().isoformat()
            }
        }
        
        await websocket.send_json(response)
        logger.info(f"✅ 设备注册完成: {device_id}")
        
    except Exception as e:
        logger.error(f"❌ 处理注册失败: {e}")


async def handle_heartbeat(connection_id: str, message: Dict):
    """处理心跳"""
    try:
        device_id = message.get("from")
        
        # 更新设备最后活跃时间
        device = device_router.get_device(device_id)
        if device:
            device.last_seen = datetime.now()
            device.status = "online"
        
        # 发送心跳响应
        response = {
            "protocol": "AIP/1.0",
            "message_id": f"node50_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": datetime.now().isoformat() + "Z",
            "from": "Node_50",
            "to": device_id,
            "type": "heartbeat",
            "payload": {
                "status": "ok"
            }
        }
        
        await connection_manager.send_message(connection_id, response)
        
    except Exception as e:
        logger.error(f"❌ 处理心跳失败: {e}")


async def handle_response(connection_id: str, message: Dict):
    """处理任务执行结果"""
    try:
        payload = message.get("payload", {})
        
        # 提取任务 ID（从原始消息 ID 中）
        original_message_id = message.get("message_id", "")
        
        # 记录任务结果
        await device_router.handle_task_result(original_message_id, payload)
        
        logger.info(f"✅ 任务结果已处理")
        
    except Exception as e:
        logger.error(f"❌ 处理响应失败: {e}")


async def handle_command(connection_id: str, message: Dict):
    """处理命令（从设备发起的命令）"""
    try:
        payload = message.get("payload", {})
        command = payload.get("command", "")
        
        # 路由命令
        result = await device_router.route_task(command)
        
        # 发送响应
        device_id = message.get("from")
        response = {
            "protocol": "AIP/1.0",
            "message_id": f"node50_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": datetime.now().isoformat() + "Z",
            "from": "Node_50",
            "to": device_id,
            "type": "response",
            "payload": result
        }
        
        await connection_manager.send_message(connection_id, response)
        
    except Exception as e:
        logger.error(f"❌ 处理命令失败: {e}")


async def handle_status(connection_id: str, message: Dict):
    """处理状态查询"""
    try:
        device_id = message.get("from")
        
        # 获取设备状态
        status = device_router.get_device_status()
        
        # 发送响应
        response = {
            "protocol": "AIP/1.0",
            "message_id": f"node50_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": datetime.now().isoformat() + "Z",
            "from": "Node_50",
            "to": device_id,
            "type": "response",
            "payload": status
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
