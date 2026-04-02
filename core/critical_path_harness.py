#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/critical_path_harness.py
==============================
PR-515 — Critical Interaction Path Hardening.

This module is the **canonical routing-path authority** for the Galaxy
multi-model intelligent routing system.  It hardens the most important
end-to-end interaction paths so that the system is not merely architecturally
coherent but reliably usable along the highest-value routes that matter most
to actual operation.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  PRODUCT / OPERATOR / STATUS SURFACES                               │
    │  API projection  ·  operator inspect  ·  status board              │
    └────────────────────────────┬────────────────────────────────────────┘
                                 │  CRITICAL-PATH-VERIFIED EVIDENCE
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  CRITICAL PATH HARNESS LAYER  (this module, Layer 15)              │
    │                                                                     │
    │  Hardens (end-to-end path records, non-blocking):                  │
    │    • Multimodal ingress → canonical route selection                │
    │    • Primary model / provider selection                            │
    │    • Support / fallback provider switching                         │
    │    • Execution dispatch via CommandRouter                          │
    │    • Result return to caller                                       │
    │                                                                     │
    │  Closes:                                                            │
    │    • GAP-512-009: establishes a canonical runtime authority for    │
    │      multi-model routing path separate from ContinuumState /       │
    │      TopologyRoutePlan so that routing decisions are inspectable   │
    │      through operator surfaces, not only through projection        │
    │      stack representations.                                        │
    │                                                                     │
    │  Integration sentinels wired into:                                 │
    │    • core/openclawd.py (multimodal ingress + route selection)      │
    │    • core/multi_llm_router.py (routing authority)                  │
    │                                                                     │
    │  Policy sentinels:                                                  │
    │    • MULTIMODAL_INGRESS_PATH_CLOSED_POLICY                         │
    │    • ROUTING_AUTHORITY_CANONICAL_POLICY                            │
    │    • PROVIDER_SELECTION_INSPECTABLE_POLICY                         │
    │    • FALLBACK_SWITCHING_HARNESS_POLICY                             │
    │    • NO_COMPETING_ROUTING_AUTHORITY_POLICY (closes GAP-512-009)   │
    └────────────────────────────┬────────────────────────────────────────┘
                                 │  READS CANONICAL LAYERS
                                 ▼
    ┌─────────────────────────────────────────────────────────────────────┐
    │  RUNTIME TRUTH LAYERS (Layers 6–14)                                │
    │  TaskGraphRuntime · CanonicalTaskRuntime · ReplayFoundation        │
    │  AuditEventSemantics · OperatorSurface                             │
    │  CapabilityAssimilationLayer · NetworkTopologyRuntime              │
    │  ClosureAuditRuntime · FailureDegradedRecoveryRuntime              │
    │  AuthorityConflictEliminationRuntime                               │
    └─────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Multimodal ingress path is materially closed.**
    From the moment a multimodal request enters OpenClawd through routing,
    provider selection, fallback, dispatch, and result return, every
    handoff is recorded so the path can be verified and debugged.
    Governed by :data:`MULTIMODAL_INGRESS_PATH_CLOSED_POLICY`.

2.  **Routing authority is canonical, not projection-derived.**
    Multi-model routing decisions must be recorded in this canonical
    runtime layer, not derived only from ContinuumState / TopologyRoutePlan
    projections.  This closes GAP-512-009.
    Governed by :data:`ROUTING_AUTHORITY_CANONICAL_POLICY`.

3.  **Provider selection and fallback switching are operator-inspectable.**
    Every provider selection and every fallback switch produces a
    harness record that can be read via the canonical operator surface.
    Governed by :data:`PROVIDER_SELECTION_INSPECTABLE_POLICY`.

4.  **Fallback switching is a first-class harness event.**
    A fallback switch (tier-1 → tier-2, primary → fallback provider)
    is not merely a routing artifact but an explicit runtime event with
    its own record, so that operator and projection layers observe full
    primary → fallback arcs.
    Governed by :data:`FALLBACK_SWITCHING_HARNESS_POLICY`.

