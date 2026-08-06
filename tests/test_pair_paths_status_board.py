#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pair_paths_status_board.py

``GET /api/v1/pair/paths`` —— 面板「路径状态盘」的数据源。

要解决什么
==========
设备连不上时，人唯一能做的判断是"是我这边的问题，还是那台电脑的问题"。
没有这一屏的话，两边都只能看到"连不上"，然后互相怀疑：在手机上重装应用、
重启路由器，而真正的原因可能只是那台电脑上 Funnel 没授权。

所以这一屏必须回答的不是"通不通"，而是**不通的话是被什么挡住的**。
只报 up/down 的状态盘和没有状态盘差别不大 —— 它把"连不上"换了个地方显示而已。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from core.routes.pairing import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


def _paths(client) -> dict:
    r = client.get("/api/v1/pair/paths")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    return {p["kind"]: p for p in body["paths"]}


# ---------------------------------------------------------------------------
# 一、三条路都要出现，哪怕不通
# ---------------------------------------------------------------------------


def test_all_three_kinds_are_listed_even_when_down(client):
    """只列通的那几条，等于把"这条路存在但不可用"和"没有这条路"混成一件事。

    前者要看的是怎么修，后者根本不用管。
    """
    by_kind = _paths(client)
    assert set(by_kind) == {"lan", "tailscale", "funnel"}


def test_order_follows_the_single_preference_list(client):
    """次序与 ``TailscaleManager.NETWORK_PREFERENCE`` 同源，不另写一份。"""
    from core.tailscale_manager import TailscaleManager

    r = client.get("/api/v1/pair/paths").json()
    assert [p["kind"] for p in r["paths"]] == TailscaleManager.NETWORK_PREFERENCE


def test_lan_is_always_up(client):
    """本机总在某个网段上。局域网那条报 down 只会让人去查一个没坏的东西。"""
    assert _paths(client)["lan"]["up"] is True
    assert _paths(client)["lan"]["url"].startswith("ws://")


# ---------------------------------------------------------------------------
# 二、不通的必须说清楚是被什么挡住的
# ---------------------------------------------------------------------------


def test_a_down_path_carries_a_reason(client):
    """容器里没有 tailscale，所以 tailscale/funnel 两条必然不通 —— 正好用来验这一点。"""
    by_kind = _paths(client)
    for kind in ("tailscale", "funnel"):
        p = by_kind[kind]
        if not p["up"]:
            assert p["reason"], f"{kind} 报了不通却没说为什么"


def test_funnel_blocked_by_the_auth_gate_says_so(client, monkeypatch):
    """闸门拦下的和"没装 tailscale"是两件完全不同的事。

    前者要去改一行配置，后者要去装个软件。混成一句"funnel 不可用"的话，
    用户会先去装 Tailscale，装完发现还是不行。
    """
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
    p = _paths(client)["funnel"]
    assert p["up"] is False
    assert p["reason"] == "auth_disabled"
    assert p["how_to_fix"], "拒绝了却不告诉人怎么办"


def test_public_reachable_is_a_single_clear_answer(client):
    """「手表带流量出门还能不能用」只有一个判据，就是 funnel 通不通。

    让人自己从三行状态里推这个结论，就会推错。
    """
    r = client.get("/api/v1/pair/paths").json()
    assert isinstance(r["public_reachable"], bool)
    by_kind = {p["kind"]: p for p in r["paths"]}
    assert r["public_reachable"] == by_kind["funnel"]["up"]


# ---------------------------------------------------------------------------
# 三、和设备侧对得上
# ---------------------------------------------------------------------------


def test_the_reported_urls_are_the_same_ones_handed_to_devices(client):
    """状态盘显示的地址必须就是配对时交给设备的那些。

    两处各算各的话，面板显示"局域网那条是通的"而设备手里拿的是另一个地址，
    排障时看到的两份事实互相矛盾。
    """
    from core.agent_card import build_candidates, local_device_id
    from core.electron_launch_guard import resolve_gateway_port

    expected = {c["kind"]: c["url"] for c in build_candidates(local_device_id(), resolve_gateway_port())}
    by_kind = _paths(client)
    for kind, url in expected.items():
        assert by_kind[kind]["url"] == url


def test_device_id_and_port_are_reported(client):
    """设备连的是 ``/ws/device/<网关 id>``。这一屏得能回答"网关的 id 是什么"。"""
    from core.agent_card import local_device_id

    r = client.get("/api/v1/pair/paths").json()
    assert r["device_id"] == local_device_id()
    assert isinstance(r["port"], int) and r["port"] > 0
