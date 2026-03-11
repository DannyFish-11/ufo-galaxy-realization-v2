"""
UFO Galaxy - 统一设备数据模型（Single Source of Truth）
=====================================================

所有模块必须使用此文件中的 Pydantic V2 模型表示设备数据。
禁止在其他模块中自行定义 Device 数据类。

层次关系:
  DeviceCapabilityModel — 单项设备能力
  DeviceModel           — 完整设备信息（注册、状态、能力、网络、统计）
  DeviceRegisterSchema  — API 层注册请求（精简字段）
  DeviceStatusSchema    — API 层状态查询响应
  DeviceCommandSchema   — API 层命令下发请求
  DeviceCommandResultSchema — 命令执行结果

枚举来源:
  DeviceType / DeviceStatus 从 core.device_types 导入（唯一定义处）
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from core.device_types import DeviceType, DeviceStatus, resolve_device_type


# ============================================================================
# 核心数据模型 — 系统内部使用
# ============================================================================


class DeviceCapabilityModel(BaseModel):
    """设备能力 — 描述设备支持的单项能力。

    合并自:
      - core/device_registry.py:DeviceCapability (dataclass)
      - 本文件旧版 DeviceCapabilitySchema
    """

    name: str = Field(..., min_length=1, description="能力名称，如 screen / camera / microphone")
    description: str = Field(default="", description="能力描述")
    available: bool = Field(default=True, description="当前是否可用")
    version: str = Field(default="1.0", description="能力版本")
    params: Dict[str, Any] = Field(default_factory=dict, description="能力参数")

    model_config = {"from_attributes": True}


class DeviceModel(BaseModel):
    """统一设备模型 — 全系统唯一的 Device 数据表示。

    合并自:
      - core/device_registry.py:Device (dataclass, 21 字段)
      - galaxy_gateway/device_router.py:Device (普通类, 6 字段)
      - nodes/Node_71_MultiDeviceCoordination/main.py:Device (dataclass, 9 字段)

    所有模块必须使用此模型，不得自行定义 Device 数据类。
    """

    # ── 基本标识 ──
    device_id: str = Field(
        default_factory=lambda: f"dev_{uuid.uuid4().hex[:8]}",
        min_length=1,
        max_length=256,
        description="设备唯一标识符",
    )
    device_type: DeviceType = Field(
        default=DeviceType.CUSTOM,
        description="设备类型大类",
    )
    name: str = Field(default="", description="设备友好名称")
    status: DeviceStatus = Field(
        default=DeviceStatus.OFFLINE,
        description="设备状态",
    )

    # ── 硬件信息 ──
    manufacturer: str = Field(default="", description="制造商")
    model_name: str = Field(default="", description="型号")
    os_version: str = Field(default="", description="操作系统版本")
    app_version: str = Field(default="", description="Galaxy 客户端版本")

    # ── 能力 ──
    capabilities: List[DeviceCapabilityModel] = Field(
        default_factory=list,
        description="设备支持的能力列表",
    )

    # ── 分组与标签 ──
    groups: List[str] = Field(default_factory=list, description="设备所属分组")
    tags: List[str] = Field(default_factory=list, description="设备标签")

    # ── 网络 ──
    ip_address: str = Field(default="", description="IP 地址")
    port: int = Field(default=0, ge=0, le=65535, description="端口")
    mac_address: str = Field(default="", description="MAC 地址")
    endpoint: str = Field(default="", description="设备服务端点 URL")

    # ── 位置（来自 Node_71 Device） ──
    location: str = Field(default="", description="设备物理位置")

    # ── 元数据 ──
    metadata: Dict[str, Any] = Field(default_factory=dict, description="扩展元数据")

    # ── 时间戳 ──
    registered_at: float = Field(default_factory=time.time, description="注册时间戳")
    last_seen: float = Field(default_factory=time.time, description="最后活跃时间戳")
    last_heartbeat: float = Field(default_factory=time.time, description="最后心跳时间戳")

    # ── 统计 ──
    total_commands: int = Field(default=0, ge=0, description="总命令数")
    successful_commands: int = Field(default=0, ge=0, description="成功命令数")
    failed_commands: int = Field(default=0, ge=0, description="失败命令数")

    # ── 当前任务（来自 Node_71 Device） ──
    current_task: Optional[str] = Field(default=None, description="当前正在执行的任务 ID")

    model_config = {"from_attributes": True}

    # ── 验证器 ──

    @field_validator("device_type", mode="before")
    @classmethod
    def _coerce_device_type(cls, v: Any) -> DeviceType:
        if isinstance(v, DeviceType):
            return v
        if isinstance(v, str):
            return resolve_device_type(v)
        return DeviceType.CUSTOM

    @field_validator("status", mode="before")
    @classmethod
    def _coerce_status(cls, v: Any) -> DeviceStatus:
        if isinstance(v, DeviceStatus):
            return v
        if isinstance(v, str):
            try:
                return DeviceStatus(v.lower())
            except ValueError:
                return DeviceStatus.UNKNOWN
        return DeviceStatus.UNKNOWN

    # ── 便捷方法 ──

    def is_online(self) -> bool:
        return self.status == DeviceStatus.ONLINE

    def is_capability_available(self, capability: str) -> bool:
        for cap in self.capabilities:
            if cap.name == capability:
                return cap.available
        return False

    def get_capability(self, capability: str) -> Optional[DeviceCapabilityModel]:
        for cap in self.capabilities:
            if cap.name == capability:
                return cap
        return None

    def capability_names(self) -> List[str]:
        return [cap.name for cap in self.capabilities]

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="python")

    def to_api_dict(self) -> Dict[str, Any]:
        """返回 API 兼容的 dict（枚举序列化为字符串值）。"""
        return self.model_dump(mode="json")


# ============================================================================
# API 层请求/响应模型（精简字段，面向外部）
# ============================================================================


class DeviceRegisterSchema(BaseModel):
    """设备注册请求 — API 层使用。"""

    device_id: str = Field(..., min_length=1, max_length=256, description="设备唯一标识符")
    device_type: str = Field(..., description="设备类型，如 android / ios / windows / drone 等")
    device_name: str = Field(default="", description="设备友好名称")
    capabilities: List[str] = Field(
        default_factory=list,
        description="设备支持的能力列表，如 ['screen', 'camera', 'microphone']",
    )
    os_version: str = Field(default="", description="操作系统版本")
    app_version: str = Field(default="", description="Galaxy 客户端应用版本")

    model_config = {"from_attributes": True}


class DeviceStatusSchema(BaseModel):
    """设备状态查询响应 — API 层使用。"""

    device_id: str = Field(..., max_length=256, description="设备唯一标识符")
    status: str = Field(default="unknown", description="设备状态")
    online: bool = Field(default=False, description="设备是否在线")
    last_seen: Optional[datetime] = Field(default=None, description="设备最后活跃时间")
    telemetry: Dict[str, Any] = Field(default_factory=dict, description="设备遥测数据摘要")

    model_config = {"from_attributes": True}


class DeviceCapabilitySchema(BaseModel):
    """设备能力查询响应 — API 层使用（向后兼容旧接口）。"""

    capability_name: str = Field(..., description="能力名称")
    supported: bool = Field(default=True, description="当前设备是否支持该能力")
    version: str = Field(default="1.0", description="能力版本")

    model_config = {"from_attributes": True}


class DeviceCommandSchema(BaseModel):
    """设备命令请求 — API 层使用。"""

    device_id: str = Field(..., max_length=256, description="目标设备 ID")
    command: str = Field(..., description="命令名称")
    params: Dict[str, Any] = Field(default_factory=dict, description="命令参数")
    timeout: int = Field(default=30, ge=1, le=600, description="命令超时秒数")

    model_config = {"from_attributes": True}


class DeviceCommandResultSchema(BaseModel):
    """设备命令执行结果 — API 层使用。"""

    device_id: str = Field(..., max_length=256, description="设备 ID")
    command_id: str = Field(default="", description="命令唯一标识符")
    status: str = Field(default="unknown", description="执行状态")
    result: Any = Field(default=None, description="命令执行结果或错误信息")
    execution_time_ms: float = Field(default=0.0, ge=0, description="命令执行耗时（毫秒）")

    model_config = {"from_attributes": True}
