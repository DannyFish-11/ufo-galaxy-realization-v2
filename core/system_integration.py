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

import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Protocol

logger = logging.getLogger("Galaxy.SystemIntegration")


class CapabilityContractLike(Protocol):
    name: str
    description: str
    source: Any
    source_id: str
    parameters: Dict[str, Any]
    available: bool
    metadata: Dict[str, Any]


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
        # 运行时执行器注册。能力真相统一来自 CapabilityRegistry/Resolver；
        # 这里只保存执行处理器，不再维护第二套能力目录。
        self._runtime_capabilities: Dict[str, Capability] = {}
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
        """初始化统一能力外观层。"""
        if self._initialized:
            return

        self._load_builtin_capabilities()
        self._initialized = True
        logger.info("系统集成初始化完成（统一能力外观层）")
    
    async def _load_device_capabilities(self):
        return
    
    async def _load_mcp_capabilities(self):
        return
    
    async def _load_skill_capabilities(self):
        return
    
    async def _load_node_capabilities(self):
        return
    
    async def _load_agent_capabilities(self):
        return
    
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
            self.register_capability(
                id=cap.id,
                name=cap.name,
                type=cap.type,
                description=cap.description,
                priority=cap.priority,
            )
    
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
        """注册能力到统一能力注册表，并保存运行时执行器。"""
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry
        from core.unified.capability_resolver import get_capability_resolver

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
        source_map = {
            CapabilityType.DEVICE: "device",
            CapabilityType.MCP: "mcp",
            CapabilityType.SKILL: "skill",
            CapabilityType.NODE: "node",
            CapabilityType.AGENT: "node",
            CapabilityType.BUILTIN: "unknown",
        }
        CapabilityRegistry.get_instance().register(
            CapabilityItem(
                name=name,
                description=description or f"Capability: {name}",
                source=source_map.get(type, "unknown"),
                source_id=source or id or name,
                parameters=parameters or {},
                available=True,
                metadata={
                    "system_integration_id": id,
                    "system_integration_type": type.value,
                    "priority": priority,
                    **(metadata or {}),
                },
            )
        )
        get_capability_resolver().invalidate_cache()
        self._runtime_capabilities[name] = cap
        logger.debug(f"注册能力: {id} ({type.value})")
        return cap
    
    def unregister_capability(self, id: str) -> bool:
        """注销能力。"""
        from core.agent.capability_registry import CapabilityRegistry
        from core.unified.capability_resolver import get_capability_resolver

        target = None
        for name, cap in list(self._runtime_capabilities.items()):
            if cap.id == id:
                target = name
                break
        if target is None:
            return False
        CapabilityRegistry.get_instance().eject(target)
        get_capability_resolver().invalidate_cache()
        self._runtime_capabilities.pop(target, None)
        return True

    @staticmethod
    def _contract_to_capability(contract: CapabilityContractLike) -> Capability:
        source_type = getattr(contract, "source", None)
        source_value = getattr(source_type, "value", str(source_type or "unknown"))
        type_map = {
            "device": CapabilityType.DEVICE,
            "mcp": CapabilityType.MCP,
            "skill": CapabilityType.SKILL,
            "node": CapabilityType.NODE,
            "gateway": CapabilityType.NODE,
            "unknown": CapabilityType.BUILTIN,
        }
        metadata = dict(getattr(contract, "metadata", {}) or {})
        return Capability(
            id=str(metadata.get("system_integration_id") or contract.name),
            name=contract.name,
            type=type_map.get(source_value, CapabilityType.BUILTIN),
            description=getattr(contract, "description", "") or "",
            source=getattr(contract, "source_id", "") or "",
            parameters=getattr(contract, "parameters", {}) or {},
            priority=int(metadata.get("priority", 5) or 5),
            enabled=bool(getattr(contract, "available", True)),
            metadata=metadata,
        )
    
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
        from core.unified.capability_resolver import get_capability_resolver

        resolver = get_capability_resolver()
        candidates = []

        direct = resolver.resolve(name)
        if direct is not None:
            candidates.append(self._merge_runtime_capability(self._contract_to_capability(direct)))

        if not candidates:
            for contract in resolver.find(name):
                candidates.append(self._merge_runtime_capability(self._contract_to_capability(contract)))

        if type:
            candidates = [c for c in candidates if c.type == type]

        if not candidates:
            return None

        if prefer_online:
            online_candidates = []
            for cap in candidates:
                if await self._is_capability_available(cap):
                    online_candidates.append(cap)
            if online_candidates:
                candidates = online_candidates

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

    def _merge_runtime_capability(self, cap: Capability) -> Capability:
        runtime_cap = self._runtime_capabilities.get(cap.name)
        if runtime_cap is None:
            return cap
        return Capability(
            id=runtime_cap.id or cap.id,
            name=cap.name,
            type=runtime_cap.type or cap.type,
            description=runtime_cap.description or cap.description,
            source=runtime_cap.source or cap.source,
            handler=runtime_cap.handler,
            parameters=runtime_cap.parameters or cap.parameters,
            priority=runtime_cap.priority or cap.priority,
            enabled=runtime_cap.enabled and cap.enabled,
            metadata={**cap.metadata, **runtime_cap.metadata},
        )
    
    def list_capabilities(
        self,
        type: CapabilityType = None,
        name: str = None,
    ) -> List[Capability]:
        """列出能力"""
        from core.unified.capability_resolver import get_capability_resolver

        capabilities = [
            self._merge_runtime_capability(self._contract_to_capability(contract))
            for contract in get_capability_resolver().resolve_all()
        ]
        if type:
            capabilities = [cap for cap in capabilities if cap.type == type]
        if name:
            capabilities = [cap for cap in capabilities if cap.name == name]
        return capabilities
    
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
        if cap.handler is not None:
            try:
                result = cap.handler(**params)
                if inspect.isawaitable(result):
                    return await result
                return result
            except Exception as exc:
                logger.error("执行自定义能力失败: %s (%s)", cap.name, exc)
                raise RuntimeError(f"执行能力失败: {cap.name}") from exc

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
        """执行节点能力 (unified executor with HTTP fallback)"""
        node_name = cap.source

        # Primary path: invoke via unified node executor (fusion_entry)
        try:
            from core.node_invocation import InvocationSource, invoke_node
            inv_result = await invoke_node(
                node_name,
                params.get("action", "execute"),
                params,
                invocation_source=InvocationSource.SYSTEM,
            )
            if inv_result.success:
                return inv_result.result
        except Exception as e:
            logger.debug(f"unified executor failed for {node_name}, trying HTTP fallback: {e}")

        # HTTP fallback: call node's HTTP /execute endpoint
        try:
            import httpx
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
            from core.llm.route_authority import get_llm_route_authority
            router = get_llm_route_authority().execution_router
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
        capabilities = self.list_capabilities()
        by_type: Dict[str, int] = {}
        for cap in capabilities:
            by_type[cap.type.value] = by_type.get(cap.type.value, 0) + 1
        return {
            "total_capabilities": len(capabilities),
            "by_type": by_type,
            "unique_names": len({cap.name for cap in capabilities}),
        }


# ============================================================================
# 全局实例
# ============================================================================

system = SystemIntegration.get_instance()
