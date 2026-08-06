#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_paired_device_can_actually_connect.py

配对成功之后,设备得**真的连得上**。

问题的形状（鉴权默认翻成开启后才暴露出来）
==========================================
``POST /api/v1/pair/claim`` 发的是 ``core.capability_token`` 的**能力令牌**;
而设备入口 ``device_register`` 校验走的是 ``core.auth.verify_api_token``,它只认
环境令牌与 ``device_token_registry`` 的每设备令牌 —— **不认能力令牌**。

鉴权默认关着的时候这条缝看不出来（入口压根不校验）。默认一开,现象就是:
配对返回 ``success: true`` 并给了一枚令牌,设备拿着它去连,被 401 顶回来。
"配得上、连不了" —— 两套判据各说各话的典型。

同时必须守住的两条
==================
1. 能力令牌**不是**通用 API 令牌。``device:status`` 级别的手表不能拿它去写配置,
   否则这就是提权。它只在设备入口这一处成立。
2. 令牌绑定 ``subject == device_id``。否则一枚泄露的令牌换个 device_id 就能冒充
   别人接入。
"""

from __future__ import annotations

import pytest

from core.capability_token import issue_token
from galaxy_gateway.android.handlers.registration import (
    _PAIRED_DEVICE_MIN_SCOPE,
    _evaluate_ingress_authentication,
    _verify_pairing_capability_token,
)


def _msg(device_id: str, token: str | None = None) -> dict:
    m = {"type": "device_register", "device_id": device_id}
    if token is not None:
        m["token"] = token
    return m


@pytest.fixture(autouse=True)
def _auth_on(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", "env-admin-token-0123456789abcdefghij")
    return None


# ---------------------------------------------------------------------------
# 一、配对令牌能进门
# ---------------------------------------------------------------------------


def test_pairing_token_is_accepted_at_device_ingress():
    """**这条就是被修掉的那道缝。**"""
    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    out = _evaluate_ingress_authentication(_msg("watch-7", tok))
    assert out["token_valid"] is True, "配对发的令牌在设备入口被拒 —— 配得上、连不了"
    assert out["state"] == "verified"


def test_a_richer_scope_also_gets_in():
    """friend / trusted 级别拿到的作用域更宽,不该反而进不来。"""
    tok = issue_token("phone-1", ["device:status", "device:tap", "messaging:*"])
    assert _evaluate_ingress_authentication(_msg("phone-1", tok))["token_valid"] is True


def test_wildcard_scope_gets_in():
    """``trusted`` 拿的是 ``*``。通配必须覆盖到最小作用域。"""
    tok = issue_token("desktop-2", ["*"])
    assert _evaluate_ingress_authentication(_msg("desktop-2", tok))["token_valid"] is True


def test_pairing_token_counts_as_device_approved():
    """能力令牌天然绑定 device_id,就是"本设备已批准"。"""
    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    assert _evaluate_ingress_authentication(_msg("watch-7", tok))["device_approved"] is True


# ---------------------------------------------------------------------------
# 二、绑定必须校验
# ---------------------------------------------------------------------------


def test_token_for_another_device_is_rejected():
    """一枚泄露的令牌换个 device_id 就能冒充接入 —— 必须拦。"""
    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    out = _evaluate_ingress_authentication(_msg("phone-impostor", tok))
    assert out["token_valid"] is False
    assert out["state"] == "rejected_token_invalid"


def test_missing_device_id_does_not_pass():
    """没有 device_id 就没法谈绑定,不能当成"绑定通过"。"""
    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    assert _verify_pairing_capability_token(tok, "") is False


# ---------------------------------------------------------------------------
# 三、作用域不够 / 过期 / 撤销
# ---------------------------------------------------------------------------


def test_scopeless_token_is_rejected():
    """``blocked`` 对端压根拿不到令牌;真拿到一枚空作用域的也不许进。"""
    tok = issue_token("blocked-1", [])
    assert _verify_pairing_capability_token(tok, "blocked-1") is False


def test_unrelated_scope_is_rejected():
    """作用域不含 ``device:status`` 的令牌不是"设备接入"用的。"""
    tok = issue_token("svc-1", ["billing:read"])
    assert _verify_pairing_capability_token(tok, "svc-1") is False


def test_expired_token_is_rejected():
    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE], ttl_s=-1.0)
    assert _verify_pairing_capability_token(tok, "watch-7") is False


def test_revoked_token_is_rejected():
    """撤销要立刻生效 —— 否则"移除对端"是个假动作。"""
    import base64
    import json

    from core.capability_token import reset_revoked_cache, revoke

    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    claims = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
    try:
        revoke(claims["jti"])
        assert _verify_pairing_capability_token(tok, "watch-7") is False
    finally:
        reset_revoked_cache()


def test_garbage_token_is_rejected():
    assert _verify_pairing_capability_token("not-a-token", "watch-7") is False


# ---------------------------------------------------------------------------
# 四、不许变成通用 API 令牌（提权）
# ---------------------------------------------------------------------------


def test_pairing_token_is_not_a_general_api_credential():
    """**这条守的是另一侧。**

    如果把能力令牌塞进 ``core.auth.verify_api_token``,中间件立刻会把一枚
    ``device:status`` 的手表令牌当成合法 API 令牌 —— 手表随即能去写配置。
    这里要它在通用校验那边**不通过**。
    """
    from core.auth import verify_api_token

    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    assert verify_api_token(tok) is False, "能力令牌被当成通用 API 令牌了 —— 提权"


def test_middleware_still_rejects_a_pairing_token(monkeypatch):
    """走一遍真中间件,别只信单元层。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from galaxy_gateway.middleware import BearerAuthMiddleware

    app = FastAPI()
    app.add_middleware(BearerAuthMiddleware)

    @app.post("/api/config")
    async def _write():  # pragma: no cover - 不该被走到
        return {"ok": True}

    tok = issue_token("watch-7", [_PAIRED_DEVICE_MIN_SCOPE])
    r = TestClient(app).post("/api/config", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# 五、原有的两条凭证没被挤掉
# ---------------------------------------------------------------------------


def test_env_admin_token_still_works():
    """加了第三条凭证不该把原来的挤掉。"""
    out = _evaluate_ingress_authentication(_msg("any-device", "env-admin-token-0123456789abcdefghij"))
    assert out["token_valid"] is True


def test_anonymous_registration_is_rejected_under_enforced_auth():
    """默认开启鉴权之后,匿名注册必须被拒 —— 这正是改默认要的效果。"""
    out = _evaluate_ingress_authentication(_msg("anon-1"))
    assert out["token_valid"] is False
    assert out["state"] == "rejected_token_missing"
