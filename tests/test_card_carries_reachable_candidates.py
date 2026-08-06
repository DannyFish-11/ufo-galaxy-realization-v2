#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_card_carries_reachable_candidates.py

名片得带上**所有可达路径**,不能只带一个内网地址。

问题的形状
==========
``endpoints["websocket"]`` 里那个 ``ws://192.168.x.x:9000/...`` 出了网段就是死
地址。扫码解决的是"不用手填 IP/端口/路径",解决不了"能不能连通"。手表带流量
单独出门时,内网地址、tailnet 地址都够不着 —— Wear OS 没有 Tailscale 客户端,
进不了 tailnet —— 只有 Funnel 那条公网路能用。名片里没有它,这台设备就配不上。

三条容易写对一半的地方
======================
1. **签了没解**。``candidates`` 进了 payload、被签名覆盖,但 ``from_link``
   不读它 —— 字段在生产端是活的、在消费端是死的,静默丢失,没有任何报错。
2. **Funnel URL 拼了端口**。Funnel 对外只能落在 443/8443/10000,拼上 ``:9000``
   得到一个语法正确但必然连不上的地址。
3. **排序各写各的**。桌面按一种顺序发、设备按另一种顺序连。
"""

from __future__ import annotations

import pytest

from core.agent_card import (
    build_candidates,
    build_local_card,
    create_agent_card,
    from_link,
    to_link,
)
from core.tailscale_manager import TailscaleManager


class _FakeManager:
    """一个可控的 TailscaleManager 替身 —— 容器里没有真 tailscale。"""

    @property
    def NETWORK_PREFERENCE(self):
        # 动态取,不是在类定义时抄一份 —— 否则 monkeypatch 真身的偏好表时
        # 这个替身还拿着旧值,那条区分度测试就白测了。
        return TailscaleManager.NETWORK_PREFERENCE

    def __init__(self, ts_url=None, funnel=None):
        self._ts_url = ts_url
        self._funnel = funnel

    def get_connection_url(self, port):
        return self._ts_url

    def get_funnel_url(self):
        return self._funnel


@pytest.fixture
def fake_ts(monkeypatch):
    def _install(ts_url=None, funnel=None):
        monkeypatch.setattr(
            "core.tailscale_manager.TailscaleManager",
            lambda *a, **k: _FakeManager(ts_url, funnel),
        )

    return _install


# ---------------------------------------------------------------------------
# 一、三条路都在,且形状正确
# ---------------------------------------------------------------------------


def test_all_three_paths_are_listed(fake_ts):
    fake_ts(ts_url="wss://100.99.88.77:9000", funnel="https://box.tail1234.ts.net")
    cands = build_candidates("dev-1", 9000)
    assert [c["kind"] for c in cands] == ["lan", "tailscale", "funnel"]


def test_funnel_url_carries_no_local_port(fake_ts):
    """Funnel 对外就是 443。拼上 :9000 = 语法正确但必然连不上。"""
    fake_ts(ts_url="wss://100.99.88.77:9000", funnel="https://box.tail1234.ts.net")
    funnel = [c for c in build_candidates("dev-1", 9000) if c["kind"] == "funnel"][0]
    assert funnel["url"] == "wss://box.tail1234.ts.net/ws/device/dev-1"
    assert ":9000" not in funnel["url"]


def test_funnel_url_is_wss_not_https(fake_ts):
    """名片里放的是 WebSocket 入口,设备端拿去直接连,不该再自己换协议。"""
    fake_ts(funnel="https://box.tail1234.ts.net")
    funnel = [c for c in build_candidates("dev-1", 9000) if c["kind"] == "funnel"][0]
    assert funnel["url"].startswith("wss://")


def test_every_candidate_targets_this_device(fake_ts):
    fake_ts(ts_url="wss://100.99.88.77:9000", funnel="https://box.tail1234.ts.net")
    for c in build_candidates("watch-7", 9000):
        assert c["url"].endswith("/ws/device/watch-7"), c


# ---------------------------------------------------------------------------
# 二、排序只有一处定义
# ---------------------------------------------------------------------------


def test_order_comes_from_the_single_preference_list(fake_ts, monkeypatch):
    """把权威次序改掉,名片里的次序必须跟着变。

    区分度在这里:如果 build_candidates 自己硬编码了一份顺序,这条会红 ——
    而"两处各写一份"正是排障时看到"名片第一条是局域网、设备却先连公网"的根因。
    """
    monkeypatch.setattr(TailscaleManager, "NETWORK_PREFERENCE", ["funnel", "tailscale", "lan"])
    fake_ts(ts_url="wss://100.99.88.77:9000", funnel="https://box.tail1234.ts.net")
    assert [c["kind"] for c in build_candidates("dev-1", 9000)] == ["funnel", "tailscale", "lan"]


def test_priority_is_dense_when_a_path_is_missing(fake_ts):
    """少一条路时编号不许留洞。

    设备端是"从 priority 1 开始逐个试";留洞会让它跳过一档,
    表现成"明明有 Funnel 却从来没试过"。
    """
    fake_ts(ts_url=None, funnel="https://box.tail1234.ts.net")
    cands = build_candidates("dev-1", 9000)
    assert [c["kind"] for c in cands] == ["lan", "funnel"]
    assert [c["priority"] for c in cands] == [1, 2]


def test_available_paths_are_ordered_by_preference():
    """``get_available_paths`` 只回答"有哪几条",次序仍来自那份常量。"""
    mgr = TailscaleManager()
    mgr._available = True
    mgr.ts_ip = "100.99.88.77"
    paths = mgr.get_available_paths(include_funnel=False)
    assert paths == ["lan", "tailscale"]
    # 与偏好表同序 —— 不是碰巧
    assert paths == [k for k in TailscaleManager.NETWORK_PREFERENCE if k in set(paths)]


def test_lan_is_always_available():
    """本机总在某个网段上;这条没有的话设备在同一 Wi-Fi 下反而连不上。"""
    mgr = TailscaleManager()
    mgr._available = False
    mgr.ts_ip = None
    assert mgr.get_available_paths() == ["lan"]


# ---------------------------------------------------------------------------
# 三、签了必须解得出来（这条是真被漏掉过的）
# ---------------------------------------------------------------------------


def test_candidates_survive_the_link_round_trip():
    """**最要命的一条。**

    ``candidates`` 进 payload、被签名覆盖,但消费端不读 —— 字段在生产端活着、
    在消费端死了,静默丢失,没有任何报错。设备扫完码只剩内网地址。
    """
    cands = [
        {"kind": "lan", "url": "ws://192.168.1.5:9000/ws/device/d1", "priority": 1},
        {"kind": "funnel", "url": "wss://box.tail1234.ts.net/ws/device/d1", "priority": 2},
    ]
    card = create_agent_card("d1", candidates=cands)
    verdict = from_link(to_link(card))
    assert verdict.valid, verdict.reason
    assert verdict.card is not None
    assert verdict.card.candidates == cands


def test_candidates_are_covered_by_the_signature():
    """改了候选路径而签名照收,等于任何人都能把设备重定向到自己的服务器。"""
    card = create_agent_card(
        "d1", candidates=[{"kind": "funnel", "url": "wss://box.ts.net/ws/device/d1", "priority": 1}]
    )
    link = to_link(card)

    import base64
    import json
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(link).query)
    payload = json.loads(base64.urlsafe_b64decode(q["c"][0] + "=="))
    payload["candidates"][0]["url"] = "wss://evil.example/ws/device/d1"
    tampered = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")

    verdict = from_link(f"galaxy://pair?c={tampered}&s={q['s'][0]}")
    assert not verdict.valid, "改了候选路径签名却还认 —— 设备会被重定向"


def test_malformed_candidate_entries_are_dropped_not_crashed():
    """对端塞了非法项时,丢掉那一项即可,不该让整张名片解不出来。"""
    card = create_agent_card("d1")
    card.candidates = [{"kind": "lan", "url": "ws://a/ws/device/d1", "priority": 1}, "not-a-dict", 42]
    verdict = from_link(to_link(card))
    assert verdict.valid, verdict.reason
    assert verdict.card is not None
    assert [c["kind"] for c in verdict.card.candidates] == ["lan"]


# ---------------------------------------------------------------------------
# 四、本机名片真的把候选路径挂上去了
# ---------------------------------------------------------------------------


def test_local_card_has_candidates(fake_ts):
    fake_ts(ts_url="wss://100.99.88.77:9000", funnel="https://box.tail1234.ts.net")
    card = build_local_card()
    assert [c["kind"] for c in card.candidates] == ["lan", "tailscale", "funnel"]


def test_explicit_endpoints_do_not_wipe_out_candidates(fake_ts):
    """早先写成"只在 endpoints 为空时才算候选"。

    结果:任何显式传 endpoints 的调用方拿到的名片候选路径都是空的 —— 多路可达
    对它整个不存在,而且不报错,只表现成"这台设备只能在局域网里配上"。
    """
    fake_ts(funnel="https://box.tail1234.ts.net")
    card = build_local_card(endpoints={"websocket": "ws://10.0.0.9:9000/ws/device/x"})
    assert card.endpoints["websocket"] == "ws://10.0.0.9:9000/ws/device/x", "显式端点被覆盖了"
    assert [c["kind"] for c in card.candidates] == ["lan", "funnel"]


def test_lan_only_install_still_gets_a_card(fake_ts):
    """没装 Tailscale 只是少两条路,不该让名片发不出来。"""
    fake_ts(ts_url=None, funnel=None)
    card = build_local_card()
    assert [c["kind"] for c in card.candidates] == ["lan"]
    assert card.endpoints.get("websocket")


def test_tailscale_blowing_up_degrades_to_lan(monkeypatch):
    """Tailscale 那边抛异常时退回只有局域网,而不是把整张名片带崩。"""

    def _boom(*a, **k):
        raise RuntimeError("tailscaled 没起来")

    monkeypatch.setattr("core.tailscale_manager.TailscaleManager", _boom)
    assert [c["kind"] for c in build_candidates("d1", 9000)] == ["lan"]
