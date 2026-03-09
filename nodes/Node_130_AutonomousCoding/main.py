"""
Node 130: AutonomousCoding — 自主编程引擎
==========================================
提供代码生成、Bug 修复、测试编写、优化、重构、质量分析功能。
底层委托到 enhancements/coding/autonomous_coding_engine_v2.py。
"""

import json
import logging
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from nodes.common.cors_config import get_cors_origins

logger = logging.getLogger("Node_130_AutonomousCoding")

app = FastAPI(title="Node 130 - AutonomousCoding", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy engine access via fusion_entry
from nodes.Node_130_AutonomousCoding.fusion_entry import _get_engine, _run_async


class CodingRequest(BaseModel):
    action: str = Field(..., description="操作: generate_code/fix_bug/write_tests/optimize/refactor/analyze")
    code: str = Field(default="", description="源代码（部分操作必填）")
    language: str = Field(default="python", description="编程语言")
    description: str = Field(default="", description="任务描述")
    params: Dict[str, Any] = Field(default_factory=dict, description="额外参数")


@app.get("/health")
async def health():
    return {"status": "ok", "node": "Node_130_AutonomousCoding"}


@app.get("/status")
async def status():
    return {
        "node": "Node_130_AutonomousCoding",
        "status": "running",
        "actions": ["generate_code", "fix_bug", "write_tests", "optimize", "refactor", "analyze"],
    }


@app.post("/execute")
async def execute(req: CodingRequest):
    """执行编程任务"""
    try:
        engine = _get_engine()
        action_map = {
            "generate_code": lambda: _run_async(engine.generate_code(req.description, req.language, **req.params)),
            "fix_bug": lambda: _run_async(engine.fix_bug(req.code, req.description, req.language, **req.params)),
            "write_tests": lambda: _run_async(engine.write_tests(req.code, req.language, **req.params)),
            "optimize": lambda: _run_async(engine.optimize_code(req.code, req.language, **req.params)),
            "refactor": lambda: _run_async(engine.refactor_code(req.code, req.description, req.language, **req.params)),
            "analyze": lambda: _run_async(engine.analyze_quality(req.code, req.language, **req.params)),
        }

        handler = action_map.get(req.action)
        if not handler:
            raise HTTPException(
                status_code=400,
                detail=f"未知操作: {req.action}。支持: {list(action_map.keys())}",
            )

        result = handler()
        return {
            "success": True,
            "action": req.action,
            "result": result if isinstance(result, (dict, list, str)) else str(result),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"编程任务执行失败: {e}")
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8130)
