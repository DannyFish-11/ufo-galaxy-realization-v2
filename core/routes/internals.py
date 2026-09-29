"""core/routes/internals.py — 内部诊断索引（只读，需 API 鉴权，面板不画）。

  GET /api/v1/diagnostics/internals          全部段：名字 + 一句话说明
  GET /api/v1/diagnostics/internals/{name}   读一段；需要参数的段用 ?q=

各段是什么、从哪里读，见 :mod:`core.diagnostics_internals`。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/diagnostics/internals")
    async def list_internal_sections() -> Dict[str, Any]:
        from core.diagnostics_internals import list_sections

        return {"sections": list_sections()}

    @router.get("/api/v1/diagnostics/internals/{name}")
    async def read_internal_section(name: str, q: str = Query("", max_length=256)) -> Dict[str, Any]:
        from core.diagnostics_internals import read_section

        section = read_section(name, q)
        if section is None:
            raise HTTPException(status_code=404, detail=f"没有这一段：{name}")
        return section

    return router
