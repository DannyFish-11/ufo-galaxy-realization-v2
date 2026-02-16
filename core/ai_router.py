"""
Galaxy - AI 驱动智能路由器
根据任务类型、复杂度、成本等因素智能选择最佳 LLM 模型
"""

import os
import json
import asyncio
import logging
import time
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import random

logger = logging.getLogger("Galaxy.AIRouter")

# ============================================================================
# 任务类型分类
# ============================================================================

class TaskType(Enum):
    """任务类型"""
    # 简单任务 - 可以用小模型
    SIMPLE_QA = "simple_qa"              # 简单问答
    TRANSLATION = "translation"          # 翻译
    SUMMARIZATION = "summarization"      # 总结
    CLASSIFICATION = "classification"    # 分类
    
    # 中等任务 - 需要中等模型
    REASONING = "reasoning"              # 推理
    ANALYSIS = "analysis"                # 分析
    WRITING = "writing"                  # 写作
    CODING = "coding"                    # 编程
    
    # 复杂任务 - 需要大模型
    COMPLEX_REASONING = "complex_reasoning"  # 复杂推理
    CREATIVE = "creative"                # 创意写作
    PLANNING = "planning"                # 规划
    MULTI_STEP = "multi_step"            # 多步骤任务
    
    # 特殊任务
    VISION = "vision"                    # 视觉理解
    FUNCTION_CALL = "function_call"      # 函数调用
    UNKNOWN = "unknown"                  # 未知

class TaskComplexity(Enum):
    """任务复杂度"""
    LOW = "low"          # 简单，可用小模型
    MEDIUM = "medium"    # 中等，需要中等模型
    HIGH = "high"        # 复杂，需要大模型

# ============================================================================
# 模型能力配置
# ============================================================================

@dataclass
class ModelCapabilities:
    """模型能力"""
    model_id: str
    provider: str
    model_name: str
    
    # 能力评分 (0-10)
    reasoning: float = 5.0           # 推理能力
    creativity: float = 5.0          # 创意能力
    coding: float = 5.0              # 编程能力
    analysis: float = 5.0            # 分析能力
    speed: float = 5.0               # 速度
    context_length: int = 4096       # 上下文长度
    
    # 成本 (美元/1K tokens)
    cost_input: float = 0.01
    cost_output: float = 0.03
    
    # 特殊能力
    supports_vision: bool = False
    supports_function_call: bool = True
    
    # API 配置
    api_key: str = ""
    base_url: str = ""
    
    # 统计
    total_calls: int = 0
    success_calls: int = 0
    avg_latency: float = 0.0

# 预定义模型能力
DEFAULT_MODELS = {
    # OpenAI
    "gpt-4o": ModelCapabilities(
        model_id="gpt-4o",
        provider="openai",
        model_name="gpt-4o",
        reasoning=9.0, creativity=8.5, coding=9.0, analysis=9.0, speed=7.0,
        context_length=128000,
        cost_input=0.005, cost_output=0.015,
        supports_vision=True, supports_function_call=True
    ),
    "gpt-4o-mini": ModelCapabilities(
        model_id="gpt-4o-mini",
        provider="openai",
        model_name="gpt-4o-mini",
        reasoning=7.0, creativity=6.5, coding=7.5, analysis=7.0, speed=9.0,
        context_length=128000,
        cost_input=0.00015, cost_output=0.0006,
        supports_vision=True, supports_function_call=True
    ),
    
    # DeepSeek
    "deepseek-chat": ModelCapabilities(
        model_id="deepseek-chat",
        provider="deepseek",
        model_name="deepseek-chat",
        reasoning=8.0, creativity=7.5, coding=8.5, analysis=8.0, speed=8.0,
        context_length=64000,
        cost_input=0.0001, cost_output=0.0002,
        base_url="https://api.deepseek.com/v1"
    ),
    "deepseek-reasoner": ModelCapabilities(
        model_id="deepseek-reasoner",
        provider="deepseek",
        model_name="deepseek-reasoner",
        reasoning=9.5, creativity=7.0, coding=8.0, analysis=9.0, speed=5.0,
        context_length=64000,
        cost_input=0.00055, cost_output=0.00219,
        base_url="https://api.deepseek.com/v1"
    ),
    
    # Anthropic
    "claude-3-5-sonnet": ModelCapabilities(
        model_id="claude-3-5-sonnet",
        provider="anthropic",
        model_name="claude-3-5-sonnet-20241022",
        reasoning=9.5, creativity=9.0, coding=9.5, analysis=9.5, speed=7.0,
        context_length=200000,
        cost_input=0.003, cost_output=0.015,
        supports_vision=True
    ),
    
    # Google
    "gemini-2.0-flash": ModelCapabilities(
        model_id="gemini-2.0-flash",
        provider="google",
        model_name="gemini-2.0-flash-exp",
        reasoning=8.0, creativity=7.5, coding=8.0, analysis=8.0, speed=9.5,
        context_length=1000000,
        cost_input=0.0, cost_output=0.0,  # 免费额度
        supports_vision=True
    ),
    
    # Groq (快速推理)
    "llama-3.3-70b": ModelCapabilities(
        model_id="llama-3.3-70b",
        provider="groq",
        model_name="llama-3.3-70b-versatile",
        reasoning=8.0, creativity=7.0, coding=7.5, analysis=7.5, speed=10.0,
        context_length=8000,
        cost_input=0.0, cost_output=0.0,  # 免费额度
        base_url="https://api.groq.com/openai/v1"
    ),
}

