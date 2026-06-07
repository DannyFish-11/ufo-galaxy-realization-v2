"""
core.network_topology_runtime — Global Device Network Topology Runtime
=======================================================================
PR-28 — Network-aware transport selection for cross-device, multi-device
communication over arbitrary networks (LAN, Tailscale, public internet).

Responsibilities:
1. Discover THIS device's network position (LAN subnet, Tailscale IP, public IP)
2. Maintain a topology map of all known devices' network positions
3. Provide path assessment: "what is the best path from here to target?"

Path assessment (priority order):
    1. SAME_SUBNET   → TCP direct (LAN, <1ms)
    2. SAME_TAILNET  → Tailscale P2P (WireGuard, ~5-20ms)
    3. P2P_CAPABLE   → QUIC/WebRTC direct (NAT hole punch, ~20-80ms)
    4. RELAY         → Tailscale DERP (~80-300ms)
    5. GATEWAY       → WebSocket via Galaxy Gateway (~50-200ms)

Integration:
- AIPTransport._select_adapter() calls assess_path() for smart selection
- MeshCoordinator registers device positions
- TailscaleP2PAdapter focuses on transport, this focuses on routing
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import platform
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.NetworkTopology")

_TOPOLOGY_PROBE_INTERVAL = 30.0


@dataclass
class NetworkPosition:
    """Network position of a single device."""
    device_id: str = ""
    lan_subnet: str = ""
    lan_ip: str = ""
    tailscale_ip: str = ""
    tailscale_hostname: str = ""
    public_ip: str = ""
    public_port: int = 0
    nat_type: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    rtt_ms: float = 999.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "lan_subnet": self.lan_subnet,
            "lan_ip": self.lan_ip,
            "tailscale_ip": self.tailscale_ip,
            "tailscale_hostname": self.tailscale_hostname,
            "public_ip": self.public_ip,
            "nat_type": self.nat_type,
            "capabilities": list(self.capabilities),
            "rtt_ms": self.rtt_ms,
        }


@dataclass
class PathAssessment:
    """Best path assessment between two devices."""
    source: str = ""
    target: str = ""
    best_path: str = "unknown"
    recommended_transport: str = "websocket"
    estimated_rtt_ms: float = 999.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "best_path": self.best_path,
            "recommended_transport": self.recommended_transport,
            "estimated_rtt_ms": round(self.estimated_rtt_ms, 1),
            "reason": self.reason,
        }


class NetworkTopologyRuntime:
    """Real-time network topology map for global device communication.

    Usage:
        topo = get_network_topology_runtime()
        await topo.start()

        path = topo.assess_path("my-device", "target-device")
        print(path.recommended_transport)  # "tailscale_p2p" | "tcp" | "websocket"
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._positions: Dict[str, NetworkPosition] = {}
        self._my_device_id: str = ""
        self._my_position: NetworkPosition = NetworkPosition()
        self._running = False
        self._probe_task: Optional[asyncio.Task] = None

    # ── Public API ──────────────────────────────────────────────────

    async def start(self, device_id: str = "") -> None:
        """Start topology discovery."""
        self._my_device_id = device_id or self._detect_device_id()
        self._running = True
        self._my_position = await self._discover_self()
        self._my_position.device_id = self._my_device_id
        with self._lock:
            self._positions[self._my_device_id] = self._my_position
        self._probe_task = asyncio.create_task(
            self._refresh_loop(), name="network_topology_refresh",
        )
        logger.info(
            "NetworkTopologyRuntime started | device=%s lan=%s ts=%s",
            self._my_device_id, self._my_position.lan_subnet,
            self._my_position.tailscale_ip or "none",
        )

    async def stop(self) -> None:
        """Stop topology monitoring."""
        self._running = False
        if self._probe_task and not self._probe_task.done():
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
        logger.info("NetworkTopologyRuntime stopped")

    def register_device(self, position: NetworkPosition) -> None:
        """Register or update a peer device's network position."""
        with self._lock:
            existing = self._positions.get(position.device_id)
            if existing:
                if position.lan_ip:
                    existing.lan_ip = position.lan_ip
                if position.tailscale_ip:
                    existing.tailscale_ip = position.tailscale_ip
                if position.public_ip:
                    existing.public_ip = position.public_ip
                if position.capabilities:
                    existing.capabilities = list(set(existing.capabilities + position.capabilities))
                existing.last_seen = time.time()
            else:
                self._positions[position.device_id] = position

    def unregister_device(self, device_id: str) -> None:
        with self._lock:
            self._positions.pop(device_id, None)

    def assess_path(self, source: str, target: str) -> PathAssessment:
        """Assess best network path from source to target device.

        CORE METHOD used by AIPTransport for smart transport selection.
        """
        with self._lock:
            src_pos = self._positions.get(source)
            tgt_pos = self._positions.get(target)

        if not src_pos or not tgt_pos:
            return PathAssessment(
                source=source, target=target,
                best_path="unknown",
                recommended_transport="websocket",
                estimated_rtt_ms=999.0,
                reason="Device position not in topology map",
            )

        # Path 1: Same subnet → TCP direct
        if src_pos.lan_subnet and tgt_pos.lan_subnet:
            if src_pos.lan_subnet == tgt_pos.lan_subnet:
                return PathAssessment(
                    source=source, target=target,
                    best_path="same_subnet",
                    recommended_transport="tcp",
                    estimated_rtt_ms=1.0,
                    reason=f"Same LAN subnet {src_pos.lan_subnet}",
                )

        # Path 2: Same Tailscale tailnet → P2P via WireGuard
        if src_pos.tailscale_ip and tgt_pos.tailscale_ip:
            return PathAssessment(
                source=source, target=target,
                best_path="same_tailnet",
                recommended_transport="tailscale_p2p",
                estimated_rtt_ms=max(5.0, min(src_pos.rtt_ms, tgt_pos.rtt_ms, 50.0)),
                reason=f"Tailscale P2P: {src_pos.tailscale_ip} -> {tgt_pos.tailscale_ip}",
            )

        # Path 3: P2P capable (public IP + good NAT)
        if tgt_pos.public_ip and tgt_pos.nat_type in ("full_cone", "restricted", "none"):
            if "quic" in tgt_pos.capabilities:
                return PathAssessment(
                    source=source, target=target,
                    best_path="p2p_quic",
                    recommended_transport="quic",
                    estimated_rtt_ms=50.0,
                    reason=f"QUIC P2P to {tgt_pos.public_ip}",
                )

        # Path 4: DERP relay
        if src_pos.tailscale_ip and not tgt_pos.tailscale_ip:
            return PathAssessment(
                source=source, target=target,
                best_path="derp_relay",
                recommended_transport="tailscale_p2p",
                estimated_rtt_ms=150.0,
                reason="Target not on tailnet, using DERP relay",
            )

        # Path 5: WebSocket gateway (ultimate fallback)
        return PathAssessment(
            source=source, target=target,
            best_path="gateway_ws",
            recommended_transport="websocket",
            estimated_rtt_ms=100.0,
            reason="No P2P path available, fallback to WebSocket gateway",
        )

    def get_topology_summary(self) -> Dict[str, Any]:
        """Return JSON-safe topology summary."""
        with self._lock:
            return {
                "my_device_id": self._my_device_id,
                "my_position": self._my_position.to_dict(),
                "device_count": len(self._positions),
                "devices": {did: pos.to_dict() for did, pos in self._positions.items()},
            }

    # ── Durable state recovery (PR-RECOVERY) ────────────────────────

    def restore_durable_state(self, state: dict = None) -> Dict[str, int]:
        """恢复持久化拓扑状态。

        当前 NetworkTopologyRuntime 不维护磁盘持久化状态，所有位置信息
        通过运行时探测 (_discover_self / _refresh_loop) 动态发现。
        此方法提供与 recovery 协议的兼容接口，返回零恢复计数。

        Args:
            state: 可选的预加载状态字典（当前忽略，用于接口兼容）。

        Returns:
            {"nodes_restored": 0, "edges_restored": 0}
        """
        logger.debug(
            "NetworkTopologyRuntime.restore_durable_state called — "
            "no durable state to restore (runtime-discovered topology)"
        )
        return {"nodes_restored": 0, "edges_restored": 0}

    # ── Internal: Self discovery ────────────────────────────────────

    async def _discover_self(self) -> NetworkPosition:
        """Discover this device's own network position."""
        pos = NetworkPosition()
        try:
            pos.lan_ip = self._get_lan_ip()
            pos.lan_subnet = self._subnet_from_ip(pos.lan_ip)
        except Exception:
            pass
        try:
            pos.tailscale_ip, pos.tailscale_hostname = await self._get_tailscale_info()
        except Exception:
            pass
        pos.capabilities = self._detect_capabilities()
        return pos

    @staticmethod
    def _detect_device_id() -> str:
        return f"{platform.system().lower()}-{platform.node() or 'unknown'}"

    @staticmethod
    def _get_lan_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()

    @staticmethod
    def _subnet_from_ip(ip: str, prefix: int = 24) -> str:
        try:
            return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
        except Exception:
            return ""

    async def _get_tailscale_info(self) -> Tuple[str, str]:
        import shutil
        if not shutil.which("tailscale"):
            return "", ""
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                self_info = status.get("Self", {})
                ts_ips = self_info.get("TailscaleIPs", [""])
                return (ts_ips[0] if ts_ips else ""), self_info.get("HostName", "")
        except Exception:
            pass
        return "", ""

    @staticmethod
    def _detect_capabilities() -> List[str]:
        caps = ["websocket", "tcp", "udp"]
        import shutil
        if shutil.which("tailscale"):
            caps.append("tailscale_p2p")
        try:
            import aioquic  # noqa: F401
            caps.append("quic")
        except ImportError:
            pass
        return caps

    # ── Internal: Refresh loop ──────────────────────────────────────

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(_TOPOLOGY_PROBE_INTERVAL)
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            try:
                new_pos = await self._discover_self()
                new_pos.device_id = self._my_device_id
                with self._lock:
                    self._my_position = new_pos
                    self._positions[self._my_device_id] = new_pos
            except Exception:
                pass


# ── Singleton ────────────────────────────────────────────────────────────

_topology_instance: Optional[NetworkTopologyRuntime] = None
_topology_lock = threading.Lock()


def get_network_topology_runtime() -> NetworkTopologyRuntime:
    global _topology_instance
    if _topology_instance is None:
        with _topology_lock:
            if _topology_instance is None:
                _topology_instance = NetworkTopologyRuntime()
    return _topology_instance
