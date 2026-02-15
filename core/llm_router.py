"""
Galaxy - LLM 智能路由器
支持三级优先模型、负载均衡、故障转移
"""

import os
import json
import asyncio
import logging
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import random

logger = logging.getLogger("Galaxy.LLMRouter")

# ============================================================================
# 配置
# ============================================================================

class FailoverStrategy(str, Enum):
    """故障转移策略"""
    PRIORITY = "priority"       # 按优先级
    ROUND_ROBIN = "round_robin" # 轮询
    RANDOM = "random"           # 随机
    WEIGHT = "weight"           # 按权重

@dataclass
class ModelConfig:
    """模型配置"""
    provider: str
    model: str
    api_key: str = ""
    base_url: str = ""
    weight: int = 100
    enabled: bool = True
    max_tokens: int = 4096
    temperature: float = 0.7
    
    # 统计
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    avg_latency: float = 0.0
    last_error: str = ""

@dataclass
class RouterConfig:
    """路由配置"""
    priority1: ModelConfig = None
    priority2: ModelConfig = None
    priority3: ModelConfig = None
    failover_strategy: FailoverStrategy = FailoverStrategy.PRIORITY
    retry_count: int = 3
    timeout: int = 30
    
    def __post_init__(self):
        # 从环境变量加载默认配置
        if self.priority1 is None:
            self.priority1 = ModelConfig(
                provider=os.getenv("LLM_PRIORITY1_PROVIDER", "openai"),
                model=os.getenv("LLM_PRIORITY1_MODEL", "gpt-4o"),
                api_key=os.getenv("OPENAI_API_KEY", ""),
                weight=60
            )
        if self.priority2 is None:
            self.priority2 = ModelConfig(
                provider=os.getenv("LLM_PRIORITY2_PROVIDER", "deepseek"),
                model=os.getenv("LLM_PRIORITY2_MODEL", "deepseek-chat"),
                api_key=os.getenv("DEEPSEEK_API_KEY", ""),
                base_url="https://api.deepseek.com/v1",
                weight=30
            )
        if self.priority3 is None:
            self.priority3 = ModelConfig(
                provider=os.getenv("LLM_PRIORITY3_PROVIDER", "groq"),
                model=os.getenv("LLM_PRIORITY3_MODEL", "llama-3.1-70b-versatile"),
                api_key=os.getenv("GROQ_API_KEY", ""),
                base_url="https://api.groq.com/openai/v1",
                weight=10
            )

# ============================================================================
# LLM 客户端
# ============================================================================