5.  **No competing routing authority is introduced.**
    This module records facts into a ring buffer for inspection.  It does
    NOT introduce a new canonical routing policy that competes with
    MultiLLMRouter or OpenClawd.  It is a harness, not a router.
    Governed by :data:`NO_COMPETING_ROUTING_AUTHORITY_POLICY`.

6.  **Harness writes are best-effort and non-blocking.**
    All ring-buffer writes are wrapped so that harness failures never
    abort the primary routing or execution path.
    Governed by :data:`HARNESS_NON_BLOCKING_POLICY`.

7.  **Abstraction discipline is preserved.**
    Product-facing surfaces consume this layer through canonical
    operator/projection boundaries only.  Raw ring-buffer contents are
    not exposed directly to product UI surfaces.
    Governed by :data:`ABSTRACTION_DISCIPLINE_POLICY`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.CriticalPathHarness")

# ===========================================================================
# Module-level authority / policy sentinels
# ===========================================================================

#: Authority sentinel for this module.  Import-verified by closure audit.
CRITICAL_PATH_HARNESS_AUTHORITY: str = (
    "CRITICAL_PATH_HARNESS::AUTHORITY_V1: "
    "core/critical_path_harness.py is the canonical layer for "
    "multi-model interaction path harness records in the Galaxy system. "
    "Closes GAP-512-009 (routing path canonical authority)."
)

#: Layer position in the canonical authority stack (above authority conflict
#: elimination layer at 14).
CRITICAL_PATH_HARNESS_LAYER_POSITION: int = 15

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

#: Multimodal ingress path must be materially closed end-to-end.
MULTIMODAL_INGRESS_PATH_CLOSED_POLICY: str = (
    "MULTIMODAL_INGRESS_PATH_CLOSED_V1: "
    "From multimodal ingress through routing, provider selection, "
    "fallback, dispatch, and result return, every critical handoff "
    "MUST be recorded in the harness ring buffer so the path is "
    "verifiable and debuggable when exercised."
)

#: Routing decisions are recorded in a canonical runtime layer, not only
#: in ContinuumState / TopologyRoutePlan projection.
ROUTING_AUTHORITY_CANONICAL_POLICY: str = (
    "ROUTING_AUTHORITY_CANONICAL_V1: "
    "Multi-model routing decisions MUST produce harness records in this "
    "module (Layer 15) so they are canonical-runtime-inspectable.  "
    "ContinuumState / TopologyRoutePlan remain model-provider routing "
    "projections but are NOT the sole authority for routing truth.  "
    "Resolves GAP-512-009."
)

#: Provider selection and fallback switches must be operator-inspectable.
PROVIDER_SELECTION_INSPECTABLE_POLICY: str = (
    "PROVIDER_SELECTION_INSPECTABLE_V1: "
    "Every provider-selection and every fallback-switch event MUST "
    "produce a CriticalPathHarness record accessible through canonical "
    "operator inspection surfaces."
)

#: Fallback switching is a first-class harness event.
FALLBACK_SWITCHING_HARNESS_POLICY: str = (
    "FALLBACK_SWITCHING_HARNESS_V1: "
    "Fallback switches (tier-1 → tier-2, primary → fallback provider) "
    "are first-class harness events with their own ProviderSwitchRecord. "
    "They MUST NOT be treated as silent internal routing artifacts."
)

#: No competing routing authority — harness is observer-only.
NO_COMPETING_ROUTING_AUTHORITY_POLICY: str = (
    "NO_COMPETING_ROUTING_AUTHORITY_V1: "
    "CriticalPathHarness is an observer and recorder.  It MUST NOT "
    "make routing decisions or modify provider selection.  MultiLLMRouter "
    "and OpenClawd retain full routing authority. "
    "Resolves GAP-512-009: adds canonical runtime authority for routing "
    "path inspection without competing with the router."
)

