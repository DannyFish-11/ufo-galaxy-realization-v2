"""
Node_114_OpenCode - FastAPI Server
OpenCode 专用节点服务器
"""

import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import uvicorn

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.opencode_engine import OpenCodeEngine, ModelProvider
from nodes.common.cors_config import get_cors_origins

# ========== 配置 ==========
NODE_PORT = int(os.getenv("NODE_114_PORT", "9103"))
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="Node_114_OpenCode",
    description="OpenCode 专用节点 - AI 驱动的代码生成",
    version="0.1.0"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 全局引擎实例 ==========
engine = OpenCodeEngine()

# ========== Pydantic 模型 ==========

class GenerateCodeRequest(BaseModel):
    """生成代码请求"""
    prompt: str = Field(..., description="代码生成提示")
    language: Optional[str] = Field(None, description="目标语言（python/javascript/java等）")
    model: Optional[str] = Field(None, description="指定模型（可选）")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="上下文信息")

class ConfigureRequest(BaseModel):
    """配置请求"""
    model: Optional[str] = Field(None, description="模型名称")
    provider: Optional[str] = Field(None, description="提供商（openai/anthropic/deepseek等）")
    api_key: Optional[str] = Field(None, description="API Key")
    temperature: Optional[float] = Field(None, description="温度参数（0-1）")

# ========== API 端点 ==========

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_114_OpenCode",
        "status": "running",
        "version": "0.1.0",
        "description": "OpenCode 专用节点 - AI 驱动的代码生成"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    status = engine.get_status()
    return {
        "status": "healthy" if status["installed"] else "not_installed",
        "installed": status["installed"],
        "generation_count": status["generation_count"]
    }

@app.post("/api/v1/generate_code", response_model=Dict[str, Any])
async def generate_code(request: GenerateCodeRequest):
    """
    生成代码
    
    Args:
        request: 生成代码请求
        
    Returns:
        Dict: 生成结果
    """
    try:
        result = engine.generate_code(
            prompt=request.prompt,
            language=request.language,
            model=request.model,
            context=request.context
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/configure", response_model=Dict[str, Any])
async def configure(request: ConfigureRequest):
    """
    配置 OpenCode
    
    Args:
        request: 配置请求
        
    Returns:
        Dict: 配置结果
    """
    try:
        result = engine.configure(
            model=request.model,
            provider=request.provider,
            api_key=request.api_key,
            temperature=request.temperature
        )
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Configuration failed"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/install", response_model=Dict[str, Any])
async def install():
    """
    安装 OpenCode
    
    Returns:
        Dict: 安装结果
    """
    try:
        result = engine.install()
        
        if not result["success"]:
            raise HTTPException(status_code=500, detail=result.get("error", "Installation failed"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/status", response_model=Dict[str, Any])
async def get_status():
    """
    获取状态
    
    Returns:
        Dict: 状态信息
    """
    try:
        return engine.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/supported_models", response_model=Dict[str, List[str]])
async def get_supported_models():
    """
    获取支持的模型列表
    
    Returns:
        Dict: 提供商 -> 模型列表
    """
    try:
        return engine.get_supported_models()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/generation_history", response_model=List[Dict[str, Any]])
async def get_generation_history(limit: int = 100):
    """
    获取生成历史
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 生成历史
    """
    try:
        history = engine.generation_history[-limit:]
        return [r.to_dict() for r in history]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 主函数 ==========

if __name__ == "__main__":
    print(f"🚀 Starting Node_114_OpenCode on {NODE_HOST}:{NODE_PORT}")
    print(f"📚 API Documentation: http://{NODE_HOST}:{NODE_PORT}/docs")
    
    uvicorn.run(
        app,
        host=NODE_HOST,
        port=NODE_PORT,
        log_level="info"
    )
