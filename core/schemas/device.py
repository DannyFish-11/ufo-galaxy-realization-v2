#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - 设备操作 Pydantic 模型
====================================

定义设备注册、状态、能力、命令及命令结果等数据模型，
供 API 层和内部模块统一使用。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DeviceRegisterSchema(BaseModel):
    """设备注册请求模型。

    用于新设备加入 Galaxy-Nexus 星枢时提交的注册信息。
    """

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="设备唯一标识符",
    )
    device_type: str = Field(
        ...,
        description="设备类型，如 android / ios / windows / drone 等",
    )
    device_name: str = Field(
        default="",
        description="设备友好名称",
    )
    capabilities: List[str] = Field(
        default_factory=list,
        description="设备支持的能力列表，如 ['screen', 'camera', 'microphone']",
    )
    os_version: str = Field(
        default="",
        description="操作系统版本",
    )
    app_version: str = Field(
        default="",
        description="Galaxy 客户端应用版本",
    )

    model_config = {"from_attributes": True}


class DeviceStatusSchema(BaseModel):
    """设备状态模型。

    包含设备的在线状态、最后活跃时间以及遥测摘要。
    """

    device_id: str = Field(
        ...,
        max_length=256,
        description="设备唯一标识符",
    )
    status: str = Field(
        default="unknown",
        description="设备状态：online / offline / busy / error / unknown",
    )
    online: bool = Field(
        default=False,
        description="设备是否在线",
    )
    last_seen: Optional[datetime] = Field(
        default=None,
        description="设备最后活跃时间",
    )
    telemetry: Dict[str, Any] = Field(
        default_factory=dict,
        description="设备遥测数据摘要",
    )

    model_config = {"from_attributes": True}


class DeviceCapabilitySchema(BaseModel):
    """设备能力模型。

    描述单项设备能力及其支持状态。
    """

    capability_name: str = Field(
        ...,
        description="能力名称",
    )
    supported: bool = Field(
        default=True,
        description="当前设备是否支持该能力",
    )
    version: str = Field(
        default="1.0",
        description="能力版本",
    )

    model_config = {"from_attributes": True}


class DeviceCommandSchema(BaseModel):
    """设备命令请求模型。

    用于向目标设备下发操作指令。
    """

    device_id: str = Field(
        ...,
        max_length=256,
        description="目标设备 ID",
    )
    command: str = Field(
        ...,
        description="命令名称，如 screenshot / file_read / clipboard_write",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="命令参数",
    )
    timeout: int = Field(
        default=30,
        ge=1,
        le=600,
        description="命令超时秒数",
    )

    model_config = {"from_attributes": True}


class DeviceCommandResultSchema(BaseModel):
    """设备命令执行结果模型。

    send_command / parallel_commands 的返回值结构。
    """

    device_id: str = Field(
        ...,
        max_length=256,
        description="设备 ID",
    )
    command_id: str = Field(
        default="",
        description="命令唯一标识符",
    )
    status: str = Field(
        default="unknown",
        description="执行状态：success / error / timeout",
    )
    result: Any = Field(
        default=None,
        description="命令执行结果或错误信息",
    )
    execution_time_ms: float = Field(
        default=0.0,
        ge=0,
        description="命令执行耗时（毫秒）",
    )

    model_config = {"from_attributes": True}
