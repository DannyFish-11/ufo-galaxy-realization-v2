#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/agent_bus_fabric.py
=========================
PR-4 — Agent Bus & Fabric Convergence.

Establishes the canonical three-layer architecture for Galaxy's communication
fabric and provides the authority sentinels, strategy selection helpers, and
observability primitives that let all components speak a consistent language.

Layering model
--------------
::

    ┌────────────────────────────────────────────────────────────────┐
    │  AGENT BUS (Semantic Layer)                                    │
    │  TaskEnvelope / ResultEnvelope — canonical message contract    │
    │  Determines *what* is communicated and *how it is correlated*  │
    └───────────────────────────┬────────────────────────────────────┘
                                │  carried by
    ┌───────────────────────────▼────────────────────────────────────┐
    │  NATS (Distributed Carrier / Fabric)                           │
    │  JetStream streams — galaxy.task.*, galaxy.device.*, …        │
    │  Determines *how messages traverse the cluster*                │
    └─────────────────┬──────────────────┬──────────────────────────┘
                      │                  │
    ┌─────────────────▼──┐  ┌────────────▼────────────────────────┐
    │  Gateway / WS       │  │  Direct / Relay / Mesh substrate    │
    │  (Device-facing     │  │  (node-to-node or assisted paths)  │
    │   transport)        │  │                                     │
    └─────────────────────┘  └─────────────────────────────────────┘

Invariants
----------
1.  Agent Bus = semantic layer only.  It defines *what* a message means
    (task, result, correlation) but is not tied to any transport mechanism.
2.  NATS = carrier/fabric only.  It provides durability, fan-out, and
    cross-cluster delivery but does NOT define message semantics.
3.  Gateway/WebSocket = device-facing transport only.  It accepts and delivers
    messages to physical/virtual devices but does NOT own task semantics.
4.  ``CommandRouter`` selects which carrier/substrate to use based on
    ``FabricTransportStrategy`` rules; it MUST record the chosen path for
    observability.
5.  Every message crossing any substrate boundary MUST be expressible as a
    ``TaskEnvelope`` or ``ResultEnvelope`` (the canonical Agent Bus contract).
    Legacy shapes are translated through the interop layer; they are never
    the wire contract inside the canonical path.

Public API
----------
Authority sentinels:
    AGENT_BUS_FABRIC_AUTHORITY
    AGENT_BUS_LAYER
    NATS_CARRIER_LAYER
    GATEWAY_SUBSTRATE_LAYER
    COMMAND_ROUTER_STRATEGY_LAYER
    CANONICAL_CONTRACT_POLICY

Strategy constants:
    TRANSPORT_STRATEGY_DIRECT
    TRANSPORT_STRATEGY_GATEWAY
    TRANSPORT_STRATEGY_NATS
    TRANSPORT_STRATEGY_RELAY
    TRANSPORT_STRATEGY_MESH
    TRANSPORT_STRATEGY_UNKNOWN

Observability reason constants:
    FABRIC_REASON_NATS_UNAVAILABLE
    FABRIC_REASON_GATEWAY_UNAVAILABLE
    FABRIC_REASON_STRATEGY_FALLBACK
    FABRIC_REASON_SEMANTIC_FAILURE
    FABRIC_REASON_DEVICE_TRANSPORT_FAILURE
    FABRIC_REASON_FABRIC_FAILURE

Dataclasses:
    FabricTransportStrategyRecord
    FabricObservabilityRecord

Helpers:
    select_transport_strategy(...)  -> FabricTransportStrategyRecord
    record_fabric_event(...)        -> FabricObservabilityRecord
    wrap_for_nats(payload)          -> dict
    wrap_for_gateway(payload)       -> dict
    is_canonical_contract(payload)  -> bool
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("Galaxy.AgentBusFabric")

