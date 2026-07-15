"""
galaxy_gateway/api/pairing.py — 设备配对/发放 REST 端点(P3-1 阶段二)
=====================================================================

把 core.device_enrollment 的协调器暴露成一组 REST 端点。信任边界:

- **设备侧(无凭证,开放)**:``/enroll`` 提交入伙请求、``/status`` 查状态、
  ``/claim`` 领 token —— 新设备此时还没有任何凭证,这些必须开放;request_id 是
  uuid4(不可猜),充当"领取自己 token"的一次性能力凭据。
- **信任侧(你在已信任设备上操作,require_auth)**:``/code`` 生成配对码、
  ``/pending`` 看待批准、``/approve`` / ``/deny`` 终裁 —— 这些是"别处批准"的动作,
  应由已鉴权的可信面完成。鉴权当前默认关(与全系统现状一致);随 P3-1 推进到
  auth-on 后,批准方用自己的每设备 token。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth import require_auth
from core.device_enrollment import get_enrollment_coordinator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pairing", tags=["device-pairing"])


class EnrollBody(BaseModel):
    device_id: str
    device_type: Optional[str] = None
    name: Optional[str] = None
    fingerprint: Optional[Dict[str, Any]] = None
    pairing_code: Optional[str] = None


class DecisionBody(BaseModel):
    request_id: str
    reason: Optional[str] = None


# ── 信任侧(require_auth) ────────────────────────────────────────────────
@router.post("/code")
async def create_pairing_code(_auth: dict = Depends(require_auth)) -> Dict[str, Any]:
    """桌面生成一个短时效配对码(可展示为二维码/文本)。"""
    return get_enrollment_coordinator().create_pairing_code()


@router.get("/pending")
async def list_pending(_auth: dict = Depends(require_auth)) -> Dict[str, Any]:
    """列出待你终裁的入伙请求(供批准界面)。不含任何 token。"""
    return {"pending": get_enrollment_coordinator().pending()}


@router.post("/approve")
async def approve(body: DecisionBody, _auth: dict = Depends(require_auth)) -> Dict[str, Any]:
    """批准(HITL 终裁):发放该设备专属 token。token 不在此返回,由设备 /claim 领取。"""
    tok = get_enrollment_coordinator().approve(body.request_id)
    if tok is None:
        return {"ok": False, "error": "request not pending or not found"}
    return {"ok": True, "request_id": body.request_id, "status": "approved"}


@router.post("/deny")
async def deny(body: DecisionBody, _auth: dict = Depends(require_auth)) -> Dict[str, Any]:
    ok = get_enrollment_coordinator().deny(body.request_id, reason=body.reason)
    return {"ok": ok, "request_id": body.request_id, "status": "denied" if ok else "not_pending"}


# ── 设备侧(开放:新设备尚无凭证) ─────────────────────────────────────────
@router.post("/enroll")
async def enroll(body: EnrollBody) -> Dict[str, Any]:
    """新设备提交入伙请求。返回 request_id;设备随后轮询 /status,批准后 /claim 领 token。"""
    try:
        req = get_enrollment_coordinator().submit_enrollment(
            body.device_id,
            device_type=body.device_type,
            name=body.name,
            fingerprint=body.fingerprint,
            pairing_code=body.pairing_code,
        )
    except ValueError as exc:
        # 不把异常文本回给未鉴权的设备端(CodeQL:信息泄漏)——详情落日志,
        # 对外只给静态、无堆栈的校验提示。
        logger.warning("enroll rejected (invalid request): %s", exc)
        return {"ok": False, "error": "invalid enrollment request (device_id required)"}
    return {
        "ok": True,
        "request_id": req.request_id,
        "status": req.status,
        "code_verified": req.code_verified,
    }


@router.get("/status/{request_id}")
async def status(request_id: str) -> Dict[str, Any]:
    view = get_enrollment_coordinator().get(request_id)
    if view is None:
        return {"ok": False, "error": "unknown request_id"}
    return {"ok": True, **view}


@router.post("/claim/{request_id}")
async def claim(request_id: str) -> Dict[str, Any]:
    """设备领取自己的 token(仅批准后、且一次性)。request_id 即一次性能力凭据。"""
    tok = get_enrollment_coordinator().claim(request_id)
    if tok is None:
        return {"ok": False, "error": "not approved or already claimed"}
    return {"ok": True, "token": tok}
