"""
core.tailscale_manager — Tailscale管理器（选填）
====================================================
Tailscale提供安全的WireGuard隧道，用于广域网设备连接。
状态: 选填 — 安装后自动启用，未安装时不影响局域网功能。
"""
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger("Galaxy.Tailscale")


class TailscaleManager:
    """Tailscale管理器 — 选填组件"""

    def __init__(self):
        self.ts_ip: Optional[str] = None
        self._available = False

    async def initialize(self) -> Optional[str]:
        """检测Tailscale，返回IP或None"""
        import shutil

        if not shutil.which("tailscale"):
            logger.info("Tailscale not installed (optional — LAN mode only)")
            return None

        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                import json
                status = json.loads(result.stdout)
                self.ts_ip = status.get("Self", {}).get("TailscaleIPs", [None])[0]
                self._available = True
                logger.info("Tailscale IP: %s", self.ts_ip)
                return self.ts_ip
        except Exception as exc:
            logger.debug("Tailscale check failed: %s", exc)

        return None

    def is_available(self) -> bool:
        """检查Tailscale是否可用"""
        return self._available

    def get_connection_url(self, port: int = 8765) -> Optional[str]:
        """获取Android端应连接的URL"""
        if self.ts_ip:
            return f"ws://{self.ts_ip}:{port}"
        return None

    @staticmethod
    def get_install_guide() -> str:
        """获取安装指引"""
        return (
            "Tailscale is OPTIONAL. It enables secure cross-WAN device connectivity.\n"
            "Install: https://tailscale.com/download\n"
            "Then run: tailscale up\n"
            "Without Tailscale: devices must be on the same LAN."
        )
