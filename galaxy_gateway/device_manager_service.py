"""
Galaxy - 设备管理服务
提供设备管理的 HTTP API 和 Web 界面
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ============================================================================
# 数据模型
# ============================================================================

class DeviceInfo(BaseModel):
    """设备信息"""
    device_id: str
    device_name: str
    device_type: str
    aliases: List[str] = []
    capabilities: List[str] = []
    ip_address: str
    status: str = "offline"
    last_seen: Optional[str] = None
    metadata: Dict[str, Any] = {}

class DeviceRegistry:
    """设备注册表"""
    
    def __init__(self):
        self.devices: Dict[str, DeviceInfo] = {}
        self._load_from_file()
    
    def _load_from_file(self):
        """从文件加载设备"""
        data_file = Path("data/devices.json")
        if data_file.exists():
            try:
                with open(data_file, 'r') as f:
                    data = json.load(f)
                    for device_id, device_data in data.items():
                        self.devices[device_id] = DeviceInfo(**device_data)
                logger.info(f"Loaded {len(self.devices)} devices from file")
            except Exception as e:
                logger.error(f"Failed to load devices: {e}")
    
    def _save_to_file(self):
        """保存设备到文件"""
        data_file = Path("data/devices.json")
        data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(data_file, 'w') as f:
                json.dump({k: v.dict() for k, v in self.devices.items()}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save devices: {e}")
    
    def register(self, device: DeviceInfo) -> bool:
        """注册设备"""
        device.last_seen = datetime.now().isoformat()
        device.status = "online"
        self.devices[device.device_id] = device
        self._save_to_file()
        logger.info(f"Device registered: {device.device_id}")
        return True
    
    def unregister(self, device_id: str) -> bool:
        """注销设备"""
        if device_id in self.devices:
            del self.devices[device_id]
            self._save_to_file()
            logger.info(f"Device unregistered: {device_id}")
            return True
        return False
    
    def get(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_all(self) -> List[DeviceInfo]:
        """获取所有设备"""
        return list(self.devices.values())
    
    def get_online(self) -> List[DeviceInfo]:
        """获取在线设备"""
        return [d for d in self.devices.values() if d.status == "online"]
    
    def update_status(self, device_id: str, status: str):
        """更新设备状态"""
        if device_id in self.devices:
            self.devices[device_id].status = status
            self.devices[device_id].last_seen = datetime.now().isoformat()
            self._save_to_file()

# ============================================================================
# 全局实例
# ============================================================================

registry = DeviceRegistry()

# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(title="Galaxy Device Manager", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# API 端点
# ============================================================================

@app.get("/")
async def root():
    """根端点 - 返回设备管理界面"""
    static_path = Path(__file__).parent / "static" / "device_manager.html"
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text())
    return {"service": "Galaxy Device Manager", "version": "1.0.0"}

@app.get("/api/status")
async def get_status():
    """获取服务状态"""
    return {
        "status": "online",
        "devices": {
            "total": len(registry.devices),
            "online": len(registry.get_online())
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/devices")
async def list_devices():
    """列出所有设备"""
    return {
        "devices": [d.dict() for d in registry.get_all()],
        "total": len(registry.devices)
    }

@app.post("/api/devices/register")
async def register_device(device: DeviceInfo):
    """注册设备"""
    if registry.register(device):
        return {"success": True, "device": device.dict()}
    raise HTTPException(status_code=400, detail="Failed to register device")

@app.delete("/api/devices/{device_id}")
async def unregister_device(device_id: str):
    """注销设备"""
    if registry.unregister(device_id):
        return {"success": True}
    raise HTTPException(status_code=404, detail="Device not found")

@app.get("/api/devices/{device_id}")
async def get_device(device_id: str):
    """获取设备信息"""
    device = registry.get(device_id)
    if device:
        return device.dict()
    raise HTTPException(status_code=404, detail="Device not found")

@app.post("/api/execute")
async def execute_command(request: dict):
    """执行命令"""
    device_id = request.get("device_id")
    command = request.get("command")
    params = request.get("params", {})
    
    device = registry.get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # 这里可以添加实际的命令执行逻辑
    return {
        "success": True,
        "device_id": device_id,
        "command": command,
        "result": f"Command '{command}' sent to {device.device_name}"
    }

# ============================================================================
# WebSocket 支持
# ============================================================================

active_connections: List[WebSocket] = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接"""
    await websocket.accept()
    active_connections.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理心跳
            if message.get("type") == "heartbeat":
                await websocket.send_json({"type": "heartbeat_ack"})
            
            # 处理设备状态更新
            elif message.get("type") == "device_status":
                device_id = message.get("device_id")
                status = message.get("status")
                registry.update_status(device_id, status)
                
                # 广播给所有连接
                await broadcast({
                    "type": "device_status_update",
                    "device_id": device_id,
                    "status": status
                })
    
    except WebSocketDisconnect:
        active_connections.remove(websocket)

async def broadcast(message: dict):
    """广播消息"""
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except:
            pass

# ============================================================================
# 启动函数
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 8080):
    """运行服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_server()
