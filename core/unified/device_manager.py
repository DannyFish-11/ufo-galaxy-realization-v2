"""
core/unified/device_manager.py
================================
Galaxy 系统统一设备管理器（单例）。

**Authority role (SSOT)**
--------------------------
This class is the *single canonical authority* for all device state mutations
in the Galaxy system.  Every module that needs to register, update, or
unregister a device **must** do so through this class (or the SSOT helper
functions in ``galaxy_gateway.ssot``).

Canonical mutation path::

    caller → galaxy_gateway.ssot.udm_write_*()
            → UnifiedDeviceManager  ← THIS CLASS (SSOT write point)
            → CapabilityBus          (device capabilities propagated automatically)
            → CapabilityAssimilationLayer  (device projected into capability/task/network graphs)

Downstream modules that maintain their own per-device records (e.g.
``core.device_registry``, ``core.device_pool_manager``,
``core.device_status_api``) are **compatibility / scheduling layers**;
they must not act as parallel canonical truth sources.

职责：
  - 设备注册 / 注销 / 状态更新
  - 设备查询（按 ID / 类型 / 在线状态）
  - 向统一连接管理器注册/注销 WebSocket 连接
  - 设备注册后自动向 CapabilityBus 传播设备能力（capability visibility integration）
  - 设备注册后自动将设备能力注入 CapabilityAssimilationLayer（capability graph integration）

所有旧 DeviceManager 实现（galaxy_gateway/handlers/device_manager.py、
enhancements/multidevice/device_manager.py、core/device_agent_manager.py）
均应委托此类管理设备生命周期。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# PR-2 canonical device-state write authority sentinel.
# UDM is the sole canonical write authority for all device state mutations in
# the Galaxy system.  All registration, online/offline transitions, heartbeat
# state updates, and device-state writes MUST pass through this class.
#
# Gateway-originated writes should use galaxy_gateway.ssot.udm_write_*()
# helpers which provide structured error handling and write-through semantics.
#
# Downstream structures (device_registry, device_pool_manager, etc.) are
# compatibility / scheduling layers only and must NOT act as parallel
# canonical truth sources.
# ---------------------------------------------------------------------------
UDM_DEVICE_STATE_AUTHORITY = "UDM::CANONICAL_DEVICE_STATE_WRITE_AUTHORITY"

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

        # Capability visibility integration (Requirement 4):
        # Propagate device capabilities into the canonical CapabilityBus so
        # that consumers of the bus always have an up-to-date view of what
        # each registered device can do.  This is a best-effort, non-blocking
        # call — failure to propagate never prevents device registration.
        self._propagate_capabilities_to_bus(device)

        # Capability graph integration (PR-B2):
        # Project the device into the CapabilityAssimilationLayer so that the
        # capability graph, task graph, and network graph are all aware of this
        # device as a first-class capability provider.  This is idempotent —
        # re-registering the same device_id merges/updates the existing record.
        self._assimilate_device_to_capability_layer(device)
        self._sync_capabilities_to_authority(device)

        # PR-DEVICE-WORKER-FUSION: Register the device as a NATS Worker.
        # This is the convergence point: UDM device IS a Worker. No bridge,
        # no duplication — just a second view of the same entity.
        self._register_device_as_worker(device)

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

        # Remove device capabilities from the canonical CapabilityBus before
        # dropping the device record so the bus stays consistent.
        caps = self._normalize_capabilities(self._devices[device_id].capabilities)
        self._remove_capabilities_from_bus(device_id)
        self._clear_capabilities_from_authority(device_id, caps)

        self._devices.pop(device_id)
        logger.info(
            "Device unregistered",
            extra={"event": "unregister_device", "device_id": device_id},
        )

        # PR-DEVICE-WORKER-FUSION: Remove the device from the NATS Worker plane.
        self._unregister_device_worker(device_id)

    # ------------------------------------------------------------------
    # Internal capability helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_capabilities(raw: Any) -> List[str]:
        """Return a deduplicated, stripped list of non-empty capability strings."""
        return [s for s in (str(c).strip() for c in (raw or [])) if s]

    # ------------------------------------------------------------------
    # Capability-bus integration helpers (private)
    # ------------------------------------------------------------------

    def _propagate_capabilities_to_bus(self, device: UnifiedDevice) -> None:
        """Propagate *device* capabilities into the canonical CapabilityBus.

        This is the automatic bridge that ensures capability visibility is
        updated whenever a device is registered or re-registered through the
        SSOT path.  Each string capability declared by the device is surfaced
        as a ``device__<device_id>__<capability>`` entry in the bus with role
        ``CapabilityBusRole.DEVICE``.

        Failure is logged at DEBUG level and never raises — device registration
        must succeed even if the bus is unavailable.
        """
        caps = self._normalize_capabilities(device.capabilities)
        if not caps:
            return
        try:
            from core.capability_bus import get_capability_bus  # noqa: PLC0415
            bus = get_capability_bus()
            for cap_str in caps:
                bus.register_device_capability(
                    device_id=device.device_id,
                    action=cap_str,
                    description=(
                        f"Capability '{cap_str}' provided by device "
                        f"{device.device_name or device.device_id} "
                        f"(type: {device.device_type})"
                    ),
                    metadata={
                        "device_name": device.device_name or device.device_id,
                        "device_type": str(device.device_type),
                        "source": device.source or "udm",
                    },
                )
            logger.debug(
                "Propagated %d capability/capabilities to CapabilityBus for device %s",
                len(caps),
                device.device_id,
                extra={"event": "capability_bus_propagate", "device_id": device.device_id},
            )
        except Exception as exc:
            logger.debug(
                "CapabilityBus propagation skipped for device %s: %s",
                device.device_id,
                exc,
                extra={"event": "capability_bus_propagate_skip", "device_id": device.device_id},
            )

    def _remove_capabilities_from_bus(self, device_id: str) -> None:
        """Remove all capabilities for *device_id* from the canonical CapabilityBus.

        Called automatically before a device is unregistered.  Failure is
        logged at DEBUG level and never raises.
        """
        device = self._devices.get(device_id)
        if device is None:
            return
        caps = self._normalize_capabilities(device.capabilities)
        if not caps:
            return
        try:
            from core.capability_bus import get_capability_bus  # noqa: PLC0415
            bus = get_capability_bus()
            for cap_str in caps:
                bus.unregister(f"device__{device_id}__{cap_str}")
            logger.debug(
                "Removed %d capability/capabilities from CapabilityBus for device %s",
                len(caps),
                device_id,
                extra={"event": "capability_bus_remove", "device_id": device_id},
            )
        except Exception as exc:
            logger.debug(
                "CapabilityBus removal skipped for device %s: %s",
                device_id,
                exc,
                extra={"event": "capability_bus_remove_skip", "device_id": device_id},
            )

    def _assimilate_device_to_capability_layer(self, device: UnifiedDevice) -> None:
        """Project *device* into the CapabilityAssimilationLayer.

        Ensures the device is a first-class participant in the capability graph,
        task graph, and network graph — not just visible in the CapabilityBus.

        This call is idempotent: re-assimilating the same device_id merges the
        updated capabilities into the existing record without creating duplicate
        entries.  It is safe to call after every registration or capability
        update.

        Failure is logged at DEBUG level and never raises — device registration
        must succeed even if the assimilation layer is unavailable.
        """
        try:
            from core.capability_assimilation import assimilate_device  # noqa: PLC0415
            caps = self._normalize_capabilities(device.capabilities)
            assimilate_device(
                device_id=device.device_id,
                capabilities=caps,
                host=device.ip_address or "localhost",
                port=device.port or 0,
                tags=[str(device.device_type)],
                metadata=dict(device.metadata or {}),
            )
            logger.debug(
                "Assimilated device into CapabilityAssimilationLayer: device_id=%s caps=%d",
                device.device_id,
                len(caps),
                extra={
                    "event": "capability_assimilation_ok",
                    "device_id": device.device_id,
                },
            )
        except Exception as exc:
            logger.debug(
                "CapabilityAssimilationLayer assimilation skipped for device %s: %s",
                device.device_id,
                exc,
                extra={
                    "event": "capability_assimilation_skip",
                    "device_id": device.device_id,
                },
            )

    def _sync_capabilities_to_authority(self, device: UnifiedDevice) -> None:
        """Update unified capability-plane runtime truth for device capabilities."""
        caps = self._normalize_capabilities(device.capabilities)
        if not caps:
            return
        try:
            from core.capability_runtime.capability_state import CapabilityAvailability  # noqa: PLC0415
            from core.unified.capability_authority import CapabilityAuthority  # noqa: PLC0415

            authority = CapabilityAuthority.get_instance()
            availability = (
                CapabilityAvailability.AVAILABLE.value
                if device.status == UnifiedDeviceStatus.ONLINE
                else CapabilityAvailability.UNAVAILABLE.value
            )
            for cap_str in caps:
                authority.update_runtime(
                    f"device__{device.device_id}__{cap_str}",
                    availability=availability,
                    device_bindings=[device.device_id],
                    preferred_device_ids=[device.device_id],
                    metadata={
                        "participant_kind": "device",
                        "network_reachability": "reachable"
                        if device.status == UnifiedDeviceStatus.ONLINE
                        else "offline",
                        "device_status": (
                            device.status.value if hasattr(device.status, "value") else str(device.status)
                        ),
                    },
                    mutation_source="unified_device_manager",
                    lifecycle_event="capability_runtime_updated",
                )
        except Exception as exc:
            logger.debug("CapabilityAuthority device sync skipped for %s: %s", device.device_id, exc)

    def _clear_capabilities_from_authority(self, device_id: str, capabilities: List[str]) -> None:
        """Remove device capability records from the unified capability plane."""
        if not capabilities:
            return
        try:
            from core.unified.capability_authority import CapabilityAuthority  # noqa: PLC0415

            authority = CapabilityAuthority.get_instance()
            for cap_str in capabilities:
                authority.remove(
                    f"device__{device_id}__{cap_str}",
                    mutation_source="unified_device_manager.unregister_device",
                )
        except Exception as exc:
            logger.debug("CapabilityAuthority device removal skipped for %s: %s", device_id, exc)

    # ------------------------------------------------------------------
    # PR-DEVICE-WORKER-FUSION: Device → NATS Worker convergence
    # ------------------------------------------------------------------

    def _register_device_as_worker(self, device: "UnifiedDevice") -> None:
        """Propagate a UDM-registered device into the NATS Worker plane.

        This is the single convergence point where the UDM device becomes a
        NATS Worker. It is called automatically at the end of register_device().
        The operation is best-effort: failure to publish the Worker event does
        NOT fail device registration. The device will still work locally;
        remote dispatch simply won't be available until the NATS connection
        is restored.

        Async note: this method is synchronous (called from sync register_device)
        but the actual NATS publish is async. We schedule it as a background
        task so it never blocks the registration hot path.
        """
        try:
            from core.device_worker_convergence import get_dwc  # noqa: PLC0415

            dwc = get_dwc()
            if not dwc.is_available():
                logger.debug(
                    "Worker convergence skipped: NATS unavailable for device %s",
                    device.device_id,
                )
                return

            # Schedule the async registration as a background task
            # because register_device() is a sync method.
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(dwc.on_device_registered(device))
                logger.debug(
                    "Scheduled Worker registration for device %s",
                    device.device_id,
                )
            except RuntimeError:
                # No running loop — cannot schedule. Log and skip.
                logger.debug(
                    "Worker registration skipped: no event loop for device %s",
                    device.device_id,
                )

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Worker convergence skipped for device %s: %s",
                device.device_id,
                exc,
            )

    def _unregister_device_worker(self, device_id: str) -> None:
        """Remove a device from the NATS Worker plane on unregister.

        Best-effort: failure does NOT prevent device unregistration.
        """
        try:
            from core.device_worker_convergence import get_dwc  # noqa: PLC0415

            dwc = get_dwc()
            if not dwc.is_available():
                return

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(dwc.on_device_unregistered(device_id))
                logger.debug(
                    "Scheduled Worker unregistration for device %s",
                    device_id,
                )
            except RuntimeError:
                logger.debug(
                    "Worker unregistration skipped: no event loop for device %s",
                    device_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Worker convergence unregistration skipped for device %s: %s",
                device_id,
                exc,
            )

    def _sync_worker_heartbeat(self, device_id: str) -> None:
        """Sync a device heartbeat into the NATS Worker plane.

        Called automatically from heartbeat(). Best-effort: failure does
        NOT affect the device's UDM status.
        """
        try:
            from core.device_worker_convergence import get_dwc  # noqa: PLC0415

            dwc = get_dwc()
            if not dwc.is_available():
                return

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(dwc.on_device_heartbeat(device_id))
            except RuntimeError:
                pass
        except Exception:  # noqa: BLE001
            pass

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

        # If capabilities were updated, re-project the device into the
        # CapabilityAssimilationLayer so the capability graph stays current.
        # This handles the case where capabilities arrive after the initial
        # registration (e.g. a separate capability_report message).
        if "capabilities" in fields_changed:
            self._assimilate_device_to_capability_layer(device)
            self._sync_capabilities_to_authority(device)
        elif "status" in fields_changed:
            self._sync_capabilities_to_authority(device)

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
        self._sync_capabilities_to_authority(device)

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

            # PR-DEVICE-WORKER-FUSION: Sync heartbeat to NATS Worker plane.
            self._sync_worker_heartbeat(device_id)

        # Block-4: feed heartbeat into health scorer
        try:
            from core.unified.device_health import get_device_health_scorer
            get_device_health_scorer().heartbeat(device_id)
        except Exception:
            pass
        if device is not None:
            self._sync_capabilities_to_authority(device)

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
