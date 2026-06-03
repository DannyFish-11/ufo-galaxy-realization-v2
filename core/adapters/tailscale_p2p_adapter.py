"""
core.adapters.tailscale_p2p_adapter — Tailscale P2P Direct Transport Adapter
================================================================================
PR-28 — Tailscale WireGuard tunnel direct P2P transport for AIPTransport.

Tailscale creates an encrypted WireGuard overlay network where each device
gets a 100.x.x.x IP. Devices on the same tailnet can reach each other
directly via these IPs, even across NATs and firewalls.

This adapter enables AIPTransport to send AIP v3 messages directly through
Tailscale tunnels, bypassing the Galaxy Gateway WebSocket relay entirely.

Path characteristics:
    Same tailnet P2P:  latency ~5-20ms, encrypted WireGuard, NAT-traversal
    DERP relay fallback: latency ~80-300ms, still encrypted, global reach

Usage:
    Registered automatically in lifecycle.py Phase 8 if Tailscale is available.
    AIPTransport auto-selects this adapter when target is on same tailnet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any, Dict, List, Optional

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.TailscaleP2P")

# ── Constants ────────────────────────────────────────────────────────────

_DEFAULT_P2P_PORT = 19721           # Tailscale P2P direct port (distinct from LAN 19720)
_CONNECT_TIMEOUT = 5.0              # seconds
_READ_TIMEOUT = 10.0                # seconds
Peer_CACHE_TTL = 60.0               # seconds: how long to cache peer Tailscale IPs


class TailscaleP2PAdapter(TransportAdapter):
    """Tailscale P2P transport adapter for AIPTransport.

    Sends AIP v3 messages directly to target devices via their Tailscale
    100.x.x.x IPs through the WireGuard tunnel. No Galaxy Gateway relay.

    Requirements:
    - Tailscale must be installed and running on this device
    - Target device must be on the same tailnet (have a 100.x IP)
    - Target device must be listening on the P2P port via this adapter

    Singleton pattern: one persistent connection pool per target device.
    """

    @property
    def transport_type(self) -> str:
        return "tailscale_p2p"

    def __init__(self, p2p_port: int = _DEFAULT_P2P_PORT) -> None:
        self._p2p_port = p2p_port
        self._available = False           # set after successful tailscale detection
        self._my_ts_ip: Optional[str] = None
        self._my_hostname: str = ""
        # Cache of device_id -> (tailscale_ip, timestamp)
        self._peer_cache: Dict[str, tuple[str, float]] = {}
        # Persistent TCP connections: device_id -> (reader, writer)
        self._connections: Dict[str, tuple[Any, Any]] = {}

    # ── TransportAdapter interface ──────────────────────────────────

    async def initialize(self) -> bool:
        """Detect Tailscale and populate peer cache.

        Called from lifecycle.py Phase 8 during startup.
        Returns True if Tailscale is available and usable.
        """
        try:
            self._my_ts_ip, self._my_hostname = await self._detect_self()
            if self._my_ts_ip:
                self._available = True
                await self._refresh_peer_cache()
                logger.info(
                    "TailscaleP2PAdapter initialized | my_ip=%s hostname=%s peers=%d",
                    self._my_ts_ip, self._my_hostname, len(self._peer_cache),
                )
                return True
        except Exception as exc:
            logger.debug("TailscaleP2PAdapter init failed: %s", exc)
        self._available = False
        return False

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Send AIP v3 message to target device via Tailscale P2P.

        Args:
            message: AIP v3 message dict
            target:  target device_id

        Returns:
            {"success": bool, "via": "tailscale_p2p", "rtt_ms": float}
        """
        if not self._available:
            return {"success": False, "error": "TailscaleP2P not available"}

        ts_ip = await self._resolve_target(target)
        if not ts_ip:
            return {"success": False, "error": f"Target {target} not found in tailnet"}

        start = time.time()
        try:
            # Use persistent connection or create new one
            writer = await self._get_writer(ts_ip)
            payload = json.dumps(message, default=str).encode("utf-8")
            # Frame: 4-byte length prefix + JSON payload
            frame = len(payload).to_bytes(4, "big") + payload
            writer.write(frame)
            await writer.drain()

            rtt = (time.time() - start) * 1000
            return {"success": True, "via": "tailscale_p2p", "rtt_ms": round(rtt, 2)}
        except Exception as exc:
            # Connection broken — remove from pool and fail
            self._connections.pop(target, None)
            logger.debug("Tailscale P2P send to %s (%s) failed: %s", target, ts_ip, exc)
            return {"success": False, "error": f"Tailscale P2P failed: {exc}"}

    async def is_available(self, target: str) -> bool:
        """Check if target is reachable via Tailscale P2P.

        True if:
        1. Tailscale is running on this device
        2. Target has a cached Tailscale IP (is on same tailnet)
        3. Target responds to TCP probe on P2P port
        """
        if not self._available:
            return False

        ts_ip = await self._resolve_target(target)
        if not ts_ip:
            return False

        # Quick TCP connect probe
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ts_ip, self._p2p_port),
                timeout=1.0,
            )
            writer.close()
            return True
        except Exception:
            return False

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Broadcast to all known tailnet peers."""
        if not self._available:
            return {"success": False, "error": "TailscaleP2P not available"}

        results = {}
        await self._refresh_peer_cache()
        for device_id, (ts_ip, _) in list(self._peer_cache.items()):
            try:
                result = await self.send(message, device_id)
                results[device_id] = result
            except Exception as exc:
                results[device_id] = {"success": False, "error": str(exc)}

        ok = sum(1 for r in results.values() if r.get("success"))
        return {
            "success": ok > 0,
            "via": "tailscale_p2p",
            "sent": ok,
            "total": len(results),
            "results": results,
        }

    async def close(self) -> None:
        """Close all persistent connections."""
        for device_id, (reader, writer) in list(self._connections.items()):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._connections.clear()
        logger.debug("TailscaleP2PAdapter connections closed")

    # ── Internal helpers ────────────────────────────────────────────

    async def _detect_self(self) -> tuple[Optional[str], str]:
        """Detect own Tailscale IP and hostname.

        Returns: (tailscale_ip, hostname)
        """
        import shutil
        import subprocess

        if not shutil.which("tailscale"):
            return None, ""

        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                self_info = status.get("Self", {})
                ts_ips = self_info.get("TailscaleIPs", [])
                ts_ip = ts_ips[0] if ts_ips else None
                hostname = self_info.get("HostName", "")
                return ts_ip, hostname
        except Exception:
            pass
        return None, ""

    async def _refresh_peer_cache(self) -> None:
        """Refresh peer cache from tailscale status."""
        import shutil
        import subprocess

        if not shutil.which("tailscale"):
            return

        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                peers = status.get("Peer", {})
                now = time.time()
                for key, peer_info in peers.items():
                    ts_ips = peer_info.get("TailscaleIPs", [])
                    hostname = peer_info.get("HostName", key)
                    if ts_ips:
                        # Use hostname as device_id (matches MagicDNS)
                        self._peer_cache[hostname] = (ts_ips[0], now)
        except Exception as exc:
            logger.debug("Peer cache refresh failed: %s", exc)

    async def _resolve_target(self, target: str) -> Optional[str]:
        """Resolve device_id to Tailscale IP.

        1. Check cache
        2. If stale, refresh from tailscale status
        3. Try exact match, then fuzzy match
        """
        now = time.time()
        cached = self._peer_cache.get(target)
        if cached:
            ts_ip, ts = cached
            if now - ts < _Peer_CACHE_TTL:
                return ts_ip

        # Stale or missing — refresh
        await self._refresh_peer_cache()
        cached = self._peer_cache.get(target)
        if cached:
            return cached[0]

        # Try to match tailscale hostname from device_id
        # e.g., "android-pixel" might match "pixel.your-tailnet.ts.net"
        for hostname, (ts_ip, _) in self._peer_cache.items():
            if target.lower() in hostname.lower() or hostname.lower() in target.lower():
                return ts_ip

        return None

    async def _get_writer(self, ts_ip: str) -> Any:
        """Get or create a TCP writer for the given Tailscale IP.

        Uses persistent connections keyed by IP address.
        """
        # Check if we have a connection for this IP
        for device_id, (reader, writer) in list(self._connections.items()):
            # Check if connection is still alive
            if writer.is_closing():
                del self._connections[device_id]
                continue
            # We need to map ts_ip back to device_id — for now create new
            # Simplified: use ts_ip as key

        # Check existing connection by IP pseudo-key
        ip_key = f"_ip_{ts_ip}"
        existing = self._connections.get(ip_key)
        if existing:
            _, writer = existing
            if not writer.is_closing():
                return writer
            del self._connections[ip_key]

        # Create new connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ts_ip, self._p2p_port),
            timeout=_CONNECT_TIMEOUT,
        )
        self._connections[ip_key] = (reader, writer)
        logger.debug("New Tailscale P2P connection to %s:%d", ts_ip, self._p2p_port)
        return writer

    # ── Server side (inbound) ───────────────────────────────────────

    async def start_server(self, host: str = "", port: int = 0) -> asyncio.Server:
        """Start a TCP server listening for inbound Tailscale P2P connections.

        Binds to the Tailscale IP (100.x.x.x) by default, or 0.0.0.0 if
        tailscale IP is not detected.

        Args:
            host: Bind host (default: Tailscale IP, fallback 0.0.0.0)
            port: Port to bind (default: _DEFAULT_P2P_PORT)

        Returns:
            asyncio.Server instance
        """
        bind_host = host or self._my_ts_ip or "0.0.0.0"
        bind_port = port or self._p2p_port

        server = await asyncio.start_server(
            self._handle_inbound,
            host=bind_host,
            port=bind_port,
        )
        logger.info(
            "Tailscale P2P server listening on %s:%d", bind_host, bind_port,
        )
        return server

    async def _handle_inbound(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an inbound Tailscale P2P connection."""
        peer_addr = writer.get_extra_info("peername")
        logger.debug("Inbound Tailscale P2P connection from %s", peer_addr)

        try:
            while True:
                # Read 4-byte length prefix
                len_bytes = await asyncio.wait_for(reader.read(4), timeout=_READ_TIMEOUT)
                if len(len_bytes) < 4:
                    break  # Connection closed

                msg_len = int.from_bytes(len_bytes, "big")
                if msg_len > 10 * 1024 * 1024:  # 10MB max
                    logger.warning("Oversized message from %s: %d bytes", peer_addr, msg_len)
                    break

                # Read payload
                payload_bytes = await asyncio.wait_for(
                    reader.read(msg_len), timeout=_READ_TIMEOUT,
                )
                if len(payload_bytes) < msg_len:
                    break  # Incomplete

                message = json.loads(payload_bytes.decode("utf-8"))
                logger.debug("Received P2P message from %s: type=%s", peer_addr, message.get("type"))

                # Dispatch to message handler (AIP v3 message)
                await self._dispatch_inbound(message, peer_addr)

        except asyncio.TimeoutError:
            logger.debug("P2P connection from %s timed out", peer_addr)
        except Exception as exc:
            logger.debug("P2P connection from %s error: %s", peer_addr, exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch_inbound(
        self, message: Dict[str, Any], peer_addr: tuple,
    ) -> None:
        """Dispatch an inbound AIP v3 message.

        Subclasses or callers can override this to handle inbound messages.
        Default implementation routes to the AIP v3 ingress handler.
        """
        try:
            # Route to AIP v3 message handler
            from core.aip_transport import get_aip_transport
            # Mark as received via tailscale_p2p
            message["_received_via"] = "tailscale_p2p"
            message["_peer_addr"] = f"{peer_addr[0]}:{peer_addr[1]}"

            # Emit event for downstream processing
            from core.state_event_bus import get_state_event_bus
            get_state_event_bus().publish(
                "aip.tailscale_p2p.received",
                source="tailscale_p2p_adapter",
                payload=message,
            )
        except Exception as exc:
            logger.debug("Inbound dispatch error: %s", exc)
