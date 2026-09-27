"""主脑要能在局域网里看见电脑 —— 而且一台电脑只算一台。

一台 Mac 同时广播 ``_device-info``(带型号)、``_ssh``、``_smb``、``_rfb``;Linux 开了
avahi 广播 ``_workstation``。原来 mDNS 只浏览 ``_galaxy`` / Matter / HomeKit / Chromecast,
所以电脑根本不出现;就算加上服务类型,每条广播也会各自成为一个候选 —— 同一台电脑在
列表里出现四次。

这组测试:

* 解析部分(``lan_computers``)直接单测:型号 → 平台、能不能远程登录、合成键;
* 合成部分走 ``LanDiscovery.ingest_service`` 真实入口 + 真实接入平面,断言四条广播
  只产生**一个**候选,且认得出它是 Mac 笔记本、能远程登录;
* 下线:关掉屏幕共享不算这台电脑不在了,最后一条广播消失才算;
* 还有一条**真的 zeroconf**:真广播 ``_ssh._tcp`` + 真浏览,确认默认就会去听电脑那几类。
"""

from __future__ import annotations

import socket
import time

import pytest

from core import lan_computers as lc
from core.device_onboarding.service import get_onboarding_service, reset_onboarding_service


@pytest.fixture
def plane(tmp_path, monkeypatch):
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "onboarding"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_URL", raising=False)
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()
    yield get_onboarding_service()
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()


def _ucm():
    from core.unified.connection_manager import get_unified_connection_manager

    return get_unified_connection_manager()


# ── 认出"这是什么电脑" ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "model,expected",
    [
        ("MacBookPro18,3", "macbook"),  # 笔记本
        ("MacBookAir10,1", "macbook"),
        ("Macmini9,1", "mac"),
        ("iMac21,1", "mac"),
        ("MacStudio13,1", "mac"),
        ("", "computer"),  # 没型号就别猜
    ],
)
def test_apple_model_becomes_a_platform_hint(model, expected):
    assert lc.computer_hint({"_device-info._tcp.local."}, {"model": model} if model else {}) == expected


def test_hints_fall_back_to_declared_os_then_to_the_service_mix():
    assert lc.computer_hint({"_ssh._tcp.local."}, {"os": "Windows 11 Pro"}) == "windows"
    assert lc.computer_hint({"_ssh._tcp.local."}, {"platform": "linux/amd64"}) == "linux"
    # 只有 avahi 的 _workstation:基本就是 Linux
    assert lc.computer_hint({"_workstation._tcp.local."}, {}) == "linux"
    # 只有 _ssh、什么线索都没有:如实说"一台电脑",不猜系统
    assert lc.computer_hint({"_ssh._tcp.local."}, {}) == "computer"


def test_the_hint_words_are_ones_taxonomy_already_understands():
    """猜出来的词必须能被 taxonomy 归类,否则等于没猜。"""
    from core.device_onboarding.taxonomy import classify_type

    assert classify_type("macbook").aip_device_type == "macos_laptop"
    assert classify_type("mac").aip_device_type == "macos_desktop"
    assert classify_type("windows").aip_device_type == "windows_desktop"
    assert classify_type("linux").aip_device_type == "linux_desktop"


def test_remote_login_is_only_true_when_ssh_is_actually_advertised():
    assert lc.has_remote_login({"_ssh._tcp.local."}) is True
    assert lc.has_remote_login({"_sftp-ssh._tcp.local."}) is True
    # 只有文件共享和屏幕共享 —— 登不进去,就不该提议走远程接入那条路
    assert lc.has_remote_login({"_smb._tcp.local.", "_rfb._tcp.local."}) is False


def test_all_services_of_one_machine_share_a_key():
    props = {"mdns_server": "studio.local."}
    keys = {
        lc.machine_key(f"Danny's Mac._{s}._tcp.local.", props) for s in ("ssh", "smb", "rfb", "device-info", "sftp-ssh")
    }
    assert keys == {"studio.local"}  # 实例名再怎么不同,机器只有一个
    # 拿不到目标主机名时退回实例名
    assert lc.machine_key("studio._ssh._tcp.local.", {}) == "studio"


# ── 一台电脑只算一台候选 ─────────────────────────────────────────────────────────

_MAC = [
    ("_device-info._tcp.local.", "Danny’s MacBook Pro._device-info._tcp.local.", {"model": "MacBookPro18,3"}),
    ("_ssh._tcp.local.", "Danny’s MacBook Pro._ssh._tcp.local.", {}),
    ("_sftp-ssh._tcp.local.", "Danny’s MacBook Pro._sftp-ssh._tcp.local.", {}),
    ("_smb._tcp.local.", "Danny’s MacBook Pro._smb._tcp.local.", {}),
]


def _announce_mac(disco, server="dannys-macbook-pro.local."):
    for stype, name, props in _MAC:
        disco.ingest_service(stype, name, "192.168.1.42", 22, {**props, "mdns_server": server})


