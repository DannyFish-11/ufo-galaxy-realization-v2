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

from fastapi import APIRouter, Request
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


def _server_error(where: str, exc: Exception) -> JSONResponse:
    """把内部异常转成脱敏响应:完整异常只进服务端日志。

    起因是 CodeQL 的 "Information exposure through an exception":原先这里
    直接 ``str(exc)`` 回给调用方,而异常文本可能带出文件路径、内部模块名、
    密钥文件位置等。配对接口尤其敏感 —— 它就是信任链的入口。

    与仓库既有做法一致(见 core/routes/models.py::verify_provider:
    "分类成用户能行动的脱敏文案;完整异常只进服务端日志")。

    仍返回一个稳定的 ``error_code``,让调用方能据此分支处理、并凭它去
    服务端日志里定位对应那条 ERROR —— 脱敏不等于让人无从排查。
    """
    logger.error("配对接口内部错误 [%s]: %s", where, exc, exc_info=True)
    return JSONResponse(
        {
            "success": False,
            "error": "内部错误,请查看服务端日志",
            "error_code": where,
        },
        status_code=500,
    )


class ClaimRequest(BaseModel):
    #: 二选一:配对链接(galaxy://pair?...)或 6 位短码
    link: Optional[str] = None
    code: Optional[str] = None
    #: **领取方**的自我描述。令牌签给它,不是签给出示名片的那一台。
    #:
    #: 方向必须写死在这里,否则整条链是断的:桌面出示名片、手机来领,
    #: 而令牌若签成 ``card.device_id``(= 桌面),手机拿它去 ``/ws/device/<自己的 id>``
    #: 注册时,设备入口那道 ``subject == device_id`` 绑定校验必然把它顶回来 ——
    #: "配得上、连不了"。此前的用例都是在同一台机上 card→claim,两个 id 恰好相同,
    #: 所以这个方向错误一直没被照出来。
    device_id: str
    name: str = ""
    device_type: str = "unknown"
    capabilities: Optional[List[str]] = None
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
            return _server_error("pair_card", exc)

    @router.post("/api/v1/pair/claim")
    async def claim_peer(req: ClaimRequest, request: Request):
        """凭链接或短码接纳一台对端。

        名片签名校验不通过一律拒绝 —— 这是信任链的入口,不能"内容看着对"就放行。

        本端点是**鉴权豁免**的(见 galaxy_gateway/middleware.py 的豁免表):还没配对的
        设备手里没有任何令牌,要求它先带令牌就是死锁。凭证是那个一次性短码/链接本身。
        代价是这条路对公网开放,所以短码猜错要按来源节流 —— 见下。
        """
        try:
            from core.agent_card import from_link, get_pairing_attempt_throttle, get_pairing_code_registry
            from core.peer_trust import TrustLevel, coerce_trust, get_peer_trust_book

            throttle = get_pairing_attempt_throttle()
            source = (request.client.host if request.client else "") or "unknown"

            link = (req.link or "").strip()
            if not link:
                code = (req.code or "").strip()
                if not code:
                    return JSONResponse({"success": False, "error": "需要提供 link 或 code"}, status_code=400)
                if throttle.is_blocked(source):
                    logger.warning("配对被拒:短码猜测次数超限 —— source=%s", source)
                    return JSONResponse(
                        {"success": False, "error": "配对码错误次数过多,请稍后再试"},
                        status_code=429,
                    )
                link = get_pairing_code_registry().resolve(code) or ""
                if not link:
                    fails = throttle.record_failure(source)
                    logger.warning("配对码无效:source=%s 窗口内累计 %d 次", source, fails)
                    return JSONResponse(
                        {"success": False, "error": "配对码无效或已过期/已被使用"},
                        status_code=400,
                    )

            verdict = from_link(link)
            if not verdict.valid or verdict.card is None:
                # 名片伪造也计入节流:它和猜短码是同一件事的两种入口,
                # 只拦一边等于没拦。
                throttle.record_failure(source)
                logger.warning("配对被拒:名片校验失败 —— %s", verdict.reason)
                return JSONResponse({"success": False, "error": verdict.reason}, status_code=400)

            card = verdict.card

            # 校验通过的名片证明的是"这个人手里有一张本机签发、还没过期的邀请",
            # **不是**"这个人就是名片上那台机器"。所以登记与签发都以领取方
            # (req.device_id)为准,名片只用来判"该不该放它进来"。
            subject = req.device_id.strip()
            if not subject:
                throttle.record_failure(source)
                return JSONResponse({"success": False, "error": "需要提供 device_id"}, status_code=400)

            trust = coerce_trust(req.trust, TrustLevel.ASK)
            book = get_peer_trust_book()
            rec = book.upsert(
                subject,
                name=req.name or subject,
                trust=trust,
                auto_accept=req.auto_accept if req.auto_accept is not None else [],
                capabilities=req.capabilities if req.capabilities is not None else [],
                note=req.note,
            )

            # 能力令牌:作用域由信任级别推导,与信任同源,不另立一套权限。
            token: Optional[str] = None
            scopes = _scopes_for_trust(rec.trust)
            if scopes:
                try:
                    from core.capability_token import issue_token

                    token = issue_token(subject, scopes, ttl_s=req.token_ttl_s)
                except Exception as exc:  # noqa: BLE001
                    # 令牌签发失败不该让配对整体回滚(对端已登记、信任已生效),
                    # 但必须让调用方知道它没拿到令牌,否则会以为拿到了。
                    logger.warning("配对成功但能力令牌签发失败:device_id=%s: %s", subject, exc)

            logger.info(
                "配对成功:device_id=%s type=%s trust=%s scopes=%s(邀请来自 %s)",
                subject,
                req.device_type,
                rec.trust,
                scopes,
                card.device_id,
            )
            return JSONResponse(
                {
                    "success": True,
                    "peer": rec.to_dict(),
                    "capability_token": token,
                    "token_scopes": scopes,
                    "token_issued": token is not None,
                    # 兼容字段,永远是局域网地址。
                    "endpoints": card.endpoints,
                    # **设备接下来要连哪里**,按可达性排序。
                    # 少了这一条,C 做的多路可达在交接处原地丢掉:设备配上了,
                    # 手里却只有那个出了网段就是死地址的内网 IP。
                    "candidates": card.candidates,
                    "gateway_device_id": card.device_id,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _server_error("pair_claim", exc)

    @router.get("/api/v1/pair/paths")
    async def get_path_status():
        """本机当前每条可达路径的状态 —— 面板的「路径状态盘」读它。

        为什么要有这么一屏
        ------------------
        设备连不上时,人唯一能做的判断是"是我这边的问题,还是那台电脑的问题"。
        没有这一屏的话,两边都只能看到"连不上",然后互相怀疑。

        这里回答的是**桌面这一侧**的事实:哪几条路现在是通的,Funnel 那条如果没开
        是被什么挡住的。设备侧的判断由 ``ConnectionPathPlanner`` 负责,两边合起来
        才拼得出全貌。

        ``funnel`` 那条要跑一次 ``tailscale serve status``,比另外两条贵 ——
        所以这个端点是**按需**的,不进任何轮询。
        """
        try:
            from core.agent_card import build_candidates, local_device_id
            from core.electron_launch_guard import resolve_gateway_port
            from core.tailscale_manager import TailscaleManager

            port = resolve_gateway_port()
            did = local_device_id()
            candidates = build_candidates(did, port)
            live_kinds = {c["kind"] for c in candidates}

            mgr = TailscaleManager()
            gate = mgr.funnel_preflight()

            paths = []
            for kind in mgr.NETWORK_PREFERENCE:
                cand = next((c for c in candidates if c["kind"] == kind), None)
                if cand is not None:
                    paths.append({"kind": kind, "up": True, "url": cand["url"], "reason": "", "how_to_fix": ""})
                    continue
                # 不在候选里 = 这条路现在不可用。**为什么**不可用要说清楚,
                # 否则这一屏只是把"连不上"换了个地方显示。
                if kind == "funnel" and not gate["ok"]:
                    paths.append(
                        {
                            "kind": kind,
                            "up": False,
                            "url": "",
                            "reason": gate["reason"],
                            "how_to_fix": gate["how_to_fix"],
                        }
                    )
                else:
                    paths.append(
                        {
                            "kind": kind,
                            "up": False,
                            "url": "",
                            "reason": "tailscale_unavailable" if kind != "lan" else "unavailable",
                            "how_to_fix": (TailscaleManager.get_install_guide() if kind != "lan" else ""),
                        }
                    )

            return JSONResponse(
                {
                    "success": True,
                    "device_id": did,
                    "port": port,
                    "paths": paths,
                    # 手表带流量单独出门时唯一能用的那条。单独拎出来,因为它是
                    # 「出门还能不能用」这个问题的唯一判据。
                    "public_reachable": "funnel" in live_kinds,
                }
            )
        except Exception as exc:  # noqa: BLE001
            return _server_error("pair_paths", exc)

    @router.get("/api/v1/pair/peers")
    async def list_peers():
        try:
            from core.peer_trust import get_peer_trust_book

            peers = [p.to_dict() for p in get_peer_trust_book().list_peers()]
            return JSONResponse({"success": True, "count": len(peers), "peers": peers})
        except Exception as exc:  # noqa: BLE001
            return _server_error("pair_list_peers", exc)

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
            return _server_error("pair_get_peer", exc)

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
            return _server_error("pair_set_trust", exc)

    @router.delete("/api/v1/pair/peers/{device_id}")
    async def remove_peer(device_id: str):
        try:
            from core.peer_trust import get_peer_trust_book

            removed = get_peer_trust_book().remove(device_id)
            return JSONResponse({"success": True, "removed": removed, "device_id": device_id})
        except Exception as exc:  # noqa: BLE001
            return _server_error("pair_remove_peer", exc)

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
            return _server_error("pair_check", exc)

    return router
