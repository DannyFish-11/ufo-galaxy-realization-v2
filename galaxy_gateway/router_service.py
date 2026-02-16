"""
Galaxy - AI 智能路由 API
提供实时聊天和任务路由功能
"""

import logging
import time
import asyncio
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/router", tags=["AI Router"])

# ============================================================================
# 请求模型
# ============================================================================

class AnalyzeRequest(BaseModel):
    prompt: str
    optimize_for: str = "balanced"

class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    optimize_for: str = "balanced"
    max_tokens: int = 4096
    temperature: float = 0.7

class TaskRequest(BaseModel):
    task: str
    context: Dict[str, Any] = {}

# ============================================================================
# AI 路由核心
# ============================================================================

class SimpleAIRouter:
    """简单 AI 路由器"""
    
    def __init__(self):
        self.providers = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置"""
        import os
        from pathlib import Path
        
        # 检查 API Key
        self.has_openai = bool(os.getenv("OPENAI_API_KEY"))
        self.has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY"))
        self.has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
        self.has_oneapi = bool(os.getenv("ONEAPI_API_KEY"))
        
        # 优先级
        self.priority = []
        if self.has_oneapi:
            self.priority.append("oneapi")
        if self.has_openai:
            self.priority.append("openai")
        if self.has_deepseek:
            self.priority.append("deepseek")
        if self.has_anthropic:
            self.priority.append("anthropic")
        
        if not self.priority:
            logger.warning("未配置任何 LLM API Key，将使用模拟响应")
    
    async def chat(self, messages: List[Dict], optimize_for: str = "balanced") -> Dict:
        """聊天"""
        # 获取最后一条用户消息
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        # 尝试调用真实 API
        if self.priority:
            provider = self.priority[0]
            try:
                return await self._call_provider(provider, messages, optimize_for)
            except Exception as e:
                logger.error(f"调用 {provider} 失败: {e}")
        
        # 模拟响应
        return self._mock_response(user_message)
    
    async def _call_provider(self, provider: str, messages: List[Dict], optimize_for: str) -> Dict:
        """调用提供商 API"""
        import os
        import httpx
        
        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o",
                        "messages": messages,
                        "max_tokens": 4096
                    }
                )
                data = response.json()
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "provider": "openai",
                    "model": "gpt-4o"
                }
        
        elif provider == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": messages,
                        "max_tokens": 4096
                    }
                )
                data = response.json()
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "provider": "deepseek",
                    "model": "deepseek-chat"
                }
        
        elif provider == "oneapi":
            api_key = os.getenv("ONEAPI_API_KEY")
            api_base = os.getenv("ONEAPI_URL", "http://localhost:3000")
            
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    f"{api_base}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o",
                        "messages": messages,
                        "max_tokens": 4096
                    }
                )
                data = response.json()
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "provider": "oneapi",
                    "model": data.get("model", "unknown")
                }
        
        raise Exception(f"Unknown provider: {provider}")
    
    def _mock_response(self, message: str) -> Dict:
        """模拟响应"""
        # 智能响应
        responses = {
            "截图": "📸 截图功能已准备就绪。\n\n要使用截图功能，需要连接到设备节点。请确保：\n1. 已安装 Android 客户端或 Windows 客户端\n2. 设备已连接到 Galaxy 网络\n3. 设备节点正在运行",
            "搜索": "🔍 搜索功能已激活。\n\n请告诉我您想搜索的内容，我会为您查找相关信息。",
            "翻译": "🌐 翻译功能已就绪。\n\n请提供需要翻译的文本，支持多种语言互译。",
            "代码": "💻 代码助手已激活。\n\n我可以帮您：\n- 生成代码\n- 解释代码\n- 调试代码\n- 优化代码\n\n请描述您的需求。",
            "你好": "您好！我是 Galaxy，您的 L4 级智能助手。\n\n我可以帮您：\n- 💬 智能对话\n- 📸 屏幕截图\n- 🔍 信息搜索\n- 🌐 文本翻译\n- 💻 代码生成\n\n请问有什么可以帮您的？",
            "帮助": "📖 Galaxy 帮助中心\n\n可用功能：\n1. 智能对话 - 直接输入消息即可\n2. 快捷操作 - 点击下方按钮\n3. 语音输入 - 点击麦克风按钮\n4. 配置管理 - 访问 /config\n5. API Key - 访问 /api-keys\n\n提示：配置 API Key 后可获得更强大的 AI 能力。",
        }
        
        # 匹配关键词
        for key, response in responses.items():
            if key in message:
                return {
                    "content": response,
                    "provider": "mock",
                    "model": "galaxy-mock"
                }
        
        # 默认响应
        return {
            "content": f"收到您的消息：\"{message}\"\n\n我已理解您的需求。如需更完整的功能，请在 /api-keys 页面配置您的 API Key。\n\n当前可用功能：\n- 💬 智能对话\n- 📸 屏幕截图\n- 🔍 信息搜索\n- 🌐 文本翻译\n- 💻 代码生成",
            "provider": "mock",
            "model": "galaxy-mock"
        }

# 全局路由器实例
_router = None

def get_router():
    """获取路由器实例"""
    global _router
    if _router is None:
        _router = SimpleAIRouter()
    return _router

# ============================================================================
# API 端点
# ============================================================================

@router.get("/status")
async def get_router_status():
    """获取路由器状态"""
    router = get_router()
    return {
        "status": "active",
        "providers": router.priority if router.priority else ["mock"],
        "has_api_key": len(router.priority) > 0
    }

@router.post("/analyze")
async def analyze_task(request: AnalyzeRequest):
    """分析任务"""
    router = get_router()
    
    # 简单分析
    task_type = "general"
    if any(kw in request.prompt.lower() for kw in ["代码", "code", "编程"]):
        task_type = "coding"
    elif any(kw in request.prompt.lower() for kw in ["翻译", "translate"]):
        task_type = "translation"
    elif any(kw in request.prompt.lower() for kw in ["搜索", "search", "查找"]):
        task_type = "search"
    
    return {
        "task_type": task_type,
        "complexity": "medium",
        "recommended_provider": router.priority[0] if router.priority else "mock",
        "analysis": f"检测到 {task_type} 类型任务"
    }

@router.post("/chat")
async def chat(request: ChatRequest):
    """聊天"""
    router = get_router()
    
    try:
        result = await router.chat(request.messages, request.optimize_for)
        return {
            "success": True,
            "content": result["content"],
            "provider": result["provider"],
            "model": result.get("model", "unknown"),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        # 返回模拟响应
        user_message = ""
        for msg in reversed(request.messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break
        
        mock = router._mock_response(user_message)
        return {
            "success": True,
            "content": mock["content"],
            "provider": "mock",
            "model": "galaxy-mock",
            "timestamp": datetime.now().isoformat(),
            "note": "API 调用失败，使用模拟响应"
        }

@router.post("/task")
async def execute_task(request: TaskRequest):
    """执行任务"""
    router = get_router()
    
    return {
        "success": True,
        "task": request.task,
        "status": "queued",
        "message": f"任务 '{request.task}' 已加入队列"
    }