__all__ = [
    # Authority sentinels
    "AGENT_BUS_FABRIC_AUTHORITY",
    "AGENT_BUS_LAYER",
    "NATS_CARRIER_LAYER",
    "GATEWAY_SUBSTRATE_LAYER",
    "COMMAND_ROUTER_STRATEGY_LAYER",
    "CANONICAL_CONTRACT_POLICY",
    # Strategy constants
    "TRANSPORT_STRATEGY_DIRECT",
    "TRANSPORT_STRATEGY_GATEWAY",
    "TRANSPORT_STRATEGY_NATS",
    "TRANSPORT_STRATEGY_RELAY",
    "TRANSPORT_STRATEGY_MESH",
    "TRANSPORT_STRATEGY_UNKNOWN",
    # Observability reasons
    "FABRIC_REASON_NATS_UNAVAILABLE",
    "FABRIC_REASON_GATEWAY_UNAVAILABLE",
    "FABRIC_REASON_STRATEGY_FALLBACK",
    "FABRIC_REASON_SEMANTIC_FAILURE",
    "FABRIC_REASON_DEVICE_TRANSPORT_FAILURE",
    "FABRIC_REASON_FABRIC_FAILURE",
    # Dataclasses
    "FabricTransportStrategyRecord",
    "FabricObservabilityRecord",
    # Helpers
    "select_transport_strategy",
    "record_fabric_event",
    "wrap_for_nats",
    "wrap_for_gateway",
    "is_canonical_contract",
    # Ring buffer
    "get_fabric_event_log",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the canonical Agent Bus & Fabric authority (PR-4).
AGENT_BUS_FABRIC_AUTHORITY: str = "AGENT_BUS_FABRIC::CANONICAL_V1"

#: Semantic communication layer — TaskEnvelope / ResultEnvelope define *what*
#: a message means.  Layer identity is transport-independent.
AGENT_BUS_LAYER: str = "AGENT_BUS::SEMANTIC_LAYER"

#: NATS JetStream is the distributed carrier/fabric.  It carries canonical
#: contracts across cluster boundaries but does NOT define message semantics.
NATS_CARRIER_LAYER: str = "NATS::CARRIER_FABRIC_LAYER"

#: Galaxy Gateway / WebSocket is the device-facing transport substrate.
#: It accepts and delivers messages to physical/virtual devices but does NOT
#: own task semantics or act as an orchestration authority.
GATEWAY_SUBSTRATE_LAYER: str = "GATEWAY::DEVICE_TRANSPORT_SUBSTRATE"

#: CommandRouter is the strategy selection layer — it decides *which*
#: carrier/substrate to use for each dispatch, records the decision, and
#: enforces the canonical envelope contract on every path.
COMMAND_ROUTER_STRATEGY_LAYER: str = "COMMAND_ROUTER::TRANSPORT_STRATEGY_LAYER"

#: Policy: every message crossing any substrate boundary MUST carry a
#: TaskEnvelope or ResultEnvelope as its canonical contract.  Legacy shapes
#: are translated by the interop layer before entering canonical paths.
CANONICAL_CONTRACT_POLICY: str = (
    "REQUIRED: all cross-substrate messages must carry TaskEnvelope/ResultEnvelope "
    "as the canonical Agent Bus contract.  Legacy shapes must be translated via "
    "core.message_interop before entering canonical dispatch paths."
)

# ---------------------------------------------------------------------------
# Transport strategy constants
# ---------------------------------------------------------------------------

#: Local direct delivery — target is reachable on the same host/process.
TRANSPORT_STRATEGY_DIRECT: str = "direct"

#: Gateway-mediated delivery — target is reachable via the Galaxy Gateway
#: WebSocket transport substrate.
TRANSPORT_STRATEGY_GATEWAY: str = "gateway"

#: NATS fabric delivery — target is reachable via the NATS JetStream carrier.
TRANSPORT_STRATEGY_NATS: str = "nats"

#: Relay-assisted delivery — delivery is mediated by a ProxyRelay node because
#: the direct path and NATS are unavailable or not preferred.
TRANSPORT_STRATEGY_RELAY: str = "relay"

#: Mesh-overlay delivery — peer-exchange / mesh-assisted path.  This is an
#: overlay / enrichment path only; it must NOT be treated as a primary or
#: orchestration-authoritative transport.
TRANSPORT_STRATEGY_MESH: str = "mesh"

#: Strategy could not be determined (error or misconfiguration).
TRANSPORT_STRATEGY_UNKNOWN: str = "unknown"

# Priority order for automatic strategy selection (highest preference first).
_STRATEGY_PRIORITY: tuple[str, ...] = (
    TRANSPORT_STRATEGY_DIRECT,
    TRANSPORT_STRATEGY_GATEWAY,
    TRANSPORT_STRATEGY_NATS,
    TRANSPORT_STRATEGY_RELAY,
    TRANSPORT_STRATEGY_MESH,
)

# ---------------------------------------------------------------------------
# Observability reason constants
# ---------------------------------------------------------------------------

#: NATS fabric is unavailable; strategy falls back to another carrier.
FABRIC_REASON_NATS_UNAVAILABLE: str = "fabric_reason::nats_unavailable"

#: Gateway transport substrate is unavailable; strategy falls back.
FABRIC_REASON_GATEWAY_UNAVAILABLE: str = "fabric_reason::gateway_unavailable"

#: Strategy fallback was triggered by a lower-priority path being selected.
FABRIC_REASON_STRATEGY_FALLBACK: str = "fabric_reason::strategy_fallback"

#: Failure originated in the semantic layer (bad envelope, invalid contract).
FABRIC_REASON_SEMANTIC_FAILURE: str = "fabric_reason::semantic_failure"

#: Failure originated in the device transport layer (WebSocket/Gateway).
FABRIC_REASON_DEVICE_TRANSPORT_FAILURE: str = "fabric_reason::device_transport_failure"

#: Failure originated in the fabric/carrier layer (NATS, relay, mesh).
FABRIC_REASON_FABRIC_FAILURE: str = "fabric_reason::fabric_failure"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FabricTransportStrategyRecord:
    """Result of a transport strategy selection decision.

    Fields
    ------
    strategy : str
        The chosen transport strategy constant (e.g. ``TRANSPORT_STRATEGY_NATS``).
    fallback_used : bool
        True when the preferred strategy was unavailable and a lower-priority
        strategy was selected instead.
    preferred_strategy : str
        The originally preferred strategy before fallback (equals *strategy*
        when no fallback occurred).
    reason : str
        Human-readable / machine-readable reason for the selection or fallback.
    task_id : str
        The ``task_id`` of the envelope being dispatched, for correlation.
    trace_id : str
        The ``trace_id`` of the envelope being dispatched, for correlation.
    selected_at : float
        Unix timestamp (seconds) when the strategy was selected.
    layer : str
        Always ``COMMAND_ROUTER_STRATEGY_LAYER`` — identifies where the
        selection decision was made.
    """

    strategy: str = TRANSPORT_STRATEGY_UNKNOWN
    fallback_used: bool = False
    preferred_strategy: str = TRANSPORT_STRATEGY_UNKNOWN
    reason: str = ""
    task_id: str = ""
    trace_id: str = ""
    selected_at: float = field(default_factory=time.time)
    layer: str = COMMAND_ROUTER_STRATEGY_LAYER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "fallback_used": self.fallback_used,
            "preferred_strategy": self.preferred_strategy,
            "reason": self.reason,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "selected_at": self.selected_at,
            "layer": self.layer,
        }


