"""core/routes/result_recovery.py — 真相链没收口、补跑后仍没收口的结果（隔离待处理队列）。

端点
----
  GET  /api/v1/results/isolated                  列出隔离项（``?include_dismissed=true`` 连已知悉的一起）
  GET  /api/v1/results/isolated/{key}            单条
  POST /api/v1/results/isolated/{key}/retry      再试一次（只重跑失败步骤；补齐了就移出队列）
  POST /api/v1/results/isolated/{key}/dismiss    知悉（标 dismissed，记录保留）

语义与存储全在 :mod:`core.truth_chain_recovery`，这里只搬运。只返回类型化字段，
原始结果消息不经接口外露。挂在可观测性路由下（与面板用的那组一样免鉴权），面板
「全部设置」最上面那段读的就是它。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException


def create_router() -> APIRouter:
    router = APIRouter()
    register(router)
    return router


def register(router: APIRouter) -> None:
    """把四个端点直接登记到 *router* 上。

    可观测性路由用它挂载，而不是 ``include_router`` 一个子路由：新版 FastAPI 把被包含的子路由存成一个
    没有 ``.path`` 的条目，遍历 ``router.routes`` 读 ``.path`` 的既有调用方会因此出错。
    """

    @router.get("/api/v1/results/isolated")
    async def list_isolated(include_dismissed: bool = False) -> Dict[str, Any]:
        from core.truth_chain_recovery import get_truth_chain_recovery

        recovery = get_truth_chain_recovery()
        return {
            "summary": recovery.summary(),
            "items": recovery.isolated(include_dismissed=include_dismissed),
            "recovered_recent": recovery.recent_recovered()[:20],
        }

    @router.get("/api/v1/results/isolated/{key}")
    async def get_isolated(key: str) -> Dict[str, Any]:
        from core.truth_chain_recovery import get_truth_chain_recovery

        row = get_truth_chain_recovery().get(key)
        if row is None:
            raise HTTPException(status_code=404, detail=f"隔离队列里没有 {key}")
        return row

    @router.post("/api/v1/results/isolated/{key}/retry")
    async def retry_isolated(key: str) -> Dict[str, Any]:
        from core.truth_chain_recovery import get_truth_chain_recovery

        row = get_truth_chain_recovery().retry_isolated(key)
        if row is None:
            raise HTTPException(status_code=404, detail=f"隔离队列里没有 {key}")
        return row

    @router.post("/api/v1/results/isolated/{key}/dismiss")
    async def dismiss_isolated(key: str) -> Dict[str, Any]:
        from core.truth_chain_recovery import get_truth_chain_recovery

        row = get_truth_chain_recovery().dismiss(key)
        if row is None:
            raise HTTPException(status_code=404, detail=f"隔离队列里没有 {key}")
        return row


__all__ = ["create_router", "register"]
