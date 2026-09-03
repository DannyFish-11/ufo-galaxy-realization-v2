"""
mDNS Announcer — Galaxy Gateway Local Network Discovery

Publishes a _galaxy._tcp service so Wear OS and Android devices
can auto-discover the gateway on the same LAN (zero-config).

No manual IP entry needed when phone/watch and gateway are on
the same Wi-Fi network. Falls back to Tailscale for off-LAN use.

Usage:
    from galaxy_gateway.mdns_announcer import MdnsAnnouncer
    announcer = MdnsAnnouncer(port=9000)  # 与统一网关端口一致
    announcer.start()   # non-blocking
    ...
    announcer.stop()
"""

import logging
import socket
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Lazy import: zeroconf is optional (graceful degrade if not installed)
_zeroconf = None
_Zeroconf = None
_ServiceInfo = None


def _ensure_zeroconf():
    global _Zeroconf, _ServiceInfo  # _zeroconf 从不在本函数赋值,不列(F824)
    if _Zeroconf is not None:
        return True
    try:
        from zeroconf import ServiceInfo, Zeroconf  # type: ignore

        _Zeroconf = Zeroconf
        _ServiceInfo = ServiceInfo
        return True
    except ImportError:
        logger.warning(
            "zeroconf not installed — LAN auto-discovery unavailable. " "Install: pip install zeroconf>=0.132.0"
        )
        return False


class MdnsAnnouncer:
    """
    Publishes _galaxy._tcp on the local network.

    Properties broadcast:
        - path: WebSocket endpoint path (/ws/device/{device_id})
        - proto: AIP v3
        - tls: false (Tailscale/LAN use plain WS)
    """

    SERVICE_TYPE = "_galaxy._tcp.local."
    SERVICE_NAME = "Galaxy Gateway"

    def __init__(self, port: int = 9000, gateway_token: str = ""):
        self.port = port
        self.gateway_token = gateway_token
        self._zc: Optional[Any] = None
        self._info: Optional[Any] = None
        self._started = False

    # ------------------------------------------------------------------
    # IP detection — prefer LAN IP over localhost
    # ------------------------------------------------------------------

    @staticmethod
    def get_lan_ip() -> Optional[str]:
        """本机局域网 IP;探不到返回 ``None``。

        改前这里的兜底是 ``"127.0.0.1"``,而调用方 :meth:`start` 会把它**广播到
        整个局域网**。任何听到的手机/手表都会拿到一个必然连不通的地址 —— 在它们
        那边,``127.0.0.1`` 指向它们自己。

        探测收口到 :mod:`core.lan_address`(仓里原有五份各写各的实现,失败语义与
        探测目标都不一致)。那份实现还修了一个更隐蔽的问题:原来只探
        ``8.8.8.8:80``,要求内核选得出一条到**公网**的路 —— 而"局域网通、公网
        不通"正是本产品的主场景,那种机器上原实现会误判成"没有局域网地址"。
        """
        from core.lan_address import detect_lan_ip

        return detect_lan_ip()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """Start broadcasting. Returns False if zeroconf unavailable."""
        if self._started:
            return True
        if not _ensure_zeroconf():
            return False

        try:
            ip = self.get_lan_ip()
            if not ip:
                # 宁可不广播,也不广播一个环回地址。
                # 广播出去的后果不是"发现失败",而是"发现成功但连不上" ——
                # 后者的排查成本高得多,因为设备侧看到的是一个格式正确的地址。
                logger.warning("mDNS: 未探测到局域网地址,跳过广播(不发布环回地址)")
                return False
            desc = {
                "path": "/ws/device/{device_id}",
                "proto": "aip-v3",
                "tls": "false",
                "auth": "token",
            }
            self._info = _ServiceInfo(
                type_=self.SERVICE_TYPE,
                name=f"{self.SERVICE_NAME}.{self.SERVICE_TYPE}",
                addresses=[socket.inet_aton(ip)],
                port=self.port,
                properties=desc,
                server="galaxy-gateway.local.",
            )
            self._zc = _Zeroconf()
            self._zc.register_service(self._info)
            self._started = True
            logger.info(
                "mDNS: broadcasting _galaxy._tcp on %s:%d (LAN IP=%s)",
                self.SERVICE_NAME,
                self.port,
                ip,
            )
            return True
        except Exception as e:
            logger.warning("mDNS: failed to start: %s", e)
            return False

    def stop(self) -> None:
        """Stop broadcasting."""
        if not self._started:
            return
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
                self._zc.close()
        except Exception as e:
            logger.debug("mDNS: cleanup error: %s", e)
        finally:
            self._zc = None
            self._info = None
            self._started = False
            logger.info("mDNS: stopped")

    def __del__(self):
        self.stop()
