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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .exceptions import DeviceAlreadyRegisteredError, DeviceManagerError, DeviceNotFoundError
from .models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType

logger = logging.getLogger("Galaxy.Unified.DeviceManager")

# Default heartbeat-timeout and grace-period constants (seconds).
_DEFAULT_HEARTBEAT_TIMEOUT_SECS: float = 60.0
_DEFAULT_HEARTBEAT_GRACE_SECS: float = 30.0


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
        注册设备。若设备已存在则仅更新可变字段（去重语义）。

        - 相同 device_id 重复注册不会创建重复条目。
        - 若 metadata / capabilities 等可变字段发生变化，则更新已有条目。
        - registered_at 保持首次注册时间不变。
        - 本方法即为 UDM SSOT 写入点；调用成功后调用方才可更新本地缓存。

        Args:
            device: UnifiedDevice Pydantic 模型实例。
        """
        if not isinstance(device, UnifiedDevice):
            raise DeviceManagerError(
                f"register_device requires a UnifiedDevice instance, got {type(device).__name__}"
            )

        existing = self._devices.get(device.device_id)
        if existing is not None:
            # Preserve the original registration timestamp to avoid identity drift.
            device.registered_at = existing.registered_at
            # Detect metadata / capability changes for structured logging.
            meta_changed = existing.metadata != device.metadata
            caps_changed = existing.capabilities != device.capabilities
            self._devices[device.device_id] = device
            self._devices[device.device_id].status = UnifiedDeviceStatus.ONLINE
            logger.info(
                "Device re-registered (dedup)",
                extra={
                    "event": "register_device_dedup",
                    "device_id": device.device_id,
                    "device_type": device.device_type,
                    "is_new": False,
                    "meta_changed": meta_changed,
                    "caps_changed": caps_changed,
                },
            )
        else:
            device.registered_at = datetime.now(timezone.utc)
            device.status = UnifiedDeviceStatus.ONLINE
            self._devices[device.device_id] = device
            logger.info(
                "Device registered",
                extra={
                    "event": "register_device",
                    "device_id": device.device_id,
                    "device_type": device.device_type,
                    "is_new": True,
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
        device.last_heartbeat = datetime.now(timezone.utc)
        logger.debug(
            "Device status updated",
            extra={"event": "status_update", "device_id": device_id, "status": status},
        )

    def heartbeat(self, device_id: str) -> None:
        """记录设备心跳；若设备处于离线/错误态则自动恢复为 ONLINE。"""
        device = self._devices.get(device_id)
        if device is not None:
            device.last_heartbeat = datetime.now(timezone.utc)
            active = {UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value,
                      UnifiedDeviceStatus.BUSY, UnifiedDeviceStatus.BUSY.value}
            if device.status not in active:
                device.status = UnifiedDeviceStatus.ONLINE
                logger.info(
                    "Device recovered to ONLINE on heartbeat",
                    extra={"event": "heartbeat_recovery", "device_id": device_id},
                )

    async def check_heartbeat_timeouts(
        self,
        timeout_secs: float = _DEFAULT_HEARTBEAT_TIMEOUT_SECS,
        grace_secs: float = _DEFAULT_HEARTBEAT_GRACE_SECS,
    ) -> List[str]:
        """检查所有在线设备的心跳超时，对超时设备自动标记为离线。

        避免 flapping：仅当超过 ``timeout_secs + grace_secs`` 无心跳时才标记离线。
        设备收到新心跳（调用 :meth:`heartbeat`）后会自动恢复为 ONLINE。

        Args:
            timeout_secs: 基础心跳超时阈值（秒）。
            grace_secs:   额外宽限期（秒），减少 flapping。

        Returns:
            被标记为离线的设备 ID 列表。
        """
        threshold = timeout_secs + grace_secs
        now = datetime.now(timezone.utc)
        marked_offline: List[str] = []

        online_values = {
            UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value,
            UnifiedDeviceStatus.BUSY, UnifiedDeviceStatus.BUSY.value,
        }

        for device in list(self._devices.values()):
            if device.status not in online_values:
                continue
            if device.last_heartbeat is None:
                # 从未收到心跳，从注册时间起算
                ref = device.registered_at
            else:
                ref = device.last_heartbeat

            # Ensure ref is timezone-aware for comparison.
            # Backward-compatibility guard: devices registered before the
            # UTC-aware migration may still carry naive datetimes.
            if ref.tzinfo is None:
                ref = ref.replace(tzinfo=timezone.utc)

            elapsed = (now - ref).total_seconds()
            if elapsed > threshold:
                device.status = UnifiedDeviceStatus.OFFLINE
                marked_offline.append(device.device_id)
                logger.warning(
                    "Device auto-offline: no heartbeat within timeout+grace",
                    extra={
                        "event": "heartbeat_timeout_offline",
                        "device_id": device.device_id,
                        "elapsed_secs": round(elapsed, 1),
                        "threshold_secs": threshold,
                    },
                )

        return marked_offline

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

    def get_autonomous_devices(self) -> List[UnifiedDevice]:
        """返回声明了高层自治能力的在线设备（metadata.goal_execution_enabled=True）。"""
        result = []
        for device in self.get_online_devices():
            meta = device.metadata or {}
            if meta.get("goal_execution_enabled") or meta.get("local_model_enabled"):
                result.append(device)
        return result

    def get_devices_with_capability(self, capability_name: str) -> List[UnifiedDevice]:
        """按能力名称筛选在线设备（capabilities 列表或 metadata 中声明）。"""
        cap_lower = capability_name.lower()
        result = []
        for device in self.get_online_devices():
            # 检查低层能力列表
            if any(cap_lower == str(c).lower() for c in (device.capabilities or [])):
                result.append(device)
                continue
            # 检查高层自治能力（metadata key）
            meta = device.metadata or {}
            if meta.get(cap_lower) or meta.get(capability_name):
                result.append(device)
        return result

    def get_device_type(self, device_id: str) -> Optional[str]:
        """Return the normalised device-type string for *device_id*.

        Returns the string value of the device's ``device_type`` field
        (e.g. ``"android"``, ``"windows"``), or ``None`` when the device
        is not registered.

        This is the SSOT accessor used by policy modules such as
        :mod:`core.device_policy` to determine routing behaviour without
        importing model classes directly.

        Parameters
        ----------
        device_id:
            Unique device identifier.

        Returns
        -------
        str | None
            Lower-case device-type string, or ``None`` if unknown.
        """
        device = self._devices.get(device_id)
        if device is None:
            return None
        dt = device.device_type
        # device_type may be stored as an enum instance or a plain string
        # depending on whether use_enum_values propagated correctly.
        if hasattr(dt, "value"):
            return str(dt.value)
        return str(dt) if dt else None

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


def get_unified_device_manager() -> "UnifiedDeviceManager":
    """返回进程级 UnifiedDeviceManager 单例。

    直接委托给类自身的 __new__ 单例机制，避免双重 cache 导致的测试隔离问题。
    """
    return UnifiedDeviceManager()
