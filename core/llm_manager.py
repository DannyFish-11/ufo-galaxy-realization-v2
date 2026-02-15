import os
import json
import logging
import asyncio
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel
from datetime import datetime

# 假设使用 OpenAI SDK 兼容接口
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None

logger = logging.getLogger("llm_manager")

class ModelConfig(BaseModel):
    provider: str = "oneapi" # 默认为 oneapi
    model_name: str
    api_key: Optional[str] = None # 如果使用 OneAPI，通常统一配置
    base_url: Optional[str] = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    temperature: float = 0.7

class TokenUsage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_cost: float
    timestamp: str

class LLMManager:
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.oneapi_client = None
        self.oneapi_config = None
        self.usage_log: List[TokenUsage] = []
        self.default_model = "gpt-4o"
        self._load_config()

    def _load_config(self):
        """加载配置，优先支持 OneAPI"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    config = json.load(f)
                    
                    # OneAPI 配置
                    oneapi_base = config.get("oneapi_base_url")
                    oneapi_key = config.get("oneapi_key")
                    
                    if oneapi_base and oneapi_key and AsyncOpenAI:
                        self.oneapi_client = AsyncOpenAI(
                            api_key=oneapi_key,
                            base_url=oneapi_base
                        )
                        self.oneapi_config = {
                            "base_url": oneapi_base,
                            "api_key": oneapi_key
                        }
                        logger.info(f"OneAPI 聚合层已激活: {oneapi_base}")
                    
                    self.default_model = config.get("default_llm_model", "gpt-4o")
                    
            except Exception as e:
                logger.error(f"加载 LLM 配置失败: {e}")

    def get_client(self) -> Any:
        """获取 OneAPI 客户端"""
        if self.oneapi_client:
            return self.oneapi_client
        else:
            raise ValueError("OneAPI 未配置，请在 config.json 中设置 oneapi_base_url 和 oneapi_key")

    async def chat_completion(self, messages: List[Dict], tools: List[Dict] = None, model_alias: str = None, **kwargs) -> Any:
        """统一的 Chat Completion 接口，通过 OneAPI 路由"""
        client = self.get_client()
        target_model = model_alias or self.default_model
        
        try:
            start_time = datetime.now()
            # 直接透传 model_alias 给 OneAPI，由 OneAPI 负责路由
            response = await client.chat.completions.create(
                model=target_model,
                messages=messages,
                tools=tools,
                **kwargs
            )
            
            # Token 审计 (OneAPI 通常不返回精确成本，这里仅记录 Token 数)
            if response.usage:
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
                # 成本估算暂时置为 0，因为 OneAPI 费率复杂，建议在 OneAPI 后台查看
                cost = 0.0 
                
                usage_record = TokenUsage(
                    model=target_model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_cost=cost,
                    timestamp=start_time.isoformat()
                )
                self.usage_log.append(usage_record)
                logger.info(f"LLM 调用完成: {target_model}, Tokens: {input_tokens}/{output_tokens}")
                
            return response
            
        except Exception as e:
            logger.error(f"LLM 调用失败 ({target_model}): {e}")
            raise

    def get_usage_summary(self) -> Dict[str, Any]:
        """获取 Token 使用统计"""
        total_cost = sum(u.total_cost for u in self.usage_log)
        by_model = {}
        for u in self.usage_log:
            if u.model not in by_model:
                by_model[u.model] = {"input": 0, "output": 0, "cost": 0.0}
            by_model[u.model]["input"] += u.input_tokens
            by_model[u.model]["output"] += u.output_tokens
            by_model[u.model]["cost"] += u.total_cost
            
        return {
            "total_cost": total_cost,
            "by_model": by_model,
            "history_count": len(self.usage_log)
        }
