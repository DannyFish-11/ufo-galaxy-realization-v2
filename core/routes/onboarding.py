"""core/routes/onboarding.py — 设备接入平面的对外接口(面板用;智能体用 devices__* 工具)。

  GET    /api/v1/onboarding/overview                    成员(按角色分组)+ 候选 + 汇总
  POST   /api/v1/onboarding/candidates/{id}/join        接入一个候选(body: {"inputs": {...}})
  POST   /api/v1/onboarding/candidates/{id}/ignore      不再提示
  DELETE /api/v1/onboarding/members/{device_id}         移除成员(该收回的都收回)
  POST   /api/v1/onboarding/invite                      邀请新设备(body: {"kind": "phone|watch|computer"})
  POST   /api/v1/onboarding/scan                        立即把轮询型来源跑一遍

面板上人点「接入」「移除」本身就是人的确认,所以这里不再二次询问手表
(智能体那条路径会问,见 core/device_onboarding/agent_tools.py)。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API.Onboarding")


class JoinBody(BaseModel):
    inputs: Dict[str, Any] = {}


class InviteBody(BaseModel):
    kind: str


def _error(where: str, exc: Exception) -> JSONResponse:
    # 完整异常只进服务端日志,对外给稳定的错误码(同 core/routes/pairing.py 的做法)。
    logger.warning("onboarding %s 失败: %s", where, exc, exc_info=True)
    return JSONResponse({"success": False, "error": "内部错误,见服务端日志", "error_code": where}, status_code=500)


def create_router(service_manager=None, config=None) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/onboarding/overview")
    async def overview(include_ignored: bool = False):
        try:
            from core.device_onboarding.service import get_onboarding_service, onboarding_enabled

            if not onboarding_enabled():
                return JSONResponse({"success": True, "enabled": False})
            return JSONResponse(
                {"success": True, "enabled": True, **get_onboarding_service().overview(include_ignored=include_ignored)}
            )
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_overview", exc)

    @router.post("/api/v1/onboarding/candidates/{candidate_id}/join")
    async def join(candidate_id: str, body: JoinBody):
        try:
            from core.device_onboarding.service import get_onboarding_service

            out = await get_onboarding_service().join(candidate_id, body.inputs)
            return JSONResponse(out, status_code=200 if out.get("candidate") else 404)
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_join", exc)

    @router.post("/api/v1/onboarding/candidates/{candidate_id}/ignore")
    async def ignore(candidate_id: str):
        try:
            from core.device_onboarding.service import get_onboarding_service

            out = get_onboarding_service().ignore(candidate_id)
            return JSONResponse(out, status_code=200 if out.get("success") else 404)
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_ignore", exc)

    @router.delete("/api/v1/onboarding/members/{device_id}")
    async def remove(device_id: str):
        try:
            from core.device_onboarding.service import get_onboarding_service

            out = await get_onboarding_service().remove(device_id)
            return JSONResponse(out, status_code=200 if out.get("success") else 404)
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_remove", exc)

    @router.post("/api/v1/onboarding/invite")
    async def invite(body: InviteBody):
        try:
            from core.device_onboarding.agent_tools import _invite

            out = _invite({"kind": body.kind})
            return JSONResponse(out, status_code=200 if out.get("success") else 400)
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_invite", exc)

    @router.post("/api/v1/onboarding/scan")
    async def scan():
        try:
            from core.device_onboarding.sources import scan_once

            return JSONResponse({"success": True, "sources": await scan_once()})
        except Exception as exc:  # noqa: BLE001
            return _error("onboarding_scan", exc)

    return router
