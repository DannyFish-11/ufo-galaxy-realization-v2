"""
LLM 提供商管理器
===============

支持多种大模型 API：
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3.5)
- Groq (Llama 3.3 70B)
- 智谱 (GLM-4)
- DeepSeek
- 本地模型 (Ollama)
- 自定义 API

支持：
- 自动故障转移
- 负载均衡
- 成本优化
- 模型切换

版本: v2.3.22
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import httpx

logger = logging.getLogger(__name__)


class LLMProvider(Enum):
    """LLM 提供商"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GROQ = "groq"
    ZHIPU = "zhipu"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    CUSTOM = "custom"


@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: LLMProvider
    model: str
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
    cost_per_1k_tokens: float = 0.0
    capabilities: List[str] = field(default_factory=list)
    
    # OpenAI 兼容
    def to_openai_format(self) -> Dict:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature
        }


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    provider: LLMProvider
    model: str
    tokens_used: int
    latency_ms: float
    cost: float
    success: bool = True
    error: str = ""


class LLMProviderManager:
    """LLM 提供商管理器"""
    
    def __init__(self):
        self.providers: Dict[LLMProvider, LLMConfig] = {}
        self.default_provider: Optional[LLMProvider] = None
        self.fallback_order: List[LLMProvider] = []
        self._load_default_providers()
    
    def _load_default_providers(self):
        """加载默认提供商配置"""
        # OpenAI
        if os.getenv("OPENAI_API_KEY"):
            self.register_provider(LLMConfig(
                provider=LLMProvider.OPENAI,
                model="gpt-4-turbo-preview",
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url="https://api.openai.com/v1",
                cost_per_1k_tokens=0.01,
                capabilities=["chat", "function_calling", "vision"]
            ))
        
        # Anthropic
        if os.getenv("ANTHROPIC_API_KEY"):
            self.register_provider(LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-5-sonnet-20241022",
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                base_url="https://api.anthropic.com/v1",
                cost_per_1k_tokens=0.003,
                capabilities=["chat", "vision", "long_context"]
            ))
        
        # Groq (最快)
        if os.getenv("GROQ_API_KEY"):
            self.register_provider(LLMConfig(
                provider=LLMProvider.GROQ,
                model="llama-3.3-70b-versatile",
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
                cost_per_1k_tokens=0.0001,
                capabilities=["chat", "fast_inference"]
            ))
        
        # 智谱 (中文好)
        if os.getenv("ZHIPU_API_KEY"):
            self.register_provider(LLMConfig(
                provider=LLMProvider.ZHIPU,
                model="glm-4",
                api_key=os.getenv("ZHIPU_API_KEY"),
                base_url="https://open.bigmodel.cn/api/paas/v4",
                cost_per_1k_tokens=0.001,
                capabilities=["chat", "chinese"]
            ))
        
        # DeepSeek
        if os.getenv("DEEPSEEK_API_KEY"):
            self.register_provider(LLMConfig(
                provider=LLMProvider.DEEPSEEK,
                model="deepseek-chat",
                api_key=os.getenv("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com/v1",
                cost_per_1k_tokens=0.0001,
                capabilities=["chat", "coding"]
            ))
        
        # Ollama (本地)
        self.register_provider(LLMConfig(
            provider=LLMProvider.OLLAMA,
            model="llama3.2",
            base_url="http://localhost:11434/v1",
            cost_per_1k_tokens=0.0,
            capabilities=["chat", "local", "private"]
        ))
        
        # 设置默认提供商和故障转移顺序
        if self.providers:
            # 优先级: Groq (快) > DeepSeek (便宜) > 智谱 (中文) > OpenAI > Anthropic > Ollama
            self.fallback_order = [
                LLMProvider.GROQ,
                LLMProvider.DEEPSEEK,
                LLMProvider.ZHIPU,
                LLMProvider.OPENAI,
                LLMProvider.ANTHROPIC,
                LLMProvider.OLLAMA
            ]
            self.fallback_order = [p for p in self.fallback_order if p in self.providers]
            if self.fallback_order:
                self.default_provider = self.fallback_order[0]
    
    def register_provider(self, config: LLMConfig):
        """注册提供商"""
        self.providers[config.provider] = config
        logger.info(f"Registered LLM provider: {config.provider.value} ({config.model})")
    
    def unregister_provider(self, provider: LLMProvider):
        """注销提供商"""
        if provider in self.providers:
            del self.providers[provider]
            if self.default_provider == provider:
                self.default_provider = self.fallback_order[0] if self.fallback_order else None
            logger.info(f"Unregistered LLM provider: {provider.value}")
    
    def get_provider(self, provider: Optional[LLMProvider] = None) -> Optional[LLMConfig]:
        """获取提供商配置"""
        if provider:
            return self.providers.get(provider)
        return self.providers.get(self.default_provider) if self.default_provider else None
    
    def list_providers(self) -> List[Dict]:
        """列出所有提供商"""
        return [
            {
                "provider": p.value,
                "model": c.model,
                "capabilities": c.capabilities,
                "cost_per_1k_tokens": c.cost_per_1k_tokens,
                "available": bool(c.api_key or p == LLMProvider.OLLAMA)
            }
            for p, c in self.providers.items()
        ]
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """发送对话请求"""
        # 选择提供商
        target_provider = provider or self.default_provider
        if not target_provider:
            return LLMResponse(
                content="",
                provider=LLMProvider.CUSTOM,
                model="",
                tokens_used=0,
                latency_ms=0,
                cost=0,
                success=False,
                error="No LLM provider available"
            )
        
        config = self.providers.get(target_provider)
        if not config:
            return LLMResponse(
                content="",
                provider=target_provider,
                model="",
                tokens_used=0,
                latency_ms=0,
                cost=0,
                success=False,
                error=f"Provider {target_provider.value} not configured"
            )
        
        # 使用指定模型或默认模型
        target_model = model or config.model
        
        # 尝试调用
        start_time = datetime.now()
        try:
            content = await self._call_api(config, messages, target_model, **kwargs)
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # 估算 token 数量
            tokens_used = len(str(messages)) // 4 + len(content) // 4
            cost = (tokens_used / 1000) * config.cost_per_1k_tokens
            
            return LLMResponse(
                content=content,
                provider=target_provider,
                model=target_model,
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                cost=cost,
                success=True
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            
            # 尝试故障转移
            for fallback in self.fallback_order:
                if fallback != target_provider and fallback in self.providers:
                    logger.info(f"Falling back to {fallback.value}")
                    try:
                        fallback_config = self.providers[fallback]
                        content = await self._call_api(fallback_config, messages, fallback_config.model, **kwargs)
                        latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                        tokens_used = len(str(messages)) // 4 + len(content) // 4
                        cost = (tokens_used / 1000) * fallback_config.cost_per_1k_tokens
                        
                        return LLMResponse(
                            content=content,
                            provider=fallback,
                            model=fallback_config.model,
                            tokens_used=tokens_used,
                            latency_ms=latency_ms,
                            cost=cost,
                            success=True
                        )
                    except Exception as e2:
                        logger.error(f"Fallback {fallback.value} also failed: {e2}")
                        continue
            
            return LLMResponse(
                content="",
                provider=target_provider,
                model=target_model,
                tokens_used=0,
                latency_ms=(datetime.now() - start_time).total_seconds() * 1000,
                cost=0,
                success=False,
                error=str(e)
            )
    
    async def _call_api(
        self,
        config: LLMConfig,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> str:
        """调用 API"""
        if config.provider == LLMProvider.ANTHROPIC:
            return await self._call_anthropic(config, messages, model, **kwargs)
        else:
            # OpenAI 兼容格式
            return await self._call_openai_compatible(config, messages, model, **kwargs)
    
    async def _call_openai_compatible(
        self,
        config: LLMConfig,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> str:
        """调用 OpenAI 兼容 API"""
        url = f"{config.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", config.max_tokens),
            "temperature": kwargs.get("temperature", config.temperature)
        }
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    
    async def _call_anthropic(
        self,
        config: LLMConfig,
        messages: List[Dict[str, str]],
        model: str,
        **kwargs
    ) -> str:
        """调用 Anthropic API"""
        url = f"{config.base_url}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": config.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        # 转换消息格式
        anthropic_messages = []
        system_prompt = ""
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        payload = {
            "model": model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", config.max_tokens),
        }
        if system_prompt:
            payload["system"] = system_prompt
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["content"][0]["text"]
    
    def set_default_provider(self, provider: LLMProvider):
        """设置默认提供商"""
        if provider in self.providers:
            self.default_provider = provider
            logger.info(f"Default provider set to: {provider.value}")
    
    def set_fallback_order(self, order: List[LLMProvider]):
        """设置故障转移顺序"""
        self.fallback_order = [p for p in order if p in self.providers]
        logger.info(f"Fallback order set: {[p.value for p in self.fallback_order]}")


# 全局实例
llm_manager = LLMProviderManager()
