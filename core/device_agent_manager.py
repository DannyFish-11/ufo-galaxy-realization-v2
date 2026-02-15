# -*- coding: utf-8 -*-
"""
UFO Galaxy - 统一设备 Agent 管理器
===================================

功能：
1. 统一管理所有设备 Agent（Android、Windows、macOS、IoT 等）
2. 提供设备注册、发现、状态监控
3. 支持动态添加新的 Device Agent
4. 与微软 UFO 深度集成

作者：Manus AI
日期：2026-02-06
版本：2.0
"""

import asyncio
import logging
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, Optional, List, Callable, Type
import aiohttp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# 设备类型和状态定义
# ============================================================================

class DeviceType(Enum):
    """设备类型枚举"""
    ANDROID = "android"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    IOS = "ios"
    IOT = "iot"
    CAMERA = "camera"
    AUDIO = "audio"
    SERIAL = "serial"
    BLE = "ble"
    NFC = "nfc"
    CANBUS = "canbus"
    DRONE = "drone"
    PRINTER_3D = "printer_3d"
    CUSTOM = "custom"


class DeviceStatus(Enum):
    """设备状态枚举"""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    INITIALIZING = "initializing"
    DISCONNECTED = "disconnected"


class DeviceCapability(Enum):
    """设备能力枚举"""
    SCREEN_CAPTURE = "screen_capture"
    UI_AUTOMATION = "ui_automation"
    VOICE_INPUT = "voice_input"
    VOICE_OUTPUT = "voice_output"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    SPEAKER = "speaker"
    BLUETOOTH = "bluetooth"
    NFC = "nfc"
    GPS = "gps"
    ACCELEROMETER = "accelerometer"
    GYROSCOPE = "gyroscope"
    FILE_SYSTEM = "file_system"
    NETWORK = "network"
    NOTIFICATION = "notification"
    APP_CONTROL = "app_control"


@dataclass
class DeviceInfo:
    """设备信息数据类"""
    device_id: str
    device_type: DeviceType
    device_name: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    capabilities: List[DeviceCapability] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_heartbeat: Optional[datetime] = None
    registered_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type.value,
            "device_name": self.device_name,
            "status": self.status.value,
            "capabilities": [c.value for c in self.capabilities],
            "metadata": self.metadata,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None
        }


# ============================================================================
# 设备 Agent 基类
# ============================================================================

