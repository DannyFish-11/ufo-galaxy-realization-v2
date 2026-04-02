#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_network_bridge.py
====================================
PR-D: Capability + Network Runtime Convergence — Capability ↔ Network Bridge.

Establishes the **joint selection layer** that bridges the capability graph
(who can do what) with the network runtime (how to reach them / which path
is available).  This enables the planner/router/policy to simultaneously
explain:

  * Why this provider/executor was selected (capability fit)
  * Why this network/transport path was chosen (topology state)
  * How fallback works when either side degrades

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  CAPABILITY ↔ NETWORK BRIDGE  (this module, Layer 11)               │
    │                                                                      │
    │  Consumes:                                                           │
    │    • CapabilityGraphSelection  (capability fit, provider candidates) │
    │    • NetworkTopologyRuntime    (path availability, transport state)  │
    │    • NetworkGraphRuntime       (fabric node / edge registry)         │
    │                                                                      │
    │  Exposes:                                                            │
    │    • joint_select(task_caps, target_id) → JointSelectionResult       │
    │    • explain_joint_selection(result)    → JointSelectionExplanation  │
    │    • fallback_joint_select(…)           → JointSelectionResult       │
    │    • get_bridge_log()                   → Deque[BridgeRecord]        │
    └──────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Bridge is read-only from both capability and network layers.**
    This module MUST NOT mutate any capability assimilation record or any
    topology node/edge state.
2.  **Planner/router/policy MUST use this bridge for joint decisions.**
    Direct cross-layer reads (reading topology from capability side or reading
    capabilities from topology side) are prohibited.
3.  **Every joint selection is observable.**
    All bridge calls are recorded in a 256-entry ring buffer with enough
    detail to reconstruct the decision.

Public API
----------
Authority sentinels:
    CAPABILITY_NETWORK_BRIDGE_AUTHORITY
    CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION
    DUAL_GRAPH_SELECTION_POLICY

Dataclasses:
    PathAvailability
    JointSelectionResult
    JointSelectionExplanation
    BridgeRecord

Functions:
    joint_select(required_capabilities, target_id, *, kind_filter)
        -> JointSelectionResult
    explain_joint_selection(result)
        -> JointSelectionExplanation
    fallback_joint_select(required_capabilities, *, exclude_ids, kind_filter)
        -> JointSelectionResult
    get_bridge_log()
        -> Deque[BridgeRecord]
    reset_bridge_log()
        -> None  # for testing
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.CapabilityNetworkBridge")

