"""
galaxy_gateway/android/handlers/auth.py

PR-AUTH-UNIFIED(服务端补齐):处理客户端 onOpen 后发送的统一 ``auth``
首帧,并以 ``auth_ok`` / ``auth_failed`` 应答。

背景
----
Android / WearOS 客户端的 AuthMessage 契约(shared-protocol
AuthMessage.kt)早已上线:连接建立后第一帧发
``{"type": "auth", "token": ..., "device_id": ..., "device_type": ...}``,
并等待 ``auth_ok`` / ``auth_failed`` / ``auth_invalid``。此前 V2 侧没有
任何应答者——客户端发了就石沉大海,文档写的认证状态机两端空转。

语义(与 core.auth 的 canonical 口径一致,不另起炉灶)
----------------------------------------------------
- 认证开关:``core.auth.is_auth_enabled()``(GALAXY_AUTH_ENABLED,
  production 模式强制开)。**关闭时诚实应答**:回 ``auth_ok`` 且
  ``auth_enforced=false``——不假装校验过。
- 凭证判定与 ``device_register`` 是**同一份**
  (:func:`core.participant_admission.evaluate_ingress_authentication`):
  令牌可以在顶层 ``token``,也可以在 ``payload.token``(手表的 AuthMessage 就是编进
  payload 的);环境令牌、每设备令牌、以及 ``/api/v1/pair/claim`` 发的配对令牌
  (绑定本设备,subject 必须等于 device_id)都算。此前这里只认顶层的环境令牌 ——
  于是手表"配上了对、连得上网关、却过不了认证"。
- 失败语义:开了认证而令牌缺失/不匹配 → ``auth_failed`` + reason;
  服务端不在此处强行断连(传输层归属 websocket 路由),由客户端按
  契约自行断开并停止重连风暴。
- 连接级状态:结果记入 ``bridge`` 的连接认证表,供后续按需门控。
"""

from __future__ import annotations

import logging
import uuid
import weakref
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

_VALID_DEVICE_TYPES = frozenset({"android", "wearos", "windows", "desktop"})


def _mask(value: str, keep: int = 4) -> str:
    """Return a log-safe masked form of a secret-ish string."""
    if not value:
        return "<empty>"
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


async def handle_auth(bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]) -> Dict[str, Any]:
    """Handle the unified post-connect ``auth`` frame.

    Returns an ``auth_ok`` or ``auth_failed`` response dict that the
    ingress loop writes back to the socket.
    """
    inner = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    device_id = str(message.get("device_id") or inner.get("device_id") or "").strip()
    device_type = str(message.get("device_type") or inner.get("device_type") or "").strip().lower()
    message_id = str(message.get("message_id") or message.get("correlation_id") or uuid.uuid4())

    def _response(
        ok: bool,
        *,
        reason: str = "",
        auth_enforced: bool,
    ) -> Dict[str, Any]:
        return {
            "version": "3.0",
            "type": "auth_ok" if ok else "auth_failed",
            "message_id": str(uuid.uuid4()),
            "correlation_id": message_id,
            "device_id": device_id,
            "auth_enforced": auth_enforced,
            **({"reason": reason} if reason else {}),
        }

    if device_type and device_type not in _VALID_DEVICE_TYPES:
        logger.warning(
            "[WS:AUTH] unknown device_type=%r device_id=%s — continuing "
            "(forward-compat: new platforms must not be locked out by the "
            "auth surface)",
            device_type,
            _mask(device_id),
        )

    try:
        from core.auth import is_auth_enabled
        from core.participant_admission import evaluate_ingress_authentication
    except Exception as exc:  # pragma: no cover — auth module must not hard-fail ingress
        logger.error("[WS:AUTH] core.auth unavailable (%s) — failing closed", exc)
        return _response(False, reason="auth_backend_unavailable", auth_enforced=True)

    if not is_auth_enabled():
        # 诚实语义:未开启认证就明说没校验,客户端据此知道自己处于
        # 开放网关模式,而不是误以为令牌被验证过。
        logger.info(
            "[WS:AUTH] auth disabled (GALAXY_AUTH_ENABLED off) — auth_ok " "with auth_enforced=false device_id=%s",
            _mask(device_id),
        )
        _record_connection_auth(bridge, device_id, authenticated=True, enforced=False, websocket=websocket)
        return _response(True, auth_enforced=False)

    outcome = evaluate_ingress_authentication({**message, "device_id": device_id})
    if outcome.get("state") == "auth_check_unavailable":
        logger.error("[WS:AUTH] credential check unavailable (%s) — failing closed", outcome.get("reason"))
        return _response(False, reason="auth_backend_unavailable", auth_enforced=True)

    if outcome.get("state") == "rejected_auth_misconfigured":
        logger.error(
            "[WS:AUTH] auth enabled but no active tokens configured "
            "(GALAXY_API_TOKEN / GALAXY_API_TOKENS) — auth_failed"
        )
        return _response(False, reason="server_not_configured", auth_enforced=True)

    if not outcome.get("token_present"):
        logger.warning("[WS:AUTH] missing token device_id=%s", _mask(device_id))
        return _response(False, reason="missing_token", auth_enforced=True)

    if not outcome.get("token_valid"):
        logger.warning("[WS:AUTH] invalid token device_id=%s", _mask(device_id))
        return _response(False, reason="invalid_token", auth_enforced=True)

    logger.info(
        "[WS:AUTH] auth_ok device_id=%s device_type=%s",
        _mask(device_id),
        device_type or "unknown",
    )
    _record_connection_auth(bridge, device_id, authenticated=True, enforced=True, websocket=websocket)
    return _response(True, auth_enforced=True)


def _record_connection_auth(
    bridge: "AndroidBridge",
    device_id: str,
    *,
    authenticated: bool,
    enforced: bool,
    websocket: Any = None,
) -> None:
    """Record the auth outcome on the bridge, bound to the socket it happened on.

    The socket is held weakly: "this device authenticated" must mean *on this
    connection*, so that a different socket claiming the same device_id cannot
    ride on it (see :func:`galaxy_gateway.android.ingress_trust.sender_is_trusted`).
    """
    if not device_id:
        return
    try:
        table = getattr(bridge, "_connection_auth_state", None)
        if table is None:
            table = {}
            setattr(bridge, "_connection_auth_state", table)
        entry: Dict[str, Any] = {
            "authenticated": authenticated,
            "auth_enforced": enforced,
        }
        if websocket is not None:
            try:
                entry["ws"] = weakref.ref(websocket)
            except TypeError:  # 不支持弱引用的对象(测试替身):不绑定,等于不可信
                pass
        table[device_id] = entry
    except Exception as exc:  # noqa: BLE001 — observability only, never blocks auth
        logger.debug("[WS:AUTH] connection auth state record skipped: %s", exc)
