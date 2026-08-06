"""
PR-AUTH-UNIFIED(服务端补齐)—— WebSocket auth 首帧应答者测试
=============================================================

客户端契约(Android/WearOS shared-protocol AuthMessage.kt)early 上线:
onOpen 后首帧发 ``{"type": "auth", ...}``,等待 auth_ok/auth_failed。
此前 V2 无应答者,状态机两端空转。本套件钉住服务端应答语义:

1. 认证关闭(默认)→ auth_ok 且 auth_enforced=false(诚实:没校验)。
2. 认证开启 + 令牌缺失 → auth_failed reason=missing_token。
3. 认证开启 + 令牌错误 → auth_failed reason=invalid_token。
4. 认证开启 + 令牌正确 → auth_ok 且 auth_enforced=true。
5. 认证开启 + 服务端没配令牌 → auth_failed reason=server_not_configured。
6. AUTH 类型已注册进 AndroidBridge 消息处理表。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _msg(token: str = "", device_id: str = "dev-auth-1") -> dict:
    return {
        "type": "auth",
        "token": token,
        "device_id": device_id,
        "device_type": "android",
        "protocol_version": "3.0",
        "message_id": "msg-auth-1",
    }


@pytest.fixture()
def _auth_env(monkeypatch):
    """认证开启 + 单一有效令牌的标准环境。"""
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "1")
    monkeypatch.setenv("GALAXY_API_TOKEN", "valid-token-abc")
    monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
    monkeypatch.delenv("GALAXY_MODE", raising=False)


class TestAuthDisabled:
    def test_auth_ok_with_enforced_false(self, monkeypatch):
        # 显式关闭。原来靠 delenv 走默认，而 GALAXY_AUTH_ENABLED 的默认已改为
        # 开启（见 tests/test_public_exposure_requires_auth.py）。本条测的是
        # 「关掉时的行为」，就该自己关掉，而不是指望默认恰好是关的。
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        monkeypatch.delenv("GALAXY_MODE", raising=False)
        from galaxy_gateway.android.handlers.auth import handle_auth

        resp = _run(handle_auth(MagicMock(), None, _msg()))
        assert resp["type"] == "auth_ok"
        assert resp["auth_enforced"] is False
        assert resp["correlation_id"] == "msg-auth-1"


class TestAuthEnabled:
    def test_missing_token_fails(self, _auth_env):
        from galaxy_gateway.android.handlers.auth import handle_auth

        resp = _run(handle_auth(MagicMock(), None, _msg(token="")))
        assert resp["type"] == "auth_failed"
        assert resp["reason"] == "missing_token"
        assert resp["auth_enforced"] is True

    def test_invalid_token_fails(self, _auth_env):
        from galaxy_gateway.android.handlers.auth import handle_auth

        resp = _run(handle_auth(MagicMock(), None, _msg(token="wrong")))
        assert resp["type"] == "auth_failed"
        assert resp["reason"] == "invalid_token"

    def test_valid_token_ok(self, _auth_env):
        from galaxy_gateway.android.handlers.auth import handle_auth

        bridge = MagicMock(spec=[])
        resp = _run(handle_auth(bridge, None, _msg(token="valid-token-abc")))
        assert resp["type"] == "auth_ok"
        assert resp["auth_enforced"] is True
        # 连接级认证状态被记录,供后续按需门控
        assert getattr(bridge, "_connection_auth_state")["dev-auth-1"] == {
            "authenticated": True,
            "auth_enforced": True,
        }

    def test_no_server_tokens_fails_closed(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "1")
        monkeypatch.delenv("GALAXY_API_TOKEN", raising=False)
        monkeypatch.delenv("GALAXY_API_TOKENS", raising=False)
        from galaxy_gateway.android.handlers.auth import handle_auth

        resp = _run(handle_auth(MagicMock(), None, _msg(token="anything")))
        assert resp["type"] == "auth_failed"
        assert resp["reason"] == "server_not_configured"


class TestBridgeWiring:
    def test_auth_type_registered_in_bridge(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType

        assert MessageType.AUTH.value == "auth"
        assert MessageType.AUTH_OK.value == "auth_ok"
        assert MessageType.AUTH_FAILED.value == "auth_failed"

        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        assert MessageType.AUTH in bridge._message_handlers
