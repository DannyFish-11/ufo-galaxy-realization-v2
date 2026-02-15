"""
Galaxy - AI 智能路由 API
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.ai_router import get_ai_router, TaskType, TaskComplexity

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

# ============================================================================
# API 端点
# ============================================================================

@router.get("/stats")
async def get_stats():
    """获取路由统计"""
    ai_router = get_ai_router()
    return ai_router.get_stats()

@router.post("/analyze")
async def analyze_task(request: AnalyzeRequest):
    """分析任务类型"""
    ai_router = get_ai_router()
    
    task_type, complexity = ai_router.analyze_task(request.prompt)
    
    # 获取推荐模型
    model_id, model = ai_router.select_best_model(request.prompt, optimize_for=request.optimize_for)
    
    # 生成选择原因
    reason = _generate_reason(task_type, complexity, model_id, request.optimize_for)
    
    return {
        "task_type": task_type.value,
        "complexity": complexity.value,
        "recommended_model": model_id,
        "reason": reason,
        "model_info": {
            "provider": model.provider,
            "reasoning": model.reasoning,
            "creativity": model.creativity,
            "coding": model.coding,
            "speed": model.speed
        }
    }

@router.post("/chat")
async def smart_chat(request: ChatRequest):
    """智能路由聊天"""
    ai_router = get_ai_router()
    
    try:
        result = await ai_router.chat(
            messages=request.messages,
            optimize_for=request.optimize_for,
            max_tokens=request.max_tokens,
            temperature=request.temperature
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/models")
async def list_models():
    """列出所有可用模型"""
    ai_router = get_ai_router()
    
    models = []
    for model_id, model in ai_router.models.items():
        if model.api_key:  # 只返回有 API Key 的模型
            models.append({
                "id": model_id,
                "provider": model.provider,
                "name": model.model_name,
                "capabilities": {
                    "reasoning": model.reasoning,
                    "creativity": model.creativity,
                    "coding": model.coding,
                    "analysis": model.analysis,
                    "speed": model.speed
                },
                "cost": {
                    "input": model.cost_input,
                    "output": model.cost_output
                },
                "features": {
                    "vision": model.supports_vision,
                    "function_call": model.supports_function_call
                },
                "stats": {
                    "total_calls": model.total_calls,
                    "success_calls": model.success_calls,
                    "avg_latency": model.avg_latency
                }
            })
    
    return {"models": models}

# ============================================================================
# 页面路由
# ============================================================================

from fastapi.responses import HTMLResponse
from pathlib import Path

@router.get("/page", response_class=HTMLResponse)
async def router_page():
    """AI 路由页面"""
    static_path = Path(__file__).parent / "static" / "router.html"
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(encoding='utf-8'))
    return {"error": "Router page not found"}

# ============================================================================
# 辅助函数
# ============================================================================

def _generate_reason(task_type: TaskType, complexity: TaskComplexity, model_id: str, optimize_for: str) -> str:
    """生成选择原因"""
    
    reasons = []
    
    # 任务类型
    type_reasons = {
        TaskType.SIMPLE_QA: "简单问答任务",
        TaskType.TRANSLATION: "翻译任务",
        TaskType.SUMMARIZATION: "总结任务",
        TaskType.CLASSIFICATION: "分类任务",
        TaskType.REASONING: "推理任务",
        TaskType.ANALYSIS: "分析任务",
        TaskType.WRITING: "写作任务",
        TaskType.CODING: "编程任务",
        TaskType.COMPLEX_REASONING: "复杂推理任务",
        TaskType.CREATIVE: "创意写作任务",
        TaskType.PLANNING: "规划任务",
        TaskType.MULTI_STEP: "多步骤任务",
        TaskType.VISION: "视觉理解任务",
        TaskType.FUNCTION_CALL: "函数调用任务",
        TaskType.UNKNOWN: "通用任务"
    }
    reasons.append(f"识别为{type_reasons.get(task_type, '未知任务')}")
    
    # 复杂度
    complexity_reasons = {
        TaskComplexity.LOW: "复杂度低，可使用快速模型",
        TaskComplexity.MEDIUM: "中等复杂度，需要平衡能力和速度",
        TaskComplexity.HIGH: "复杂度高，需要强大的推理能力"
    }
    reasons.append(complexity_reasons.get(complexity, ""))
    
    # 优化目标
    optimize_reasons = {
        "speed": "优化速度，选择响应最快的模型",
        "cost": "优化成本，选择性价比最高的模型",
        "quality": "优化质量，选择能力最强的模型",
        "balanced": "平衡模式，综合考虑各因素"
    }
    reasons.append(optimize_reasons.get(optimize_for, ""))
    
    return "；".join([r for r in reasons if r])
