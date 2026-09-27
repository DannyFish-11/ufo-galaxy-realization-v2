"""插在主脑本机上的设备:串口、蓝牙(BlueZ / D-Bus)、CAN 的发现 → 候选 → 接入 → 在线。

sysfs 用临时目录搭出与内核一致的结构(``/sys/class/tty/*/device`` 是指向 USB 接口目录的
符号链接,``/sys/class/net/*/type`` 为 280 即 CAN);BlueZ 用 ``busctl --json`` 的真实输出
格式;CAN 被动监听用一个吐 ``struct can_frame`` 字节的假 socket。其余全走真实入口
(发现函数 / OnboardingService / UDM / UCM)。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import struct

import pytest

from core.device_onboarding import local_buses as lb
from core.device_onboarding.service import get_onboarding_service, reset_onboarding_service


@pytest.fixture
def plane(tmp_path, monkeypatch):
    from core.mesh.mesh_auto_enrollment import reset_auto_enrollment_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import reset_unified_device_manager

    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "onboarding"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GALAXY_ONBOARDING_AUTO", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_URL", raising=False)
    monkeypatch.delenv("HOME_ASSISTANT_TOKEN", raising=False)
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()
    reset_auto_enrollment_service()
    yield get_onboarding_service()
    reset_unified_device_manager()
    reset_unified_connection_manager()
    reset_onboarding_service()
    reset_auto_enrollment_service()


def _udm():
    from core.unified.device_manager import get_unified_device_manager

    return get_unified_device_manager()


def _ucm():
    from core.unified.connection_manager import get_unified_connection_manager

    return get_unified_connection_manager()


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


# ── 串口 ─────────────────────────────────────────────────────────────────────────


def _fake_usb_tty(root, tty, usb, **attrs):
    """/sys/devices/.../<usb>/<usb>:1.0/<tty> + /sys/class/tty/<tty>/device → 接口目录。"""
    usb_dir = os.path.join(root, "devices", "pci0000:00", "0000:00:14.0", "usb1", usb)
    iface = os.path.join(usb_dir, f"{usb}:1.0")
    os.makedirs(os.path.join(iface, tty), exist_ok=True)
    for k, v in attrs.items():
        _write(os.path.join(usb_dir, k), v)
    cls = os.path.join(root, "class", "tty", tty)
    os.makedirs(cls, exist_ok=True)
    os.symlink(iface, os.path.join(cls, "device"))


def test_sysfs_serial_listing_matches_pyserial_fields(tmp_path):
    root = str(tmp_path / "sys")
    _fake_usb_tty(
        root,
        "ttyACM0",
        "1-1.2",
        idVendor="2341",
        idProduct="0043",
        serial="75833353",
        manufacturer="Arduino",
        product="Uno",
    )
    _fake_usb_tty(root, "ttyUSB0", "1-1.3", idVendor="1A86", idProduct="7523", product="USB Serial")
    # 主板上的 8250 占位口与虚拟终端:不算串口设备
    os.makedirs(os.path.join(root, "class", "tty", "ttyS0", "device"))
    os.makedirs(os.path.join(root, "class", "tty", "tty1"))

    rows = lb.sysfs_serial_ports(root=root, dev="/dev")
    assert [r["device"] for r in rows] == ["/dev/ttyACM0", "/dev/ttyUSB0"]
    uno, ch340 = rows
    assert (uno["vid"], uno["pid"], uno["serial_number"], uno["location"]) == ("2341", "0043", "75833353", "1-1.2")
    assert (ch340["vid"], ch340["serial_number"]) == ("1a86", "")  # 厂商号统一小写


def test_serial_board_identity_follows_the_board_not_the_port():
    a = lb.serial_observation({"device": "/dev/ttyACM0", "vid": "2341", "pid": "0043", "serial_number": "758"})
    b = lb.serial_observation({"device": "/dev/ttyACM3", "vid": "2341", "pid": "0043", "serial_number": "758"})
    assert a.key == b.key == "usb:2341:0043:758"
    assert a.identity["device_id"] == b.identity["device_id"] == "serial-usb-2341-0043-758"
    assert a.kind_hint == "arduino"
    # 通用 USB 转串口芯片不猜是什么板子;没有序列号就按插口区分
    c = lb.serial_observation({"device": "/dev/ttyUSB0", "vid": "1a86", "pid": "7523", "location": "1-1.3"})
    assert (c.kind_hint, c.key) == ("iot", "usb:1a86:7523@1-1.3")


def test_serial_device_is_a_candidate_then_a_member_with_presence(plane, monkeypatch):
    port = {
        "device": "/dev/ttyACM0",
        "vid": "2341",
        "pid": "0043",
        "serial_number": "758",
        "manufacturer": "Arduino",
        "product": "Uno",
    }
    plugged = [port]
    monkeypatch.setattr(lb, "list_serial_ports", lambda: list(plugged))

    assert asyncio.run(lb.scan_serial()) == 1
    [cand] = plane.overview()["candidates"]
    assert (cand["source"], cand["join_path"], cand["human_step"]) == ("serial", "local_bus", "approve")
    assert cand["aip_device_type"] == "embedded_arduino"

    out = asyncio.run(plane.join(cand["candidate_id"]))
    assert out["success"] and out["outcome"]["kind"] == "joined"
    d = _udm().get_device("serial-usb-2341-0043-758")
    assert (d.transport, d.execution_model) == ("serial", "adapter_bridged_device")
    assert d.metadata["transport_target"] == "/dev/ttyACM0"

    asyncio.run(lb.scan_serial())
    assert _ucm().get_presence_view()["serial-usb-2341-0043-758"]["online"] is True

    plugged.clear()  # 拔掉
    asyncio.run(lb.scan_serial())
    assert _ucm().get_presence_view()["serial-usb-2341-0043-758"]["online"] is False
    assert _udm().get_device("serial-usb-2341-0043-758") is not None  # 成员还在,只是不在线


# ── 蓝牙(BlueZ,经 D-Bus)────────────────────────────────────────────────────────

#: ``busctl --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects``
#: 的输出格式(variant 写成 {"type","data"},见 busctl(1))。
_BLUEZ = {
    "type": "a{oa{sa{sv}}}",
    "data": [
        {
            "/org/bluez/hci0": {"org.bluez.Adapter1": {"Address": {"type": "s", "data": "00:1A:7D:DA:71:13"}}},
            "/org/bluez/hci0/dev_F4_7B_09_AA_BB_CC": {
                "org.bluez.Device1": {
                    "Address": {"type": "s", "data": "f4:7b:09:aa:bb:cc"},
                    "Alias": {"type": "s", "data": "Pixel Watch"},
                    "Icon": {"type": "s", "data": "watch"},
                    "Paired": {"type": "b", "data": True},
                    "Connected": {"type": "b", "data": True},
                    "RSSI": {"type": "n", "data": -58},
                    "UUIDs": {"type": "as", "data": ["0000180f-0000-1000-8000-00805f9b34fb"]},
                    "Adapter": {"type": "o", "data": "/org/bluez/hci0"},
                },
                "org.freedesktop.DBus.Properties": {},
            },
            "/org/bluez/hci0/dev_C8_0F_10_00_00_01": {
                "org.bluez.Device1": {
                    "Address": {"type": "s", "data": "C8:0F:10:00:00:01"},
                    "Name": {"type": "s", "data": "MJ_HT_V1"},
                    "Connected": {"type": "b", "data": False},
                }
            },
        }
    ],
}


def test_bluez_devices_parsed_from_busctl_json():
    objs = lb.parse_busctl_managed_objects(json.dumps(_BLUEZ))
    watch, sensor = sorted(lb.bluez_observations(objs), key=lambda o: o.name)[::-1]
    assert (watch.key, watch.name, watch.kind_hint) == ("F4:7B:09:AA:BB:CC", "Pixel Watch", "watch")
    assert watch.properties["connected"] is True and watch.properties["rssi"] == -58
    assert watch.identity == {"mac": "F4:7B:09:AA:BB:CC"}
    assert (sensor.name, sensor.kind_hint, sensor.properties["connected"]) == ("MJ_HT_V1", "iot", False)
    assert lb.parse_busctl_managed_objects("not json") == {}


def test_bluetooth_candidates_go_through_home_assistant(plane, monkeypatch):
    monkeypatch.setattr(lb, "_busctl_managed_objects", lambda: lb.parse_busctl_managed_objects(json.dumps(_BLUEZ)))
    assert asyncio.run(lb.scan_bluetooth()) == 2
    cands = plane.overview()["candidates"]
    assert {c["join_path"] for c in cands} == {"via_home_assistant"}
    out = asyncio.run(plane.join(cands[0]["candidate_id"]))
    assert out["outcome"]["kind"] == "needs_human" and "Home Assistant" in out["outcome"]["needs"]["what"]


def test_no_system_bus_means_no_bluetooth_not_an_error(monkeypatch):
    # 真的去调:这台机器(CI 容器)没有系统总线 / BlueZ,应当安静地返回空
    assert isinstance(lb._busctl_managed_objects(timeout_s=5.0), dict)
    monkeypatch.setattr(lb.shutil, "which", lambda _n: None)
    assert lb._busctl_managed_objects() == {}


# ── CAN(SocketCAN)──────────────────────────────────────────────────────────────


def _fake_net(root, name, *, type_, flags, operstate, hw):
    d = os.path.join(root, "class", "net", name)
    _write(os.path.join(d, "type"), type_)
    _write(os.path.join(d, "flags"), flags)
    _write(os.path.join(d, "operstate"), operstate)
    if hw:
        os.makedirs(os.path.join(d, "device"))


def test_can_interfaces_found_in_sysfs(tmp_path):
    root = str(tmp_path / "sys")
    _fake_net(root, "can0", type_="280", flags="0x40081", operstate="up", hw=True)
    _fake_net(root, "vcan0", type_="280", flags="0x80", operstate="down", hw=False)
    _fake_net(root, "eth0", type_="1", flags="0x1003", operstate="up", hw=True)
    assert lb.can_interfaces(root) == [
        {"interface": "can0", "up": True, "operstate": "up", "virtual": False},
        {"interface": "vcan0", "up": False, "operstate": "down", "virtual": True},
    ]


class _FakeCanSocket:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False
        self.sent = []

    def settimeout(self, _t):
        pass

    def recv(self, _n):
        if self._frames:
            return self._frames.pop(0)
        raise socket.timeout()

    def send(self, data):  # 被动监听绝不应该发
        self.sent.append(data)

    def close(self):
        self.closed = True


def _frame(can_id, data=b""):
    return struct.pack("=IB3x8s", can_id, len(data), data.ljust(8, b"\0"))


def test_can_passive_listen_collects_message_ids_and_never_sends():
    frames = [
        _frame(0x123, b"\x01"),
        _frame(0x123, b"\x02"),
        _frame(0x18FEF100 | 0x80000000, b"\xff" * 8),  # J1939 扩展帧
        _frame(0x20000004),  # 错误帧:不算节点
    ]
    fake = _FakeCanSocket(frames)
    ids = lb.listen_can_ids("can0", 0.5, sock_factory=lambda _n: fake)
    assert ids == ["123", "18fef100"]
    assert fake.closed and fake.sent == []
    assert lb.listen_can_ids("can0", 0) == []  # 0 = 关闭监听


def test_can_bus_becomes_a_member_and_tracks_link_state(plane, monkeypatch):
    state = {"up": True}
    monkeypatch.setattr(
        lb, "can_interfaces", lambda: [{"interface": "can0", "up": state["up"], "operstate": "up", "virtual": False}]
    )
    monkeypatch.setattr(lb, "listen_can_ids", lambda _i, _s: ["123", "18fef100"])
    asyncio.run(lb.scan_can())
    [cand] = plane.overview()["candidates"]
    assert cand["join_path"] == "local_bus" and "2 个报文 ID" in cand["name"]
    asyncio.run(plane.join(cand["candidate_id"]))
    d = _udm().get_device("can-can0")
    assert (d.transport, d.metadata["transport_target"]) == ("canbus", "can0")

    asyncio.run(lb.scan_can())
    assert _ucm().get_presence_view()["can-can0"]["online"] is True
    state["up"] = False
    asyncio.run(lb.scan_can())
    assert _ucm().get_presence_view()["can-can0"]["online"] is False


# ── 汇入统一扫描 ─────────────────────────────────────────────────────────────────


def test_scan_once_runs_local_buses_and_one_failure_does_not_stop_the_rest(plane, monkeypatch):
    from core.device_onboarding import sources

    monkeypatch.setenv("GALAXY_ONBOARDING_SSDP", "false")

    def boom():
        raise RuntimeError("usb subsystem exploded")

    monkeypatch.setattr(lb, "list_serial_ports", boom)
    monkeypatch.setattr(lb, "_busctl_managed_objects", lambda: {})
    monkeypatch.setattr(
        lb, "can_interfaces", lambda: [{"interface": "vcan0", "up": False, "operstate": "down", "virtual": True}]
    )
    out = asyncio.run(sources.scan_once())
    assert out["serial"].startswith("error:")
    assert (out["bluetooth"], out["can"]) == (0, 1)


def test_each_local_bus_can_be_switched_off(plane, monkeypatch):
    for env in ("GALAXY_ONBOARDING_SERIAL", "GALAXY_ONBOARDING_BLUETOOTH", "GALAXY_ONBOARDING_CAN"):
        monkeypatch.setenv(env, "off")
    monkeypatch.setattr(lb, "list_serial_ports", lambda: pytest.fail("串口扫描已关闭"))
    assert asyncio.run(lb.scan_serial()) == asyncio.run(lb.scan_bluetooth()) == asyncio.run(lb.scan_can()) == 0


# ── 真的 D-Bus:私有 dbus-daemon + 导出 org.bluez.Device1 的服务 + 真的 busctl ────────

_FAKE_BLUEZ = r"""
import asyncio, sys
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, dbus_property
from dbus_fast.constants import PropertyAccess as PA

