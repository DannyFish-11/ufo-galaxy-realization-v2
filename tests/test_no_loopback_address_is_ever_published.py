#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_no_loopback_address_is_ever_published.py

**发给别的设备的地址,永远不许是环回地址。**

问题的形状
==========
仓里有两处会把"本机局域网地址"发出去:

* :func:`core.agent_card.build_candidates` —— 写进配对名片的候选路径,
  ``kind="lan"``、``priority=1``,手机拿到后**第一个**就试它;
* :class:`galaxy_gateway.mdns_announcer.MdnsAnnouncer` —— 广播到整个局域网。

两者的探测函数在失败时都返回 ``"127.0.0.1"``。而 ``127.0.0.1`` 在**收到它的那台
设备**上指向那台设备自己 —— 一个格式完全正确、却必然连不通的地址。

这类兜底比抛异常更糟:故障被伪装成了成功。没有异常、没有告警,只有连不上,
而排查方向会被引向"网络有问题",真正的原因是"网关当时没探到自己的地址"。

顺带收口的事
============
探测逻辑改前在仓里有**五份**各写各的实现,三种失败语义
(``""`` / 抛异常 / ``"127.0.0.1"``)、两种探测目标。

探测目标的差别不是风格问题:``connect(("8.8.8.8", 80))`` 要求内核选得出一条到
**公网**的路,一台只连着路由器、路由器没上行的机器会 ``ENETUNREACH``;
而 ``10.255.255.255`` 那份照常给出正确答案。"局域网通、公网不通"恰恰是本产品
最主要的部署形态 —— 同一台机器上,五个调用点会得到两种不同的结论。

现在统一走 :mod:`core.lan_address`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import agent_card, lan_address
from core.tailscale_manager import TailscaleManager

REPO = Path(__file__).resolve().parent.parent


# ── is_loopback 的判据 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.0.0.2",
        "127.1.2.3",
        "127.255.255.254",  # 整个 /8 都是环回,不只是 .0.0.1
        "localhost",
        "LocalHost",
        "localhost.",  # DNS 的完全限定形态
        "::1",
        "0:0:0:0:0:0:0:1",
        "::",
        "0.0.0.0",  # "监听所有接口"的写法,当连接目标用时到不了任何远端
    ],
)
def test_loopback_forms_are_recognised(host):
    assert lan_address.is_loopback(host) is True


@pytest.mark.parametrize("host", ["192.168.1.5", "10.0.0.1", "100.64.12.34", "2001:db8::1", "galaxy.local", ""])
def test_real_addresses_are_not_flagged(host):
    # 反向保险:判得太宽会把真能用的地址挡掉,那比原缺陷更糟。
    assert lan_address.is_loopback(host) is False


# ── 探测口本身 ───────────────────────────────────────────────────────────


def test_detect_returns_none_rather_than_loopback(monkeypatch):
    """所有探测手段都只给出环回时,必须返回 None —— 不是 "127.0.0.1"。"""
    monkeypatch.setattr(lan_address, "_probe", lambda target: "127.0.0.1")
    monkeypatch.setattr(lan_address, "_from_hostname", lambda: ["127.0.0.1", "::1"])
    assert lan_address.detect_lan_ip() is None


def test_detect_falls_through_to_the_second_probe_target(monkeypatch):
    """第一个探测目标不可达时,必须继续试第二个。

    这条守的正是"局域网通、公网不通"那个场景:私网目标能选出路,公网目标不能
    (或反之)。只试一个的实现会在那种机器上误判成"没有局域网地址"。
    """
    seen = []

    def fake_probe(target):
        seen.append(target[0])
        return "192.168.1.7" if target[0] == "8.8.8.8" else None

    monkeypatch.setattr(lan_address, "_probe", fake_probe)
    assert lan_address.detect_lan_ip() == "192.168.1.7"
    assert len(seen) >= 2, f"第一个目标失败后没有继续试:{seen}"


def test_or_empty_wrapper_keeps_the_old_contract(monkeypatch):
    # launcher/services 与 core/nats_bus 原本就把空串当"没有",迁移不该改它们的契约。
    monkeypatch.setattr(lan_address, "detect_lan_ip", lambda: None)
    assert lan_address.detect_lan_ip_or_empty() == ""


# ── 名片候选路径 ─────────────────────────────────────────────────────────


class _FakeManager:
    """容器里没有真 tailscale,给一个可控替身。"""

    @property
    def NETWORK_PREFERENCE(self):
        return TailscaleManager.NETWORK_PREFERENCE

    def __init__(self, ts_url=None, funnel=None):
        self._ts_url, self._funnel = ts_url, funnel

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


def test_lan_candidate_is_omitted_not_poisoned(monkeypatch, fake_ts):
    """探不到局域网地址时,``lan`` 这条候选**不出现**,而不是指向 127.0.0.1。"""
    fake_ts(ts_url="ws://100.64.0.9:9000", funnel="https://x.ts.net")
    monkeypatch.setattr(agent_card, "_local_ip", lambda: None)

    cands = agent_card.build_candidates("dev-1", 9000)

    kinds = [c["kind"] for c in cands]
    assert "lan" not in kinds, f"探不到地址却仍发了 lan 候选:{cands}"
    assert kinds, "不该把整张候选表清空 —— tailscale/funnel 还是可达的"
    for c in cands:
        assert "127.0.0.1" not in c["url"], f"候选里出现环回地址:{c}"


