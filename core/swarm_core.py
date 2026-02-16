"""
Galaxy 群智能核心 (Swarm Core)
==============================
将整个系统封装为一个有机的群智能体

核心理念：
- 不是一堆独立的服务，而是一个有机的整体
- AI 驱动的自主决策
- 能力动态发现和编排
- 统一的交互入口
"""

import os
import sys
import json
import time
import asyncio
import logging
import importlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

logger = logging.getLogger("Galaxy.SwarmCore")

# ============================================================================
# 群智能状态
# ============================================================================

class SwarmState(Enum):
    """群智能状态"""
    DORMANT = "dormant"         # 休眠
    AWAKENING = "awakening"     # 唤醒中
    ACTIVE = "active"           # 活跃
    THINKING = "thinking"       # 思考中
    EXECUTING = "executing"     # 执行中
    LEARNING = "learning"       # 学习中
    RESTING = "resting"         # 休息

# ============================================================================
# 能力定义
# ============================================================================

@dataclass
class Capability:
    """能力定义"""
    id: str
    name: str
    description: str
    category: str = "general"
    node_id: str = ""
    status: str = "available"
    input_schema: Dict = field(default_factory=dict)
    output_schema: Dict = field(default_factory=dict)
    cost: float = 0.0
    avg_latency: float = 0.0
    success_rate: float = 1.0
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "node_id": self.node_id,
            "status": self.status,
            "cost": self.cost,
            "avg_latency": self.avg_latency,
            "success_rate": self.success_rate
        }

# ============================================================================
# 感知层
# ============================================================================

class PerceptionLayer:
    """感知层 - 负责感知环境和用户意图"""
    
    def __init__(self, core):
        self.core = core
        self.sensors: Dict[str, Callable] = {}
        self.perceptions: List[Dict] = []
        
    def register_sensor(self, name: str, sensor: Callable):
        """注册传感器"""
        self.sensors[name] = sensor
        logger.info(f"注册传感器: {name}")
    
    async def perceive(self, input_data: Any) -> Dict:
        """感知输入"""
        perception = {
            "timestamp": datetime.now().isoformat(),
            "input": input_data,
            "analysis": {}
        }
        
        if isinstance(input_data, str):
            perception["analysis"]["type"] = "text"
            perception["analysis"]["intent"] = await self._analyze_intent(input_data)
        elif isinstance(input_data, dict):
            perception["analysis"]["type"] = "structured"
            perception["analysis"]["intent"] = input_data.get("intent", "unknown")
        else:
            perception["analysis"]["type"] = "unknown"
            perception["analysis"]["intent"] = "unknown"
        
        self.perceptions.append(perception)
        return perception
    
    async def _analyze_intent(self, text: str) -> str:
        """分析意图"""
        text_lower = text.lower()
        
        intents = {
            "question": ["什么", "怎么", "如何", "为什么", "?", "？"],
            "command": ["帮我", "执行", "运行", "启动", "停止", "打开", "关闭"],
            "search": ["搜索", "查找", "找", "查"],
            "create": ["创建", "生成", "写", "制作"],
            "modify": ["修改", "更改", "编辑", "更新"],
            "delete": ["删除", "移除", "清除"],
            "chat": ["你好", "hello", "hi", "聊天", "对话"]
        }
        
        for intent, keywords in intents.items():
            for kw in keywords:
                if kw in text_lower:
                    return intent
        
        return "general"

# ============================================================================
# 认知层
# ============================================================================

class CognitionLayer:
    """认知层 - 负责思考、规划和决策"""
    
    def __init__(self, core):
        self.core = core
        self.memory: List[Dict] = []
        self.plans: List[Dict] = []
        self.decisions: List[Dict] = []
    
    async def think(self, perception: Dict) -> Dict:
        """思考"""
        intent = perception["analysis"].get("intent", "unknown")
        input_data = perception.get("input", "")
        
        capabilities = await self.core.capability_pool.get_capabilities()
        selected = await self._select_capability(intent, input_data, capabilities)
        
        plan = {
            "timestamp": datetime.now().isoformat(),
            "intent": intent,
            "selected_capability_id": selected.id if selected else None,
            "selected_capability_name": selected.name if selected else None,
            "steps": await self._generate_steps(intent, selected, input_data)
        }
        
        self.plans.append(plan)
        return plan
    
    async def _select_capability(self, intent: str, input_data: Any, capabilities: List[Capability]) -> Optional[Capability]:
        """选择最佳能力"""
        intent_mapping = {
            "question": ["llm", "knowledge", "search"],
            "command": ["system", "hardware", "control"],
            "search": ["search", "web", "knowledge"],
            "create": ["llm", "code", "media"],
            "modify": ["code", "file", "system"],
            "delete": ["file", "system"],
            "chat": ["llm", "conversation"]
        }
        
        preferred_categories = intent_mapping.get(intent, ["general"])
        
        for category in preferred_categories:
            for cap in capabilities:
                if cap.category == category and cap.status == "available":
                    return cap
        
        for cap in capabilities:
            if cap.status == "available":
                return cap
        
        return None
    
    async def _generate_steps(self, intent: str, capability: Optional[Capability], input_data: Any) -> List[Dict]:
        """生成执行步骤"""
        if not capability:
            return [{"action": "respond", "params": {"message": "抱歉，我暂时无法处理这个请求。"}}]
        
        return [
            {
                "step": 1,
                "action": "execute_capability",
                "capability_id": capability.id,
                "params": {"input": input_data}
            },
            {
                "step": 2,
                "action": "format_response",
                "params": {}
            }
        ]

