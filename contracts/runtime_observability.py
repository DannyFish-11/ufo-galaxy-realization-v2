"""contracts/runtime_observability.py
======================================
Runtime Observability Contracts — PR-G.

This module defines the **canonical structured observability contracts** for
production-grade visibility into multi-device runtime state transitions and
dispatch decisions.  It answers the architectural question:

    *"How do operators and developers inspect what the runtime decided, why
    it decided it, and how state evolved across devices, sessions, and dispatch
    flows in production?"*

These contracts build on the prior contract chain:

- **PR-A** — device lifecycle and runtime wiring
- **PR-B** — mesh session runtime integration
- **PR-D** — source dispatch orchestrator production wiring
- **PR-E** — explicit executor target typing
- **PR-F** — dispatch continuity and recovery context

This module formalises:
- the device lifecycle event kind enum (:class:`DeviceLifecycleEventKind`);
- the structured device lifecycle event (:class:`DeviceLifecycleEvent`);
- the mesh session transition kind enum (:class:`MeshSessionTransitionKind`);
- the structured mesh session transition event (:class:`MeshSessionTransitionEvent`);
- the dispatch decision event kind enum (:class:`DispatchDecisionEventKind`);
- the structured dispatch decision event (:class:`DispatchDecisionEvent`);
- the recovery decision kind enum (:class:`RecoveryDecisionKind`);
- the structured recovery decision event (:class:`RecoveryDecisionEvent`);
- builder functions for all event types.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``from_dict``.
- **Graceful defaults** — all fields beyond required identity fields are
  optional; callers with partial context always produce a valid event.
- **Backward compatible** — all fields are optional beyond required keys.
- **Structured, not ad-hoc** — every event carries a stable ``event_kind``
  string, a ``trace_id`` correlation field, timestamps, and a human-readable
  ``reason`` that explains the decision without requiring source-code inspection.

Sentinels
---------
:data:`RUNTIME_OBSERVABILITY_IS_AUTHORITY`
    Affirms this module is the canonical structured observability contracts
    authority for PR-G.
:data:`DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY`
    Affirms that device lifecycle state changes emit structured events.
:data:`MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY`
    Affirms that mesh session lifecycle transitions emit structured events.
:data:`DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY`
    Affirms that dispatch plan selection emits a structured event with the
    reason why a mode was chosen.
:data:`RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY`
    Affirms that recovery/reassociation vs terminal-loss decisions emit
    structured events with enough context to correlate them to prior state.

Usage::

    from contracts.runtime_observability import (
        DeviceLifecycleEventKind,
        DeviceLifecycleEvent,
        MeshSessionTransitionKind,
        MeshSessionTransitionEvent,
        DispatchDecisionEventKind,
        DispatchDecisionEvent,
        RecoveryDecisionKind,
        RecoveryDecisionEvent,
        build_device_lifecycle_event,
        build_mesh_session_transition_event,
        build_dispatch_decision_event,
        build_recovery_decision_event,
    )

    evt = build_device_lifecycle_event(
        device_id="android_01",
        event_kind=DeviceLifecycleEventKind.attach,
        reason="device_registered_with_join_runtime_posture",
    )
    print(evt.to_dict())
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

RUNTIME_OBSERVABILITY_IS_AUTHORITY: str = (
    "RUNTIME_OBSERVABILITY_IS_AUTHORITY: "
    "contracts/runtime_observability.py is the canonical structured observability "
    "contracts authority for PR-G.  It defines event types for device lifecycle, "
    "mesh session transitions, dispatch decisions, and recovery decisions.  "
    "All production-observable runtime state transition records MUST conform to "
    "these contracts."
)

DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY: str = (
    "POLICY::DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_PR-G: "
    "Device lifecycle state changes (attach, detach, reconnect, readiness_change, "
    "degraded, lost) MUST be emitted as structured DeviceLifecycleEvent records.  "
    "Ad-hoc log strings are insufficient for production observability.  Each event "
    "MUST carry a stable event_kind, device_id, trace_id, timestamp, and a "
    "human-readable reason explaining why the transition occurred.  PR-G."
)

MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY: str = (
    "POLICY::MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_PR-G: "
    "Mesh session lifecycle transitions (create, activate, suspend, restore, "
    "terminate) MUST be emitted as structured MeshSessionTransitionEvent records "
    "so that operators can trace the full session lifecycle in production.  "
    "Each event MUST carry session_id, transition_kind, prior_status, new_status, "
    "and a reason explaining why the transition was triggered.  PR-G."
)

DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY: str = (
    "POLICY::DISPATCH_DECISIONS_ARE_EXPLAINABLE_PR-G: "
    "Source dispatch plan selection MUST emit a structured DispatchDecisionEvent "
    "that captures the selected mode (local / remote_handoff / fallback_local / "
    "staged_mesh), the selected executor target type, and the decision_reason "
    "explaining why this mode was chosen over alternatives.  This makes routing "
    "decisions inspectable without reading source code.  PR-G."
)

RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY: str = (
    "POLICY::RECOVERY_DECISIONS_ARE_TRACEABLE_PR-G: "
    "Recovery/reassociation vs terminal-loss decisions MUST emit structured "
    "RecoveryDecisionEvent records.  Each event MUST carry the continuity_id, "
    "prior_dispatch_id, prior_session_id, decision_kind (resumable_reassociation / "
    "terminal_loss / recovery_fallback), and a reason.  This makes recovery "
    "path selection observable without ad-hoc log inspection.  PR-G."
)

RUNTIME_OBSERVABILITY_PR_G_SENTINEL: str = (
    "RUNTIME_OBSERVABILITY_PR_G_SENTINEL: "
    "PR-G structured runtime observability contracts are present and active.  "
    "Structured events for device lifecycle, mesh session transitions, dispatch "
    "decisions, and recovery decisions are defined and ready to be emitted by "
    "the runtime observability sink."
)


# TODO(PR-RUNTIME-TRACE): This module defines structured observability event
# contracts but does not itself emit events.  All builder functions in this
# module are called by upstream producers; there is no central registration
# or automatic emission.  Future work: add a canonical event bus adapter so
# that DeviceLifecycleEvent / MeshSessionTransitionEvent / DispatchDecisionEvent
# / RecoveryDecisionEvent objects produced here are automatically routed to
# core.runtime.runtime_observability_sink without requiring every caller to
# manually call emit().  This prevents observability gaps in the production
# path when a new caller forgets to instrument.

# ---------------------------------------------------------------------------
# DeviceLifecycleEventKind
# ---------------------------------------------------------------------------


class DeviceLifecycleEventKind(str, Enum):
    """Stable enum of device lifecycle event kinds.

    Values are lowercase strings safe for serialisation, counter keys, and
    policy analysis.
    """

    attach = "attach"
    """Device successfully attached as a runtime participant."""

    detach = "detach"
    """Device explicitly detached from the runtime."""

    reconnect = "reconnect"
    """Device reconnected after a disconnect."""

    readiness_change = "readiness_change"
    """Device readiness state changed (e.g. degraded → ready)."""

    degraded = "degraded"
    """Device entered degraded state; health score dropped below threshold."""

    lost = "lost"
    """Device is unreachable / lost; declared non-participant."""

    heartbeat_miss = "heartbeat_miss"
    """Device missed expected heartbeat; may indicate connectivity issue."""

    unknown = "unknown"
    """Unrecognised event kind — should not occur in production."""


# ---------------------------------------------------------------------------
# DeviceLifecycleEvent
# ---------------------------------------------------------------------------


@dataclass
class DeviceLifecycleEvent:
    """A single structured device lifecycle event.

    Emitted whenever a device transitions between lifecycle states in the
    multi-device runtime.  Consumers should read from this event rather than
    inferring device state from logs or raw health signals.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    event_kind:
        :class:`DeviceLifecycleEventKind` value describing what happened.
    device_id:
        Identifier of the device whose lifecycle changed.
    trace_id:
        Correlation trace ID for the originating request or session.
    session_id:
        Active session identifier, if available.
    mesh_session_id:
        Active mesh session identifier, if available.
    formation_id:
        Active formation identifier, if available.
    prior_state:
        The lifecycle/attachment state before this transition, if known.
    new_state:
        The lifecycle/attachment state after this transition.
    readiness:
        Readiness string (``"ready"``, ``"degraded"``, ``"lost"``,
        ``"recovering"``) when event_kind is ``readiness_change``.
    health_score:
        Normalised health score ``[0.0, 1.0]`` when available.
    reason:
        Human-readable explanation of why this event occurred.
    metadata:
        Arbitrary key-value extensibility bag.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    event_kind: str = DeviceLifecycleEventKind.unknown.value
    device_id: str = ""
    trace_id: Optional[str] = None
    session_id: Optional[str] = None
    mesh_session_id: Optional[str] = None
    formation_id: Optional[str] = None
    prior_state: Optional[str] = None
    new_state: Optional[str] = None
    readiness: Optional[str] = None
    health_score: Optional[float] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_kind": self.event_kind,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "mesh_session_id": self.mesh_session_id,
            "formation_id": self.formation_id,
            "prior_state": self.prior_state,
            "new_state": self.new_state,
            "readiness": self.readiness,
            "health_score": self.health_score,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DeviceLifecycleEvent":
        """Reconstruct a :class:`DeviceLifecycleEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            event_kind=str(d.get("event_kind") or DeviceLifecycleEventKind.unknown.value),
            device_id=str(d.get("device_id") or ""),
            trace_id=d.get("trace_id"),
            session_id=d.get("session_id"),
            mesh_session_id=d.get("mesh_session_id"),
            formation_id=d.get("formation_id"),
            prior_state=d.get("prior_state"),
            new_state=d.get("new_state"),
            readiness=d.get("readiness"),
            health_score=float(d["health_score"]) if d.get("health_score") is not None else None,
            reason=str(d.get("reason") or ""),
            metadata=dict(d.get("metadata") or {}),
        )

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# MeshSessionTransitionKind
# ---------------------------------------------------------------------------


class MeshSessionTransitionKind(str, Enum):
    """Stable enum of mesh session lifecycle transition kinds."""

    create = "create"
    """A new mesh session was created (status → PENDING)."""

    activate = "activate"
    """Session transitioned to ACTIVE."""

    suspend = "suspend"
    """Session transitioned to SUSPENDED."""

    restore = "restore"
    """Session restored from SUSPENDED → RESTORING → ACTIVE."""

    terminate = "terminate"
    """Session reached a terminal state (COMPLETED / CANCELLED / FAILED)."""

    participant_joined = "participant_joined"
    """A new device participant joined the session."""

    participant_left = "participant_left"
    """A device participant left or was removed from the session."""

    unknown = "unknown"
    """Unrecognised transition kind."""


# ---------------------------------------------------------------------------
# MeshSessionTransitionEvent
# ---------------------------------------------------------------------------


@dataclass
class MeshSessionTransitionEvent:
    """A single structured mesh session lifecycle transition event.

    Emitted on every lifecycle mutation of a :class:`~contracts.mesh_session.MeshSession`
    managed by the lifecycle coordinator.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    transition_kind:
        :class:`MeshSessionTransitionKind` value describing what happened.
    session_id:
        The mesh session identifier.
    mesh_id:
        Optional mesh/body identifier for multi-mesh environments.
    trace_id:
        Correlation trace ID.
    task_id:
        Optional task identifier for the execution this session serves.
    prior_status:
        The session status before this transition.
    new_status:
        The session status after this transition.
    source_device_id:
        Device that initiated this session (or triggered the transition).
    primary_device_id:
        Primary executor device for this session.
    participant_device_id:
        Device involved in a participant_joined/participant_left transition.
    participant_count:
        Number of participants after the transition.
    reason:
        Human-readable explanation of why this transition occurred.
    restore_count:
        Number of times this session has been restored (relevant for restore events).
    metadata:
        Arbitrary key-value extensibility bag.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    transition_kind: str = MeshSessionTransitionKind.unknown.value
    session_id: str = ""
    mesh_id: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    prior_status: Optional[str] = None
    new_status: Optional[str] = None
    source_device_id: Optional[str] = None
    primary_device_id: Optional[str] = None
    participant_device_id: Optional[str] = None
    participant_count: int = 0
    reason: str = ""
    restore_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "transition_kind": self.transition_kind,
            "session_id": self.session_id,
            "mesh_id": self.mesh_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "prior_status": self.prior_status,
            "new_status": self.new_status,
            "source_device_id": self.source_device_id,
            "primary_device_id": self.primary_device_id,
            "participant_device_id": self.participant_device_id,
            "participant_count": self.participant_count,
            "reason": self.reason,
            "restore_count": self.restore_count,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MeshSessionTransitionEvent":
        """Reconstruct a :class:`MeshSessionTransitionEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            transition_kind=str(d.get("transition_kind") or MeshSessionTransitionKind.unknown.value),
            session_id=str(d.get("session_id") or ""),
            mesh_id=d.get("mesh_id"),
            trace_id=d.get("trace_id"),
            task_id=d.get("task_id"),
            prior_status=d.get("prior_status"),
            new_status=d.get("new_status"),
            source_device_id=d.get("source_device_id"),
            primary_device_id=d.get("primary_device_id"),
            participant_device_id=d.get("participant_device_id"),
            participant_count=int(d.get("participant_count") or 0),
            reason=str(d.get("reason") or ""),
            restore_count=int(d.get("restore_count") or 0),
            metadata=dict(d.get("metadata") or {}),
        )

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# DispatchDecisionEventKind
# ---------------------------------------------------------------------------


class DispatchDecisionEventKind(str, Enum):
    """Stable enum of dispatch decision event kinds."""

    plan_selected = "plan_selected"
    """A dispatch plan was selected (mode chosen, target resolved)."""

    target_routed = "target_routed"
    """An executor target was resolved and routed to."""

    fallback_triggered = "fallback_triggered"
    """Dispatch fell back to a fallback mode (e.g. fallback_local)."""

    plan_blocked = "plan_blocked"
    """Dispatch was blocked (no eligible target, policy denial, etc.)."""

    orchestration_complete = "orchestration_complete"
    """End-to-end orchestration completed (success or failure)."""

    unknown = "unknown"
    """Unrecognised event kind."""


# ---------------------------------------------------------------------------
# DispatchDecisionEvent
# ---------------------------------------------------------------------------


@dataclass
class DispatchDecisionEvent:
    """A single structured dispatch decision event.

    Emitted whenever the source dispatch orchestrator selects a dispatch
    mode and executor target.  Makes dispatch routing decisions observable
    without requiring source-code inspection.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    event_kind:
        :class:`DispatchDecisionEventKind` value.
    dispatch_id:
        The dispatch decision identifier.
    plan_id:
        The dispatch plan identifier, if a plan was built.
    trace_id:
        Correlation trace ID.
    task_id:
        Task identifier, if available.
    session_id:
        Source-side session identifier, if available.
    source_device_id:
        Identifier of the source device making the dispatch decision.
    mode:
        The dispatch mode selected (``local`` / ``remote_handoff`` /
        ``fallback_local`` / ``staged_mesh`` / ``blocked`` / ``unknown``).
    prior_mode:
        The mode that was evaluated before a fallback, if applicable.
    executor_target_type:
        Explicit executor target type (from PR-E), if applicable.
    target_device_id:
        Target device identifier, if a remote or mesh target was chosen.
    has_mesh_session:
        Whether a mesh session was involved in this dispatch decision.
    has_handoff_envelope:
        Whether a handoff envelope was pre-built for this dispatch.
    has_continuity_context:
        Whether a continuity context was carried into this dispatch.
    decision_reason:
        Human-readable explanation of why this mode/target was selected.
    success:
        Whether the dispatch completed successfully.
    error_summary:
        Short error summary if the dispatch failed.
    metadata:
        Arbitrary key-value extensibility bag.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    event_kind: str = DispatchDecisionEventKind.plan_selected.value
    dispatch_id: Optional[str] = None
    plan_id: Optional[str] = None
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    source_device_id: Optional[str] = None
    mode: str = "unknown"
    prior_mode: Optional[str] = None
    executor_target_type: Optional[str] = None
    target_device_id: Optional[str] = None
    has_mesh_session: bool = False
    has_handoff_envelope: bool = False
    has_continuity_context: bool = False
    decision_reason: str = ""
    success: bool = False
    error_summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_kind": self.event_kind,
            "dispatch_id": self.dispatch_id,
            "plan_id": self.plan_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "source_device_id": self.source_device_id,
            "mode": self.mode,
            "prior_mode": self.prior_mode,
            "executor_target_type": self.executor_target_type,
            "target_device_id": self.target_device_id,
            "has_mesh_session": self.has_mesh_session,
            "has_handoff_envelope": self.has_handoff_envelope,
            "has_continuity_context": self.has_continuity_context,
            "decision_reason": self.decision_reason,
            "success": self.success,
            "error_summary": self.error_summary,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DispatchDecisionEvent":
        """Reconstruct a :class:`DispatchDecisionEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            event_kind=str(d.get("event_kind") or DispatchDecisionEventKind.plan_selected.value),
            dispatch_id=d.get("dispatch_id"),
            plan_id=d.get("plan_id"),
            trace_id=d.get("trace_id"),
            task_id=d.get("task_id"),
            session_id=d.get("session_id"),
            source_device_id=d.get("source_device_id"),
            mode=str(d.get("mode") or "unknown"),
            prior_mode=d.get("prior_mode"),
            executor_target_type=d.get("executor_target_type"),
            target_device_id=d.get("target_device_id"),
            has_mesh_session=bool(d.get("has_mesh_session", False)),
            has_handoff_envelope=bool(d.get("has_handoff_envelope", False)),
            has_continuity_context=bool(d.get("has_continuity_context", False)),
            decision_reason=str(d.get("decision_reason") or ""),
            success=bool(d.get("success", False)),
            error_summary=d.get("error_summary"),
            metadata=dict(d.get("metadata") or {}),
        )

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# RecoveryDecisionKind
# ---------------------------------------------------------------------------


class RecoveryDecisionKind(str, Enum):
    """Stable enum of recovery/reassociation decision kinds.

    Distinguishes recoverable reassociation scenarios from terminal loss
    decisions so that recovery path selection is observable.
    """

    resumable_reassociation = "resumable_reassociation"
    """Execution can be resumed; prior session/dispatch context is intact."""

    recovery_fallback = "recovery_fallback"
    """Execution resumes with a new dispatch cycle; prior context partially used."""

    terminal_loss = "terminal_loss"
    """Execution cannot be resumed; prior context is discarded."""

    unknown = "unknown"
    """Unrecognised recovery decision kind."""


# ---------------------------------------------------------------------------
# RecoveryDecisionEvent
# ---------------------------------------------------------------------------


@dataclass
class RecoveryDecisionEvent:
    """A single structured recovery/reassociation decision event.

    Emitted whenever the runtime makes a recovery decision: whether a
    recoverable interruption can be resumed via reassociation, whether
    it falls back to a new dispatch cycle, or whether execution is
    terminally lost.

    Attributes
    ----------
    event_id:
        Auto-generated UUID for this event.
    timestamp:
        Unix timestamp when the event was created.
    decision_kind:
        :class:`RecoveryDecisionKind` value describing the outcome.
    continuity_id:
        The :class:`~contracts.dispatch_continuity.DispatchContinuityContext`
        identifier linking this recovery to the prior dispatch cycle.
    prior_dispatch_id:
        Dispatch ID of the interrupted execution.
    prior_session_id:
        Session ID from the interrupted execution.
    prior_mesh_session_id:
        Mesh session ID from the interrupted execution, if applicable.
    prior_task_id:
        Task ID from the interrupted execution.
    trace_id:
        Correlation trace ID.
    device_id:
        Device ID involved in the recovery (e.g. reconnecting device).
    interruption_class:
        The interruption class that triggered this recovery decision
        (``recoverable`` / ``terminal`` / ``unknown``).
    interruption_reason:
        Human-readable reason for the original interruption.
    is_resumable:
        Whether the execution can be resumed (False for terminal_loss).
    resume_attempt_count:
        Number of resume attempts that have been made.
    reason:
        Human-readable explanation of why this recovery decision was made.
    metadata:
        Arbitrary key-value extensibility bag.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    decision_kind: str = RecoveryDecisionKind.unknown.value
    continuity_id: Optional[str] = None
    prior_dispatch_id: Optional[str] = None
    prior_session_id: Optional[str] = None
    prior_mesh_session_id: Optional[str] = None
    prior_task_id: Optional[str] = None
    trace_id: Optional[str] = None
    device_id: Optional[str] = None
    interruption_class: str = "unknown"
    interruption_reason: str = ""
    is_resumable: bool = False
    resume_attempt_count: int = 0
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "decision_kind": self.decision_kind,
            "continuity_id": self.continuity_id,
            "prior_dispatch_id": self.prior_dispatch_id,
            "prior_session_id": self.prior_session_id,
            "prior_mesh_session_id": self.prior_mesh_session_id,
            "prior_task_id": self.prior_task_id,
            "trace_id": self.trace_id,
            "device_id": self.device_id,
            "interruption_class": self.interruption_class,
            "interruption_reason": self.interruption_reason,
            "is_resumable": self.is_resumable,
            "resume_attempt_count": self.resume_attempt_count,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RecoveryDecisionEvent":
        """Reconstruct a :class:`RecoveryDecisionEvent` from a plain dict."""
        return cls(
            event_id=str(d.get("event_id") or uuid.uuid4().hex),
            timestamp=float(d.get("timestamp") or time.time()),
            decision_kind=str(d.get("decision_kind") or RecoveryDecisionKind.unknown.value),
            continuity_id=d.get("continuity_id"),
            prior_dispatch_id=d.get("prior_dispatch_id"),
            prior_session_id=d.get("prior_session_id"),
            prior_mesh_session_id=d.get("prior_mesh_session_id"),
            prior_task_id=d.get("prior_task_id"),
            trace_id=d.get("trace_id"),
            device_id=d.get("device_id"),
            interruption_class=str(d.get("interruption_class") or "unknown"),
            interruption_reason=str(d.get("interruption_reason") or ""),
            is_resumable=bool(d.get("is_resumable", False)),
            resume_attempt_count=int(d.get("resume_attempt_count") or 0),
            reason=str(d.get("reason") or ""),
            metadata=dict(d.get("metadata") or {}),
        )

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_device_lifecycle_event(
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
) -> DeviceLifecycleEvent:
    """Build a :class:`DeviceLifecycleEvent` from available context.

    Parameters
    ----------
    device_id:
        Identifier of the device whose lifecycle changed.
    event_kind:
        :class:`DeviceLifecycleEventKind` or string value describing what happened.
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
    DeviceLifecycleEvent
    """
    kind_str = event_kind.value if isinstance(event_kind, DeviceLifecycleEventKind) else str(event_kind)
    return DeviceLifecycleEvent(
        event_kind=kind_str,
        device_id=str(device_id),
        trace_id=trace_id,
        session_id=session_id,
        mesh_session_id=mesh_session_id,
        formation_id=formation_id,
        prior_state=prior_state,
        new_state=new_state,
        readiness=readiness,
        health_score=health_score,
        reason=reason or "",
        metadata=dict(metadata) if metadata else {},
    )


