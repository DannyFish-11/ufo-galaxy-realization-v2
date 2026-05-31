"""core/device_registry.py
========================
Galaxy — Legacy-compatible device indexing and discovery layer.

ARCHITECTURE ROLE (PR-4)
------------------------
``DeviceRegistry`` is a **compatibility / indexing / discovery layer** layered
over the canonical device authority chain defined in PR-1:

- ``UnifiedDeviceManager`` (UDM) — canonical write SSOT for device
  registration and mutable device state.
- ``RegisteredRuntimeDevice`` — canonical single-device read contract.
- ``MultiDeviceRuntimeProjection`` — canonical multi-device runtime projection.

``DeviceRegistry`` is **not** a peer canonical truth source.  Its
responsibilities are:

1. **Forwarding** all canonical registration / status / heartbeat writes to
   UDM first.
2. **Maintaining local indexes** — group membership, tag index, capability
   index — as convenience data structures layered over UDM-owned state.
3. **Persistence snapshot / cache** — the on-disk storage is treated as a
   snapshot or projection cache, *not* as a canonical source of device truth.
   Devices restored from disk are always loaded in the OFFLINE state and must
   re-register through UDM to obtain authoritative online status.
4. **Discovery helpers** — ``discover()`` / ``negotiate_capability()`` /
   ``get_devices_by_group()`` / ``get_devices_by_tag()`` operate as
   compatibility utilities that query the local index.
5. **Projection bridge** — ``project_to_contract(device_id)`` normalises a
   registry-local record into the canonical ``RegisteredRuntimeDevice``
   contract so that downstream consumers do not need to depend on the
   registry's internal model.

Event callbacks (``on_device_registered`` / ``on_device_online`` /
``on_device_offline``) are preserved for backward compatibility.

Usage::

    from core.device_registry import device_registry

    # Register device — writes to UDM first, then updates local index.
    device = await device_registry.register(
        device_id="android_001",
        device_type="android",
        name="My Phone",
        capabilities=["screen", "camera", "microphone"],
    )

    # Discover devices from local index (compatibility helper).
    devices = await device_registry.discover()

    # Get a device record (UDM-status reflected in local cache).
    device = device_registry.get("android_001")

    # Project to canonical contract.
    contract = device_registry.project_to_contract("android_001")
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime

from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("Galaxy.DeviceRegistry")

# ---------------------------------------------------------------------------
# Architecture role declaration (PR-4)
# ---------------------------------------------------------------------------
#
# This constant documents the architectural role of DeviceRegistry.
# It is intentionally readable so that grep/audit tools can confirm demotion.

_REGISTRY_ROLE = (
    "compatibility_indexing_discovery_layer"
    " — not a canonical device truth source"
    " — canonical authority is UnifiedDeviceManager (UDM)"
)



def _get_udm():
    """Lazily return the UnifiedDeviceManager singleton (avoids circular imports)."""
    try:
        from core.unified.device_manager import get_unified_device_manager
        return get_unified_device_manager()
    except Exception as _e:
        logger.debug("_get_udm: failed to obtain UDM singleton — %s", _e)
        return None


# ============================================================================
# 数据模型 — 统一使用 core.schemas.device 中的 Pydantic V2 模型
# ============================================================================

from core.device_types import DeviceType, DeviceStatus  # noqa: E402 — 单一事实来源
from core.schemas.device import (  # noqa: E402
    DeviceModel as Device,
    DeviceCapabilityModel as DeviceCapability,
)


# ============================================================================
# 设备注册管理器
# ============================================================================

class DeviceRegistry:
    """Compatibility / indexing / discovery layer over the UDM canonical authority.

    PR-4 architecture role: ``_REGISTRY_ROLE``

    This class is **not** a canonical device truth source.  All registration
    and mutable-state writes are forwarded to ``UnifiedDeviceManager`` (UDM)
    first; the local ``devices`` dict, group/tag/capability indexes, and
    on-disk snapshot are maintained only as a compatibility convenience layer.

    Canonical authority chain (PR-1)
    ---------------------------------
    - Write SSOT : ``UnifiedDeviceManager.register_device / upsert_device_state``
    - Single-device read contract : ``RegisteredRuntimeDevice``
    - Multi-device read projection : ``MultiDeviceRuntimeProjection``

    This registry's persistence is treated as a **snapshot / projection cache**.
    Devices loaded from disk are always restored in the OFFLINE state; they do
    not re-acquire authoritative online status until they register again through
    the normal UDM write path.
    """
    
    _instance = None
    
    def __init__(self):
        # 设备存储
        self.devices: Dict[str, Device] = {}
        
        # 设备分组
        self.groups: Dict[str, List[str]] = {}  # group_name -> [device_ids]
        
        # 设备标签索引
        self.tag_index: Dict[str, List[str]] = {}  # tag -> [device_ids]
        
        # 能力索引
        self.capability_index: Dict[str, List[str]] = {}  # capability -> [device_ids]
        
        # 持久化路径
        self.storage_path = Path("data/devices.json")
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 事件回调
        self._on_device_registered: List[Callable] = []
        self._on_device_offline: List[Callable] = []
        self._on_device_online: List[Callable] = []
        
        # 加载已保存的设备
        self._load()
        
        logger.info(f"设备注册管理器初始化，已加载 {len(self.devices)} 个设备")
    
    @classmethod
    def get_instance(cls) -> "DeviceRegistry":
        # NOTE: This singleton is used for process-wide state sharing.
        # Avoid adding new call sites — prefer dependency injection where
        # possible to improve testability.  See ARCHITECTURE_REVIEW.md
        # (Singleton Guardrails section) for the planned refactor strategy.
        if cls._instance is None:
            cls._instance = DeviceRegistry()
        return cls._instance
    
    # ========================================================================
    # 设备注册
    # ========================================================================
    
    async def register(
        self,
        device_id: str = None,
        device_type: str = "custom",
        name: str = "",
        capabilities: List[str] = None,
        capability_details: List[Dict] = None,
        groups: List[str] = None,
        tags: List[str] = None,
        ip_address: str = "",
        port: int = 0,
        mac_address: str = "",
        manufacturer: str = "",
        model: str = "",
        os_version: str = "",
        app_version: str = "",
        metadata: Dict[str, Any] = None,
        **kwargs,
    ) -> Device:
        """Register a device.

        UDM-first semantics (PR-4)
        --------------------------
        Canonical identity and mutable state are owned by UDM.  This method:

        1. Delegates the canonical write to ``UnifiedDeviceManager`` first.
        2. Checks whether UDM already holds a record for *device_id* before
           constructing local state — this prevents divergent canonical
           identity when the device is registered more than once.
        3. Maintains the local compatibility index (groups / tags /
           capability index) as a convenience layer on top of UDM state.

        Args:
            device_id: Device ID (auto-generated when not provided).
            device_type: Device type string.
            name: Human-readable device name.
            capabilities: List of capability name strings.
            capability_details: Per-capability detail dicts.
            groups: Group membership list.
            tags: Freeform classification tags.
            ip_address: IP address string.
            port: Port number.
            mac_address: MAC address string.
            manufacturer: Manufacturer name.
            model: Model name.
            os_version: OS version string.
            app_version: App version string.
            metadata: Arbitrary extension metadata.

        Returns:
            The local ``Device`` compatibility record.
        """
        # 生成设备 ID
        if not device_id:
            device_id = f"{device_type}_{uuid.uuid4().hex[:8]}"

        # 解析设备类型
        try:
            dev_type = DeviceType(device_type.lower())
        except ValueError:
            dev_type = DeviceType.CUSTOM

        # 合并额外字段到 metadata
        _metadata = metadata or {}
        for key, value in kwargs.items():
            _metadata[key] = value

        # ── SSOT: write to UDM first ─────────────────────────────────────
        # Canonical identity is owned by UDM.  Write there before touching
        # any local index state so that duplicate registrations converge on
        # a single UDM record rather than creating divergent copies.
        udm = _get_udm()
        if udm is not None:
            try:
                udm.register_device_from_dict(device_id, {
                    "device_name": name or f"{device_type}_{device_id[:8]}",
                    "device_type": device_type,
                    "capabilities": capabilities or [],
                    "source": "device_registry",
                    **(_metadata or {}),
                })
                logger.debug("DeviceRegistry.register: UDM write succeeded for %s", device_id)
            except Exception as _udm_err:
                logger.warning(
                    "DeviceRegistry.register: UDM write failed for %s — %s", device_id, _udm_err
                )

        # ── Local compatibility record ────────────────────────────────────
        # If the device was already registered in the local index, reuse the
        # existing record so we do not create a divergent local entry.
        existing = self.devices.get(device_id)
        if existing is not None:
            # Refresh timestamps and mutable fields on the existing record.
            now = time.time()
            existing.last_seen = now
            existing.last_heartbeat = now
            existing.status = DeviceStatus.ONLINE
            # Merge any new group/tag additions requested by this call.
            self._merge_groups_and_tags(existing, groups, tags)
            self._update_indexes(existing)
            self._save()
            await self._emit_event("registered", existing)
            logger.info("DeviceRegistry.register: reused existing local record for %s", device_id)
            return existing

        # 构建能力列表
        cap_list = []
        if capabilities:
            for i, cap_name in enumerate(capabilities):
                details = {}
                if capability_details and i < len(capability_details):
                    details = capability_details[i]

                cap_list.append(DeviceCapability(
                    name=cap_name,
                    description=details.get("description", ""),
                    available=details.get("available", True),
                    params=details.get("params", {}),
                ))

        # 创建设备对象（Pydantic V2 模型）
        now = time.time()
        device = Device(
            device_id=device_id,
            device_type=dev_type,
            name=name or f"{device_type}_{device_id[:8]}",
            status=DeviceStatus.ONLINE,
            manufacturer=manufacturer,
            model_name=model,
            os_version=os_version,
            app_version=app_version,
            capabilities=cap_list,
            groups=groups or [],
            tags=tags or [],
            ip_address=ip_address,
            port=port,
            mac_address=mac_address,
            metadata=_metadata,
            registered_at=now,
            last_seen=now,
            last_heartbeat=now,
        )

        # 存储本地缓存
        self.devices[device_id] = device
        
        # 更新索引
        self._update_indexes(device)
        
        # 保存
        self._save()
        
        # 触发事件
        await self._emit_event("registered", device)
        
        logger.info("DeviceRegistry.register: new local record created for %s (%s)", device_id, device_type)
        
        return device
    
    async def unregister(self, device_id: str) -> bool:
        """注销设备"""
        # ── SSOT: write to UDM first ─────────────────────────────────────
        udm = _get_udm()
        if udm is not None:
            try:
                udm.unregister_device(device_id)
                logger.debug("DeviceRegistry.unregister: UDM write succeeded for %s", device_id)
            except Exception as _udm_err:
                logger.warning(
                    "DeviceRegistry.unregister: UDM write failed for %s — %s", device_id, _udm_err
                )

        device = self.devices.pop(device_id, None)
        if device is None:
            return False
        
        # 更新索引
        self._remove_from_indexes(device)
        
        # 保存
        self._save()
        
        logger.info(f"设备注销: {device_id}")
        
        return True
    
    def get(self, device_id: str) -> Optional[Device]:
        """Return a local compatibility record for *device_id*.

        UDM-first semantics (PR-4)
        --------------------------
        When UDM is available the local record's ``status`` is refreshed from
        the canonical UDM state before being returned, so callers receive a
        status value that reflects authoritative online/offline truth rather
        than a potentially stale local cache value.

        If UDM is unavailable the local cache entry is returned as-is.
        """
        udm = _get_udm()
        local = self.devices.get(device_id)
        if udm is not None:
            try:
                udm_dev = udm.get_device(device_id)
                if udm_dev is not None and local is not None:
                    # Reflect authoritative UDM status into the local record.
                    try:
                        local.status = DeviceStatus(
                            udm_dev.status.value
                            if hasattr(udm_dev.status, "value")
                            else str(udm_dev.status).lower()
                        )
                    except ValueError as _ve:
                        logger.debug(
                            "DeviceRegistry.get: unrecognised UDM status for %s — %s",
                            device_id, _ve,
                        )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
        return local
    
    async def get_or_create(self, device_id: str, **kwargs) -> Device:
        """获取或创建设备"""
        device = self.devices.get(device_id)
        if device:
            device.last_seen = time.time()
            device.status = DeviceStatus.ONLINE
            return device

        # 创建新设备
        return await self.register(device_id=device_id, **kwargs)
    
    # ========================================================================
    # 设备发现
    # ========================================================================
    
    async def discover(
        self,
        device_type: str = None,
        capability: str = None,
        group: str = None,
        tag: str = None,
        online_only: bool = True,
    ) -> List[Device]:
        """
        发现设备
        
        Args:
            device_type: 设备类型过滤
            capability: 能力过滤
            group: 分组过滤
            tag: 标签过滤
            online_only: 只返回在线设备
        
        Returns:
            设备列表
        """
        results = list(self.devices.values())
        
        # 按类型过滤
        if device_type:
            try:
                dev_type = DeviceType(device_type.lower())
                results = [d for d in results if d.device_type == dev_type]
            except ValueError:
                pass
        
        # 按能力过滤
        if capability:
            device_ids = self.capability_index.get(capability, [])
            results = [d for d in results if d.device_id in device_ids]
        
        # 按分组过滤
        if group:
            device_ids = self.groups.get(group, [])
            results = [d for d in results if d.device_id in device_ids]
        
        # 按标签过滤
        if tag:
            device_ids = self.tag_index.get(tag, [])
            results = [d for d in results if d.device_id in device_ids]
        
        # 只返回在线设备
        if online_only:
            results = [d for d in results if d.is_online()]
        
        return results
    
    def list_devices(
        self,
        device_type: str = None,
        status: DeviceStatus = None,
    ) -> List[Device]:
        """列出设备（优先从 UDM 读取，本地缓存补充遗留条目）"""
        # Use local cache as primary source but reflect online/offline status from UDM
        udm = _get_udm()
        if udm is not None:
            try:
                udm_ids = {d.device_id for d in udm.list_devices()}
                # Bring UDM status into the local cache entries
                for did in list(self.devices.keys()):
                    udm_dev = udm.get_device(did)
                    if udm_dev is not None:
                        try:
                            self.devices[did].status = DeviceStatus(udm_dev.status.value if hasattr(udm_dev.status, "value") else str(udm_dev.status).lower())
                        except ValueError:
                            pass
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        results = list(self.devices.values())
        
        if device_type:
            try:
                dev_type = DeviceType(device_type.lower())
                results = [d for d in results if d.device_type == dev_type]
            except ValueError:
                pass
        
        if status:
            results = [d for d in results if d.status == status]
        
        return results
    
    # ========================================================================
    # 设备状态管理
    # ========================================================================
    
    async def update_status(
        self,
        device_id: str,
        status: DeviceStatus = None,
        heartbeat: bool = False,
    ) -> bool:
        """更新设备状态"""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        # ── SSOT: write to UDM first ─────────────────────────────────────
        udm = _get_udm()
        if udm is not None:
            try:
                if heartbeat:
                    udm.heartbeat(device_id)
                if status is not None:
                    from core.unified.models import UnifiedDeviceStatus
                    try:
                        udm_status = UnifiedDeviceStatus(status.value if hasattr(status, "value") else str(status).lower())
                    except ValueError:
                        udm_status = UnifiedDeviceStatus.ONLINE
                    udm.update_device_status(device_id, udm_status)
                logger.debug("DeviceRegistry.update_status: UDM write succeeded for %s", device_id)
            except Exception as _udm_err:
                logger.warning(
                    "DeviceRegistry.update_status: UDM write failed for %s — %s", device_id, _udm_err
                )

        now = time.time()
        device.last_seen = now
        
        if heartbeat:
            device.last_heartbeat = now
        
        if status:
            old_status = device.status
            device.status = status
            
            # 触发状态变化事件
            if old_status != status:
                if status == DeviceStatus.ONLINE:
                    await self._emit_event("online", device)
                elif status == DeviceStatus.OFFLINE:
                    await self._emit_event("offline", device)
                    # Wire device-offline lifecycle event into multi-device runtime harness.
                    try:
                        from core.multi_device_runtime_harness import (
                            on_device_health_changed,
                            on_participant_readiness_changed,
                            DeviceHealthEvent,
                        )
                        on_device_health_changed(
                            DeviceHealthEvent(
                                device_id=device_id,
                                health_score=0.0,
                                is_reachable=False,
                                event_type="disconnect",
                            )
                        )
                        on_participant_readiness_changed(
                            device_id, "lost", reason="disconnect"
                        )
                    except Exception as _harn_exc:
                        logger.debug(
                            "DeviceRegistry.update_status: harness notification failed — %s",
                            _harn_exc,
                        )
        
        return True
    
    async def heartbeat(self, device_id: str) -> bool:
        """设备心跳"""
        return await self.update_status(device_id, heartbeat=True)
    
    async def check_offline_devices(self, timeout: float = 60.0):
        """Mark timed-out devices as OFFLINE in the local compatibility cache.

        Local-cache-only operation (PR-4)
        ----------------------------------
        This method updates the local cache status only.  Authoritative
        online/offline state is managed by ``UnifiedDeviceManager`` via its
        own heartbeat-timeout mechanism (``check_heartbeat_timeouts``).
        Callers should not rely solely on this method for canonical device
        liveness decisions.
        """
        now = time.time()
        
        for device in self.devices.values():
            if device.status == DeviceStatus.ONLINE:
                if now - device.last_heartbeat > timeout:
                    device.status = DeviceStatus.OFFLINE
                    await self._emit_event("offline", device)
                    logger.warning("DeviceRegistry: local cache marks device offline: %s", device.device_id)
                    # Wire heartbeat-miss lifecycle event into multi-device runtime harness.
                    try:
                        from core.multi_device_runtime_harness import (
                            on_device_health_changed,
                            on_participant_readiness_changed,
                            DeviceHealthEvent,
                        )
                        on_device_health_changed(
                            DeviceHealthEvent(
                                device_id=device.device_id,
                                health_score=0.0,
                                is_reachable=False,
                                event_type="heartbeat_miss",
                            )
                        )
                        on_participant_readiness_changed(
                            device.device_id, "lost", reason="heartbeat_miss"
                        )
                    except Exception as _harn_exc:
                        logger.debug(
                            "DeviceRegistry.check_offline_devices: harness notification failed — %s",
                            _harn_exc,
                        )
                    # PR-B: Suspend active mesh sessions for the lost device so the
                    # MeshSessionLifecycleCoordinator reflects the heartbeat-miss.
                    try:
                        from core.mesh.mesh_session_lifecycle import (
                            get_lifecycle_coordinator,
                            suspend_durable_session,
                        )
                        _coord = get_lifecycle_coordinator()
                        _session_ids = _coord.find_sessions_for_device(device.device_id)
                        for _sid in _session_ids:
                            suspend_durable_session(
                                _sid,
                                reason=f"heartbeat_miss:{device.device_id}",
                            )
                            logger.info(
                                "DeviceRegistry: mesh session suspended for offline device: "
                                "device_id=%s session_id=%s",
                                device.device_id, _sid,
                            )
                    except Exception as _mesh_exc:
                        logger.debug(
                            "DeviceRegistry.check_offline_devices: mesh session suspend non-fatal — %s",
                            _mesh_exc,
                        )
                    # V2 lifecycle mainline: detach attached session in
                    # AttachedSessionRegistry so the registry reflects heartbeat-miss.
                    try:
                        from core.attached_runtime_session_registry import (
                            lookup_session_by_device,
                            detach_session,
                            InvalidationReason,
                        )
                        _entry = lookup_session_by_device(device.device_id)
                        if _entry is not None:
                            detach_session(
                                _entry,
                                reason=InvalidationReason.disconnected,
                                metadata={"detach_source": "heartbeat_miss"},
                            )
                            logger.info(
                                "DeviceRegistry: attached session detached on heartbeat-miss: "
                                "device_id=%s runtime_session_id=%s",
                                device.device_id, _entry.runtime_session_id,
                            )
                    except Exception as _asr_exc:
                        logger.debug(
                            "DeviceRegistry.check_offline_devices: attached session detach non-fatal — %s",
                            _asr_exc,
                        )
    
    # ========================================================================
    # 能力协商
    # ========================================================================
    
    def negotiate_capability(
        self,
        capability: str,
        device_id: str = None,
        prefer_online: bool = True,
    ) -> Optional[Device]:
        """
        协商设备能力
        
        找到具有指定能力的最佳设备
        
        Args:
            capability: 能力名称
            device_id: 指定设备 ID (可选)
            prefer_online: 优先在线设备
        
        Returns:
            设备对象
        """
        # 如果指定了设备
        if device_id:
            device = self.devices.get(device_id)
            if device and device.is_capability_available(capability):
                return device
            return None
        
        # 从能力索引查找
        device_ids = self.capability_index.get(capability, [])
        
        candidates = []
        for did in device_ids:
            device = self.devices.get(did)
            if device and device.is_capability_available(capability):
                candidates.append(device)
        
        if not candidates:
            return None
        
        # 优先在线设备
        if prefer_online:
            online = [d for d in candidates if d.is_online()]
            if online:
                candidates = online
        
        # 选择成功率最高的设备
        candidates.sort(
            key=lambda d: d.successful_commands / max(d.total_commands, 1),
            reverse=True,
        )
        
        return candidates[0]
    
    def get_available_capabilities(self) -> List[str]:
        """获取所有可用能力"""
        return list(self.capability_index.keys())
    
    # ========================================================================
    # 分组和标签
    # ========================================================================
    
    def add_to_group(self, device_id: str, group: str) -> bool:
        """添加设备到分组"""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        if group not in device.groups:
            device.groups.append(group)
        
        if group not in self.groups:
            self.groups[group] = []
        
        if device_id not in self.groups[group]:
            self.groups[group].append(device_id)
        
        self._save()
        return True
    
    def remove_from_group(self, device_id: str, group: str) -> bool:
        """从分组移除设备"""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        if group in device.groups:
            device.groups.remove(group)
        
        if group in self.groups and device_id in self.groups[group]:
            self.groups[group].remove(device_id)
        
        self._save()
        return True
    
    def add_tag(self, device_id: str, tag: str) -> bool:
        """添加标签"""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        if tag not in device.tags:
            device.tags.append(tag)
        
        if tag not in self.tag_index:
            self.tag_index[tag] = []
        
        if device_id not in self.tag_index[tag]:
            self.tag_index[tag].append(device_id)
        
        self._save()
        return True
    
    def remove_tag(self, device_id: str, tag: str) -> bool:
        """移除标签"""
        device = self.devices.get(device_id)
        if not device:
            return False
        
        if tag in device.tags:
            device.tags.remove(tag)
        
        if tag in self.tag_index and device_id in self.tag_index[tag]:
            self.tag_index[tag].remove(device_id)
        
        self._save()
        return True
    
    def get_devices_by_group(self, group: str) -> List[Device]:
        """获取分组中的设备"""
        device_ids = self.groups.get(group, [])
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    def get_devices_by_tag(self, tag: str) -> List[Device]:
        """获取标签下的设备"""
        device_ids = self.tag_index.get(tag, [])
        return [self.devices[did] for did in device_ids if did in self.devices]
    
    # ========================================================================
    # 统计
    # ========================================================================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        online = sum(1 for d in self.devices.values() if d.is_online())
        offline = len(self.devices) - online
        
        by_type = {}
        for device in self.devices.values():
            t = device.device_type.value
            by_type[t] = by_type.get(t, 0) + 1
        
        return {
            "total": len(self.devices),
            "online": online,
            "offline": offline,
            "by_type": by_type,
            "groups": len(self.groups),
            "tags": len(self.tag_index),
            "capabilities": len(self.capability_index),
        }

    # ========================================================================
    # Projection bridge (PR-4)
    # ========================================================================

    def project_to_contract(self, device_id: str):
        """Project a registry-local record into the canonical ``RegisteredRuntimeDevice`` contract.

        Projection bridge (PR-4)
        -------------------------
        This method normalises a ``DeviceModel`` record held in the local
        compatibility index into the canonical single-device read contract
        (``RegisteredRuntimeDevice``), using the ``from_device_registry_record``
        adapter from ``contracts.registered_runtime_device``.

        This allows downstream consumers that require the canonical read
        contract to source it from registry-discovered or registry-indexed
        devices without having to depend on the registry's internal model.

        Args:
            device_id: The ID of the device to project.

        Returns:
            A :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
            instance, or ``None`` if the device is not present in the local
            index.
        """
        local = self.get(device_id)
        if local is None:
            return None
        try:
            from contracts.registered_runtime_device import from_device_registry_record
            return from_device_registry_record(local)
        except Exception as _err:
            logger.warning(
                "DeviceRegistry.project_to_contract: projection failed for %s — %s",
                device_id, _err,
            )
            return None
    
    def _update_indexes(self, device: Device):
        """更新索引"""
        # 更新能力索引
        for cap in device.capabilities:
            if cap.name not in self.capability_index:
                self.capability_index[cap.name] = []
            if device.device_id not in self.capability_index[cap.name]:
                self.capability_index[cap.name].append(device.device_id)
        
        # 更新分组索引
        for group in device.groups:
            if group not in self.groups:
                self.groups[group] = []
            if device.device_id not in self.groups[group]:
                self.groups[group].append(device.device_id)
        
        # 更新标签索引
        for tag in device.tags:
            if tag not in self.tag_index:
                self.tag_index[tag] = []
            if device.device_id not in self.tag_index[tag]:
                self.tag_index[tag].append(device.device_id)
    
    def _merge_groups_and_tags(
        self,
        device: Device,
        new_groups: Optional[List[str]],
        new_tags: Optional[List[str]],
    ) -> None:
        """Merge *new_groups* and *new_tags* into an existing device record.

        Used by the duplicate-registration path in ``register()`` to apply
        incremental group / tag additions without replacing the existing record.
        """
        for g in (new_groups or []):
            if g not in device.groups:
                device.groups.append(g)
        for t in (new_tags or []):
            if t not in device.tags:
                device.tags.append(t)

    def _remove_from_indexes(self, device: Device):
        """从索引移除"""
        # 从能力索引移除
        for cap in device.capabilities:
            if cap.name in self.capability_index:
                if device.device_id in self.capability_index[cap.name]:
                    self.capability_index[cap.name].remove(device.device_id)
        
        # 从分组索引移除
        for group in device.groups:
            if group in self.groups:
                if device.device_id in self.groups[group]:
                    self.groups[group].remove(device.device_id)
        
        # 从标签索引移除
        for tag in device.tags:
            if tag in self.tag_index:
                if device.device_id in self.tag_index[tag]:
                    self.tag_index[tag].remove(device.device_id)
    
    def _save(self):
        """Persist the current registry state as a snapshot / projection cache.

        Snapshot semantics (PR-4)
        -------------------------
        The file written here is a **cache / snapshot** of the last known local
        state.  It is NOT a canonical source of device truth; authoritative
        state lives in UDM.  The snapshot is used solely to restore the local
        compatibility index (groups, tags, capability index) after a restart.
        """
        try:
            data = {
                "devices": {did: d.to_api_dict() for did, d in self.devices.items()},
                "groups": self.groups,
                "tag_index": self.tag_index,
                "capability_index": self.capability_index,
                "saved_at": time.time(),
            }
            
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("DeviceRegistry._save: failed — %s", e)
    
    def _load(self):
        """Restore the compatibility index from the on-disk snapshot.

        Snapshot / cache semantics (PR-4)
        ----------------------------------
        This method restores the local **compatibility index only** — it does
        NOT recreate authoritative online device state.  Every device loaded
        from disk is forced to ``OFFLINE`` status; a device may only transition
        to ONLINE by re-registering through the normal UDM write path
        (``register()`` → ``UnifiedDeviceManager.register_device``).

        This ensures that a stale snapshot cannot silently make the system
        believe that devices are online when they have not re-connected after
        a restart.
        """
        try:
            if not self.storage_path.exists():
                return
            
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
            
            # 加载设备（Pydantic V2 模型，自动验证和类型转换）
            for did, ddata in data.get("devices", {}).items():
                try:
                    # 兼容旧格式：model → model_name
                    if "model" in ddata and "model_name" not in ddata:
                        ddata["model_name"] = ddata.pop("model")
                    # Force OFFLINE — snapshot does not restore authoritative online state.
                    ddata["status"] = DeviceStatus.OFFLINE
                    if "device_id" not in ddata:
                        ddata["device_id"] = did
                    device = Device.model_validate(ddata)
                    self.devices[did] = device
                except Exception as load_err:
                    logger.warning("DeviceRegistry._load: skipping invalid device %s — %s", did, load_err)
            
            # 加载索引
            self.groups = data.get("groups", {})
            self.tag_index = data.get("tag_index", {})
            self.capability_index = data.get("capability_index", {})
            
        except Exception as e:
            logger.error("DeviceRegistry._load: failed — %s", e)
    
    async def _emit_event(self, event_type: str, device: Device):
        """触发事件"""
        if event_type == "registered":
            for callback in self._on_device_registered:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device)
                    else:
                        callback(device)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
        
        elif event_type == "online":
            for callback in self._on_device_online:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device)
                    else:
                        callback(device)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
        
        elif event_type == "offline":
            for callback in self._on_device_offline:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(device)
                    else:
                        callback(device)
                except Exception as e:
                    logger.error(f"事件回调失败: {e}")
    
    def on_device_registered(self, callback: Callable):
        """注册设备注册事件回调"""
        self._on_device_registered.append(callback)
    
    def on_device_online(self, callback: Callable):
        """注册设备上线事件回调"""
        self._on_device_online.append(callback)
    
    def on_device_offline(self, callback: Callable):
        """注册设备离线事件回调"""
        self._on_device_offline.append(callback)


# ============================================================================
# 全局实例
# ============================================================================

device_registry = DeviceRegistry.get_instance()
