"""
设备管理器

负责:
1. 设备注册和注销
2. 设备信息存储
3. 设备能力查询
4. 设备状态管理
"""

import logging
from typing import Dict, List, Optional, Set
from datetime import datetime

from ..protocol import (
    DeviceInfo, DeviceType, DevicePlatform, DeviceCapability,
    AIPMessage, MessageType
)

logger = logging.getLogger(__name__)


class DeviceManager:
    """设备管理器"""
    
    def __init__(self):
        self.devices: Dict[str, DeviceInfo] = {}
        self.device_status: Dict[str, str] = {}  # device_id -> status
        self.device_last_seen: Dict[str, datetime] = {}
        
    def register_device(self, device_info: DeviceInfo) -> bool:
        """注册设备"""
        device_id = device_info.device_id
        
        if device_id in self.devices:
            logger.info(f"Device {device_id} re-registered, updating info")
        else:
            logger.info(f"New device registered: {device_id}")
        
        self.devices[device_id] = device_info
        self.device_status[device_id] = "online"
        self.device_last_seen[device_id] = datetime.utcnow()
        
        return True
    
    def unregister_device(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self.devices:
            logger.warning(f"Device {device_id} not found for unregistration")
            return False
        
        del self.devices[device_id]
        self.device_status.pop(device_id, None)
        self.device_last_seen.pop(device_id, None)
        
        logger.info(f"Device unregistered: {device_id}")
        return True
    
    def update_device_status(self, device_id: str, status: str):
        """更新设备状态"""
        if device_id in self.devices:
            self.device_status[device_id] = status
            self.device_last_seen[device_id] = datetime.utcnow()
    
    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息"""
        return self.devices.get(device_id)
    
    def get_all_devices(self) -> List[DeviceInfo]:
        """获取所有设备"""
        return list(self.devices.values())
    
    def get_devices_by_type(self, device_type: DeviceType) -> List[DeviceInfo]:
        """按类型获取设备"""
        return [d for d in self.devices.values() if d.device_type == device_type]
    
    def get_devices_by_platform(self, platform: DevicePlatform) -> List[DeviceInfo]:
        """按平台获取设备"""
        return [d for d in self.devices.values() if d.platform == platform]
    
    def get_devices_with_capability(self, capability: DeviceCapability) -> List[DeviceInfo]:
        """获取具有指定能力的设备"""
        return [
            d for d in self.devices.values() 
            if d.capabilities & capability.value
        ]
    
    def get_online_devices(self) -> List[DeviceInfo]:
        """获取在线设备"""
        return [
            d for d in self.devices.values()
            if self.device_status.get(d.device_id) == "online"
        ]
    
    def find_best_device_for_task(
        self, 
        required_capabilities: DeviceCapability,
        preferred_platform: Optional[DevicePlatform] = None
    ) -> Optional[DeviceInfo]:
        """为任务找到最佳设备"""
        candidates = self.get_devices_with_capability(required_capabilities)
        candidates = [d for d in candidates if self.device_status.get(d.device_id) == "online"]
        
        if not candidates:
            return None
        
        # 优先选择指定平台
        if preferred_platform:
            platform_matches = [d for d in candidates if d.platform == preferred_platform]
            if platform_matches:
                candidates = platform_matches
        
        # 返回第一个匹配的设备（可以扩展为更复杂的选择逻辑）
        return candidates[0] if candidates else None
    
    def handle_register_message(self, message: AIPMessage) -> AIPMessage:
        """处理设备注册消息"""
        payload = message.payload
        device_info_data = payload.get("device_info", {})
        
        # 构建 DeviceInfo
        device_info = DeviceInfo(
            device_id=message.device_id,
            device_type=message.device_type or DeviceType.UNKNOWN,
            platform=self._infer_platform(message.device_type),
            **device_info_data
        )
        
        self.register_device(device_info)
        
        # 返回确认消息
        return AIPMessage(
            type=MessageType.DEVICE_REGISTER_ACK,
            device_id=message.device_id,
            correlation_id=message.message_id,
            payload={
                "status": "registered",
                "server_time": datetime.utcnow().isoformat()
            }
        )
    
    def _infer_platform(self, device_type: Optional[DeviceType]) -> DevicePlatform:
        """从设备类型推断平台"""
        if not device_type:
            return DevicePlatform.UNKNOWN
        
        type_str = device_type.value
        if type_str.startswith("android"):
            return DevicePlatform.ANDROID
        elif type_str.startswith("ios"):
            return DevicePlatform.IOS
        elif type_str.startswith("windows"):
            return DevicePlatform.WINDOWS
        elif type_str.startswith("macos"):
            return DevicePlatform.MACOS
        elif type_str.startswith("linux"):
            return DevicePlatform.LINUX
        elif type_str.startswith("cloud"):
            return DevicePlatform.CLOUD
        elif type_str.startswith("embedded") or type_str.startswith("iot"):
            return DevicePlatform.EMBEDDED
        else:
            return DevicePlatform.UNKNOWN
    
    def get_device_count(self) -> int:
        """获取设备总数"""
        return len(self.devices)
    
    def get_online_count(self) -> int:
        """获取在线设备数"""
        return len([s for s in self.device_status.values() if s == "online"])
    
    def to_dict(self) -> dict:
        """导出为字典"""
        return {
            "total_devices": self.get_device_count(),
            "online_devices": self.get_online_count(),
            "devices": [d.model_dump() for d in self.devices.values()]
        }
