"""
core.tailscale_manager — Tailscale管理器（选填，AIP v3集成版）
=========================================================
Tailscale提供安全的WireGuard隧道，用于广域网设备连接。
状态: 选填 — 安装后自动启用，未安装时不影响局域网功能。

PR-AIPV3-TAILSCALE: 持续监控 + AIP v3状态事件 + LAN回退
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional

# RUF006: retain fire-and-forget create_task results so the event loop's weak
# reference can't let them be garbage-collected mid-execution.
_BACKGROUND_TASKS: set = set()

logger = logging.getLogger("Galaxy.Tailscale")

# PR-AIPV3: Unified AIP v3 emission
try:
    from core.nats_bus import get_nats_bus  # noqa: F401
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401

    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False


class TailscaleManager:
    """Tailscale管理器 — 选填组件，AIP v3集成版

    新增功能（PR-AIPV3-TAILSCALE）:
    1. 持续监控循环（每30秒检测一次状态）
    2. IP变化/断开 → STATE_EVENT AIP v3 消息
    3. 断开时自动回退到LAN模式
    4. 与NetworkTopologyRuntime联动更新拓扑节点
    """

    # PR-STABILITY: Configurable check interval (env var override)
    _CHECK_INTERVAL_SECONDS = float(os.environ.get("GALAXY_TAILSCALE_CHECK_INTERVAL", "30.0"))
    # PR-HEADSCALE: Support custom control server (Headscale)
    _HEADSCALE_URL = os.environ.get("GALAXY_HEADSCALE_URL", "")
    # PR-PEER-RELAY: 让常驻网关节点充当 Tailscale 对等中继——手机/手表弱网(对称NAT)直连
    # 失败时,流量经"家里桌面"中转而非绕海外 DERP,延迟从几百 ms 降到个位数,零成本私有中继。
    # 跑本启动器的桌面网关默认开;GALAXY_TS_ADVERTISE_RELAY=0 显式关闭。需控制端(官方/较新
    # Headscale)与各端较新 Tailscale 客户端支持 Peer Relay;不支持时静默降级,绝不影响联网。
    _ADVERTISE_RELAY = os.environ.get("GALAXY_TS_ADVERTISE_RELAY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )

    #: 是否尝试自动拉起 Funnel（把网关暴露到公网，手表带流量单独连上靠它）。
    #: 默认开 —— 但真正能不能开由 funnel_preflight 的鉴权闸门说了算。
    _ADVERTISE_FUNNEL = os.environ.get("GALAXY_TS_FUNNEL", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.ts_ip: Optional[str] = None
        self.ts_hostname: Optional[str] = None
        self._available = False
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._previous_state: Dict[str, Any] = {}
        self._initialized = True

    # ── Core detection ──

    async def initialize(self) -> Optional[str]:
        """检测Tailscale，返回IP或None。启动持续监控。"""
        ip = await self._check_tailscale()
        if ip:
            self._start_monitoring()
            # PR-PEER-RELAY: 已连上则尝试宣告本机为对等中继（best-effort，不影响返回）。
            await self.ensure_relay_advertised()
        return ip

    async def ensure_relay_advertised(self) -> bool:
        """向 Tailscale 宣告本机为【对等中继】(best-effort)。

        已登录设备用 ``tailscale set --advertise-relay``（无需重新登录）。仅在本机已连上
        Tailscale 且开关开启时尝试；旧版客户端/控制端不支持时静默降级（返回 False），
        绝不抛出影响联网。返回是否成功宣告。
        """
        if not self._ADVERTISE_RELAY or not self._available:
            return False
        if not shutil.which("tailscale"):
            return False
        try:
            r = await asyncio.to_thread(
                subprocess.run,
                ["tailscale", "set", "--advertise-relay"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if r.returncode == 0:
                logger.info("Tailscale 对等中继已宣告（本机充当私有 relay，手机/手表弱网经此中转）")
                return True
            logger.info(
                "宣告对等中继未成功（客户端/控制端可能不支持 Peer Relay，已降级）：%s",
                (r.stderr or r.stdout or "").strip()[:160],
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("ensure_relay_advertised 跳过（非致命）：%s", exc)
        return False

    # ── Funnel：把网关暴露到**公网** ────────────────────────────────────────
    #
    # 与上面的 relay/普通 Tailscale 有本质区别，必须分清：
    #   普通 Tailscale —— 只有 tailnet 内的设备能连，对方**要装客户端**；
    #   Funnel        —— 整个公网能连，对方**不用装**。
    # 手表（Wear OS 没有 Tailscale 客户端）能带 LTE 单独连上，靠的就是 Funnel。
    #
    # 正因为它把网关推到公网，开它之前必须先过鉴权闸门（见 funnel_preflight）。

    #: Funnel 对外只能落在这三个端口之一（Tailscale 的硬限制），
    #: 本地 9000 由 ``tailscale serve`` 映射过去。
    FUNNEL_PUBLIC_PORT = 443

    def funnel_preflight(self) -> Dict[str, Any]:
        """开 Funnel 之前的**硬闸门**：不满足就不许开。

        判据只有一条，但它是硬的：**网关一旦公网可达，鉴权必须是开的。**

        局域网内默认不鉴权是合理的 —— 家里网段本身就是信任边界。Funnel 把这个
        边界整个拿掉了，此时"默认放行"就等于把桌面裸奔在公网上：任何人都能连
        ``/ws/device/<任意 id>`` 驱动你的机器。

        所以这里**不是警告，是拒绝**。返回 ``{"ok": False, "reason": ...,
        "how_to_fix": ...}``，调用方据此不开 Funnel 并把原因原样呈现给人。

        判"能不能开"而不是"当前开没开"—— 后者会让一次读取失败变成放行。
        """
        from core.auth import get_active_tokens, is_auth_enabled  # noqa: PLC0415

        if not is_auth_enabled():
            return {
                "ok": False,
                "reason": "auth_disabled",
                "detail": "鉴权被显式关闭（GALAXY_AUTH_ENABLED=false），不能把网关暴露到公网。",
                "how_to_fix": "去掉 GALAXY_AUTH_ENABLED=false（默认即开启），或改设为 true。",
            }
        if not get_active_tokens():
            return {
                "ok": False,
                "reason": "no_token",
                "detail": "鉴权开着但一个可用令牌都没有 —— 此时放行等于没有鉴权。",
                "how_to_fix": "设置 GALAXY_API_TOKEN / GALAXY_API_TOKENS，或确认 GALAXY_DATA_DIR 可写以便自签本机令牌。",
            }
        return {"ok": True, "reason": "", "detail": "", "how_to_fix": ""}

    def get_funnel_url(self) -> Optional[str]:
        """本机当前的 Funnel 公网地址；没开或问不出来返回 None。

        问不出来与"确实没开"都返回 None，但前者会留痕 —— 这条链上"没有地址"
        和"拿不到地址"对使用者是同一个后果（手表连不上），但对排障完全不同。
        """
        if not self._available or not shutil.which("tailscale"):
            return None
        try:
            r = subprocess.run(
                ["tailscale", "serve", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if r.returncode != 0:
                return None
            status = json.loads(r.stdout or "{}")
            # AllowFunnel 的键形如 "box.tailnet.ts.net:443"，值为 true 才是真开着
            for hostport, enabled in (status.get("AllowFunnel") or {}).items():
                if enabled:
                    return f"https://{str(hostport).split(':', 1)[0]}"
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Funnel 状态查询失败（不等于未开启）：%s", exc)
            return None

    async def ensure_funnel_enabled(self, local_port: int = 9000) -> Dict[str, Any]:
        """尝试拉起 Funnel。**best-effort，绝不阻断启动。**

        写法与 :meth:`ensure_relay_advertised` 一致：失败静默降级、只留痕。
        但多一层 —— 先过 :meth:`funnel_preflight`，闸门不过就**根本不执行**。

        首次还需要你在 Tailscale 后台给这台机 ``funnel`` 属性 + 开 HTTPS 证书；
        没授权时 CLI 会返回一条带链接的错误，这里原样带出去让人能照着点。
        """
        out: Dict[str, Any] = {"enabled": False, "url": None, "reason": "", "detail": "", "how_to_fix": ""}
        if not self._ADVERTISE_FUNNEL:
            out["reason"] = "disabled_by_config"
            out["detail"] = "GALAXY_TS_FUNNEL=0 已显式关闭"
            return out
        if not self._available or not shutil.which("tailscale"):
            out["reason"] = "tailscale_unavailable"
            out["detail"] = "本机没有可用的 Tailscale"
            out["how_to_fix"] = self.get_install_guide()
            return out

        gate = self.funnel_preflight()
        if not gate["ok"]:
            # 这就是那个印章：闸门不过，一行命令都不执行。
            logger.error(
                "拒绝开启 Tailscale Funnel（%s）：%s 处置：%s",
                gate["reason"],
                gate["detail"],
                gate["how_to_fix"],
            )
            out.update(reason=gate["reason"], detail=gate["detail"], how_to_fix=gate["how_to_fix"])
            return out

        existing = self.get_funnel_url()
        if existing:
            out.update(enabled=True, url=existing, reason="already_enabled")
            return out

        try:
            r = await asyncio.to_thread(
                subprocess.run,
                ["tailscale", "funnel", "--bg", f"--https={self.FUNNEL_PUBLIC_PORT}", str(local_port)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if r.returncode == 0:
                url = self.get_funnel_url()
                out.update(enabled=bool(url), url=url, reason="" if url else "url_unresolved")
                if url:
                    logger.info("Tailscale Funnel 已开启：%s → 本地 :%d（手表可带流量单独连上）", url, local_port)
                return out
            msg = (r.stderr or r.stdout or "").strip()
            out.update(reason="cli_refused", detail=msg[:400])
            # 未授权是最常见的一种，CLI 会在文案里带上可点的链接，原样透出去
            out["how_to_fix"] = "首次需在 Tailscale 后台给本机开启 Funnel 与 HTTPS 证书（错误信息里通常带链接）"
            logger.warning("Funnel 未能开启（已降级，不影响启动）：%s", msg[:200])
        except Exception as exc:  # noqa: BLE001
            out.update(reason="exception", detail=str(exc))
            logger.debug("ensure_funnel_enabled 跳过（非致命）：%s", exc)
        return out

    def get_relay_status(self) -> Dict[str, Any]:
        """汇总中继态：本机是否宣告中继 / 各 peer 当前经哪条中继（DERP 区域 或 peer relay）。"""
        out: Dict[str, Any] = {
            "advertise_relay_enabled": self._ADVERTISE_RELAY,
            "self_relay": None,
            "peers_via_relay": [],
        }
        if not self._available or not shutil.which("tailscale"):
            return out
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                out["self_relay"] = status.get("Self", {}).get("Relay", "") or None
                for _k, peer in (status.get("Peer", {}) or {}).items():
                    rel = peer.get("Relay", "")
                    if rel:
                        out["peers_via_relay"].append(
                            {
                                "hostname": peer.get("HostName", ""),
                                "relay": rel,
                                "online": peer.get("Online", False),
                            }
                        )
        except Exception as exc:  # noqa: BLE001
            logger.debug("get_relay_status failed: %s", exc)
        return out

    async def _check_tailscale(self) -> Optional[str]:
        """单次Tailscale检测。"""
        if not shutil.which("tailscale"):
            if self._available:
                self._available = False
                self._emit_state_change("uninstalled", {})
            return None

        try:
            # async 检测循环:tailscaled 卡住时同步 run 冻事件循环最长 10s,放线程
            result = await asyncio.to_thread(
                subprocess.run,
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                new_ip = status.get("Self", {}).get("TailscaleIPs", [None])[0]
                new_hostname = status.get("Self", {}).get("HostName", "")

                # Detect state changes
                old_ip = self.ts_ip
                old_available = self._available

                self.ts_ip = new_ip
                self.ts_hostname = new_hostname
                self._available = True

                if old_available and old_ip != new_ip:
                    self._emit_state_change("ip_changed", {"old_ip": old_ip, "new_ip": new_ip})
                    logger.info("Tailscale IP changed: %s → %s", old_ip, new_ip)
                elif not old_available:
                    self._emit_state_change("connected", {"ip": new_ip, "hostname": new_hostname})
                    logger.info("Tailscale connected: %s (%s)", new_ip, new_hostname)

                return new_ip
            else:
                # tailscale command failed (not running?)
                if self._available:
                    self._available = False
                    self.ts_ip = None
                    self._emit_state_change("disconnected", {"reason": "tailscale_not_running"})
                    logger.info("Tailscale disconnected (not running)")
                return None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._available:
                self._available = False
                self.ts_ip = None
                self._emit_state_change("disconnected", {"reason": f"check_error:{exc}"})
            logger.debug("Tailscale check failed: %s", exc)
            return None

    # ── Monitoring loop ──

    def _start_monitoring(self) -> None:
        """启动持续监控循环。"""
        if self._monitoring:
            return
        self._monitoring = True
        try:
            loop = asyncio.get_running_loop()
            self._monitor_task = loop.create_task(self._monitor_loop())
            logger.info("Tailscale monitoring started (interval=%ss)", self._CHECK_INTERVAL_SECONDS)
        except RuntimeError:
            logger.debug("Tailscale monitoring: no running event loop")

    async def _monitor_loop(self) -> None:
        """持续监控Tailscale状态。"""
        while self._monitoring:
            await asyncio.sleep(self._CHECK_INTERVAL_SECONDS)
            try:
                await self._check_tailscale()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Tailscale monitor loop error: %s", exc)

    def stop_monitoring(self) -> None:
        """停止持续监控。"""
        self._monitoring = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
        logger.info("Tailscale monitoring stopped")

    # ── AIP v3 state emission ──

    def _emit_state_change(self, event_action: str, details: Dict[str, Any]) -> None:
        """Emit STATE_EVENT AIP v3 message for Tailscale state changes.

        Best-effort: never raises.
        """
        if not _AIPV3_AVAILABLE:
            return
        try:
            import asyncio

            msg = StateEventMsg(
                device_id=self.ts_hostname or "tailscale_node",
                event_category="network",
                event_action=event_action,
                payload={
                    "source": "tailscale_manager",
                    "ts_ip": self.ts_ip,
                    "ts_hostname": self.ts_hostname,
                    **details,
                },
            )
            nats = get_nats_bus()
            if nats.is_usable():
                _bt = asyncio.get_running_loop().create_task(nats.publish_state_event(msg))
                _BACKGROUND_TASKS.add(_bt)
                _bt.add_done_callback(_BACKGROUND_TASKS.discard)
            else:
                logger.debug("AIPV3-TAILSCALE STATE_EVENT: %s", msg.model_dump_json(exclude_none=True))
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        # Notify local callbacks (e.g., system_mode, network_topology_runtime)
        for cb in self._callbacks:
            try:
                cb(event_action, details)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    def on_state_change(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Register a callback for Tailscale state changes.

        Callback signature: ``(event_action: str, details: dict) -> None``
        """
        self._callbacks.append(callback)

    # ── Query API ──

    def is_available(self) -> bool:
        """检查Tailscale是否可用。"""
        return self._available

    def get_connection_url(self, port: int = 9000) -> Optional[str]:
        """获取设备端应连接的 tailnet 内 URL。

        用 ``wss`` 不用 ``ws``：Funnel 强制 TLS，而 tailnet 内也没有理由明文；
        两条路统一成 wss，设备端就不用按来源切协议。
        """
        if self.ts_ip:
            return f"wss://{self.ts_ip}:{port}"
        return None

    def get_tailscale_ip(self) -> Optional[str]:
        """获取当前Tailscale IP。"""
        return self.ts_ip

    def get_tailscale_hostname(self) -> Optional[str]:
        """获取当前Tailscale主机名。"""
        return self.ts_hostname

    #: 候选路径的偏好次序 —— **唯一一处**定义谁优先于谁。
    #:
    #: 名片里的 ``candidates``（core/agent_card.build_candidates）和设备端的依次
    #: 试连都按这个排。写成两处的话，桌面按一种顺序发、设备按另一种顺序连，
    #: 排障时看到的现象是"名片明明第一条是局域网，它却先去连公网"。
    #:
    #: 次序的依据是**时延与依赖**，不是可用性：
    #:
    #: 1. ``lan``       同网段直连，最快，且不依赖 Tailscale 守护进程活着；
    #: 2. ``tailscale`` 跨网 P2P（打不通时经 DERP 中继），要求两端都在 tailnet；
    #: 3. ``funnel``    经 Tailscale 公网入口，时延最高，但**手表带流量单独出门
    #:    时唯一能用的一条**（Wear OS 没有 Tailscale 客户端，进不了 tailnet）。
    NETWORK_PREFERENCE: List[str] = ["lan", "tailscale", "funnel"]

    def get_network_priority(self) -> List[str]:
        """返回当前**实际可用**的路径类型，已按 :attr:`NETWORK_PREFERENCE` 排序。

        与 :attr:`NETWORK_PREFERENCE` 的分工：常量说"谁优先于谁"，这个方法说
        "此刻哪几条存在"。合在一起写会让"没探测到"和"不偏好"取同一个值 ——
        那正是本仓反复修的那类形状。

        ``funnel`` 需要跑一次 ``tailscale serve status``，比另外两条贵；调用方
        不需要它时传 ``include_funnel=False``（见下）。
        """
        return self.get_available_paths()

    def get_available_paths(self, *, include_funnel: bool = True) -> List[str]:
        """当前可用路径，按偏好排序。``lan`` 永远在（本机总在某个网段上）。"""
        available = {"lan"}
        if self._available and self.ts_ip:
            available.add("tailscale")
            if include_funnel and self.get_funnel_url():
                available.add("funnel")
        return [kind for kind in self.NETWORK_PREFERENCE if kind in available]

    # ── Static helpers ──

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指引。"""
        return (
            "Tailscale is OPTIONAL. It enables secure cross-WAN device connectivity.\n"
            "Install: https://tailscale.com/download\n"
            "Then run: tailscale up\n"
            "Without Tailscale: devices must be on the same LAN."
        )

    @staticmethod
    def is_tailscale_installed() -> bool:
        """检查tailscale命令是否安装。"""
        return shutil.which("tailscale") is not None

    # ── Headscale Integration ──

    def is_headscale_mode(self) -> bool:
        """Check if using custom Headscale control server."""
        return bool(self._HEADSCALE_URL)

    def get_login_server(self) -> Optional[str]:
        """Get the control server URL (Headscale or Tailscale official)."""
        return self._HEADSCALE_URL if self._HEADSCALE_URL else None

    def get_device_setup_command(self, hostname: str, ephemeral: bool = True, advertise_relay: bool = False) -> str:
        """Generate tailscale up command for a new device.

        Usage for Wear OS watch via adb:
            adb shell <command>

        ``advertise_relay=True`` 用于常驻优质节点（网关/软路由/NAS），让其充当对等中继。
        """
        cmd_parts = ["tailscale up"]

        if self._HEADSCALE_URL:
            cmd_parts.append(f"--login-server={self._HEADSCALE_URL}")

        cmd_parts.append(f"--hostname={hostname}")
        cmd_parts.append("--accept-routes")

        # PR-PEER-RELAY: 常驻优质节点宣告对等中继能力。
        if advertise_relay:
            cmd_parts.append("--advertise-relay")

        if ephemeral:
            cmd_parts.append("--ephemeral")

        # Auth key hint
        if self._HEADSCALE_URL:
            cmd_parts.append("--authkey=<GET_FROM_HEADSCALE_ADMIN>")

        return " ".join(cmd_parts)

    def get_gateway_url_for_watch(self, port: int = 9000) -> Optional[str]:
        """手表该连的地址。

        修复：原来**写死** ``wss://100.64.0.1:9000`` —— 那是"网关在我们的分配方案里
        通常是 100.64.0.1"这个假设，而 Tailscale 的 100.64.0.0/10 是按加入顺序分配的，
        本机几乎不可能正好是 .1。写死等于给手表一个必然连不上的地址。

        而且手表（Wear OS 没有 Tailscale 客户端）**根本进不了 tailnet**，
        tailnet 内地址对它没意义 —— 真正能用的是 Funnel 的公网地址。故顺序是：
        Funnel（手表唯一能用的）→ tailnet 内地址（给能装客户端的设备兜底）。
        """
        if not self._available:
            return None
        funnel = self.get_funnel_url()
        if funnel:
            return funnel.replace("https://", "wss://", 1)
        return self.get_connection_url(port)

    def get_peer_by_hostname(self, hostname: str) -> Optional[Dict[str, Any]]:
        """Get peer info from tailscale status by hostname."""
        if not self._available:
            return None
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                peers = status.get("Peer", {})
                for key, peer in peers.items():
                    if peer.get("HostName", "") == hostname:
                        ts_ips = peer.get("TailscaleIPs", [])
                        return {
                            "hostname": hostname,
                            "tailscale_ip": ts_ips[0] if ts_ips else None,
                            "os": peer.get("OS", ""),
                            "online": peer.get("Online", False),
                            "relay": peer.get("Relay", ""),
                        }
        except Exception as exc:
            logger.debug("Peer lookup failed: %s", exc)
        return None

    def get_all_peers(self) -> List[Dict[str, Any]]:
        """Get all tailnet peers."""
        peers_list = []
        if not self._available:
            return peers_list
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                peers = status.get("Peer", {})
                for key, peer in peers.items():
                    ts_ips = peer.get("TailscaleIPs", [])
                    peers_list.append(
                        {
                            "hostname": peer.get("HostName", key),
                            "tailscale_ip": ts_ips[0] if ts_ips else None,
                            "os": peer.get("OS", ""),
                            "online": peer.get("Online", False),
                        }
                    )
        except Exception as exc:
            logger.debug("Peers list failed: %s", exc)
        return peers_list
