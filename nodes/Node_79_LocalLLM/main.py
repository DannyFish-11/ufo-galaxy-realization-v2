"""
Node 79: Local LLM
本地大语言模型服务 - 集成 Ollama

功能：
1. Ollama 模型管理（下载、删除、列表）
2. 本地推理（同步/异步）
3. 流式输出
4. Function Calling（工具调用）
5. Fallback 机制（本地失败 → 云端）

优势：
- 离线可用
- 无 API 费用
- 响应速度快 (< 1s)
- 数据隐私保护

支持的模型：
- DeepSeek-Coder-6.7B (代码任务首选)
- Qwen2.5-14B-Instruct (复杂任务)
- Qwen2.5-7B-Instruct (常规任务)
- Qwen2.5-3B-Instruct (简单任务，快速响应)
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any, AsyncIterator
from datetime import datetime
from contextlib import asynccontextmanager
from enum import Enum

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

NODE_ID = os.getenv("NODE_ID", "79")
NODE_NAME = os.getenv("NODE_NAME", "LocalLLM")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Ollama 配置
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# Fallback 配置（云端 LLM）
FALLBACK_ENABLED = os.getenv("FALLBACK_ENABLED", "true").lower() == "true"
FALLBACK_URL = os.getenv("FALLBACK_URL", "http://localhost:8001")  # Node 01 (OneAPI)

# 模型配置
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "qwen2.5:7b-instruct-q4_K_M")

# 多模型支持
MODEL_MAPPING = {
    "code": os.getenv("CODE_MODEL", "deepseek-coder:6.7b-instruct-q4_K_M"),
    "complex": os.getenv("COMPLEX_MODEL", "qwen2.5:14b-instruct-q4_K_M"),
    "normal": os.getenv("NORMAL_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
    "simple": os.getenv("SIMPLE_MODEL", "qwen2.5:3b-instruct-q4_K_M"),
}

# 任务类型关键词
TASK_KEYWORDS = {
    "code": ["code", "programming", "debug", "refactor", "function", "class", "代码", "编程", "函数"],
    "complex": ["analyze", "reasoning", "plan", "design", "architecture", "分析", "推理", "规划", "设计"],
    "simple": ["hello", "hi", "what", "who", "when", "where", "你好", "什么", "谁", "哪里"],
}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=f"[Node {NODE_ID}] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class ModelInfo(BaseModel):
    name: str
    size: Optional[int] = None
    digest: Optional[str] = None
    modified_at: Optional[str] = None

class GenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = None  # None = 自动选择
    task_type: Optional[str] = None  # code, complex, normal, simple
    system: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    stream: bool = False
    tools: Optional[List[Dict]] = None

class ChatMessage(BaseModel):
    role: str  # system, user, assistant
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None  # None = 自动选择
    task_type: Optional[str] = None  # code, complex, normal, simple
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    stream: bool = False
    tools: Optional[List[Dict]] = None

class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]

class GenerateResponse(BaseModel):
    model: str
    response: str
    done: bool
    context: Optional[List[int]] = None
    tool_calls: Optional[List[ToolCall]] = None
    total_duration: Optional[int] = None
    load_duration: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_duration: Optional[int] = None

# =============================================================================
# Ollama Client
# =============================================================================

class OllamaClient:
    """Ollama API 客户端"""
    
    def __init__(self, base_url: str = OLLAMA_URL):
        self.base_url = base_url.rstrip("/")
        self.http_client = httpx.AsyncClient(timeout=300)  # 5 分钟超时
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.http_client.get(f"{self.base_url}/")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False
    
    async def list_models(self) -> List[ModelInfo]:
        """列出所有模型"""
        try:
            response = await self.http_client.get(f"{self.base_url}/api/tags")
            
            if response.status_code == 200:
                data = response.json()
                models = []
                for model in data.get("models", []):
                    models.append(ModelInfo(
                        name=model.get("name"),
                        size=model.get("size"),
                        digest=model.get("digest"),
                        modified_at=model.get("modified_at")
                    ))
                return models
            else:
                logger.error(f"Failed to list models: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
    
    async def pull_model(self, model: str) -> bool:
        """下载模型"""
        try:
            logger.info(f"Pulling model: {model}")
            
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": model}
            ) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line:
                            data = json.loads(line)
                            status = data.get("status")
                            logger.info(f"Pull status: {status}")
                    
                    logger.info(f"Model {model} pulled successfully")
                    return True
                else:
                    logger.error(f"Failed to pull model: {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"Error pulling model: {e}")
            return False
    
    async def delete_model(self, model: str) -> bool:
        """删除模型"""
        try:
            response = await self.http_client.delete(
                f"{self.base_url}/api/delete",
                json={"name": model}
            )
            
            if response.status_code == 200:
                logger.info(f"Model {model} deleted successfully")
                return True
            else:
                logger.error(f"Failed to delete model: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error deleting model: {e}")
            return False
    
    async def generate(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: Optional[List[Dict]] = None
    ) -> GenerateResponse:
        """生成响应（同步）"""
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            if system:
                payload["system"] = system
            
            if tools:
                payload["tools"] = tools
            
            response = await self.http_client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # 解析工具调用
                tool_calls = None
                response_text = data.get("response", "")
                
                if tools and "```json" in response_text:
                    # 简单的工具调用解析
                    try:
                        json_start = response_text.find("```json") + 7
                        json_end = response_text.find("```", json_start)
                        json_str = response_text[json_start:json_end].strip()
                        tool_data = json.loads(json_str)
                        
                        if "name" in tool_data and "arguments" in tool_data:
                            tool_calls = [ToolCall(
                                name=tool_data["name"],
                                arguments=tool_data["arguments"]
                            )]
                    except Exception as e:
                        logger.warning(f"Failed to parse tool call: {e}")
                
                return GenerateResponse(
                    model=data.get("model"),
                    response=response_text,
                    done=data.get("done", True),
                    context=data.get("context"),
                    tool_calls=tool_calls,
                    total_duration=data.get("total_duration"),
                    load_duration=data.get("load_duration"),
                    prompt_eval_duration=data.get("prompt_eval_duration"),
                    eval_duration=data.get("eval_duration")
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}"
                )
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            raise
    
    async def generate_stream(
        self,
        prompt: str,
        model: str = DEFAULT_MODEL,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048
    ) -> AsyncIterator[str]:
        """生成响应（流式）"""
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            if system:
                payload["system"] = system
            
            async with self.http_client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload
            ) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if line:
                            data = json.loads(line)
                            chunk = data.get("response", "")
                            if chunk:
                                yield chunk
                else:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Ollama API error: {response.text}"
                    )
        except Exception as e:
            logger.error(f"Error streaming response: {e}")
            raise
    
    async def chat(
        self,
        messages: List[ChatMessage],
        model: str = DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        tools: Optional[List[Dict]] = None
    ) -> GenerateResponse:
        """聊天（同步）"""
        try:
            payload = {
                "model": model,
                "messages": [msg.dict() for msg in messages],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            if tools:
                payload["tools"] = tools
            
            response = await self.http_client.post(
                f"{self.base_url}/api/chat",
                json=payload
            )
            
            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})
                
                return GenerateResponse(
                    model=data.get("model"),
                    response=message.get("content", ""),
                    done=data.get("done", True),
                    total_duration=data.get("total_duration"),
                    load_duration=data.get("load_duration"),
                    prompt_eval_duration=data.get("prompt_eval_duration"),
                    eval_duration=data.get("eval_duration")
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Ollama API error: {response.text}"
                )
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            raise
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# Model Selection
# =============================================================================

def select_model_by_task(prompt: str, task_type: Optional[str] = None) -> str:
    """根据任务类型自动选择模型"""
    # 如果明确指定了 task_type
    if task_type and task_type in MODEL_MAPPING:
        return MODEL_MAPPING[task_type]
    
    # 根据 prompt 内容推断任务类型
    prompt_lower = prompt.lower()
    
    # 检查代码任务
    for keyword in TASK_KEYWORDS["code"]:
        if keyword in prompt_lower:
            logger.info(f"Detected code task, using {MODEL_MAPPING['code']}")
            return MODEL_MAPPING["code"]
    
    # 检查复杂任务
    for keyword in TASK_KEYWORDS["complex"]:
        if keyword in prompt_lower:
            logger.info(f"Detected complex task, using {MODEL_MAPPING['complex']}")
            return MODEL_MAPPING["complex"]
    
    # 检查简单任务
    for keyword in TASK_KEYWORDS["simple"]:
        if keyword in prompt_lower:
            logger.info(f"Detected simple task, using {MODEL_MAPPING['simple']}")
            return MODEL_MAPPING["simple"]
    
    # 默认使用常规模型
    logger.info(f"Using default model: {MODEL_MAPPING['normal']}")
    return MODEL_MAPPING["normal"]

# =============================================================================
# Local LLM Service
# =============================================================================

class LocalLLMService:
    """本地 LLM 服务"""
    
    def __init__(self):
        self.ollama = OllamaClient()
        self.fallback_client = httpx.AsyncClient(timeout=60) if FALLBACK_ENABLED else None
    
    async def health_check(self) -> bool:
        """健康检查"""
        return await self.ollama.health_check()
    
    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        """生成响应（带 Fallback）"""
        try:
            # 自动选择模型
            model = request.model or select_model_by_task(request.prompt, request.task_type)
            
            # 尝试本地生成
            return await self.ollama.generate(
                prompt=request.prompt,
                model=model,
                system=request.system,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools
            )
        except Exception as e:
            logger.warning(f"Local LLM failed: {e}")
            
            # Fallback 到云端
            if FALLBACK_ENABLED and self.fallback_client:
                logger.info("Falling back to cloud LLM")
                return await self.fallback_to_cloud(request)
            else:
                raise
    
    async def generate_stream(self, request: GenerateRequest) -> AsyncIterator[str]:
        """生成响应（流式，带 Fallback）"""
        try:
            # 自动选择模型
            model = request.model or select_model_by_task(request.prompt, request.task_type)
            
            async for chunk in self.ollama.generate_stream(
                prompt=request.prompt,
                model=model,
                system=request.system,
                temperature=request.temperature,
                max_tokens=request.max_tokens
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"Local LLM stream failed: {e}")
            
            # Fallback 到云端（非流式）
            if FALLBACK_ENABLED and self.fallback_client:
                logger.info("Falling back to cloud LLM (non-streaming)")
                response = await self.fallback_to_cloud(request)
                yield response.response
            else:
                raise
    
    async def chat(self, request: ChatRequest) -> GenerateResponse:
        """聊天（带 Fallback）"""
        try:
            # 自动选择模型（基于最后一条用户消息）
            last_user_message = next((msg.content for msg in reversed(request.messages) if msg.role == "user"), "")
            model = request.model or select_model_by_task(last_user_message, request.task_type)
            
            return await self.ollama.chat(
                messages=request.messages,
                model=model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools
            )
        except Exception as e:
            logger.warning(f"Local LLM chat failed: {e}")
            
            # Fallback 到云端
            if FALLBACK_ENABLED and self.fallback_client:
                logger.info("Falling back to cloud LLM")
                return await self.fallback_chat_to_cloud(request)
            else:
                raise
    
    async def fallback_to_cloud(self, request: GenerateRequest) -> GenerateResponse:
        """Fallback 到云端 LLM"""
        try:
            response = await self.fallback_client.post(
                f"{FALLBACK_URL}/generate",
                json={
                    "prompt": request.prompt,
                    "model": "gpt-3.5-turbo",  # 云端模型
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return GenerateResponse(
                    model="cloud-fallback",
                    response=data.get("response", ""),
                    done=True
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Cloud fallback failed"
                )
        except Exception as e:
            logger.error(f"Cloud fallback error: {e}")
            raise
    
    async def fallback_chat_to_cloud(self, request: ChatRequest) -> GenerateResponse:
        """Fallback 聊天到云端 LLM"""
        try:
            response = await self.fallback_client.post(
                f"{FALLBACK_URL}/chat",
                json={
                    "messages": [msg.dict() for msg in request.messages],
                    "model": "gpt-3.5-turbo",
                    "temperature": request.temperature,
                    "max_tokens": request.max_tokens
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                return GenerateResponse(
                    model="cloud-fallback",
                    response=data.get("response", ""),
                    done=True
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Cloud fallback failed"
                )
        except Exception as e:
            logger.error(f"Cloud fallback error: {e}")
            raise
    
    async def close(self):
        """关闭服务"""
        await self.ollama.close()
        if self.fallback_client:
            await self.fallback_client.aclose()

# =============================================================================
# FastAPI Application
# =============================================================================

llm_service = LocalLLMService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting Node 79: Local LLM")
    
    # 健康检查
    if await llm_service.health_check():
        logger.info("Ollama is healthy")
    else:
        logger.warning("Ollama is not available, fallback mode only")
    
    yield
    
    # 清理资源
    await llm_service.close()
    logger.info("Node 79 shutdown complete")

app = FastAPI(
    title="Node 79: Local LLM",
    description="本地大语言模型服务 - 集成 Ollama",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "Node 79: Local LLM",
        "status": "running",
        "ollama_url": OLLAMA_URL,
        "fallback_enabled": FALLBACK_ENABLED,
        "default_model": DEFAULT_MODEL,
        "model_mapping": MODEL_MAPPING,
        "supported_task_types": list(MODEL_MAPPING.keys())
    }

@app.get("/health")
async def health():
    healthy = await llm_service.health_check()
    return {
        "status": "healthy" if healthy else "degraded",
        "ollama_available": healthy,
        "fallback_available": FALLBACK_ENABLED,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/models")
async def list_models():
    """列出所有可用模型"""
    models = await llm_service.ollama.list_models()
    return {
        "models": [model.dict() for model in models],
        "count": len(models)
    }

@app.post("/models/pull")
async def pull_model(model: str):
    """下载模型"""
    success = await llm_service.ollama.pull_model(model)
    
    if success:
        return {"success": True, "model": model}
    else:
        raise HTTPException(status_code=500, detail="Failed to pull model")

@app.delete("/models/{model}")
async def delete_model(model: str):
    """删除模型"""
    success = await llm_service.ollama.delete_model(model)
    
    if success:
        return {"success": True, "model": model}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete model")

@app.post("/generate")
async def generate(request: GenerateRequest):
    """生成响应"""
    if request.stream:
        async def stream_generator():
            async for chunk in llm_service.generate_stream(request):
                yield f"data: {json.dumps({'chunk': chunk})}\n\n"
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream"
        )
    else:
        response = await llm_service.generate(request)
        return response

@app.post("/chat")
async def chat(request: ChatRequest):
    """聊天"""
    response = await llm_service.chat(request)
    return response

# =============================================================================
# OpenAI Compatible API (for One-API integration)
# =============================================================================

class OpenAIMessage(BaseModel):
    role: str
    content: str

class OpenAIRequest(BaseModel):
    model: str = DEFAULT_MODEL
    messages: List[OpenAIMessage]
    max_tokens: Optional[int] = 2048
    temperature: Optional[float] = 0.7
    stream: Optional[bool] = False

@app.post("/v1/chat/completions")
async def openai_chat_completions(request: OpenAIRequest):
    """
    OpenAI 兼容 API - 用于 One-API 集成
    
    完全兼容 OpenAI Chat Completions API 格式
    使 One-API 可以直接调用本地 LLM
    """
    try:
        import time
        
        # 转换消息格式
        chat_messages = [
            ChatMessage(role=msg.role, content=msg.content)
            for msg in request.messages
        ]
        
        # 创建 ChatRequest
        chat_request = ChatRequest(
            messages=chat_messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=False
        )
        
        # 调用本地 LLM
        result = await llm_service.chat(chat_request)
        
        # 返回 OpenAI 格式响应
        return {
            "id": f"chatcmpl-local-{int(time.time())}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": result.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": result.response
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 0,  # Ollama 不返回 token 计数
                "completion_tokens": 0,
                "total_tokens": 0
            },
            "system_fingerprint": "local-llm"
        }
    
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/v1/models")
async def openai_list_models():
    """
    OpenAI 兼容 API - 列出可用模型
    """
    import time
    
    models = await llm_service.ollama.list_models()
    
    return {
        "object": "list",
        "data": [
            {
                "id": model.name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "local",
                "permission": [],
                "root": model.name,
                "parent": None
            }
            for model in models
        ]
    }

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8079)
