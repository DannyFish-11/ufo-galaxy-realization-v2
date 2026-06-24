"""
Node_113_ExternalToolWrapper - FastAPI Server
通用工具包装器节点服务器
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

from nodes.common.cors_config import get_cors_origins
from core.tool_wrapper_engine import (
    ToolWrapperEngine,
    ToolType,
    InstallMethod
)

# ========== 配置 ==========
NODE_PORT = int(os.getenv("NODE_113_PORT", "9102"))
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="Node_113_ExternalToolWrapper",
    description="通用工具包装器 - 动态学习和使用任何 CLI 工具",
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
engine = ToolWrapperEngine()

# ========== Pydantic 模型 ==========

class UseToolRequest(BaseModel):
    """使用工具请求"""
    tool_name: str = Field(..., description="工具名称")
    task_description: str = Field(..., description="任务描述")
    context: Optional[Dict[str, Any]] = Field(default_factory=dict, description="上下文信息")

class LearnToolRequest(BaseModel):
    """学习工具请求"""
    tool_name: str = Field(..., description="工具名称")
    tool_type: str = Field(..., description="工具类型: cli/api/library/gui")
    description: str = Field(..., description="工具描述")
    install_command: str = Field(..., description="安装命令")
    examples: Optional[List[str]] = Field(default_factory=list, description="使用示例")

class DiscoverToolRequest(BaseModel):
    """发现工具请求"""
    tool_name: str = Field(..., description="工具名称")

class ForgetToolRequest(BaseModel):
    """忘记工具请求"""
    tool_name: str = Field(..., description="工具名称")

# ========== API 端点 ==========

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_113_ExternalToolWrapper",
        "status": "running",
        "version": "0.1.0",
        "description": "通用工具包装器 - 动态学习和使用任何 CLI 工具"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "known_tools_count": len(engine.get_known_tools()),
        "execution_history_count": len(engine.execution_history)
    }

@app.post("/api/v1/use_tool", response_model=Dict[str, Any])
async def use_tool(request: UseToolRequest):
    """
    使用工具完成任务
    
    Args:
        request: 使用工具请求
        
    Returns:
        Dict: 执行结果
    """
    try:
        result = engine.use_tool(
            tool_name=request.tool_name,
            task_description=request.task_description,
            context=request.context
        )
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/learn_tool", response_model=Dict[str, Any])
async def learn_tool(request: LearnToolRequest):
    """
    手动教授工具知识
    
    Args:
        request: 学习工具请求
        
    Returns:
        Dict: 工具知识
    """
    try:
        # 验证工具类型
        try:
            ToolType(request.tool_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tool_type. Must be one of: {[t.value for t in ToolType]}"
            )
        
        tool_knowledge = engine.learn_tool(
            tool_name=request.tool_name,
            tool_type=request.tool_type,
            description=request.description,
            install_command=request.install_command,
            examples=request.examples
        )
        
        return tool_knowledge.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/discover_tool", response_model=Dict[str, Any])
async def discover_tool(request: DiscoverToolRequest):
    """
    发现并学习工具
    
    Args:
        request: 发现工具请求
        
    Returns:
        Dict: 工具知识
    """
    try:
        tool_knowledge = engine.discover_tool(tool_name=request.tool_name)
        return tool_knowledge.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/known_tools", response_model=Dict[str, List[str]])
async def get_known_tools():
    """
    获取已知工具列表
    
    Returns:
        Dict: 工具列表
    """
    try:
        tools = engine.get_known_tools()
        return {"tools": tools}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/tool_knowledge/{tool_name}", response_model=Dict[str, Any])
async def get_tool_knowledge(tool_name: str):
    """
    获取工具知识
    
    Args:
        tool_name: 工具名称
        
    Returns:
        Dict: 工具知识
    """
    try:
        knowledge = engine.get_tool_knowledge(tool_name)
        if knowledge is None:
            raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found")
        return knowledge.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/v1/forget_tool", response_model=Dict[str, bool])
async def forget_tool(request: ForgetToolRequest):
    """
    忘记工具
    
    Args:
        request: 忘记工具请求
        
    Returns:
        Dict: 忘记结果
    """
    try:
        success = engine.forget_tool(request.tool_name)
        if not success:
            raise HTTPException(status_code=404, detail=f"Tool {request.tool_name} not found")
        return {"success": success}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/execution_history", response_model=List[Dict[str, Any]])
async def get_execution_history(limit: int = 100):
    """
    获取执行历史
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 执行历史
    """
    try:
        history = engine.execution_history[-limit:]
        return [r.to_dict() for r in history]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 主函数 ==========

if __name__ == "__main__":
    print(f"🚀 Starting Node_113_ExternalToolWrapper on {NODE_HOST}:{NODE_PORT}")
    print(f"📚 API Documentation: http://{NODE_HOST}:{NODE_PORT}/docs")
    
    uvicorn.run(
        app,
        host=NODE_HOST,
        port=NODE_PORT,
        log_level="info"
    )