def build_mesh_session_transition_event(
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
) -> MeshSessionTransitionEvent:
    """Build a :class:`MeshSessionTransitionEvent` from available context.

    Parameters
    ----------
    session_id:
        The mesh session identifier.
    transition_kind:
        :class:`MeshSessionTransitionKind` or string value.
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
    MeshSessionTransitionEvent
    """
    kind_str = transition_kind.value if isinstance(transition_kind, MeshSessionTransitionKind) else str(transition_kind)
    return MeshSessionTransitionEvent(
        transition_kind=kind_str,
        session_id=str(session_id),
        mesh_id=mesh_id,
        trace_id=trace_id,
        task_id=task_id,
        prior_status=prior_status,
        new_status=new_status,
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        participant_device_id=participant_device_id,
        participant_count=participant_count,
        reason=reason or "",
        restore_count=restore_count,
        metadata=dict(metadata) if metadata else {},
    )


def build_dispatch_decision_event(
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
) -> DispatchDecisionEvent:
    """Build a :class:`DispatchDecisionEvent` from available dispatch context.

    Parameters
    ----------
    mode:
        The dispatch mode selected (``local`` / ``remote_handoff`` /
        ``fallback_local`` / ``staged_mesh`` / ``blocked`` / ``unknown``).
    event_kind:
        :class:`DispatchDecisionEventKind` or string value.
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
        Identifier of the source device making the dispatch decision.
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
    DispatchDecisionEvent
    """
    kind_str = event_kind.value if isinstance(event_kind, DispatchDecisionEventKind) else str(event_kind)
    return DispatchDecisionEvent(
        event_kind=kind_str,
        dispatch_id=dispatch_id,
        plan_id=plan_id,
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        source_device_id=source_device_id,
        mode=str(mode),
        prior_mode=prior_mode,
        executor_target_type=executor_target_type,
        target_device_id=target_device_id,
        has_mesh_session=has_mesh_session,
        has_handoff_envelope=has_handoff_envelope,
        has_continuity_context=has_continuity_context,
        decision_reason=decision_reason or "",
        success=success,
        error_summary=error_summary,
        metadata=dict(metadata) if metadata else {},
    )


