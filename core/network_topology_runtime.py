"""
core.network_topology_runtime — Global Device Network Topology Runtime
=======================================================================
PR-28 — Network-aware transport selection for cross-device, multi-device
communication over arbitrary networks (LAN, Tailscale, public internet).

Problem: Mesh and NATS work great within LAN, but fail or have high latency
across network boundaries (e.g., phone on 4G, PC at home, watch via BLE).

Solution: Maintain a real-time network topology map of all devices. For each
transport decision, answer:
    "What is the shortest/fastest path from THIS device to TARGET device?"

Topology model
--------------
Each device has a NetworkPosition:
    - lan_subnet:   e.g., "192.168.1.0/24" (detected via local interfaces)
    - tailscale_ip: e.g., "100.x.x.x" (from TailscaleManager)
    - public_ip:    e.g., "203.0.113.1" (STUN discovery)
    - nat_type:     "none" | "full_cone" | "restricted" | "symmetric"
    - capabilities: ["tcp", "udp", "quic", "webrtc", "ble", "mqtt"]

Path selection (in priority order):
    1. SAME_SUBNET   → TCP/UDP direct (LAN, <1ms)
    2. SAME_TAILNET  → Tailscale P2P (WireGuard, ~5-20ms)
    3. P2P_CAPABLE   → WebRTC/QUIC direct (NAT hole punch, ~20-80ms)
    4. RELAY         → Tailscale DERP / QUIC fallback (~80-300ms)
    5. GATEWAY       → WebSocket via Galaxy Gateway (~50-200ms)

Integration
-----------
- AIPTransport queries this runtime before selecting a transport adapter
- Mesh uses it to decide which underlay to use for peer discovery
- NATS uses it to optimize message routing (local delivery vs relay)
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
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.NetworkTopology")

# ── Constants ────────────────────────────────────────────────────────────

_TOPOLOGY_PROBE_INTERVAL = 30.0  # seconds between topology refresh
_STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
]


# ── Data models ──────────────────────────────────────────────────────────


@dataclass
class NetworkPosition:
    """The network position of a single device.

    Attributes
    ----------
    device_id:      Unique device identifier
    lan_subnet:     Local subnet CIDR, e.g. "192.168.1.0/24"
    lan_ip:         Local IP address
    tailscale_ip:   Tailscale 100.x IP (empty if not on tailnet)
    tailscale_hostname: Tailscale hostname
    public_ip:      Public IP (discovered via STUN)
    public_port:    Public port mapped by NAT
    nat_type:       "none" | "full_cone" | "restricted" | "symmetric" | "unknown"
    capabilities:   List of supported transports
    last_seen:      Unix timestamp of last refresh
    rtt_ms:         Round-trip time in ms (probed periodically)
    """

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
            "public_port": self.public_port,
            "nat_type": self.nat_type,
            "capabilities": list(self.capabilities),
            "last_seen": self.last_seen,
            "rtt_ms": self.rtt_ms,
        }


@dataclass
class PathAssessment:
    """Result of assessing the best path between two devices.

    Attributes
    ----------
    source:         Source device_id
    target:         Target device_id
    best_path:      One of "same_subnet" | "same_tailnet" | "p2p_quic" |
                    "p2p_webrtc" | "derp_relay" | "gateway_ws"
    recommended_transport:  Transport type to use
    estimated_rtt_ms:       Estimated round-trip time
    reason:         Human-readable explanation
    """

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


# ── Network Topology Runtime ─────────────────────────────────────────────


class NetworkTopologyRuntime:
    """Real-time network topology map for global device communication.

    Usage::

        topo = get_network_topology_runtime()
        await topo.start()

        # Query best path to a device
        path = await topo.assess_path("my-device", "target-device")
        print(path.recommended_transport)  # "tcp" | "tailscale_p2p" | "quic" | ...

        # Get all devices on same subnet
        neighbors = topo.get_same_subnet_devices("my-device")

        # Get all devices on same tailnet
        tailnet_peers = topo.get_tailnet_peers("my-device")
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
        """Start topology discovery and monitoring."""
        self._my_device_id = device_id or self._detect_device_id()
        self._running = True

        # Discover my own network position
        self._my_position = await self._discover_self()
        self._my_position.device_id = self._my_device_id

        with self._lock:
            self._positions[self._my_device_id] = self._my_position

        # Start periodic refresh
        self._probe_task = asyncio.create_task(
            self._refresh_loop(),
            name="network_topology_refresh",
        )
        logger.info(
            "NetworkTopologyRuntime started | device=%s lan=%s ts=%s public=%s",
            self._my_device_id,
            self._my_position.lan_subnet,
            self._my_position.tailscale_ip or "none",
            self._my_position.public_ip or "none",
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
                # Merge: update fields that changed
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
        """Remove a device from topology."""
        with self._lock:
            self._positions.pop(device_id, None)

    async def assess_path(self, source: str, target: str) -> PathAssessment:
        """Assess the best network path from source to target device.

        This is the core method used by AIPTransport for smart transport
        selection. Returns a PathAssessment with recommended transport.
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

        # Path 1: Same subnet → TCP/UDP direct
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
            # Both on Tailscale: P2P direct through WireGuard tunnel
            return PathAssessment(
                source=source, target=target,
                best_path="same_tailnet",
                recommended_transport="tailscale_p2p",
                estimated_rtt_ms=max(5.0, min(src_pos.rtt_ms, tgt_pos.rtt_ms)),
                reason=f"Tailscale P2P: {src_pos.tailscale_ip} -> {tgt_pos.tailscale_ip}",
            )

        # Path 3: P2P capable (both have public IPs or good NAT)
        if tgt_pos.public_ip and tgt_pos.nat_type in ("full_cone", "restricted", "none"):
            if "quic" in tgt_pos.capabilities:
                return PathAssessment(
                    source=source, target=target,
                    best_path="p2p_quic",
                    recommended_transport="quic",
                    estimated_rtt_ms=50.0,
                    reason=f"QUIC P2P to {tgt_pos.public_ip}:{tgt_pos.public_port}",
                )
            if "webrtc" in tgt_pos.capabilities:
                return PathAssessment(
                    source=source, target=target,
                    best_path="p2p_webrtc",
                    recommended_transport="webrtc",
                    estimated_rtt_ms=40.0,
                    reason=f"WebRTC P2P to {tgt_pos.public_ip}",
                )

        # Path 4: DERP relay (Tailscale fallback)
        if src_pos.tailscale_ip and not tgt_pos.tailscale_ip:
            # Target not on tailnet but source is — can still reach via DERP
            return PathAssessment(
                source=source, target=target,
                best_path="derp_relay",
                recommended_transport="derp_relay",
                estimated_rtt_ms=150.0,
                reason="Target not on tailnet, using DERP relay",
            )

        # Path 5: Gateway WebSocket (ultimate fallback)
        return PathAssessment(
            source=source, target=target,
            best_path="gateway_ws",
            recommended_transport="websocket",
            estimated_rtt_ms=100.0,
            reason="No P2P path available, fallback to WebSocket gateway",
        )

    def get_same_subnet_devices(self, device_id: str) -> List[str]:
        """Get all device IDs on the same LAN subnet."""
        with self._lock:
            my_pos = self._positions.get(device_id)
            if not my_pos or not my_pos.lan_subnet:
                return []
            return [
                did for did, pos in self._positions.items()
                if did != device_id and pos.lan_subnet == my_pos.lan_subnet
            ]

    def get_tailnet_peers(self, device_id: str) -> List[str]:
        """Get all device IDs on the same Tailscale tailnet."""
        with self._lock:
            my_pos = self._positions.get(device_id)
            if not my_pos or not my_pos.tailscale_ip:
                return []
            return [
                did for did, pos in self._positions.items()
                if did != device_id and pos.tailscale_ip
            ]

    def get_p2p_capable_devices(self, device_id: str) -> List[str]:
        """Get devices reachable via P2P (public IP + good NAT)."""
        with self._lock:
            return [
                did for did, pos in self._positions.items()
                if did != device_id
                and pos.public_ip
                and pos.nat_type in ("full_cone", "restricted", "none")
            ]

    def get_topology_summary(self) -> Dict[str, Any]:
        """Return a JSON-safe summary of the current topology."""
        with self._lock:
            return {
                "my_device_id": self._my_device_id,
                "my_position": self._my_position.to_dict(),
                "device_count": len(self._positions),
                "devices": {did: pos.to_dict() for did, pos in self._positions.items()},
            }

    # ── Internal: Self discovery ────────────────────────────────────

    async def _discover_self(self) -> NetworkPosition:
        """Discover this device's own network position."""
        pos = NetworkPosition()

        # LAN subnet + IP
        try:
            pos.lan_ip = self._get_lan_ip()
            pos.lan_subnet = self._subnet_from_ip(pos.lan_ip)
        except Exception as exc:
            logger.debug("LAN discovery failed: %s", exc)

        # Tailscale
        try:
            ts_ip, ts_host = await self._get_tailscale_info()
            pos.tailscale_ip = ts_ip
            pos.tailscale_hostname = ts_host
        except Exception as exc:
            logger.debug("Tailscale discovery failed: %s", exc)

        # Public IP + NAT type
        try:
            pos.public_ip, pos.public_port, pos.nat_type = await self._stun_discovery()
        except Exception as exc:
            logger.debug("STUN discovery failed: %s", exc)

        # Capabilities
        pos.capabilities = self._detect_capabilities()

        return pos

    @staticmethod
    def _detect_device_id() -> str:
        """Generate a device ID from hostname + platform."""
        hostname = platform.node() or "unknown"
        system = platform.system().lower()
        return f"{system}-{hostname}"

    @staticmethod
    def _get_lan_ip() -> str:
        """Get the primary LAN IP address."""
        # Try to connect to a public address to determine outgoing interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip

    @staticmethod
    def _subnet_from_ip(ip: str, prefix: int = 24) -> str:
        """Derive subnet CIDR from IP address."""
        try:
            network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
            return str(network)
        except Exception:
            return ""

    async def _get_tailscale_info(self) -> Tuple[str, str]:
        """Get Tailscale IP and hostname. Returns (ip, hostname)."""
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                import json
                status = json.loads(result.stdout)
                ip = status.get("Self", {}).get("TailscaleIPs", [""])[0]
                hostname = status.get("Self", {}).get("HostName", "")
                return ip, hostname
        except Exception:
            pass
        return "", ""

    async def _stun_discovery(self) -> Tuple[str, int, str]:
        """Discover public IP, port, and NAT type via STUN.

        Returns: (public_ip, public_port, nat_type)
        """
        # Lightweight STUN — try each server
        for host, port in _STUN_SERVERS:
            try:
                result = await self._stun_request(host, port)
                if result:
                    return result
            except Exception:
                continue
        return "", 0, "unknown"

    @staticmethod
    async def _stun_request(host: str, port: int) -> Optional[Tuple[str, int, str]]:
        """Perform a single STUN binding request."""
        try:
            import stun  # optional dependency
            nat_type, external_ip, external_port = stun.get_ip_info(
                stun_host=host, stun_port=port,
            )
            return external_ip, external_port, nat_type
        except ImportError:
            # Fallback: simple UDP socket probe
            return await NetworkTopologyRuntime._udp_stun_fallback(host, port)

    @staticmethod
    async def _udp_stun_fallback(host: str, port: int) -> Optional[Tuple[str, int, str]]:
        """Fallback STUN using raw UDP socket."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3.0)
            # Simple STUN binding request (RFC 5389)
            tid = bytes([0x21, 0x12, 0xA4, 0x42]) + bytes(12)
            req = bytes([0x00, 0x01, 0x00, 0x00]) + tid
            sock.sendto(req, (host, port))
            data, _ = sock.recvfrom(1024)
            sock.close()
            if len(data) >= 20:
                # Parse XOR-MAPPED-ADDRESS attribute
                # Simplified: extract IP from response
                # Full parsing would walk attributes
                return "", 0, "unknown"
        except Exception:
            pass
        return None

    @staticmethod
    def _detect_capabilities() -> List[str]:
        """Detect which transports this device supports."""
        caps = ["websocket", "tcp", "udp"]

        # Check Tailscale
        if shutil.which("tailscale"):
            caps.append("tailscale_p2p")
            caps.append("derp_relay")

        # Check QUIC (aioquic available)
        try:
            import aioquic  # noqa: F401
            caps.append("quic")
        except ImportError:
            pass

        # Check WebRTC (aiortc available)
        try:
            import aiortc  # noqa: F401
            caps.append("webrtc")
        except ImportError:
            pass

        # Check MQTT (paho available)
        try:
            import paho.mqtt.client  # noqa: F401
            caps.append("mqtt")
        except ImportError:
            pass

        # BLE only on Linux/Android with dbus
        if platform.system() == "Linux":
            try:
                import dbus  # noqa: F401
                caps.append("ble")
            except ImportError:
                pass

        return caps

    # ── Internal: Refresh loop ──────────────────────────────────────

    async def _refresh_loop(self) -> None:
        """Periodic topology refresh."""
        while self._running:
            try:
                await asyncio.sleep(_TOPOLOGY_PROBE_INTERVAL)
                if not self._running:
                    break

                # Refresh self
                new_pos = await self._discover_self()
                new_pos.device_id = self._my_device_id
                with self._lock:
                    self._my_position = new_pos
                    self._positions[self._my_device_id] = new_pos

                # Probe RTT to known peers
                await self._probe_peer_rtts()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Topology refresh error: %s", exc)

    async def _probe_peer_rtts(self) -> None:
        """Probe RTT to all known peers."""
        with self._lock:
            peers = list(self._positions.items())

        for device_id, pos in peers:
            if device_id == self._my_device_id:
                continue
            # Try to ping via best available path
            rtt = await self._probe_rtt(pos)
            if rtt > 0:
                with self._lock:
                    if device_id in self._positions:
                        self._positions[device_id].rtt_ms = rtt
                        self._positions[device_id].last_seen = time.time()

    async def _probe_rtt(self, pos: NetworkPosition) -> float:
        """Probe RTT to a peer via best available path. Returns ms or -1."""
        # Try Tailscale IP first
        if pos.tailscale_ip:
            rtt = await self._ping_host(pos.tailscale_ip)
            if rtt > 0:
                return rtt
        # Try LAN IP
        if pos.lan_ip:
            rtt = await self._ping_host(pos.lan_ip)
            if rtt > 0:
                return rtt
        return -1.0

    @staticmethod
    async def _ping_host(host: str, timeout: float = 2.0) -> float:
        """Ping a host, return RTT in ms or -1."""
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", str(int(timeout)), host],
                capture_output=True, text=True, timeout=timeout + 1,
            )
            if result.returncode == 0:
                # Parse time=XX.X ms from output
                import re
                match = re.search(r"time=([\d.]+)\s*ms", result.stdout)
                if match:
                    return float(match.group(1))
        except Exception:
            pass
        return -1.0


# ── Singleton ────────────────────────────────────────────────────────────

_topology_instance: Optional[NetworkTopologyRuntime] = None
_topology_lock = threading.Lock()


def get_network_topology_runtime() -> NetworkTopologyRuntime:
    """Return the process-wide NetworkTopologyRuntime singleton."""
    global _topology_instance
    if _topology_instance is None:
        with _topology_lock:
            if _topology_instance is None:
                _topology_instance = NetworkTopologyRuntime()
    return _topology_instance


def reset_network_topology_runtime() -> None:
    """Reset singleton (for testing)."""
    global _topology_instance
    with _topology_lock:
        _topology_instance = None
