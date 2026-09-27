"""core/device_onboarding/local_buses.py — 插在主脑这台机器上的设备:串口、蓝牙(BlueZ / D-Bus)、CAN。

局域网发现(mDNS / SSDP / tailnet)看不见它们 —— 它们不在网络上,而是直接挂在本机:

* **串口**:USB 转串口、Arduino、ESP32 开发板……优先用 pyserial 的 ``list_ports``;
  没装 pyserial 时在 Linux 上直接读 sysfs(``/sys/class/tty``),结果一样。
* **蓝牙**:BlueZ 在系统 D-Bus 上导出的 ``org.bluez.Device1``(配过对的、扫描时见过的)。
  用 ``busctl`` 读 —— 所有 systemd 发行版自带,不再依赖一个常常装不上的 Python D-Bus 绑定。
* **CAN**:SocketCAN 接口(``/sys/class/net/*/type == 280``)。接口是 up 的时候可以
  被动听一小会儿,把总线上出现过的报文 ID 记下来 —— 那就是总线上有哪些节点在说话。
  只听不发,不会干扰总线。

三者都是全量扫描:这次没看见的候选标记为"不在了";已是成员的,经 UCM ``local``
通道报在不在(拔掉 USB、蓝牙断开、CAN 口 down 都能看到)。

每个来源在这台机器上不可用(不是 Linux、没有系统总线、没装 busctl……)时返回空,
不报错 —— 主脑跑在哪都能启动。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

from core.device_onboarding.models import CandidateStatus, Observation

logger = logging.getLogger("Galaxy.Onboarding.LocalBuses")

#: UCM 在线通道:挂在主脑本机上。
PRESENCE_CHANNEL = "local"


def _enabled(env: str) -> bool:
    return os.getenv(env, "true").strip().lower() not in ("0", "false", "no", "off")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _slug(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z]+", "-", text).strip("-").lower()


# ── 串口 ─────────────────────────────────────────────────────────────────────────

#: USB 厂商号 → 类型提示。只列能确定是什么板子的;通用 USB 转串口芯片(CH340、CP210x、
#: FTDI)后面接的可能是任何东西,不猜。
_SERIAL_VENDOR_HINT = {
    "2341": "arduino",  # Arduino SA
    "2a03": "arduino",  # Arduino SRL
    "1b4f": "arduino",  # SparkFun(Arduino 兼容)
    "239a": "arduino",  # Adafruit
    "303a": "esp32",  # Espressif(ESP32-S2/S3/C3 原生 USB)
}

#: 看起来像真串口的设备名(``ttyS*`` 多数是主板上并不存在的 8250 占位,不算)。
_SERIAL_NAME = re.compile(r"^(ttyUSB|ttyACM|ttyAMA|ttyXRUSB|cu\.|tty\.usb|COM)\S*", re.I)


def _usb_parent(dev_dir: str) -> str:
    """从 tty 的 device 目录往上找带 ``idVendor`` 的那一级(USB 设备本身)。"""
    cur = dev_dir
    for _ in range(6):
        if os.path.exists(os.path.join(cur, "idVendor")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return ""


def sysfs_serial_ports(root: str = "/sys", dev: str = "/dev") -> List[Dict[str, str]]:
    """没有 pyserial 时的 Linux 实现:和 ``serial.tools.list_ports`` 给出同样的字段。"""
    base = os.path.join(root, "class", "tty")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for name in names:
        if not _SERIAL_NAME.match(name):
            continue
        dev_link = os.path.join(base, name, "device")
        if not os.path.exists(dev_link):
            continue
        usb = _usb_parent(os.path.realpath(dev_link))
        row = {"device": os.path.join(dev, name), "name": name, "location": ""}
        if usb:
            row.update(
                vid=_read(os.path.join(usb, "idVendor")).lower(),
                pid=_read(os.path.join(usb, "idProduct")).lower(),
                serial_number=_read(os.path.join(usb, "serial")),
                manufacturer=_read(os.path.join(usb, "manufacturer")),
                product=_read(os.path.join(usb, "product")),
                location=os.path.basename(usb),
            )
        out.append(row)
    return out


def _pyserial_ports() -> Optional[List[Dict[str, str]]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return None
    rows = []
    for p in list_ports.comports():
        if not _SERIAL_NAME.match(os.path.basename(p.device or "")) and not p.vid:
            continue
        rows.append(
            {
                "device": p.device or "",
                "name": p.name or os.path.basename(p.device or ""),
                "vid": f"{p.vid:04x}" if p.vid is not None else "",
                "pid": f"{p.pid:04x}" if p.pid is not None else "",
                "serial_number": p.serial_number or "",
                "manufacturer": p.manufacturer or "",
                "product": p.product or "",
                "description": p.description or "",
                "location": p.location or "",
            }
        )
    return rows


def list_serial_ports() -> List[Dict[str, str]]:
    rows = _pyserial_ports()
    if rows is None:
        rows = sysfs_serial_ports()
    return rows


def serial_observation(p: Dict[str, str]) -> Observation:
    """一个串口 → Observation。键尽量用"这块板子"而不是"这个口":换个 USB 口插还是它。"""
    vid, pid, sn = p.get("vid", ""), p.get("pid", ""), p.get("serial_number", "")
    if vid and sn:
        key = f"usb:{vid}:{pid}:{sn}"
    elif vid:
        key = f"usb:{vid}:{pid}@{p.get('location') or p.get('device', '')}"
    else:
        key = p.get("device", "")
    product = p.get("product", "") or p.get("description", "")
    name = " ".join(x for x in (p.get("manufacturer", ""), product) if x) or p.get("name", "") or key
    return Observation(
        source="serial",
        key=key,
        name=f"{name}({p.get('device', '')})" if p.get("device") else name,
        kind_hint=_SERIAL_VENDOR_HINT.get(vid, "iot"),
        identity={"device_id": f"serial-{_slug(key)}"},
        capabilities=["serial_io"],
        properties={k: v for k, v in p.items() if v},
    )


# ── 蓝牙(BlueZ,经 D-Bus)────────────────────────────────────────────────────────

_BUSCTL_ARGS = ["--json=short", "call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"]


def _bus_arg() -> str:
    """默认系统总线;主脑跑在容器里、宿主的系统总线挂在别处时,用 ``GALAXY_BLUEZ_DBUS_ADDRESS`` 指过去。"""
    addr = os.getenv("GALAXY_BLUEZ_DBUS_ADDRESS", "").strip()
    return f"--address={addr}" if addr else "--system"


def _busctl_managed_objects(timeout_s: float = 5.0) -> Dict[str, Any]:
    exe = shutil.which("busctl")
    if not exe:
        return {}
    try:
        cp = subprocess.run(  # noqa: S603 — argv 列表,不经 shell
            [exe, _bus_arg(), *_BUSCTL_ARGS], capture_output=True, text=True, timeout=timeout_s
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("busctl 调用失败: %s", exc)
        return {}
    if cp.returncode != 0:
        # 没有 BlueZ / 没有系统总线 / 容器里:都是"这里没有蓝牙",不是错误
        logger.debug("BlueZ 不可用: %s", (cp.stderr or "").strip()[:200])
        return {}
    return parse_busctl_managed_objects(cp.stdout)


def _unvariant(v: Any) -> Any:
    """busctl --json 把 variant 写成 ``{"type": "s", "data": ...}``;剥掉这一层。"""
    if isinstance(v, dict) and set(v) == {"type", "data"}:
        return _unvariant(v["data"])
    if isinstance(v, list):
        return [_unvariant(x) for x in v]
    return v


def parse_busctl_managed_objects(text: str) -> Dict[str, Any]:
    """``busctl --json=short call … GetManagedObjects`` 的输出 → {路径: {接口: {属性: 值}}}。"""
    try:
        doc = json.loads(text or "{}")
    except ValueError:
        return {}
    data = doc.get("data") if isinstance(doc, dict) else None
    objects = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    return {
        path: {iface: {k: _unvariant(v) for k, v in (props or {}).items()} for iface, props in (ifaces or {}).items()}
        for path, ifaces in objects.items()
    }


#: BlueZ 的 ``Icon``(freedesktop 图标名)→ 类型提示。
_BT_ICON_HINT = {"phone": "phone", "computer": "linux", "video-display": "tv", "watch": "watch"}


def bluez_observations(objects: Dict[str, Any]) -> List[Observation]:
    out = []
    for path, ifaces in objects.items():
        dev = ifaces.get("org.bluez.Device1") if isinstance(ifaces, dict) else None
        if not isinstance(dev, dict) or not dev.get("Address"):
            continue
        addr = str(dev["Address"]).upper()
        icon = str(dev.get("Icon") or "")
        out.append(
            Observation(
                source="bluetooth",
                key=addr,
                name=str(dev.get("Alias") or dev.get("Name") or addr),
                kind_hint=next((h for k, h in _BT_ICON_HINT.items() if icon.startswith(k)), "iot"),
                identity={"mac": addr},
                capabilities=["bluetooth"],
                properties={
                    "address": addr,
                    "icon": icon,
                    "paired": bool(dev.get("Paired")),
                    "connected": bool(dev.get("Connected")),
                    "trusted": bool(dev.get("Trusted")),
                    "rssi": dev.get("RSSI"),
                    "uuids": list(dev.get("UUIDs") or [])[:16],
                    "adapter": str(dev.get("Adapter") or os.path.dirname(path)),
                },
            )
        )
    return out


# ── CAN(SocketCAN)──────────────────────────────────────────────────────────────

ARPHRD_CAN = "280"
_CAN_FRAME = struct.Struct("=IB3x8s")
_CAN_EFF_FLAG, _CAN_RTR_FLAG, _CAN_ERR_FLAG = 0x80000000, 0x40000000, 0x20000000


def can_interfaces(root: str = "/sys") -> List[Dict[str, Any]]:
    base = os.path.join(root, "class", "net")
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    out = []
    for name in names:
        d = os.path.join(base, name)
        if _read(os.path.join(d, "type")) != ARPHRD_CAN:
            continue
        try:
            flags = int(_read(os.path.join(d, "flags")) or "0", 16)
        except ValueError:
            flags = 0
        out.append(
            {
                "interface": name,
                "up": bool(flags & 0x1),
                "operstate": _read(os.path.join(d, "operstate")),
                # vcan / vxcan 没有底层硬件
                "virtual": not os.path.exists(os.path.join(d, "device")),
            }
        )
    return out


def _can_socket(ifname: str) -> Any:
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.bind((ifname,))
    return s


def listen_can_ids(ifname: str, seconds: float, sock_factory: Optional[Callable[[str], Any]] = None) -> List[str]:
    """被动听 ``seconds`` 秒,返回出现过的报文 ID(扩展帧 8 位十六进制,标准帧 3 位)。只收不发。"""
    if seconds <= 0 or not hasattr(socket, "AF_CAN"):
        return []
    try:
        sock = (sock_factory or _can_socket)(ifname)
    except OSError as exc:
        logger.debug("CAN %s 打不开: %s", ifname, exc)
        return []
    seen: Dict[str, None] = {}
    try:
        sock.settimeout(0.2)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and len(seen) < 256:
            try:
                frame = sock.recv(_CAN_FRAME.size)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(frame) < _CAN_FRAME.size:
                continue
            can_id, _dlc, _data = _CAN_FRAME.unpack(frame[: _CAN_FRAME.size])
            if can_id & _CAN_ERR_FLAG:
                continue
            seen[f"{can_id & 0x1FFFFFFF:08x}" if can_id & _CAN_EFF_FLAG else f"{can_id & 0x7FF:03x}"] = None
    finally:
        sock.close()
    return sorted(seen)


def can_listen_seconds() -> float:
    try:
        return max(0.0, min(10.0, float(os.getenv("GALAXY_ONBOARDING_CAN_LISTEN_S", "1.0"))))
    except ValueError:
        return 1.0


def can_observation(iface: Dict[str, Any], node_ids: Iterable[str] = ()) -> Observation:
    name = iface["interface"]
    ids = list(node_ids)
    label = f"CAN 总线 {name}" + (f"(听到 {len(ids)} 个报文 ID)" if ids else "")
    return Observation(
        source="can",
        key=f"{socket.gethostname()}:{name}",
        name=label,
        kind_hint="iot",
        identity={"device_id": f"can-{_slug(name)}"},
        capabilities=["canbus"],
        properties={**iface, "message_ids": ids},
    )


# ── 汇入接入平面 ──────────────────────────────────────────────────────────────────


def _publish(source: str, observations: List[Observation], present_of: Callable[[Observation], bool]) -> int:
    """观察结果交给接入平面;已是成员的报 ``local`` 在线通道;这次没看见的标记不在了。"""
    from core.device_onboarding.service import get_onboarding_service
    from core.device_onboarding.sources import mark_absent
    from core.unified.connection_manager import get_unified_connection_manager

    svc = get_onboarding_service()
    ucm = get_unified_connection_manager()
    members_seen = set()
    for obs in observations:
        if svc.observe(obs) is None:
            member = svc.link(obs)
            if member:
                members_seen.add(member)
                ucm.report_presence(member, PRESENCE_CHANNEL, present_of(obs), detail={"source": source})
    mark_absent(source, [o.key for o in observations])
    for c in svc.candidates.values():
        linked = c.linked_device_id
        if c.source == source and c.status == CandidateStatus.JOINED.value and linked and linked not in members_seen:
            ucm.report_presence(linked, PRESENCE_CHANNEL, False, detail={"source": source})
    return len(observations)


async def scan_serial() -> int:
    if not _enabled("GALAXY_ONBOARDING_SERIAL"):
        return 0
    rows = await asyncio.to_thread(list_serial_ports)
    return _publish("serial", [serial_observation(p) for p in rows], lambda o: True)


async def scan_bluetooth() -> int:
    if not _enabled("GALAXY_ONBOARDING_BLUETOOTH"):
        return 0
    objects = await asyncio.to_thread(_busctl_managed_objects)
    return _publish("bluetooth", bluez_observations(objects), lambda o: bool(o.properties.get("connected")))


async def scan_can() -> int:
    if not _enabled("GALAXY_ONBOARDING_CAN"):
        return 0
    ifaces = await asyncio.to_thread(can_interfaces)
    listen = can_listen_seconds()
    obs = []
    for i in ifaces:
        ids = await asyncio.to_thread(listen_can_ids, i["interface"], listen) if i["up"] else []
        obs.append(can_observation(i, ids))
    return _publish("can", obs, lambda o: bool(o.properties.get("up")))
