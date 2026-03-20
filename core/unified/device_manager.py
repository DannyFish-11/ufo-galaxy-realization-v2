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
        upsert_device_state(device_id, patch, source) -> Optional[UnifiedDevice]
        update_device_status(device_id, status) -> None
        heartbeat(device_id) -> None
        get_device(device_id) -> Optional[UnifiedDevice]
        list_devices() -> List[UnifiedDevice]
        get_devices_by_type(device_type) -> List[UnifiedDevice]
        get_online_devices() -> List[UnifiedDevice]

    所有设备状态写入必须经由本类（SSOT 唯一写入口）。
    外部代码应优先调用 upsert_device_state() 进行状态更新，
    update_device_status() 和 heartbeat() 作为向后兼容入口保留。
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

    def upsert_device_state(
        self,
        device_id: str,
        patch: "Dict[str, Any]",
        source: str = "unknown",
    ) -> "Optional[UnifiedDevice]":
        """对已注册设备执行 部分或全量 状态更新（SSOT 唯一写入口）。

        采用 **prefer-latest** 冲突策略：``updated_at`` 时间戳最新的写入总是胜出；
        每次成功写入后 ``state_version`` 单调递增，便于下游追踪版本漂移。

        支持的 ``patch`` 字段（所有字段均为可选）：
            - ``status``       (str | UnifiedDeviceStatus)
            - ``device_name``  (str)
            - ``ip_address``   (str)
            - ``port``         (int)
            - ``capabilities`` (list[str]) — 全量替换
            - ``metadata``     (dict) — 深度合并
            - ``source``       (str) — 覆盖来源标记

        Args:
            device_id: 目标设备 ID。
            patch:     字段 → 新值的字典，支持部分更新。
            source:    本次写入的来源标识（如 "heartbeat"、"device_router"、"rest_register"）。

        Returns:
            更新后的 UnifiedDevice，若设备未找到则返回 None。
        """
        device = self._devices.get(device_id)
        if device is None:
            logger.warning(
                "upsert_device_state called for unknown device",
                extra={"event": "upsert_miss", "device_id": device_id, "source": source},
            )
            return None

        now = datetime.now(timezone.utc)
        fields_changed: list = []

        # -- status --
        if "status" in patch:
            new_status = patch["status"]
            if not isinstance(new_status, UnifiedDeviceStatus):
                try:
                    new_status = UnifiedDeviceStatus(str(new_status).lower())
                except ValueError:
                    new_status = UnifiedDeviceStatus.ONLINE
            if device.status != new_status:
                device.status = new_status
                fields_changed.append("status")

        # -- device_name --
        if "device_name" in patch and patch["device_name"]:
            if device.device_name != patch["device_name"]:
                device.device_name = patch["device_name"]
                fields_changed.append("device_name")

        # -- ip_address --
        if "ip_address" in patch:
            if device.ip_address != patch["ip_address"]:
                device.ip_address = patch["ip_address"]
                fields_changed.append("ip_address")

        # -- port --
        if "port" in patch:
            if device.port != patch["port"]:
                device.port = patch["port"]
                fields_changed.append("port")

        # -- capabilities (full replace) --
        if "capabilities" in patch and patch["capabilities"] is not None:
            new_caps = list(patch["capabilities"])
            if device.capabilities != new_caps:
                device.capabilities = new_caps
                fields_changed.append("capabilities")

        # -- metadata (deep merge) --
        if "metadata" in patch and isinstance(patch["metadata"], dict):
            merged = dict(device.metadata or {})
            merged.update(patch["metadata"])
            if merged != device.metadata:
                device.metadata = merged
                fields_changed.append("metadata")

        # -- source override --
        if "source" in patch and patch["source"]:
            device.source = patch["source"]

        # Always update heartbeat timestamp and bump version counter.
        device.last_heartbeat = now
        device.updated_at = now
        device.state_version = (device.state_version or 0) + 1

        logger.info(
            "Device state upserted",
            extra={
                "event": "upsert_device_state",
                "device_id": device_id,
                "source": source,
                "state_version": device.state_version,
                "fields_changed": fields_changed,
                "status": device.status,
                "timestamp": now.isoformat(),
            },
        )
        return device

    def update_device_status(self, device_id: str, status: UnifiedDeviceStatus) -> None:
        """更新设备状态。"""
        device = self._devices.get(device_id)
        if device is None:
            logger.warning(
                "update_device_status called for unknown device",
                extra={"event": "status_update_miss", "device_id": device_id},
            )
            return

        now = datetime.now(timezone.utc)
        device.status = status
        device.last_heartbeat = now
        device.updated_at = now
        device.state_version = (device.state_version or 0) + 1
        logger.debug(
            "Device status updated",
            extra={
                "event": "status_update",
                "device_id": device_id,
                "status": status,
                "state_version": device.state_version,
            },
        )

    def heartbeat(self, device_id: str) -> None:
        """记录设备心跳；若设备处于离线/错误态则自动恢复为 ONLINE。

        Block-4 addition: also records a heartbeat sample in
        :class:`~core.unified.device_health.DeviceHealthScorer` for health
        scoring purposes.
        """
        device = self._devices.get(device_id)
        if device is not None:
            now = datetime.now(timezone.utc)
            device.last_heartbeat = now
            device.updated_at = now
            device.state_version = (device.state_version or 0) + 1
            active = {UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value,
                      UnifiedDeviceStatus.BUSY, UnifiedDeviceStatus.BUSY.value}
            if device.status not in active:
                device.status = UnifiedDeviceStatus.ONLINE
                logger.info(
                    "Device recovered to ONLINE on heartbeat",
                    extra={
                        "event": "heartbeat_recovery",
                        "device_id": device_id,
                        "state_version": device.state_version,
                    },
                )

        # Block-4: feed heartbeat into health scorer
        try:
            from core.unified.device_health import get_device_health_scorer
            get_device_health_scorer().heartbeat(device_id)
        except Exception:
            pass

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

    def get_device_health(self, device_id: str) -> Optional[Any]:
        """Return the :class:`~core.unified.device_health.HealthScore` for *device_id*.

        Returns ``None`` if the health scorer is unavailable.

        Block-4 addition.
        """
        try:
            from core.unified.device_health import get_device_health_scorer
            return get_device_health_scorer().score(device_id)
        except Exception:
            return None

    def get_online_devices_by_health(self) -> List[UnifiedDevice]:
        """Return online devices ordered by descending health score.

        Devices without health data are placed at the end of the list with a
        default score of 1.0 (optimistic).

        Block-4 addition.
        """
        devices = self.get_online_devices()
        try:
            from core.unified.device_health import get_device_health_scorer
            scorer = get_device_health_scorer()
            return sorted(
                devices,
                key=lambda d: scorer.score(d.device_id).total_score,
                reverse=True,
            )
        except Exception:
            return devices

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