@dataclass
class FabricObservabilityRecord:
    """A single fabric event recorded in the ring-buffer log.

    Distinguishes semantic failures (Agent Bus contract errors) from fabric
    failures (NATS/relay/mesh) from device-transport failures (Gateway/WS).

    Fields
    ------
    event_id : str
        Unique event identifier.
    task_id : str
        Correlated task identifier.
    trace_id : str
        Correlated trace identifier.
    strategy : str
        Transport strategy in use at the time of the event.
    layer : str
        Layer where the event occurred (AGENT_BUS_LAYER / NATS_CARRIER_LAYER /
        GATEWAY_SUBSTRATE_LAYER).
    reason : str
        Machine-readable reason constant (FABRIC_REASON_*).
    detail : str
        Human-readable detail string for debugging.
    success : bool
        Whether the event represents a successful operation.
    fallback_triggered : bool
        True when this event caused a strategy fallback.
    recorded_at : float
        Unix timestamp.
    """

    event_id: str = field(default_factory=lambda: f"fev_{uuid.uuid4().hex[:12]}")
    task_id: str = ""
    trace_id: str = ""
    strategy: str = TRANSPORT_STRATEGY_UNKNOWN
    layer: str = ""
    reason: str = ""
    detail: str = ""
    success: bool = True
    fallback_triggered: bool = False
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "strategy": self.strategy,
            "layer": self.layer,
            "reason": self.reason,
            "detail": self.detail,
            "success": self.success,
            "fallback_triggered": self.fallback_triggered,
            "recorded_at": self.recorded_at,
        }


