"""本地模式(只用这台电脑)下,按设计就该这样的几件事不算「降级」。

所有者 Windows 真机日志(本地模式):

    ⚠ 消息总线                单机模式正常(进程内总线)· 没起 NATS,跨设备分发不可用
    ⚠ L4 增强模块             已加载 7 个组件 · 未接入主循环（自主性由常驻注意力循环承担）
    15:24:13 | WARNING | mDNS: failed to start:
    ✓ 就绪 · 7 正常 · 4 降级

* 本地模式不起 NATS 是对的 —— 不该画 ⚠、不该进降级栏;
* 本地模式不入 tailnet、不往局域网广播自己(没有别的设备要来找它;那条原因为空的 mDNS 告警也就不会有);
* L4 那一行按设计就不接主循环 —— 说清楚,但不算降级;
* mDNS 真起不来时(跨设备模式),告警要说得出原因 —— 不能是一个冒号后面什么都没有。
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from launcher.bus_phase import bus_phase


class _Svc:
    def __init__(self, nats):
        self._nats = nats
        self.calls = []
        self.tailnet = SimpleNamespace(
            not_on_tailnet_details=lambda: [("Tailscale", "未安装 (LAN 直连模式)", "warn")],
            start_lan_discovery=lambda: (self.calls.append("lan"), ("局域网发现", "已发布 _galaxy._tcp", "ok"))[1],
        )

    async def start_nats(self):
        return self._nats

    async def start_tailscale(self):
        self.calls.append("tailscale")
        raise RuntimeError("Tailscale not installed")


_OFF = {"ok": False, "url": "", "error": "", "hint": "", "disabled": True, "reason": "本地模式用不到消息总线"}


def _local(monkeypatch):
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-local")


def test_local_mode_without_nats_is_fine_and_does_not_announce_itself(monkeypatch):
    _local(monkeypatch)
    svc = _Svc(_OFF)
    value, status, details, hint = asyncio.run(bus_phase(svc))
    assert status == "ok" and hint is None, "本地模式不起 NATS 被当成了降级"
    assert "本地模式" in value
    assert svc.calls == [], "本地模式还在入 tailnet / 往局域网广播"
    assert any(d[0] == "局域网发现" and d[2] == "info" for d in details)


def test_cross_device_mode_still_does_all_three_and_degrades_honestly(monkeypatch):
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    svc = _Svc({"ok": False, "url": "", "error": "WinError 4551", "hint": "", "disabled": False})
    value, status, details, hint = asyncio.run(bus_phase(svc))
    assert status == "warn" and "WinError 4551" in value and hint
    assert svc.calls == ["tailscale", "lan"]
    assert ("Tailscale", "未安装 (LAN 直连模式)", "warn") in details


def test_a_working_bus_is_green_in_either_mode(monkeypatch):
    _local(monkeypatch)
    value, status, _d, hint = asyncio.run(bus_phase(_Svc({"ok": True, "url": "nats://localhost:4222"})))
    assert (value, status, hint) == ("nats://localhost:4222", "ok", None)


def test_the_l4_line_is_said_but_not_counted_as_degraded():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    block = src.split("# ── L4 增强模块")[1].split("# (API 网关已在第一阶段绑定")[0]
    tail = block[block.index("未接入主循环") :]
    assert '"info",' in tail[:600] and '"warn",' not in tail[:600]


def test_mdns_says_why_it_could_not_start(monkeypatch, caplog):
    import galaxy_gateway.mdns_announcer as m

    class NonUniqueNameException(Exception):
        """zeroconf 的这个异常没有消息文本 —— 日志里就只剩一个冒号。"""

    class _ZC:
        def register_service(self, info, **kw):
            raise NonUniqueNameException()

    monkeypatch.setattr(m, "_ensure_zeroconf", lambda: True)
    monkeypatch.setattr(m, "_Zeroconf", _ZC, raising=False)
    monkeypatch.setattr(m, "_ServiceInfo", lambda **kw: object(), raising=False)
    a = m.MdnsAnnouncer(port=9000)
    monkeypatch.setattr(a, "get_lan_ip", lambda: "192.168.1.5")
    with caplog.at_level(logging.WARNING, logger=m.logger.name):
        assert a.start() is False
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "NonUniqueNameException" in said, f"原因又是空的: {said!r}"


def test_mdns_picks_a_free_name_instead_of_failing(monkeypatch):
    """同一网段里另一台 Galaxy(或上一次没注销干净的广播)占着名字时,换一个名字照样发布。"""
    import galaxy_gateway.mdns_announcer as m

    seen = {}

    class _ZC:
        def register_service(self, info, **kw):
            seen.update(kw)

    monkeypatch.setattr(m, "_ensure_zeroconf", lambda: True)
    monkeypatch.setattr(m, "_Zeroconf", _ZC, raising=False)
    monkeypatch.setattr(m, "_ServiceInfo", lambda **kw: object(), raising=False)
    a = m.MdnsAnnouncer(port=9000)
    monkeypatch.setattr(a, "get_lan_ip", lambda: "192.168.1.5")
    assert a.start() is True
    assert seen.get("allow_name_change") is True
