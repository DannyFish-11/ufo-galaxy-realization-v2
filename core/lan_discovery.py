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
from typing import Any, Dict, List, Optional, Tuple

from core.lan_computers import COMPUTER_SERVICE_TYPES, is_computer_service, machine_key, summarize

logger = logging.getLogger("Galaxy.LanDiscovery")

_DEFAULT_SERVICE_TYPES = [
    "_galaxy._tcp.local.",
    # 网关 tcp_adapter.register_local_service 与 Android 端广播的都是这个类型;
    # 浏览它之后,手机等对端经既有链路(本模块→UDM→mesh 邻接刷新)自动成为可直连邻居。
    "_galaxy-aip3._tcp.local.",
    "_matter._tcp.local.",
    "_matterc._udp.local.",
    "_hap._tcp.local.",
    "_googlecast._tcp.local.",
    # 电脑:远程登录 / 文件共享 / 型号信息 / 屏幕共享。见 core/lan_computers.py ——
    # 同一台机器会同时广播好几条,那边负责合成一个候选、并猜它是什么。
    *sorted(COMPUTER_SERVICE_TYPES),
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
    if os.environ.get("GALAXY_LAN_DISCOVERY", "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        import zeroconf  # noqa: F401

        return True
    except ImportError:
        return False


class LanDiscovery:
    """mDNS 浏览 → UCM ``lan`` 通道 + 接入平面候选 + DEVICE_UPDATED 事件。"""

    def __init__(self) -> None:
        self._zc: Optional[Any] = None
        self._browsers: List[Any] = []
        self._running = False
        # 诊断
        self.discovered_count = 0
        self.removed_count = 0
        self.last_seen_ts = 0.0
        # mDNS 名 → 在线记在谁身上(成员 id 或发现身份),下线时清同一个
        self._reported: Dict[str, str] = {}
        #: 电脑:机器键 → 这台机器身上见过的 mDNS 服务(一台 Mac 同时广播好几条)。
        #: 合成一个候选靠它;某一条服务下线时,机器还有别的服务就不算"不在了"。
        self._machine_services: Dict[str, Dict[str, Any]] = {}

    # ── 生命周期 ──────────────────────────────────────────────────────

    def start(self) -> Dict[str, Any]:
        """开始浏览。zeroconf 的回调跑在它自己的线程里,handler 只做轻量镜像。"""
        from zeroconf import ServiceBrowser, Zeroconf

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
            # 不直接 close():在事件循环线程上 zeroconf 会**跳过注销**,只留一条
            # "skipped as it does blocking i/o" 的告警,广播其实还挂着。
            # 见 core/zeroconf_close.py。
            from core.zeroconf_close import close_zeroconf

            close_zeroconf(self._zc, label="LAN 发现(mDNS 浏览)")
            self._zc = None

    # ── 镜像(可直接单测,不依赖 zeroconf) ─────────────────────────────

    @staticmethod
    def _device_id(name: str) -> str:
        return "mdns_" + name.rstrip(".").replace(" ", "_")

    def _note_computer(
        self, service_type: str, name: str, address: str, props: Dict[str, str]
    ) -> Optional[Dict[str, Any]]:
        """这条广播属于一台电脑吗?是就累加到那台机器上并返回合成后的样子。"""
        if not is_computer_service(service_type):
            return None
        key = machine_key(name, props)
        row = self._machine_services.setdefault(
            key, {"services": set(), "addresses": set(), "props": {}, "name": "", "members": set()}
        )
        row["services"].add(service_type)
        if address:
            row["addresses"].add(address)
        # _device-info 带型号,别被后来不带型号的广播冲掉
        row["props"].update({k: v for k, v in props.items() if v})
        row["name"] = row["name"] or (name.split(".")[0] or key)
        row["members"].add(name)
        return {
            "key": key,
            "name": row["name"],
            "addresses": row["addresses"],
            "summary": summarize(row["services"], row["props"], row["addresses"]),
        }

    def _forget_computer_service(self, service_type: str, name: str) -> Optional[Tuple[bool, str]]:
        """一条电脑服务下线 → ``(这台机器是否彻底不在了, 机器键)``;不是电脑服务返回 None。

        机器键必须由这里给出:它是当初按 ``mdns_server`` 合成的,下线回调只带服务名,
        单看名字推不出来(推出来的是实例名,对不上候选)。
        """
        if not is_computer_service(service_type):
            return None
        for key, row in list(self._machine_services.items()):
            if name in row["members"]:
                row["members"].discard(name)
                row["services"].discard(service_type)
                if not row["members"]:
                    self._machine_services.pop(key, None)
                    return True, key
                return False, key
        # 没记过这条(比如重启后收到的下线):按名字兜底,至少把它自己置离线
        return True, machine_key(name, {})

    def ingest_service(
        self,
        service_type: str,
        name: str,
        address: str = "",
        port: int = 0,
        properties: Optional[Dict[str, str]] = None,
    ) -> bool:
        """一个 mDNS 服务出现/更新 → 在线归 UCM(``lan`` 通道),是谁归接入平面。

        以前这里直接把它写进 UDM(``iot``+在线):附近的投屏盒子和已接入的成员长得
        一模一样,同一台手机还会以 ``mdns_*`` 的身份再出现一次。现在:

        * 连接信息(地址/端口/服务类型)进 UCM 的 ``lan`` 通道 —— Mesh 直连邻接从这里读;
        * 交给接入平面 ``observe()``:是已有成员就认领(按 TXT 里的 device_id 或地址),
          否则记成候选,**不进 UDM、不进能力平面**。
        """
        if not name:
            return False
        is_matter = service_type.startswith("_matter")
        props = dict(properties or {})
        computer = self._note_computer(service_type, name, address, props)
        # 电脑:key 用机器身份,这样一台机器的 _ssh / _smb / _device-info 合成一个候选,
        # 而不是在列表里出现三次。其余类型逐字保持原来的行为(key = mDNS 名)。
        obs_key = computer["key"] if computer else name
        device_id = self._device_id(obs_key)
        detail = {
            "host": address,
            "port": port,
            "service_type": service_type,
            "mdns_name": name,
            "properties": props,
            "matter": is_matter,
        }
        try:
            from core.device_onboarding.models import Observation
            from core.device_onboarding.service import get_onboarding_service

            obs = Observation(
                source="mdns",
                key=obs_key,
                name=(computer["name"] if computer else name.split(".")[0]) or name,
                kind_hint=(
                    computer["summary"]["computer_hint"]
                    if computer
                    else props.get("device_type") or props.get("platform") or ("matter" if is_matter else "")
                ),
                addresses=sorted(computer["addresses"]) if computer else ([address] if address else []),
                identity={"device_id": props.get("device_id", ""), "ip": address},
                properties={
                    "service_type": service_type,
                    "port": port,
                    **props,
                    **(computer["summary"] if computer else {}),
                },
            )
            svc = get_onboarding_service()
            member = svc.link(obs)
            svc.observe(obs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("LAN 发现:交给接入平面失败 %s: %s", name, exc)
            member = None
        try:
            from core.unified.connection_manager import get_unified_connection_manager

            # 已是成员:在线记在成员身上;否则记在发现身份上(Mesh 直连邻接读的就是它)。
            get_unified_connection_manager().report_presence(member or device_id, "lan", True, detail=detail)
            self._reported[name] = member or device_id
            if computer:
                # 下线时按机器键找回同一个在线身份(某一条服务名已经对不上了)
                self._reported[computer["key"]] = member or device_id
        except Exception as exc:  # noqa: BLE001
            logger.debug("LAN 发现:上报在线失败 %s: %s", name, exc)
            return False
        self.discovered_count += 1
        self.last_seen_ts = time.time()
        try:
            from core.state_event_bus import StateEventType, emit

            emit(
                StateEventType.DEVICE_UPDATED,
                "lan_discovery",
                {
                    "device_id": member or device_id,
                    "service_type": service_type,
                    "address": address,
                    "port": port,
                    "matter": is_matter,
                    "event": "discovered",
                },
            )
        except Exception:  # noqa: BLE001
            pass
        return True

    def service_removed(self, service_type: str, name: str) -> None:
        """服务下线 → UCM ``lan`` 通道置离线,候选标记"不在了"。

        电脑要多一步:一台机器广播好几条服务,关掉屏幕共享不等于这台电脑不在了 ——
        只有它最后一条广播也没了,才算"不在"(见 core/lan_computers.py)。
        """
        computer_gone = self._forget_computer_service(service_type, name)
        if computer_gone is not None and computer_gone[0] is False:
            return  # 这台机器还有别的服务在,不动它
        device_id = self._reported.pop(name, None) or self._device_id(name)
        obs_key = name
        if computer_gone is not None:
            obs_key = computer_gone[1]
            device_id = self._reported.pop(obs_key, None) or self._device_id(obs_key)
        try:
            from core.unified.connection_manager import get_unified_connection_manager

            ucm = get_unified_connection_manager()
            ucm.report_presence(device_id, "lan", False)
            from core.device_onboarding.models import Observation
            from core.device_onboarding.service import get_onboarding_service

            get_onboarding_service().observe(Observation(source="mdns", key=obs_key, present=False))
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
                # ServiceInfo.server 是目标主机名(nas.local.):同一台机器所有服务都指向它。
                # 电脑靠它把多条广播合成一个候选,见 core/lan_computers.machine_key。
                if getattr(info, "server", ""):
                    props["mdns_server"] = str(info.server)
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
