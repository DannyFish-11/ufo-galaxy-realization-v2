#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_observability — Multimodal Route Observability and Fallback Analytics
===================================================================================

PR-41 — Multimodal Route Observability and Fallback Analytics

Provides structured observability for multimodal routing decisions so the
control loop can be measured, audited, and tuned.

Architecture
------------

Observability events are **emitted from canonical decisions** (OpenClawd's
``_select_multimodal_route()``), not inferred afterward from logs.  Every
routing decision produces exactly one :class:`RoutingDecisionEvent`, and
every fallback produces one :class:`FallbackDecisionEvent`.

Public structures
-----------------
:class:`RouteKind`
    Stable enum of route tier outcomes (native_multimodal / partial_multimodal /
    text_only / advisory / unknown).

:class:`RoutingFallbackKind`
    Normalised taxonomy of routing fallback reasons suitable for aggregation and
    policy tuning.

:class:`RoutingDecisionEvent`
    Single structured event capturing one routing decision from OpenClawd.
    Always produced by :func:`build_routing_decision_event`.

:class:`FallbackDecisionEvent`
    Single structured fallback event emitted when the route degrades from the
    preferred native-multimodal tier.

:class:`ControlLoopMetrics`
    Thread-safe aggregated counters for routing/fallback decisions.
    Use :func:`get_control_loop_metrics` to access the global singleton.

:class:`RoutingAnalyticsSnapshot`
    Point-in-time, JSON-serialisable snapshot of :class:`ControlLoopMetrics`
    suitable for diagnostics, dashboards, and policy tuning.

Public helpers
--------------
:func:`build_routing_decision_event`
    Build a :class:`RoutingDecisionEvent` from a raw routing-decision dict.

:func:`build_fallback_decision_event`
    Build a :class:`FallbackDecisionEvent` from a :class:`RoutingDecisionEvent`
    when a fallback occurred.  Returns ``None`` when there is no fallback.

:func:`record_routing_decision`
    Primary integration point for OpenClawd: record a routing decision dict,
    update the global :class:`ControlLoopMetrics`, and return the event.

:func:`get_control_loop_metrics`
    Return the global :class:`ControlLoopMetrics` singleton.

:func:`build_routing_analytics_snapshot`
    Build a :class:`RoutingAnalyticsSnapshot` from the current global metrics.

:func:`reset_routing_metrics`
    Reset the global singleton (primarily for tests).

Serialisation
-------------
All public dataclasses expose ``to_dict()`` / ``from_dict()`` round-trip
methods.  All values stored are plain Python primitives (str, int, float,
bool, list, dict) so that ``json.dumps(obj.to_dict())`` always succeeds.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Route / Fallback Kind Enums
# ---------------------------------------------------------------------------


class RouteKind(str, Enum):
    """Stable enum of route tier outcomes from OpenClawd routing decisions.

    Values are lowercase strings safe for serialisation, counter keys, and
    policy analysis.
    """

    NATIVE_MULTIMODAL = "native_multimodal"
    """Tier-1: native multimodal API selected; is_native_multimodal=True."""

    PARTIAL_MULTIMODAL = "partial_multimodal"
    """Tier-2: native MM warranted but provider unavailable; text-capable fallback."""

    TEXT_ONLY = "text_only"
    """Perception state does not require native multimodal; text-only route."""

    ADVISORY = "advisory"
    """No provider reachable at all; safe no-op / degraded advisory output."""

    UNKNOWN = "unknown"
    """Unrecognised route type — should not occur in production."""