# ---------------------------------------------------------------------------
# Ring-buffer observability log
# ---------------------------------------------------------------------------

_FABRIC_EVENT_LOG: Deque[FabricObservabilityRecord] = deque(maxlen=256)


def get_fabric_event_log() -> Deque[FabricObservabilityRecord]:
    """Return the module-level fabric observability ring buffer (maxlen=256)."""
    return _FABRIC_EVENT_LOG


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def select_transport_strategy(
    *,
    task_id: str = "",
    trace_id: str = "",
    nats_available: bool = False,
    gateway_available: bool = False,
    relay_available: bool = False,
    mesh_available: bool = False,
    direct_available: bool = False,
    preferred: Optional[str] = None,
) -> FabricTransportStrategyRecord:
    """Select the best available transport strategy for a dispatch.

    Selection rules (in priority order)
    ------------------------------------
    1. ``direct``   — same-host/process delivery, highest preference.
    2. ``gateway``  — Galaxy Gateway WebSocket substrate.
    3. ``nats``     — NATS JetStream distributed carrier.
    4. ``relay``    — ProxyRelay mediated fallback.
    5. ``mesh``     — Mesh overlay (enrichment only, lowest preference).

    When a *preferred* strategy is requested and available, it is used
    immediately.  When it is unavailable the selector falls back to the next
    available strategy in priority order, and ``fallback_used`` is set True.

    Parameters
    ----------
    task_id, trace_id : str
        Correlation identifiers propagated from the ``TaskEnvelope``.
    nats_available : bool
        True when the NATS fabric is connected and ready.
    gateway_available : bool
        True when the Galaxy Gateway WebSocket transport is reachable.
    relay_available : bool
        True when a ProxyRelay fallback path exists.
    mesh_available : bool
        True when a mesh overlay path exists.
    direct_available : bool
        True when the target is reachable on the local host/process.
    preferred : str | None
        Caller hint for the preferred strategy.  Honoured when that strategy
        is also available; otherwise falls back.

    Returns
    -------
    FabricTransportStrategyRecord
    """
    availability: Dict[str, bool] = {
        TRANSPORT_STRATEGY_DIRECT: direct_available,
        TRANSPORT_STRATEGY_GATEWAY: gateway_available,
        TRANSPORT_STRATEGY_NATS: nats_available,
        TRANSPORT_STRATEGY_RELAY: relay_available,
        TRANSPORT_STRATEGY_MESH: mesh_available,
    }

    preferred_strategy = preferred or TRANSPORT_STRATEGY_UNKNOWN

    # Try the preferred strategy first (if caller expressed a preference).
    if preferred and availability.get(preferred):
        return FabricTransportStrategyRecord(
            strategy=preferred,
            fallback_used=False,
            preferred_strategy=preferred,
            reason=f"preferred_strategy_available:{preferred}",
            task_id=task_id,
            trace_id=trace_id,
        )

    # Walk the priority list to find the first available strategy.
    for strategy in _STRATEGY_PRIORITY:
        if availability.get(strategy):
            fallback = strategy != preferred_strategy
            reason = (
                f"fallback_selected:{strategy}:preferred_unavailable:{preferred_strategy}"
                if fallback and preferred
                else f"strategy_selected:{strategy}"
            )
            return FabricTransportStrategyRecord(
                strategy=strategy,
                fallback_used=fallback and bool(preferred),
                preferred_strategy=preferred_strategy,
                reason=reason,
                task_id=task_id,
                trace_id=trace_id,
            )

    # No strategy available.
    return FabricTransportStrategyRecord(
        strategy=TRANSPORT_STRATEGY_UNKNOWN,
        fallback_used=False,
        preferred_strategy=preferred_strategy,
        reason="no_transport_available",
        task_id=task_id,
        trace_id=trace_id,
    )