class BaseDeviceAgent(ABC):
    """
    设备 Agent 基类
    
    所有设备 Agent 都必须继承此类并实现抽象方法
    """
    
    def __init__(self, device_info: DeviceInfo):
        self.device_info = device_info
        self.is_connected = False
        self._event_handlers: Dict[str, List[Callable]] = {}
        
    @property
    def device_id(self) -> str:
        return self.device_info.device_id
    
    @property
    def device_type(self) -> DeviceType:
        return self.device_info.device_type
    
    @abstractmethod
    async def connect(self) -> bool:
        """连接到设备"""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """断开设备连接"""
        pass
    
    @abstractmethod
    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行设备命令"""
        pass
    
    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        """获取设备状态"""
        pass
    
    @abstractmethod
    async def get_capabilities(self) -> List[DeviceCapability]:
        """获取设备能力列表"""
        pass
    
    def on(self, event: str, handler: Callable):
        """注册事件处理器"""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)
    
    def off(self, event: str, handler: Callable):
        """移除事件处理器"""
        if event in self._event_handlers:
            self._event_handlers[event].remove(handler)
    
    async def emit(self, event: str, data: Any = None):
        """触发事件"""
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")


# ============================================================================
# Android 设备 Agent
# ============================================================================

class AndroidDeviceAgent(BaseDeviceAgent):
    """Android 设备 Agent"""
    
    def __init__(self, device_info: DeviceInfo, server_url: str = "ws://localhost:8765"):
        super().__init__(device_info)
        self.server_url = server_url
        self.ws_connection = None
        
    async def connect(self) -> bool:
        try:
            # 通过 WebSocket 连接到 Android 设备
            import websockets
            self.ws_connection = await websockets.connect(
                f"{self.server_url}/device/{self.device_id}"
            )
            self.is_connected = True
            self.device_info.status = DeviceStatus.ONLINE
            logger.info(f"Android device {self.device_id} connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect Android device: {e}")
            self.device_info.status = DeviceStatus.ERROR
            return False
    
    async def disconnect(self) -> bool:
        try:
            if self.ws_connection:
                await self.ws_connection.close()
            self.is_connected = False
            self.device_info.status = DeviceStatus.OFFLINE
            return True
        except Exception as e:
            logger.error(f"Failed to disconnect Android device: {e}")
            return False
    
    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            return {"error": "Device not connected"}
        
        try:
            message = json.dumps({
                "type": "command",
                "command": command,
                "params": params
            })
            await self.ws_connection.send(message)
            response = await self.ws_connection.recv()
            return json.loads(response)
        except Exception as e:
            return {"error": str(e)}
    
    async def get_status(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "android",
            "status": self.device_info.status.value,
            "is_connected": self.is_connected,
            "capabilities": await self.get_capabilities(),
            "battery_level": self.device_info.metadata.get("battery_level", "unknown"),
            "screen_on": self.device_info.metadata.get("screen_on", False),
            "wifi_connected": self.device_info.metadata.get("wifi_connected", False),
            "bluetooth_enabled": self.device_info.metadata.get("bluetooth_enabled", False)
        }
    
    async def get_capabilities(self) -> List[DeviceCapability]:
        return [
            DeviceCapability.SCREEN_CAPTURE,
            DeviceCapability.UI_AUTOMATION,
            DeviceCapability.VOICE_INPUT,
            DeviceCapability.VOICE_OUTPUT,
            DeviceCapability.CAMERA,
            DeviceCapability.MICROPHONE,
            DeviceCapability.SPEAKER,
            DeviceCapability.BLUETOOTH,
            DeviceCapability.NFC,
            DeviceCapability.GPS,
            DeviceCapability.NOTIFICATION,
            DeviceCapability.APP_CONTROL
        ]
    
    # Android 特有方法
    async def capture_screen(self) -> Dict[str, Any]:
        return await self.execute_command("capture_screen", {})
    
    async def tap(self, x: int, y: int) -> Dict[str, Any]:
        return await self.execute_command("tap", {"x": x, "y": y})
    
    async def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 300) -> Dict[str, Any]:
        return await self.execute_command("swipe", {
            "start_x": start_x, "start_y": start_y,
            "end_x": end_x, "end_y": end_y,
            "duration": duration
        })
    
    async def input_text(self, text: str) -> Dict[str, Any]:
        return await self.execute_command("input_text", {"text": text})
    
    async def launch_app(self, package_name: str) -> Dict[str, Any]:
        return await self.execute_command("launch_app", {"package": package_name})


# ============================================================================
# Windows 设备 Agent（集成微软 UFO）
# ============================================================================

class WindowsDeviceAgent(BaseDeviceAgent):
    """Windows 设备 Agent - 深度集成微软 UFO"""
    
    def __init__(self, device_info: DeviceInfo, ufo_path: str = None):
        super().__init__(device_info)
        self.ufo_path = ufo_path
        self.ufo_available = False
        self.puppeteer = None
        
    async def connect(self) -> bool:
        try:
            # 尝试加载微软 UFO
            await self._load_microsoft_ufo()
            self.is_connected = True
            self.device_info.status = DeviceStatus.ONLINE
            logger.info(f"Windows device {self.device_id} connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect Windows device: {e}")
            self.device_info.status = DeviceStatus.ERROR
            return False
    
    async def _load_microsoft_ufo(self):
        """加载微软 UFO 模块"""
        try:
            import sys
            if self.ufo_path:
                sys.path.insert(0, self.ufo_path)
            
            # 尝试导入微软 UFO 的 Puppeteer
            from external.microsoft_ufo.automator.puppeteer import Puppeteer
            self.puppeteer = Puppeteer()
            self.ufo_available = True
            logger.info("Microsoft UFO loaded successfully")
        except ImportError as e:
            logger.warning(f"Microsoft UFO not available: {e}")
            self.ufo_available = False
    
    async def disconnect(self) -> bool:
        self.is_connected = False
        self.device_info.status = DeviceStatus.OFFLINE
        return True
    
    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            return {"error": "Device not connected"}
        
        # 优先使用微软 UFO
        if self.ufo_available and self.puppeteer:
            return await self._execute_with_ufo(command, params)
        else:
            return await self._execute_with_fallback(command, params)
    
    async def _execute_with_ufo(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """使用微软 UFO 执行命令"""
        try:
            if command == "click":
                # 使用 UFO 的点击功能
                result = self.puppeteer.click(params.get("x"), params.get("y"))
                return {"success": True, "method": "microsoft_ufo", "result": result}
            elif command == "type":
                result = self.puppeteer.type_text(params.get("text"))
                return {"success": True, "method": "microsoft_ufo", "result": result}
            elif command == "find_element":
                # 使用 UFO 的元素查找
                result = self.puppeteer.find_element(params.get("selector"))
                return {"success": True, "method": "microsoft_ufo", "result": result}
            else:
                return {"error": f"Unknown command: {command}"}
        except Exception as e:
            return {"error": str(e), "method": "microsoft_ufo"}
    
    async def _execute_with_fallback(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """降级执行（不使用微软 UFO）"""
        try:
            import pyautogui
            if command == "click":
                pyautogui.click(params.get("x"), params.get("y"))
                return {"success": True, "method": "pyautogui"}
            elif command == "type":
                pyautogui.write(params.get("text"))
                return {"success": True, "method": "pyautogui"}
            else:
                return {"error": f"Unknown command: {command}"}
        except Exception as e:
            return {"error": str(e), "method": "fallback"}
    
    async def get_status(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "windows",
            "status": self.device_info.status.value,
            "is_connected": self.is_connected,
            "ufo_available": self.ufo_available,
            "capabilities": [c.value for c in await self.get_capabilities()]
        }
    
    async def get_capabilities(self) -> List[DeviceCapability]:
        caps = [
            DeviceCapability.SCREEN_CAPTURE,
            DeviceCapability.UI_AUTOMATION,
            DeviceCapability.FILE_SYSTEM,
            DeviceCapability.NETWORK
        ]
        if self.ufo_available:
            caps.append(DeviceCapability.APP_CONTROL)
        return caps


# ============================================================================
# IoT 设备 Agent
# ============================================================================

class IoTDeviceAgent(BaseDeviceAgent):
    """IoT 设备 Agent - 支持各种物联网设备"""
    
    def __init__(self, device_info: DeviceInfo, protocol: str = "mqtt"):
        super().__init__(device_info)
        self.protocol = protocol
        self.mqtt_client = None
        
    async def connect(self) -> bool:
        try:
            if self.protocol == "mqtt":
                await self._connect_mqtt()
            elif self.protocol == "http":
                await self._connect_http()
            self.is_connected = True
            self.device_info.status = DeviceStatus.ONLINE
            return True
        except Exception as e:
            logger.error(f"Failed to connect IoT device: {e}")
            return False
    
    async def _connect_mqtt(self):
        """通过 MQTT 连接"""
        try:
            import paho.mqtt.client as mqtt
            broker = self.device_info.metadata.get("mqtt_broker", "localhost")
            port = self.device_info.metadata.get("mqtt_port", 1883)
            self.mqtt_client = mqtt.Client()
            self.mqtt_client.connect(broker, port)
            self.mqtt_client.loop_start()
        except ImportError:
            logger.warning("paho-mqtt not installed")
    
    async def _connect_http(self):
        """通过 HTTP 连接"""
        pass
    
    async def disconnect(self) -> bool:
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        self.is_connected = False
        self.device_info.status = DeviceStatus.OFFLINE
        return True
    
    async def execute_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_connected:
            return {"error": "Device not connected"}
        
        if self.protocol == "mqtt" and self.mqtt_client:
            topic = f"device/{self.device_id}/command"
            payload = json.dumps({"command": command, "params": params})
            self.mqtt_client.publish(topic, payload)
            return {"success": True, "method": "mqtt"}
        
        return {"error": "No valid connection"}
    
    async def get_status(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "iot",
            "status": self.device_info.status.value,
            "protocol": self.protocol,
            "is_connected": self.is_connected
        }
    
    async def get_capabilities(self) -> List[DeviceCapability]:
        return self.device_info.capabilities


# ============================================================================
# 设备 Agent 管理器
# ============================================================================

class DeviceAgentManager:
    """
    统一设备 Agent 管理器
    
    功能：
    1. 注册和管理所有设备 Agent
    2. 设备发现和自动连接
    3. 状态监控和心跳检测
    4. 提供统一的设备访问接口
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._agents: Dict[str, BaseDeviceAgent] = {}
        self._agent_types: Dict[DeviceType, Type[BaseDeviceAgent]] = {
            DeviceType.ANDROID: AndroidDeviceAgent,
            DeviceType.WINDOWS: WindowsDeviceAgent,
            DeviceType.IOT: IoTDeviceAgent
        }
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._heartbeat_task = None
        self._initialized = True
        
        logger.info("DeviceAgentManager initialized")
    
    async def initialize(self) -> bool:
        """初始化设备管理器"""
        try:
            # 启动心跳检测
            await self.start_heartbeat(interval=30)
            logger.info("DeviceAgentManager fully initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize DeviceAgentManager: {e}")
            return False
    
    async def shutdown(self) -> bool:
        """关闭设备管理器"""
        try:
            await self.stop_heartbeat()
            await self.disconnect_all()
            logger.info("DeviceAgentManager shutdown complete")
            return True
        except Exception as e:
            logger.error(f"Failed to shutdown DeviceAgentManager: {e}")
            return False
    
    def register_agent_type(self, device_type: DeviceType, agent_class: Type[BaseDeviceAgent]):
        """注册新的设备 Agent 类型"""
        self._agent_types[device_type] = agent_class
        logger.info(f"Registered agent type: {device_type.value}")
    
    async def register_device(self, device_info: DeviceInfo, **kwargs) -> Optional[BaseDeviceAgent]:
        """注册设备并创建 Agent"""
        if device_info.device_id in self._agents:
            logger.warning(f"Device {device_info.device_id} already registered")
            return self._agents[device_info.device_id]
        
        agent_class = self._agent_types.get(device_info.device_type)
        if not agent_class:
            logger.error(f"Unknown device type: {device_info.device_type}")
            return None
        
        agent = agent_class(device_info, **kwargs)
        self._agents[device_info.device_id] = agent
        device_info.registered_at = datetime.now()
        
        logger.info(f"Device registered: {device_info.device_id} ({device_info.device_type.value})")
        await self._emit("device_registered", device_info)
        
        return agent
    
    async def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self._agents:
            return False
        
        agent = self._agents[device_id]
        await agent.disconnect()
        del self._agents[device_id]
        
        logger.info(f"Device unregistered: {device_id}")
        await self._emit("device_unregistered", device_id)
        
        return True
    
    def get_agent(self, device_id: str) -> Optional[BaseDeviceAgent]:
        """获取设备 Agent"""
        return self._agents.get(device_id)
    
    def get_all_agents(self) -> Dict[str, BaseDeviceAgent]:
        """获取所有设备 Agent"""
        return self._agents.copy()
    
    def get_agents_by_type(self, device_type: DeviceType) -> List[BaseDeviceAgent]:
        """按类型获取设备 Agent"""
        return [
            agent for agent in self._agents.values()
            if agent.device_type == device_type
        ]
    
    async def get_all_status(self) -> Dict[str, Any]:
        """获取所有设备状态"""
        status = {}
        for device_id, agent in self._agents.items():
            status[device_id] = await agent.get_status()
        return status
    
    async def connect_all(self) -> Dict[str, bool]:
        """连接所有设备"""
        results = {}
        for device_id, agent in self._agents.items():
            results[device_id] = await agent.connect()
        return results
    
    async def disconnect_all(self) -> Dict[str, bool]:
        """断开所有设备"""
        results = {}
        for device_id, agent in self._agents.items():
            results[device_id] = await agent.disconnect()
        return results
    
    async def execute_on_device(self, device_id: str, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """在指定设备上执行命令"""
        agent = self.get_agent(device_id)
        if not agent:
            return {"error": f"Device not found: {device_id}"}
        return await agent.execute_command(command, params)
    
    async def broadcast_command(self, command: str, params: Dict[str, Any], device_type: Optional[DeviceType] = None) -> Dict[str, Any]:
        """向所有设备（或指定类型的设备）广播命令"""
        results = {}
        agents = self.get_agents_by_type(device_type) if device_type else list(self._agents.values())
        
        for agent in agents:
            results[agent.device_id] = await agent.execute_command(command, params)
        
        return results
    
    def on(self, event: str, handler: Callable):
        """注册事件处理器"""
        if event not in self._event_handlers:
            self._event_handlers[event] = []
        self._event_handlers[event].append(handler)
    
    async def _emit(self, event: str, data: Any = None):
        """触发事件"""
        if event in self._event_handlers:
            for handler in self._event_handlers[event]:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
                except Exception as e:
                    logger.error(f"Event handler error: {e}")
    
    async def start_heartbeat(self, interval: int = 30):
        """启动心跳检测"""
        async def heartbeat_loop():
            while True:
                await asyncio.sleep(interval)
                for device_id, agent in self._agents.items():
                    try:
                        status = await agent.get_status()
                        agent.device_info.last_heartbeat = datetime.now()
                        if status.get("status") == "error":
                            await self._emit("device_error", agent.device_info)
                    except Exception as e:
                        logger.error(f"Heartbeat failed for {device_id}: {e}")
                        agent.device_info.status = DeviceStatus.ERROR
                        await self._emit("device_error", agent.device_info)
        
        self._heartbeat_task = asyncio.create_task(heartbeat_loop())
    
    async def stop_heartbeat(self):
        """停止心跳检测"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None


# ============================================================================
# 全局实例
# ============================================================================

device_manager = DeviceAgentManager()


# ============================================================================
# FastAPI 路由（可选）
# ============================================================================

def create_device_api():
    """创建设备管理 API"""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    
    app = FastAPI(title="UFO Galaxy Device Manager API", version="2.0")
    
    class RegisterDeviceRequest(BaseModel):
        device_id: str
        device_type: str
        device_name: str
        capabilities: List[str] = []
        metadata: Dict[str, Any] = {}
    
    class ExecuteCommandRequest(BaseModel):
        command: str
        params: Dict[str, Any] = {}
    
    @app.post("/devices/register")
    async def register_device(request: RegisterDeviceRequest):
        device_info = DeviceInfo(
            device_id=request.device_id,
            device_type=DeviceType(request.device_type),
            device_name=request.device_name,
            capabilities=[DeviceCapability(c) for c in request.capabilities],
            metadata=request.metadata
        )
        agent = await device_manager.register_device(device_info)
        if agent:
            return {"success": True, "device_id": request.device_id}
        raise HTTPException(status_code=400, detail="Failed to register device")
    
    @app.delete("/devices/{device_id}")
    async def unregister_device(device_id: str):
        success = await device_manager.unregister_device(device_id)
        if success:
            return {"success": True}
        raise HTTPException(status_code=404, detail="Device not found")
    
    @app.get("/devices")
    async def list_devices():
        return await device_manager.get_all_status()
    
    @app.get("/devices/{device_id}")
    async def get_device_status(device_id: str):
        agent = device_manager.get_agent(device_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Device not found")
        return await agent.get_status()
    
    @app.post("/devices/{device_id}/execute")
    async def execute_command(device_id: str, request: ExecuteCommandRequest):
        result = await device_manager.execute_on_device(
            device_id, request.command, request.params
        )
        return result
    
    @app.post("/devices/{device_id}/connect")
    async def connect_device(device_id: str):
        agent = device_manager.get_agent(device_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Device not found")
        success = await agent.connect()
        return {"success": success}
    
    @app.post("/devices/{device_id}/disconnect")
    async def disconnect_device(device_id: str):
        agent = device_manager.get_agent(device_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Device not found")
        success = await agent.disconnect()
        return {"success": success}
    
    return app


# ============================================================================
# 示例使用
# ============================================================================

async def main():
    """示例：如何使用设备管理器"""
    
    # 创建 Android 设备信息
    android_device = DeviceInfo(
        device_id="android_001",
        device_type=DeviceType.ANDROID,
        device_name="My Android Phone",
        capabilities=[
            DeviceCapability.SCREEN_CAPTURE,
            DeviceCapability.UI_AUTOMATION,
            DeviceCapability.CAMERA
        ],
        metadata={
            "manufacturer": "Samsung",
            "model": "Galaxy S24",
            "android_version": "14"
        }
    )
    
    # 注册设备
    agent = await device_manager.register_device(
        android_device,
        server_url="ws://localhost:8765"
    )
    
    # 获取所有设备状态
    all_status = await device_manager.get_all_status()
    print(f"All devices: {json.dumps(all_status, indent=2, default=str)}")
    
    # 在设备上执行命令
    result = await device_manager.execute_on_device(
        "android_001",
        "capture_screen",
        {}
    )
    print(f"Command result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
