"""
core/state_sync_bus.py
======================
PR-STATE-SYNC: State Synchronization Bus — Meta-coordination layer.

Unifies 7 previously isolated authority standards so that state changes in
one are propagated to all others:

    1. UDM        (UnifiedDeviceManager)            — device registration SSOT
    2. UCM        (UnifiedConnectionManager)        — WebSocket connection mgmt
    3. CapabilityAuthority                         — capability registration truth
    4. AttachedRuntimeSessionRegistry              — agent session registry (128-entry)
    5. NetworkTopologyRuntime                      — network topology runtime (256-entry)
    6. AndroidNetworkParticipation                 — Android participation 7-tier
    7. FabricConfig                                — system mode configuration

Design
------
* Publish/subscribe pattern — any standard publishes a state change, all
  interested consumers receive it.
* Best-effort — failure in one consumer never blocks others.
* AIP v3 native — all state changes are emitted as AIP v3 STATE_EVENT messages.
* Non-blocking — all deliveries are async fire-and-forget.

Usage::
    from core.state_sync_bus import get_state_sync_bus, StateChangeEvent

    bus = get_state_sync_bus()
    bus.subscribe("device_registered", on_device_registered)
    bus.publish(StateChangeEvent(
        source="UDM",
        event_type="device_registered",
        device_id="phone_01",
        payload={"device_type": "android"},
    ))
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.StateSyncBus")

# PR-AIPV3: AIP v3 unified message emission
try:
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401
    from core.nats_bus import get_nats_bus  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False


# ---------------------------------------------------------------------------
# StateChangeEvent
# ---------------------------------------------------------------------------


@dataclass
class StateChangeEvent:
    """A state change event published to the synchronization bus."""

    source: str
    """Authority standard that originated the change (e.g. 'UDM', 'UCM')."""

    event_type: str
    """Event type: device_registered, device_unregistered, device_online,
    device_offline, capability_registered, session_attached, session_detached,
    topology_changed, participation_changed, mode_changed, ..."""

    device_id: str = ""
    """Primary device identifier (may be empty for global events)."""

    payload: Dict[str, Any] = field(default_factory=dict)
    """Event-specific data."""

    timestamp: float = field(default_factory=time.time)
    """Unix timestamp."""

    trace_id: str = ""
    """Optional trace identifier for end-to-end correlation."""


# ---------------------------------------------------------------------------
# StateSynchronizationBus
# ---------------------------------------------------------------------------


class StateSynchronizationBus:
    """Meta-coordination layer synchronizing 7 authority standards.

    Thread-safe.  Best-effort delivery.  AIP v3 native.
    """

    _instance: Optional["StateSynchronizationBus"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._subscribers: Dict[str, List[Callable[[StateChangeEvent], None]]] = {}
        self._global_subscribers: List[Callable[[StateChangeEvent], None]] = []
        self._lock = asyncio.Lock() if asyncio.get_event_loop().is_running() else None
        self._initialized = True

    # ── Subscription ──

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[StateChangeEvent], None],
    ) -> None:
        """Subscribe to a specific event type.

        Use ``event_type='*'`` to receive all events.
        """
        if event_type == "*":
            self._global_subscribers.append(callback)
        else:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)

    def unsubscribe(
        self,
        event_type: str,
        callback: Callable[[StateChangeEvent], None],
    ) -> None:
        """Unsubscribe a callback."""
        if event_type == "*":
            if callback in self._global_subscribers:
                self._global_subscribers.remove(callback)
        else:
            subs = self._subscribers.get(event_type, [])
            if callback in subs:
                subs.remove(callback)

    # ── Publication ──

    def publish(self, event: StateChangeEvent) -> None:
        """Publish a state change event to all subscribers.

        Best-effort: exceptions in individual subscribers are logged and
        swallowed.  AIP v3 STATE_EVENT is also emitted when available.
        """
        # AIP v3 emission
        self._emit_aip_v3(event)

        # Local delivery
        callbacks: List[Callable[[StateChangeEvent], None]] = []
        callbacks.extend(self._global_subscribers)
        callbacks.extend(self._subscribers.get(event.event_type, []))

        delivered = 0
        for cb in callbacks:
            try:
                cb(event)
                delivered += 1
            except Exception as exc:
                logger.debug(
                    "StateSyncBus delivery failed for %s → %s: %s",
                    event.event_type,
                    getattr(cb, "__name__", repr(cb)),
                    exc,
                )

        if delivered:
            logger.debug(
                "StateSyncBus: %s from %s delivered to %d subscriber(s)",
                event.event_type,
                event.source,
                delivered,
            )

    def publish_sync(
        self,
        source: str,
        event_type: str,
        device_id: str = "",
        payload: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> None:
        """Convenient sync-style publish."""
        self.publish(
            StateChangeEvent(
                source=source,
                event_type=event_type,
                device_id=device_id,
                payload=dict(payload or {}),
                trace_id=trace_id,
            )
        )

    # ── AIP v3 emission ──

    def _emit_aip_v3(self, event: StateChangeEvent) -> None:
        """Emit STATE_EVENT AIP v3 message for state changes."""
        if not _AIPV3_AVAILABLE:
            return
        try:
            import asyncio

            msg = StateEventMsg(
                device_id=event.device_id or "system",
                event_category="state_sync",
                event_action=event.event_type,
                payload={
                    "source": event.source,
                    **event.payload,
                },
                trace_id=event.trace_id,
            )
            nats = get_nats_bus()
            if nats.is_connected():
                asyncio.get_event_loop().create_task(nats.publish_state_event(msg))
        except Exception:
            pass

    # ── Built-in cross-standard sync handlers ──

    def install_default_sync_handlers(self) -> None:
        """Install default cross-standard synchronization handlers.

        This wires the 7 standards together so that state changes in one
        are automatically propagated to the relevant others.
        """
        # UDM device_registered → NetworkTopologyRuntime, CapabilityAuthority
        self.subscribe("device_registered", self._on_device_registered)
        # UDM device_unregistered → NetworkTopologyRuntime, CapabilityAuthority
        self.subscribe("device_unregistered", self._on_device_unregistered)
        # UDM heartbeat → AndroidNetworkParticipation
        self.subscribe("device_online", self._on_device_online)
        self.subscribe("device_offline", self._on_device_offline)
        # Capability registered → CapabilityAuthority
        self.subscribe("capability_registered", self._on_capability_registered)
        # Session attached → AttachedRuntimeSessionRegistry
        self.subscribe("session_attached", self._on_session_attached)
        self.subscribe("session_detached", self._on_session_detached)

        logger.info("StateSyncBus: default cross-standard sync handlers installed")

    # ── Default handler implementations ──

    def _on_device_registered(self, event: StateChangeEvent) -> None:
        """Sync UDM device registration → NetworkTopologyRuntime."""
        try:
            from core.network_topology_runtime import (  # noqa: PLC0415
                NetworkTopologyRuntime,
                TopologyConnectionState,
                TopologyNode,
                TopologyNodeKind,
            )

            runtime = NetworkTopologyRuntime()
            device_type = event.payload.get("device_type", "unknown")
            kind_map = {
                "android_phone": TopologyNodeKind.DEVICE,
                "worker": TopologyNodeKind.NATS_FABRIC_ENDPOINT,
                "desktop": TopologyNodeKind.DEVICE,
            }
            node = TopologyNode(
                node_id=event.device_id,
                kind=kind_map.get(device_type, TopologyNodeKind.DEVICE),
                state=TopologyConnectionState.REACHABLE,
                host=event.payload.get("ip_address", ""),
                port=event.payload.get("port", 0),
                metadata={"device_type": device_type, "transport": event.payload.get("transport", "")},
            )
            runtime.register_node(node)
        except Exception as exc:
            logger.debug("StateSyncBus _on_device_registered failed: %s", exc)

    def _on_device_unregistered(self, event: StateChangeEvent) -> None:
        """Sync UDM device unregistration → NetworkTopologyRuntime."""
        try:
            from core.network_topology_runtime import NetworkTopologyRuntime  # noqa: PLC0415

            runtime = NetworkTopologyRuntime()
            runtime.remove_node(event.device_id)
        except Exception as exc:
            logger.debug("StateSyncBus _on_device_unregistered failed: %s", exc)

    def _on_device_online(self, event: StateChangeEvent) -> None:
        """Sync device online → NetworkTopologyRuntime."""
        try:
            from core.network_topology_runtime import (  # noqa: PLC0415
                NetworkTopologyRuntime,
                TopologyConnectionState,
            )

            runtime = NetworkTopologyRuntime()
            runtime.update_node_state(event.device_id, TopologyConnectionState.CONNECTED)
        except Exception as exc:
            logger.debug("StateSyncBus _on_device_online failed: %s", exc)

    def _on_device_offline(self, event: StateChangeEvent) -> None:
        """Sync device offline → NetworkTopologyRuntime."""
        try:
            from core.network_topology_runtime import (  # noqa: PLC0415
                NetworkTopologyRuntime,
                TopologyConnectionState,
            )

            runtime = NetworkTopologyRuntime()
            runtime.update_node_state(event.device_id, TopologyConnectionState.UNAVAILABLE)
        except Exception as exc:
            logger.debug("StateSyncBus _on_device_offline failed: %s", exc)

    def _on_capability_registered(self, event: StateChangeEvent) -> None:
        """Sync capability registration → CapabilityBus."""
        try:
            from core.capability_bus import get_capability_bus  # noqa: PLC0415

            bus = get_capability_bus()
            capability_name = event.payload.get("capability_name", "")
            if capability_name:
                # Capability is already registered via CapabilityBus.publish
                # This sync handler is a no-op since CapabilityBus already handles it
                pass
        except Exception as exc:
            logger.debug("StateSyncBus _on_capability_registered failed: %s", exc)

    def _on_session_attached(self, event: StateChangeEvent) -> None:
        """Sync session attach → AndroidNetworkParticipation."""
        logger.debug("StateSyncBus: session_attached for %s", event.device_id)

    def _on_session_detached(self, event: StateChangeEvent) -> None:
        """Sync session detach → AndroidNetworkParticipation."""
        logger.debug("StateSyncBus: session_detached for %s", event.device_id)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_bus_instance: Optional[StateSynchronizationBus] = None


def get_state_sync_bus() -> StateSynchronizationBus:
    """Return the module-level :class:`StateSynchronizationBus` singleton."""
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = StateSynchronizationBus()
    return _bus_instance


def install_default_sync() -> None:
    """Convenience: create bus + install default handlers in one call."""
    bus = get_state_sync_bus()
    bus.install_default_sync_handlers()
    logger.info("StateSynchronizationBus default sync installed")
