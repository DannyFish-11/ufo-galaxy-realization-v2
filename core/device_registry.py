"""
UFO Galaxy - 统一设备注册管理器
================================

提供完整的设备注册、发现、管理功能

功能：
1. 设备注册和注销
2. 设备发现 (自动发现局域网设备)
3. 设备能力协商
4. 设备分组和标签
5. 持久化存储
6. 设备状态监控

使用方法：
    from core.device_registry import device_registry
    
    # 注册设备
    device = await device_registry.register(
        device_id="android_001",
        device_type="android",
        name="我的手机",
        capabilities=["screen", "camera", "microphone"],
    )
    
    # 发现设备
    devices = await device_registry.discover()
    
    # 获取设备
    device = device_registry.get("android_001")
    
    # 列出设备
    devices = device_registry.list_devices()
"""

import asyncio
import json
import logging
import os
import socket
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("UFO-Galaxy.DeviceRegistry")


# ============================================================================
# 数据模型
# ============================================================================

class DeviceType(str, Enum):
    """设备类型"""
    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    IOT = "iot"
    BROWSER = "browser"
    CUSTOM = "custom"


class DeviceStatus(str, Enum):
    """设备状态"""
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class DeviceCapability:
    """设备能力"""
    name: str
    description: str = ""
    available: bool = True
    params: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "description": self.description,
            "available": self.available,
            "params": self.params,
        }


@dataclass
class Device:
    """设备定义"""
    device_id: str
    device_type: DeviceType
    name: str
    status: DeviceStatus = DeviceStatus.OFFLINE
    
    # 基本信息
    manufacturer: str = ""
    model: str = ""
    os_version: str = ""
    app_version: str = ""
    
    # 能力
    capabilities: List[DeviceCapability] = field(default_factory=list)
    
    # 分组和标签
    groups: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    # 网络
    ip_address: str = ""
    port: int = 0
    mac_address: str = ""
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 时间戳
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    
    # 统计
    total_commands: int = 0
    successful_commands: int = 0
    failed_commands: int = 0
    
    def is_online(self) -> bool:
        """检查设备是否在线"""
        return self.status == DeviceStatus.ONLINE
    
    def is_capability_available(self, capability: str) -> bool:
        """检查能力是否可用"""
        for cap in self.capabilities:
            if cap.name == capability:
                return cap.available
        return False
    
    def get_capability(self, capability: str) -> Optional[DeviceCapability]:
        """获取能力"""
        for cap in self.capabilities:
            if cap.name == capability:
                return cap
        return None
    
    def to_dict(self) -> Dict:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type.value,
            "name": self.name,
            "status": self.status.value,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "os_version": self.os_version,
            "app_version": self.app_version,
            "capabilities": [cap.to_dict() for cap in self.capabilities],
            "groups": self.groups,
            "tags": self.tags,
            "ip_address": self.ip_address,
            "port": self.port,
            "mac_address": self.mac_address,
            "metadata": self.metadata,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "last_heartbeat": self.last_heartbeat,
            "total_commands": self.total_commands,
            "successful_commands": self.successful_commands,
            "failed_commands": self.failed_commands,
        }


# ============================================================================
# 设备注册管理器
# ============================================================================

