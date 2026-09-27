"""core/lan_computers.py — 从 mDNS 广播里认出"这是一台电脑",并把同一台机器的多条广播合成一个。

一台 Mac 在局域网里通常同时广播好几条:``_device-info._tcp``(带型号)、``_ssh._tcp``、
``_sftp-ssh._tcp``、``_smb._tcp``、``_rfb._tcp``(屏幕共享);Linux 开了 avahi 会广播
``_workstation._tcp``;Windows 装了 OpenSSH 服务器会有 ``_ssh._tcp``。

不处理的话会出两个毛病:

1. 同一台电脑在候选里出现三四次(每条服务一个);
2. 看不出它是电脑 —— ``kind_hint`` 为空,归不到 ``*_desktop`` / ``*_laptop``。

所以这里做两件事:

* :func:`machine_key` —— 同一台机器的多条广播合成同一个键。用 mDNS 的目标主机名
  (``ServiceInfo.server``,形如 ``nas.local.``),它对同一台机器的所有服务都一样;
  拿不到就退回实例名。
* :func:`computer_hint` —— 从 ``_device-info`` 的 ``model=`` 等线索猜平台,返回
  ``taxonomy`` 认识的词(``macbook`` / ``imac`` / ``windows`` / ``linux``…),
  由它归到 AIP 细分类型。**猜不出就返回 ``"computer"``,不瞎归**。

判断"能不能远程登录"只看有没有 ``_ssh``/``_sftp-ssh`` 广播 —— 那是后面"智能体远程
接入"这条路的前提,没有就别提议走那条路。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Mapping, Optional, Set

#: 电脑会广播、而灯泡电视不会广播的服务类型。看见任一条就当"疑似一台电脑"。
COMPUTER_SERVICE_TYPES = frozenset(
    {
        "_ssh._tcp.local.",  # 远程登录(Mac 的「远程登录」、Windows 的 OpenSSH、Linux sshd)
        "_sftp-ssh._tcp.local.",  # 同上,文件传输那一面
        "_smb._tcp.local.",  # 文件共享(Mac/Windows/Samba)
        "_workstation._tcp.local.",  # avahi 的"这台机器"广播(Linux 常见)
        "_device-info._tcp.local.",  # 苹果设备的型号信息(不带端口,纯 TXT)
        "_rfb._tcp.local.",  # 屏幕共享 / VNC
    }
)

#: 能远程登录 —— "智能体远程接入"这条路的前提。
REMOTE_LOGIN_SERVICES = frozenset({"_ssh._tcp.local.", "_sftp-ssh._tcp.local."})

#: ``_device-info`` 的 ``model`` 前缀 → taxonomy 认得的词。
#: 苹果的 model 形如 ``MacBookPro18,3`` / ``Macmini9,1`` / ``iMac21,1`` / ``RackMac``。
_APPLE_MODEL_HINTS = (
    ("macbook", "macbook"),  # 笔记本
    ("macmini", "mac"),
    ("macpro", "mac"),
    ("macstudio", "mac"),
    ("imac", "mac"),
    ("mac", "mac"),
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def machine_key(name: str, props: Optional[Mapping[str, str]] = None) -> str:
    """同一台机器的多条 mDNS 广播 → 同一个键。

    优先用 mDNS 的目标主机名(``mdns_server``,由 :mod:`core.lan_discovery` 从
    ``ServiceInfo.server`` 放进来):一台机器所有服务都指向它。拿不到就用实例名
    (``nas._ssh._tcp.local.`` → ``nas``)—— 同一台机器的各条服务实例名通常也一致。
    """
    server = str((props or {}).get("mdns_server") or "").strip().rstrip(".").lower()
    if server:
        return server
    return (name or "").split(".")[0].strip().lower() or (name or "")


def is_computer_service(service_type: str) -> bool:
    return service_type in COMPUTER_SERVICE_TYPES


def has_remote_login(service_types: Iterable[str]) -> bool:
    return bool(REMOTE_LOGIN_SERVICES & set(service_types))


def computer_hint(service_types: Iterable[str], props: Optional[Mapping[str, str]] = None) -> str:
    """猜这台电脑是什么 → taxonomy 认得的词;猜不出返回 ``"computer"``。

    线索按可靠程度:``_device-info`` 的 ``model``(苹果给的准确型号)→ TXT 里的
    ``os`` / ``platform`` → 服务组合(只有 ``_workstation`` 基本是 Linux 的 avahi)。
    """
    p = {str(k).lower(): str(v) for k, v in (props or {}).items()}
    types = set(service_types)

    model = _norm(p.get("model", ""))
    for prefix, hint in _APPLE_MODEL_HINTS:
        if model.startswith(prefix):
            return hint

    declared = _norm(p.get("os", "") or p.get("platform", "") or p.get("device_type", ""))
    for needle, hint in (("windows", "windows"), ("darwin", "mac"), ("macos", "mac"), ("linux", "linux")):
        if needle in declared:
            return hint

    if "_workstation._tcp.local." in types and not model:
        return "linux"
    return "computer"


def summarize(
    service_types: Iterable[str], props: Optional[Mapping[str, str]] = None, addresses: Iterable[str] = ()
) -> Dict[str, object]:
    """给候选属性里放的那一份:它是什么、能不能远程登录、看见过哪些服务。"""
    types: Set[str] = set(service_types)
    p = dict(props or {})
    return {
        "is_computer": any(is_computer_service(t) for t in types),
        "remote_login": has_remote_login(types),
        "computer_hint": computer_hint(types, p),
        "mdns_services": sorted(types),
        "model": p.get("model", ""),
        "addresses": sorted(a for a in addresses if a),
    }
