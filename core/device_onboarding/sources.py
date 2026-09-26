"""core/device_onboarding/sources.py — 发现来源:把各种"看见"翻成 Observation。

事件型来源自己回调(mDNS 在 ``core/lan_discovery.py``、HA 实体在 ``core/ha_bridge.py``、
NATS edge worker 在这里订阅);轮询型来源由 :func:`scan_once` 统一跑一遍,
:func:`run_scan_loop` 按 ``GALAXY_ONBOARDING_SCAN_INTERVAL_S`` 周期执行。

新来源的写法:把原始信息翻成 ``Observation``,调 ``get_onboarding_service().observe()``;
它若知道在线与否,调 UCM ``report_presence``。其余交给接入平面。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import time
from typing import Any, Dict, Iterable, List, Optional

from core.device_onboarding import ha_client
from core.device_onboarding.models import CandidateStatus, Observation
from core.device_onboarding.service import get_onboarding_service, onboarding_enabled

logger = logging.getLogger("Galaxy.Onboarding.Sources")


def scan_interval_s() -> float:
    try:
        return max(15.0, float(os.getenv("GALAXY_ONBOARDING_SCAN_INTERVAL_S", "60")))
    except ValueError:
        return 60.0


def mark_absent(source: str, present_keys: Iterable[str]) -> int:
    """全量扫描型来源:这次没看见的候选标记为"不在了"(不删 —— 人可能已忽略它)。"""
    svc = get_onboarding_service()
    keys = set(present_keys)
    n = 0
    for c in svc.candidates.values():
        if c.source == source and c.key not in keys and c.present and c.status != CandidateStatus.JOINED.value:
            c.present = False
            svc.candidates.put(c.candidate_id, c)
            n += 1
    return n


# ── SSDP / UPnP(电视、路由器、DLNA、打印机) ──────────────────────────────────────
#
# Node_71 里有一份 SSDP 实现,但它在节点层,core 不能反向依赖(导入边界)。这里只要
# "发一次 M-SEARCH、收几秒回应",几十行足够,不引入长驻监听。

_SSDP_ADDR = ("239.255.255.250", 1900)
_MSEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    "MX: 2\r\n"
    "ST: ssdp:all\r\n\r\n"
).encode("ascii")


def parse_ssdp_response(data: bytes, addr: str) -> Optional[Dict[str, str]]:
    """一条 SSDP 回应 → {uuid, st, location, server, address}。不是合法回应返回 None。"""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return None
    if not text.upper().startswith("HTTP/1.1 200"):
        return None
    headers: Dict[str, str] = {}
    for line in text.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    usn = headers.get("usn", "")
    m = re.search(r"uuid:([0-9a-fA-F-]+)", usn)
    if not m:
        return None
    return {
        "uuid": m.group(1).lower(),
        "st": headers.get("st", ""),
        "location": headers.get("location", ""),
        "server": headers.get("server", ""),
        "address": addr,
    }


def ssdp_search(timeout_s: float = 3.0) -> List[Dict[str, str]]:
    """发一次 M-SEARCH,收 ``timeout_s`` 秒回应,按 uuid 合并。"""
    found: Dict[str, Dict[str, str]] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(0.5)
        sock.sendto(_MSEARCH, _SSDP_ADDR)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                data, (host, _port) = sock.recvfrom(4096)
            except socket.timeout:
                continue
            r = parse_ssdp_response(data, host)
            if not r:
                continue
            cur = found.setdefault(r["uuid"], {**r, "types": ""})
            if "device:" in r["st"] and r["st"] not in cur["types"]:
                cur["types"] = (cur["types"] + " " + r["st"]).strip()
    except OSError as exc:
        logger.debug("SSDP 搜索失败(网络不支持组播?): %s", exc)
    finally:
        sock.close()
    return list(found.values())


def ssdp_observation(r: Dict[str, str]) -> Observation:
    kind = r.get("types", "").lower()
    name = r.get("server", "") or r["uuid"]
    return Observation(
        source="ssdp",
        key=r["uuid"],
        name=name,
        kind_hint="tv" if "mediarenderer" in kind else "iot",
        addresses=[r["address"]] if r.get("address") else [],
        identity={"ip": r.get("address", "")},
        properties={"device_type_urn": r.get("types", ""), "location": r.get("location", ""), "server": name},
    )


async def scan_ssdp() -> int:
    if os.getenv("GALAXY_ONBOARDING_SSDP", "true").strip().lower() in ("0", "false", "no", "off"):
        return 0
    results = await asyncio.to_thread(ssdp_search)
    svc = get_onboarding_service()
    for r in results:
        svc.observe(ssdp_observation(r))
    mark_absent("ssdp", [r["uuid"] for r in results])
    return len(results)


# ── Home Assistant 自己发现、等人确认的集成 ────────────────────────────────────────

#: HA 配置流的来源:这些是 HA **自己发现**的(人主动发起的 "user" 流不算候选)。
_HA_DISCOVERY_SOURCES = {
    "zeroconf",
    "ssdp",
    "dhcp",
    "bluetooth",
    "homekit",
    "usb",
    "mqtt",
    "discovery",
    "hassio",
    "integration_discovery",
}


def ha_flow_observation(flow: Dict[str, Any]) -> Optional[Observation]:
    ctx = flow.get("context") or {}
    if str(ctx.get("source", "")) not in _HA_DISCOVERY_SOURCES:
        return None
    placeholders = {k: str(v) for k, v in (ctx.get("title_placeholders") or {}).items()}
    handler = str(flow.get("handler", ""))
    name = placeholders.get("name") or next(iter(placeholders.values()), "") or handler
    return Observation(
        source="ha_flow",
        key=str(flow.get("flow_id", "")),
        name=name,
        kind_hint="iot",
        properties={"handler": handler, "step_id": flow.get("step_id", ""), "ha_source": ctx.get("source", "")},
    )


async def scan_ha_flows() -> int:
    if not ha_client.ha_configured():
        return 0
    try:
        flows = await ha_client.ha_rest("GET", "/api/config/config_entries/flow")
    except ha_client.HAUnavailable as exc:
        logger.debug("HA 已发现集成拉取失败: %s", exc.reason)
        return 0
    svc = get_onboarding_service()
    keys = []
    for f in flows or []:
        obs = ha_flow_observation(f)
        if obs and obs.key:
            svc.observe(obs)
            keys.append(obs.key)
    mark_absent("ha_flow", keys)
    return len(keys)


# ── 自建 tailnet 里、不属于任何成员的节点 ─────────────────────────────────────────


async def scan_tailnet() -> int:
    """headscale 对账:成员报 tailnet 在线通道;没认出来的节点成为候选。"""
    from core.tailnet_membership import annotate
    from core.unified.connection_manager import get_unified_connection_manager
    from core.unified.device_manager import get_unified_device_manager

    devices = [
        {"device_id": d.device_id, "remote_ip": d.ip_address or "", "metadata": dict(d.metadata or {})}
        for d in get_unified_device_manager().list_devices()
        if not d.bridge_id
    ]
    try:
        status = await asyncio.to_thread(annotate, devices)
    except Exception as exc:  # noqa: BLE001
        logger.debug("tailnet 对账失败: %s", exc)
        return 0
    if not status.get("configured") or not status.get("reachable", True):
        return 0
    ucm = get_unified_connection_manager()
    for d in devices:
        node = d.get("tailnet")
        if node:
            ucm.report_presence(d["device_id"], "tailnet", bool(node.get("online")), detail={"ips": node.get("ips")})
    svc = get_onboarding_service()
    keys = []
    for n in status.get("tailnet_only", []):
        key = str(n.get("node_id") or n.get("name") or "")
        if not key:
            continue
        ips = list(n.get("ips") or [])
        svc.observe(
            Observation(
                source="tailnet",
                key=key,
                name=str(n.get("name") or key),
                addresses=ips,
                identity={"ip": ips[0] if ips else "", "tailnet_name": str(n.get("name") or "")},
                properties={"online": bool(n.get("online")), "last_seen": n.get("last_seen", "")},
                present=True,
            )
        )
        keys.append(key)
    mark_absent("tailnet", keys)
    return len(keys)


# ── NATS 上的 Go edge worker ─────────────────────────────────────────────────────


def worker_observation(data: Dict[str, Any]) -> Optional[Observation]:
    reg = data.get("worker_register") if isinstance(data.get("worker_register"), dict) else data
    wid = str(reg.get("worker_id") or "")
    if not wid:
        return None
    caps = []
    for c in reg.get("capabilities") or []:
        name = c.get("name") if isinstance(c, dict) else c
        if name:
            caps.append(str(name))
    return Observation(
        source="nats_worker",
        key=wid,
        name=str(reg.get("hostname") or wid),
        kind_hint=str(reg.get("device_type") or reg.get("platform") or "linux"),
        identity={"worker_id": wid},
        capabilities=caps + (["docker"] if reg.get("has_docker") else []) + (["gpu"] if reg.get("has_gpu") else []),
        properties={
            "hostname": reg.get("hostname", ""),
            "platform": reg.get("platform", ""),
            "has_docker": bool(reg.get("has_docker")),
            "has_gpu": bool(reg.get("has_gpu")),
            "cpu_cores": reg.get("cpu_cores", 0),
            "memory_total_mb": reg.get("memory_total_mb", 0),
        },
    )


async def _on_worker_register(data: Dict[str, Any]) -> None:
    obs = worker_observation(data or {})
    if obs is None:
        return
    get_onboarding_service().observe(obs)
    from core.unified.connection_manager import get_unified_connection_manager

    get_unified_connection_manager().report_presence(obs.key, "nats", True)


async def _on_worker_heartbeat(data: Dict[str, Any]) -> None:
    hb = data.get("heartbeat") if isinstance(data.get("heartbeat"), dict) else data
    wid = str((hb or {}).get("worker_id") or "")
    if wid:
        from core.unified.connection_manager import get_unified_connection_manager

        get_unified_connection_manager().report_presence(wid, "nats", True, detail={"status": hb.get("status", "")})


async def subscribe_workers() -> bool:
    """订阅 edge worker 的注册与心跳。用独立的 durable,不与 MasterBrain 分摊消息。"""
    try:
        from core.nats_bus import get_nats_bus
        from core.nats_subjects import WorkerLifecycleSubjects

        bus = get_nats_bus()
        if not bus.is_connected():
            return False
        wrap = bus._wrap_aip_v3_callback  # noqa: SLF001 — 与 MasterBrain 同一套 v3→旧格式转换
        await bus.subscribe(WorkerLifecycleSubjects.REGISTER, wrap(_on_worker_register), durable="onboarding-workers")
        await bus.subscribe(WorkerLifecycleSubjects.HEARTBEAT, wrap(_on_worker_heartbeat), durable="onboarding-hb")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("edge worker 订阅跳过: %s", exc)
        return False


# ── 统一调度 ──────────────────────────────────────────────────────────────────────


async def scan_once() -> Dict[str, Any]:
    """所有轮询型来源跑一遍。每个来源独立失败,不连坐。"""
    out: Dict[str, Any] = {}
    for name, fn in (("ha_flows", scan_ha_flows), ("tailnet", scan_tailnet), ("ssdp", scan_ssdp)):
        try:
            out[name] = await fn()
        except Exception as exc:  # noqa: BLE001
            out[name] = f"error: {exc}"
            logger.debug("发现来源 %s 失败: %s", name, exc)
    return out


async def run_scan_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        if onboarding_enabled():
            await scan_once()
        try:
            await asyncio.wait_for(stop.wait(), timeout=scan_interval_s())
        except asyncio.TimeoutError:
            pass
