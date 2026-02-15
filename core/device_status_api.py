# -*- coding: utf-8 -*-
"""
UFO Galaxy - 设备状态统一管理层 API
====================================

功能：
1. 统一管理所有设备的状态信息
2. 提供 RESTful API 供 UI 调用
3. 支持 WebSocket 实时推送状态更新
4. 与节点系统和 Device Agent 集成

作者：Manus AI
日期：2026-02-06
版本：2.0
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据模型
# ============================================================================

class DeviceCategory(str, Enum):
    """设备类别"""
    MOBILE = "mobile"           # 移动设备（Android、iOS）
    DESKTOP = "desktop"         # 桌面设备（Windows、macOS、Linux）
    IOT = "iot"                 # 物联网设备
    PERIPHERAL = "peripheral"   # 外设（摄像头、串口等）
    NETWORK = "network"         # 网络设备
    CUSTOM = "custom"           # 自定义设备


@dataclass
class HardwareStatus:
    """硬件状态"""
    # 摄像头
    camera_available: bool = False
    camera_front: bool = False
    camera_back: bool = False
    camera_in_use: bool = False
    
    # 蓝牙
    bluetooth_supported: bool = False
    bluetooth_enabled: bool = False
    bluetooth_connected_devices: List[str] = field(default_factory=list)
    
    # NFC
    nfc_supported: bool = False
    nfc_enabled: bool = False
    
    # 音频
    microphone_available: bool = False
    speaker_available: bool = False
    audio_volume: int = 0
    audio_muted: bool = False
    
    # 网络
    wifi_connected: bool = False
    wifi_ssid: Optional[str] = None
    wifi_signal: int = 0
    mobile_data_connected: bool = False
    
    # 电池
    battery_level: int = 0
    battery_charging: bool = False
    
    # 传感器
    has_accelerometer: bool = False
    has_gyroscope: bool = False
    has_gps: bool = False
    
    # 串口/USB
    serial_ports: List[str] = field(default_factory=list)
    usb_devices: List[str] = field(default_factory=list)


@dataclass
class DeviceState:
    """设备状态"""
    device_id: str
    device_name: str
    device_type: str
    category: DeviceCategory
    
    # 连接状态
    is_online: bool = False
    is_connected_to_server: bool = False
    last_heartbeat: Optional[str] = None
    
    # 硬件状态
    hardware: HardwareStatus = field(default_factory=HardwareStatus)
    
    # 节点状态
    active_nodes: int = 0
    total_nodes: int = 0
    node_health: float = 100.0
    
    # 系统信息
    os_version: str = ""
    app_version: str = ""
    ip_address: str = ""
    
    # 扩展数据
    extra_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['category'] = self.category.value
        return result


# ============================================================================
# 设备状态管理器
# ============================================================================

class DeviceStatusManager:
    """设备状态管理器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._devices: Dict[str, DeviceState] = {}
        self._websocket_clients: Set[WebSocket] = set()
        self._status_history: Dict[str, List[Dict[str, Any]]] = {}
        self._initialized = True
        
        logger.info("DeviceStatusManager initialized")
    
    def register_device(self, device_state: DeviceState) -> bool:
        """注册设备"""
        self._devices[device_state.device_id] = device_state
        self._status_history[device_state.device_id] = []
        logger.info(f"Device registered: {device_state.device_id} ({device_state.device_name})")
        asyncio.create_task(self._broadcast_update("device_registered", device_state.to_dict()))
        return True
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id in self._devices:
            device = self._devices.pop(device_id)
            self._status_history.pop(device_id, None)
            logger.info(f"Device unregistered: {device_id}")
            asyncio.create_task(self._broadcast_update("device_unregistered", {"device_id": device_id}))
            return True
        return False
    
    def update_device_status(self, device_id: str, status_update: Dict[str, Any]) -> bool:
        """更新设备状态"""
        if device_id not in self._devices:
            return False
        
        device = self._devices[device_id]
        
        # 更新硬件状态
        if "hardware" in status_update:
            hw = status_update["hardware"]
            for key, value in hw.items():
                if hasattr(device.hardware, key):
                    setattr(device.hardware, key, value)
        
        # 更新其他字段
        for key in ["is_online", "is_connected_to_server", "active_nodes", "total_nodes", 
                    "node_health", "os_version", "app_version", "ip_address"]:
            if key in status_update:
                setattr(device, key, status_update[key])
        
        # 更新心跳时间
        device.last_heartbeat = datetime.now().isoformat()
        
        # 更新扩展数据
        if "extra_data" in status_update:
            device.extra_data.update(status_update["extra_data"])
        
        # 记录历史
        self._record_history(device_id, device.to_dict())
        
        # 广播更新
        asyncio.create_task(self._broadcast_update("device_status_updated", device.to_dict()))
        
        return True
    
    def get_device_status(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备状态"""
        if device_id in self._devices:
            return self._devices[device_id].to_dict()
        return None
    
    def get_all_devices(self) -> List[Dict[str, Any]]:
        """获取所有设备状态"""
        return [device.to_dict() for device in self._devices.values()]
    
    def get_devices_by_category(self, category: DeviceCategory) -> List[Dict[str, Any]]:
        """按类别获取设备"""
        return [
            device.to_dict() for device in self._devices.values()
            if device.category == category
        ]
    
    def get_online_devices(self) -> List[Dict[str, Any]]:
        """获取在线设备"""
        return [
            device.to_dict() for device in self._devices.values()
            if device.is_online
        ]
    
    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        total = len(self._devices)
        online = sum(1 for d in self._devices.values() if d.is_online)
        connected = sum(1 for d in self._devices.values() if d.is_connected_to_server)
        
        by_category = {}
        for cat in DeviceCategory:
            devices = [d for d in self._devices.values() if d.category == cat]
            if devices:
                by_category[cat.value] = {
                    "total": len(devices),
                    "online": sum(1 for d in devices if d.is_online)
                }
        
        return {
            "total_devices": total,
            "online_devices": online,
            "connected_devices": connected,
            "by_category": by_category,
            "last_updated": datetime.now().isoformat()
        }
    
    def _record_history(self, device_id: str, status: Dict[str, Any]):
        """记录状态历史"""
        if device_id not in self._status_history:
            self._status_history[device_id] = []
        
        history = self._status_history[device_id]
        history.append({
            "timestamp": datetime.now().isoformat(),
            "status": status
        })
        
        # 只保留最近 100 条记录
        if len(history) > 100:
            self._status_history[device_id] = history[-100:]
    
    async def add_websocket_client(self, websocket: WebSocket):
        """添加 WebSocket 客户端"""
        self._websocket_clients.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._websocket_clients)}")
    
    async def remove_websocket_client(self, websocket: WebSocket):
        """移除 WebSocket 客户端"""
        self._websocket_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._websocket_clients)}")
    
    async def _broadcast_update(self, event_type: str, data: Dict[str, Any]):
        """广播状态更新"""
        if not self._websocket_clients:
            return
        
        message = json.dumps({
            "event": event_type,
            "data": data,
            "timestamp": datetime.now().isoformat()
        })
        
        disconnected = set()
        for client in self._websocket_clients:
            try:
                await client.send_text(message)
            except Exception as e:
                logger.error(f"Failed to send to WebSocket client: {e}")
                disconnected.add(client)
        
        # 清理断开的连接
        self._websocket_clients -= disconnected


# ============================================================================
# 全局实例
# ============================================================================

status_manager = DeviceStatusManager()


# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(
    title="UFO Galaxy Device Status API",
    description="统一设备状态管理 API",
    version="2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


# Pydantic 模型
class RegisterDeviceRequest(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    category: str = "custom"
    os_version: str = ""
    app_version: str = ""


class UpdateStatusRequest(BaseModel):
    hardware: Optional[Dict[str, Any]] = None
    is_online: Optional[bool] = None
    is_connected_to_server: Optional[bool] = None
    active_nodes: Optional[int] = None
    total_nodes: Optional[int] = None
    node_health: Optional[float] = None
    extra_data: Optional[Dict[str, Any]] = None


# API 路由
@app.get("/")
async def root():
    return {"service": "UFO Galaxy Device Status API", "version": "2.0"}


@app.get("/status/summary")
async def get_summary():
    """获取状态摘要"""
    return status_manager.get_status_summary()


@app.get("/devices")
async def list_devices(category: Optional[str] = None, online_only: bool = False):
    """列出所有设备"""
    if online_only:
        return status_manager.get_online_devices()
    if category:
        try:
            cat = DeviceCategory(category)
            return status_manager.get_devices_by_category(cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    return status_manager.get_all_devices()


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    """获取设备状态"""
    status = status_manager.get_device_status(device_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return status


@app.post("/devices/register")
async def register_device(request: RegisterDeviceRequest):
    """注册设备"""
    try:
        category = DeviceCategory(request.category)
    except ValueError:
        category = DeviceCategory.CUSTOM
    
    device_state = DeviceState(
        device_id=request.device_id,
        device_name=request.device_name,
        device_type=request.device_type,
        category=category,
        os_version=request.os_version,
        app_version=request.app_version
    )
    
    success = status_manager.register_device(device_state)
    return {"success": success, "device_id": request.device_id}


@app.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """注销设备"""
    success = status_manager.unregister_device(device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True}


@app.put("/devices/{device_id}/status")
async def update_status(device_id: str, request: UpdateStatusRequest):
    """更新设备状态"""
    update_data = request.dict(exclude_none=True)
    success = status_manager.update_device_status(device_id, update_data)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True}


@app.post("/devices/{device_id}/heartbeat")
async def heartbeat(device_id: str):
    """设备心跳"""
    success = status_manager.update_device_status(device_id, {
        "is_online": True,
        "is_connected_to_server": True
    })
    if not success:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True, "timestamp": datetime.now().isoformat()}


# WebSocket 端点
@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket 实时状态推送"""
    await websocket.accept()
    await status_manager.add_websocket_client(websocket)
    
    try:
        # 发送当前状态
        await websocket.send_json({
            "event": "initial_status",
            "data": {
                "summary": status_manager.get_status_summary(),
                "devices": status_manager.get_all_devices()
            },
            "timestamp": datetime.now().isoformat()
        })
        
        # 保持连接并处理消息
        while True:
            data = await websocket.receive_text()
            # 可以处理客户端发送的消息
            message = json.loads(data)
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif message.get("type") == "get_status":
                device_id = message.get("device_id")
                if device_id:
                    status = status_manager.get_device_status(device_id)
                    await websocket.send_json({
                        "event": "device_status",
                        "data": status,
                        "timestamp": datetime.now().isoformat()
                    })
                    
    except WebSocketDisconnect:
        await status_manager.remove_websocket_client(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await status_manager.remove_websocket_client(websocket)


# ============================================================================
# 启动函数
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 8766):
    """运行服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
