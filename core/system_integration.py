"""
Galaxy - 系统集成层
======================

统一协调 Agent、MCP、Skill 和设备系统

功能：
1. 统一的能力注册表
2. 智能任务分发
3. 跨系统协调
4. 能力发现和协商

使用方法：
    from core.system_integration import system
    
    # 注册能力
    system.register_capability("device_control", "android_001", handler)
    
    # 发现能力
    cap = await system.discover_capability("web_search")
    
    # 执行任务
    result = await system.execute("搜索 Python 教程")
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger("Galaxy.SystemIntegration")


# ============================================================================
# 能力类型
# ============================================================================

class CapabilityType(str, Enum):
    """能力类型"""
    DEVICE = "device"       # 设备能力
    MCP = "mcp"             # MCP 工具
    SKILL = "skill"         # 技能
    NODE = "node"           # 节点
    AGENT = "agent"         # Agent
    BUILTIN = "builtin"     # 内置


@dataclass
class Capability:
    """能力定义"""
    id: str
    name: str
    type: CapabilityType
    description: str = ""
    source: str = ""        # 来源 (device_id / mcp_server / skill_id / node_id)
    handler: Optional[Callable] = None
    parameters: Dict = field(default_factory=dict)
    priority: int = 5       # 优先级 1-10
    enabled: bool = True
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "description": self.description,
            "source": self.source,
            "parameters": self.parameters,
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


# ============================================================================
# 系统集成管理器
# ============================================================================

class SystemIntegration:
    """
    系统集成管理器
    
    统一协调所有子系统
    """
    
    _instance = None
    
    def __init__(self):
        # 能力注册表
        self.capabilities: Dict[str, Capability] = {}
        
        # 按类型索引
        self.by_type: Dict[CapabilityType, List[str]] = {
            CapabilityType.DEVICE: [],
            CapabilityType.MCP: [],
            CapabilityType.SKILL: [],
            CapabilityType.NODE: [],
            CapabilityType.AGENT: [],
            CapabilityType.BUILTIN: [],
        }
        
        # 按名称索引
        self.by_name: Dict[str, List[str]] = {}
        
        # 初始化标志
        self._initialized = False
        
        logger.info("系统集成管理器初始化")
    
    @classmethod
    def get_instance(cls) -> "SystemIntegration":
        # NOTE: This singleton is used for process-wide state sharing.
        # Avoid adding new call sites — prefer dependency injection where
        # possible to improve testability.  See ARCHITECTURE_REVIEW.md
        # (Singleton Guardrails section) for the planned refactor strategy.
        if cls._instance is None:
            cls._instance = SystemIntegration()
        return cls._instance
    
    # ========================================================================
    # 初始化
    # ========================================================================
    
    async def initialize(self):
        """初始化 - 加载所有子系统能力"""
        if self._initialized:
            return
        
        # 加载设备能力
        await self._load_device_capabilities()
        
        # 加载 MCP 能力
        await self._load_mcp_capabilities()
        
        # 加载技能能力
        await self._load_skill_capabilities()
        
        # 加载节点能力
        await self._load_node_capabilities()
        
        # 加载 Agent 能力
        await self._load_agent_capabilities()
        
        # 加载内置能力
        self._load_builtin_capabilities()
        
        self._initialized = True
        logger.info(f"系统集成初始化完成，已加载 {len(self.capabilities)} 个能力")
    
    async def _load_device_capabilities(self):
        """加载设备能力"""
        try:
            from core.device_registry import device_registry
            
            for device in device_registry.list_devices():
                for cap in device.capabilities:
                    if cap.available:
                        self.register_capability(
                            id=f"device_{device.device_id}_{cap.name}",
                            name=cap.name,
                            type=CapabilityType.DEVICE,
                            description=cap.description,
                            source=device.device_id,
                            parameters=cap.params,
                            metadata={"device_type": device.device_type.value},
                        )
        except Exception as e:
            logger.warning(f"加载设备能力失败: {e}")
    
    async def _load_mcp_capabilities(self):
        """加载 MCP 能力"""
        try:
            from core.mcp_loader import mcp_loader
            
            for server_id, server in mcp_loader.servers.items():
                for tool in server.tools:
                    self.register_capability(
                        id=f"mcp_{server_id}_{tool.name}",
                        name=tool.name,
                        type=CapabilityType.MCP,
                        description=tool.description,
                        source=server_id,
                        parameters=tool.inputSchema,
                    )
        except Exception as e:
            logger.warning(f"加载 MCP 能力失败: {e}")
    
    async def _load_skill_capabilities(self):
        """加载技能能力"""
        try:
            from core.skill_loader import skill_loader
            
            for skill_id, skill in skill_loader.skills.items():
                self.register_capability(
                    id=f"skill_{skill_id}",
                    name=skill.name,
                    type=CapabilityType.SKILL,
                    description=skill.description,
                    source=skill_id,
                    metadata={"version": skill.version},
                )
        except Exception as e:
            logger.warning(f"加载技能能力失败: {e}")
        
        # 也加载 SKILL.md 格式的技能
        try:
            from core.skill_md_loader import skill_md_loader
            
            for skill_id, skill in skill_md_loader.skills.items():
                self.register_capability(
                    id=f"skill_md_{skill_id}",
                    name=skill.name,
                    type=CapabilityType.SKILL,
                    description=skill.description,
                    source=skill_id,
                )
        except Exception as e:
            logger.warning(f"加载 SKILL.md 能力失败: {e}")
    
    async def _load_node_capabilities(self):
        """加载节点能力"""
        try:
            import os
            import json
            from pathlib import Path
            
            config_path = Path("config/node_registry.json")
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                
                for node_name, node_info in config.get("nodes", {}).items():
                    self.register_capability(
                        id=f"node_{node_info['id']}",
                        name=node_info["name"],
                        type=CapabilityType.NODE,
                        description=f"节点: {node_info['name']}",
                        source=node_name,
                        priority=3,
                    )
        except Exception as e:
            logger.warning(f"加载节点能力失败: {e}")
    
    async def _load_agent_capabilities(self):
        """加载 Agent 能力"""
        try:
            from core.agent_factory import get_agent_factory_instance
            
            agent_factory = get_agent_factory_instance()
            for agent_id, agent in agent_factory.agents.items():
                for cap in agent.config.capabilities:
                    self.register_capability(
                        id=f"agent_{agent_id}_{cap.name}",
                        name=cap.name,
                        type=CapabilityType.AGENT,
                        description=cap.description,
                        source=agent_id,
                        priority=7,
                    )
        except Exception as e:
            logger.warning(f"加载 Agent 能力失败: {e}")
    
    def _load_builtin_capabilities(self):
        """加载内置能力"""
        builtins = [
            Capability(
                id="builtin_chat",
                name="chat",
                type=CapabilityType.BUILTIN,
                description="与 AI 进行对话",
                priority=1,
            ),
            Capability(
                id="builtin_device_control",
                name="device_control",
                type=CapabilityType.BUILTIN,
                description="控制设备执行操作",
                priority=8,
            ),
        ]
        
        for cap in builtins:
            self.capabilities[cap.id] = cap
            self.by_type[cap.type].append(cap.id)
    
    # ========================================================================
    # 能力注册
    # ========================================================================
    
    def register_capability(
        self,
        id: str,
        name: str,
        type: CapabilityType,
        description: str = "",
        source: str = "",
        handler: Callable = None,
        parameters: Dict = None,
        priority: int = 5,
        metadata: Dict = None,
    ) -> Capability:
        """注册能力"""
        cap = Capability(
            id=id,
            name=name,
            type=type,
            description=description,
            source=source,
            handler=handler,
            parameters=parameters or {},
            priority=priority,
            metadata=metadata or {},
        )
        
        self.capabilities[id] = cap
        
        # 更新索引
        if id not in self.by_type[type]:
            self.by_type[type].append(id)
        
        if name not in self.by_name:
            self.by_name[name] = []
        if id not in self.by_name[name]:
            self.by_name[name].append(id)
        
        logger.debug(f"注册能力: {id} ({type.value})")
        return cap
    
    def unregister_capability(self, id: str) -> bool:
        """注销能力"""
        if id not in self.capabilities:
            return False
        
        cap = self.capabilities.pop(id)
        
        # 更新索引
        if id in self.by_type[cap.type]:
            self.by_type[cap.type].remove(id)
        
        if cap.name in self.by_name and id in self.by_name[cap.name]:
            self.by_name[cap.name].remove(id)
        
        return True
    
    # ========================================================================
    # 能力发现
    # ========================================================================
    
    async def discover_capability(
        self,
        name: str,
        type: CapabilityType = None,
        prefer_online: bool = True,
    ) -> Optional[Capability]:
        """
        发现能力
        
        找到具有指定名称的最佳能力
        """
        # 按名称查找
        cap_ids = self.by_name.get(name, [])
        
        if not cap_ids:
            return None
        
        candidates = [self.capabilities[cid] for cid in cap_ids if cid in self.capabilities]
        
        # 按类型过滤
        if type:
            candidates = [c for c in candidates if c.type == type]
        
        if not candidates:
            return None
        
        # 检查在线状态
        if prefer_online:
            online_candidates = []
            for cap in candidates:
                if await self._is_capability_available(cap):
                    online_candidates.append(cap)
            
            if online_candidates:
                candidates = online_candidates
        
        # 按优先级排序
        candidates.sort(key=lambda c: c.priority, reverse=True)
        
        return candidates[0]
    
    async def _is_capability_available(self, cap: Capability) -> bool:
        """检查能力是否可用"""
        if not cap.enabled:
            return False
        
        if cap.type == CapabilityType.DEVICE:
            try:
                from core.device_registry import device_registry
                device = device_registry.get(cap.source)
                return device and device.is_online()
            except (ImportError, AttributeError):
                return False

        elif cap.type == CapabilityType.MCP:
            try:
                from core.mcp_loader import mcp_loader
                server = mcp_loader.servers.get(cap.source)
                return server and server.status.value == "running"
            except (ImportError, AttributeError):
                return False
        
        elif cap.type == CapabilityType.SKILL:
            return True  # 技能总是可用
        
        elif cap.type == CapabilityType.NODE:
            return True  # 节点总是可用
        
        elif cap.type == CapabilityType.AGENT:
            return True  # Agent 总是可用
        
        elif cap.type == CapabilityType.BUILTIN:
            return True
        
        return False
    
    def list_capabilities(
        self,
        type: CapabilityType = None,
        name: str = None,
    ) -> List[Capability]:
        """列出能力"""
        if type:
            cap_ids = self.by_type.get(type, [])
            return [self.capabilities[cid] for cid in cap_ids if cid in self.capabilities]
        
        if name:
            cap_ids = self.by_name.get(name, [])
            return [self.capabilities[cid] for cid in cap_ids if cid in self.capabilities]
        
        return list(self.capabilities.values())
    
    # ========================================================================
    # 能力执行
    # ========================================================================
    
    async def execute(
        self,
        capability_name: str,
        **params,
    ) -> Any:
        """
        执行能力
        
        自动发现并执行最佳能力
        """
        cap = await self.discover_capability(capability_name)
        
        if not cap:
            raise ValueError(f"能力不存在: {capability_name}")
        
        return await self._execute_capability(cap, params)
    
    async def _execute_capability(
        self,
        cap: Capability,
        params: Dict,
    ) -> Any:
        """执行具体能力"""
        if cap.type == CapabilityType.DEVICE:
            return await self._execute_device(cap, params)
        
        elif cap.type == CapabilityType.MCP:
            return await self._execute_mcp(cap, params)
        
        elif cap.type == CapabilityType.SKILL:
            return await self._execute_skill(cap, params)
        
        elif cap.type == CapabilityType.NODE:
            return await self._execute_node(cap, params)
        
        elif cap.type == CapabilityType.AGENT:
            return await self._execute_agent(cap, params)
        
        elif cap.type == CapabilityType.BUILTIN:
            return await self._execute_builtin(cap, params)
        
        raise RuntimeError(f"未知能力类型: {cap.type}")
    
    async def _execute_device(self, cap: Capability, params: Dict) -> Any:
        """执行设备能力"""
        try:
            from core.device_communication import device_comm
            
            device_id = cap.source
            action = cap.name
            
            return await device_comm.send_command(device_id, action, params)
        except Exception as e:
            logger.error(f"执行设备能力失败: {e}")
            raise
    
    async def _execute_mcp(self, cap: Capability, params: Dict) -> Any:
        """执行 MCP 能力"""
        try:
            from core.mcp_loader import mcp_loader
            
            server_id = cap.source
            tool_name = cap.name
            
            return await mcp_loader.call_tool(server_id, tool_name, params)
        except Exception as e:
            logger.error(f"执行 MCP 能力失败: {e}")
            raise
    
    async def _execute_skill(self, cap: Capability, params: Dict) -> Any:
        """执行技能能力"""
        try:
            from core.skill_loader import skill_loader
            from core.skill_md_loader import skill_md_loader
            
            skill_id = cap.source
            
            # 尝试 skill_loader
            try:
                return await skill_loader.execute(skill_id, **params)
            except Exception as e:
                logger.debug(f"skill_loader 执行 {skill_id} 失败: {e}")

            # 尝试 skill_md_loader
            try:
                return await skill_md_loader.execute(skill_id, params)
            except Exception as e:
                logger.debug(f"skill_md_loader 执行 {skill_id} 失败: {e}")
            
            raise ValueError(f"技能不存在: {skill_id}")
        except Exception as e:
            logger.error(f"执行技能能力失败: {e}")
            raise
    
    async def _execute_node(self, cap: Capability, params: Dict) -> Any:
        """执行节点能力"""
        try:
            import httpx
            
            node_name = cap.source
            # 从节点 ID 提取端口号
            node_id = node_name.replace("Node_", "").split("_")[0]
            port = 8000 + int(node_id)
            
            url = f"http://localhost:{port}/execute"
            
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=params)
                return response.json()
        except Exception as e:
            logger.error(f"执行节点能力失败: {e}")
            raise
    
    async def _execute_agent(self, cap: Capability, params: Dict) -> Any:
        """执行 Agent 能力"""
        try:
            from core.agent_factory import get_agent_factory_instance
            
            agent_id = cap.source
            # Agent 执行逻辑
            # ...
            return {"success": True, "agent_id": agent_id}
        except Exception as e:
            logger.error(f"执行 Agent 能力失败: {e}")
            raise
    
    async def _execute_builtin(self, cap: Capability, params: Dict) -> Any:
        """执行内置能力"""
        if cap.id == "builtin_chat":
            # 对话
            from core.multi_llm_router import get_llm_router
            router = get_llm_router()
            return await router.chat([{"role": "user", "content": params.get("message", "")}])
        
        elif cap.id == "builtin_device_control":
            # 设备控制
            from core.device_control_service import device_control
            device_id = params.get("device_id")
            action = params.get("action")
            return await device_control.execute_action(device_id, action)
        
        return None
    
    # ========================================================================
    # 统计
    # ========================================================================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_capabilities": len(self.capabilities),
            "by_type": {
                t.value: len(ids) for t, ids in self.by_type.items()
            },
            "unique_names": len(self.by_name),
        }


# ============================================================================
# 全局实例
# ============================================================================

system = SystemIntegration.get_instance()
