"""
core/device_activation_registry.py
===================================
PR-DEVICE-RESOLUTION: Device Activation Registry — Observe-Only Decision Tracing

Records every device-to-node resolution and activation policy decision
without executing any side effects.  This is the observability plane for
the Device Resolution & Activation system.

Records:
    - Resolver inputs (device_type, transport, capabilities)
    - Match results (which rules hit, which node was selected)
    - Policy decisions (why a node should/should not start)
    - Full correlation context (trace_id, timestamp, source event)

This module does NOT start nodes, does NOT listen to events, and does NOT
modify system state.  It is a pure observation / audit / diagnostics layer.

Usage::

    from core.device_activation_registry import get_registry

    registry = get_registry()
    registry.record_resolution(
        device_type="android_phone",
        transport=None,
        capabilities=None,
        result=resolved_mapping,
        decision=activation_decision,
        trace_id=trace_id,
    )

    # Later: query what happened
    recent = registry.list_recent(limit=50)
    stats = registry.get_decision_stats()
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from core.activation_policy import ActivationDecision
from core.device_node_resolver import ResolvedMapping

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
DEVICE_ACTIVATION_REGISTRY_SENTINEL = (
    "DEVICE_ACTIVATION_REGISTRY::OBSERVE_ONLY_DECISION_TRACING"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class ResolutionRecord:
    """A single device-to-node resolution + activation decision snapshot."""

    # Identification
    record_id: str
    trace_id: str
    correlation_id: str
    timestamp: float

    # Source event context (what triggered this resolution)
    source_event: str  # e.g. "device_registered", "capability_request", "boot"
    source_module: str

    # Device description (resolver inputs)
    device_id: Optional[str]
    device_type: Optional[str]
    transport: Optional[str]
    requested_capabilities: List[str]

    # Resolution results
    matched_rules: List[str]
    resolved_nodes: List[str]
    selected_node: Optional[str]
    selected_node_port: Optional[int]

    # Activation decision
    activation_policy: Optional[str]
    decision: str  # "start" | "skip" | "unknown"
    decision_reason: str

    # Diagnostics
    duration_ms: float
    conflicts: List[str]  # if multiple rules matched, note conflicts
    fallback_used: bool  # True if capability fallback was used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "timestamp_iso": time.strftime(
                "%Y-%m-%dT%H:%M:%S", time.localtime(self.timestamp)
            ),
            "source_event": self.source_event,
            "source_module": self.source_module,
            "device": {
                "id": self.device_id,
                "type": self.device_type,
                "transport": self.transport,
                "capabilities": self.requested_capabilities,
            },
            "resolution": {
                "matched_rules": self.matched_rules,
                "resolved_nodes": self.resolved_nodes,
                "selected_node": self.selected_node,
                "selected_node_port": self.selected_node_port,
                "fallback_used": self.fallback_used,
                "conflicts": self.conflicts,
            },
            "activation": {
                "policy": self.activation_policy,
                "decision": self.decision,
                "reason": self.decision_reason,
            },
            "performance": {
                "duration_ms": self.duration_ms,
            },
        }


@dataclass
class ResolutionStats:
    """Aggregated statistics over the recorded history."""

    total_records: int
    start_decisions: int
    skip_decisions: int
    unknown_decisions: int
    fallback_count: int
    conflict_count: int
    avg_duration_ms: float
    policy_distribution: Dict[str, int]
    top_device_types: List[str]
    top_nodes: List[str]
    error_count: int


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class DeviceActivationRegistry:
    """Observe-only registry for device-to-node resolution decisions.

    Maintains an in-memory ring buffer of resolution records.  No persistence,
    no side effects.  Pure observation and diagnostics.

    Args:
        max_records: Ring buffer capacity (default 10_000).
    """

    def __init__(self, max_records: int = 10_000) -> None:
        self._records: Deque[ResolutionRecord] = deque(maxlen=max_records)
        self._node_stats: Dict[str, Dict[str, int]] = {}
        self._policy_stats: Dict[str, int] = {}
        self._device_type_stats: Dict[str, int] = {}
        self._error_count: int = 0

    # -- public: recording ---------------------------------------------------

    def record_resolution(
        self,
        *,
        device_type: Optional[str] = None,
        transport: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        device_id: Optional[str] = None,
        result: Optional[ResolvedMapping] = None,
        decision: Optional[ActivationDecision] = None,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        source_event: str = "unknown",
        source_module: str = "device_activation_registry",
        duration_ms: float = 0.0,
    ) -> ResolutionRecord:
        """Record a resolution + decision snapshot.

        This is the primary entry point.  Called by resolver/policy
        orchestrators after a decision is made.

        Args:
            device_type: The AIP device type that was resolved.
            transport: The transport protocol.
            capabilities: Requested capabilities.
            device_id: Specific device instance ID (if known).
            result: The ResolvedMapping from DeviceNodeResolver.
            decision: The ActivationDecision from ActivationPolicyEngine.
            trace_id: End-to-end correlation ID.
            correlation_id: Business correlation ID.
            source_event: What triggered this resolution.
            source_module: Which module initiated the resolution.
            duration_ms: How long the resolution took.

        Returns:
            The created ResolutionRecord.
        """
        now = time.time()
        tid = trace_id or str(uuid.uuid4())[:8]
        cid = correlation_id or tid

        # Build match rule descriptions
        matched_rules: List[str] = []
        conflicts: List[str] = []
        fallback_used = False
        resolved_nodes: List[str] = []
        selected_node: Optional[str] = None
        selected_port: Optional[int] = None

        if result:
            matched_rules.append(f"{result.match_type}:{result.match_key}")
            selected_node = result.implementation.node
            selected_port = result.implementation.port
            resolved_nodes.append(selected_node)
            if result.match_type == "capabilities":
                fallback_used = True

        # Check for conflicts (multiple rules could match)
        if device_type and transport:
            # Both type and transport provided — note if they diverge
            pass  # Future: check if type-match and transport-match disagree

        # Activation decision
        act_policy: Optional[str] = None
        decision_str = "unknown"
        decision_reason = "No decision provided"

        if decision:
            act_policy = decision.policy.value
            decision_str = "start" if decision.should_start else "skip"
            decision_reason = decision.reason

        # Handle "no result" case
        if result is None:
            decision_str = "unknown"
            decision_reason = f"No mapping for device_type={device_type} transport={transport}"
            if decision is None:
                self._error_count += 1

        record = ResolutionRecord(
            record_id=str(uuid.uuid4())[:12],
            trace_id=tid,
            correlation_id=cid,
            timestamp=now,
            source_event=source_event,
            source_module=source_module,
            device_id=device_id,
            device_type=device_type,
            transport=transport,
            requested_capabilities=list(capabilities or []),
            matched_rules=matched_rules,
            resolved_nodes=resolved_nodes,
            selected_node=selected_node,
            selected_node_port=selected_port,
            activation_policy=act_policy,
            decision=decision_str,
            decision_reason=decision_reason,
            duration_ms=duration_ms,
            conflicts=conflicts,
            fallback_used=fallback_used,
        )

        self._records.append(record)
        self._update_stats(record)

        logger.debug(
            "[ActivationRegistry] %s | %s → %s | %s | %s",
            record.record_id,
            device_type or transport or str(capabilities),
            selected_node or "UNRESOLVED",
            decision_str,
            decision_reason[:60],
        )

        return record

    def record_error(
        self,
        *,
        error: str,
        device_type: Optional[str] = None,
        transport: Optional[str] = None,
        trace_id: Optional[str] = None,
        source_event: str = "unknown",
    ) -> None:
        """Record a resolution error (no result, no decision)."""
        self.record_resolution(
            device_type=device_type,
            transport=transport,
            decision=None,
            result=None,
            trace_id=trace_id,
            source_event=source_event,
            decision_reason=f"ERROR: {error}",
        )
        self._error_count += 1

    # -- public: querying ----------------------------------------------------

    def list_recent(
        self,
        *,
        limit: int = 50,
        device_type: Optional[str] = None,
        node: Optional[str] = None,
    ) -> List[ResolutionRecord]:
        """Return recent resolution records with optional filters."""
        records = list(self._records)
        if device_type:
            records = [r for r in records if r.device_type == device_type]
        if node:
            records = [r for r in records if r.selected_node == node]
        return records[-limit:]

    def get_stats(self) -> ResolutionStats:
        """Return aggregated statistics over all recorded history."""
        records = list(self._records)
        if not records:
            return ResolutionStats(0, 0, 0, 0, 0, 0, 0.0, {}, [], [], 0)

        start_d = sum(1 for r in records if r.decision == "start")
        skip_d = sum(1 for r in records if r.decision == "skip")
        unknown_d = sum(1 for r in records if r.decision == "unknown")
        fallback_c = sum(1 for r in records if r.fallback_used)
        conflict_c = sum(len(r.conflicts) for r in records)
        avg_dur = sum(r.duration_ms for r in records) / len(records)

        # Top device types
        dt_counts: Dict[str, int] = {}
        for r in records:
            if r.device_type:
                dt_counts[r.device_type] = dt_counts.get(r.device_type, 0) + 1
        top_dt = sorted(dt_counts, key=dt_counts.get, reverse=True)[:5]

        # Top nodes
        n_counts: Dict[str, int] = {}
        for r in records:
            if r.selected_node:
                n_counts[r.selected_node] = n_counts.get(r.selected_node, 0) + 1
        top_n = sorted(n_counts, key=n_counts.get, reverse=True)[:5]

        return ResolutionStats(
            total_records=len(records),
            start_decisions=start_d,
            skip_decisions=skip_d,
            unknown_decisions=unknown_d,
            fallback_count=fallback_c,
            conflict_count=conflict_c,
            avg_duration_ms=round(avg_dur, 2),
            policy_distribution=dict(self._policy_stats),
            top_device_types=top_dt,
            top_nodes=top_n,
            error_count=self._error_count,
        )

    def get_node_history(self, node_name: str) -> List[ResolutionRecord]:
        """Return all records that resolved to a specific node."""
        return [r for r in self._records if r.selected_node == node_name]

    def get_unresolved(self, limit: int = 50) -> List[ResolutionRecord]:
        """Return records where no mapping was found."""
        return [
            r for r in self._records
            if r.selected_node is None
        ][-limit:]

    def export_json(self, limit: int = 1_000) -> List[Dict[str, Any]]:
        """Export recent records as JSON-serializable dicts."""
        return [r.to_dict() for r in list(self._records)[-limit:]]

    # -- internal ------------------------------------------------------------

    def _update_stats(self, record: ResolutionRecord) -> None:
        if record.selected_node:
            self._node_stats.setdefault(record.selected_node, {"count": 0, "starts": 0})
            self._node_stats[record.selected_node]["count"] += 1
            if record.decision == "start":
                self._node_stats[record.selected_node]["starts"] += 1

        if record.activation_policy:
            self._policy_stats[record.activation_policy] = (
                self._policy_stats.get(record.activation_policy, 0) + 1
            )

        if record.device_type:
            self._device_type_stats[record.device_type] = (
                self._device_type_stats.get(record.device_type, 0) + 1
            )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_registry_instance: Optional[DeviceActivationRegistry] = None


def get_registry() -> DeviceActivationRegistry:
    """Return the module-level DeviceActivationRegistry singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = DeviceActivationRegistry()
    return _registry_instance
