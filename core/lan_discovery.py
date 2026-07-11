"""
core/lan_discovery.py — 局域网 mDNS 设备发现（Matter 接入·阶段1）
=================================================================

用 zeroconf(mDNS) 浏览局域网里"自报家门"的设备，镜像进统一设备模型
（UDM）并发 DEVICE_UPDATED 事件。默认浏览的服务类型：

  _galaxy._tcp.local.      自家节点（与 Node_71 发现栈同一服务名）
  _matter._tcp.local.      已入网的 Matter 设备
  _matterc._udp.local.     可配网（commissionable）的 Matter 设备
  _hap._tcp.local.         HomeKit 配件
  _googlecast._tcp.local.  Chromecast / Google Home

可用 GALAXY_LAN_DISCOVERY_TYPES（逗号分隔）覆写。

来龙去脉：Node_71 里有一套真实现的 mDNS/SSDP/组播发现栈，但（a）没接在
任何活链路上，（b）mDNS 服务类型写死 `_galaxy._tcp`——就算接上也看不见
Matter 设备。本模块是它的"接线落地版"：多服务类型浏览 + UDM SSOT 写入
+ 事件总线，Matter 设备在局域网正是靠 `_matter._tcp` mDNS 宣告的，接上
即可被看见（发现≠控制；控制经 HA 桥/Node_27 下行）。

启用条件：zeroconf 可导入 且 GALAXY_LAN_DISCOVERY != "0"。zeroconf 缺失
时优雅降级为 disabled，零影响。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LanDiscovery")

_DEFAULT_SERVICE_TYPES = [
    "_galaxy._tcp.local.",
    "_matter._tcp.local.",
    "_matterc._udp.local.",
    "_hap._tcp.local.",
    "_googlecast._tcp.local.",
]


def _service_types() -> List[str]:
    raw = os.environ.get("GALAXY_LAN_DISCOVERY_TYPES", "").strip()
    if not raw:
        return list(_DEFAULT_SERVICE_TYPES)
    out = []
    for t in raw.split(","):
        t = t.strip()
        if t:
            if not t.endswith("."):
                t += "."
            out.append(t)
    return out or list(_DEFAULT_SERVICE_TYPES)


def lan_discovery_enabled() -> bool:
    """是否应启动 LAN 发现：未被 GALAXY_LAN_DISCOVERY=0 显式关闭 且 zeroconf 可用。"""
    if os.environ.get("GALAXY_LAN_DISCOVERY", "1").strip() == "0":
        return False
    try:
        import zeroconf  # noqa: F401
        return True
    except ImportError:
        return False


class LanDiscovery:
    """mDNS 浏览 → UDM 镜像 + DEVICE_UPDATED 事件。"""

    def __init__(self) -> None:
        self._zc: Optional[Any] = None
        self._browsers: List[Any] = []
        self._running = False
        # 诊断
        self.discovered_count = 0
        self.removed_count = 0
        self.last_seen_ts = 0.0

    # ── 生命周期 ──────────────────────────────────────────────────────

    def start(self) -> Dict[str, Any]:
        """开始浏览。zeroconf 的回调跑在它自己的线程里,handler 只做轻量镜像。"""
        from zeroconf import Zeroconf, ServiceBrowser

        self._zc = Zeroconf()
        types = _service_types()
        listener = _Listener(self)
        for stype in types:
            try:
                self._browsers.append(ServiceBrowser(self._zc, stype, listener))
            except Exception as exc:  # noqa: BLE001
                logger.debug("LAN 发现:浏览 %s 失败(跳过): %s", stype, exc)
        self._running = True
        logger.info("LAN 发现已启动(mDNS 浏览 %d 类服务: %s)", len(types), types)
        return {"service_types": types}

    def stop(self) -> None:
        self._running = False
        for b in self._browsers:
            try:
                b.cancel()
            except Exception:  # noqa: BLE001
                pass
        self._browsers.clear()
        if self._zc is not None:
            try:
                self._zc.close()
            except Exception:  # noqa: BLE001
                pass
            self._zc = None

    # ── 镜像(可直接单测,不依赖 zeroconf) ─────────────────────────────

    @staticmethod
    def _device_id(name: str) -> str:
        return "mdns_" + name.rstrip(".").replace(" ", "_")

    def ingest_service(self, service_type: str, name: str,
                       address: str = "", port: int = 0,
                       properties: Optional[Dict[str, str]] = None) -> bool:
        """一个 mDNS 服务出现/更新 → 注册/刷新进 UDM + 发事件。"""
        if not name:
            return False
        is_matter = service_type.startswith("_matter")
        device_id = self._device_id(name)
        try:
            from core.unified.device_manager import get_unified_device_manager
            dm = get_unified_device_manager()
            patch = {
                "device_name": name.split(".")[0] or name,
                "status": "online",
                "ip_address": address or None,
                "port": port or None,
                "capabilities": ["discovered"] + (["matter"] if is_matter else []),
                "metadata": {
                    "protocol": "mdns",
                    "service_type": service_type,
                    "mdns_name": name,
                    "properties": dict(properties or {}),
                    "matter": is_matter,
                },
                "source": "lan_discovery",
            }
            if dm.get_device(device_id) is None:
                # 注册只立最小身份;完整状态走 SSOT upsert(register_device_from_dict
                # 会把"多余键"整体当 metadata,嵌套错位)。
                dm.register_device_from_dict(device_id, {
                    "device_type": "iot", "device_name": patch["device_name"],
                })
            dm.upsert_device_state(device_id, patch, source="lan_discovery")
            self.discovered_count += 1
            self.last_seen_ts = time.time()
        except Exception as exc:  # noqa: BLE001
            logger.debug("LAN 发现:镜像 %s 失败: %s", name, exc)
            return False
        try:
            from core.state_event_bus import emit, StateEventType
            emit(StateEventType.DEVICE_UPDATED, "lan_discovery", {
                "device_id": device_id,
                "service_type": service_type,
                "address": address,
                "port": port,
                "matter": is_matter,
                "event": "discovered",
            })
        except Exception:  # noqa: BLE001
            pass
        return True

    def service_removed(self, service_type: str, name: str) -> None:
        """服务下线 → UDM 标记 offline。"""
        device_id = self._device_id(name)
        try:
            from core.unified.device_manager import get_unified_device_manager
            dm = get_unified_device_manager()
            if dm.get_device(device_id) is not None:
                dm.upsert_device_state(device_id, {"status": "offline"}, source="lan_discovery")
                self.removed_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("LAN 发现:下线 %s 处理失败: %s", name, exc)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "enabled": True,
            "running": self._running,
            "discovered_count": self.discovered_count,
            "removed_count": self.removed_count,
            "last_seen_ts": self.last_seen_ts,
        }


class _Listener:
    """zeroconf ServiceListener:解析 ServiceInfo 后转交 LanDiscovery 镜像。"""

    def __init__(self, owner: LanDiscovery) -> None:
        self._owner = owner

    def _resolve(self, zc: Any, service_type: str, name: str) -> None:
        address, port, props = "", 0, {}
        try:
            info = zc.get_service_info(service_type, name, timeout=2000)
            if info is not None:
                addrs = info.parsed_addresses() or []
                address = addrs[0] if addrs else ""
                port = int(info.port or 0)
                for k, v in (info.properties or {}).items():
                    try:
                        props[k.decode() if isinstance(k, bytes) else str(k)] = (
                            v.decode() if isinstance(v, bytes) else str(v)
                        )
                    except Exception:  # noqa: BLE001
                        continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("LAN 发现:解析 %s 失败(仍按名字镜像): %s", name, exc)
        self._owner.ingest_service(service_type, name, address, port, props)

    # zeroconf ServiceListener 接口
    def add_service(self, zc: Any, service_type: str, name: str) -> None:
        self._resolve(zc, service_type, name)

    def update_service(self, zc: Any, service_type: str, name: str) -> None:
        self._resolve(zc, service_type, name)

    def remove_service(self, zc: Any, service_type: str, name: str) -> None:
        self._owner.service_removed(service_type, name)


# ── 模块级单例 ─────────────────────────────────────────────────────────

_discovery_instance: Optional[LanDiscovery] = None


def get_lan_discovery() -> LanDiscovery:
    global _discovery_instance
    if _discovery_instance is None:
        _discovery_instance = LanDiscovery()
    return _discovery_instance
