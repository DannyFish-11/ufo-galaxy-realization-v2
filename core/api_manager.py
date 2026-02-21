"""
Galaxy API 管理器
=================

统一管理所有 API 配置
支持双并行策略: OneAPI 聚合器 + 其他单独模型
支持工具类 API
支持环境变量同步

版本: v1.1
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("APIManager")


@dataclass
class ModelConfig:
    """模型配置"""
    provider: str
    model_id: str
    model_name: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True
    env_key: str = ""


@dataclass
class ToolConfig:
    """工具配置"""
    tool_id: str
    name: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True
    description: str = ""
    node: str = ""
    env_key: str = ""


@dataclass
class NodeConfig:
    """节点配置"""
    node_id: str
    name: str
    port: int
    status: str = "configured"
    endpoint: str = ""


class APIManager:
    """
    API 管理器
    
    统一管理所有 API 配置
    支持双并行策略
    支持工具类 API
    支持环境变量同步
    """
    
    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "api_config.json"
            )
        
        self.config_path = config_path
        self.config: Dict[str, Any] = {}
        self.models: Dict[str, ModelConfig] = {}
        self.tools: Dict[str, ToolConfig] = {}
        self.nodes: Dict[str, NodeConfig] = {}
        
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                logger.info(f"已加载配置: {self.config_path}")
                self._parse_config()
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self._init_default_config()
        else:
            self._init_default_config()
    
    def _init_default_config(self):
        """初始化默认配置"""
        self.config = {
            "oneapi": {"enabled": True, "api_key": "", "base_url": "http://localhost:8001/v1"},
            "direct_models": {},
            "tools": {},
            "nodes": {}
        }
        logger.info("使用默认配置")
    
    def _parse_config(self):
        """解析配置"""
        # 解析 OneAPI 模型
        oneapi = self.config.get("oneapi", {})
        if oneapi.get("enabled"):
            for model in oneapi.get("models", []):
                key = f"oneapi:{model['id']}"
                self.models[key] = ModelConfig(
                    provider="oneapi",
                    model_id=model["id"],
                    model_name=model["name"],
                    api_key=oneapi.get("api_key", ""),
                    base_url=oneapi.get("base_url", ""),
                    enabled=True
                )
        
        # 解析直接模型
        direct_models = self.config.get("direct_models", {})
        for provider, config in direct_models.items():
            if config.get("enabled"):
                for model_id in config.get("models", []):
                    key = f"{provider}:{model_id}"
                    self.models[key] = ModelConfig(
                        provider=provider,
                        model_id=model_id,
                        model_name=model_id,
                        api_key=config.get("api_key", ""),
                        base_url=config.get("base_url", ""),
                        enabled=True,
                        env_key=config.get("env_key", f"{provider.upper()}_API_KEY")
                    )
        
        # 解析工具
        tools = self.config.get("tools", {})
        for tool_id, config in tools.items():
            self.tools[tool_id] = ToolConfig(
                tool_id=tool_id,
                name=config.get("description", tool_id),
                api_key=config.get("api_key", ""),
                base_url=config.get("base_url", ""),
                enabled=config.get("enabled", True),
                description=config.get("description", ""),
                node=config.get("node", ""),
                env_key=config.get("env_key", f"{tool_id.upper()}_API_KEY")
            )
        
        # 解析节点
        nodes = self.config.get("nodes", {}).get("registry", {})
        base_url = self.config.get("nodes", {}).get("base_url", "http://localhost")
        
        for node_id, config in nodes.items():
            self.nodes[node_id] = NodeConfig(
                node_id=node_id,
                name=config.get("name", f"Node_{node_id}"),
                port=config.get("port", 8000),
                status=config.get("status", "configured"),
                endpoint=f"{base_url}:{config.get('port', 8000)}"
            )
        
        logger.info(f"已解析 {len(self.models)} 个模型, {len(self.tools)} 个工具, {len(self.nodes)} 个节点")
    
    # =========================================================================
    # 环境变量同步 - 关键功能
    # =========================================================================
    
    def sync_to_env(self) -> Dict[str, bool]:
        """
        将配置同步到环境变量
        
        这是关键功能，确保节点能读取到 API Key
        """
        results = {}
        
        # 同步 OneAPI
        oneapi = self.config.get("oneapi", {})
        if oneapi.get("api_key"):
            os.environ["ONEAPI_API_KEY"] = oneapi["api_key"]
            results["ONEAPI_API_KEY"] = True
            logger.info("已同步 ONEAPI_API_KEY 到环境变量")
        
        # 同步直接模型
        direct_models = self.config.get("direct_models", {})
        for provider, config in direct_models.items():
            if config.get("api_key"):
                env_key = config.get("env_key", f"{provider.upper()}_API_KEY")
                os.environ[env_key] = config["api_key"]
                results[env_key] = True
                logger.info(f"已同步 {env_key} 到环境变量")
        
        # 同步工具
        tools = self.config.get("tools", {})
        for tool_id, config in tools.items():
            if config.get("api_key"):
                env_key = config.get("env_key", f"{tool_id.upper()}_API_KEY")
                os.environ[env_key] = config["api_key"]
                results[env_key] = True
                logger.info(f"已同步 {env_key} 到环境变量")
        
        return results
    
    def sync_from_env(self) -> Dict[str, str]:
        """
        从环境变量同步到配置
        
        用于首次启动时读取已有的环境变量
        """
        synced = {}
        
        # 同步直接模型
        direct_models = self.config.get("direct_models", {})
        for provider, config in direct_models.items():
            env_key = config.get("env_key", f"{provider.upper()}_API_KEY")
            env_value = os.environ.get(env_key, "")
            if env_value:
                config["api_key"] = env_value
                synced[env_key] = "已同步"
        
        # 同步工具
        tools = self.config.get("tools", {})
        for tool_id, config in tools.items():
            env_key = config.get("env_key", f"{tool_id.upper()}_API_KEY")
            env_value = os.environ.get(env_key, "")
            if env_value:
                config["api_key"] = env_value
                synced[env_key] = "已同步"
        
        if synced:
            self._save_config()
            logger.info(f"从环境变量同步了 {len(synced)} 个配置")
        
        return synced
    
    # =========================================================================
    # 配置管理
    # =========================================================================
    
    def get_config(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self.config
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """更新配置"""
        try:
            self.config = new_config
            self._parse_config()
            self._save_config()
            # 自动同步到环境变量
            self.sync_to_env()
            return True
        except Exception as e:
            logger.error(f"更新配置失败: {e}")
            return False
    
    def _save_config(self):
        """保存配置"""
        try:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info(f"配置已保存: {self.config_path}")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
    # =========================================================================
    # API Key 管理
    # =========================================================================
    
    def set_api_key(self, category: str, key_name: str, api_key: str) -> bool:
        """
        设置 API Key
        
        category: "oneapi", "direct_models", "tools"
        key_name: 具体的提供商或工具名称
        """
        try:
            if category == "oneapi":
                self.config.setdefault("oneapi", {})["api_key"] = api_key
            elif category == "direct_models":
                self.config.setdefault("direct_models", {}).setdefault(key_name, {})["api_key"] = api_key
            elif category == "tools":
                self.config.setdefault("tools", {}).setdefault(key_name, {})["api_key"] = api_key
            
            self._save_config()
            self._parse_config()
            # 同步到环境变量
            self.sync_to_env()
            return True
        except Exception as e:
            logger.error(f"设置 API Key 失败: {e}")
            return False
    
    def get_api_key(self, category: str, key_name: str) -> str:
        """获取 API Key"""
        if category == "oneapi":
            return self.config.get("oneapi", {}).get("api_key", "")
        elif category == "direct_models":
            return self.config.get("direct_models", {}).get(key_name, {}).get("api_key", "")
        elif category == "tools":
            return self.config.get("tools", {}).get(key_name, {}).get("api_key", "")
        return ""
    
    # =========================================================================
    # 模型管理
    # =========================================================================
    
    def get_models(self) -> List[Dict[str, Any]]:
        """获取所有模型"""
        return [
            {
                "key": key,
                "provider": model.provider,
                "model_id": model.model_id,
                "model_name": model.model_name,
                "enabled": model.enabled,
                "configured": bool(model.api_key),
                "env_key": model.env_key
            }
            for key, model in self.models.items()
        ]
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """获取已配置的可用模型"""
        return [
            {
                "key": key,
                "provider": model.provider,
                "model_id": model.model_id,
                "model_name": model.model_name
            }
            for key, model in self.models.items()
            if model.enabled and model.api_key
        ]
    
    # =========================================================================
    # 工具管理
    # =========================================================================
    
    def get_tools(self) -> List[Dict[str, Any]]:
        """获取所有工具"""
        return [
            {
                "tool_id": tool.tool_id,
                "name": tool.name,
                "enabled": tool.enabled,
                "configured": bool(tool.api_key),
                "description": tool.description,
                "node": tool.node,
                "env_key": tool.env_key
            }
            for tool in self.tools.values()
        ]
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取已配置的可用工具"""
        return [
            {
                "tool_id": tool.tool_id,
                "name": tool.name,
                "node": tool.node
            }
            for tool in self.tools.values()
            if tool.enabled and tool.api_key
        ]
    
    # =========================================================================
    # 节点管理
    # =========================================================================
    
    def get_nodes(self) -> List[Dict[str, Any]]:
        """获取所有节点"""
        return [
            {
                "node_id": node.node_id,
                "name": node.name,
                "port": node.port,
                "status": node.status,
                "endpoint": node.endpoint
            }
            for node in self.nodes.values()
        ]
    
    async def check_node_health(self, node_id: str) -> Dict[str, Any]:
        """检查节点健康状态"""
        node = self.nodes.get(node_id)
        if not node:
            return {"success": False, "error": "Node not found"}
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{node.endpoint}/health")
                if response.status_code == 200:
                    return {"success": True, "status": "healthy"}
                return {"success": False, "status": "unhealthy"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def check_all_nodes(self) -> Dict[str, Any]:
        """检查所有节点"""
        results = {}
        tasks = [self.check_node_health(node_id) for node_id in self.nodes.keys()]
        health_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for node_id, result in zip(self.nodes.keys(), health_results):
            if isinstance(result, Exception):
                results[node_id] = {"success": False, "error": str(result)}
            else:
                results[node_id] = result
        
        return results
    
    # =========================================================================
    # LLM 调用
    # =========================================================================
    
    async def call_llm(
        self,
        messages: List[Dict[str, str]],
        model: str = "auto",
        max_tokens: int = 1000
    ) -> Dict[str, Any]:
        """调用 LLM"""
        available = self.get_available_models()
        if not available:
            return {"success": False, "error": "No models configured"}
        
        available.sort(key=lambda x: 0 if x["provider"] == "oneapi" else 1)
        
        for model_info in available:
            result = await self._call_model(model_info, messages, max_tokens)
            if result.get("success"):
                return result
        
        return {"success": False, "error": "All models failed"}
    
    async def _call_model(
        self,
        model_info: Dict[str, Any],
        messages: List[Dict[str, str]],
        max_tokens: int
    ) -> Dict[str, Any]:
        """调用单个模型"""
        model_key = model_info["key"]
        model_config = self.models.get(model_key)
        
        if not model_config or not model_config.api_key:
            return {"success": False, "error": "Model not configured"}
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{model_config.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {model_config.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model_config.model_id,
                        "messages": messages,
                        "max_tokens": max_tokens
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "success": True,
                        "provider": model_config.provider,
                        "model": model_config.model_id,
                        "content": data["choices"][0]["message"]["content"],
                        "usage": data.get("usage", {})
                    }
                
                return {"success": False, "error": f"HTTP {response.status_code}"}
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # API 验证 - 关键功能
    # =========================================================================
    
    async def validate_api_key(self, category: str, key_name: str) -> Dict[str, Any]:
        """
        验证 API Key 是否有效
        
        这是关键功能，确保 API Key 真的能用
        """
        api_key = self.get_api_key(category, key_name)
        
        if not api_key:
            return {"valid": False, "error": "API Key not configured"}
        
        # 根据不同的 API 进行验证
        if category == "direct_models":
            return await self._validate_llm_api(key_name, api_key)
        elif category == "tools":
            return await self._validate_tool_api(key_name, api_key)
        elif category == "oneapi":
            return await self._validate_oneapi(api_key)
        
        return {"valid": False, "error": "Unknown category"}
    
    async def _validate_llm_api(self, provider: str, api_key: str) -> Dict[str, Any]:
        """验证 LLM API"""
        endpoints = {
            "openai": ("https://api.openai.com/v1/chat/completions", "gpt-3.5-turbo"),
            "anthropic": ("https://api.anthropic.com/v1/messages", "claude-3-haiku-20240307"),
            "deepseek": ("https://api.deepseek.com/v1/chat/completions", "deepseek-chat"),
            "zhipu": ("https://open.bigmodel.cn/api/paas/v4/chat/completions", "glm-4-flash"),
            "groq": ("https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant"),
            "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "openai/gpt-3.5-turbo"),
            "gemini": ("https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent", None)
        }
        
        if provider not in endpoints:
            return {"valid": False, "error": f"Unknown provider: {provider}"}
        
        url, model = endpoints[provider]
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if provider == "gemini":
                    # Gemini 使用不同的 API 格式
                    response = await client.post(
                        f"{url}?key={api_key}",
                        json={"contents": [{"parts": [{"text": "Hi"}]}]}
                    )
                elif provider == "anthropic":
                    response = await client.post(
                        url,
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model,
                            "max_tokens": 10,
                            "messages": [{"role": "user", "content": "Hi"}]
                        }
                    )
                else:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": "Hi"}],
                            "max_tokens": 10
                        }
                    )
                
                if response.status_code == 200:
                    return {"valid": True, "message": "API Key 有效"}
                elif response.status_code == 401:
                    return {"valid": False, "error": "API Key 无效"}
                else:
                    return {"valid": False, "error": f"HTTP {response.status_code}"}
        
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    async def _validate_tool_api(self, tool_id: str, api_key: str) -> Dict[str, Any]:
        """验证工具 API"""
        if tool_id == "brave_search":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.search.brave.com/res/v1/web/search",
                        headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                        params={"q": "test", "count": 1}
                    )
                    if response.status_code == 200:
                        return {"valid": True, "message": "Brave API Key 有效"}
                    return {"valid": False, "error": f"HTTP {response.status_code}"}
            except Exception as e:
                return {"valid": False, "error": str(e)}
        
        elif tool_id == "openweather":
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.openweathermap.org/data/2.5/weather",
                        params={"q": "London", "appid": api_key}
                    )
                    if response.status_code == 200:
                        return {"valid": True, "message": "OpenWeather API Key 有效"}
                    return {"valid": False, "error": f"HTTP {response.status_code}"}
            except Exception as e:
                return {"valid": False, "error": str(e)}
        
        return {"valid": False, "error": f"Unknown tool: {tool_id}"}
    
    async def _validate_oneapi(self, api_key: str) -> Dict[str, Any]:
        """验证 OneAPI"""
        base_url = self.config.get("oneapi", {}).get("base_url", "http://localhost:8001/v1")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if response.status_code == 200:
                    return {"valid": True, "message": "OneAPI 连接成功"}
                return {"valid": False, "error": f"HTTP {response.status_code}"}
        except Exception as e:
            return {"valid": False, "error": str(e)}
    
    # =========================================================================
    # 状态
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        available_models = self.get_available_models()
        available_tools = self.get_available_tools()
        
        return {
            "total_models": len(self.models),
            "configured_models": len(available_models),
            "total_tools": len(self.tools),
            "configured_tools": len(available_tools),
            "total_nodes": len(self.nodes),
            "oneapi_enabled": self.config.get("oneapi", {}).get("enabled", False),
            "oneapi_configured": bool(self.config.get("oneapi", {}).get("api_key")),
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
api_manager = APIManager()