class LLMClient:
    """LLM 客户端"""
    
    def __init__(self, config: ModelConfig):
        self.config = config
        self.client = None
        self._init_client()
    
    def _init_client(self):
        """初始化客户端"""
        try:
            from openai import AsyncOpenAI
            
            self.client = AsyncOpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or None
            )
            logger.info(f"LLM 客户端初始化: {self.config.provider}/{self.config.model}")
        except ImportError:
            logger.warning("openai 库未安装")
    
    async def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """聊天"""
        if not self.client:
            raise Exception("客户端未初始化")
        
        start_time = time.time()
        
        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
                temperature=kwargs.get("temperature", self.config.temperature),
                timeout=kwargs.get("timeout", 30)
            )
            
            latency = time.time() - start_time
            
            # 更新统计
            self.config.total_calls += 1
            self.config.success_calls += 1
            self.config.avg_latency = (
                (self.config.avg_latency * (self.config.total_calls - 1) + latency) 
                / self.config.total_calls
            )
            
            return {
                "success": True,
                "content": response.choices[0].message.content,
                "model": self.config.model,
                "provider": self.config.provider,
                "latency": latency,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
            
        except Exception as e:
            self.config.total_calls += 1
            self.config.failed_calls += 1
            self.config.last_error = str(e)
            
            return {
                "success": False,
                "error": str(e),
                "model": self.config.model,
                "provider": self.config.provider
            }

# ============================================================================
# 智能路由器
# ============================================================================

class LLMRouter:
    """LLM 智能路由器"""
    
    def __init__(self, config: RouterConfig = None):
        self.config = config or RouterConfig()
        self.clients: Dict[str, LLMClient] = {}
        self._init_clients()
    
    def _init_clients(self):
        """初始化所有客户端"""
        for priority, model_config in [
            ("priority1", self.config.priority1),
            ("priority2", self.config.priority2),
            ("priority3", self.config.priority3)
        ]:
            if model_config and model_config.enabled and model_config.api_key:
                self.clients[priority] = LLMClient(model_config)
    
    def get_available_clients(self) -> List[tuple]:
        """获取可用客户端列表"""
        available = []
        
        for priority in ["priority1", "priority2", "priority3"]:
            if priority in self.clients:
                client = self.clients[priority]
                if client.config.enabled:
                    available.append((priority, client))
        
        return available
    
    def select_client(self, strategy: FailoverStrategy = None) -> tuple:
        """选择客户端"""
        available = self.get_available_clients()
        
        if not available:
            raise Exception("没有可用的 LLM 客户端")
        
        strategy = strategy or self.config.failover_strategy
        
        if strategy == FailoverStrategy.PRIORITY:
            return available[0]
        
        elif strategy == FailoverStrategy.ROUND_ROBIN:
            # 简单轮询
            idx = int(time.time()) % len(available)
            return available[idx]
        
        elif strategy == FailoverStrategy.RANDOM:
            return random.choice(available)
        
        elif strategy == FailoverStrategy.WEIGHT:
            # 按权重选择
            total_weight = sum(c.config.weight for _, c in available)
            r = random.randint(1, total_weight)
            
            current = 0
            for priority, client in available:
                current += client.config.weight
                if r <= current:
                    return (priority, client)
            
            return available[0]
        
        return available[0]
    
    async def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """聊天 - 带故障转移"""
        retry_count = kwargs.pop("retry_count", self.config.retry_count)
        
        errors = []
        
        for attempt in range(retry_count):
            try:
                priority, client = self.select_client()
                
                logger.info(f"尝试 {attempt + 1}/{retry_count}: {priority} ({client.config.provider}/{client.config.model})")
                
                result = await client.chat(messages, **kwargs)
                
                if result["success"]:
                    result["priority"] = priority
                    result["attempt"] = attempt + 1
                    return result
                
                errors.append({
                    "priority": priority,
                    "provider": client.config.provider,
                    "error": result.get("error", "Unknown error")
                })
                
                # 如果是 API Key 问题，禁用该客户端
                if "api_key" in result.get("error", "").lower():
                    client.config.enabled = False
                    logger.warning(f"禁用客户端 {priority}: API Key 无效")
                
            except Exception as e:
                errors.append({
                    "priority": "unknown",
                    "error": str(e)
                })
        
        # 所有尝试都失败
        return {
            "success": False,
            "error": "所有 LLM 服务都不可用",
            "errors": errors,
            "attempts": retry_count
        }
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        status = {
            "timestamp": datetime.now().isoformat(),
            "strategy": self.config.failover_strategy.value,
            "models": {}
        }
        
        for priority, client in self.clients.items():
            config = client.config
            status["models"][priority] = {
                "provider": config.provider,
                "model": config.model,
                "enabled": config.enabled,
                "weight": config.weight,
                "stats": {
                    "total_calls": config.total_calls,
                    "success_calls": config.success_calls,
                    "failed_calls": config.failed_calls,
                    "success_rate": f"{(config.success_calls / config.total_calls * 100) if config.total_calls > 0 else 0:.1f}%",
                    "avg_latency": f"{config.avg_latency:.2f}s"
                }
            }
        
        return status

# ============================================================================
# 全局实例
# ============================================================================

_router: Optional[LLMRouter] = None

def get_router() -> LLMRouter:
    """获取全局路由器"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router

async def chat(messages: List[Dict], **kwargs) -> Dict[str, Any]:
    """便捷聊天函数"""
    return await get_router().chat(messages, **kwargs)

# ============================================================================
# 测试
# ============================================================================

async def test_router():
    """测试路由器"""
    router = get_router()
    
    print("=" * 60)
    print("LLM 智能路由器测试")
    print("=" * 60)
    
    # 显示状态
    status = router.get_status()
    print(f"\n策略: {status['strategy']}")
    print("\n模型配置:")
    for priority, info in status["models"].items():
        print(f"  {priority}: {info['provider']}/{info['model']} (权重: {info['weight']})")
    
    # 测试聊天
    print("\n测试聊天...")
    result = await router.chat([
        {"role": "user", "content": "你好，请用一句话介绍自己"}
    ])
    
    if result["success"]:
        print(f"\n响应 ({result['priority']}, {result['provider']}/{result['model']}):")
        print(f"  {result['content']}")
        print(f"\n延迟: {result['latency']:.2f}s")
        print(f"Token: {result['usage']['total_tokens']}")
    else:
        print(f"\n错误: {result['error']}")

if __name__ == "__main__":
    asyncio.run(test_router())