def test_four_broadcasts_from_one_mac_make_one_candidate(plane):
    from core.lan_discovery import LanDiscovery

    disco = LanDiscovery()
    _announce_mac(disco)

    [cand] = plane.overview()["candidates"]  # 一台,不是四台
    assert cand["aip_device_type"] == "macos_laptop"  # 认出是 Mac 笔记本
    assert cand["properties"]["remote_login"] is True  # 能远程登录
    assert cand["properties"]["model"] == "MacBookPro18,3"
    assert cand["properties"]["mdns_services"] == [
        "_device-info._tcp.local.",
        "_sftp-ssh._tcp.local.",
        "_smb._tcp.local.",
        "_ssh._tcp.local.",
    ]
    assert cand["addresses"] == ["192.168.1.42"]


def test_a_windows_box_with_only_openssh_is_still_a_computer(plane):
    from core.lan_discovery import LanDiscovery

    disco = LanDiscovery()
    disco.ingest_service(
        "_ssh._tcp.local.", "WORKPC._ssh._tcp.local.", "192.168.1.9", 22, {"mdns_server": "workpc.local."}
    )
    [cand] = plane.overview()["candidates"]
    # 没有型号线索 → 如实"一台电脑",不硬猜成 Windows;但远程登录这一点是确定的
    assert cand["properties"]["remote_login"] is True
    assert cand["properties"]["computer_hint"] == "computer"


def test_turning_off_screen_sharing_does_not_make_the_computer_disappear(plane):
    from core.lan_discovery import LanDiscovery

    disco = LanDiscovery()
    _announce_mac(disco)
    disco.ingest_service(
        "_rfb._tcp.local.",
        "Danny’s MacBook Pro._rfb._tcp.local.",
        "192.168.1.42",
        5900,
        {"mdns_server": "dannys-macbook-pro.local."},
    )
    [cand] = plane.overview()["candidates"]
    cid = cand["candidate_id"]

    # 关掉屏幕共享:机器还在
    disco.service_removed("_rfb._tcp.local.", "Danny’s MacBook Pro._rfb._tcp.local.")
    assert plane.candidates.get(cid).present is True

    # 剩下四条也逐条消失 → 最后一条走的时候才算"不在了"
    for stype, name, _ in _MAC[:-1]:
        disco.service_removed(stype, name)
        assert plane.candidates.get(cid).present is True
    disco.service_removed(_MAC[-1][0], _MAC[-1][1])
    assert plane.candidates.get(cid).present is False


def test_non_computer_services_keep_their_old_per_name_behaviour(plane):
    """电视/投屏那些逐字保持原样:一条广播一个候选,key 还是 mDNS 名。"""
    from core.lan_discovery import LanDiscovery

    disco = LanDiscovery()
    disco.ingest_service("_googlecast._tcp.local.", "LivingRoomTV._googlecast._tcp.local.", "192.168.1.60", 8009, {})
    [cand] = plane.overview()["candidates"]
    assert cand["key"] == "LivingRoomTV._googlecast._tcp.local."
    assert "is_computer" not in cand["properties"]


# ── 真 zeroconf:默认真的会去听电脑那几类 ────────────────────────────────────────


def test_a_real_ssh_broadcast_is_actually_browsed(plane):
    zeroconf = pytest.importorskip("zeroconf")
    from core.lan_discovery import LanDiscovery, _service_types

    assert "_ssh._tcp.local." in _service_types(), "默认就该浏览 _ssh —— 不然电脑永远看不见"

    disco = LanDiscovery()
    seen: list = []
    original = disco.ingest_service

    def spy(stype, name, address="", port=0, properties=None):
        seen.append((stype, name))
        return original(stype, name, address, port, properties)

    disco.ingest_service = spy  # type: ignore[method-assign]

    zc = zeroconf.Zeroconf()
    info = zeroconf.ServiceInfo(
        "_ssh._tcp.local.",
        "pytest-host._ssh._tcp.local.",
        addresses=[socket.inet_aton("127.0.0.1")],
        port=22,
        properties={"model": "Macmini9,1"},
        server="pytest-host.local.",
    )
    try:
        zc.register_service(info)
        disco.start()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not any(n.startswith("pytest-host") for _t, n in seen):
            time.sleep(0.2)
    finally:
        disco.stop()
        try:
            zc.unregister_service(info)
        finally:
            from core.zeroconf_close import close_zeroconf

            close_zeroconf(zc, label="test")

    assert any(n.startswith("pytest-host") for _t, n in seen), f"没收到自己的广播: {seen}"
    cands = [c for c in plane.overview()["candidates"] if c["key"].startswith("pytest-host")]
    assert cands, "收到了广播但没成为候选"
    assert cands[0]["properties"]["remote_login"] is True
    assert cands[0]["aip_device_type"] == "macos_desktop"  # Macmini → 台式
