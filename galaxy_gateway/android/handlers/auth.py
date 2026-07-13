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
- 令牌源:``core.auth.get_active_tokens()``(支持轮换重叠窗口)。
- 失败语义:开了认证而令牌缺失/不匹配 → ``auth_failed`` + reason;
  服务端不在此处强行断连(传输层归属 websocket 路由),由客户端按
  契约自行断开并停止重连风暴。
- 连接级状态:结果记入 ``bridge`` 的连接认证表,供后续按需门控。
"""

from __future__ import annotations

import logging
import uuid
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


async def handle_auth(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Dict[str, Any]:
    """Handle the unified post-connect ``auth`` frame.

    Returns an ``auth_ok`` or ``auth_failed`` response dict that the
    ingress loop writes back to the socket.
    """
    device_id = str(message.get("device_id") or "").strip()
    device_type = str(message.get("device_type") or "").strip().lower()
    token = str(message.get("token") or "")
    message_id = str(message.get("message_id") or uuid.uuid4())

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
        from core.auth import get_active_tokens, is_auth_enabled
    except Exception as exc:  # pragma: no cover — auth module must not hard-fail ingress
        logger.error("[WS:AUTH] core.auth unavailable (%s) — failing closed", exc)
        return _response(False, reason="auth_backend_unavailable", auth_enforced=True)

    if not is_auth_enabled():
        # 诚实语义:未开启认证就明说没校验,客户端据此知道自己处于
        # 开放网关模式,而不是误以为令牌被验证过。
        logger.info(
            "[WS:AUTH] auth disabled (GALAXY_AUTH_ENABLED off) — auth_ok "
            "with auth_enforced=false device_id=%s",
            _mask(device_id),
        )
        _record_connection_auth(bridge, device_id, authenticated=True, enforced=False)
        return _response(True, auth_enforced=False)

    active_tokens = get_active_tokens()
    if not active_tokens:
        logger.error(
            "[WS:AUTH] auth enabled but no active tokens configured "
            "(GALAXY_API_TOKEN / GALAXY_API_TOKENS) — auth_failed"
        )
        return _response(False, reason="server_not_configured", auth_enforced=True)

    if not token:
        logger.warning("[WS:AUTH] missing token device_id=%s", _mask(device_id))
        return _response(False, reason="missing_token", auth_enforced=True)

    if token not in active_tokens:
        logger.warning(
            "[WS:AUTH] invalid token device_id=%s token=%s",
            _mask(device_id),
            _mask(token),
        )
        return _response(False, reason="invalid_token", auth_enforced=True)

    logger.info(
        "[WS:AUTH] auth_ok device_id=%s device_type=%s",
        _mask(device_id),
        device_type or "unknown",
    )
    _record_connection_auth(bridge, device_id, authenticated=True, enforced=True)
    return _response(True, auth_enforced=True)


def _record_connection_auth(
    bridge: "AndroidBridge", device_id: str, *, authenticated: bool, enforced: bool
) -> None:
    """Best-effort: record the auth outcome on the bridge for later gating."""
    if not device_id:
        return
    try:
        table = getattr(bridge, "_connection_auth_state", None)
        if table is None:
            table = {}
            setattr(bridge, "_connection_auth_state", table)
        table[device_id] = {
            "authenticated": authenticated,
            "auth_enforced": enforced,
        }
    except Exception as exc:  # noqa: BLE001 — observability only, never blocks auth
        logger.debug("[WS:AUTH] connection auth state record skipped: %s", exc)
