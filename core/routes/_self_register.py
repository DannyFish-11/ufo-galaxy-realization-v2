"""设备自己从 REST 来登记（``POST /api/v1/devices/register``、旧的 ``/api/devices/register``）时，谁能直接进 UDM。

原先两个登记口不查任何凭据就写 UDM：同一局域网谁都能登记一台假设备、接到派过去的任务（安卓走 WS，有带内认证；
非安卓设备的通用入口 ``/api/v1/participants/register`` 自己核验入口令牌 —— 只有这两个口是敞着的）。
所有者定：**在面板上确认**。

直接登记的三种情况：鉴权关着（主人选择信任局域网）、带着主人的令牌（面板、脚本）、本来就是成员（重新登记）。
其余的交给设备接入平面记成候选（``core.device_onboarding.join_paths.SelfRegisteredPath``），回 202；
人在面板「全部设置」最上面点「接入」才写进 UDM。设备之后再来登记时已是成员，走原来那条完整路径。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.API.SelfRegister")


def register_directly(device_id: str, authorization: Optional[str], *, known: bool) -> bool:
    """这次登记能不能直接进 UDM。"""
    return known or from_owner(authorization)


def from_owner(authorization: Optional[str]) -> bool:
    """请求是不是主人发的:鉴权关着(主人选择信任局域网),或带着主人的令牌(面板、脚本)。"""
    from core.auth import is_auth_enabled, verify_api_token

    if not is_auth_enabled():
        return True
    parts = (authorization or "").split()
    return len(parts) == 2 and parts[0].lower() == "bearer" and verify_api_token(parts[1])


def stored_identity(device_id: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    """成员不带凭据来重新登记时用的资料:**已登记的**名字 / 类型 / 能力,不是请求里报的。

    设备号就写在请求体里,谁都能冒用:原先重新登记会拿请求里报的覆盖 UDM 与能力表 —— 冒用一台手机的设备号就能
    改它的名字、给它添上没有的能力。改资料要主人的令牌(或在面板上移除后重新接入)。"""
    from core.unified.device_manager import get_unified_device_manager

    keep: Dict[str, Any] = {}
    try:
        d = get_unified_device_manager().get_device(device_id)
    except Exception:  # noqa: BLE001 — 查不到就按兼容缓存
        d = None
    if d is not None:
        keep = {
            "device_name": d.device_name,
            "device_type": d.aip_device_type or getattr(d.device_type, "value", str(d.device_type)),
            "capabilities": list(d.capabilities or []),
        }
    else:
        from core.routes._shared import registered_devices

        old = registered_devices.get(device_id) or {}
        keep = {k: old[k] for k in ("device_name", "device_type", "capabilities") if k in old}
    return {**fallback, **keep}


def await_owner(device_info: Dict[str, Any]) -> JSONResponse:
    """记成候选、等人在面板上同意；不写 UDM。"""
    from core.device_onboarding.join_paths import SELF_REGISTER_SOURCE
    from core.device_onboarding.models import CandidateStatus, Observation
    from core.device_onboarding.service import get_onboarding_service, onboarding_enabled

    device_id = str(device_info.get("device_id") or "")
    if not onboarding_enabled():
        return JSONResponse(
            {
                "success": False,
                "status": "rejected",
                "error": "设备接入已关闭（GALAXY_ONBOARDING_ENABLED）：新设备要带主人的令牌来登记",
            },
            status_code=403,
        )
    cand = get_onboarding_service().observe(
        Observation(
            source=SELF_REGISTER_SOURCE,
            key=device_id,
            name=str(device_info.get("device_name") or device_id),
            kind_hint=str(device_info.get("device_type") or ""),
            identity={"device_id": device_id},
            capabilities=[str(c) for c in device_info.get("capabilities") or []],
            properties={"registration": dict(device_info)},
        )
    )
    if cand is None:  # 刚刚被接入了(已是成员):让它再来登记一次就走完整路径
        return JSONResponse({"success": False, "status": "joined", "message": "已接入，请再登记一次"}, status_code=409)
    if cand.status == CandidateStatus.IGNORED.value:
        return JSONResponse(
            {"success": False, "status": "rejected", "error": "主人选了不接入这台设备"}, status_code=403
        )
    logger.info("设备 %s 自己来登记,不带凭据:记成候选,等主人在面板上同意", device_id)
    return JSONResponse(
        {
            "success": False,
            "status": "pending_approval",
            "device_id": device_id,
            "candidate_id": cand.candidate_id,
            "message": "已记下，等主人在面板上同意；同意后再来登记一次即可",
        },
        status_code=202,
    )
