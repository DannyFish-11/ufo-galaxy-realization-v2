"""core/tailnet_membership.py — 设备列表与 headscale 的对账:哪台设备在 tailnet 里是谁。

为什么要对账
============
这套系统里有两份"我有哪些设备"的清单,各管一半:

* **设备列表**(``/api/v1/devices``,UDM + 配对簿):哪些设备配过对、此刻连没连着网关;
* **headscale 的节点表**:哪些机器是 tailnet 的成员、此刻在不在线。

两份各自都对,但分开看就答不了最实际的问题:"我的手表出门能不能直连?"
(= 它在不在 tailnet 里、在不在线)、"这台 100.64.0.7 是谁?"、"手表丢了,
它还能不能进我的网?"。所以这里把第二份并进第一份:每台设备多一栏 ``tailnet``,
不属于任何已知设备的节点单列为 ``tailnet_only``(比如你的笔记本)。

怎么认
======
按可靠程度依次试:

1. **配对时记下的钥匙** —— 网关给手表签钥匙时记下 key_id,headscale 的节点上带着
   它是凭哪把钥匙加入的。这是一一对应,不会认错;
2. **节点名** —— 手表的 tailnet 进程用 ``galaxy-watch-<设备 id 前 6 位>`` 当名字;
3. **地址** —— 设备连网关时的来源地址若在 tailnet 段里,就是那个节点。

一个都对不上的节点不猜,归入 ``tailnet_only``。

移除设备 = 收回网络
====================
在面板上移除一台已配对的设备时,它在 headscale 里的节点一并删除。否则丢了的手表
仍是你 tailnet 的正式成员 —— 配对令牌作废了,网却还通着。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.headscale_join import JoinGrant, JoinUnavailable, TailnetNode, delete_node, join_status, list_nodes

logger = logging.getLogger("Galaxy.TailnetMembership")

#: 节点表缓存秒数。设备列表会被面板频繁拉,不能每次都去问 headscale。
NODES_CACHE_S = 10.0


def _store_path() -> str:
    explicit = os.getenv("GALAXY_TAILNET_MEMBERSHIP_PATH", "").strip()
    if explicit:
        return explicit
    base = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return os.path.join(base, "tailnet_membership.json")


_lock = threading.Lock()
_cache: Tuple[float, List[TailnetNode]] = (0.0, [])


def _load() -> Dict[str, Dict[str, Any]]:
    try:
        with open(_store_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("tailnet 成员记录读不出来(不等于没有):%s", exc)
        return {}


def _save(data: Dict[str, Dict[str, Any]]) -> None:
    path = _store_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def record_grant(device_id: str, grant: JoinGrant) -> None:
    """配对时:记下"给这台设备签了哪把钥匙"。之后凭它把节点认回设备。"""
    if not device_id or not grant.key_id:
        return
    with _lock:
        data = _load()
        data[device_id] = {"key_id": grant.key_id, "issued_at": time.time()}
        _save(data)


def watch_hostname(device_id: str) -> str:
    """与手表 tailnet 进程取的名字同一规则(galaxy-wearos TailnetProtocol.hostnameFor)。"""
    tail = "".join(c for c in device_id.lower() if c.isascii() and c.isalnum())[:6]
    return f"galaxy-watch-{tail}" if tail else "galaxy-watch"


def _nodes(*, fresh: bool = False) -> List[TailnetNode]:
    global _cache
    if not join_status()["configured"]:
        return []
    now = time.monotonic()
    if not fresh and now - _cache[0] < NODES_CACHE_S:
        return list(_cache[1])
    nodes = list_nodes()
    _cache = (now, nodes)
    return list(nodes)


def invalidate_cache() -> None:
    global _cache
    _cache = (0.0, [])


def match_nodes(
    devices: Iterable[Dict[str, Any]],
    nodes: List[TailnetNode],
    grants: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, TailnetNode], List[TailnetNode]]:
    """把节点认回设备。纯函数,便于单测。

    返回 ``(device_id → 节点, 没认出来的节点)``。
    """
    remaining = list(nodes)
    by_device: Dict[str, TailnetNode] = {}

    def take(pred) -> Optional[TailnetNode]:
        for n in remaining:
            if pred(n):
                remaining.remove(n)
                return n
        return None

    devs = [d for d in devices if d.get("device_id")]
    # 1) 配对时签的钥匙 —— 一一对应,最可靠,先认
    for d in devs:
        kid = str((grants.get(d["device_id"]) or {}).get("key_id") or "")
        if kid:
            n = take(lambda n, kid=kid: n.pre_auth_key_id == kid)
            if n:
                by_device[d["device_id"]] = n
    # 2) 手表进程的节点名
    for d in devs:
        if d["device_id"] in by_device:
            continue
        name = watch_hostname(d["device_id"])
        n = take(lambda n, name=name: n.name == name)
        if n:
            by_device[d["device_id"]] = n
    # 3) 设备连网关时的来源地址
    for d in devs:
        if d["device_id"] in by_device:
            continue
        ip = str(d.get("remote_ip") or (d.get("metadata") or {}).get("ip") or "")
        if ip:
            n = take(lambda n, ip=ip: ip in n.ips)
            if n:
                by_device[d["device_id"]] = n
    return by_device, remaining


def annotate(devices: List[Dict[str, Any]]) -> Dict[str, Any]:
    """给设备列表每一项加上 ``tailnet`` 一栏,并给出没认出来的节点。

    headscale 没配、或者这一刻问不到时,**不影响设备列表本身**:每台设备的
    ``tailnet`` 为 null,另附一句为什么。
    """
    status = join_status()
    if not status["configured"]:
        for d in devices:
            d["tailnet"] = None
        return {"configured": False, "reason": status["reason"], "tailnet_only": []}
    try:
        nodes = _nodes()
    except JoinUnavailable as exc:
        for d in devices:
            d["tailnet"] = None
        return {"configured": True, "reachable": False, "reason": exc.reason, "tailnet_only": []}
    by_device, unmatched = match_nodes(devices, nodes, _load())
    for d in devices:
        n = by_device.get(d.get("device_id", ""))
        d["tailnet"] = n.to_dict() if n else None
    return {
        "configured": True,
        "reachable": True,
        "reason": "",
        "tailnet_only": [n.to_dict() for n in unmatched],
    }


def forget_device(device_id: str, device: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """移除设备时把它踢出 tailnet。返回做了什么,供面板如实展示。"""
    with _lock:
        grants = _load()
        grant = grants.pop(device_id, None)
        if grant is not None:
            _save(grants)
    if not join_status()["configured"]:
        return {"tailnet_removed": False, "reason": "not_configured"}
    try:
        nodes = _nodes(fresh=True)
        by_device, _ = match_nodes(
            [device or {"device_id": device_id}],
            nodes,
            {device_id: grant} if grant else {},
        )
        node = by_device.get(device_id)
        if node is None:
            return {"tailnet_removed": False, "reason": "not_in_tailnet"}
        delete_node(node.node_id)
        invalidate_cache()
        logger.info("已把 %s 移出 tailnet(节点 %s %s)", device_id, node.node_id, node.name)
        return {"tailnet_removed": True, "node": node.to_dict()}
    except JoinUnavailable as exc:
        # 配对簿里已经删了;网没收回要说清楚,让人去 headscale 手动处理。
        logger.warning("移除 %s 时没能把它移出 tailnet:%s", device_id, exc.reason)
        return {"tailnet_removed": False, "reason": exc.reason, "how_to_fix": exc.how_to_fix}
