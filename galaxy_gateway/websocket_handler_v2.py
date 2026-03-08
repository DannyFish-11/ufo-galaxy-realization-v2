"""
WebSocket Handler v2 - 协议兼容版
支持 AIP v1.0 和 AIP v2.0 (Android Agent) 的颗粒级对接

.. deprecated::
    此模块已废弃。AIP v1/v2 兼容由 galaxy_gateway/protocol/compat.py 处理。
    如需 WebSocket 处理，请使用 galaxy_gateway/websocket_handler.py。
"""
import warnings as _warnings
_warnings.warn(
    "websocket_handler_v2 已废弃，请使用 websocket_handler",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
import json
import logging
from typing import Dict, Any
from fastapi import WebSocket

logger = logging.getLogger("GatewayV2")

def validate_aip_message(message: Dict) -> str:
    """
    智能识别并验证协议版本
    返回: "v1", "v2" 或 "invalid"
    """
    # 检查 AIP v2.0 (Android 端格式)
    if all(k in message for k in ["version", "type", "device_id"]):
        if message.get("version") == "2.0":
            return "v2"
    
    # 检查 AIP v1.0 (传统格式)
    if all(k in message for k in ["protocol", "message_id", "type", "from"]):
        return "v1"
        
    return "invalid"

async def handle_v2_message(connection_id: str, message: Dict, websocket: WebSocket):
    """处理 Android 端的 AIP v2.0 消息"""
    msg_type = message.get("type")
    device_id = message.get("device_id")
    payload = message.get("payload", {})
    
    logger.info(f"📱 [AIP v2.0] 收到来自 {device_id} 的 {msg_type} 消息")
    
    if msg_type == "device_register":
        # 颗粒级对接：将 v2.0 注册信息映射到系统路由
        device_type = message.get("device_type", "android")
        capabilities = payload.get("capabilities", {})
        logger.info(f"✅ 设备注册成功: {device_id} ({device_type})")
        # 这里调用 device_router.register_device(...)
        
    elif msg_type == "heartbeat":
        # 自动回复心跳 ACK
        ack = {
            "version": "2.0",
            "type": "heartbeat_ack",
            "device_id": "galaxy_gateway",
            "timestamp": int(asyncio.get_event_loop().time() * 1000),
            "payload": {}
        }
        await websocket.send_json(ack)

# 替换原始逻辑的钩子已准备就绪