class RoutingFallbackKind(str, Enum):
    """Normalised taxonomy of multimodal routing fallback reasons.

    Each value represents a distinct reason the system degraded from the
    preferred native-multimodal tier.  Values are stable strings safe for
    serialisation, aggregation, and policy tuning.
    """

    NONE = "none"
    """No fallback occurred; native multimodal or text-only route was used."""

    NATIVE_MULTIMODAL_TO_TEXT = "native_multimodal_to_text"
    """Native multimodal was warranted but provider unavailable; fell back to text."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """No providers available for the required modalities."""

    CAPABILITY_MISMATCH = "capability_mismatch"
    """Provider exists but lacks the required multimodal capability."""

    ROUTER_UNAVAILABLE = "router_unavailable"
    """The LLM router itself was unavailable."""

    ROUTER_ERROR = "router_error"
    """A routing error occurred preventing normal tier resolution."""

    OTHER = "other"
    """Unclassified fallback; see ``fallback_reason`` for details."""


# ---------------------------------------------------------------------------
# RoutingDecisionEvent
# ---------------------------------------------------------------------------


@dataclass
class RoutingDecisionEvent:
    """A single structured event capturing one multimodal routing decision.

    Emitted by OpenClawd after every call to ``_select_multimodal_route()``.
    Consumers should read from this event rather than re-inferring the route
    from logs or response metadata.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    trace_id:
        Correlation trace ID for the originating request.
    runtime_session_id:
        Active OpenClawd session ID, if available.
    route_kind:
        The tier selected: native_multimodal / partial_multimodal / text_only / advisory.
    is_native_multimodal:
        ``True`` when the selected route is a native multimodal API route (tier 1).
    provider:
        Selected provider name, or ``"none"``.
    model:
        Selected model name, or ``"none"``.
    route_reason:
        Human-readable rationale for the selected tier.
    fallback_kind:
        Normalised fallback kind when the route is a downgrade from tier 1.
    fallback_reason:
        Raw fallback reason string from the routing decision.
    active_modalities:
        Modality list from the canonical perception state.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    route_kind: str = RouteKind.UNKNOWN.value
    is_native_multimodal: bool = False
    provider: str = "none"
    model: str = "none"
    route_reason: str = ""
    fallback_kind: str = RoutingFallbackKind.NONE.value
    fallback_reason: str = ""
    active_modalities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "route_kind": self.route_kind,
            "is_native_multimodal": self.is_native_multimodal,
            "provider": self.provider,
            "model": self.model,
            "route_reason": self.route_reason,
            "fallback_kind": self.fallback_kind,
            "fallback_reason": self.fallback_reason,
            "active_modalities": list(self.active_modalities),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoutingDecisionEvent":
        """Reconstruct a :class:`RoutingDecisionEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            trace_id=d.get("trace_id"),
            runtime_session_id=d.get("runtime_session_id"),
            route_kind=str(d.get("route_kind") or RouteKind.UNKNOWN.value),
            is_native_multimodal=bool(d.get("is_native_multimodal", False)),
            provider=str(d.get("provider") or "none"),
            model=str(d.get("model") or "none"),
            route_reason=str(d.get("route_reason") or ""),
            fallback_kind=str(d.get("fallback_kind") or RoutingFallbackKind.NONE.value),
            fallback_reason=str(d.get("fallback_reason") or ""),
            active_modalities=list(d.get("active_modalities") or []),
        )


# ---------------------------------------------------------------------------
# FallbackDecisionEvent
# ---------------------------------------------------------------------------


@dataclass
class FallbackDecisionEvent:
    """A structured event emitted when multimodal routing falls back.

    A :class:`FallbackDecisionEvent` is emitted for every routing decision
    where ``fallback_kind != "none"``, providing a distinct record of every
    fallback for aggregation and policy analysis.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    trace_id:
        Correlation trace ID for the originating request.
    runtime_session_id:
        Active OpenClawd session ID, if available.
    fallback_kind:
        Normalised fallback kind (from :class:`RoutingFallbackKind`).
    from_route_kind:
        The intended route tier before fallback (native_multimodal when
        fallback was triggered from a multimodal-warranted request).
    to_route_kind:
        The actual route tier after fallback.
    provider:
        Provider selected, or ``"none"`` if none available.
    model:
        Model selected, or ``"none"`` if none available.
    fallback_reason:
        Human-readable raw fallback reason string.
    active_modalities:
        Modality list from the canonical perception state.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    fallback_kind: str = RoutingFallbackKind.OTHER.value
    from_route_kind: str = RouteKind.NATIVE_MULTIMODAL.value
    to_route_kind: str = RouteKind.ADVISORY.value
    provider: str = "none"
    model: str = "none"
    fallback_reason: str = ""
    active_modalities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "fallback_kind": self.fallback_kind,
            "from_route_kind": self.from_route_kind,
            "to_route_kind": self.to_route_kind,
            "provider": self.provider,
            "model": self.model,
            "fallback_reason": self.fallback_reason,
            "active_modalities": list(self.active_modalities),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackDecisionEvent":
        """Reconstruct a :class:`FallbackDecisionEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            trace_id=d.get("trace_id"),
            runtime_session_id=d.get("runtime_session_id"),
            fallback_kind=str(d.get("fallback_kind") or RoutingFallbackKind.OTHER.value),
            from_route_kind=str(d.get("from_route_kind") or RouteKind.NATIVE_MULTIMODAL.value),
            to_route_kind=str(d.get("to_route_kind") or RouteKind.ADVISORY.value),
            provider=str(d.get("provider") or "none"),
            model=str(d.get("model") or "none"),
            fallback_reason=str(d.get("fallback_reason") or ""),
            active_modalities=list(d.get("active_modalities") or []),
        )


# ---------------------------------------------------------------------------
# RoutingAnalyticsSnapshot
# ---------------------------------------------------------------------------


@dataclass
class RoutingAnalyticsSnapshot:
    """Point-in-time snapshot of :class:`ControlLoopMetrics` for diagnostics/dashboards.

    This is the stable, serialisable surface for diagnostics, policy tuning,
    and future dashboard rendering.  It captures both raw counts and
    rate-normalised values (0.0–1.0) for easy comparison.

    Attributes
    ----------
    total_decisions:
        Total routing decisions recorded since last reset.
    native_multimodal_count:
        Number of native multimodal (tier-1) route selections.
    text_only_count:
        Number of text-only route selections.
    partial_multimodal_count:
        Number of partial multimodal (text-capable fallback) selections.
    advisory_count:
        Number of advisory (degraded/no-op) route selections.
    native_multimodal_rate:
        Fraction of decisions that selected native multimodal (0.0–1.0).
    text_only_rate:
        Fraction of decisions that were text-only (0.0–1.0).
    partial_multimodal_rate:
        Fraction of decisions that fell back to partial multimodal (0.0–1.0).
    advisory_rate:
        Fraction of decisions that resulted in advisory/no-op (0.0–1.0).
    fallback_kind_counts:
        Dict mapping :class:`RoutingFallbackKind` string → count.
    route_reason_counts:
        Dict mapping route_reason string → count.
    provider_counts:
        Dict mapping provider name → count.
    model_counts:
        Dict mapping model name → count.
    projection_mismatch_count:
        Count of detected projection/control mismatches.
    snapshotted_at:
        Unix timestamp when the snapshot was taken.
    schema_version:
        Integer schema version for forward compatibility.  Currently ``1``.
    """

    total_decisions: int = 0
    native_multimodal_count: int = 0
    text_only_count: int = 0
    partial_multimodal_count: int = 0
    advisory_count: int = 0
    native_multimodal_rate: float = 0.0
    text_only_rate: float = 0.0
    partial_multimodal_rate: float = 0.0
    advisory_rate: float = 0.0
    fallback_kind_counts: Dict[str, int] = field(default_factory=dict)
    route_reason_counts: Dict[str, int] = field(default_factory=dict)
    provider_counts: Dict[str, int] = field(default_factory=dict)
    model_counts: Dict[str, int] = field(default_factory=dict)
    projection_mismatch_count: int = 0
    snapshotted_at: float = field(default_factory=time.time)
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "total_decisions": self.total_decisions,
            "native_multimodal_count": self.native_multimodal_count,
            "text_only_count": self.text_only_count,
            "partial_multimodal_count": self.partial_multimodal_count,
            "advisory_count": self.advisory_count,
            "native_multimodal_rate": self.native_multimodal_rate,
            "text_only_rate": self.text_only_rate,
            "partial_multimodal_rate": self.partial_multimodal_rate,
            "advisory_rate": self.advisory_rate,
            "fallback_kind_counts": dict(self.fallback_kind_counts),
            "route_reason_counts": dict(self.route_reason_counts),
            "provider_counts": dict(self.provider_counts),
            "model_counts": dict(self.model_counts),
            "projection_mismatch_count": self.projection_mismatch_count,
            "snapshotted_at": self.snapshotted_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoutingAnalyticsSnapshot":
        """Reconstruct a :class:`RoutingAnalyticsSnapshot` from a plain dict."""
        return cls(
            schema_version=int(d.get("schema_version") or 1),
            total_decisions=int(d.get("total_decisions") or 0),
            native_multimodal_count=int(d.get("native_multimodal_count") or 0),
            text_only_count=int(d.get("text_only_count") or 0),
            partial_multimodal_count=int(d.get("partial_multimodal_count") or 0),
            advisory_count=int(d.get("advisory_count") or 0),
            native_multimodal_rate=float(d.get("native_multimodal_rate") or 0.0),
            text_only_rate=float(d.get("text_only_rate") or 0.0),
            partial_multimodal_rate=float(d.get("partial_multimodal_rate") or 0.0),
            advisory_rate=float(d.get("advisory_rate") or 0.0),
            fallback_kind_counts=dict(d.get("fallback_kind_counts") or {}),
            route_reason_counts=dict(d.get("route_reason_counts") or {}),
            provider_counts=dict(d.get("provider_counts") or {}),
            model_counts=dict(d.get("model_counts") or {}),
            projection_mismatch_count=int(d.get("projection_mismatch_count") or 0),
            snapshotted_at=float(d.get("snapshotted_at") or time.time()),
        )


# ---------------------------------------------------------------------------
# ControlLoopMetrics
# ---------------------------------------------------------------------------


class ControlLoopMetrics:
    """Thread-safe aggregated counters for multimodal routing decisions.

    Accumulates routing and fallback decision counts from
    :class:`RoutingDecisionEvent` instances.  Intended to be used as a
    singleton via :func:`get_control_loop_metrics`.

    Tracked metrics
    ---------------
    - ``native_multimodal_count`` — total native MM route selections.
    - ``text_only_count`` — total text-only route selections.
    - ``partial_multimodal_count`` — total partial MM (text-capable fallback) selections.
    - ``advisory_count`` — total advisory (no-op/degraded) route selections.
    - ``total_decisions`` — total routing decisions recorded.
    - ``fallback_kind_counts`` — dict mapping :class:`RoutingFallbackKind` → count.
    - ``route_reason_counts`` — dict mapping route_reason string → count (capped).
    - ``provider_counts`` — dict mapping provider name → count.
    - ``model_counts`` — dict mapping model name → count.
    - ``projection_mismatch_count`` — count of detected projection/control mismatches.
    """

    _MAX_REASON_KEYS: int = 200  # Cap on distinct route_reason strings tracked.

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._reset_counters()

    def _reset_counters(self) -> None:
        self.native_multimodal_count: int = 0
        self.text_only_count: int = 0
        self.partial_multimodal_count: int = 0
        self.advisory_count: int = 0
        self.total_decisions: int = 0
        self.fallback_kind_counts: Dict[str, int] = {}
        self.route_reason_counts: Dict[str, int] = {}
        self.provider_counts: Dict[str, int] = {}
        self.model_counts: Dict[str, int] = {}
        self.projection_mismatch_count: int = 0

    def reset(self) -> None:
        """Reset all counters to zero (primarily for tests)."""
        with self._lock:
            self._reset_counters()

    def record(self, event: RoutingDecisionEvent) -> None:
        """Record a :class:`RoutingDecisionEvent` into the aggregated counters."""
        with self._lock:
            self.total_decisions += 1

            kind = event.route_kind
            if kind == RouteKind.NATIVE_MULTIMODAL.value:
                self.native_multimodal_count += 1
            elif kind == RouteKind.TEXT_ONLY.value:
                self.text_only_count += 1
            elif kind == RouteKind.PARTIAL_MULTIMODAL.value:
                self.partial_multimodal_count += 1
            elif kind == RouteKind.ADVISORY.value:
                self.advisory_count += 1

            # Fallback kind distribution
            fk = event.fallback_kind
            self.fallback_kind_counts[fk] = self.fallback_kind_counts.get(fk, 0) + 1

            # Route reason distribution (bounded to avoid unbounded memory growth)
            rr = event.route_reason
            if rr and len(self.route_reason_counts) < self._MAX_REASON_KEYS:
                self.route_reason_counts[rr] = self.route_reason_counts.get(rr, 0) + 1

            # Provider/model frequency
            if event.provider and event.provider != "none":
                self.provider_counts[event.provider] = (
                    self.provider_counts.get(event.provider, 0) + 1
                )
            if event.model and event.model != "none":
                self.model_counts[event.model] = (
                    self.model_counts.get(event.model, 0) + 1
                )

    def record_projection_mismatch(self) -> None:
        """Increment the projection/control mismatch counter."""
        with self._lock:
            self.projection_mismatch_count += 1

    def snapshot(self) -> RoutingAnalyticsSnapshot:
        """Build a point-in-time :class:`RoutingAnalyticsSnapshot` from current state."""
        with self._lock:
            total = self.total_decisions if self.total_decisions > 0 else 1
            return RoutingAnalyticsSnapshot(
                total_decisions=self.total_decisions,
                native_multimodal_count=self.native_multimodal_count,
                text_only_count=self.text_only_count,
                partial_multimodal_count=self.partial_multimodal_count,
                advisory_count=self.advisory_count,
                native_multimodal_rate=self.native_multimodal_count / total,
                text_only_rate=self.text_only_count / total,
                partial_multimodal_rate=self.partial_multimodal_count / total,
                advisory_rate=self.advisory_count / total,
                fallback_kind_counts=dict(self.fallback_kind_counts),
                route_reason_counts=dict(self.route_reason_counts),
                provider_counts=dict(self.provider_counts),
                model_counts=dict(self.model_counts),
                projection_mismatch_count=self.projection_mismatch_count,
                snapshotted_at=time.time(),
            )


# ---------------------------------------------------------------------------
# Singleton global metrics
# ---------------------------------------------------------------------------

_GLOBAL_METRICS: Optional[ControlLoopMetrics] = None
_METRICS_LOCK = threading.Lock()


def get_control_loop_metrics() -> ControlLoopMetrics:
    """Return the global :class:`ControlLoopMetrics` singleton."""
    global _GLOBAL_METRICS
    if _GLOBAL_METRICS is None:
        with _METRICS_LOCK:
            if _GLOBAL_METRICS is None:
                _GLOBAL_METRICS = ControlLoopMetrics()
    return _GLOBAL_METRICS


def reset_routing_metrics() -> None:
    """Reset the global :class:`ControlLoopMetrics` singleton (primarily for tests)."""
    get_control_loop_metrics().reset()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_fallback_kind(route_dict: Dict[str, Any]) -> str:
    """Derive a :class:`RoutingFallbackKind` string from a raw routing decision dict.

    Maps the structured fields of the dict returned by
    ``OpenClawd._select_multimodal_route()`` to the normalised
    :class:`RoutingFallbackKind` taxonomy.
    """
    route_type = str(route_dict.get("route_type") or "")
    fallback_reason = str(route_dict.get("fallback_reason") or "")

    if route_type in (RouteKind.NATIVE_MULTIMODAL.value, RouteKind.TEXT_ONLY.value):
        return RoutingFallbackKind.NONE.value

    if "router_unavailable" in fallback_reason:
        return RoutingFallbackKind.ROUTER_UNAVAILABLE.value

    if "routing_error" in fallback_reason or "error=" in fallback_reason:
        return RoutingFallbackKind.ROUTER_ERROR.value

    if "no_providers_available" in fallback_reason:
        return RoutingFallbackKind.PROVIDER_UNAVAILABLE.value

    if "native_multimodal_provider_unavailable" in fallback_reason:
        return RoutingFallbackKind.NATIVE_MULTIMODAL_TO_TEXT.value

    if "capability_mismatch" in fallback_reason:
        return RoutingFallbackKind.CAPABILITY_MISMATCH.value

    if fallback_reason:
        return RoutingFallbackKind.OTHER.value

    return RoutingFallbackKind.NONE.value


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_routing_decision_event(
    route_dict: Dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> RoutingDecisionEvent:
    """Build a :class:`RoutingDecisionEvent` from a raw routing decision dict.

    Parameters
    ----------
    route_dict:
        The dict returned by ``OpenClawd._select_multimodal_route()``.
    trace_id:
        Optional correlation trace ID for the originating request.
    runtime_session_id:
        Optional session ID for the originating request.

    Returns
    -------
    RoutingDecisionEvent
        A fully-populated, serialisable routing decision event.
    """
    route_type = str(route_dict.get("route_type") or RouteKind.UNKNOWN.value)
    fallback_kind = _classify_fallback_kind(route_dict)

    return RoutingDecisionEvent(
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        route_kind=route_type,
        is_native_multimodal=bool(route_dict.get("is_native_multimodal", False)),
        provider=str(route_dict.get("provider") or "none"),
        model=str(route_dict.get("model") or "none"),
        route_reason=str(route_dict.get("route_reason") or ""),
        fallback_kind=fallback_kind,
        fallback_reason=str(route_dict.get("fallback_reason") or ""),
        active_modalities=list(route_dict.get("active_modalities") or []),
    )


def build_fallback_decision_event(
    routing_event: RoutingDecisionEvent,
) -> Optional[FallbackDecisionEvent]:
    """Build a :class:`FallbackDecisionEvent` from a :class:`RoutingDecisionEvent`.

    Returns ``None`` when no fallback occurred (``fallback_kind == "none"``).

    Parameters
    ----------
    routing_event:
        The :class:`RoutingDecisionEvent` from the same routing decision.

    Returns
    -------
    FallbackDecisionEvent or None
        A fallback event if the routing decision involved a fallback,
        otherwise ``None``.
    """
    if routing_event.fallback_kind == RoutingFallbackKind.NONE.value:
        return None
    return FallbackDecisionEvent(
        trace_id=routing_event.trace_id,
        runtime_session_id=routing_event.runtime_session_id,
        fallback_kind=routing_event.fallback_kind,
        from_route_kind=RouteKind.NATIVE_MULTIMODAL.value,
        to_route_kind=routing_event.route_kind,
        provider=routing_event.provider,
        model=routing_event.model,
        fallback_reason=routing_event.fallback_reason,
        active_modalities=list(routing_event.active_modalities),
    )


def record_routing_decision(
    route_dict: Dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> RoutingDecisionEvent:
    """Record a routing decision into the global :class:`ControlLoopMetrics`.

    This is the primary integration point for OpenClawd.  Call after every
    ``_select_multimodal_route()`` invocation.

    Parameters
    ----------
    route_dict:
        The dict returned by ``OpenClawd._select_multimodal_route()``.
    trace_id:
        Optional correlation trace ID.
    runtime_session_id:
        Optional session ID.

    Returns
    -------
    RoutingDecisionEvent
        The event that was recorded into the global metrics.
    """
    event = build_routing_decision_event(
        route_dict,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
    )
    get_control_loop_metrics().record(event)
    return event


def build_routing_analytics_snapshot() -> RoutingAnalyticsSnapshot:
    """Build a :class:`RoutingAnalyticsSnapshot` from the current global metrics."""
    return get_control_loop_metrics().snapshot()
