"""
Node_108_MetaCognition - FastAPI Server
元认知节点服务器
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

from core.metacognition_engine import (
    MetaCognitionEngine,
    ThoughtType,
    CognitiveBias
)

# ========== 配置 ==========
NODE_PORT = int(os.getenv("NODE_108_PORT", "9100"))
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="Node_108_MetaCognition",
    description="元认知节点 - 反思思考过程，评估决策质量，优化策略",
    version="0.1.0"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 全局引擎实例 ==========
engine = MetaCognitionEngine()

# ========== Pydantic 模型 ==========

class TrackThoughtRequest(BaseModel):
    """追踪思维请求"""
    thought_type: str = Field(..., description="思维类型: perception/analysis/decision/action/reflection")
    content: str = Field(..., description="思维内容")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文信息")

class TrackThoughtResponse(BaseModel):
    """追踪思维响应"""
    thought_id: str
    thought_type: str
    quality_score: float
    biases_detected: List[str]
    timestamp: float

class TrackDecisionRequest(BaseModel):
    """追踪决策请求"""
    decision_content: str = Field(..., description="决策内容")
    alternatives: List[str] = Field(..., description="备选方案")
    reasoning: str = Field(..., description="推理过程")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 (0-1)")

class TrackDecisionResponse(BaseModel):
    """追踪决策响应"""
    decision_id: str
    decision_content: str
    confidence: float
    timestamp: float

class EvaluateDecisionRequest(BaseModel):
    """评估决策请求"""
    decision_id: str = Field(..., description="决策ID")
    outcome: Dict[str, Any] = Field(..., description="决策结果，必须包含 success_score (0-1)")

class EvaluateDecisionResponse(BaseModel):
    """评估决策响应"""
    decision_id: str
    overall_quality: float
    success_score: float
    confidence_match: float
    reasoning_quality: float

class ReflectRequest(BaseModel):
    """反思请求"""
    time_window: Optional[int] = Field(None, description="时间窗口（秒），None 表示所有历史")

class OptimizeStrategyRequest(BaseModel):
    """优化策略请求"""
    task_description: str = Field(..., description="任务描述")
    current_strategy: Dict[str, Any] = Field(..., description="当前策略")

# ========== API 端点 ==========

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_108_MetaCognition",
        "status": "running",
        "version": "0.1.0",
        "description": "元认知节点 - 反思思考过程，评估决策质量，优化策略"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "cognitive_state": engine.get_cognitive_state()
    }

@app.post("/api/v1/reflect", response_model=Dict[str, Any])
async def reflect(request: ReflectRequest):
    """
    反思最近的思维和决策过程
    
    Args:
        request: 反思请求
        
    Returns:
        Dict: 反思结果
    """
    try:
        reflection = engine.reflect(time_window=request.time_window)
        return reflection
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/track_thought", response_model=TrackThoughtResponse)
async def track_thought(request: TrackThoughtRequest):
    """
    追踪思维过程
    
    Args:
        request: 追踪思维请求
        
    Returns:
        TrackThoughtResponse: 思维记录
    """
    try:
        # 验证思维类型
        try:
            thought_type = ThoughtType(request.thought_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid thought_type. Must be one of: {[t.value for t in ThoughtType]}"
            )
        
        # 追踪思维
        thought = engine.track_thought(
            thought_type=thought_type,
            content=request.content,
            context=request.context
        )
        
        return TrackThoughtResponse(
            thought_id=thought.thought_id,
            thought_type=thought.thought_type.value,
            quality_score=thought.quality_score,
            biases_detected=[b.value for b in thought.biases_detected],
            timestamp=thought.timestamp
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/track_decision", response_model=TrackDecisionResponse)
async def track_decision(request: TrackDecisionRequest):
    """
    追踪决策过程
    
    Args:
        request: 追踪决策请求
        
    Returns:
        TrackDecisionResponse: 决策记录
    """
    try:
        decision = engine.track_decision(
            decision_content=request.decision_content,
            alternatives=request.alternatives,
            reasoning=request.reasoning,
            confidence=request.confidence
        )
        
        return TrackDecisionResponse(
            decision_id=decision.decision_id,
            decision_content=decision.decision_content,
            confidence=decision.confidence,
            timestamp=decision.timestamp
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/evaluate_decision", response_model=EvaluateDecisionResponse)
async def evaluate_decision(request: EvaluateDecisionRequest):
    """
    评估决策质量
    
    Args:
        request: 评估决策请求
        
    Returns:
        EvaluateDecisionResponse: 评估结果
    """
    try:
        # 验证 outcome 包含 success_score
        if "success_score" not in request.outcome:
            raise HTTPException(
                status_code=400,
                detail="outcome must contain 'success_score' (0-1)"
            )
        
        evaluation = engine.evaluate_decision(
            decision_id=request.decision_id,
            outcome=request.outcome
        )
        
        if "error" in evaluation:
            raise HTTPException(status_code=404, detail=evaluation["error"])
        
        return EvaluateDecisionResponse(
            decision_id=request.decision_id,
            overall_quality=evaluation["overall_quality"],
            success_score=evaluation["success_score"],
            confidence_match=evaluation["confidence_match"],
            reasoning_quality=evaluation["reasoning_quality"]
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/optimize_strategy", response_model=Dict[str, Any])
async def optimize_strategy(request: OptimizeStrategyRequest):
    """
    优化策略
    
    Args:
        request: 优化策略请求
        
    Returns:
        Dict: 优化建议
    """
    try:
        optimization = engine.optimize_strategy(
            task_description=request.task_description,
            current_strategy=request.current_strategy
        )
        return optimization
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/cognitive_state", response_model=Dict[str, Any])
async def get_cognitive_state():
    """
    获取当前认知状态
    
    Returns:
        Dict: 认知状态
    """
    try:
        return engine.get_cognitive_state()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/thought_history", response_model=List[Dict[str, Any]])
async def get_thought_history(limit: int = 100):
    """
    获取思维历史
    
    Args:
        limit: 返回记录数量限制
        
    Returns:
        List[Dict]: 思维历史
    """
    try:
        thoughts = engine.thought_history[-limit:]
        return [t.to_dict() for t in thoughts]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/decision_history", response_model=List[Dict[str, Any]])
async def get_decision_history(limit: int = 100):
    """
    获取决策历史
    
    Args:
        limit: 返回记录数量限制
        
    Returns:
        List[Dict]: 决策历史
    """
    try:
        decisions = engine.decision_history[-limit:]
        return [d.to_dict() for d in decisions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 主函数 ==========

if __name__ == "__main__":
    print(f"🚀 Starting Node_108_MetaCognition on {NODE_HOST}:{NODE_PORT}")
    print(f"📚 API Documentation: http://{NODE_HOST}:{NODE_PORT}/docs")
    
    uvicorn.run(
        app,
        host=NODE_HOST,
        port=NODE_PORT,
        log_level="info"
    )
