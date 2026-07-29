"""core/routes/pairing.py — 配对与对端信任的对外接口

端点
----
  GET    /api/v1/pair/card              本机名片(链接 + 短码,可扫码或口述)
  POST   /api/v1/pair/claim             凭链接或短码接纳一台对端,并签发能力令牌
  GET    /api/v1/pair/peers             已登记对端列表
  GET    /api/v1/pair/peers/{device_id} 单个对端档案
  POST   /api/v1/pair/trust             调整对端信任级别 / 自动放行模式
  DELETE /api/v1/pair/peers/{device_id} 移除对端
  POST   /api/v1/pair/check             试算一次意图判定(排障用,不产生副作用)

为什么把"签发能力令牌"放在配对里
--------------------------------
``core/capability_token.py`` 此前**全仓只有测试在调用** —— 签发/校验能力令牌的
基础设施造好了却没有任何生产路径使用它。配对是它天然的入口:
接纳一台设备的那一刻,正是该决定"它能干什么、到什么时候"的时刻。

令牌作用域由信任级别推导(见 :func:`_scopes_for_trust`),因此
"提升信任" 与 "扩大授权" 是同一个动作,不会出现两套彼此漂移的权限来源。
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API.Pairing")

#: 各信任级别对应的能力令牌作用域。
#: 刻意保守:blocked 无令牌;ask/unknown 只给只读;friend 给常规操作;
#: trusted 才给通配。改这里等于改整个 Mesh 的授权面,故集中在一处。
_TRUST_SCOPES: Dict[str, List[str]] = {
    "blocked": [],
    "unknown": ["device:status"],
    "ask": ["device:status"],
    "friend": ["device:status", "device:tap", "device:input", "messaging:*"],
    "trusted": ["*"],
}


def _scopes_for_trust(trust: str) -> List[str]:
    return list(_TRUST_SCOPES.get(str(trust).lower(), _TRUST_SCOPES["unknown"]))


class ClaimRequest(BaseModel):
    #: 二选一:配对链接(galaxy://pair?...)或 6 位短码
    link: Optional[str] = None
    code: Optional[str] = None
    #: 接纳时赋予的信任级别,默认 ask(保守:先接进来,动作仍要人确认)
    trust: str = "ask"
    auto_accept: Optional[List[str]] = None
    note: str = ""
    #: 能力令牌有效期
    token_ttl_s: float = 24 * 3600.0


class TrustRequest(BaseModel):
    device_id: str
    trust: Optional[str] = None
    auto_accept: Optional[List[str]] = None
    note: Optional[str] = None


class CheckRequest(BaseModel):
    device_id: str
    intent: str = ""


def create_router(service_manager=None, config=None) -> APIRouter:
    """配对与对端信任路由。"""
    router = APIRouter()

    @router.get("/api/v1/pair/card")
    async def get_local_card(ttl_s: float = 0.0, code_ttl_s: float = 0.0):
        """出示本机名片:同时给出可扫码的链接与可口述的短码。

        两种形态覆盖两类现场:有屏幕有摄像头的扫码,和只有终端的手输。
        """
        try:
            from core.agent_card import (
                DEFAULT_CARD_TTL_S,
                DEFAULT_CODE_TTL_S,
                build_local_card,
                get_pairing_code_registry,
                to_link,
            )

            card = build_local_card(ttl_s=ttl_s or DEFAULT_CARD_TTL_S)
            link = to_link(card)
            code, code_exp = get_pairing_code_registry().issue(link, ttl_s=code_ttl_s or DEFAULT_CODE_TTL_S)
            return JSONResponse(
                {
                    "success": True,
                    "card": card.to_dict(),
                    "link": link,
                    "code": code,
                    "code_expires_at": code_exp,
                    "hint": "对方可扫码/粘贴 link,或在无摄像头场景直接输入 code(一次性,默认 10 分钟内有效)",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("出示本机名片失败: %s", exc)
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.post("/api/v1/pair/claim")
    async def claim_peer(req: ClaimRequest):
        """凭链接或短码接纳一台对端。

        名片签名校验不通过一律拒绝 —— 这是信任链的入口,不能"内容看着对"就放行。
        """
        try:
            from core.agent_card import from_link, get_pairing_code_registry
            from core.peer_trust import TrustLevel, coerce_trust, get_peer_trust_book

            link = (req.link or "").strip()
            if not link:
                code = (req.code or "").strip()
                if not code:
                    return JSONResponse({"success": False, "error": "需要提供 link 或 code"}, status_code=400)
                link = get_pairing_code_registry().resolve(code) or ""
                if not link:
                    return JSONResponse(
                        {"success": False, "error": "配对码无效或已过期/已被使用"},
                        status_code=400,
                    )

            verdict = from_link(link)
            if not verdict.valid or verdict.card is None:
                logger.warning("配对被拒:名片校验失败 —— %s", verdict.reason)
                return JSONResponse({"success": False, "error": verdict.reason}, status_code=400)

            card = verdict.card
            trust = coerce_trust(req.trust, TrustLevel.ASK)
            book = get_peer_trust_book()
            rec = book.upsert(
                card.device_id,
                name=card.name,
                trust=trust,
                auto_accept=req.auto_accept if req.auto_accept is not None else [],
                capabilities=card.capabilities,
                note=req.note,
            )

            # 能力令牌:作用域由信任级别推导,与信任同源,不另立一套权限。
            token: Optional[str] = None
            scopes = _scopes_for_trust(rec.trust)
            if scopes:
                try:
                    from core.capability_token import issue_token

                    token = issue_token(card.device_id, scopes, ttl_s=req.token_ttl_s)
                except Exception as exc:  # noqa: BLE001
                    # 令牌签发失败不该让配对整体回滚(对端已登记、信任已生效),
                    # 但必须让调用方知道它没拿到令牌,否则会以为拿到了。
                    logger.warning("配对成功但能力令牌签发失败:device_id=%s: %s", card.device_id, exc)

            logger.info(
                "配对成功:device_id=%s name=%s trust=%s scopes=%s",
                card.device_id,
                card.name,
                rec.trust,
                scopes,
            )
            return JSONResponse(
                {
                    "success": True,
                    "peer": rec.to_dict(),
                    "capability_token": token,
                    "token_scopes": scopes,
                    "token_issued": token is not None,
                    "endpoints": card.endpoints,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("配对失败: %s", exc)
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.get("/api/v1/pair/peers")
    async def list_peers():
        try:
            from core.peer_trust import get_peer_trust_book

            peers = [p.to_dict() for p in get_peer_trust_book().list_peers()]
            return JSONResponse({"success": True, "count": len(peers), "peers": peers})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.get("/api/v1/pair/peers/{device_id}")
    async def get_peer(device_id: str):
        try:
            from core.peer_trust import get_peer_trust_book

            book = get_peer_trust_book()
            rec = book.get(device_id)
            if rec is None:
                # 未登记不是错误:如实告知它当前按默认信任处理,而不是 404 让调用方
                # 以为"这台设备不存在"。
                return JSONResponse(
                    {
                        "success": True,
                        "registered": False,
                        "device_id": device_id,
                        "effective_trust": book.trust_of(device_id).value,
                        "hint": "该对端尚未配对,按默认信任级别处理",
                    }
                )
            return JSONResponse({"success": True, "registered": True, "peer": rec.to_dict()})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.post("/api/v1/pair/trust")
    async def set_trust(req: TrustRequest):
        """调整信任级别 / 自动放行模式。提升信任会同步扩大令牌作用域(下次签发生效)。"""
        try:
            from core.peer_trust import get_peer_trust_book

            book = get_peer_trust_book()
            rec = book.upsert(
                req.device_id,
                trust=req.trust,
                auto_accept=req.auto_accept,
                note=req.note,
            )
            return JSONResponse(
                {
                    "success": True,
                    "peer": rec.to_dict(),
                    "token_scopes_next_issue": _scopes_for_trust(rec.trust),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.delete("/api/v1/pair/peers/{device_id}")
    async def remove_peer(device_id: str):
        try:
            from core.peer_trust import get_peer_trust_book

            removed = get_peer_trust_book().remove(device_id)
            return JSONResponse({"success": True, "removed": removed, "device_id": device_id})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    @router.post("/api/v1/pair/check")
    async def check_intent(req: CheckRequest):
        """试算判定,便于排障:为什么这台设备的这个动作被拦/被放行。"""
        try:
            from core.peer_trust import get_peer_trust_book

            book = get_peer_trust_book()
            result = book.check(req.device_id, req.intent)
            rec = book.get(req.device_id)
            return JSONResponse(
                {
                    "success": True,
                    "device_id": req.device_id,
                    "intent": req.intent,
                    "trust": book.trust_of(req.device_id).value,
                    "auto_accept": rec.auto_accept if rec else [],
                    "result": result.value,
                    "checked_at": time.time(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)

    return router