class Device1(ServiceInterface):
    def __init__(self, addr, alias, connected):
        super().__init__("org.bluez.Device1")
        self._a, self._n, self._c = addr, alias, connected
    @dbus_property(access=PA.READ)
    def Address(self) -> "s": return self._a
    @dbus_property(access=PA.READ)
    def Alias(self) -> "s": return self._n
    @dbus_property(access=PA.READ)
    def Connected(self) -> "b": return self._c
    @dbus_property(access=PA.READ)
    def UUIDs(self) -> "as": return ["0000180f-0000-1000-8000-00805f9b34fb"]

async def main():
    bus = await MessageBus(bus_address=sys.argv[1]).connect()
    bus.export("/org/bluez/hci0/dev_F4_7B_09_AA_BB_CC", Device1("F4:7B:09:AA:BB:CC", "Pixel Watch", True))
    await bus.request_name("org.bluez")
    print("ready", flush=True)
    await asyncio.sleep(60)

asyncio.run(main())
"""


def test_bluetooth_scan_over_a_real_dbus(tmp_path, monkeypatch):
    import select
    import shutil
    import subprocess
    import sys
    import time

    pytest.importorskip("dbus_fast")
    if not (shutil.which("dbus-daemon") and shutil.which("busctl")):
        pytest.skip("需要 dbus-daemon 与 busctl")
    sock = tmp_path / "bus.sock"
    conf = tmp_path / "bus.conf"
    conf.write_text(
        '<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-Bus Bus Configuration 1.0//EN" '
        '"http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd"><busconfig><type>session</type>'
        f"<listen>unix:path={sock}</listen><auth>EXTERNAL</auth>"
        '<policy context="default"><allow send_destination="*"/><allow receive_sender="*"/><allow own="*"/>'
        "</policy></busconfig>"
    )
    script = tmp_path / "fake_bluez.py"
    script.write_text(_FAKE_BLUEZ)
    daemon = subprocess.Popen(["dbus-daemon", f"--config-file={conf}", "--nofork"])
    service = None
    try:
        for _ in range(50):
            if sock.exists():
                break
            time.sleep(0.1)
        address = f"unix:path={sock}"
        service = subprocess.Popen([sys.executable, str(script), address], stdout=subprocess.PIPE, text=True)
        ready, _, _ = select.select([service.stdout], [], [], 15)
        assert ready and service.stdout.readline().strip() == "ready", "假 BlueZ 服务没起来"

        monkeypatch.setenv("GALAXY_BLUEZ_DBUS_ADDRESS", address)
        [watch] = lb.bluez_observations(lb._busctl_managed_objects())
        assert (watch.key, watch.name, watch.properties["connected"]) == ("F4:7B:09:AA:BB:CC", "Pixel Watch", True)
        assert watch.properties["uuids"] == ["0000180f-0000-1000-8000-00805f9b34fb"]
    finally:
        for p in (service, daemon):
            if p is not None:
                p.terminate()
                p.wait(timeout=5)