def record_fabric_event(
    *,
    task_id: str = "",
    trace_id: str = "",
    strategy: str = TRANSPORT_STRATEGY_UNKNOWN,
    layer: str = "",
    reason: str = "",
    detail: str = "",
    success: bool = True,
    fallback_triggered: bool = False,
) -> FabricObservabilityRecord:
    """Create and append a :class:`FabricObservabilityRecord` to the ring buffer.

    This function is the single entry-point for recording transport/fabric
    events in the observability log.  Callers in ``CommandRouter``, the NATS
    executor, and the gateway adapter should call this when:

    - A transport strategy is selected (including fallbacks).
    - A fabric or device-transport failure occurs.
    - A semantic contract error is detected.

    The *layer* argument should be one of the canonical layer constants
    (``AGENT_BUS_LAYER``, ``NATS_CARRIER_LAYER``, ``GATEWAY_SUBSTRATE_LAYER``)
    so that downstream observability consumers can distinguish failure domains.

    Parameters
    ----------
    task_id, trace_id : str
        Correlation identifiers from the ``TaskEnvelope``.
    strategy : str
        The transport strategy that was in use.
    layer : str
        The layer where the event occurred.
    reason : str
        A ``FABRIC_REASON_*`` constant or other machine-readable reason string.
    detail : str
        Human-readable description for debugging.
    success : bool
        Whether this event represents a successful operation.
    fallback_triggered : bool
        True when this event caused or was caused by a strategy fallback.

    Returns
    -------
    FabricObservabilityRecord
        The newly created record (also appended to the ring buffer).
    """
    rec = FabricObservabilityRecord(
        task_id=task_id,
        trace_id=trace_id,
        strategy=strategy,
        layer=layer,
        reason=reason,
        detail=detail,
        success=success,
        fallback_triggered=fallback_triggered,
    )
    _FABRIC_EVENT_LOG.append(rec)
    if not success:
        logger.warning(
            "FabricEvent task=%s trace=%s strategy=%s layer=%s reason=%s detail=%s",
            task_id or "-",
            trace_id or "-",
            strategy,
            layer,
            reason,
            detail,
        )
    else:
        logger.debug(
            "FabricEvent task=%s trace=%s strategy=%s layer=%s reason=%s",
            task_id or "-",
            trace_id or "-",
            strategy,
            layer,
            reason,
        )
    return rec


def wrap_for_nats(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Annotate *payload* as a canonical NATS carrier message.

    Adds the ``_fabric_layer`` and ``_nats_schema`` discriminator keys so
    that NATS consumers can verify that the message originated from the
    canonical Agent Bus path and carries a ``TaskEnvelope``-compatible shape.

    If ``_nats_schema`` is already present it is not overwritten (the caller
    already stamped the correct schema name).

    Parameters
    ----------
    payload : dict
        The message dict to annotate (mutated in place and returned).

    Returns
    -------
    dict
        The annotated payload.
    """
    payload["_fabric_layer"] = NATS_CARRIER_LAYER
    if "_nats_schema" not in payload:
        payload["_nats_schema"] = "TaskEnvelope"
    return payload


def wrap_for_gateway(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Annotate *payload* as a canonical Gateway substrate message.

    Adds the ``_fabric_layer`` discriminator key so that gateway/WebSocket
    handlers can verify the message entered through the canonical Agent Bus
    path.

    Parameters
    ----------
    payload : dict
        The message dict to annotate (mutated in place and returned).

    Returns
    -------
    dict
        The annotated payload.
    """
    payload["_fabric_layer"] = GATEWAY_SUBSTRATE_LAYER
    return payload


def is_canonical_contract(payload: Any) -> bool:
    """Return True when *payload* satisfies the minimal canonical contract.

    A payload satisfies the canonical contract when it is either a
    ``TaskEnvelope`` / ``ResultEnvelope`` instance **or** a dict that carries
    both ``task_id`` and ``trace_id`` fields (the minimum correlation fields
    required by ``CANONICAL_CONTRACT_POLICY``).

    This is a lightweight check; full validation is the responsibility of the
    consuming handler.

    Parameters
    ----------
    payload : Any
        The message to check.

    Returns
    -------
    bool
    """
    # Accept Pydantic model instances with the required fields.
    if hasattr(payload, "task_id") and hasattr(payload, "trace_id"):
        return bool(getattr(payload, "task_id", None) and getattr(payload, "trace_id", None))

    # Accept dict-shaped messages.
    if isinstance(payload, dict):
        return "task_id" in payload and "trace_id" in payload

    return False
