"""
core/device_readiness.py
========================
Canonical device readiness aggregation layer.

Unifies ``registered``, ``online``, ``connected``, ``routable``, and basic
capability readiness checks across the existing codebase without changing
current routing behaviour.

This module is **additive only** — it does not modify any existing module
and degrades gracefully when optional subsystems are unavailable.

Public API
----------
Models:
    ConnectionSummary
    RoutabilitySummary
    DeviceReadinessSummary

Helpers:
    get_connection_summary(device_id) -> ConnectionSummary
    get_routability_summary(device_id) -> RoutabilitySummary
    get_device_readiness(device_id) -> DeviceReadinessSummary
    get_cross_device_ready_devices() -> list[DeviceReadinessSummary]
    is_device_cross_device_ready(device_id) -> bool
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DeviceReadiness")

__all__ = [
    "ConnectionSummary",
    "RoutabilitySummary",
    "DeviceReadinessSummary",
    "get_connection_summary",
    "get_routability_summary",
    "get_device_readiness",
    "get_cross_device_ready_devices",
    "is_device_cross_device_ready",
    "DEVICE_READINESS_AUTHORITY",
]

# Sentinel that identifies this module as the canonical authority.
DEVICE_READINESS_AUTHORITY: str = "DEVICE_READINESS_LAYER_V1"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@dataclass
class ConnectionSummary:
    """Aggregated connection state for a single device."""

    device_id: str
    websocket_connected: bool = False
    ucm_connected: bool = False
    router_present: bool = False
    connection_state: str = "disconnected"
    local_connection_id: Optional[str] = None
    last_heartbeat_at: Optional[str] = None
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "websocket_connected": self.websocket_connected,
            "ucm_connected": self.ucm_connected,
            "router_present": self.router_present,
            "connection_state": self.connection_state,
            "local_connection_id": self.local_connection_id,
            "last_heartbeat_at": self.last_heartbeat_at,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


@dataclass
class RoutabilitySummary:
    """Aggregated routing / transport availability for a single device."""

    device_id: str
    direct_ws_available: bool = False
    ucm_send_available: bool = False
    relay_available: bool = False
    mesh_direct_available: bool = False
    mesh_relay_available: bool = False
    effective_routable: bool = False
    preferred_path: str = "none"
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "direct_ws_available": self.direct_ws_available,
            "ucm_send_available": self.ucm_send_available,
            "relay_available": self.relay_available,
            "mesh_direct_available": self.mesh_direct_available,
            "mesh_relay_available": self.mesh_relay_available,
            "effective_routable": self.effective_routable,
            "preferred_path": self.preferred_path,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


@dataclass
class DeviceReadinessSummary:
    """Full readiness summary for a single device."""

    device_id: str
    registered: bool = False
    online: bool = False
    connected: bool = False
    routable: bool = False
    capability_ready: bool = False
    connection: ConnectionSummary = field(default=None)  # type: ignore[assignment]
    routability: RoutabilitySummary = field(default=None)  # type: ignore[assignment]
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.connection is None:
            self.connection = ConnectionSummary(device_id=self.device_id)
        if self.routability is None:
            self.routability = RoutabilitySummary(device_id=self.device_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "registered": self.registered,
            "online": self.online,
            "connected": self.connected,
            "routable": self.routable,
            "capability_ready": self.capability_ready,
            "connection": self.connection.to_dict(),
            "routability": self.routability.to_dict(),
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


# ---------------------------------------------------------------------------
# Internal helpers — defensive subsystem accessors
# ---------------------------------------------------------------------------


def _get_udm():
    """Return UnifiedDeviceManager singleton, or None on failure."""
    try:
        from core.unified.device_manager import get_unified_device_manager
        return get_unified_device_manager()
    except Exception as exc:  # pragma: no cover
        logger.debug("DeviceReadiness: UDM unavailable — %s", exc)
        return None


def _get_ucm():
    """Return UnifiedConnectionManager singleton, or None on failure."""
    try:
        from core.unified.connection_manager import UnifiedConnectionManager
        return UnifiedConnectionManager()
    except Exception as exc:  # pragma: no cover
        logger.debug("DeviceReadiness: UCM unavailable — %s", exc)
        return None


def _get_gateway_ws_manager():
    """Return the gateway GatewayWSManager, or None on failure."""
    try:
        from galaxy_gateway.app import websocket_manager  # type: ignore
        return websocket_manager
    except Exception:  # pragma: no cover
        return None


def _get_device_router():
    """Return the gateway DeviceRouter, or None on failure."""
    try:
        from galaxy_gateway.device_router import DeviceRouter  # type: ignore
        return DeviceRouter()
    except Exception:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# get_connection_summary
# ---------------------------------------------------------------------------


def get_connection_summary(device_id: str) -> ConnectionSummary:
    """Aggregate connection state for *device_id* from all available sources.

    Degrades gracefully: when a subsystem is unavailable the corresponding
    field stays ``False`` and a reason string is appended to
    ``ConnectionSummary.reasons``.
    """
    summary = ConnectionSummary(device_id=device_id)

    # --- UCM (primary source) ---
    ucm = _get_ucm()
    if ucm is None:
        summary.reasons.append("ucm_unavailable")
    else:
        try:
            conn_info = ucm.get_connection(device_id)
            if conn_info is not None:
                summary.ucm_connected = True
                state_val = conn_info.state
                summary.connection_state = (
                    state_val if isinstance(state_val, str) else state_val.value
                )
                summary.local_connection_id = getattr(conn_info, "connection_id", None)
                hb = getattr(conn_info, "last_heartbeat", None)
                if hb is not None:
                    summary.last_heartbeat_at = (
                        hb.isoformat() if hasattr(hb, "isoformat") else str(hb)
                    )
                summary.sources["ucm"] = {
                    "state": summary.connection_state,
                    "routable": conn_info.routable,
                }
            else:
                summary.reasons.append("ucm_no_connection_record")

            # direct websocket presence
            summary.websocket_connected = ucm.is_device_connected(device_id)
        except Exception as exc:
            logger.warning(
                "DeviceReadiness: UCM connection query failed",
                extra={
                    "event": "readiness_ucm_query_failed",
                    "device_id": device_id,
                    "error": str(exc),
                },
            )
            summary.reasons.append(f"ucm_query_error:{exc}")

    # --- Gateway WS manager (enrichment) ---
    gw_ws = _get_gateway_ws_manager()
    if gw_ws is not None:
        try:
            connected_ids = set(gw_ws.get_connected_devices() or [])
            if device_id in connected_ids:
                summary.websocket_connected = True
                summary.sources["gateway_ws"] = {"connected": True}
        except Exception as exc:
            logger.debug(
                "DeviceReadiness: gateway WS manager query failed for %s — %s",
                device_id,
                exc,
            )
            summary.reasons.append(f"gateway_ws_error:{exc}")

    # --- Device router (enrichment) ---
    router = _get_device_router()
    if router is not None:
        try:
            local_devices = getattr(router, "devices", {}) or {}
            if device_id in local_devices:
                summary.router_present = True
                summary.sources["device_router"] = {"present": True}
        except Exception as exc:
            logger.debug(
                "DeviceReadiness: device router query failed for %s — %s",
                device_id,
                exc,
            )
            summary.reasons.append(f"device_router_error:{exc}")

    # Derive a consolidated connection_state when UCM had no record.
    if summary.websocket_connected and summary.connection_state == "disconnected":
        summary.connection_state = "connected"

    return summary


# ---------------------------------------------------------------------------
# get_routability_summary
# ---------------------------------------------------------------------------


def get_routability_summary(device_id: str) -> RoutabilitySummary:
    """Aggregate routing / transport availability for *device_id*.

    Checks:
    - Direct WS via UCM / gateway WS manager.
    - UCM send availability.
    - Relay path (``core.proxy_relay`` presence).
    - Mesh direct / relay paths (``core.mesh_coordinator`` presence).
    """
    summary = RoutabilitySummary(device_id=device_id)

    # --- Direct WS ---
    ucm = _get_ucm()
    if ucm is not None:
        try:
            conn_info = ucm.get_connection(device_id)
            if conn_info is not None and getattr(conn_info, "routable", False):
                summary.direct_ws_available = True
                summary.ucm_send_available = True
                summary.sources["ucm_routable"] = True
        except Exception as exc:
            summary.reasons.append(f"ucm_routable_error:{exc}")
    else:
        summary.reasons.append("ucm_unavailable")

    # Enrich from gateway WS manager
    gw_ws = _get_gateway_ws_manager()
    if gw_ws is not None:
        try:
            connected_ids = set(gw_ws.get_connected_devices() or [])
            if device_id in connected_ids:
                summary.direct_ws_available = True
                summary.sources["gateway_ws_direct"] = True
        except Exception as exc:
            logger.debug(
                "DeviceReadiness: gateway WS routability query failed for %s — %s",
                device_id,
                exc,
            )

    # --- Relay availability ---
    try:
        import core.proxy_relay as _pr  # noqa: F401  # presence check only
        summary.relay_available = True
        summary.sources["proxy_relay"] = "module_present"
    except Exception:
        summary.reasons.append("relay_unavailable")

    # --- Mesh availability ---
    try:
        import core.mesh_coordinator as _mc  # noqa: F401  # presence check only
        summary.mesh_direct_available = True
        summary.mesh_relay_available = True
        summary.sources["mesh_coordinator"] = "module_present"
    except Exception:
        summary.reasons.append("mesh_unavailable")

    # --- Derive effective routable & preferred path ---
    if summary.direct_ws_available:
        summary.effective_routable = True
        summary.preferred_path = "direct_ws"
    elif summary.ucm_send_available:
        summary.effective_routable = True
        summary.preferred_path = "ucm"
    elif summary.relay_available:
        summary.effective_routable = True
        summary.preferred_path = "relay"
    elif summary.mesh_direct_available:
        summary.effective_routable = True
        summary.preferred_path = "mesh_direct"
    elif summary.mesh_relay_available:
        summary.effective_routable = True
        summary.preferred_path = "mesh_relay"
    else:
        summary.preferred_path = "none"

    return summary


# ---------------------------------------------------------------------------
# get_device_readiness
# ---------------------------------------------------------------------------


def get_device_readiness(device_id: str) -> DeviceReadinessSummary:
    """Return a full :class:`DeviceReadinessSummary` for *device_id*.

    Aggregates identity (UDM), connection, and routing state. Degrades
    gracefully: each subsystem failure is recorded in ``reasons`` without
    raising.
    """
    summary = DeviceReadinessSummary(device_id=device_id)
    summary.connection = ConnectionSummary(device_id=device_id)
    summary.routability = RoutabilitySummary(device_id=device_id)

    # --- Registered + online (UDM) ---
    udm = _get_udm()
    if udm is None:
        summary.reasons.append("udm_unavailable")
    else:
        try:
            device = udm.get_device(device_id)
            if device is None:
                summary.registered = False
                summary.reasons.append("device_not_registered")
            else:
                summary.registered = True
                summary.sources["udm"] = {
                    "device_type": getattr(device, "device_type", None),
                    "status": getattr(device, "status", None),
                }
                # online = ONLINE or BUSY
                raw_status = getattr(device, "status", "")
                status_str = raw_status if isinstance(raw_status, str) else str(raw_status)
                summary.online = status_str.lower() in ("online", "busy")

                # capability readiness — device has at least one capability declared
                caps = getattr(device, "capabilities", None) or []
                summary.capability_ready = len(caps) > 0
        except Exception as exc:
            logger.warning(
                "DeviceReadiness: UDM query failed",
                extra={
                    "event": "readiness_udm_query_failed",
                    "device_id": device_id,
                    "error": str(exc),
                },
            )
            summary.reasons.append(f"udm_query_error:{exc}")

    # Only continue with connection/routing checks if device is registered;
    # but still populate summaries defensively so callers get a full object.
    conn_summary = get_connection_summary(device_id)
    route_summary = get_routability_summary(device_id)
    summary.connection = conn_summary
    summary.routability = route_summary

    # Derive top-level connected / routable from sub-summaries
    summary.connected = conn_summary.websocket_connected or conn_summary.ucm_connected
    summary.routable = route_summary.effective_routable

    # Propagate sub-summary reasons
    summary.reasons.extend(conn_summary.reasons)
    summary.reasons.extend(route_summary.reasons)

    return summary


# ---------------------------------------------------------------------------
# Cross-device helpers
# ---------------------------------------------------------------------------


def get_cross_device_ready_devices() -> List[DeviceReadinessSummary]:
    """Return readiness summaries for all devices that pass cross-device criteria.

    A device is cross-device ready when:
    - ``registered`` is True
    - ``online`` is True
    - ``connected`` is True
    - ``routable`` is True

    If UDM is unavailable this returns an empty list and logs a warning.
    """
    udm = _get_udm()
    if udm is None:
        logger.warning(
            "DeviceReadiness: UDM unavailable — cannot list cross-device ready devices",
            extra={"event": "readiness_cross_device_list_failed"},
        )
        return []

    try:
        all_devices = udm.list_devices()
    except Exception as exc:
        logger.warning(
            "DeviceReadiness: list_devices failed",
            extra={"event": "readiness_list_devices_failed", "error": str(exc)},
        )
        return []

    ready: List[DeviceReadinessSummary] = []
    for device in all_devices:
        device_id = device.device_id
        try:
            rs = get_device_readiness(device_id)
            if rs.registered and rs.online and rs.connected and rs.routable:
                ready.append(rs)
        except Exception as exc:
            logger.warning(
                "DeviceReadiness: readiness evaluation failed for %s — %s",
                device_id,
                exc,
                extra={
                    "event": "readiness_per_device_eval_failed",
                    "device_id": device_id,
                    "error": str(exc),
                },
            )

    return ready


def is_device_cross_device_ready(device_id: str) -> bool:
    """Return True if *device_id* satisfies all cross-device readiness criteria.

    Equivalent to checking ``get_device_readiness(device_id)`` and testing
    ``registered and online and connected and routable``.
    """
    try:
        rs = get_device_readiness(device_id)
        return rs.registered and rs.online and rs.connected and rs.routable
    except Exception as exc:
        logger.warning(
            "DeviceReadiness: is_device_cross_device_ready check failed for %s — %s",
            device_id,
            exc,
            extra={
                "event": "readiness_is_ready_failed",
                "device_id": device_id,
                "error": str(exc),
            },
        )
        return False