def test_priorities_stay_contiguous_when_lan_is_omitted(monkeypatch, fake_ts):
    """少一条路不该在编号上留洞。

    设备端是"从 1 开始逐个试"。如果 lan 缺席却仍占着 priority=1,
    tailscale 会拿到 2、funnel 拿到 3,中间那个 1 是空的 —— 取决于设备端怎么写,
    可能表现为"跳过第一档"或"第一档永远失败"。
    """
    fake_ts(ts_url="ws://100.64.0.9:9000", funnel="https://x.ts.net")
    monkeypatch.setattr(agent_card, "_local_ip", lambda: None)

    cands = agent_card.build_candidates("dev-1", 9000)
    assert [c["priority"] for c in cands] == list(range(1, len(cands) + 1))


def test_lan_candidate_is_present_when_the_address_is_real(monkeypatch, fake_ts):
    # 反向保险:别把 lan 这条路整个弄丢了。
    fake_ts()
    monkeypatch.setattr(agent_card, "_local_ip", lambda: "192.168.1.42")
    cands = agent_card.build_candidates("dev-1", 9000)
    assert cands[0]["kind"] == "lan"
    assert cands[0]["url"] == "ws://192.168.1.42:9000/ws/device/dev-1"
    assert cands[0]["priority"] == 1


def test_card_endpoint_is_omitted_when_address_is_unknown(monkeypatch, fake_ts):
    """名片的 ``endpoints["websocket"]`` 同样不许写环回。

    消费端无从分辨"这台机器就在本机"和"这台机器当时没探到自己的地址" ——
    两者在名片上长得一模一样。
    """
    fake_ts()
    monkeypatch.setattr(agent_card, "_local_ip", lambda: None)
    card = agent_card.build_local_card()
    assert "127.0.0.1" not in str(card.endpoints.get("websocket", "")), card.endpoints


# ── mDNS 广播 ────────────────────────────────────────────────────────────


def test_mdns_refuses_to_broadcast_a_loopback_address(monkeypatch):
    """探不到地址时宁可不广播。

    广播出去的后果不是"发现失败",而是"发现成功但连不上" ——
    后者排查成本高得多,因为设备侧看到的是一个格式正确的地址。
    """
    from galaxy_gateway import mdns_announcer as mod

    registered = []

    class _FakeZc:
        def register_service(self, info):
            registered.append(info)

        def close(self):
            pass

    # zeroconf 在本容器里没装;直接把懒加载的两个全局塞成替身,
    # 让 _ensure_zeroconf 的早退不至于把这条用例变成"什么都没测"。
    monkeypatch.setattr(mod, "_Zeroconf", _FakeZc)
    monkeypatch.setattr(mod, "_ServiceInfo", lambda **kw: kw)
    monkeypatch.setattr(mod.MdnsAnnouncer, "get_lan_ip", staticmethod(lambda: None))

    announcer = mod.MdnsAnnouncer(port=9000)
    assert announcer.start() is False
    assert registered == [], "探不到地址却仍然注册了 mDNS 服务"


def test_mdns_broadcasts_when_the_address_is_real(monkeypatch):
    # 反向保险:这条用例要是没了,上面那条可以靠"永远不广播"作弊通过。
    from galaxy_gateway import mdns_announcer as mod

    registered = []

    class _FakeZc:
        def register_service(self, info):
            registered.append(info)

        def close(self):
            pass

    monkeypatch.setattr(mod, "_Zeroconf", _FakeZc)
    monkeypatch.setattr(mod, "_ServiceInfo", lambda **kw: kw)
    monkeypatch.setattr(mod.MdnsAnnouncer, "get_lan_ip", staticmethod(lambda: "192.168.1.42"))

    announcer = mod.MdnsAnnouncer(port=9000)
    try:
        assert announcer.start() is True
        assert len(registered) == 1
    finally:
        announcer.stop()


# ── 防止再长出第六份实现 ──────────────────────────────────────────────────


def test_no_module_grows_its_own_lan_ip_probe():
    """探测逻辑只许有一份。

    这条守的是"收口会不会被慢慢磨掉"。上一次它散成五份并不是谁一次性写错的,
    是每个需要用的地方就地写了一个 —— 每一处单看都合理。
    """
    probe_call = re.compile(r"""connect\(\s*\(\s*["'](?:8\.8\.8\.8|10\.255\.255\.255)["']""")
    offenders = []
    for path in sorted(REPO.glob("**/*.py")):
        parts = set(path.parts)
        if parts & {".venv", "venv", "external", "node_modules", "build", "dist", "__pycache__"}:
            continue
        if path.name in ("lan_address.py", Path(__file__).name):
            continue  # 权威实现自己,和本文件
        text = path.read_text(encoding="utf-8", errors="replace")
        if probe_call.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, "这些文件又自己写了一份局域网地址探测,应改用 core.lan_address:\n  " + "\n  ".join(offenders)
