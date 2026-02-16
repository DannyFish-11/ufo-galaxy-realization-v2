"""
Galaxy 硬件抽象层 (Hardware Abstraction Layer)
==============================================
统一的硬件接口，支持多种硬件设备
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger("Galaxy.HAL")

# ============================================================================
# 硬件状态
# ============================================================================

class DeviceStatus(Enum):
    """设备状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    READY = "ready"
    BUSY = "busy"
    ERROR = "error"

class DeviceType(Enum):
    """设备类型"""
    DIGITAL_LIFE_CARD = "digital_life_card"
    ROBOT_DOG = "robot_dog"
    ROBOT_ARM = "robot_arm"
    CAMERA = "camera"
    MICROPHONE = "microphone"
    SERIAL = "serial"
    USB = "usb"
    GPIO = "gpio"
    UNKNOWN = "unknown"

# ============================================================================
# 设备基类
# ============================================================================

@dataclass
class DeviceInfo:
    """设备信息"""
    id: str
    name: str
    type: DeviceType
    status: DeviceStatus = DeviceStatus.DISCONNECTED
    manufacturer: str = ""
    model: str = ""
    connection: str = ""
    capabilities: List[str] = field(default_factory=list)
    last_seen: str = ""
    error_message: str = ""
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "status": self.status.value,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "connection": self.connection,
            "capabilities": self.capabilities
        }

class BaseDevice(ABC):
    """设备基类"""
    
    def __init__(self, device_id: str, name: str, device_type: DeviceType):
        self.info = DeviceInfo(id=device_id, name=name, type=device_type)
        self._callbacks: Dict[str, List[Callable]] = {}
    
    @abstractmethod
    async def connect(self) -> bool:
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        pass
    
    @abstractmethod
    async def get_status(self) -> Dict[str, Any]:
        pass

# ============================================================================
# 数字生命卡
# ============================================================================

class DigitalLifeCard(BaseDevice):
    """数字生命卡 - 流浪地球周边"""
    
    def __init__(self, device_id: str = "digital_life_card"):
        super().__init__(device_id, "数字生命卡", DeviceType.DIGITAL_LIFE_CARD)
        self.info.manufacturer = "流浪地球"
        self.info.capabilities = ["storage", "encryption", "backup"]
        self._storage_path: Optional[Path] = None
    
    async def connect(self) -> bool:
        self._storage_path = Path.home() / ".galaxy" / "digital_life"
        self._storage_path.mkdir(parents=True, exist_ok=True)
        self.info.status = DeviceStatus.CONNECTED
        return True
    
    async def disconnect(self) -> bool:
        self._storage_path = None
        self.info.status = DeviceStatus.DISCONNECTED
        return True
    
    async def get_status(self) -> Dict[str, Any]:
        return {"mounted": self._storage_path is not None, "path": str(self._storage_path)}
    
    async def read_memory(self, key: str) -> Optional[bytes]:
        if not self._storage_path:
            return None
        memory_file = self._storage_path / "memory" / f"{key}.dat"
        if memory_file.exists():
            return memory_file.read_bytes()
        return None
    
    async def write_memory(self, key: str, data: bytes) -> bool:
        if not self._storage_path:
            return False
        memory_dir = self._storage_path / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / f"{key}.dat").write_bytes(data)
        return True

# ============================================================================
# 苯苯机械狗
# ============================================================================

class BenbenRobotDog(BaseDevice):
    """苯苯机械狗 - 流浪地球周边"""
    
    def __init__(self, device_id: str = "benben_dog"):
        super().__init__(device_id, "苯苯机械狗", DeviceType.ROBOT_DOG)
        self.info.manufacturer = "流浪地球"
        self.info.model = "Benben"
        self.info.capabilities = ["move", "posture", "voice", "camera"]
        self._position = {"x": 0, "y": 0, "angle": 0}
    
    async def connect(self) -> bool:
        self.info.status = DeviceStatus.CONNECTED
        return True
    
    async def disconnect(self) -> bool:
        self.info.status = DeviceStatus.DISCONNECTED
        return True
    
    async def get_status(self) -> Dict[str, Any]:
        return {"connected": True, "position": self._position}
    
    async def move(self, direction: str, distance: float = 1.0) -> bool:
        if direction == "forward":
            self._position["y"] += distance
        elif direction == "backward":
            self._position["y"] -= distance
        return True
    
    async def turn(self, angle: float) -> bool:
        self._position["angle"] += angle
        return True
    
    async def stop(self) -> bool:
        return True
    
    async def speak(self, text: str) -> bool:
        return True

# ============================================================================
# HAL 管理器
# ============================================================================

class HAL:
    """硬件抽象层管理器"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self.devices: Dict[str, BaseDevice] = {}
        self.devices["digital_life_card"] = DigitalLifeCard()
        self.devices["benben_dog"] = BenbenRobotDog()
        self._initialized = True
    
    def get_device(self, device_id: str) -> Optional[BaseDevice]:
        return self.devices.get(device_id)
    
    def get_devices(self) -> List[BaseDevice]:
        return list(self.devices.values())
    
    def get_status(self) -> Dict:
        return {
            "devices_count": len(self.devices),
            "devices": [d.info.to_dict() for d in self.devices.values()]
        }

_hal: Optional[HAL] = None

def get_hal() -> HAL:
    global _hal
    if _hal is None:
        _hal = HAL()
    return _hal
