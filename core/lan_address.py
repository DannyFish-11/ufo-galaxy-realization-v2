"""core/lan_address.py

本机局域网地址的**唯一**探测口。

为什么要收口
============
改前仓里有五份各写各的实现::

    launcher/services.py:_get_lan_ip              失败返回 ""
    core/nats_bus.py:_get_lan_ip                  失败返回 ""
    core/network_topology_runtime.py:_get_lan_ip  失败直接抛
    core/agent_card.py:_local_ip                  失败返回 "127.0.0.1"   ← 有毒
    galaxy_gateway/mdns_announcer.py:get_lan_ip   失败返回 "127.0.0.1"   ← 有毒

三种失败语义、两种探测目标(``8.8.8.8:80`` 与 ``10.255.255.255:1``)。

两种探测目标的差别不是风格问题
------------------------------
``connect(("8.8.8.8", 80))`` 要求内核**选得出一条到公网的路**。一台只连着家里
路由器、但路由器没有上行的机器,这一步会 ``ENETUNREACH`` —— 于是那三份实现认为
"本机没有局域网地址",而 ``10.255.255.255`` 那份照常给出正确答案。而"局域网通、
公网不通"恰恰是本产品最主要的部署形态(手机 + PC 在同一个 Wi-Fi 下)。
同一台机器,五个调用点会得到两种不同的结论。

"127.0.0.1" 这个兜底比抛异常更糟
--------------------------------
那两份有毒的实现,产出的地址是要**发给别的设备**的:

* :func:`core.agent_card.build_candidates` 把它作为 ``kind="lan"``、
  ``priority=1`` 的候选路径写进配对名片 —— 手机拿到后**第一个**就试它,
  而 ``127.0.0.1`` 在手机上指向手机自己,连的是个不存在的本地端口;
* :class:`galaxy_gateway.mdns_announcer.MdnsAnnouncer` 把它广播到局域网,
  任何听到的设备都会拿到一个必然连不通的地址。

两者的共同点是:**故障被伪装成了成功**。调用方拿到一个格式完全正确的地址,
没有异常、没有告警,只有连不上;而排查方向会被引向"网络有问题",
真正的原因是"这台机器当时没探到自己的局域网地址"。

所以本模块的失败语义是 ``None``,不是环回地址,也不是空串:
``None`` 逼调用方显式决定"探不到的时候该怎么办",而那三种答案
(省略这条候选 / 拒绝广播 / 当成空)本来就该由调用方各自回答。
"""

from __future__ import annotations

import logging
import socket
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 探测目标,按顺序试。
#:
#: 第一个是私网广播地址:内核只需要有一条**任意**路由就能选出接口,不要求能上公网,
#: 因此在"局域网通、公网不通"的机器上照样成立 —— 那是本产品的主场景。
#: 第二个是公网地址,作为前者在某些内核/防火墙组合下被拒时的补充。
#: 两个都只 ``connect`` 不发包(UDP 的 connect 只做选路,不产生流量)。
_PROBE_TARGETS: Tuple[Tuple[str, int], ...] = (
    ("10.255.255.255", 1),
    ("8.8.8.8", 80),
)


def is_loopback(host: str) -> bool:
    """*host* 是否指向本机。

    覆盖整个 ``127.0.0.0/8``(不只是 ``127.0.0.1``)、IPv6 环回,以及
    ``0.0.0.0`` / ``::`` —— 后两个是"监听所有接口"的写法,被当成**连接目标**
    时同样到不了任何远端。

    与安卓侧 ``shared-transport`` 的 ``GatewayAddress.isLoopbackHost`` 判据一致;
    两端对"这个地址能不能发给对方"必须有同一个答案,否则一端发、另一端收下,
    故障在中间消失。
    """
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return False
    if h == "localhost" or h.endswith(".localhost"):
        return True
    if h in ("::1", "0:0:0:0:0:0:0:1", "::", "0.0.0.0"):
        return True
    octets = h.split(".")
    if len(octets) == 4 and all(o.isdigit() for o in octets if o != ""):
        try:
            return int(octets[0]) == 127
        except ValueError:  # pragma: no cover - isdigit 已排除,留作防御
            return False
    return False


def _probe(target: Tuple[str, int]) -> Optional[str]:
    """向 *target* 选一次路,返回内核选中的本地地址。失败返回 ``None``。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect(target)
            return s.getsockname()[0] or None
    except OSError as exc:
        logger.debug("局域网地址探测:%s 不可达(%s)", target[0], exc)
        return None


def _from_hostname() -> List[str]:
    """退路:解析本机主机名。容器/虚机里常常只解出环回,由调用方筛。"""
    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        return list(addrs)
    except OSError as exc:
        logger.debug("局域网地址探测:主机名解析失败(%s)", exc)
        return []


def detect_lan_ip() -> Optional[str]:
    """本机在局域网中的 IPv4 地址;探不到返回 ``None``。

    **不会**返回环回地址。探不到就是探不到 —— 见模块文档:
    把 ``127.0.0.1`` 当兜底会让"故障"变成"格式正确的错误答案"。
    """
    for target in _PROBE_TARGETS:
        ip = _probe(target)
        if ip and not is_loopback(ip):
            return ip
    for ip in _from_hostname():
        if ip and not is_loopback(ip):
            return ip
    logger.info("局域网地址探测:本机当前只有环回地址,不对外发布任何局域网地址")
    return None


def detect_lan_ip_or_empty() -> str:
    """:func:`detect_lan_ip` 的空串形态。

    只给那些**本来就把空串当"没有"**的既有调用方用(``launcher/services`` 与
    ``core/nats_bus``),迁移时保持它们的契约不变。新代码请直接用
    :func:`detect_lan_ip` 并显式处理 ``None``。
    """
    return detect_lan_ip() or ""
