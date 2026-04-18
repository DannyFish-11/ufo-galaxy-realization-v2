"""core/runtime/runtime_observability_sink.py
=============================================
Runtime Observability Sink — PR-G.

This module implements the **canonical production-grade runtime observability
sink** for multi-device runtime state transitions and dispatch decisions.

It answers the architectural question:

    *"Where do structured runtime observability events go, and how do the
    existing lifecycle/dispatch modules emit them in a production-observable
    way?"*

Background
----------
The contracts defined in ``contracts/runtime_observability.py`` (PR-G) define
what structured events look like.  This module implements:

1. :class:`RuntimeObservabilitySink` — a thread-safe, in-process ring-buffer
   sink that accumulates structured observability events across the process
   lifetime.  Bounded to prevent unbounded memory growth in production.

2. Module-level emit helpers that combine structured event building, structured
   logging (at INFO level for major state transitions), and ring-buffer storage
   into a single call per event type:

   - :func:`emit_device_lifecycle_event` — device attach/detach/reconnect/etc.
   - :func:`emit_mesh_session_transition_event` — mesh session lifecycle
   - :func:`emit_dispatch_decision_event` — dispatch plan selection
   - :func:`emit_recovery_decision_event` — recovery/reassociation decisions

3. Snapshot and query helpers:
   - :func:`get_observability_sink` — return the global singleton
   - :func:`build_observability_snapshot` — serialisable point-in-time snapshot
   - :func:`reset_observability_sink` — reset the singleton (for tests)

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Thread-safe** — a process-level :class:`threading.Lock` guards the
  ring-buffer; emit helpers are safe to call from any thread.
- **Bounded** — the ring-buffer is capped at
  :data:`SINK_MAX_EVENTS_PER_KIND` entries per event kind to prevent
  memory growth in long-running processes.
- **Structured logging** — every emit also logs a structured INFO record
  to ``Galaxy.RuntimeObservability`` so that existing log pipelines can
  capture the event without requiring a custom consumer.
- **Graceful degradation** — emit helpers never raise.  Any error in event
  building or sink storage is logged at DEBUG and suppressed.
- **Fully serialisable** — :func:`build_observability_snapshot` returns a
  plain-dict snapshot suitable for ``json.dumps``.

Sentinels
---------
:data:`RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY`
    Affirms this module is the canonical runtime observability sink for PR-G.
:data:`SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY`
    Affirms that emit helpers produce both structured log records and
    ring-buffer entries for every major state transition.
:data:`SINK_IS_BOUNDED_POLICY`
    Affirms that the ring-buffer is bounded per event kind.

Usage::

    from core.runtime.runtime_observability_sink import (
        emit_device_lifecycle_event,
        emit_mesh_session_transition_event,
        emit_dispatch_decision_event,
        emit_recovery_decision_event,
        build_observability_snapshot,
    )

    # Emit when a device attaches:
    emit_device_lifecycle_event(
        device_id="android_01",
        event_kind="attach",
        reason="device_registered_with_join_runtime_posture",
        session_id="sess_abc",
    )

    # Emit when a dispatch plan is selected:
    emit_dispatch_decision_event(
        mode="remote_handoff",
        dispatch_id="disp_xyz",
        decision_reason="mesh_participant_available_and_eligible",
        executor_target_type="android_device",
        target_device_id="android_01",
    )

    # Get a snapshot for diagnostics:
    snapshot = build_observability_snapshot()
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from contracts.runtime_observability import (
    DeviceLifecycleEvent,
    DeviceLifecycleEventKind,
    DispatchDecisionEvent,
    DispatchDecisionEventKind,
    MeshSessionTransitionEvent,
    MeshSessionTransitionKind,
    RecoveryDecisionEvent,
    RecoveryDecisionKind,
    build_device_lifecycle_event,
    build_dispatch_decision_event,
    build_mesh_session_transition_event,
    build_recovery_decision_event,
)

logger = logging.getLogger("Galaxy.RuntimeObservability")

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY: str = (
    "RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY: "
    "core/runtime/runtime_observability_sink.py is the canonical production-grade "
    "runtime observability sink for PR-G.  It accumulates structured events for "
    "device lifecycle, mesh session transitions, dispatch decisions, and recovery "
    "decisions in a thread-safe, bounded in-process ring-buffer, and emits "
    "structured log records for each event."
)

SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY: str = (
    "POLICY::SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_PR-G: "
    "Every emit helper in this module produces both a structured logging.INFO "
    "record to the 'Galaxy.RuntimeObservability' logger AND a ring-buffer entry.  "
    "This ensures that even when no explicit consumer reads the ring-buffer, "
    "all major state transitions appear in production log pipelines.  PR-G."
)

SINK_IS_BOUNDED_POLICY: str = (
    "POLICY::SINK_IS_BOUNDED_PR-G: "
    "The runtime observability ring-buffer is bounded at "
    "SINK_MAX_EVENTS_PER_KIND entries per event kind.  When the buffer is full, "
    "the oldest event is discarded.  This prevents unbounded memory growth in "
    "long-running production processes.  PR-G."
)

RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL: str = (
    "RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL: "
    "PR-G runtime observability sink is present and active.  Structured emit "
    "helpers for device lifecycle, mesh session transitions, dispatch decisions, "
    "and recovery decisions are operational."
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SINK_MAX_EVENTS_PER_KIND: int = 256
"""Maximum number of events retained per event kind in the ring-buffer."""


# ---------------------------------------------------------------------------
# ObservabilitySnapshot — point-in-time serialisable snapshot
# ---------------------------------------------------------------------------


@dataclass
class ObservabilitySnapshot:
    """Point-in-time snapshot of the runtime observability sink.

    Attributes
    ----------
    snapshot_id:
        Auto-generated UUID for this snapshot.
    timestamp:
        Unix timestamp when the snapshot was taken.
    device_lifecycle_events:
        Recent device lifecycle events (up to SINK_MAX_EVENTS_PER_KIND).
    mesh_session_transition_events:
        Recent mesh session transition events.
    dispatch_decision_events:
        Recent dispatch decision events.
    recovery_decision_events:
        Recent recovery decision events.
    total_device_events_emitted:
        Total device lifecycle events emitted since sink creation.
    total_mesh_events_emitted:
        Total mesh session transition events emitted since sink creation.
    total_dispatch_events_emitted:
        Total dispatch decision events emitted since sink creation.
    total_recovery_events_emitted:
        Total recovery decision events emitted since sink creation.
    """

    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    device_lifecycle_events: List[Dict[str, Any]] = field(default_factory=list)
    mesh_session_transition_events: List[Dict[str, Any]] = field(default_factory=list)
    dispatch_decision_events: List[Dict[str, Any]] = field(default_factory=list)
    recovery_decision_events: List[Dict[str, Any]] = field(default_factory=list)
    total_device_events_emitted: int = 0
    total_mesh_events_emitted: int = 0
    total_dispatch_events_emitted: int = 0
    total_recovery_events_emitted: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "device_lifecycle_events": list(self.device_lifecycle_events),
            "mesh_session_transition_events": list(self.mesh_session_transition_events),
            "dispatch_decision_events": list(self.dispatch_decision_events),
            "recovery_decision_events": list(self.recovery_decision_events),
            "total_device_events_emitted": self.total_device_events_emitted,
            "total_mesh_events_emitted": self.total_mesh_events_emitted,
            "total_dispatch_events_emitted": self.total_dispatch_events_emitted,
            "total_recovery_events_emitted": self.total_recovery_events_emitted,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# RuntimeObservabilitySink
# ---------------------------------------------------------------------------


class RuntimeObservabilitySink:
    """Thread-safe, bounded in-process ring-buffer for runtime observability events.

    Collects structured events for device lifecycle, mesh session transitions,
    dispatch decisions, and recovery decisions.  Bounded to prevent unbounded
    memory growth in long-running processes.

    Usage::

        sink = get_observability_sink()
        sink.record_device_lifecycle_event(event)
        snapshot = sink.snapshot()
    """

    def __init__(self, max_events: int = SINK_MAX_EVENTS_PER_KIND) -> None:
        self._max_events = max_events
        self._lock = threading.Lock()
        self._device_events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._mesh_events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._dispatch_events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._recovery_events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        # Monotonic counters — not bounded; count total emits across the sink lifetime.
        self._total_device: int = 0
        self._total_mesh: int = 0
        self._total_dispatch: int = 0
        self._total_recovery: int = 0

    # ------------------------------------------------------------------
    # Record methods
    # ------------------------------------------------------------------

    def record_device_lifecycle_event(self, event: DeviceLifecycleEvent) -> None:
        """Add a device lifecycle event to the ring-buffer."""
        with self._lock:
            self._device_events.append(event.to_dict())
            self._total_device += 1

    def record_mesh_session_transition_event(self, event: MeshSessionTransitionEvent) -> None:
        """Add a mesh session transition event to the ring-buffer."""
        with self._lock:
            self._mesh_events.append(event.to_dict())
            self._total_mesh += 1

    def record_dispatch_decision_event(self, event: DispatchDecisionEvent) -> None:
        """Add a dispatch decision event to the ring-buffer."""
        with self._lock:
            self._dispatch_events.append(event.to_dict())
            self._total_dispatch += 1

    def record_recovery_decision_event(self, event: RecoveryDecisionEvent) -> None:
        """Add a recovery decision event to the ring-buffer."""
        with self._lock:
            self._recovery_events.append(event.to_dict())
            self._total_recovery += 1

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def list_device_lifecycle_events(self) -> List[Dict[str, Any]]:
        """Return a copy of the current device lifecycle event buffer."""
        with self._lock:
            return list(self._device_events)

    def list_mesh_session_transition_events(self) -> List[Dict[str, Any]]:
        """Return a copy of the current mesh session transition event buffer."""
        with self._lock:
            return list(self._mesh_events)

    def list_dispatch_decision_events(self) -> List[Dict[str, Any]]:
        """Return a copy of the current dispatch decision event buffer."""
        with self._lock:
            return list(self._dispatch_events)

    def list_recovery_decision_events(self) -> List[Dict[str, Any]]:
        """Return a copy of the current recovery decision event buffer."""
        with self._lock:
            return list(self._recovery_events)

    def snapshot(self) -> ObservabilitySnapshot:
        """Return a :class:`ObservabilitySnapshot` of the current sink state."""
        with self._lock:
            return ObservabilitySnapshot(
                device_lifecycle_events=list(self._device_events),
                mesh_session_transition_events=list(self._mesh_events),
                dispatch_decision_events=list(self._dispatch_events),
                recovery_decision_events=list(self._recovery_events),
                total_device_events_emitted=self._total_device,
                total_mesh_events_emitted=self._total_mesh,
                total_dispatch_events_emitted=self._total_dispatch,
                total_recovery_events_emitted=self._total_recovery,
            )

    def counters(self) -> Dict[str, int]:
        """Return total emit counts per event kind."""
        with self._lock:
            return {
                "device_lifecycle": self._total_device,
                "mesh_session_transition": self._total_mesh,
                "dispatch_decision": self._total_dispatch,
                "recovery_decision": self._total_recovery,
            }

    def reset(self) -> None:
        """Clear all buffers and reset counters.  For use in tests only."""
        with self._lock:
            self._device_events.clear()
            self._mesh_events.clear()
            self._dispatch_events.clear()
            self._recovery_events.clear()
            self._total_device = 0
            self._total_mesh = 0
            self._total_dispatch = 0
            self._total_recovery = 0


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_sink_lock = threading.Lock()
_singleton: Optional[RuntimeObservabilitySink] = None


def get_observability_sink() -> RuntimeObservabilitySink:
    """Return the process-level :class:`RuntimeObservabilitySink` singleton."""
    global _singleton
    if _singleton is None:
        with _sink_lock:
            if _singleton is None:
                _singleton = RuntimeObservabilitySink()
    return _singleton


def reset_observability_sink() -> None:
    """Reset the singleton.  Primarily for use in tests."""
    global _singleton
    with _sink_lock:
        _singleton = None


# ---------------------------------------------------------------------------
# Emit helpers — combine event building + logging + sink storage
# ---------------------------------------------------------------------------


def emit_device_lifecycle_event(
    device_id: str,
    event_kind: "DeviceLifecycleEventKind | str" = DeviceLifecycleEventKind.unknown,
    *,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    formation_id: Optional[str] = None,
    prior_state: Optional[str] = None,
    new_state: Optional[str] = None,
    readiness: Optional[str] = None,
    health_score: Optional[float] = None,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[DeviceLifecycleEvent]:
    """Emit a structured device lifecycle event.

    Builds a :class:`~contracts.runtime_observability.DeviceLifecycleEvent`,
    logs it at INFO level to ``Galaxy.RuntimeObservability``, and stores it
    in the process-level observability sink.

    Parameters
    ----------
    device_id:
        Identifier of the device whose lifecycle changed.
    event_kind:
        :class:`~contracts.runtime_observability.DeviceLifecycleEventKind` or
        string value describing what happened.
    trace_id:
        Optional correlation trace ID.
    session_id:
        Optional active session identifier.
    mesh_session_id:
        Optional active mesh session identifier.
    formation_id:
        Optional formation identifier.
    prior_state:
        The lifecycle/attachment state before this transition.
    new_state:
        The lifecycle/attachment state after this transition.
    readiness:
        Readiness string for readiness_change events.
    health_score:
        Normalised health score when available.
    reason:
        Human-readable explanation of why this event occurred.
    metadata:
        Optional arbitrary extensibility dict.

    Returns
    -------
    DeviceLifecycleEvent or None
        The emitted event, or None if an error occurred.
    """
    try:
        evt = build_device_lifecycle_event(
            device_id=device_id,
            event_kind=event_kind,
            trace_id=trace_id,
            session_id=session_id,
            mesh_session_id=mesh_session_id,
            formation_id=formation_id,
            prior_state=prior_state,
            new_state=new_state,
            readiness=readiness,
            health_score=health_score,
            reason=reason,
            metadata=metadata,
        )
        logger.info(
            "device_lifecycle event_kind=%s device_id=%s new_state=%s reason=%s "
            "trace_id=%s event_id=%s",
            evt.event_kind,
            evt.device_id,
            evt.new_state,
            evt.reason,
            evt.trace_id,
            evt.event_id,
        )
        get_observability_sink().record_device_lifecycle_event(evt)
        return evt
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_device_lifecycle_event: suppressed error — %s", exc)
        return None


def emit_mesh_session_transition_event(
    session_id: str,
    transition_kind: "MeshSessionTransitionKind | str" = MeshSessionTransitionKind.unknown,
    *,
    mesh_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    prior_status: Optional[str] = None,
    new_status: Optional[str] = None,
    source_device_id: Optional[str] = None,
    primary_device_id: Optional[str] = None,
    participant_device_id: Optional[str] = None,
    participant_count: int = 0,
    reason: str = "",
    restore_count: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[MeshSessionTransitionEvent]:
    """Emit a structured mesh session lifecycle transition event.

    Parameters
    ----------
    session_id:
        The mesh session identifier.
    transition_kind:
        :class:`~contracts.runtime_observability.MeshSessionTransitionKind` or
        string value.
    mesh_id:
        Optional mesh/body identifier.
    trace_id:
        Optional correlation trace ID.
    task_id:
        Optional task identifier.
    prior_status:
        Session status before this transition.
    new_status:
        Session status after this transition.
    source_device_id:
        Device that initiated the session or triggered the transition.
    primary_device_id:
        Primary executor device for the session.
    participant_device_id:
        Device involved in participant_joined/left transitions.
    participant_count:
        Number of participants after the transition.
    reason:
        Human-readable explanation of why this transition occurred.
    restore_count:
        Number of times this session has been restored.
    metadata:
        Optional arbitrary extensibility dict.

    Returns
    -------
    MeshSessionTransitionEvent or None
        The emitted event, or None if an error occurred.
    """
    try:
        evt = build_mesh_session_transition_event(
            session_id=session_id,
            transition_kind=transition_kind,
            mesh_id=mesh_id,
            trace_id=trace_id,
            task_id=task_id,
            prior_status=prior_status,
            new_status=new_status,
            source_device_id=source_device_id,
            primary_device_id=primary_device_id,
            participant_device_id=participant_device_id,
            participant_count=participant_count,
            reason=reason,
            restore_count=restore_count,
            metadata=metadata,
        )
        logger.info(
            "mesh_session_transition transition_kind=%s session_id=%s "
            "prior_status=%s new_status=%s reason=%s trace_id=%s event_id=%s",
            evt.transition_kind,
            evt.session_id,
            evt.prior_status,
            evt.new_status,
            evt.reason,
            evt.trace_id,
            evt.event_id,
        )
        get_observability_sink().record_mesh_session_transition_event(evt)
        return evt
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_mesh_session_transition_event: suppressed error — %s", exc)
        return None


def emit_dispatch_decision_event(
    mode: str,
    *,
    event_kind: "DispatchDecisionEventKind | str" = DispatchDecisionEventKind.plan_selected,
    dispatch_id: Optional[str] = None,
    plan_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    prior_mode: Optional[str] = None,
    executor_target_type: Optional[str] = None,
    target_device_id: Optional[str] = None,
    has_mesh_session: bool = False,
    has_handoff_envelope: bool = False,
    has_continuity_context: bool = False,
    decision_reason: str = "",
    success: bool = False,
    error_summary: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[DispatchDecisionEvent]:
    """Emit a structured dispatch decision event.

    Parameters
    ----------
    mode:
        The dispatch mode selected.
    event_kind:
        :class:`~contracts.runtime_observability.DispatchDecisionEventKind` or
        string value.
    dispatch_id:
        The dispatch decision identifier.
    plan_id:
        The dispatch plan identifier.
    trace_id:
        Optional correlation trace ID.
    task_id:
        Optional task identifier.
    session_id:
        Source-side session identifier.
    source_device_id:
        Identifier of the source device.
    prior_mode:
        Mode evaluated before a fallback, if applicable.
    executor_target_type:
        Explicit executor target type from PR-E.
    target_device_id:
        Target device identifier for remote/mesh dispatch.
    has_mesh_session:
        Whether a mesh session was involved.
    has_handoff_envelope:
        Whether a handoff envelope was pre-built.
    has_continuity_context:
        Whether a continuity context was carried.
    decision_reason:
        Human-readable explanation of why this mode/target was selected.
    success:
        Whether the dispatch completed successfully.
    error_summary:
        Short error summary if failed.
    metadata:
        Optional arbitrary extensibility dict.

    Returns
    -------
    DispatchDecisionEvent or None
        The emitted event, or None if an error occurred.
    """
    try:
        evt = build_dispatch_decision_event(
            mode=mode,
            event_kind=event_kind,
            dispatch_id=dispatch_id,
            plan_id=plan_id,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            prior_mode=prior_mode,
            executor_target_type=executor_target_type,
            target_device_id=target_device_id,
            has_mesh_session=has_mesh_session,
            has_handoff_envelope=has_handoff_envelope,
            has_continuity_context=has_continuity_context,
            decision_reason=decision_reason,
            success=success,
            error_summary=error_summary,
            metadata=metadata,
        )
        logger.info(
            "dispatch_decision event_kind=%s mode=%s executor_target_type=%s "
            "decision_reason=%s success=%s trace_id=%s dispatch_id=%s event_id=%s",
            evt.event_kind,
            evt.mode,
            evt.executor_target_type,
            evt.decision_reason,
            evt.success,
            evt.trace_id,
            evt.dispatch_id,
            evt.event_id,
        )
        get_observability_sink().record_dispatch_decision_event(evt)
        return evt
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_dispatch_decision_event: suppressed error — %s", exc)
        return None


def emit_recovery_decision_event(
    decision_kind: "RecoveryDecisionKind | str",
    *,
    continuity_id: Optional[str] = None,
    prior_dispatch_id: Optional[str] = None,
    prior_session_id: Optional[str] = None,
    prior_mesh_session_id: Optional[str] = None,
    prior_task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    device_id: Optional[str] = None,
    interruption_class: str = "unknown",
    interruption_reason: str = "",
    is_resumable: bool = False,
    resume_attempt_count: int = 0,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[RecoveryDecisionEvent]:
    """Emit a structured recovery/reassociation decision event.

    Parameters
    ----------
    decision_kind:
        :class:`~contracts.runtime_observability.RecoveryDecisionKind` or string.
    continuity_id:
        The continuity context identifier.
    prior_dispatch_id:
        Dispatch ID of the interrupted execution.
    prior_session_id:
        Session ID from the interrupted execution.
    prior_mesh_session_id:
        Mesh session ID from the interrupted execution.
    prior_task_id:
        Task ID from the interrupted execution.
    trace_id:
        Correlation trace ID.
    device_id:
        Device ID involved in the recovery.
    interruption_class:
        The interruption class (``recoverable`` / ``terminal`` / ``unknown``).
    interruption_reason:
        Human-readable reason for the original interruption.
    is_resumable:
        Whether execution can be resumed.
    resume_attempt_count:
        Number of resume attempts made.
    reason:
        Human-readable explanation of why this recovery decision was made.
    metadata:
        Optional arbitrary extensibility dict.

    Returns
    -------
    RecoveryDecisionEvent or None
        The emitted event, or None if an error occurred.
    """
    try:
        evt = build_recovery_decision_event(
            decision_kind=decision_kind,
            continuity_id=continuity_id,
            prior_dispatch_id=prior_dispatch_id,
            prior_session_id=prior_session_id,
            prior_mesh_session_id=prior_mesh_session_id,
            prior_task_id=prior_task_id,
            trace_id=trace_id,
            device_id=device_id,
            interruption_class=interruption_class,
            interruption_reason=interruption_reason,
            is_resumable=is_resumable,
            resume_attempt_count=resume_attempt_count,
            reason=reason,
            metadata=metadata,
        )
        logger.info(
            "recovery_decision decision_kind=%s is_resumable=%s "
            "interruption_class=%s interruption_reason=%s reason=%s "
            "continuity_id=%s trace_id=%s event_id=%s",
            evt.decision_kind,
            evt.is_resumable,
            evt.interruption_class,
            evt.interruption_reason,
            evt.reason,
            evt.continuity_id,
            evt.trace_id,
            evt.event_id,
        )
        get_observability_sink().record_recovery_decision_event(evt)
        return evt
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_recovery_decision_event: suppressed error — %s", exc)
        return None


# ---------------------------------------------------------------------------
# Snapshot helper
# ---------------------------------------------------------------------------


def build_observability_snapshot() -> ObservabilitySnapshot:
    """Return a :class:`ObservabilitySnapshot` from the current global sink state."""
    return get_observability_sink().snapshot()


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY",
    "SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY",
    "SINK_IS_BOUNDED_POLICY",
    "RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL",
    # Constants
    "SINK_MAX_EVENTS_PER_KIND",
    # Classes
    "ObservabilitySnapshot",
    "RuntimeObservabilitySink",
    # Singleton management
    "get_observability_sink",
    "reset_observability_sink",
    # Emit helpers
    "emit_device_lifecycle_event",
    "emit_mesh_session_transition_event",
    "emit_dispatch_decision_event",
    "emit_recovery_decision_event",
    # Snapshot helper
    "build_observability_snapshot",
]
