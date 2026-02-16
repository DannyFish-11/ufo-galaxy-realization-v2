"""
Galaxy 一体化系统整合
=====================
整合 MCP 层、Skills 层、HAL 和节点系统

架构：
┌─────────────────────────────────────────────────────────────┐
│                    Galaxy 群智能核心                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│   │   感知层    │  │   认知层    │  │   执行层    │        │
│   └─────────────┘  └─────────────┘  └─────────────┘        │
│                          │                                  │
│   ┌──────────────────────┴──────────────────────┐          │
│   │                                             │          │
│   │   能力路由层 (Capability Router)            │          │
│   │                                             │          │
│   └─────────────────────────────────────────────┘          │
│         │              │              │                     │
│   ┌─────┴─────┐  ┌─────┴─────┐  ┌─────┴─────┐              │
│   │  MCP 层   │  │ Skills 层 │  │  节点层   │              │
│   └───────────┘  └───────────┘  └───────────┘              │
│         │              │              │                     │
│   ┌─────┴──────────────┴──────────────┴─────┐              │
│   │                                         │              │
│   │   硬件抽象层 (HAL)                      │              │
│   │   ├── 数字生命卡                        │              │
│   │   ├── 苯苯机械狗                        │              │
│   │   ├── 机械臂                            │              │
│   │   └── 其他设备                          │              │
│   │                                         │              │
│   └─────────────────────────────────────────┘              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("Galaxy.IntegratedSystem")

# ============================================================================
# 导入各层
# ============================================================================

# MCP 层
try:
    from core.mcp_layer import get_mcp_layer, MCPServerStatus
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP 层不可用")

# Skills 层
try:
    from core.skills_layer import get_skills_layer, SkillStatus
    SKILLS_AVAILABLE = True
except ImportError:
    SKILLS_AVAILABLE = False
    logger.warning("Skills 层不可用")

# HAL
try:
    from core.hal import get_hal, DeviceStatus
    HAL_AVAILABLE = True
except ImportError:
    HAL_AVAILABLE = False
    logger.warning("HAL 不可用")

# 群智能核心
try:
    from core.swarm_core import get_swarm_core, SwarmState
    SWARM_AVAILABLE = True
except ImportError:
    SWARM_AVAILABLE = False
    logger.warning("群智能核心不可用")

# ============================================================================
# 能力路由器
# ============================================================================

class CapabilityRouter:
    """
    能力路由器 - 统一调度 MCP、Skills 和节点
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # 初始化各层
        self.mcp = get_mcp_layer() if MCP_AVAILABLE else None
        self.skills = get_skills_layer() if SKILLS_AVAILABLE else None
        self.hal = get_hal() if HAL_AVAILABLE else None
        self.swarm = get_swarm_core() if SWARM_AVAILABLE else None
        
        # 能力来源映射
        self.capability_sources: Dict[str, str] = {}
        self._build_capability_index()
        
        self._initialized = True
        logger.info("能力路由器初始化完成")
    
    def _build_capability_index(self):
        """构建能力索引"""
        # MCP 工具
        if self.mcp:
            for tool in self.mcp.get_tools():
                self.capability_sources[tool.name] = f"mcp:{tool.server_id}"
        
        # Skills
        if self.skills:
            for skill in self.skills.get_skills():
                for action in skill.actions:
                    key = f"{skill.id}.{action.name}"
                    self.capability_sources[key] = f"skill:{skill.id}"
        
        # HAL 设备
        if self.hal:
            for device in self.hal.get_devices():
                for cap in device.info.capabilities:
                    key = f"device.{device.info.id}.{cap}"
                    self.capability_sources[key] = f"hal:{device.info.id}"
        
        logger.info(f"已索引 {len(self.capability_sources)} 个能力")
    
    async def execute(self, capability: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行能力"""
        params = params or {}
        
        # 查找能力来源
        source = self.capability_sources.get(capability)
        
        if not source:
            # 尝试智能匹配
            return await self._smart_execute(capability, params)
        
        source_type, source_id = source.split(":", 1)
        
        if source_type == "mcp":
            return await self._execute_mcp(capability, params)
        elif source_type == "skill":
            return await self._execute_skill(source_id, capability.split(".")[-1], params)
        elif source_type == "hal":
            return await self._execute_hal(source_id, capability, params)
        else:
            return {"success": False, "error": f"Unknown source type: {source_type}"}
    
    async def _smart_execute(self, capability: str, params: Dict) -> Dict[str, Any]:
        """智能执行 - 自动选择最佳能力"""
        # 尝试通过群智能核心
        if self.swarm:
            try:
                result = await self.swarm.interact(capability)
                return {"success": True, "result": result.get("output", ""), "source": "swarm"}
            except Exception as e:
                logger.error(f"群智能执行失败: {e}")
        
        # 返回失败
        return {"success": False, "error": f"Capability not found: {capability}"}
    
    async def _execute_mcp(self, tool_name: str, params: Dict) -> Dict[str, Any]:
        """执行 MCP 工具"""
        if not self.mcp:
            return {"success": False, "error": "MCP 层不可用"}
        
        return await self.mcp.call_tool(tool_name, params)
    
    async def _execute_skill(self, skill_id: str, action: str, params: Dict) -> Dict[str, Any]:
        """执行技能"""
        if not self.skills:
            return {"success": False, "error": "Skills 层不可用"}
        
        return await self.skills.execute(skill_id, action, params)
    
    async def _execute_hal(self, device_id: str, capability: str, params: Dict) -> Dict[str, Any]:
        """执行硬件操作"""
        if not self.hal:
            return {"success": False, "error": "HAL 不可用"}
        
        device = self.hal.get_device(device_id)
        if not device:
            return {"success": False, "error": f"Device not found: {device_id}"}
        
        # 确保设备已连接
        if device.info.status != DeviceStatus.CONNECTED:
            connected = await device.connect()
            if not connected:
                return {"success": False, "error": "Failed to connect device"}
        
        # 执行操作
        method_name = capability.split(".")[-1]
        if hasattr(device, method_name):
            method = getattr(device, method_name)
            if asyncio.iscoroutinefunction(method):
                result = await method(**params)
            else:
                result = method(**params)
            return {"success": True, "result": result, "source": "hal"}
        
        return {"success": False, "error": f"Method not found: {method_name}"}
    
    def get_capabilities(self) -> List[Dict]:
        """获取所有能力"""
        capabilities = []
        
        # MCP 工具
        if self.mcp:
            for tool in self.mcp.get_tools():
                capabilities.append({
                    "id": tool.name,
                    "name": tool.name,
                    "description": tool.description,
                    "source": "mcp",
                    "category": tool.category
                })
        
        # Skills
        if self.skills:
            for skill in self.skills.get_skills():
                for action in skill.actions:
                    capabilities.append({
                        "id": f"{skill.id}.{action.name}",
                        "name": f"{skill.name} - {action.name}",
                        "description": action.description,
                        "source": "skill",
                        "category": skill.category.value
                    })
        
        # HAL 设备
        if self.hal:
            for device in self.hal.get_devices():
                for cap in device.info.capabilities:
                    capabilities.append({
                        "id": f"device.{device.info.id}.{cap}",
                        "name": f"{device.info.name} - {cap}",
                        "description": f"{device.info.name} 的 {cap} 功能",
                        "source": "hal",
                        "category": "hardware"
                    })
        
        return capabilities
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "mcp": self.mcp.get_status() if self.mcp else {"available": False},
            "skills": self.skills.get_status() if self.skills else {"available": False},
            "hal": self.hal.get_status() if self.hal else {"available": False},
            "swarm": {"available": SWARM_AVAILABLE},
            "capabilities_count": len(self.capability_sources)
        }

# ============================================================================
# 全局实例
# ============================================================================

_router: Optional[CapabilityRouter] = None

def get_capability_router() -> CapabilityRouter:
    """获取能力路由器实例"""
    global _router
    if _router is None:
        _router = CapabilityRouter()
    return _router