class DeviceRegistry:
    """
    统一设备注册管理器
    
    提供完整的设备注册、发现、管理功能
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
        """
        注册设备
        
        Args:
            device_id: 设备 ID (可选，自动生成)
            device_type: 设备类型
            name: 设备名称
            capabilities: 能力列表
            capability_details: 能力详情
            groups: 分组列表
            tags: 标签列表
            ip_address: IP 地址
            port: 端口
            mac_address: MAC 地址
            manufacturer: 制造商
            model: 型号
            os_version: 系统版本
            app_version: 应用版本
            metadata: 元数据
        
        Returns:
            设备对象
        """
        # 生成设备 ID
        if not device_id:
            device_id = f"{device_type}_{uuid.uuid4().hex[:8]}"
        
        # 解析设备类型
        try:
            dev_type = DeviceType(device_type.lower())
        except ValueError:
            dev_type = DeviceType.CUSTOM
        
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
        
        # 创建设备对象
        device = Device(
            device_id=device_id,
            device_type=dev_type,
            name=name or f"{device_type}_{device_id[:8]}",
            status=DeviceStatus.ONLINE,
            manufacturer=manufacturer,
            model=model,
            os_version=os_version,
            app_version=app_version,
            capabilities=cap_list,
            groups=groups or [],
            tags=tags or [],
            ip_address=ip_address,
            port=port,
            mac_address=mac_address,
            metadata=metadata or {},
            registered_at=time.time(),
            last_seen=time.time(),
            last_heartbeat=time.time(),
        )
        
        # 添加额外字段
        for key, value in kwargs.items():
            device.metadata[key] = value
        
        # 存储
        self.devices[device_id] = device
        
        # 更新索引
        self._update_indexes(device)
        
        # 保存
        self._save()
        
        # 触发事件
        await self._emit_event("registered", device)
        
        logger.info(f"设备注册成功: {device_id} ({device_type})")
        
        return device
    
    async def unregister(self, device_id: str) -> bool:
        """注销设备"""
        if device_id not in self.devices:
            return False
        
        device = self.devices.pop(device_id)
        
        # 更新索引
        self._remove_from_indexes(device)
        
        # 保存
        self._save()
        
        logger.info(f"设备注销: {device_id}")
        
        return True
    
    def get(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def get_or_create(self, device_id: str, **kwargs) -> Device:
        """获取或创建设备"""
        device = self.devices.get(device_id)
        if device:
            device.last_seen = time.time()
            device.status = DeviceStatus.ONLINE
            return device
        
        # 创建新设备
        return asyncio.run(self.register(device_id=device_id, **kwargs))
    
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
        """列出设备"""
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
        
        return True
    
    async def heartbeat(self, device_id: str) -> bool:
        """设备心跳"""
        return await self.update_status(device_id, heartbeat=True)
    
    async def check_offline_devices(self, timeout: float = 60.0):
        """检查离线设备"""
        now = time.time()
        
        for device in self.devices.values():
            if device.status == DeviceStatus.ONLINE:
                if now - device.last_heartbeat > timeout:
                    device.status = DeviceStatus.OFFLINE
                    await self._emit_event("offline", device)
                    logger.warning(f"设备离线: {device.device_id}")
    
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
    # 内部方法
    # ========================================================================
    
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
        """保存到文件"""
        try:
            data = {
                "devices": {did: d.to_dict() for did, d in self.devices.items()},
                "groups": self.groups,
                "tag_index": self.tag_index,
                "capability_index": self.capability_index,
                "saved_at": time.time(),
            }
            
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存设备数据失败: {e}")
    
    def _load(self):
        """从文件加载"""
        try:
            if not self.storage_path.exists():
                return
            
            with open(self.storage_path, encoding="utf-8") as f:
                data = json.load(f)
            
            # 加载设备
            for did, ddata in data.get("devices", {}).items():
                try:
                    device_type = DeviceType(ddata.get("device_type", "custom"))
                except ValueError:
                    device_type = DeviceType.CUSTOM
                
                capabilities = [
                    DeviceCapability(
                        name=cap.get("name", ""),
                        description=cap.get("description", ""),
                        available=cap.get("available", True),
                        params=cap.get("params", {}),
                    )
                    for cap in ddata.get("capabilities", [])
                ]
                
                device = Device(
                    device_id=ddata.get("device_id", did),
                    device_type=device_type,
                    name=ddata.get("name", ""),
                    status=DeviceStatus.OFFLINE,  # 加载时默认离线
                    manufacturer=ddata.get("manufacturer", ""),
                    model=ddata.get("model", ""),
                    os_version=ddata.get("os_version", ""),
                    app_version=ddata.get("app_version", ""),
                    capabilities=capabilities,
                    groups=ddata.get("groups", []),
                    tags=ddata.get("tags", []),
                    ip_address=ddata.get("ip_address", ""),
                    port=ddata.get("port", 0),
                    mac_address=ddata.get("mac_address", ""),
                    metadata=ddata.get("metadata", {}),
                    registered_at=ddata.get("registered_at", time.time()),
                    last_seen=ddata.get("last_seen", time.time()),
                    last_heartbeat=ddata.get("last_heartbeat", time.time()),
                    total_commands=ddata.get("total_commands", 0),
                    successful_commands=ddata.get("successful_commands", 0),
                    failed_commands=ddata.get("failed_commands", 0),
                )
                
                self.devices[did] = device
            
            # 加载索引
            self.groups = data.get("groups", {})
            self.tag_index = data.get("tag_index", {})
            self.capability_index = data.get("capability_index", {})
            
        except Exception as e:
            logger.error(f"加载设备数据失败: {e}")
    
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
