"""
Node_110_SmartOrchestrator - FastAPI 服务器

提供智能任务编排的 REST API

架构说明
--------
该节点现在是 ConstellationRuntime 的**从属组件**，而非顶级编排入口。
``/api/v1/orchestrate`` 端点首先委托给 ConstellationRuntime.run()；
仅当 ConstellationRuntime 不可用时才回退到本地 SmartOrchestrator。
"""

import logging
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import uvicorn

try:
    from core.orchestrator_engine import SmartOrchestrator
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    SmartOrchestrator = None  # type: ignore[assignment,misc]

from nodes.common.cors_config import get_cors_origins

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建 FastAPI 应用
app = FastAPI(
    title="Node_110_SmartOrchestrator",
    description="智能任务编排引擎 - 委托给 ConstellationRuntime，保留旧引擎作为降级策略",
    version="2.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 本地降级编排引擎（仅在 ConstellationRuntime 不可用时使用）
orchestrator_config = {
    "node_01_url": "http://localhost:8001",
    "node_02_url": "http://localhost:8002",
    "node_67_url": "http://localhost:8067",
    "node_103_url": "http://localhost:8103"
}
try:
    _fallback_orchestrator = SmartOrchestrator(orchestrator_config) if SmartOrchestrator is not None else None
except Exception as _e:  # pragma: no cover
    logger.warning("SmartOrchestrator (fallback) 初始化失败: %s", _e)
    _fallback_orchestrator = None


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

    委托链路：
    1. 首先尝试 ConstellationRuntime.run()（系统级统一编排入口）
    2. 若 ConstellationRuntime 不可用则回退到本地 SmartOrchestrator

    该端点保持原有 OrchestrationResponse 响应 schema，向后兼容。
    """
    logger.info(
        "Received orchestration request (delegating to ConstellationRuntime): %s",
        request.task_description[:100],
    )

    # ── 1. ConstellationRuntime 主路径 ──────────────────────────────────
    try:
        from core.constellation_runtime import (
            get_constellation_runtime,
            wrap_as_orchestration_response,
        )
        runtime = get_constellation_runtime()
        cr_result = await runtime.run(
            task_description=request.task_description,
            context=request.user_context or {},
        )
        shaped = wrap_as_orchestration_response(cr_result)
        return OrchestrationResponse(**shaped)
    except Exception as cr_exc:
        logger.warning(
            "ConstellationRuntime 不可用，回退到本地引擎: %s", cr_exc
        )

    # ── 2. 本地 SmartOrchestrator 降级路径 ──────────────────────────────
    if _fallback_orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="编排引擎不可用（ConstellationRuntime 和 SmartOrchestrator 均不可用）",
        )
    try:
        result = await _fallback_orchestrator.orchestrate_task(
            task_description=request.task_description,
            user_context=request.user_context,
        )
        return OrchestrationResponse(**result)
    except Exception as e:
        logger.error("Orchestration failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/orchestrate/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    获取任务状态
    
    查询指定任务的当前状态和结果
    """
    try:
        if _fallback_orchestrator is None:
            raise HTTPException(status_code=503, detail="编排引擎不可用")
        task_info = await _fallback_orchestrator.get_task_status(task_id)
        
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
        if _fallback_orchestrator is None:
            raise HTTPException(status_code=503, detail="编排引擎不可用")
        result = await _fallback_orchestrator.optimize_execution_plan(task_id)
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
        if _fallback_orchestrator is None:
            raise HTTPException(status_code=503, detail="编排引擎不可用")
        capabilities = _fallback_orchestrator.get_system_capabilities()
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
