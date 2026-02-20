"""
Node 113: AndroidVLM - Android GUI 理解服务

FastAPI 服务器

版本：1.0.0
日期：2026-01-24
作者：Manus AI
"""

import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 添加当前目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.android_vlm_engine import AndroidVLMEngine

app = FastAPI(title="Node 113 - AndroidVLM", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化引擎
engine = AndroidVLMEngine()

# ============================================================================
# 数据模型
# ============================================================================

class CaptureScreenRequest(BaseModel):
    """截取屏幕"""
    use_cache: bool = True

class AnalyzeScreenRequest(BaseModel):
    """分析屏幕"""
    query: str
    image_base64: Optional[str] = None
    provider: str = "auto"

class FindElementRequest(BaseModel):
    """查找元素"""
    description: str
    image_base64: Optional[str] = None
    confidence: float = 0.8

class SmartClickRequest(BaseModel):
    """智能点击"""
    description: str
    confidence: float = 0.8

class GenerateActionPlanRequest(BaseModel):
    """生成操作计划"""
    task_description: str
    max_steps: int = 10

class ExecuteActionPlanRequest(BaseModel):
    """执行操作计划"""
    steps: List[Dict[str, Any]]
    verify_each_step: bool = True

class SmartTaskExecutionRequest(BaseModel):
    """智能任务执行"""
    task_description: str
    max_steps: int = 10

# ============================================================================
# API 端点
# ============================================================================

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_113_AndroidVLM",
        "version": "1.0.0",
        "status": "running",
        "description": "Android GUI 理解引擎（VLM + 无障碍服务）"
    }

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node": "Node_113_AndroidVLM"
    }

@app.post("/capture_screen")
async def capture_screen(request: CaptureScreenRequest) -> Dict[str, Any]:
    """截取 Android 屏幕"""
    try:
        result = await engine.capture_android_screen(use_cache=request.use_cache)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze_screen")
async def analyze_screen(request: AnalyzeScreenRequest) -> Dict[str, Any]:
    """使用 VLM 分析屏幕"""
    try:
        result = await engine.analyze_screen(
            query=request.query,
            image_base64=request.image_base64,
            provider=request.provider
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/find_element")
async def find_element(request: FindElementRequest) -> Dict[str, Any]:
    """使用 VLM 查找元素"""
    try:
        result = await engine.find_element_with_vlm(
            description=request.description,
            image_base64=request.image_base64,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/smart_click")
async def smart_click(request: SmartClickRequest) -> Dict[str, Any]:
    """智能点击（截图 -> VLM 查找 -> 点击）"""
    try:
        result = await engine.smart_click(
            description=request.description,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_action_plan")
async def generate_action_plan(request: GenerateActionPlanRequest) -> Dict[str, Any]:
    """生成操作计划"""
    try:
        result = await engine.generate_action_plan(
            task_description=request.task_description,
            max_steps=request.max_steps
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute_action_plan")
async def execute_action_plan(request: ExecuteActionPlanRequest) -> Dict[str, Any]:
    """执行操作计划"""
    try:
        result = await engine.execute_action_plan(
            steps=request.steps,
            verify_each_step=request.verify_each_step
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/smart_task_execution")
async def smart_task_execution(request: SmartTaskExecutionRequest) -> Dict[str, Any]:
    """智能任务执行（生成计划 -> 执行计划）"""
    try:
        result = await engine.smart_task_execution(
            task_description=request.task_description,
            max_steps=request.max_steps
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_113_PORT", "8113"))
    uvicorn.run(app, host="0.0.0.0", port=port)