# ============================================================================
# AI 路由器
# ============================================================================

class AIRouter:
    """AI 驱动智能路由器"""
    
    def __init__(self):
        self.models: Dict[str, ModelCapabilities] = {}
        self.routing_history: List[Dict] = []
        self._load_models()
        
        logger.info("AI 智能路由器初始化完成")
    
    def _load_models(self):
        """加载模型配置"""
        # 加载默认模型
        for model_id, capabilities in DEFAULT_MODELS.items():
            # 从环境变量获取 API Key
            if capabilities.provider == "openai":
                capabilities.api_key = os.getenv("OPENAI_API_KEY", "")
            elif capabilities.provider == "deepseek":
                capabilities.api_key = os.getenv("DEEPSEEK_API_KEY", "")
            elif capabilities.provider == "anthropic":
                capabilities.api_key = os.getenv("ANTHROPIC_API_KEY", "")
            elif capabilities.provider == "google":
                capabilities.api_key = os.getenv("GEMINI_API_KEY", "")
            elif capabilities.provider == "groq":
                capabilities.api_key = os.getenv("GROQ_API_KEY", "")
            
            if capabilities.api_key:
                self.models[model_id] = capabilities
    
    # ========================================================================
    # 任务分析
    # ========================================================================
    
    def analyze_task(self, prompt: str, context: Dict = None) -> Tuple[TaskType, TaskComplexity]:
        """分析任务类型和复杂度"""
        
        prompt_lower = prompt.lower()
        
        # 检测任务类型
        task_type = TaskType.UNKNOWN
        complexity = TaskComplexity.MEDIUM
        
        # 简单问答
        if any(kw in prompt_lower for kw in ["是什么", "什么是", "多少", "什么时候", "who", "what", "when", "where"]):
            if len(prompt) < 100:
                task_type = TaskType.SIMPLE_QA
                complexity = TaskComplexity.LOW
        
        # 翻译
        elif any(kw in prompt_lower for kw in ["翻译", "translate", "译成", "translate to"]):
            task_type = TaskType.TRANSLATION
            complexity = TaskComplexity.LOW
        
        # 总结
        elif any(kw in prompt_lower for kw in ["总结", "摘要", "summarize", "summary", "概括"]):
            task_type = TaskType.SUMMARIZATION
            complexity = TaskComplexity.LOW
        
        # 编程
        elif any(kw in prompt_lower for kw in ["代码", "编程", "code", "function", "python", "javascript", "写一个函数"]):
            task_type = TaskType.CODING
            complexity = TaskComplexity.MEDIUM
        
        # 推理
        elif any(kw in prompt_lower for kw in ["为什么", "原因", "分析", "为什么", "why", "reason", "explain"]):
            task_type = TaskType.REASONING
            complexity = TaskComplexity.MEDIUM
        
        # 创意写作
        elif any(kw in prompt_lower for kw in ["写一个故事", "创作", "创意", "write a story", "creative"]):
            task_type = TaskType.CREATIVE
            complexity = TaskComplexity.HIGH
        
        # 复杂推理
        elif any(kw in prompt_lower for kw in ["步骤", "计划", "策略", "step by step", "plan", "strategy"]):
            task_type = TaskType.MULTI_STEP
            complexity = TaskComplexity.HIGH
        
        # 视觉任务
        elif any(kw in prompt_lower for kw in ["图片", "图像", "截图", "看", "image", "screenshot", "看一眼"]):
            task_type = TaskType.VISION
            complexity = TaskComplexity.MEDIUM
        
        # 根据长度调整复杂度
        if len(prompt) > 1000:
            complexity = TaskComplexity.HIGH
        elif len(prompt) < 50 and complexity == TaskComplexity.MEDIUM:
            complexity = TaskComplexity.LOW
        
        return task_type, complexity
    
    # ========================================================================
    # 智能选择模型
    # ========================================================================
    
    def select_best_model(self, prompt: str, context: Dict = None, 
                          optimize_for: str = "balanced") -> Tuple[str, ModelCapabilities]:
        """
        智能选择最佳模型
        
        Args:
            prompt: 用户输入
            context: 上下文
            optimize_for: 优化目标 (speed/cost/quality/balanced)
        
        Returns:
            (model_id, model_capabilities)
        """
        
        # 分析任务
        task_type, complexity = self.analyze_task(prompt, context)
        
        logger.info(f"任务分析: 类型={task_type.value}, 复杂度={complexity.value}")
        
        # 获取可用模型
        available_models = {k: v for k, v in self.models.items() if v.api_key}
        
        if not available_models:
            raise Exception("没有可用的 LLM 模型")
        
        # 根据任务类型和优化目标选择模型
        best_model = None
        best_score = -1
        
        for model_id, model in available_models.items():
            score = self._calculate_model_score(model, task_type, complexity, optimize_for)
            
            if score > best_score:
                best_score = score
                best_model = model_id
        
        logger.info(f"选择模型: {best_model} (得分: {best_score:.2f})")
        
        return best_model, self.models[best_model]
    
    def _calculate_model_score(self, model: ModelCapabilities, 
                               task_type: TaskType, 
                               complexity: TaskComplexity,
                               optimize_for: str) -> float:
        """计算模型得分"""
        
        score = 0.0
        
        # 基础能力得分
        if task_type == TaskType.CODING:
            score += model.coding * 2
        elif task_type == TaskType.CREATIVE:
            score += model.creativity * 2
        elif task_type == TaskType.REASONING or task_type == TaskType.COMPLEX_REASONING:
            score += model.reasoning * 2
        elif task_type == TaskType.ANALYSIS:
            score += model.analysis * 2
        else:
            score += (model.reasoning + model.analysis) / 2
        
        # 复杂度调整
        if complexity == TaskComplexity.HIGH:
            # 复杂任务需要更强的推理能力
            score += model.reasoning * 0.5
        elif complexity == TaskComplexity.LOW:
            # 简单任务可以用快速模型
            score += model.speed * 0.5
        
        # 视觉任务需要支持视觉的模型
        if task_type == TaskType.VISION:
            if model.supports_vision:
                score += 10
            else:
                score -= 100  # 不支持视觉的模型不适合
        
        # 优化目标调整
        if optimize_for == "speed":
            score += model.speed * 2
        elif optimize_for == "cost":
            # 成本越低越好
            if model.cost_input + model.cost_output > 0:
                score -= (model.cost_input + model.cost_output) * 1000
            else:
                score += 5  # 免费模型加分
        elif optimize_for == "quality":
            score += (model.reasoning + model.creativity + model.coding + model.analysis) / 4
        
        # 历史成功率调整
        if model.total_calls > 0:
            success_rate = model.success_calls / model.total_calls
            score += success_rate * 5
        
        return score
    
    # ========================================================================
    # 执行请求
    # ========================================================================
    
    async def chat(self, messages: List[Dict], optimize_for: str = "balanced",
                   **kwargs) -> Dict[str, Any]:
        """
        智能路由聊天
        
        Args:
            messages: 消息列表
            optimize_for: 优化目标
            **kwargs: 其他参数
        
        Returns:
            响应结果
        """
        
        # 获取最后一条用户消息
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        # 选择最佳模型
        model_id, model = self.select_best_model(user_message, optimize_for=optimize_for)
        
        logger.info(f"AI 路由选择: {model_id} (优化: {optimize_for})")
        
        # 调用模型
        start_time = time.time()
        
        try:
            result = await self._call_model(model, messages, **kwargs)
            
            latency = time.time() - start_time
            
            # 更新统计
            model.total_calls += 1
            model.success_calls += 1
            model.avg_latency = (model.avg_latency * (model.total_calls - 1) + latency) / model.total_calls
            
            # 记录路由历史
            self.routing_history.append({
                "timestamp": datetime.now().isoformat(),
                "model": model_id,
                "latency": latency,
                "success": True
            })
            
            result["routing"] = {
                "model": model_id,
                "provider": model.provider,
                "latency": latency,
                "optimize_for": optimize_for
            }
            
            return result
            
        except Exception as e:
            model.total_calls += 1
            
            self.routing_history.append({
                "timestamp": datetime.now().isoformat(),
                "model": model_id,
                "latency": time.time() - start_time,
                "success": False,
                "error": str(e)
            })
            
            # 尝试故障转移
            return await self._failover(messages, model_id, **kwargs)
    
    async def _call_model(self, model: ModelCapabilities, messages: List[Dict], **kwargs) -> Dict:
        """调用模型"""
        
        from openai import AsyncOpenAI
        
        client = AsyncOpenAI(
            api_key=model.api_key,
            base_url=model.base_url or None
        )
        
        response = await client.chat.completions.create(
            model=model.model_name,
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 4096),
            temperature=kwargs.get("temperature", 0.7)
        )
        
        return {
            "success": True,
            "content": response.choices[0].message.content,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        }
    
    async def _failover(self, messages: List[Dict], failed_model: str, **kwargs) -> Dict:
        """故障转移"""
        
        logger.warning(f"模型 {failed_model} 失败，尝试故障转移...")
        
        # 获取其他可用模型
        available = [m for m in self.models.keys() if m != failed_model and self.models[m].api_key]
        
        if not available:
            return {
                "success": False,
                "error": "所有模型都不可用"
            }
        
        # 选择备用模型
        backup_model = available[0]
        model = self.models[backup_model]
        
        logger.info(f"故障转移到: {backup_model}")
        
        try:
            return await self._call_model(model, messages, **kwargs)
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    # ========================================================================
    # 统计
    # ========================================================================
    
    def get_stats(self) -> Dict:
        """获取路由统计"""
        
        model_stats = {}
        for model_id, model in self.models.items():
            model_stats[model_id] = {
                "provider": model.provider,
                "total_calls": model.total_calls,
                "success_calls": model.success_calls,
                "success_rate": f"{(model.success_calls / model.total_calls * 100) if model.total_calls > 0 else 0:.1f}%",
                "avg_latency": f"{model.avg_latency:.2f}s"
            }
        
        return {
            "models": model_stats,
            "total_routing": len(self.routing_history),
            "available_models": len([m for m in self.models.values() if m.api_key])
        }

# ============================================================================
# 全局实例
# ============================================================================

_ai_router: Optional[AIRouter] = None

def get_ai_router() -> AIRouter:
    """获取全局 AI 路由器"""
    global _ai_router
    if _ai_router is None:
        _ai_router = AIRouter()
    return _ai_router

async def smart_chat(messages: List[Dict], optimize_for: str = "balanced", **kwargs) -> Dict:
    """智能路由聊天"""
    return await get_ai_router().chat(messages, optimize_for, **kwargs)