#: Harness writes must not block or abort the primary path.
HARNESS_NON_BLOCKING_POLICY: str = (
    "HARNESS_NON_BLOCKING_V1: All harness ring-buffer writes are wrapped "
    "in try/except.  A harness write failure MUST NOT abort the primary "
    "routing or execution path."
)

#: Abstraction discipline — do not expose raw ring buffer to product UI.
ABSTRACTION_DISCIPLINE_POLICY: str = (
    "ABSTRACTION_DISCIPLINE_V1: Product-facing surfaces consume harness "
    "evidence through canonical operator/projection boundaries only. "
    "Raw ring-buffer contents MUST NOT be exposed directly to product UI."
)

#: PR-515 integration sentinel — verifiable by closure audit.
CRITICAL_PATH_HARNESS_INTEGRATED: str = (
    "CRITICAL_PATH_HARNESS::INTEGRATED_V1: "
    "PR-515 critical path harness is wired into "
    "core/openclawd.py (CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED) and "
    "core/multi_llm_router.py (CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED). "
    "Closes GAP-512-009."
)

__all__ = [
    # Authority / policy sentinels
    "CRITICAL_PATH_HARNESS_AUTHORITY",
    "CRITICAL_PATH_HARNESS_LAYER_POSITION",
    "MULTIMODAL_INGRESS_PATH_CLOSED_POLICY",
    "ROUTING_AUTHORITY_CANONICAL_POLICY",
    "PROVIDER_SELECTION_INSPECTABLE_POLICY",
    "FALLBACK_SWITCHING_HARNESS_POLICY",
    "NO_COMPETING_ROUTING_AUTHORITY_POLICY",
    "HARNESS_NON_BLOCKING_POLICY",
    "ABSTRACTION_DISCIPLINE_POLICY",
    "CRITICAL_PATH_HARNESS_INTEGRATED",
    # Enums
    "CriticalPathKind",
    "PathHarnessState",
    # Dataclasses
    "IngressHarnessRecord",
    "RouteSelectionRecord",
    "ProviderSwitchRecord",
    "ExecutionDispatchRecord",
    "CriticalPathSnapshot",
    # Singleton
    "CriticalPathHarnessRuntime",
    "get_critical_path_harness",
    "reset_critical_path_harness",
    # Helpers
    "record_ingress_path",
    "record_route_selection",
    "record_provider_switch",
    "record_execution_dispatch",
    "snapshot_critical_path",
]

# ===========================================================================
# Constants
# ===========================================================================

_RING_BUFFER_SIZE: int = 256

# ===========================================================================
# Enums
# ===========================================================================


class CriticalPathKind(str, Enum):
    """Identifies the kind of critical interaction path event.

    Each value corresponds to a distinct stage in the end-to-end path
    from multimodal ingress through routing to result return.
    """

    MULTIMODAL_INGRESS = "multimodal_ingress"
    """A multimodal request arrived at the OpenClawd ingress point."""

    ROUTE_SELECTION = "route_selection"
    """The routing tier was selected (native_multimodal / partial / text_only / advisory)."""

    PROVIDER_SELECTION = "provider_selection"
    """A primary model provider and model were selected for this request."""

    FALLBACK_SWITCH = "fallback_switch"
    """The routing path switched from a primary provider to a fallback provider."""

    EXECUTION_DISPATCH = "execution_dispatch"
    """The task was dispatched via CommandRouter to an executor."""

    RESULT_RETURN = "result_return"
    """A result was returned to the caller, completing the interaction path."""


