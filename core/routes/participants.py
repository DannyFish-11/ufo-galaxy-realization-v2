"""core/routes/participants.py — 通用参与方接入的对外接口（R7）。

端点
----
  POST /api/v1/participants/register            一台设备按自己的声明接入：鉴权、写 UDM、进 mesh
  POST /api/v1/participants/{device_id}/tasks   已接入的参与方提交一句自然语言任务
  POST /api/v1/participants/{device_id}/heartbeat   心跳：保持在线（离线时自动恢复）
  POST /api/v1/participants/{device_id}/disconnect  主动离开：标断开、摘附着、终止 mesh 会话
  GET  /api/v1/participants                     经通用路径接入的参与方列表（需 API 鉴权）

与设备注册同属免 API 鉴权组：设备呈递的是配对令牌（作用域受限、绑定本设备），它刻意
不被 ``require_auth`` 接受（否则只读级别的手表就能写配置）。入口令牌由
:mod:`core.participant_admission` 自己校验 —— 与安卓注册路径同一份逻辑。令牌可放在
请求体的 ``token`` 字段，也可放在 ``Authorization: Bearer`` 头。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header
from fastapi.responses import JSONResponse


def _credentials(body: Dict[str, Any], authorization: Optional[str]) -> Dict[str, Any]:
    creds = dict(body)
    if authorization and not any(creds.get(k) for k in ("token", "auth_token", "api_token", "authorization")):
        creds["authorization"] = authorization
    return creds


def _reply(result: Dict[str, Any]) -> JSONResponse:
    code = result.get("error_code", "")
    status = 404 if code == "PARTICIPANT_NOT_ADMITTED" else 401 if code.startswith("INGRESS_") else 200
    return JSONResponse(result, status_code=status)


def create_router() -> APIRouter:
    from core.auth import require_auth

    router = APIRouter()

    @router.post("/api/v1/participants/register")
    async def register_participant(
        body: Dict[str, Any] = Body(...), authorization: Optional[str] = Header(None)
    ) -> JSONResponse:
        from core.participant_admission import ParticipantDescriptor, admit_participant

        message = _credentials(body, authorization)
        admission = admit_participant(ParticipantDescriptor.from_message(message), message=message)
        status = 200 if admission.admitted else (401 if admission.error_code.startswith("INGRESS_") else 400)
        return JSONResponse(admission.to_dict(), status_code=status)

    @router.post("/api/v1/participants/{device_id}/tasks")
    async def submit_task(
        device_id: str, body: Dict[str, Any] = Body(...), authorization: Optional[str] = Header(None)
    ) -> JSONResponse:
        from core.participant_admission import submit_participant_task

        text = str(body.get("message") or "").strip()
        if not text:
            return JSONResponse({"success": False, "error_code": "MESSAGE_MISSING"}, status_code=400)
        result = await submit_participant_task(
            device_id,
            text,
            session_id=body.get("session_id"),
            credentials=_credentials(body, authorization),
        )
        return _reply(result)

    @router.post("/api/v1/participants/{device_id}/heartbeat")
    async def heartbeat(
        device_id: str, body: Optional[Dict[str, Any]] = Body(None), authorization: Optional[str] = Header(None)
    ) -> JSONResponse:
        from core.participant_admission import participant_heartbeat

        return _reply(participant_heartbeat(device_id, credentials=_credentials(body or {}, authorization)))

    @router.post("/api/v1/participants/{device_id}/disconnect")
    async def disconnect(
        device_id: str, body: Optional[Dict[str, Any]] = Body(None), authorization: Optional[str] = Header(None)
    ) -> JSONResponse:
        from core.participant_admission import participant_disconnect

        return _reply(participant_disconnect(device_id, credentials=_credentials(body or {}, authorization)))

    @router.get("/api/v1/participants", dependencies=[Depends(require_auth)])
    async def list_participants() -> Dict[str, Any]:
        from core.participant_admission import ADMISSION_SOURCE
        from core.unified.device_manager import get_unified_device_manager

        devices = [
            {
                "device_id": d.device_id,
                "device_type": (d.metadata or {}).get("participant_kind") or d.device_type,
                "name": d.device_name,
                "status": d.status,
                "capabilities": list(d.capabilities),
            }
            for d in get_unified_device_manager().list_devices()
            if getattr(d, "source", "") == ADMISSION_SOURCE
        ]
        return {"participants": devices, "count": len(devices)}

    return router


__all__ = ["create_router"]
