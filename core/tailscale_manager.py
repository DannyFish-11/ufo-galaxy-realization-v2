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
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Tailscale")

# PR-AIPV3: Unified AIP v3 emission
try:
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401
    from core.nats_bus import get_nats_bus  # noqa: F401
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

    _CHECK_INTERVAL_SECONDS = 30.0
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
        return ip

    async def _check_tailscale(self) -> Optional[str]:
        """单次Tailscale检测。"""
        if not shutil.which("tailscale"):
            if self._available:
                self._available = False
                self._emit_state_change("uninstalled", {})
            return None

        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10
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
            if nats.is_connected():
                asyncio.get_event_loop().create_task(nats.publish_state_event(msg))
            else:
                logger.debug("AIPV3-TAILSCALE STATE_EVENT: %s", msg.model_dump_json(exclude_none=True))
        except Exception:
            pass

        # Notify local callbacks (e.g., system_mode, network_topology_runtime)
        for cb in self._callbacks:
            try:
                cb(event_action, details)
            except Exception:
                pass

    def on_state_change(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Register a callback for Tailscale state changes.

        Callback signature: ``(event_action: str, details: dict) -> None``
        """
        self._callbacks.append(callback)

    # ── Query API ──

    def is_available(self) -> bool:
        """检查Tailscale是否可用。"""
        return self._available

    def get_connection_url(self, port: int = 8765) -> Optional[str]:
        """获取Android端应连接的URL。"""
        if self.ts_ip:
            return f"ws://{self.ts_ip}:{port}"
        return None

    def get_tailscale_ip(self) -> Optional[str]:
        """获取当前Tailscale IP。"""
        return self.ts_ip

    def get_tailscale_hostname(self) -> Optional[str]:
        """获取当前Tailscale主机名。"""
        return self.ts_hostname

    def get_network_priority(self) -> List[str]:
        """返回当前网络传输优先级列表。

        Tailscale可用时: ["tailscale", "lan", "internet"]
        Tailscale不可用时: ["lan", "internet"]
        """
        if self._available and self.ts_ip:
            return ["tailscale", "lan", "internet"]
        return ["lan", "internet"]

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
