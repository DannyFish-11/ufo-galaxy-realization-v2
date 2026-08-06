#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_claim_issues_token_to_the_claimer.py

配对的**方向**：桌面出示名片，设备来领，令牌签给**设备**。

改之前的形状
============
``/api/v1/pair/claim`` 把令牌签给 ``card.device_id`` —— 也就是**出示名片的那一台**。
桌面出示、手机来领的话，手机拿到的是一枚 ``subject`` 是桌面的令牌；它拿去连
``/ws/device/<自己的 id>``，设备入口那道 ``subject == device_id`` 绑定校验必然
把它顶回来。**配得上、连不了。**

这个方向错误此前一直没被照出来，因为所有用例都是在同一台机上
``card`` → ``claim``，两个 id 恰好相同。跨设备时才炸，而跨设备正是它唯一的用途。

为什么名片不能用来定身份
========================
校验通过的名片证明的是「这个人手里有一张本机签发、还没过期的邀请」，
**不是**「这个人就是名片上那台机器」。邀请是可以转交的（口述短码、转发二维码
本来就是设计里的用法）。拿它当身份用，等于谁拿到码谁就能冒充桌面。

所以：名片只回答「该不该放它进来」，身份由领取方自报并**写进令牌的 subject**，
设备入口再拿 subject 和它自报的 device_id 对一次 —— 两头闭合。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _fresh():
    import core.agent_card as ac
    import core.peer_trust as pt

    ac.reset_pairing_code_registry()
    ac.reset_pairing_attempt_throttle()
    if hasattr(pt, "reset_peer_trust_book"):
        pt.reset_peer_trust_book()
    yield


@pytest.fixture
def client():
    from core.routes.pairing import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _claim(client, code, device_id, **extra):
    body = {"code": code, "device_id": device_id}
    body.update(extra)
    return client.post("/api/v1/pair/claim", json=body)


# ---------------------------------------------------------------------------
# 一、令牌签给领取方
# ---------------------------------------------------------------------------


def test_token_subject_is_the_claimer_not_the_card_issuer(client):
    """**这就是被修掉的那个方向。**"""
    from core.capability_token import verify_token

    card = client.get("/api/v1/pair/card").json()
    watch = f"watch-{uuid.uuid4().hex[:6]}"

    r = _claim(client, card["code"], watch, trust="friend").json()
    assert r["success"] is True

    v = verify_token(r["capability_token"])
    assert v.valid, v.reason
    assert v.subject == watch, f"令牌签给了 {v.subject!r}，不是领取方 {watch!r}"
    assert v.subject != card["card"]["device_id"], "令牌又签给出示名片的那一台了"


def test_the_claimed_token_actually_gets_the_device_in(client):
    """端到端闭合：领到的令牌拿去设备入口，必须过。

    这条把 claim 与 ``_evaluate_ingress_authentication`` 的绑定校验对上 ——
    两边各自"看着对"但对不上，正是改之前的实际状态。
    """
    from galaxy_gateway.android.handlers.registration import _evaluate_ingress_authentication

    card = client.get("/api/v1/pair/card").json()
    phone = f"phone-{uuid.uuid4().hex[:6]}"
    tok = _claim(client, card["code"], phone, trust="friend").json()["capability_token"]

    out = _evaluate_ingress_authentication({"type": "device_register", "device_id": phone, "token": tok})
    assert out["token_valid"] is True, "配对领到的令牌进不了设备入口 —— 配得上、连不了"
    assert out["device_approved"] is True


def test_peer_book_registers_the_claimer(client):
    """登记的必须是设备，不是桌面自己。否则对端列表里永远只有自己一台。"""
    card = client.get("/api/v1/pair/card").json()
    watch = f"watch-{uuid.uuid4().hex[:6]}"

    r = _claim(client, card["code"], watch, name="我的手表", device_type="wearos").json()
    assert r["peer"]["device_id"] == watch
    assert r["peer"]["name"] == "我的手表"

    listed = client.get("/api/v1/pair/peers").json()
    ids = [p["device_id"] for p in listed["peers"]]
    assert watch in ids


def test_two_devices_get_two_distinct_identities(client):
    """一张名片可以接纳多台设备，各自拿到各自的身份。

    区分度：如果身份还是取自名片，两台设备会拿到**同一个** subject，
    这条会红 —— 而那正是改之前的行为。
    """
    from core.capability_token import verify_token

    a = client.get("/api/v1/pair/card").json()
    t1 = _claim(client, a["code"], "dev-A").json()["capability_token"]
    b = client.get("/api/v1/pair/card").json()
    t2 = _claim(client, b["code"], "dev-B").json()["capability_token"]

    assert verify_token(t1).subject == "dev-A"
    assert verify_token(t2).subject == "dev-B"


def test_claimer_cannot_impersonate_the_gateway(client):
    """把 device_id 填成桌面的 id 也只是"登记了一个同名对端"，

    真正拦住冒充的是设备入口的绑定校验 —— 这里确认令牌 subject 就是它自报的那个，
    没有任何一条路径能让它拿到"名片上那台机器"的身份而自己不承认。
    """
    from core.capability_token import verify_token

    card = client.get("/api/v1/pair/card").json()
    gw = card["card"]["device_id"]
    tok = _claim(client, card["code"], "impostor").json()["capability_token"]

    assert verify_token(tok).subject == "impostor"
    # 拿这枚令牌冒充网关 → 绑定对不上 → 被拒
    from galaxy_gateway.android.handlers.registration import _evaluate_ingress_authentication

    out = _evaluate_ingress_authentication({"type": "device_register", "device_id": gw, "token": tok})
    assert out["token_valid"] is False


def test_device_id_is_required(client):
    """没有 device_id 就没法谈"签给谁"。不许静默退回名片上的那个。"""
    card = client.get("/api/v1/pair/card").json()
    assert client.post("/api/v1/pair/claim", json={"code": card["code"]}).status_code == 422
    assert _claim(client, card["code"], "   ").status_code == 400


# ---------------------------------------------------------------------------
# 二、领完得知道往哪儿连
# ---------------------------------------------------------------------------


def test_claim_hands_back_the_reachable_candidates(client):
    """C 把候选路径放进了名片，交接处不能原地丢掉。

    丢了的话设备手里只剩 ``endpoints`` 里那个内网 IP —— 出了网段就是死地址，
    「手表带流量单独出门」这一档直接没了。
    """
    card = client.get("/api/v1/pair/card").json()
    r = _claim(client, card["code"], "watch-7").json()

    assert "candidates" in r, "claim 没把候选路径交给设备"
    assert r["candidates"] == card["card"]["candidates"]
    assert [c["kind"] for c in r["candidates"]][:1] == ["lan"]
    for c in r["candidates"]:
        assert c["url"].endswith("/ws/device/" + card["card"]["device_id"]) or "/ws/device/" in c["url"]
        assert isinstance(c["priority"], int)


def test_claim_tells_the_device_who_the_gateway_is(client):
    """设备要连的是网关那台，得知道它的 id —— 而这与设备自己的 id 是两回事。"""
    card = client.get("/api/v1/pair/card").json()
    r = _claim(client, card["code"], "watch-8").json()
    assert r["gateway_device_id"] == card["card"]["device_id"]
    assert r["peer"]["device_id"] == "watch-8"
