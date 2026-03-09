"""
Galaxy - 能力编排器
=======================

统一管理 MCP 工具和 Skill，提供智能的能力发现和调用

功能：
1. 统一的能力注册表
2. 智能能力发现
3. 自动选择最佳能力
4. 能力组合和编排

使用方法：
    from core.capability_orchestrator import capability_orchestrator
    
    # 发现能力
    capabilities = await capability_orchestrator.discover("搜索网页")
    
    # 执行能力
    result = await capability_orchestrator.execute("搜索网页", query="Python")
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path
from enum import Enum

logger = logging.getLogger("Galaxy.Capability")


# ============================================================================
# 数据模型
# ============================================================================

class CapabilityType(str, Enum):
    """能力类型"""
    MCP_TOOL = "mcp_tool"      # MCP 工具
    SKILL = "skill"            # 技能
    NODE = "node"              # 节点
    BUILTIN = "builtin"        # 内置


@dataclass
class Capability:
    """能力定义"""
    id: str
    name: str
    description: str
    type: CapabilityType
    source: str = ""           # 来源 (mcp_server_name / skill_id / node_id)
    parameters: Dict = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    priority: int = 5          # 优先级 (1-10)
    enabled: bool = True
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.type.value,
            "source": self.source,
            "parameters": self.parameters,
            "tags": self.tags,
            "priority": self.priority,
            "enabled": self.enabled,
        }


# ============================================================================
# 能力编排器
# ============================================================================

class CapabilityOrchestrator:
    """
    能力编排器
    
    统一管理所有能力，提供智能发现和调用
    """
    
    _instance = None
    
    def __init__(self):
        self.capabilities: Dict[str, Capability] = {}
        self._initialized = False
        
        logger.info("能力编排器初始化")
    
    @classmethod
    def get_instance(cls) -> "CapabilityOrchestrator":
        if cls._instance is None:
            cls._instance = CapabilityOrchestrator()
        return cls._instance
    
    async def reinitialize(self):
        """重新加载所有能力（MCP/Skill 变更后调用）"""
        self.capabilities.clear()
        self._initialized = False
        await self.initialize()

    async def initialize(self):
        """初始化 - 加载所有能力"""
        if self._initialized:
            return
        
        # 加载 MCP 工具
        await self._load_mcp_tools()
        
        # 加载 Skill
        await self._load_skills()
        
        # 加载节点能力
        await self._load_nodes()
        
        # 加载内置能力
        self._load_builtins()
        
        self._initialized = True
        logger.info(f"已加载 {len(self.capabilities)} 个能力")
    
    async def _load_mcp_tools(self):
        """加载 MCP 工具 — 从 mcp_loader 读取已加载的 MCP 服务器工具"""
        try:
            from core.mcp_loader import mcp_loader, MCPServerStatus

            for server_id, server in mcp_loader.servers.items():
                if server.status != MCPServerStatus.RUNNING:
                    continue
                for tool in server.tools:
                    cap = Capability(
                        id=f"mcp_{server.name}_{tool.name}",
                        name=tool.name,
                        description=tool.description,
                        type=CapabilityType.MCP_TOOL,
                        source=server.name,
                        parameters=tool.inputSchema if hasattr(tool, "inputSchema") else {},
                        tags=["mcp", server.name],
                    )
                    self.capabilities[cap.id] = cap
        except Exception as e:
            logger.warning(f"加载 MCP 工具失败: {e}")
    
    async def _load_skills(self):
        """加载技能 — 从 skill_loader 读取已加载的技能"""
        try:
            from core.skill_loader import skill_loader

            for skill_dict in skill_loader.list_skills():
                skill_id = skill_dict.get("id", "")
                cap = Capability(
                    id=f"skill_{skill_id}",
                    name=skill_dict.get("name", skill_id),
                    description=skill_dict.get("description", ""),
                    type=CapabilityType.SKILL,
                    source=skill_id,
                    parameters=skill_dict.get("parameters", {}),
                    tags=skill_dict.get("tags", []) + ["skill"],
                )
                self.capabilities[cap.id] = cap
        except Exception as e:
            logger.warning(f"加载技能失败: {e}")
    
    async def _load_nodes(self):
        """加载节点能力"""
        try:
            config_path = Path("config/node_registry.json")
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                
                for node_name, node_info in config.get("nodes", {}).items():
                    cap = Capability(
                        id=f"node_{node_info['id']}",
                        name=node_info["name"],
                        description=f"节点: {node_info['name']}",
                        type=CapabilityType.NODE,
                        source=node_name,
                        tags=["node"],
                    )
                    self.capabilities[cap.id] = cap
        except Exception as e:
            logger.warning(f"加载节点失败: {e}")
    
    def _load_builtins(self):
        """加载内置能力"""
        builtins = [
            Capability(
                id="builtin_chat",
                name="对话",
                description="与 AI 进行对话",
                type=CapabilityType.BUILTIN,
                tags=["chat", "ai"],
                priority=1,
            ),
            Capability(
                id="builtin_device_control",
                name="设备控制",
                description="控制设备执行操作",
                type=CapabilityType.BUILTIN,
                tags=["device", "control"],
                priority=8,
            ),
            Capability(
                id="builtin_swarm_execute",
                name="蜂群执行",
                description="使用 Agent 蜂群并行执行任务",
                type=CapabilityType.BUILTIN,
                tags=["agent", "swarm", "parallel"],
                priority=6,
            ),
            Capability(
                id="builtin_team_execute",
                name="特种部队执行",
                description="使用多模型特种部队团队执行任务",
                type=CapabilityType.BUILTIN,
                tags=["agent", "team", "multi-model"],
                priority=6,
            ),
            Capability(
                id="builtin_twin_decide",
                name="孪生指挥官决策",
                description="使用双指挥官交叉验证决策",
                type=CapabilityType.BUILTIN,
                tags=["agent", "twin", "decision"],
                priority=6,
            ),
            Capability(
                id="builtin_simulate",
                name="模拟执行",
                description="通过数字孪生引擎模拟操作效果",
                type=CapabilityType.BUILTIN,
                tags=["simulate", "twin", "predict"],
                priority=6,
            ),
            Capability(
                id="builtin_cross_device",
                name="跨设备协同",
                description="跨设备任务协调：剪贴板同步、文件传输、媒体控制、通知同步",
                type=CapabilityType.BUILTIN,
                tags=["cross_device", "sync", "transfer", "clipboard", "multi_device"],
                priority=7,
            ),
        ]
        
        for cap in builtins:
            self.capabilities[cap.id] = cap
    
    # ========================================================================
    # 能力发现
    # ========================================================================
    
    async def discover(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict]:
        """
        发现能力
        
        Args:
            query: 查询字符串
            limit: 返回数量限制
        
        Returns:
            匹配的能力列表
        """
        if not self._initialized:
            await self.initialize()
        
        query_lower = query.lower()
        results = []
        
        for cap in self.capabilities.values():
            if not cap.enabled:
                continue
            
            score = 0
            
            # 名称匹配
            if query_lower in cap.name.lower():
                score += 10
            
            # 描述匹配
            if query_lower in cap.description.lower():
                score += 5
            
            # 标签匹配
            for tag in cap.tags:
                if query_lower in tag.lower():
                    score += 3
            
            # 优先级加成
            score += cap.priority
            
            if score > 0:
                results.append((cap, score))
        
        # 按分数排序
        results.sort(key=lambda x: x[1], reverse=True)
        
        return [cap.to_dict() for cap, _ in results[:limit]]
    
    async def find_best(
        self,
        query: str,
    ) -> Optional[Capability]:
        """找到最佳匹配的能力"""
        results = await self.discover(query, limit=1)
        if results:
            cap_dict = results[0]
            return self.capabilities.get(cap_dict["id"])
        return None
    
    # ========================================================================
    # 能力执行
    # ========================================================================
    
    async def execute(
        self,
        capability_id: str,
        **params,
    ) -> Any:
        """
        执行能力
        
        Args:
            capability_id: 能力 ID
            **params: 参数
        
        Returns:
            执行结果
        """
        if not self._initialized:
            await self.initialize()
        
        cap = self.capabilities.get(capability_id)
        if not cap:
            raise ValueError(f"能力不存在: {capability_id}")
        
        if not cap.enabled:
            raise RuntimeError(f"能力已禁用: {capability_id}")
        
        # 根据类型执行
        if cap.type == CapabilityType.MCP_TOOL:
            return await self._execute_mcp(cap, params)
        elif cap.type == CapabilityType.SKILL:
            return await self._execute_skill(cap, params)
        elif cap.type == CapabilityType.NODE:
            return await self._execute_node(cap, params)
        elif cap.type == CapabilityType.BUILTIN:
            return await self._execute_builtin(cap, params)
        else:
            raise RuntimeError(f"未知能力类型: {cap.type}")
    
    async def _execute_mcp(self, cap: Capability, params: Dict) -> Any:
        """执行 MCP 工具"""
        from core.mcp_loader import mcp_loader

        # cap.id 格式: mcp_{server_name}_{tool_name}
        # cap.source = server_name
        server_name = cap.source
        tool_name = cap.name

        # 查找 server_id（mcp_loader 用 id 而非 name 索引）
        server_id = None
        for sid, srv in mcp_loader.servers.items():
            if srv.name == server_name:
                server_id = sid
                break

        if not server_id:
            raise RuntimeError(f"MCP 服务器 {server_name} 未找到")

        return await mcp_loader.call_tool(server_id, tool_name, params)
    
    async def _execute_skill(self, cap: Capability, params: Dict) -> Any:
        """执行技能"""
        from core.skill_loader import skill_loader
        skill_id = cap.source
        return await skill_loader.execute(skill_id, **params)
    
    async def _execute_node(self, cap: Capability, params: Dict) -> Any:
        """执行节点"""
        import httpx
        
        node_id = cap.source.replace("Node_", "").split("_")[0]
        port = 8000 + int(node_id)
        url = f"http://localhost:{port}/execute"
        
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=params)
            return response.json()
    
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

        elif cap.id == "builtin_swarm_execute":
            from core.agent_swarm import get_agent_swarm
            swarm = get_agent_swarm()
            result = await swarm.execute(params.get("task", ""), params.get("context"))
            return result.to_dict()

        elif cap.id == "builtin_team_execute":
            from core.special_forces_team import get_special_forces_team
            team = get_special_forces_team()
            result = await team.execute(params.get("task", ""), params.get("context"))
            return result.to_dict()

        elif cap.id == "builtin_twin_decide":
            from core.twin_commander import get_twin_commander
            commander = get_twin_commander()
            result = await commander.analyze(params.get("task", ""), params.get("context"))
            return result.to_dict()

        elif cap.id == "builtin_simulate":
            # 数字孪生模拟 — 选择指定设备的孪生体或第一个可用孪生体
            from core.digital_twin_engine import get_digital_twin_engine
            engine = get_digital_twin_engine()
            action = params.get("action", params.get("message", ""))
            device_id = params.get("device_id", "")

            twin = None
            if device_id:
                twin = engine.get_twin_by_device(device_id)
            if not twin and engine.twins:
                twin = next(iter(engine.twins.values()))

            if not twin:
                return {"success": False, "reply": "没有可用的数字孪生体", "predicted_state": {}}

            result = await twin.simulate_action(action, params)
            return {
                "success": result.success_probability > 0.5 if hasattr(result, "success_probability") else True,
                "reply": f"模拟完成: {result.action}" if hasattr(result, "action") else str(result),
                "predicted_state": result.predicted_state if hasattr(result, "predicted_state") else {},
                "risks": result.risks if hasattr(result, "risks") else [],
            }

        elif cap.id == "builtin_cross_device":
            # 跨设备协同
            from galaxy_gateway.cross_device_coordinator import cross_device_coordinator
            command = params.get("message", params.get("command", ""))
            context = {k: v for k, v in params.items() if k not in ("message", "command")}
            result = await cross_device_coordinator.execute_cross_device_task(command, context)
            return {
                "success": result.get("success", False),
                "reply": result.get("message", str(result)),
                "data": result,
            }

        return None
    
    # ========================================================================
    # 智能执行
    # ========================================================================
    
    async def smart_execute(
        self,
        query: str,
        **params,
    ) -> Any:
        """
        智能执行 - 自动发现并执行最佳能力
        
        Args:
            query: 查询字符串
            **params: 参数
        
        Returns:
            执行结果
        """
        # 发现最佳能力
        cap = await self.find_best(query)
        
        if cap:
            logger.info(f"智能执行: {query} -> {cap.id}")
            return await self.execute(cap.id, **params)
        else:
            # 没有找到，使用默认对话
            logger.info(f"智能执行: {query} -> builtin_chat")
            return await self.execute("builtin_chat", message=query)
    
    # ========================================================================
    # 能力管理
    # ========================================================================
    
    def list_capabilities(self) -> List[Dict]:
        """列出所有能力"""
        return [cap.to_dict() for cap in self.capabilities.values()]
    
    def enable_capability(self, id: str) -> bool:
        """启用能力"""
        if id in self.capabilities:
            self.capabilities[id].enabled = True
            return True
        return False
    
    def disable_capability(self, id: str) -> bool:
        """禁用能力"""
        if id in self.capabilities:
            self.capabilities[id].enabled = False
            return True
        return False


# ============================================================================
# 全局实例
# ============================================================================

capability_orchestrator = CapabilityOrchestrator.get_instance()


# ============================================================================
# 便捷函数
# ============================================================================

async def discover_capability(query: str, limit: int = 5) -> List[Dict]:
    """发现能力"""
    return await capability_orchestrator.discover(query, limit)


async def execute_capability(capability_id: str, **params) -> Any:
    """执行能力"""
    return await capability_orchestrator.execute(capability_id, **params)


async def smart_execute(query: str, **params) -> Any:
    """智能执行"""
    return await capability_orchestrator.smart_execute(query, **params)