class PathHarnessState(str, Enum):
    """Canonical state of a critical path harness record.

    Describes the outcome or current status at the time the record was
    captured.
    """

    ACTIVE = "active"
    """Path segment is in progress."""

    COMPLETED = "completed"
    """Path segment completed successfully."""

    DEGRADED = "degraded"
    """Path segment completed but at reduced capability (e.g., tier-2 fallback)."""

    FALLBACK_ACTIVE = "fallback_active"
    """Primary path failed; fallback path is being used."""

    ADVISORY = "advisory"
    """No provider is reachable; advisory/no-op mode."""

    FAILED = "failed"
    """Path segment failed without successful recovery."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class IngressHarnessRecord:
    """Records a multimodal ingress event at the OpenClawd boundary.

    Captures the active modalities, trace identity, and whether native
    multimodal routing was warranted, so that the full path can be traced
    from ingress onward.

    Attributes
    ----------
    trace_id:
        Canonical trace identifier for this request.
    session_id:
        Runtime session identifier (may be empty for stateless requests).
    active_modalities:
        List of modality names detected at ingress (e.g., ``["image", "text"]``).
    requires_native_multimodal:
        Whether the ingress warranted native multimodal routing.
    source:
        Module / method that recorded this ingress event.
    timestamp:
        UNIX timestamp when the record was captured.
    """

    trace_id: str = ""
    session_id: str = ""
    active_modalities: List[str] = field(default_factory=list)
    requires_native_multimodal: bool = False
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary for operator/projection consumption."""
        return {
            "kind": CriticalPathKind.MULTIMODAL_INGRESS.value,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "active_modalities": list(self.active_modalities),
            "requires_native_multimodal": self.requires_native_multimodal,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class RouteSelectionRecord:
    """Records a routing-tier selection made by the native-multimodal-first policy.

    Captures the selected tier, provider, model, and fallback reason so
    that the routing decision is inspectable through operator surfaces.

    Attributes
    ----------
    trace_id:
        Canonical trace identifier.
    route_type:
        One of ``"native_multimodal"``, ``"partial_multimodal"``,
        ``"text_only"``, ``"advisory"``.
    provider:
        Selected provider name, or ``"none"``.
    model:
        Selected model name, or ``"none"``.
    route_reason:
        Human-readable rationale for the selected tier.
    fallback_reason:
        Non-empty when a downgrade occurred.
    active_modalities:
        Modalities that were active at the time of routing.
    harness_state:
        State of this path segment.
    source:
        Module / method that recorded this event.
    timestamp:
        UNIX timestamp when the record was captured.
    """

    trace_id: str = ""
    route_type: str = ""
    provider: str = ""
    model: str = ""
    route_reason: str = ""
    fallback_reason: str = ""
    active_modalities: List[str] = field(default_factory=list)
    harness_state: PathHarnessState = PathHarnessState.COMPLETED
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary for operator/projection consumption."""
        return {
            "kind": CriticalPathKind.ROUTE_SELECTION.value,
            "trace_id": self.trace_id,
            "route_type": self.route_type,
            "provider": self.provider,
            "model": self.model,
            "route_reason": self.route_reason,
            "fallback_reason": self.fallback_reason,
            "active_modalities": list(self.active_modalities),
            "harness_state": self.harness_state.value,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class ProviderSwitchRecord:
    """Records a provider selection or fallback-switch event.

    Captures both the primary provider that was attempted and the provider
    that was ultimately selected, making the full fallback arc inspectable.

    Attributes
    ----------
    trace_id:
        Canonical trace identifier.
    from_provider:
        The provider that was attempted first (or ``"none"`` for first selection).
    to_provider:
        The provider that was ultimately selected.
    from_model:
        Model associated with ``from_provider`` (or ``"none"``).
    to_model:
        Model associated with ``to_provider``.
    switch_reason:
        Why the switch occurred (e.g., ``"provider_unavailable"``,
        ``"native_multimodal_unavailable"``).
    is_fallback:
        ``True`` when this record describes a fallback switch rather than
        an initial selection.
    harness_state:
        State of this path segment.
    source:
        Module / method that recorded this event.
    timestamp:
        UNIX timestamp when the record was captured.
    """

    trace_id: str = ""
    from_provider: str = "none"
    to_provider: str = ""
    from_model: str = "none"
    to_model: str = ""
    switch_reason: str = ""
    is_fallback: bool = False
    harness_state: PathHarnessState = PathHarnessState.COMPLETED
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Set harness_state to FALLBACK_ACTIVE when is_fallback=True."""
        if self.is_fallback and self.harness_state == PathHarnessState.COMPLETED:
            self.harness_state = PathHarnessState.FALLBACK_ACTIVE

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary for operator/projection consumption."""
        kind = (
            CriticalPathKind.FALLBACK_SWITCH.value
            if self.is_fallback
            else CriticalPathKind.PROVIDER_SELECTION.value
        )
        return {
            "kind": kind,
            "trace_id": self.trace_id,
            "from_provider": self.from_provider,
            "to_provider": self.to_provider,
            "from_model": self.from_model,
            "to_model": self.to_model,
            "switch_reason": self.switch_reason,
            "is_fallback": self.is_fallback,
            "harness_state": self.harness_state.value,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class ExecutionDispatchRecord:
    """Records execution dispatch of a task via CommandRouter.

    Captures the task identity and dispatch target so that the path from
    routing decision through execution dispatch is traceable.

    Attributes
    ----------
    task_id:
        Canonical task identifier.
    trace_id:
        Canonical trace identifier.
    executor:
        Target executor node identifier (or ``"unknown"``).
    dispatch_method:
        How the task was dispatched (e.g., ``"direct"``, ``"fabric"``,
        ``"gateway"``).
    provider:
        Provider selected for this dispatch (from the routing decision).
    model:
        Model selected for this dispatch.
    harness_state:
        State of this path segment.
    source:
        Module / method that recorded this event.
    timestamp:
        UNIX timestamp when the record was captured.
    """

    task_id: str = ""
    trace_id: str = ""
    executor: str = "unknown"
    dispatch_method: str = ""
    provider: str = ""
    model: str = ""
    harness_state: PathHarnessState = PathHarnessState.ACTIVE
    source: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary for operator/projection consumption."""
        return {
            "kind": CriticalPathKind.EXECUTION_DISPATCH.value,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "executor": self.executor,
            "dispatch_method": self.dispatch_method,
            "provider": self.provider,
            "model": self.model,
            "harness_state": self.harness_state.value,
            "source": self.source,
            "timestamp": self.timestamp,
        }


@dataclass
class CriticalPathSnapshot:
    """Snapshot of recent critical path harness activity.

    Produced by :meth:`CriticalPathHarnessRuntime.snapshot`.

    Attributes
    ----------
    ingress_count:
        Total multimodal ingress records in the ring buffer.
    route_selection_count:
        Total route-selection records in the ring buffer.
    provider_switch_count:
        Total provider-selection / fallback-switch records in the ring buffer.
    dispatch_count:
        Total execution-dispatch records in the ring buffer.
    fallback_count:
        Subset of provider_switch_count where ``is_fallback=True``.
    advisory_count:
        Route-selection records where ``route_type="advisory"``.
    recent_route_type:
        ``route_type`` of the most recent route-selection record, or ``""``
        if none.
    recent_provider:
        ``to_provider`` of the most recent provider record, or ``""``
        if none.
    snapshot_ts:
        UNIX timestamp when the snapshot was taken.
    """

    ingress_count: int = 0
    route_selection_count: int = 0
    provider_switch_count: int = 0
    dispatch_count: int = 0
    fallback_count: int = 0
    advisory_count: int = 0
    recent_route_type: str = ""
    recent_provider: str = ""
    snapshot_ts: float = field(default_factory=time.time)

    def summary(self) -> Dict[str, Any]:
        """Return a plain dictionary summary suitable for operator surfaces."""
        return {
            "ingress_count": self.ingress_count,
            "route_selection_count": self.route_selection_count,
            "provider_switch_count": self.provider_switch_count,
            "dispatch_count": self.dispatch_count,
            "fallback_count": self.fallback_count,
            "advisory_count": self.advisory_count,
            "recent_route_type": self.recent_route_type,
            "recent_provider": self.recent_provider,
            "snapshot_ts": self.snapshot_ts,
        }


# ===========================================================================
# Singleton runtime
# ===========================================================================


class CriticalPathHarnessRuntime:
    """Canonical runtime for multi-model interaction path harness records.

    Maintains separate ring buffers for each record type and provides
    snapshot/query methods for operator inspection.  All writes are
    thread-safe.

    This class is accessed as a singleton via :func:`get_critical_path_harness`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ingress: Deque[IngressHarnessRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._route_selections: Deque[RouteSelectionRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._provider_switches: Deque[ProviderSwitchRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._dispatches: Deque[ExecutionDispatchRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )

    # -----------------------------------------------------------------------
    # Write methods
    # -----------------------------------------------------------------------

    def record_ingress(self, record: IngressHarnessRecord) -> None:
        """Append an :class:`IngressHarnessRecord` to the ingress ring buffer."""
        with self._lock:
            self._ingress.append(record)

    def record_route_selection(self, record: RouteSelectionRecord) -> None:
        """Append a :class:`RouteSelectionRecord` to the route-selection ring buffer."""
        with self._lock:
            self._route_selections.append(record)

    def record_provider_switch(self, record: ProviderSwitchRecord) -> None:
        """Append a :class:`ProviderSwitchRecord` to the provider-switch ring buffer."""
        with self._lock:
            self._provider_switches.append(record)

    def record_dispatch(self, record: ExecutionDispatchRecord) -> None:
        """Append an :class:`ExecutionDispatchRecord` to the dispatch ring buffer."""
        with self._lock:
            self._dispatches.append(record)

    # -----------------------------------------------------------------------
    # Query methods
    # -----------------------------------------------------------------------

    def get_ingress_records(
        self, limit: Optional[int] = None
    ) -> List[IngressHarnessRecord]:
        """Return recent ingress records, newest last."""
        with self._lock:
            records = list(self._ingress)
        return records[-limit:] if limit else records

    def get_route_selection_records(
        self, limit: Optional[int] = None
    ) -> List[RouteSelectionRecord]:
        """Return recent route-selection records, newest last."""
        with self._lock:
            records = list(self._route_selections)
        return records[-limit:] if limit else records

    def get_provider_switch_records(
        self, limit: Optional[int] = None
    ) -> List[ProviderSwitchRecord]:
        """Return recent provider-switch records, newest last."""
        with self._lock:
            records = list(self._provider_switches)
        return records[-limit:] if limit else records

    def get_dispatch_records(
        self, limit: Optional[int] = None
    ) -> List[ExecutionDispatchRecord]:
        """Return recent dispatch records, newest last."""
        with self._lock:
            records = list(self._dispatches)
        return records[-limit:] if limit else records

    def get_fallback_records(
        self, limit: Optional[int] = None
    ) -> List[ProviderSwitchRecord]:
        """Return provider-switch records where ``is_fallback=True``."""
        with self._lock:
            records = [r for r in self._provider_switches if r.is_fallback]
        return records[-limit:] if limit else records

    # -----------------------------------------------------------------------
    # Snapshot
    # -----------------------------------------------------------------------

    def snapshot(self) -> CriticalPathSnapshot:
        """Return a :class:`CriticalPathSnapshot` of current ring-buffer state."""
        with self._lock:
            ingress_list = list(self._ingress)
            route_list = list(self._route_selections)
            switch_list = list(self._provider_switches)
            dispatch_list = list(self._dispatches)

        fallback_count = sum(1 for r in switch_list if r.is_fallback)
        advisory_count = sum(
            1 for r in route_list if r.route_type == "advisory"
        )
        recent_route_type = route_list[-1].route_type if route_list else ""
        recent_provider = switch_list[-1].to_provider if switch_list else ""

        return CriticalPathSnapshot(
            ingress_count=len(ingress_list),
            route_selection_count=len(route_list),
            provider_switch_count=len(switch_list),
            dispatch_count=len(dispatch_list),
            fallback_count=fallback_count,
            advisory_count=advisory_count,
            recent_route_type=recent_route_type,
            recent_provider=recent_provider,
        )


# ===========================================================================
# Singleton management
# ===========================================================================

_harness_instance: Optional[CriticalPathHarnessRuntime] = None
_harness_lock = threading.Lock()


def get_critical_path_harness() -> CriticalPathHarnessRuntime:
    """Return the process-wide :class:`CriticalPathHarnessRuntime` singleton."""
    global _harness_instance
    if _harness_instance is None:
        with _harness_lock:
            if _harness_instance is None:
                _harness_instance = CriticalPathHarnessRuntime()
    return _harness_instance


def reset_critical_path_harness() -> None:
    """Reset the singleton (test isolation only)."""
    global _harness_instance
    with _harness_lock:
        _harness_instance = None


# ===========================================================================
# Helper functions
# ===========================================================================


def record_ingress_path(
    *,
    trace_id: str = "",
    session_id: str = "",
    active_modalities: Optional[List[str]] = None,
    requires_native_multimodal: bool = False,
    source: str = "",
) -> IngressHarnessRecord:
    """Record a multimodal ingress event in the harness ring buffer.

    This is the primary integration point for :meth:`OpenClawd.process`
    (and equivalent multimodal ingress surfaces) to record that a
    multimodal request arrived at the system boundary.

    Per :data:`HARNESS_NON_BLOCKING_POLICY`, this function never raises.

    Args:
        trace_id: Canonical trace identifier.
        session_id: Runtime session identifier.
        active_modalities: Modality names detected at ingress.
        requires_native_multimodal: Whether native MM routing was warranted.
        source: Calling module / method name.

    Returns:
        The :class:`IngressHarnessRecord` that was appended.
    """
    rec = IngressHarnessRecord(
        trace_id=trace_id,
        session_id=session_id,
        active_modalities=active_modalities or [],
        requires_native_multimodal=requires_native_multimodal,
        source=source,
    )
    try:
        get_critical_path_harness().record_ingress(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_ingress_path: harness write skipped: %s", exc)
    return rec


def record_route_selection(
    *,
    trace_id: str = "",
    route_type: str = "",
    provider: str = "",
    model: str = "",
    route_reason: str = "",
    fallback_reason: str = "",
    active_modalities: Optional[List[str]] = None,
    source: str = "",
) -> RouteSelectionRecord:
    """Record a routing-tier selection in the harness ring buffer.

    Called after :meth:`OpenClawd._select_multimodal_route` produces a
    routing decision, so that the decision is recorded in the canonical
    harness layer (not only in the ContinuumState projection).

    Per :data:`HARNESS_NON_BLOCKING_POLICY`, this function never raises.

    Args:
        trace_id: Canonical trace identifier.
        route_type: Selected routing tier.
        provider: Selected provider name.
        model: Selected model name.
        route_reason: Human-readable rationale.
        fallback_reason: Non-empty if a downgrade occurred.
        active_modalities: Active modality list at routing time.
        source: Calling module / method name.

    Returns:
        The :class:`RouteSelectionRecord` that was appended.
    """
    # Determine harness state from route_type
    _state_map = {
        "native_multimodal": PathHarnessState.COMPLETED,
        "partial_multimodal": PathHarnessState.DEGRADED,
        "text_only": PathHarnessState.COMPLETED,
        "advisory": PathHarnessState.ADVISORY,
    }
    harness_state = _state_map.get(route_type, PathHarnessState.COMPLETED)

    rec = RouteSelectionRecord(
        trace_id=trace_id,
        route_type=route_type,
        provider=provider,
        model=model,
        route_reason=route_reason,
        fallback_reason=fallback_reason,
        active_modalities=active_modalities or [],
        harness_state=harness_state,
        source=source,
    )
    try:
        get_critical_path_harness().record_route_selection(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_route_selection: harness write skipped: %s", exc)
    return rec


def record_provider_switch(
    *,
    trace_id: str = "",
    from_provider: str = "none",
    to_provider: str = "",
    from_model: str = "none",
    to_model: str = "",
    switch_reason: str = "",
    is_fallback: bool = False,
    source: str = "",
) -> ProviderSwitchRecord:
    """Record a provider selection or fallback-switch event.

    Called when a provider is selected (first selection) or when the routing
    path switches from a primary provider to a fallback provider.

    Per :data:`HARNESS_NON_BLOCKING_POLICY`, this function never raises.

    Args:
        trace_id: Canonical trace identifier.
        from_provider: Primary provider attempted (``"none"`` for first selection).
        to_provider: Provider ultimately selected.
        from_model: Model for ``from_provider``.
        to_model: Model for ``to_provider``.
        switch_reason: Why the switch occurred.
        is_fallback: ``True`` when this is a fallback switch, not initial selection.
        source: Calling module / method name.

    Returns:
        The :class:`ProviderSwitchRecord` that was appended.
    """
    harness_state = (
        PathHarnessState.FALLBACK_ACTIVE if is_fallback else PathHarnessState.COMPLETED
    )
    rec = ProviderSwitchRecord(
        trace_id=trace_id,
        from_provider=from_provider,
        to_provider=to_provider,
        from_model=from_model,
        to_model=to_model,
        switch_reason=switch_reason,
        is_fallback=is_fallback,
        harness_state=harness_state,
        source=source,
    )
    try:
        get_critical_path_harness().record_provider_switch(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_provider_switch: harness write skipped: %s", exc)
    return rec


def record_execution_dispatch(
    *,
    task_id: str = "",
    trace_id: str = "",
    executor: str = "unknown",
    dispatch_method: str = "",
    provider: str = "",
    model: str = "",
    source: str = "",
) -> ExecutionDispatchRecord:
    """Record an execution dispatch event in the harness ring buffer.

    Called when :class:`~core.command_router.CommandRouter` dispatches a
    task to an executor, completing the routing → dispatch leg of the
    critical path.

    Per :data:`HARNESS_NON_BLOCKING_POLICY`, this function never raises.

    Args:
        task_id: Canonical task identifier.
        trace_id: Canonical trace identifier.
        executor: Target executor node identifier.
        dispatch_method: Dispatch method (``"direct"``, ``"fabric"``, etc.).
        provider: Provider selected for this dispatch.
        model: Model selected for this dispatch.
        source: Calling module / method name.

    Returns:
        The :class:`ExecutionDispatchRecord` that was appended.
    """
    rec = ExecutionDispatchRecord(
        task_id=task_id,
        trace_id=trace_id,
        executor=executor,
        dispatch_method=dispatch_method,
        provider=provider,
        model=model,
        harness_state=PathHarnessState.ACTIVE,
        source=source,
    )
    try:
        get_critical_path_harness().record_dispatch(rec)
    except Exception as exc:  # noqa: BLE001
        logger.debug("record_execution_dispatch: harness write skipped: %s", exc)
    return rec


def snapshot_critical_path() -> Dict[str, Any]:
    """Return a plain-dictionary snapshot of the critical path harness.

    Combines :meth:`CriticalPathHarnessRuntime.snapshot` with the
    canonical policy sentinels so that operator inspection surfaces
    can verify both harness liveness and governance adherence.

    Returns:
        Dict with the :meth:`CriticalPathSnapshot.summary` keys plus:
        - ``"authority"``: :data:`CRITICAL_PATH_HARNESS_AUTHORITY`
        - ``"layer_position"``: :data:`CRITICAL_PATH_HARNESS_LAYER_POSITION`
        - ``"gap_closed"``: ``"GAP-512-009"``
    """
    snap = get_critical_path_harness().snapshot()
    result = snap.summary()
    result["authority"] = CRITICAL_PATH_HARNESS_AUTHORITY
    result["layer_position"] = CRITICAL_PATH_HARNESS_LAYER_POSITION
    result["gap_closed"] = "GAP-512-009"
    return result
