"""
Galaxy - C阶段功能 API 路由
============================

C阶段新增路由:
  GET /api/v1/memory/tasks             - 最近 N 条任务记忆摘要 (4B)
  GET /api/v1/memory/stats             - 任务记忆统计 (4B)
  GET /api/v1/guardian/audit           - 工具调用守护审计日志 (2C)
  GET /api/v1/strategy/mappings        - 任务类型→策略映射表 (3B)
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create C-stage feature routes."""
    router = APIRouter()

    # ── 4B: 任务记忆 ──────────────────────────────────────────────────────

    @router.get("/api/v1/memory/tasks")
    async def memory_get_recent_tasks(n: int = 10):
        """获取最近 N 条任务执行摘要（C阶段 4B 长期记忆）。"""
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            summaries = mem.get_recent_summaries(n=min(n, 100))
            return JSONResponse({
                "success": True,
                "count": len(summaries),
                "summaries": [s.to_dict() for s in summaries],
            })
        except Exception as e:
            logger.warning("memory_get_recent_tasks error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @router.get("/api/v1/memory/stats")
    async def memory_get_stats():
        """获取任务记忆统计信息（C阶段 4B）。"""
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            return JSONResponse({"success": True, **mem.get_stats()})
        except Exception as e:
            logger.warning("memory_get_stats error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    # ── 2C: 工具守护审计 ──────────────────────────────────────────────────

    @router.get("/api/v1/guardian/audit")
    async def guardian_get_audit_log(n: int = 50):
        """获取最近 N 条工具调用守护审计日志（C阶段 2C）。"""
        try:
            from core.tool_guardian import get_guardian_audit_log
            entries = get_guardian_audit_log(n=min(n, 200))
            return JSONResponse({
                "success": True,
                "count": len(entries),
                "entries": entries,
            })
        except Exception as e:
            logger.warning("guardian_get_audit_log error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    # ── 3B: 策略映射表 ────────────────────────────────────────────────────

    @router.get("/api/v1/strategy/mappings")
    async def strategy_get_mappings():
        """获取任务类型 → 执行策略映射表（C阶段 3B）。"""
        try:
            from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
            return JSONResponse({
                "success": True,
                "mappings": TASK_TYPE_STRATEGY_MAP,
                "available_strategies": ["single", "specialized", "swarm", "fractal"],
            })
        except Exception as e:
            logger.warning("strategy_get_mappings error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    return router
