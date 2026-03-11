"""
core/unified/device_manager.py
================================
Galaxy 系统统一设备管理器（单例）。

职责：
  - 设备注册 / 注销 / 状态更新
  - 设备查询（按 ID / 类型 / 在线状态）
  - 向统一连接管理器注册/注销 WebSocket 连接

所有旧 DeviceManager 实现（galaxy_gateway/handlers/device_manager.py、
enhancements/multidevice/device_manager.py、core/device_agent_manager.py）
均应委托此类管理设备生命周期。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .exceptions import DeviceAlreadyRegisteredError, DeviceManagerError, DeviceNotFoundError
from .models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType

logger = logging.getLogger("Galaxy.Unified.DeviceManager")


class UnifiedDeviceManager:
    """
    统一设备管理器（进程级单例）。

    公开 API：
        register_device(device: UnifiedDevice) -> None
        unregister_device(device_id: str) -> None
        update_device_status(device_id, status) -> None
        get_device(device_id) -> Optional[UnifiedDevice]
        list_devices() -> List[UnifiedDevice]
        get_devices_by_type(device_type) -> List[UnifiedDevice]
        get_online_devices() -> List[UnifiedDevice]
    """

    _instance: Optional["UnifiedDeviceManager"] = None

    def __new__(cls) -> "UnifiedDeviceManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return

        # device_id → UnifiedDevice
        self._devices: Dict[str, UnifiedDevice] = {}
        self._lock = asyncio.Lock()
        self._initialized = True

        logger.info(
            "UnifiedDeviceManager initialized",
            extra={"event": "init"},
        )

    # ------------------------------------------------------------------
    # 注册 / 注销
    # ------------------------------------------------------------------

    def register_device(self, device: UnifiedDevice) -> None:
        """
        注册设备。若设备已存在则更新信息（重新注册语义）。

        Args:
            device: UnifiedDevice Pydantic 模型实例。
        """
        if not isinstance(device, UnifiedDevice):
            raise DeviceManagerError(
                f"register_device requires a UnifiedDevice instance, got {type(device).__name__}"
            )

        is_new = device.device_id not in self._devices
        if is_new:
            device.registered_at = datetime.utcnow()
        device.status = UnifiedDeviceStatus.ONLINE
        self._devices[device.device_id] = device

        logger.info(
            "Device registered" if is_new else "Device re-registered",
            extra={
                "event": "register_device",
                "device_id": device.device_id,
                "device_type": device.device_type,
                "is_new": is_new,
            },
        )

    def register_device_from_dict(self, device_id: str, data: Dict[str, Any]) -> UnifiedDevice:
        """
        从字典构建并注册 UnifiedDevice（向后兼容旧注册路径使用）。

        Returns:
            已注册的 UnifiedDevice 实例。
        """
        device_type_raw = data.get("device_type", "unknown")
        try:
            device_type = UnifiedDeviceType(str(device_type_raw).lower())
        except ValueError:
            device_type = UnifiedDeviceType.UNKNOWN

        status_raw = data.get("status", "online")
        try:
            status = UnifiedDeviceStatus(str(status_raw).lower())
        except ValueError:
            status = UnifiedDeviceStatus.ONLINE

        device = UnifiedDevice(
            device_id=device_id,
            device_name=data.get("device_name") or data.get("name") or device_id,
            device_type=device_type,
            status=status,
            ip_address=data.get("ip_address") or data.get("ip"),
            port=data.get("port"),
            capabilities=data.get("capabilities") or [],
            metadata={k: v for k, v in data.items() if k not in {
                "device_id", "device_name", "name", "device_type",
                "status", "ip_address", "ip", "port", "capabilities",
            }},
            source=data.get("source", "dict_registration"),
        )
        self.register_device(device)
        return device

    def unregister_device(self, device_id: str) -> None:
        """注销设备。"""
        if device_id not in self._devices:
            logger.warning(
                "Attempted to unregister unknown device",
                extra={"event": "unregister_unknown", "device_id": device_id},
            )
            return

        self._devices.pop(device_id)
        logger.info(
            "Device unregistered",
            extra={"event": "unregister_device", "device_id": device_id},
        )

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------

    def update_device_status(self, device_id: str, status: UnifiedDeviceStatus) -> None:
        """更新设备状态。"""
        device = self._devices.get(device_id)
        if device is None:
            logger.warning(
                "update_device_status called for unknown device",
                extra={"event": "status_update_miss", "device_id": device_id},
            )
            return

        device.status = status
        device.last_heartbeat = datetime.utcnow()
        logger.debug(
            "Device status updated",
            extra={"event": "status_update", "device_id": device_id, "status": status},
        )

    def heartbeat(self, device_id: str) -> None:
        """记录设备心跳。"""
        device = self._devices.get(device_id)
        if device is not None:
            device.last_heartbeat = datetime.utcnow()
            active = {UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value,
                      UnifiedDeviceStatus.BUSY, UnifiedDeviceStatus.BUSY.value}
            if device.status not in active:
                device.status = UnifiedDeviceStatus.ONLINE

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_device(self, device_id: str) -> Optional[UnifiedDevice]:
        """获取设备，不存在返回 None。"""
        return self._devices.get(device_id)

    def list_devices(self) -> List[UnifiedDevice]:
        """返回所有已注册设备列表。"""
        return list(self._devices.values())

    def get_devices_by_type(self, device_type: UnifiedDeviceType) -> List[UnifiedDevice]:
        """按设备类型筛选。"""
        target = device_type.value if isinstance(device_type, UnifiedDeviceType) else str(device_type).lower()
        return [d for d in self._devices.values() if d.device_type in (target, device_type)]

    def get_online_devices(self) -> List[UnifiedDevice]:
        """返回所有在线设备。"""
        online_values = {
            UnifiedDeviceStatus.ONLINE.value, UnifiedDeviceStatus.ONLINE,
            UnifiedDeviceStatus.BUSY.value, UnifiedDeviceStatus.BUSY,
        }
        return [d for d in self._devices.values() if d.status in online_values]

    def get_device_count(self) -> int:
        """设备总数。"""
        return len(self._devices)

    def get_online_count(self) -> int:
        """在线设备数。"""
        return len(self.get_online_devices())

    def to_dict(self) -> Dict[str, Any]:
        """导出为可序列化字典。"""
        return {
            "total_devices": self.get_device_count(),
            "online_devices": self.get_online_count(),
            "devices": [d.model_dump() for d in self._devices.values()],
        }


# ============================================================================
# 进程级单例访问函数
# ============================================================================


_manager: Optional[UnifiedDeviceManager] = None


def get_unified_device_manager() -> UnifiedDeviceManager:
    """返回进程级 UnifiedDeviceManager 单例。"""
    global _manager
    if _manager is None:
        _manager = UnifiedDeviceManager()
    return _manager
