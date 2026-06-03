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

Design:
- Persistent TCP connection pool (one per target device)
- Thread-safe connection management (asyncio.Lock)
- Periodic connection health check (60s interval, dead conns auto-purged)
- Explicit device_id → tailscale_ip registration (from MeshCoordinator)
- Peer cache from `tailscale status --json` (hostname → ts_ip)
- Fuzzy matching for device_id resolution

Usage:
    Registered automatically in lifecycle.py Phase 8 if Tailscale is available.
    AIPTransport auto-selects this adapter when target is on same tailnet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from core.aip_transport import TransportAdapter

logger = logging.getLogger("Galaxy.Adapter.TailscaleP2P")

# ── Constants ────────────────────────────────────────────────────────────

_DEFAULT_P2P_PORT = 19721           # Tailscale P2P direct port
_CONNECT_TIMEOUT = 5.0              # seconds
_READ_TIMEOUT = 10.0                # seconds for inbound read
_PEER_CACHE_TTL = 60.0              # seconds: peer cache freshness
_HEALTH_CHECK_INTERVAL = 60.0       # seconds: connection pool health check
_MAX_MSG_SIZE = 10 * 1024 * 1024    # 10MB max message


class _ConnectionEntry:
    """A pooled connection with metadata."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        device_id: str,
        ts_ip: str,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.device_id = device_id
        self.ts_ip = ts_ip
        self.created_at = time.time()
        self.last_used = time.time()
        self.msg_count = 0

    @property
    def is_alive(self) -> bool:
        return not self.writer.is_closing()

    def touch(self) -> None:
        self.last_used = time.time()
        self.msg_count += 1


class TailscaleP2PAdapter(TransportAdapter):
    """Tailscale P2P transport adapter for AIPTransport.

    Sends AIP v3 messages directly to target devices via their Tailscale
    100.x.x.x IPs through the WireGuard tunnel. No Galaxy Gateway relay.

    Requirements:
    - Tailscale must be installed and running on this device
    - Target device must be on the same tailnet (have a 100.x IP)
    - Target device must be listening on the P2P port via this adapter
    """

    @property
    def transport_type(self) -> str:
        return "tailscale_p2p"

    def __init__(self, p2p_port: int = _DEFAULT_P2P_PORT) -> None:
        self._p2p_port = p2p_port
        self._available = False
        self._my_ts_ip: Optional[str] = None
        self._my_hostname: str = ""
        # Explicit device_id → ts_ip registration (from MeshCoordinator etc.)
        self._device_registry: Dict[str, str] = {}
        # Peer cache from tailscale status: hostname → (ts_ip, timestamp)
        self._peer_cache: Dict[str, Tuple[str, float]] = {}
        # Connection pool: device_id → _ConnectionEntry
        self._connections: Dict[str, _ConnectionEntry] = {}
        self._conn_lock = asyncio.Lock()
        # Health check task
        self._health_task: Optional[asyncio.Task] = None
        self._running = False

    # ── TransportAdapter interface ──────────────────────────────────

    async def initialize(self) -> bool:
        """Detect Tailscale and populate peer cache."""
        try:
            self._my_ts_ip, self._my_hostname = await self._detect_self()
            if self._my_ts_ip:
                self._available = True
                await self._refresh_peer_cache()
                self._running = True
                # Start health check loop
                self._health_task = asyncio.create_task(
                    self._health_check_loop(),
                    name="tailscale_p2p_health",
                )
                logger.info(
                    "TailscaleP2PAdapter initialized | ip=%s host=%s peers=%d",
                    self._my_ts_ip, self._my_hostname, len(self._peer_cache),
                )
                return True
        except Exception as exc:
            logger.debug("TailscaleP2PAdapter init failed: %s", exc)
        self._available = False
        return False

    async def send(self, message: Dict[str, Any], target: str) -> Dict[str, Any]:
        """Send AIP v3 message to target device via Tailscale P2P."""
        if not self._available:
            return {"success": False, "error": "TailscaleP2P not available"}

        ts_ip = self._resolve_target(target)
        if not ts_ip:
            return {"success": False, "error": f"Target {target} not in tailnet registry"}

        start = time.time()
        try:
            entry = await self._acquire_connection(target, ts_ip)
            payload = json.dumps(message, default=str).encode("utf-8")
            if len(payload) > _MAX_MSG_SIZE:
                return {"success": False, "error": "Message too large"}
            # Frame: 4-byte length prefix + JSON payload
            frame = len(payload).to_bytes(4, "big") + payload
            entry.writer.write(frame)
            await entry.writer.drain()
            entry.touch()

            rtt = (time.time() - start) * 1000
            return {"success": True, "via": "tailscale_p2p", "rtt_ms": round(rtt, 2)}
        except Exception as exc:
            # Remove broken connection
            async with self._conn_lock:
                self._connections.pop(target, None)
            logger.debug("Tailscale P2P send to %s (%s) failed: %s", target, ts_ip, exc)
            return {"success": False, "error": f"Tailscale P2P failed: {exc}"}

    async def is_available(self, target: str) -> bool:
        """Check if target is reachable via Tailscale P2P."""
        if not self._available:
            return False
        ts_ip = self._resolve_target(target)
        if not ts_ip:
            return False
        # Quick TCP probe
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ts_ip, self._p2p_port),
                timeout=1.5,
            )
            writer.close()
            return True
        except Exception:
            return False

    async def broadcast(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Broadcast to all known tailnet peers."""
        if not self._available:
            return {"success": False, "error": "TailscaleP2P not available"}

        # Combine registry + peer cache
        all_targets: Dict[str, str] = {}
        for did, ts_ip in self._device_registry.items():
            all_targets[did] = ts_ip
        for hostname, (ts_ip, _) in self._peer_cache.items():
            if hostname not in all_targets:
                all_targets[hostname] = ts_ip

        results = {}
        for device_id, ts_ip in all_targets.items():
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
        """Close all persistent connections and stop health check."""
        self._running = False
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        async with self._conn_lock:
            for entry in list(self._connections.values()):
                try:
                    entry.writer.close()
                    await entry.writer.wait_closed()
                except Exception:
                    pass
            self._connections.clear()
        logger.debug("TailscaleP2PAdapter closed")

    # ── Device registration (called by MeshCoordinator etc.) ────────

    def register_device(self, device_id: str, tailscale_ip: str) -> None:
        """Explicitly register a device_id → tailscale_ip mapping.

        Called by MeshCoordinator when a peer announces with tailscale_ip.
        This is the primary way device_ids are mapped to Tailscale IPs.
        """
        if tailscale_ip:
            self._device_registry[device_id] = tailscale_ip
            logger.debug("Registered device %s → %s", device_id, tailscale_ip)

    def unregister_device(self, device_id: str) -> None:
        """Remove a device registration."""
        self._device_registry.pop(device_id, None)
        # Also close any connection
        entry = self._connections.pop(device_id, None)
        if entry:
            try:
                entry.writer.close()
            except Exception:
                pass

    def list_registered_devices(self) -> Dict[str, str]:
        """Return all registered device_id → ts_ip mappings."""
        return dict(self._device_registry)

    def get_stats(self) -> Dict[str, Any]:
        """Return connection pool stats for monitoring."""
        return {
            "available": self._available,
            "my_ts_ip": self._my_ts_ip,
            "registry_size": len(self._device_registry),
            "peer_cache_size": len(self._peer_cache),
            "connection_pool_size": len(self._connections),
            "connections": {
                did: {
                    "ts_ip": e.ts_ip,
                    "alive": e.is_alive,
                    "msg_count": e.msg_count,
                    "idle_seconds": round(time.time() - e.last_used, 1),
                }
                for did, e in self._connections.items()
            },
        }

    # ── Internal: connection management ─────────────────────────────

    async def _acquire_connection(self, device_id: str, ts_ip: str) -> _ConnectionEntry:
        """Get or create a pooled connection (thread-safe)."""
        async with self._conn_lock:
            # Check existing connection
            entry = self._connections.get(device_id)
            if entry is not None:
                if entry.is_alive and entry.ts_ip == ts_ip:
                    return entry
                # Stale or wrong IP — remove
                try:
                    entry.writer.close()
                except Exception:
                    pass
                del self._connections[device_id]

            # Create new connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ts_ip, self._p2p_port),
                timeout=_CONNECT_TIMEOUT,
            )
            entry = _ConnectionEntry(reader, writer, device_id, ts_ip)
            self._connections[device_id] = entry
            logger.debug("New P2P connection: %s → %s:%d", device_id, ts_ip, self._p2p_port)
            return entry

    async def _health_check_loop(self) -> None:
        """Periodic health check: purge dead connections, refresh peer cache."""
        while self._running:
            try:
                await asyncio.sleep(_HEALTH_CHECK_INTERVAL)
            except asyncio.CancelledError:
                break
            if not self._running:
                break

            # Purge dead connections
            async with self._conn_lock:
                dead = [
                    did for did, e in list(self._connections.items())
                    if not e.is_alive
                ]
                for did in dead:
                    entry = self._connections.pop(did, None)
                    if entry:
                        try:
                            entry.writer.close()
                        except Exception:
                            pass
                    logger.debug("Health check: purged dead connection to %s", did)

            # Refresh peer cache
            try:
                await self._refresh_peer_cache()
            except Exception:
                pass

    # ── Internal: Tailscale discovery ───────────────────────────────

    async def _detect_self(self) -> Tuple[Optional[str], str]:
        """Detect own Tailscale IP and hostname."""
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
                        self._peer_cache[hostname] = (ts_ips[0], now)
        except Exception as exc:
            logger.debug("Peer cache refresh failed: %s", exc)

    def _resolve_target(self, target: str) -> Optional[str]:
        """Resolve device_id to Tailscale IP.

        Resolution order:
        1. Explicit device registry (device_id → ts_ip)
        2. Peer cache exact match
        3. Peer cache fuzzy match
        4. None
        """
        # 1. Explicit registry (most reliable)
        ts_ip = self._device_registry.get(target)
        if ts_ip:
            return ts_ip

        # 2. Peer cache exact match
        cached = self._peer_cache.get(target)
        if cached:
            return cached[0]

        # 3. Peer cache fuzzy match
        target_lower = target.lower()
        for hostname, (ts_ip, ts) in self._peer_cache.items():
            if target_lower in hostname.lower() or hostname.lower() in target_lower:
                # Cache the match for next time
                self._device_registry[target] = ts_ip
                return ts_ip

        return None

    # ── Server side (inbound) ───────────────────────────────────────

    async def start_server(self, host: str = "", port: int = 0) -> asyncio.Server:
        """Start TCP server for inbound Tailscale P2P connections."""
        bind_host = host or self._my_ts_ip or "0.0.0.0"
        bind_port = port or self._p2p_port

        server = await asyncio.start_server(
            self._handle_inbound,
            host=bind_host,
            port=bind_port,
        )
        logger.info("Tailscale P2P server on %s:%d", bind_host, bind_port)
        return server

    async def _handle_inbound(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
    ) -> None:
        """Handle inbound P2P connection."""
        peer_addr = writer.get_extra_info("peername")
        logger.debug("Inbound P2P from %s", peer_addr)

        try:
            while True:
                len_bytes = await asyncio.wait_for(reader.read(4), timeout=_READ_TIMEOUT)
                if len(len_bytes) < 4:
                    break

                msg_len = int.from_bytes(len_bytes, "big")
                if msg_len > _MAX_MSG_SIZE:
                    logger.warning("Oversized message from %s: %d bytes", peer_addr, msg_len)
                    break

                payload_bytes = await asyncio.wait_for(reader.read(msg_len), timeout=_READ_TIMEOUT)
                if len(payload_bytes) < msg_len:
                    break

                message = json.loads(payload_bytes.decode("utf-8"))
                await self._dispatch_inbound(message, peer_addr)

        except asyncio.TimeoutError:
            pass
        except Exception as exc:
            logger.debug("P2P inbound from %s error: %s", peer_addr, exc)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch_inbound(
        self, message: Dict[str, Any], peer_addr: tuple,
    ) -> None:
        """Dispatch inbound AIP v3 message received via P2P."""
        try:
            message["_received_via"] = "tailscale_p2p"
            message["_peer_addr"] = f"{peer_addr[0]}:{peer_addr[1]}"

            from core.state_event_bus import get_state_event_bus
            get_state_event_bus().publish(
                "aip.tailscale_p2p.received",
                source="tailscale_p2p_adapter",
                payload=message,
            )
        except Exception as exc:
            logger.debug("Inbound dispatch error: %s", exc)
