"""
mDNS Announcer — Galaxy Gateway Local Network Discovery

Publishes a _galaxy._tcp service so Wear OS and Android devices
can auto-discover the gateway on the same LAN (zero-config).

No manual IP entry needed when phone/watch and gateway are on
the same Wi-Fi network. Falls back to Tailscale for off-LAN use.

Usage:
    from galaxy_gateway.mdns_announcer import MdnsAnnouncer
    announcer = MdnsAnnouncer(port=8765)
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
    global _zeroconf, _Zeroconf, _ServiceInfo
    if _Zeroconf is not None:
        return True
    try:
        from zeroconf import Zeroconf, ServiceInfo  # type: ignore
        _Zeroconf = Zeroconf
        _ServiceInfo = ServiceInfo
        return True
    except ImportError:
        logger.warning(
            "zeroconf not installed — LAN auto-discovery unavailable. "
            "Install: pip install zeroconf>=0.132.0"
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

    def __init__(self, port: int = 8765, gateway_token: str = ""):
        self.port = port
        self.gateway_token = gateway_token
        self._zc: Optional[Any] = None
        self._info: Optional[Any] = None
        self._started = False

    # ------------------------------------------------------------------
    # IP detection — prefer LAN IP over localhost
    # ------------------------------------------------------------------

    @staticmethod
    def get_lan_ip() -> str:
        """Best-effort LAN IP detection. Falls back to 127.0.0.1."""
        try:
            # Method 1: connect to a public address to determine outgoing iface
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
            finally:
                s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass

        try:
            # Method 2: hostname resolution
            ip = socket.gethostbyname(socket.gethostname())
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass

        return "127.0.0.1"

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
                server=f"galaxy-gateway.local.",
            )
            self._zc = _Zeroconf()
            self._zc.register_service(self._info)
            self._started = True
            logger.info(
                "mDNS: broadcasting _galaxy._tcp on %s:%d (LAN IP=%s)",
                self.SERVICE_NAME, self.port, ip,
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
