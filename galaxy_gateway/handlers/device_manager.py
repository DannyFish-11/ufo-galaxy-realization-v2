"""
设备管理器

负责:
1. 设备注册和注销
2. 设备信息存储
3. 设备能力查询
4. 设备状态管理

适配层：将本地 DeviceInfo/DeviceType 模型转换为统一模型，
委托 core.unified.UnifiedDeviceManager 管理设备生命周期。
"""

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    from core.unified.models import UnifiedDevice

from ..protocol import (
    DeviceInfo, DeviceType, DevicePlatform, DeviceCapability,
    AIPMessage, MessageType
)

logger = logging.getLogger(__name__)


def _to_unified_device(device_info: DeviceInfo) -> "UnifiedDevice":
    """将 gateway DeviceInfo 转换为 UnifiedDevice。"""
    from core.unified.models import UnifiedDevice, UnifiedDeviceType, UnifiedDeviceStatus
    device_type_str = "unknown"
    if device_info.device_type:
        raw = device_info.device_type.value if hasattr(device_info.device_type, "value") else str(device_info.device_type)
        # 取第一段（如 android_phone → android）
        device_type_str = raw.split("_")[0] if "_" in raw else raw
    try:
        utype = UnifiedDeviceType(device_type_str)
    except ValueError:
        utype = UnifiedDeviceType.UNKNOWN

    return UnifiedDevice(
        device_id=device_info.device_id,
        device_name=getattr(device_info, "device_name", device_info.device_id),
        device_type=utype,
        status=UnifiedDeviceStatus.ONLINE,
        capabilities=[
            c.name for c in DeviceCapability
            if getattr(device_info, "capabilities", 0) & c.value
        ] if hasattr(device_info, "capabilities") else [],
        metadata=getattr(device_info, "metadata", {}),
        source="galaxy_gateway",
    )


class DeviceManager:
    """
    设备管理器（适配层）。

    委托 core.unified.UnifiedDeviceManager 管理设备生命周期，
    同时维护本地 self.devices 字典供 gateway 内部协议代码使用。
    """

    def __init__(self):
        self.devices: Dict[str, DeviceInfo] = {}
        self.device_status: Dict[str, str] = {}  # device_id -> status
        self.device_last_seen: Dict[str, datetime] = {}

    @staticmethod
    def _unified():
        from core.unified.device_manager import get_unified_device_manager
        return get_unified_device_manager()

    def register_device(self, device_info: DeviceInfo) -> bool:
        """注册设备（同步到统一设备管理器）。"""
        device_id = device_info.device_id

        if device_id in self.devices:
            logger.info(f"Device {device_id} re-registered, updating info")
        else:
            logger.info(f"New device registered: {device_id}")

        self.devices[device_id] = device_info
        self.device_status[device_id] = "online"
        self.device_last_seen[device_id] = datetime.utcnow()

        # 同步到统一设备管理器
        try:
            self._unified().register_device(_to_unified_device(device_info))
        except Exception as exc:
            logger.warning(f"Failed to sync device {device_id} to UnifiedDeviceManager: {exc}")

        return True

    def unregister_device(self, device_id: str) -> bool:
        """注销设备（同步到统一设备管理器）。"""
        if device_id not in self.devices:
            logger.warning(f"Device {device_id} not found for unregistration")
            return False

        del self.devices[device_id]
        self.device_status.pop(device_id, None)
        self.device_last_seen.pop(device_id, None)

        # 同步到统一设备管理器
        try:
            self._unified().unregister_device(device_id)
        except Exception as exc:
            logger.warning(f"Failed to unregister device {device_id} from UnifiedDeviceManager: {exc}")

        logger.info(f"Device unregistered: {device_id}")
        return True

    def update_device_status(self, device_id: str, status: str):
        """更新设备状态（同步到统一设备管理器）。"""
        if device_id in self.devices:
            self.device_status[device_id] = status
            self.device_last_seen[device_id] = datetime.utcnow()

        # 同步到统一设备管理器
        try:
            from core.unified.models import UnifiedDeviceStatus
            ustat = UnifiedDeviceStatus(status.lower()) if status else UnifiedDeviceStatus.OFFLINE
            self._unified().update_device_status(device_id, ustat)
        except Exception as exc:
            logger.warning(f"Failed to update device status in UnifiedDeviceManager: {exc}")
    
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
        """处理设备注册消息

        Phase 9: 设备注册时进行服务端能力白名单校验，
        过滤非法声明的能力。
        """
        payload = message.payload
        device_info_data = payload.get("device_info", {})

        # Phase 9: 校验设备声明的能力
        reported_capabilities = payload.get(
            "supported_actions",
            payload.get("capabilities", []),
        )
        device_type_str = ""
        if message.device_type:
            device_type_str = message.device_type.value
        if reported_capabilities and device_type_str:
            try:
                from core.tool_permissions import validate_device_capabilities
                validated = validate_device_capabilities(
                    device_type_str, reported_capabilities
                )
                if len(validated) != len(reported_capabilities):
                    logger.info(
                        f"设备 {message.device_id} 能力校验: "
                        f"{len(reported_capabilities)} 声明 → {len(validated)} 通过"
                    )
                # 将校验后的能力写回 payload
                device_info_data["validated_capabilities"] = validated
            except Exception as e:
                logger.debug(f"设备能力校验跳过: {e}")
        
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