__all__ = [
    # Authority sentinels
    "CAPABILITY_NETWORK_BRIDGE_AUTHORITY",
    "CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION",
    "DUAL_GRAPH_SELECTION_POLICY",
    # Dataclasses
    "PathAvailability",
    "JointSelectionResult",
    "JointSelectionExplanation",
    "BridgeRecord",
    # Functions
    "joint_select",
    "explain_joint_selection",
    "fallback_joint_select",
    "get_bridge_log",
    "reset_bridge_log",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CAPABILITY_NETWORK_BRIDGE_AUTHORITY: str = (
    "core.capability_network_bridge"
    " — canonical capability ↔ network bridge (PR-D)"
)
"""Sentinel: this module is the canonical dual-graph selection bridge.

Import this sentinel to assert that a call site performs joint capability +
network routing decisions through the bridge layer rather than reading either
graph directly.
"""

CAPABILITY_NETWORK_BRIDGE_LAYER_POSITION: int = 11
"""Layer position in the canonical control-plane stack.

Layer 11 sits above the capability selection plane (Layer 10) and the network
topology runtime (Layer 8), and is consumed by planner / command router at
layer 12+.
"""

DUAL_GRAPH_SELECTION_POLICY: str = (
    "DUAL_GRAPH_SELECTION_V1: planner/router/policy MUST perform joint "
    "capability + network routing decisions via "
    "core.capability_network_bridge.joint_select(). "
    "Direct cross-layer reads between capability and network graphs are "
    "prohibited."
)
"""Policy sentinel: governs dual-graph access.

All routing decisions that require both capability fit AND network path
availability MUST go through this bridge.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256

# Transport path preference ordering (higher = preferred).
_PATH_PRIORITY: Dict[str, int] = {
    "direct": 10,
    "direct_ws": 10,
    "gateway": 7,
    "nats": 6,
    "relay": 4,
    "mesh": 3,
    "unknown": 1,
    "unavailable": 0,
}

# Connection state weights
_STATE_WEIGHT: Dict[str, float] = {
    "preferred": 1.0,
    "reachable": 0.9,
    "connected": 0.9,
    "degraded": 0.5,
    "fallback": 0.4,
    "latent": 0.2,
    "unavailable": 0.0,
    "unknown": 0.3,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PathAvailability:
    """Network path availability for a specific provider/target node.

    Attributes:
        node_id:           Node identifier.
        effective_path:    Best available path kind (``"direct"``, ``"gateway"``,
                           ``"relay"``, ``"mesh"``, ``"nats"``, ``"unknown"``).
        path_state:        Connection state string from the topology runtime.
        path_score:        Numeric availability score (0.0–1.0).
        fallback_path:     Next-best path kind if primary is unavailable.
        is_reachable:      Whether any path exists at all.
        transport_hints:   Raw transport hints from the assimilation record.
        topology_notes:    Diagnostic notes from topology lookups.
    """

    node_id: str
    effective_path: str = "unknown"
    path_state: str = "unknown"
    path_score: float = 0.0
    fallback_path: Optional[str] = None
    is_reachable: bool = False
    transport_hints: Dict[str, Any] = field(default_factory=dict)
    topology_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "effective_path": self.effective_path,
            "path_state": self.path_state,
            "path_score": self.path_score,
            "fallback_path": self.fallback_path,
            "is_reachable": self.is_reachable,
            "transport_hints": dict(self.transport_hints),
            "topology_notes": list(self.topology_notes),
        }


@dataclass
class JointSelectionResult:
    """Result of a joint capability + network selection decision.

    Attributes:
        selected_provider_id:  Selected capability provider node ID.
        capability_fit_score:  Capability fit score (from CapabilityGraphSelection).
        path_availability:     Network path availability for the selected provider.
        joint_score:           Composite score combining capability fit and path quality.
        fallback_provider_id:  Fallback provider ID (or *None* if not needed/available).
        fallback_path:         Fallback path kind.
        required_capabilities: Capabilities that were searched for.
        selection_timestamp:   Monotonic timestamp.
        is_degraded:           True if either capability or network side is degraded.
        degraded_reason:       Human-readable degradation explanation.
    """

    selected_provider_id: Optional[str]
    capability_fit_score: Optional[Any]  # CapabilityFitScore
    path_availability: PathAvailability
    joint_score: float
    fallback_provider_id: Optional[str] = None
    fallback_path: Optional[str] = None
    required_capabilities: List[str] = field(default_factory=list)
    selection_timestamp: float = field(default_factory=time.monotonic)
    is_degraded: bool = False
    degraded_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_provider_id": self.selected_provider_id,
            "capability_fit_score": self.capability_fit_score.to_dict()
            if self.capability_fit_score
            else None,
            "path_availability": self.path_availability.to_dict(),
            "joint_score": self.joint_score,
            "fallback_provider_id": self.fallback_provider_id,
            "fallback_path": self.fallback_path,
            "required_capabilities": list(self.required_capabilities),
            "selection_timestamp": self.selection_timestamp,
            "is_degraded": self.is_degraded,
            "degraded_reason": self.degraded_reason,
        }


@dataclass
class JointSelectionExplanation:
    """Full human-readable explanation of a joint selection decision.

    Attributes:
        provider_reason:     Why this provider/executor was selected.
        path_reason:         Why this network/transport path was chosen.
        fallback_reason:     How fallback works if either side degrades.
        degraded_explanation: Explanation when operating in degraded mode.
        joint_result:        The raw :class:`JointSelectionResult`.
    """

    provider_reason: str
    path_reason: str
    fallback_reason: str
    degraded_explanation: str
    joint_result: JointSelectionResult

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_reason": self.provider_reason,
            "path_reason": self.path_reason,
            "fallback_reason": self.fallback_reason,
            "degraded_explanation": self.degraded_explanation,
            "joint_result": self.joint_result.to_dict(),
        }


@dataclass
class BridgeRecord:
    """Observability record for one bridge operation (ring-buffer entry).

    Attributes:
        record_id:            Monotonically increasing record ID.
        operation:            ``"joint_select"`` | ``"fallback_select"`` | ``"explain"``.
        required_capabilities: Capabilities searched.
        selected_provider_id:  Provider selected (or ``None``).
        effective_path:        Path chosen (or ``"unknown"``).
        joint_score:           Composite joint score.
        is_degraded:           Whether degraded mode was triggered.
        timestamp:             Monotonic timestamp.
        notes:                 Diagnostic notes.
    """

    record_id: int
    operation: str
    required_capabilities: List[str]
    selected_provider_id: Optional[str]
    effective_path: str
    joint_score: float
    is_degraded: bool
    timestamp: float = field(default_factory=time.monotonic)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "operation": self.operation,
            "required_capabilities": list(self.required_capabilities),
            "selected_provider_id": self.selected_provider_id,
            "effective_path": self.effective_path,
            "joint_score": self.joint_score,
            "is_degraded": self.is_degraded,
            "timestamp": self.timestamp,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Module-level ring buffer
# ---------------------------------------------------------------------------

_bridge_log: Deque[BridgeRecord] = deque(maxlen=_RING_BUFFER_SIZE)
_record_counter: int = 0


def _next_record_id() -> int:
    global _record_counter
    _record_counter += 1
    return _record_counter


def _emit_bridge_record(
    operation: str,
    required_caps: List[str],
    result: JointSelectionResult,
    notes: Optional[List[str]] = None,
) -> None:
    rec = BridgeRecord(
        record_id=_next_record_id(),
        operation=operation,
        required_capabilities=list(required_caps),
        selected_provider_id=result.selected_provider_id,
        effective_path=result.path_availability.effective_path,
        joint_score=result.joint_score,
        is_degraded=result.is_degraded,
        notes=list(notes or []),
    )
    _bridge_log.append(rec)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _probe_path_availability(node_id: str, transport_hints: Dict[str, Any]) -> PathAvailability:
    """Query the NetworkTopologyRuntime for path availability for *node_id*.

    Falls back gracefully if the topology runtime is unavailable or has no
    record for the node (using transport_hints as supplementary information).

    Args:
        node_id:         Node to probe.
        transport_hints: Transport hints from the assimilation record.

    Returns:
        A :class:`PathAvailability` describing the best available path.
    """
    notes: List[str] = []

    # Try NetworkTopologyRuntime first (authoritative)
    try:
        from core.network_topology_runtime import (
            get_network_topology_runtime,
            TopologyConnectionState,
        )

        topo = get_network_topology_runtime()
        topo_node = topo.get_node(node_id)

        if topo_node is not None:
            state_val = topo_node.state
            state_str = state_val.value if hasattr(state_val, "value") else str(state_val)

            # Determine effective path from edges
            edges = topo.edges_from(node_id) or topo.edges_to(node_id)
            path_kind = "unknown"
            fallback_kind: Optional[str] = None
            if edges:
                # Sort edges by connection state preference
                def _edge_score(e: Any) -> int:
                    es = e.state
                    es_str = es.value if hasattr(es, "value") else str(es)
                    kind_val = e.kind
                    kind_str = kind_val.value if hasattr(kind_val, "value") else str(kind_val)
                    return _PATH_PRIORITY.get(kind_str, 0) + (
                        5 if es_str in ("preferred", "reachable", "connected") else 0
                    )

                sorted_edges = sorted(edges, key=_edge_score, reverse=True)
                pk = sorted_edges[0].kind
                path_kind = pk.value if hasattr(pk, "value") else str(pk)
                if len(sorted_edges) > 1:
                    fk = sorted_edges[1].kind
                    fallback_kind = fk.value if hasattr(fk, "value") else str(fk)

            path_score = _STATE_WEIGHT.get(state_str, 0.3)
            is_reachable = state_str not in ("unavailable",)

            return PathAvailability(
                node_id=node_id,
                effective_path=path_kind,
                path_state=state_str,
                path_score=path_score,
                fallback_path=fallback_kind,
                is_reachable=is_reachable,
                transport_hints=dict(transport_hints),
                topology_notes=notes,
            )
    except Exception as exc:
        notes.append(f"topology_runtime_unavailable: {exc}")
        logger.debug("capability_network_bridge: topology runtime unavailable for %s — %s", node_id, exc)

    # Fall back to NetworkGraphRuntime
    try:
        from core.network_graph_runtime import get_network_graph_runtime

        ng = get_network_graph_runtime()
        ng_node = ng.snapshot().nodes.get(node_id)
        if ng_node:
            # Use transport hints to infer path
            preferred = transport_hints.get("preferred_path", "unknown")
            path_kind = preferred if preferred != "unknown" else "direct"
            return PathAvailability(
                node_id=node_id,
                effective_path=path_kind,
                path_state="reachable",
                path_score=0.7,
                fallback_path=None,
                is_reachable=True,
                transport_hints=dict(transport_hints),
                topology_notes=notes + ["source=network_graph_runtime"],
            )
    except Exception as exc2:
        notes.append(f"network_graph_runtime_unavailable: {exc2}")

    # Last resort: derive from transport_hints only
    preferred = transport_hints.get("preferred_path", "unknown")
    path_score = _PATH_PRIORITY.get(preferred, 1) / 10.0
    return PathAvailability(
        node_id=node_id,
        effective_path=preferred,
        path_state="unknown",
        path_score=path_score,
        fallback_path=transport_hints.get("fallback_path"),
        is_reachable=preferred not in ("unavailable", ""),
        transport_hints=dict(transport_hints),
        topology_notes=notes + ["source=transport_hints_only"],
    )


def _compute_joint_score(
    capability_score: float,
    path_score: float,
    is_degraded: bool,
) -> float:
    """Compute a composite joint score from capability and path scores.

    The formula weights capability coverage slightly higher than path quality
    since a highly capable provider on a degraded path is still preferred over
    a poorly capable one on a perfect path.

    Returns a value in [0.0, 20.0].
    """
    base = (capability_score * 0.6) + (path_score * 10.0 * 0.4)
    return base * (0.8 if is_degraded else 1.0)


# ---------------------------------------------------------------------------
# Public bridge functions
# ---------------------------------------------------------------------------


def joint_select(
    required_capabilities: Optional[List[str]] = None,
    target_id: Optional[str] = None,
    *,
    kind_filter: Optional[List[str]] = None,
) -> JointSelectionResult:
    """Perform a joint capability + network selection.

    Selects the best available provider that:
    1. Matches the required capabilities (capability graph)
    2. Is reachable via the best available network path (network runtime)

    If *target_id* is specified, the function scores only that provider but
    still enriches the result with capability fit and network path info —
    useful when the caller has already pre-selected a target and wants
    observability data.

    Args:
        required_capabilities: List of capability names needed.
        target_id:             Optional pre-selected target provider node ID.
        kind_filter:           Optional participant kind restriction.

    Returns:
        A :class:`JointSelectionResult` with the best provider and path.
    """
    from core.capability_graph_selection import (  # lazy import
        discover_providers,
        score_provider,
        select_best_provider,
    )

    required: List[str] = list(required_capabilities or [])
    notes: List[str] = []

    # Step 1: Capability candidate discovery
    if target_id:
        try:
            from core.capability_assimilation import get_capability_assimilation_layer
            layer = get_capability_assimilation_layer()
            record = layer.get_record(target_id)
            candidates = [record] if record else []
        except Exception as exc:
            candidates = []
            notes.append(f"assimilation_lookup_failed: {exc}")
    else:
        candidates = discover_providers(
            capabilities=required,
            kind_filter=kind_filter,
            require_online=True,
        )

    if not candidates:
        # No capability providers available → return empty result
        empty_path = PathAvailability(
            node_id=target_id or "__none__",
            effective_path="unavailable",
            path_state="unavailable",
            path_score=0.0,
            is_reachable=False,
        )
        result = JointSelectionResult(
            selected_provider_id=None,
            capability_fit_score=None,
            path_availability=empty_path,
            joint_score=0.0,
            required_capabilities=required,
            is_degraded=True,
            degraded_reason="no_capability_providers_available",
        )
        _emit_bridge_record("joint_select", required, result, notes + ["no_candidates"])
        return result

    # Step 2: Score capability + path jointly
    best_result: Optional[JointSelectionResult] = None
    best_joint_score: float = -1.0

    for rec in candidates:
        cap_score = score_provider(rec, required)
        transport_hints = dict(rec.fabric_presence.transport_hints or {})
        path_avail = _probe_path_availability(rec.node_id, transport_hints)

        # Compute degraded flag
        state_str = path_avail.path_state
        cap_state = rec.fabric_presence.presence_state
        cap_state_str = cap_state.value if hasattr(cap_state, "value") else str(cap_state)
        is_degraded = state_str in ("degraded", "fallback", "latent") or cap_state_str == "degraded"

        joint_score = _compute_joint_score(
            cap_score.total_score,
            path_avail.path_score,
            is_degraded,
        )

        if joint_score > best_joint_score:
            best_joint_score = joint_score
            best_result = JointSelectionResult(
                selected_provider_id=rec.node_id,
                capability_fit_score=cap_score,
                path_availability=path_avail,
                joint_score=joint_score,
                required_capabilities=required,
                is_degraded=is_degraded,
                degraded_reason="path_or_capability_degraded" if is_degraded else "",
            )

    if best_result is None:
        # Fallback: first candidate with unknown path
        rec = candidates[0]
        cap_score = score_provider(rec, required)
        empty_path = PathAvailability(
            node_id=rec.node_id,
            effective_path="unknown",
            path_state="unknown",
            path_score=0.1,
            is_reachable=True,
        )
        best_result = JointSelectionResult(
            selected_provider_id=rec.node_id,
            capability_fit_score=cap_score,
            path_availability=empty_path,
            joint_score=cap_score.total_score * 0.1,
            required_capabilities=required,
            is_degraded=True,
            degraded_reason="path_unknown",
        )

    _emit_bridge_record("joint_select", required, best_result, notes)
    return best_result


def explain_joint_selection(result: JointSelectionResult) -> JointSelectionExplanation:
    """Produce a full human-readable explanation for a :class:`JointSelectionResult`.

    Args:
        result: The joint selection result to explain.

    Returns:
        A :class:`JointSelectionExplanation` covering provider selection reason,
        path selection reason, fallback strategy, and degraded-mode explanation.
    """
    # Provider reason
    if result.selected_provider_id is None:
        provider_reason = "No capability provider was available for the requested capabilities."
    elif result.capability_fit_score is not None:
        fit = result.capability_fit_score
        if fit.coverage_ratio >= 1.0:
            provider_reason = (
                f"Provider '{result.selected_provider_id}' selected: "
                f"full capability match ({fit.required_matched}/{fit.required_total} "
                f"capabilities: {', '.join(fit.matched_caps)})."
            )
        elif fit.coverage_ratio > 0:
            provider_reason = (
                f"Provider '{result.selected_provider_id}' selected: "
                f"best partial capability match ({fit.required_matched}/{fit.required_total}; "
                f"matched: {', '.join(fit.matched_caps)}; "
                f"missing: {', '.join(fit.missing_caps)})."
            )
        else:
            provider_reason = (
                f"Provider '{result.selected_provider_id}' selected: "
                "only available provider (no capability match)."
            )
    else:
        provider_reason = (
            f"Provider '{result.selected_provider_id}' selected (capability score unavailable)."
        )

    # Path reason
    path = result.path_availability
    if not path.is_reachable:
        path_reason = (
            f"No reachable network path to '{path.node_id}'. "
            "Provider is currently unreachable."
        )
    else:
        path_reason = (
            f"Transport path to '{path.node_id}': effective_path='{path.effective_path}' "
            f"(state='{path.path_state}', score={path.path_score:.2f})."
        )
        if path.fallback_path:
            path_reason += f" Fallback path available: '{path.fallback_path}'."

    # Fallback reason
    if result.fallback_provider_id:
        fallback_reason = (
            f"If '{result.selected_provider_id}' becomes unavailable, "
            f"fallback provider '{result.fallback_provider_id}' is available "
            f"via path '{result.fallback_path or 'unknown'}'."
        )
    elif path.fallback_path:
        fallback_reason = (
            f"If path '{path.effective_path}' degrades, fallback path "
            f"'{path.fallback_path}' is available for the same provider."
        )
    else:
        fallback_reason = (
            "No pre-computed fallback provider or path. "
            "Use fallback_joint_select() to find alternatives on demand."
        )

    # Degraded explanation
    if result.is_degraded:
        degraded_explanation = (
            f"System is operating in degraded mode: {result.degraded_reason}. "
            "Capability or network availability is reduced. "
            "Results may have reduced quality or reliability."
        )
    else:
        degraded_explanation = "System is operating normally; no degradation detected."

    expl = JointSelectionExplanation(
        provider_reason=provider_reason,
        path_reason=path_reason,
        fallback_reason=fallback_reason,
        degraded_explanation=degraded_explanation,
        joint_result=result,
    )

    _emit_bridge_record(
        "explain",
        result.required_capabilities,
        result,
    )
    return expl


def fallback_joint_select(
    required_capabilities: Optional[List[str]] = None,
    *,
    exclude_ids: Optional[List[str]] = None,
    kind_filter: Optional[List[str]] = None,
    max_results: int = 3,
) -> JointSelectionResult:
    """Select a fallback provider+path when the primary selection has failed.

    Excludes providers in *exclude_ids* (typically the already-failed primary)
    and also considers DEGRADED providers as candidates of last resort.

    Args:
        required_capabilities: Capability names the task requires.
        exclude_ids:           Node IDs to exclude.
        kind_filter:           Optional participant kind restriction.
        max_results:           Maximum fallback candidates to evaluate (best is returned).

    Returns:
        A :class:`JointSelectionResult` for the best fallback provider+path,
        or an empty/degraded result if no fallback is available.
    """
    from core.capability_graph_selection import (  # lazy import
        select_fallback_providers,
        score_provider,
    )

    required: List[str] = list(required_capabilities or [])
    excluded: Set[str] = set(exclude_ids or [])
    notes: List[str] = [f"excluded={sorted(excluded)}"]

    fallback_candidates = select_fallback_providers(
        required_capabilities=required,
        exclude_ids=list(excluded),
        kind_filter=kind_filter,
        max_results=max_results,
    )

    if not fallback_candidates:
        empty_path = PathAvailability(
            node_id="__none__",
            effective_path="unavailable",
            path_state="unavailable",
            path_score=0.0,
            is_reachable=False,
        )
        result = JointSelectionResult(
            selected_provider_id=None,
            capability_fit_score=None,
            path_availability=empty_path,
            joint_score=0.0,
            required_capabilities=required,
            is_degraded=True,
            degraded_reason="no_fallback_providers_available",
        )
        _emit_bridge_record("fallback_select", required, result, notes)
        return result

    best_result: Optional[JointSelectionResult] = None
    best_joint_score: float = -1.0

    for rec in fallback_candidates:
        cap_score = score_provider(rec, required)
        transport_hints = dict(rec.fabric_presence.transport_hints or {})
        path_avail = _probe_path_availability(rec.node_id, transport_hints)

        cap_state = rec.fabric_presence.presence_state
        cap_state_str = cap_state.value if hasattr(cap_state, "value") else str(cap_state)
        is_degraded = (
            path_avail.path_state in ("degraded", "fallback", "latent", "unknown")
            or cap_state_str == "degraded"
        )

        joint_score = _compute_joint_score(
            cap_score.total_score,
            path_avail.path_score,
            is_degraded=True,  # always treat fallback as degraded
        )

        if joint_score > best_joint_score:
            best_joint_score = joint_score
            best_result = JointSelectionResult(
                selected_provider_id=rec.node_id,
                capability_fit_score=cap_score,
                path_availability=path_avail,
                joint_score=joint_score,
                required_capabilities=required,
                is_degraded=True,
                degraded_reason="fallback_provider_selected",
            )

    if best_result is None:
        rec = fallback_candidates[0]
        cap_score = score_provider(rec, required)
        empty_path = PathAvailability(
            node_id=rec.node_id,
            effective_path="unknown",
            path_state="unknown",
            path_score=0.1,
            is_reachable=True,
        )
        best_result = JointSelectionResult(
            selected_provider_id=rec.node_id,
            capability_fit_score=cap_score,
            path_availability=empty_path,
            joint_score=0.1,
            required_capabilities=required,
            is_degraded=True,
            degraded_reason="fallback_with_unknown_path",
        )

    _emit_bridge_record("fallback_select", required, best_result, notes)
    return best_result


# ---------------------------------------------------------------------------
# Ring buffer access
# ---------------------------------------------------------------------------


def get_bridge_log() -> Deque[BridgeRecord]:
    """Return the 256-entry bridge observability ring buffer (read-only view)."""
    return _bridge_log


def reset_bridge_log() -> None:
    """Clear the bridge log (for testing)."""
    global _record_counter
    _bridge_log.clear()
    _record_counter = 0