def build_recovery_decision_event(
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
) -> RecoveryDecisionEvent:
    """Build a :class:`RecoveryDecisionEvent` from available recovery context.

    Parameters
    ----------
    decision_kind:
        :class:`RecoveryDecisionKind` or string describing the outcome.
    continuity_id:
        The continuity context identifier linking to the prior dispatch cycle.
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
    RecoveryDecisionEvent
    """
    kind_str = decision_kind.value if isinstance(decision_kind, RecoveryDecisionKind) else str(decision_kind)
    return RecoveryDecisionEvent(
        decision_kind=kind_str,
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
        reason=reason or "",
        metadata=dict(metadata) if metadata else {},
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "RUNTIME_OBSERVABILITY_IS_AUTHORITY",
    "DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY",
    "MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY",
    "DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY",
    "RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY",
    "RUNTIME_OBSERVABILITY_PR_G_SENTINEL",
    # Enums
    "DeviceLifecycleEventKind",
    "MeshSessionTransitionKind",
    "DispatchDecisionEventKind",
    "RecoveryDecisionKind",
    # Dataclasses
    "DeviceLifecycleEvent",
    "MeshSessionTransitionEvent",
    "DispatchDecisionEvent",
    "RecoveryDecisionEvent",
    # Builders
    "build_device_lifecycle_event",
    "build_mesh_session_transition_event",
    "build_dispatch_decision_event",
    "build_recovery_decision_event",
]
