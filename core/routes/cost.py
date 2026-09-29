"""
Galaxy - Cost Tracking Routes
====================================

Routes:
  GET /api/v1/cost/records  - LLM 调用成本记录
  GET /api/v1/cost/summary  - 成本汇总统计
  GET /api/v1/cost/tasks    - 按任务结清的账单 + 近期平均
  GET /api/v1/cost/health   - 成本追踪器健康状态
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create cost tracking routes router."""
    router = APIRouter()

    @router.get("/api/v1/cost/records")
    async def cost_get_records(limit: int = 50, provider: str = "", model: str = ""):
        """获取最近 N 条 LLM 调用成本记录，支持按 provider/model 过滤"""
        try:
            from core.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            if provider or model:
                records = tracker.get_recent_filtered(
                    limit=limit,
                    provider=provider or None,
                    model=model or None,
                )
            else:
                records = tracker.get_recent(limit=limit)
            return JSONResponse({"records": records})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/cost/summary")
    async def cost_get_summary():
        """获取 LLM 调用成本汇总统计"""
        try:
            from core.cost_tracker import get_cost_tracker

            return JSONResponse(get_cost_tracker().get_summary())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/cost/tasks")
    async def cost_task_bills(limit: int = 20):
        """按任务结清的账单（一次请求里全部 LLM / 工具 / 轮次 / 墙钟）与近期平均。

        上面两个端点是逐次 LLM 调用；这里是"一件事总共花了多少"。
        """
        from core.task_cost_ledger import get_task_cost_ledger

        ledger = get_task_cost_ledger()
        return JSONResponse({"bills": ledger.recent(max(1, min(limit, 200))), "summary": ledger.summary()})

    @router.get("/api/v1/cost/health")
    async def cost_health():
        """获取成本追踪器写入健康状态"""
        try:
            from core.cost_tracker import get_cost_tracker

            return JSONResponse(get_cost_tracker().get_write_health())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
