"""
Galaxy - C阶段功能 API 路由
============================

C阶段新增路由:
  GET  /api/v1/memory/tasks            - 最近 N 条任务记忆摘要 (4B)；支持 task_type 过滤 (G6)
  GET  /api/v1/memory/stats            - 任务记忆统计 (4B)
  GET  /api/v1/memory/cold             - 查询冷区历史记录；支持 task_type 过滤 (G6)
  GET  /api/v1/memory/drift/config     - 获取漂移检测配置 (G6)
  PUT  /api/v1/memory/drift/config     - 更新漂移检测配置 (G6)
  POST /api/v1/memory/drift/check      - 执行漂移检测 (G6)
  GET  /api/v1/guardian/audit          - 工具调用守护审计日志 (2C)
  GET  /api/v1/strategy/mappings       - 任务类型→策略映射表 (3B)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create C-stage feature routes."""
    router = APIRouter()

    # ── 4B / G6: 任务记忆 ────────────────────────────────────────────────

    @router.get("/api/v1/memory/tasks")
    async def memory_get_recent_tasks(n: int = 10, task_type: Optional[str] = None):
        """获取最近 N 条任务执行摘要（C阶段 4B）。

        G6 新增参数:
          task_type: 按任务类型过滤（可选；不传则返回所有类型）
        """
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            summaries = mem.get_recent_summaries(
                n=min(n, 100),
                task_type=task_type or None,
            )
            return JSONResponse({
                "success": True,
                "count": len(summaries),
                "task_type_filter": task_type,
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

    # ── G6: 冷区查询 ─────────────────────────────────────────────────────

    @router.get("/api/v1/memory/cold")
    async def memory_query_cold(n: int = 50, task_type: Optional[str] = None):
        """查询冷区历史记录（G6）。

        返回热区之外的持久化记录，可按 task_type 过滤。
        结果按时间降序（最新在前）。
        """
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            records = mem.query_cold_storage(
                n=min(n, 500),
                task_type=task_type or None,
            )
            return JSONResponse({
                "success": True,
                "count": len(records),
                "task_type_filter": task_type,
                "records": [r.to_dict() for r in records],
            })
        except Exception as e:
            logger.warning("memory_query_cold error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    # ── G6: 漂移检测配置 ─────────────────────────────────────────────────

    @router.get("/api/v1/memory/drift/config")
    async def drift_get_config():
        """获取当前漂移检测配置（G6）。"""
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            cfg = mem.get_drift_config()
            return JSONResponse({"success": True, **cfg})
        except Exception as e:
            logger.warning("drift_get_config error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    @router.put("/api/v1/memory/drift/config")
    async def drift_set_config(body: dict = Body(...)):
        """更新漂移检测配置（G6）。

        请求体（JSON，字段均可选）:
          threshold: float  # 0.0–1.0，相似度阈值
          action:    str    # "rerun" | "human_review" | "none"
        """
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()
            threshold = body.get("threshold", mem.get_drift_config()["threshold"])
            action = body.get("action", mem.get_drift_config()["action"])
            mem.configure_drift(threshold=float(threshold), action=str(action))
            return JSONResponse({"success": True, **mem.get_drift_config()})
        except ValueError as e:
            return JSONResponse({"success": False, "error": str(e)}, status_code=400)
        except Exception as e:
            logger.warning("drift_set_config error: %s", e)
            return JSONResponse({"success": False, "error": str(e)}, status_code=500)

    # ── G6: 漂移检测执行 ─────────────────────────────────────────────────

    @router.post("/api/v1/memory/drift/check")
    async def drift_check(body: dict = Body(...)):
        """对比新结果与缓存摘要，检测结果漂移（G6）。

        请求体（JSON）:
          task_key:   str   # 必填：任务标识
          new_result: str   # 必填：本次执行结果摘要
          task_type:  str   # 可选：优先匹配此类型的缓存记录
          threshold:  float # 可选：覆盖实例级阈值
          action:     str   # 可选：覆盖实例级动作

        响应:
          is_drift:        bool
          similarity:      float
          action:          str
          threshold:       float
          cached_summary:  str | null
          task_key:        str
        """
        try:
            from core.task_memory import get_task_memory
            mem = get_task_memory()

            task_key = body.get("task_key", "")
            new_result = body.get("new_result", "")
            if not task_key:
                return JSONResponse(
                    {"success": False, "error": "task_key 不能为空"},
                    status_code=400,
                )

            result = mem.check_consistency(
                task_key=task_key,
                new_result=new_result,
                threshold=body.get("threshold"),
                action=body.get("action"),
                task_type=body.get("task_type", ""),
            )
            return JSONResponse({"success": True, **result.to_dict()})
        except Exception as e:
            logger.warning("drift_check error: %s", e)
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