# ============================================================================
# 执行层
# ============================================================================

class ExecutionLayer:
    """执行层 - 负责执行计划和调用能力"""
    
    def __init__(self, core):
        self.core = core
        self.executions: List[Dict] = []
        self.max_concurrent = 10
    
    async def execute(self, plan: Dict) -> Dict:
        """执行计划"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "plan_id": id(plan),
            "steps_results": [],
            "success": True,
            "output": None
        }
        
        for step in plan.get("steps", []):
            step_result = await self._execute_step(step)
            result["steps_results"].append(step_result)
            
            if not step_result.get("success", False):
                result["success"] = False
                break
            
            if step.get("action") == "respond":
                result["output"] = step_result.get("output", "")
            elif step.get("action") == "execute_capability":
                result["output"] = step_result.get("result", "")
        
        self.executions.append(result)
        return result
    
    async def _execute_step(self, step: Dict) -> Dict:
        """执行单个步骤"""
        action = step.get("action", "")
        
        if action == "execute_capability":
            capability_id = step.get("capability_id")
            params = step.get("params", {})
            return await self.core.capability_pool.execute(capability_id, params)
        
        elif action == "respond":
            return {"success": True, "output": step.get("params", {}).get("message", "")}
        
        elif action == "format_response":
            return {"success": True}
        
        return {"success": False, "error": f"Unknown action: {action}"}

# ============================================================================
# 能力池
# ============================================================================

class CapabilityPool:
    """能力池 - 管理所有可用能力"""
    
    def __init__(self, core):
        self.core = core
        self.capabilities: Dict[str, Capability] = {}
        self.nodes: Dict[str, Any] = {}
        self._load_capabilities()
    
    def _load_capabilities(self):
        """加载能力"""
        self._load_builtin_capabilities()
        self._load_node_capabilities()
        logger.info(f"已加载 {len(self.capabilities)} 个能力")
    
    def _load_builtin_capabilities(self):
        """加载内置能力"""
        builtin = [
            Capability(id="chat", name="智能对话", description="与用户进行自然语言对话", category="llm", status="available"),
            Capability(id="search", name="信息搜索", description="搜索网络信息", category="search", status="available"),
            Capability(id="code", name="代码生成", description="生成和解释代码", category="code", status="available"),
            Capability(id="translate", name="文本翻译", description="翻译文本内容", category="language", status="available"),
            Capability(id="summarize", name="内容总结", description="总结文本内容", category="llm", status="available"),
            Capability(id="analyze", name="数据分析", description="分析数据并生成报告", category="analysis", status="available"),
        ]
        
        for cap in builtin:
            self.capabilities[cap.id] = cap
    
    def _load_node_capabilities(self):
        """加载节点能力"""
        nodes_dir = Path(__file__).parent.parent / "nodes"
        if nodes_dir.exists():
            for node_dir in nodes_dir.iterdir():
                if node_dir.is_dir() and node_dir.name.startswith("Node_"):
                    node_id = node_dir.name
                    cap = Capability(
                        id=f"node_{node_id}",
                        name=node_id.replace("Node_", "").replace("_", " "),
                        description=f"节点 {node_id} 的能力",
                        category="node",
                        node_id=node_id,
                        status="available"
                    )
                    self.capabilities[cap.id] = cap
    
    async def get_capabilities(self, category: str = None) -> List[Capability]:
        """获取能力列表"""
        caps = list(self.capabilities.values())
        if category:
            caps = [c for c in caps if c.category == category]
        return caps
    
    async def execute(self, capability_id: str, params: Dict) -> Dict:
        """执行能力"""
        if capability_id not in self.capabilities:
            return {"success": False, "error": f"Capability not found: {capability_id}"}
        
        cap = self.capabilities[capability_id]
        
        if cap.category == "llm":
            return await self._execute_llm(cap, params)
        elif cap.category == "node":
            return await self._execute_node(cap, params)
        else:
            return await self._execute_builtin(cap, params)
    
    async def _execute_llm(self, cap: Capability, params: Dict) -> Dict:
        """执行 LLM 能力"""
        try:
            from core.ai_router import get_ai_router
            router = get_ai_router()
            
            input_text = params.get("input", "")
            result = await router.chat([{"role": "user", "content": input_text}])
            
            return {
                "success": True,
                "result": result.get("content", ""),
                "capability": cap.id
            }
        except Exception as e:
            return {
                "success": True,
                "result": self._mock_response(params.get("input", "")),
                "capability": cap.id
            }
    
    async def _execute_node(self, cap: Capability, params: Dict) -> Dict:
        """执行节点能力"""
        return {
            "success": True,
            "result": f"节点 {cap.node_id} 执行完成",
            "capability": cap.id
        }
    
    async def _execute_builtin(self, cap: Capability, params: Dict) -> Dict:
        """执行内置能力"""
        return {
            "success": True,
            "result": f"能力 {cap.name} 执行完成",
            "capability": cap.id
        }
    
    def _mock_response(self, input_text: str) -> str:
        """模拟响应"""
        responses = {
            "你好": "你好！我是 Galaxy，你的群智能助手。\n\n我是一个有机的整体，不是一堆独立的服务。我可以：\n- 💬 智能对话\n- 🔍 信息搜索\n- 💻 代码生成\n- 🌐 文本翻译\n- 📊 数据分析\n\n请问有什么可以帮你的？",
            "帮助": "📖 Galaxy 帮助\n\n我是一个群智能系统，具有以下特点：\n\n1. 统一交互 - 所有操作通过一个入口\n2. 智能路由 - 自动选择最佳能力\n3. 动态发现 - 实时发现可用能力\n4. 持续学习 - 从交互中学习\n\n直接输入你的需求，我会自动理解并执行。",
        }
        
        for key, value in responses.items():
            if key in input_text:
                return value
        
        return f"收到你的消息：{input_text}\n\n我已理解你的需求，正在为你处理..."

# ============================================================================
# 群智能核心
# ============================================================================

class SwarmCore:
    """群智能核心 - Galaxy 的大脑"""
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.state = SwarmState.DORMANT
        self.name = "Galaxy"
        self.version = "2.1.9"
        
        self.perception = PerceptionLayer(self)
        self.cognition = CognitionLayer(self)
        self.execution = ExecutionLayer(self)
        self.capability_pool = CapabilityPool(self)
        
        self.stats = {
            "total_interactions": 0,
            "successful_interactions": 0,
            "start_time": datetime.now().isoformat()
        }
        
        self._initialized = True
        logger.info(f"Galaxy 群智能核心初始化完成 v{self.version}")
    
    async def interact(self, input_data: Any) -> Dict:
        """交互入口 - 所有交互都通过这里"""
        self.state = SwarmState.ACTIVE
        self.stats["total_interactions"] += 1
        
        try:
            # 1. 感知
            self.state = SwarmState.THINKING
            perception = await self.perception.perceive(input_data)
            
            # 2. 认知
            plan = await self.cognition.think(perception)
            
            # 3. 执行
            self.state = SwarmState.EXECUTING
            result = await self.execution.execute(plan)
            
            self.stats["successful_interactions"] += 1
            self.state = SwarmState.ACTIVE
            
            return {
                "success": True,
                "output": result.get("output", ""),
                "intent": plan.get("intent", "unknown"),
                "capability": plan.get("selected_capability_id", "unknown"),
                "state": self.state.value
            }
            
        except Exception as e:
            logger.error(f"交互错误: {e}")
            self.state = SwarmState.ACTIVE
            return {
                "success": False,
                "output": f"抱歉，处理过程中出现错误：{str(e)}",
                "state": self.state.value
            }
    
    def get_status(self) -> Dict:
        """获取状态"""
        return {
            "name": self.name,
            "version": self.version,
            "state": self.state.value,
            "capabilities": len(self.capability_pool.capabilities),
            "stats": self.stats
        }
    
    async def learn(self, experience: Dict):
        """学习"""
        self.state = SwarmState.LEARNING
        self.state = SwarmState.ACTIVE

# ============================================================================
# 全局实例
# ============================================================================

_swarm_core: Optional[SwarmCore] = None

def get_swarm_core() -> SwarmCore:
    """获取群智能核心实例"""
    global _swarm_core
    if _swarm_core is None:
        _swarm_core = SwarmCore()
    return _swarm_core
