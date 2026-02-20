"""
Node_110_SmartOrchestrator - FastAPI 服务器

提供智能任务编排的 REST API
"""

import logging
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import uvicorn

from core.orchestrator_engine import SmartOrchestrator

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="Node_110_SmartOrchestrator",
    description="智能任务编排引擎 - 自动分析、匹配、编排和执行任务",
    version="1.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化编排引擎
orchestrator_config = {
    "node_01_url": "http://localhost:8001",
    "node_02_url": "http://localhost:8002",
    "node_67_url": "http://localhost:8067",
    "node_103_url": "http://localhost:8103"
}
orchestrator = SmartOrchestrator(orchestrator_config)


# ==================== 请求/响应模型 ====================

class OrchestrationRequest(BaseModel):
    """编排任务请求"""
    task_description: str = Field(..., description="任务描述（自然语言）")
    user_context: Optional[Dict[str, Any]] = Field(None, description="用户上下文")


class OrchestrationResponse(BaseModel):
    """编排任务响应"""
    task_id: str
    status: str
    execution_plan: Dict[str, Any]
    result: Dict[str, Any]


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str
    created_at: str
    result: Optional[Dict[str, Any]] = None


class OptimizationResponse(BaseModel):
    """优化响应"""
    task_id: str
    optimized: bool
    steps: list


class CapabilitiesResponse(BaseModel):
    """系统能力响应"""
    total_nodes: int
    healthy_nodes: int
    capabilities: list
    stats: Dict[str, Any]


# ==================== API 端点 ====================

@app.get("/")
async def root():
    """根端点"""
    return {
        "service": "Node_110_SmartOrchestrator",
        "version": "1.0.0",
        "status": "running",
        "description": "智能任务编排引擎"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "service": "Node_110_SmartOrchestrator"
    }


@app.post("/api/v1/orchestrate", response_model=OrchestrationResponse)
async def orchestrate_task(request: OrchestrationRequest):
    """
    编排任务
    
    该端点接收自然语言任务描述，自动：
    1. 调用 Node_01 分析任务
    2. 查询 Node_67 获取节点健康状态
    3. 匹配最适合的节点
    4. 生成执行计划
    5. 通过 Node_02 执行任务
    6. 存储编排知识到 Node_103
    """
    try:
        logger.info(f"Received orchestration request: {request.task_description[:100]}...")
        
        result = await orchestrator.orchestrate_task(
            task_description=request.task_description,
            user_context=request.user_context
        )
        
        return OrchestrationResponse(**result)
        
    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/orchestrate/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态
    
    查询指定任务的当前状态和结果
    """
    try:
        task_info = await orchestrator.get_task_status(task_id)
        
        if task_info is None:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        return TaskStatusResponse(
            task_id=task_info["id"],
            status=task_info["status"],
            created_at=task_info["created_at"],
            result=task_info.get("result")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/orchestrate/{task_id}/optimize", response_model=OptimizationResponse)
async def optimize_task(task_id: str):
    """
    优化执行计划
    
    基于当前节点健康状态和历史数据，优化任务的执行计划
    """
    try:
        result = await orchestrator.optimize_execution_plan(task_id)
        return OptimizationResponse(**result)
        
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Optimization failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/capabilities", response_model=CapabilitiesResponse)
async def get_capabilities():
    """
    获取系统能力
    
    返回当前系统的节点数量、健康状态、可用能力和统计信息
    """
    try:
        capabilities = orchestrator.get_system_capabilities()
        return CapabilitiesResponse(**capabilities)
        
    except Exception as e:
        logger.error(f"Failed to get capabilities: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 启动服务器 ====================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Node_110_SmartOrchestrator Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8110, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    
    logger.info(f"Starting Node_110_SmartOrchestrator on {args.host}:{args.port}")
    
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )
