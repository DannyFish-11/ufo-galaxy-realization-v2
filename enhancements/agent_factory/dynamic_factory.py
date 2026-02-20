"""
动态 Agent 工厂
==============

基于现有 Node_118_NodeFactory 增强：
- 集成 LLM 提供商
- 根据任务复杂度动态选择 LLM
- Agent 孪生模型
- 与智能体集成

版本: v2.3.22
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """任务复杂度"""
    LOW = "low"           # 简单任务：打开应用、截图
    MEDIUM = "medium"     # 中等任务：搜索、输入
    HIGH = "high"         # 复杂任务：图片分析、多步骤操作
    CRITICAL = "critical" # 关键任务：需要最高质量模型


class AgentState(Enum):
    """Agent 状态"""
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    cost_per_1k_tokens: float = 0.0
    speed_score: float = 1.0      # 速度评分 1-10
    quality_score: float = 1.0    # 质量评分 1-10
    capabilities: List[str] = field(default_factory=list)


@dataclass
class AgentConfig:
    """Agent 配置"""
    agent_id: str
    name: str
    task: str
    llm_config: LLMConfig
    complexity: TaskComplexity
    device_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    state: AgentState = AgentState.CREATED
    result: Any = None
    error: str = ""


@dataclass
class AgentTwin:
    """Agent 孪生"""
    twin_id: str
    agent_id: str
    snapshot: Dict[str, Any] = field(default_factory=dict)
    behavior_history: List[Dict] = field(default_factory=list)
    predictions: List[Dict] = field(default_factory=list)
    coupling_mode: str = "loose"  # tight, loose, decoupled


class DynamicAgentFactory:
    """动态 Agent 工厂"""
    
    def __init__(self):
        self.llm_providers: Dict[str, LLMConfig] = {}
        self.agents: Dict[str, AgentConfig] = {}
        self.twins: Dict[str, AgentTwin] = {}
        self._initialize_llm_providers()
    
    def _initialize_llm_providers(self):
        """初始化 LLM 提供商"""
        # Groq - 最快
        if os.getenv("GROQ_API_KEY"):
            self.register_llm(LLMConfig(
                provider="groq",
                model="llama-3.3-70b-versatile",
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
                cost_per_1k_tokens=0.0001,
                speed_score=10.0,
                quality_score=7.0,
                capabilities=["chat", "fast"]
            ))
        
        # OpenAI - 高质量
        if os.getenv("OPENAI_API_KEY"):
            self.register_llm(LLMConfig(
                provider="openai",
                model="gpt-4-turbo-preview",
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url="https://api.openai.com/v1",
                cost_per_1k_tokens=0.01,
                speed_score=6.0,
                quality_score=9.0,
                capabilities=["chat", "vision", "function_calling"]
            ))
        
        # 智谱 - 中文好
        if os.getenv("ZHIPU_API_KEY"):
            self.register_llm(LLMConfig(
                provider="zhipu",
                model="glm-4",
                api_key=os.getenv("ZHIPU_API_KEY"),
                base_url="https://open.bigmodel.cn/api/paas/v4",
                cost_per_1k_tokens=0.001,
                speed_score=7.0,
                quality_score=8.0,
                capabilities=["chat", "chinese"]
            ))
        
        # DeepSeek - 便宜
        if os.getenv("DEEPSEEK_API_KEY"):
            self.register_llm(LLMConfig(
                provider="deepseek",
                model="deepseek-chat",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com/v1",
                cost_per_1k_tokens=0.0001,
                speed_score=8.0,
                quality_score=7.0,
                capabilities=["chat", "coding"]
            ))
        
        # 本地 Ollama
        self.register_llm(LLMConfig(
            provider="ollama",
            model="llama3.2",
            base_url="http://localhost:11434/v1",
            cost_per_1k_tokens=0.0,
            speed_score=5.0,
            quality_score=6.0,
            capabilities=["chat", "local", "private"]
        ))
    
    def register_llm(self, config: LLMConfig):
        """注册 LLM 提供商"""
        self.llm_providers[config.provider] = config
        logger.info(f"Registered LLM: {config.provider} ({config.model})")
    
    def select_llm_for_task(
        self,
        task: str,
        complexity: TaskComplexity,
        required_capabilities: List[str] = None
    ) -> Optional[LLMConfig]:
        """根据任务选择最佳 LLM"""
        candidates = list(self.llm_providers.values())
        
        # 过滤能力
        if required_capabilities:
            candidates = [
                c for c in candidates
                if all(cap in c.capabilities for cap in required_capabilities)
            ]
        
        if not candidates:
            # 回退到任意可用的
            candidates = list(self.llm_providers.values())
        
        # 根据复杂度选择
        if complexity == TaskComplexity.LOW:
            # 简单任务：优先速度
            candidates.sort(key=lambda c: c.speed_score, reverse=True)
        elif complexity == TaskComplexity.HIGH or complexity == TaskComplexity.CRITICAL:
            # 复杂任务：优先质量
            candidates.sort(key=lambda c: c.quality_score, reverse=True)
        else:
            # 中等任务：平衡速度和质量
            candidates.sort(key=lambda c: (c.speed_score + c.quality_score) / 2, reverse=True)
        
        return candidates[0] if candidates else None
    
    def estimate_complexity(self, task: str, context: Dict = None) -> TaskComplexity:
        """评估任务复杂度"""
        task_lower = task.lower()
        
        # 关键任务
        critical_keywords = ["分析图片", "图像识别", "复杂决策", "多步骤", "关键"]
        if any(kw in task_lower for kw in critical_keywords):
            return TaskComplexity.CRITICAL
        
        # 高复杂度
        high_keywords = ["分析", "理解", "推理", "规划", "编程", "生成代码"]
        if any(kw in task_lower for kw in high_keywords):
            return TaskComplexity.HIGH
        
        # 中等复杂度
        medium_keywords = ["搜索", "查找", "输入", "填写", "比较", "总结"]
        if any(kw in task_lower for kw in medium_keywords):
            return TaskComplexity.MEDIUM
        
        # 低复杂度
        return TaskComplexity.LOW
    
    async def create_agent(
        self,
        task: str,
        device_id: str = "",
        llm_provider: str = None,
        complexity: TaskComplexity = None
    ) -> AgentConfig:
        """创建 Agent"""
        # 评估复杂度
        if complexity is None:
            complexity = self.estimate_complexity(task)
        
        # 选择 LLM
        if llm_provider:
            llm_config = self.llm_providers.get(llm_provider)
        else:
            # 根据任务需求选择
            required_caps = []
            if "图片" in task or "图像" in task:
                required_caps.append("vision")
            if "中文" in task:
                required_caps.append("chinese")
            
            llm_config = self.select_llm_for_task(task, complexity, required_caps)
        
        if not llm_config:
            # 回退
            llm_config = LLMConfig(
                provider="fallback",
                model="fallback",
                speed_score=5.0,
                quality_score=5.0
            )
        
        # 创建 Agent
        agent_id = f"agent_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        agent = AgentConfig(
            agent_id=agent_id,
            name=f"Agent_{len(self.agents) + 1}",
            task=task,
            llm_config=llm_config,
            complexity=complexity,
            device_id=device_id
        )
        
        self.agents[agent_id] = agent
        
        # 创建孪生
        await self.create_twin(agent_id)
        
        logger.info(f"Created agent: {agent_id} (LLM: {llm_config.provider}, Complexity: {complexity.value})")
        return agent
    
    async def create_twin(self, agent_id: str) -> AgentTwin:
        """创建 Agent 孪生"""
        twin_id = f"twin_{agent_id}"
        twin = AgentTwin(
            twin_id=twin_id,
            agent_id=agent_id,
            snapshot={"state": "created"}
        )
        self.twins[twin_id] = twin
        logger.info(f"Created twin: {twin_id} for agent: {agent_id}")
        return twin
    
    async def execute_agent(self, agent_id: str, context: Dict = None) -> Dict:
        """执行 Agent"""
        if agent_id not in self.agents:
            return {"error": "Agent not found"}
        
        agent = self.agents[agent_id]
        agent.state = AgentState.RUNNING
        
        try:
            # 调用 LLM
            llm = agent.llm_config
            response = await self._call_llm(llm, agent.task, context)
            
            agent.result = response
            agent.state = AgentState.COMPLETED
            
            # 更新孪生
            await self._update_twin(agent_id, {
                "state": "completed",
                "result": response
            })
            
            return {
                "agent_id": agent_id,
                "success": True,
                "result": response,
                "llm_used": llm.provider
            }
        
        except Exception as e:
            agent.state = AgentState.FAILED
            agent.error = str(e)
            
            await self._update_twin(agent_id, {
                "state": "failed",
                "error": str(e)
            })
            
            return {
                "agent_id": agent_id,
                "success": False,
                "error": str(e)
            }
    
    async def _call_llm(
        self,
        config: LLMConfig,
        prompt: str,
        context: Dict = None
    ) -> str:
        """调用 LLM"""
        if not config.base_url:
            return f"[模拟响应] 任务: {prompt}"
        
        url = f"{config.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        
        messages = [{"role": "user", "content": prompt}]
        if context and context.get("history"):
            messages = context["history"] + messages
        
        payload = {
            "model": config.model,
            "messages": messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature
        }
        
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def _update_twin(self, agent_id: str, update: Dict):
        """更新孪生状态"""
        twin_id = f"twin_{agent_id}"
        if twin_id in self.twins:
            twin = self.twins[twin_id]
            twin.snapshot.update(update)
            twin.behavior_history.append({
                "timestamp": datetime.now().isoformat(),
                "update": update
            })
    
    def decouple_twin(self, agent_id: str):
        """解耦孪生"""
        twin_id = f"twin_{agent_id}"
        if twin_id in self.twins:
            self.twins[twin_id].coupling_mode = "decoupled"
            logger.info(f"Decoupled twin: {twin_id}")
    
    def couple_twin(self, agent_id: str, mode: str = "loose"):
        """耦合孪生"""
        twin_id = f"twin_{agent_id}"
        if twin_id in self.twins:
            self.twins[twin_id].coupling_mode = mode
            logger.info(f"Coupled twin: {twin_id} with mode: {mode}")
    
    def get_agent(self, agent_id: str) -> Optional[AgentConfig]:
        """获取 Agent"""
        return self.agents.get(agent_id)
    
    def list_agents(self) -> List[Dict]:
        """列出所有 Agent"""
        return [
            {
                "agent_id": a.agent_id,
                "name": a.name,
                "task": a.task,
                "state": a.state.value,
                "complexity": a.complexity.value,
                "llm_provider": a.llm_config.provider
            }
            for a in self.agents.values()
        ]
    
    def list_llm_providers(self) -> List[Dict]:
        """列出 LLM 提供商"""
        return [
            {
                "provider": p,
                "model": c.model,
                "speed_score": c.speed_score,
                "quality_score": c.quality_score,
                "cost_per_1k": c.cost_per_1k_tokens,
                "capabilities": c.capabilities,
                "available": bool(c.api_key or p == "ollama")
            }
            for p, c in self.llm_providers.items()
        ]


# 全局实例
agent_factory = DynamicAgentFactory()
