"""contracts/execution_trace.py
================================
Execution Trace Contract — canonical execution lifecycle trace schema.

PR-25: Execution Trace Contract

This module defines the **unified Execution Trace Contract**: a serialisable,
wire-safe schema that standardises how execution-related lifecycle events are
represented and passed across the Galaxy system.

The trace contract answers:
- What execution lifecycle event is this?
- Which request / session / intent / fallback decision does it belong to?
- What stable fields can downstream modules (runtime, governance, projection,
  status surfaces) rely on?

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible with PR-22/23/24.
- **Fully serialisable** — :meth:`ExecutionTraceEvent.to_dict` and
  :meth:`ExecutionTraceEvent.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond the minimal required set are
  optional; callers with partial metadata can always build a valid event.
- **Tolerant of missing metadata** — builder functions catch exceptions and
  degrade gracefully; they never raise to the caller.

Usage::

    from contracts.execution_trace import (
        ExecutionTraceStage,
        ExecutionTraceStatus,
        ExecutionTraceEvent,
        ExecutionTraceEnvelope,
        from_execution_intent,
        from_readiness_result,
        from_fallback_trace,
        from_execution_result,
        build_trace_envelope,
    )

    # Build a trace event from an intent profile (PR-22)
    event = from_execution_intent(intent_profile, runtime_session_id="sess-abc")

    # Build a full envelope covering one execution lifecycle
    envelope = build_trace_envelope(
        intent_profile=profile,
        readiness_result=readiness,
        fallback_trace=fallback,
        execution_result=exec_result,
    )
    payload = envelope.to_dict()

See ``docs/EXECUTION_TRACE_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ExecutionTraceStage — canonical lifecycle stage vocabulary
# ---------------------------------------------------------------------------


class ExecutionTraceStage(str, Enum):
    """Canonical lifecycle stages that can appear in an execution trace.

    Each stage corresponds to a distinct point in the execution lifecycle:

    intent_created
        An :class:`~core.execution.intent_profile.ExecutionIntentProfile` was
        constructed; this is the first observable trace point in a lifecycle.

    readiness_evaluated
        The :class:`~core.execution.readiness_gate.ExecutionReadinessGate`
        (PR-23) evaluated the intent and produced a
        :class:`~core.execution.readiness_gate.ReadinessResult`.

    fallback_selected
        The fallback routing layer (PR-24) decided on a fallback path (or
        confirmed that the primary path was used / unavailable).

    execution_started
        The executor was invoked; the action is in flight.

    execution_finished
        Execution completed (with success or failure); the result is available.

    execution_blocked
        Execution was blocked before or during dispatch (by policy, readiness
        gate, missing executor, or runtime error).
    """

    INTENT_CREATED = "intent_created"
    READINESS_EVALUATED = "readiness_evaluated"
    FALLBACK_SELECTED = "fallback_selected"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_FINISHED = "execution_finished"
    EXECUTION_BLOCKED = "execution_blocked"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionTraceStage":
        """Return the matching member, falling back to ``EXECUTION_BLOCKED`` on unknown input."""
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.EXECUTION_BLOCKED


# ---------------------------------------------------------------------------
# ExecutionTraceStatus — canonical event status vocabulary
# ---------------------------------------------------------------------------


class ExecutionTraceStatus(str, Enum):
    """Canonical status values for a single execution trace event.

    pending
        The lifecycle stage is in progress; no final determination yet.
    success
        The stage completed successfully.
    failed
        The stage or the overall execution failed.
    blocked
        Execution was blocked at this stage (by policy, gate, or runtime).
    degraded
        The stage completed but at reduced capability (fallback path was used).
    skipped
        The stage was skipped (e.g. readiness gate not consulted for a
        no-op intent).
    """

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    SKIPPED = "skipped"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionTraceStatus":
        """Return the matching member, falling back to ``PENDING`` on unknown input."""
        normalised = (value or "").strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.PENDING


# ---------------------------------------------------------------------------
# ExecutionTraceEvent — canonical single lifecycle event
# ---------------------------------------------------------------------------


class ExecutionTraceEvent(BaseModel):
    """Canonical, wire-safe execution trace event.

    Represents a single point in the execution lifecycle.  A full execution
    run typically produces several events (one per :class:`ExecutionTraceStage`),
    all sharing the same ``trace_id`` and ``intent_id``.

    Fields
    ------
    trace_id
        Unique identifier for this trace event (UUID4).  Events belonging to
        the same trace envelope share the same ``trace_id``.
    event_id
        Unique identifier for this specific event within the trace (UUID4).
        Distinct from ``trace_id`` — useful for deduplication.
    runtime_session_id
        Active runtime / OpenClawd session ID.  ``None`` when unavailable.
    intent_id
        ID of the
        :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        that originated this trace.  ``None`` when unavailable.
    stage
        Lifecycle stage this event represents
        (:class:`ExecutionTraceStage` value string).
    status
        Outcome status for this stage
        (:class:`ExecutionTraceStatus` value string).
    action_level
        Graduated action level from the Decision Gate
        (``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``).
    runtime_domain
        Runtime domain string (``"local"`` / ``"cross_device"`` /
        ``"transition"``).  ``None`` when unresolved.
    target_ref
        Compact execution target reference (app name, window title, device
        ID, command, …).  ``None`` when no target is identified.
    reason
        Human-readable explanation of the stage outcome (especially for
        ``blocked`` / ``failed`` / ``degraded`` events).  ``None`` for
        unambiguous success events.
    source
        Originating component or subsystem
        (e.g. ``"openclawd"``, ``"readiness_gate"``, ``"fallback_router"``).
    timestamp
        Unix timestamp (seconds since epoch) when this event was created.
    details
        Narrow, additive, optional dict of structured metadata for this
        event.  Downstream code should treat this as informational only;
        never depend on specific keys being present.
    """

    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Shared trace identifier for all events in one lifecycle run.",
    )
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this specific trace event.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Active runtime / OpenClawd session ID.",
    )
    intent_id: Optional[str] = Field(
        default=None,
        description="ExecutionIntentProfile ID that originated this trace.",
    )
    stage: str = Field(
        default=ExecutionTraceStage.INTENT_CREATED.value,
        description="Lifecycle stage (intent_created / readiness_evaluated / … / execution_blocked).",
    )
    status: str = Field(
        default=ExecutionTraceStatus.PENDING.value,
        description="Outcome status for this stage (pending / success / failed / blocked / degraded / skipped).",
    )
    action_level: str = Field(
        default="observe",
        description="Graduated action level from the Decision Gate.",
    )
    runtime_domain: Optional[str] = Field(
        default=None,
        description="Runtime domain string (local / cross_device / transition).",
    )
    target_ref: Optional[str] = Field(
        default=None,
        description="Compact execution target reference.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the stage outcome.",
    )
    source: str = Field(
        default="openclawd",
        description="Originating component (openclawd / readiness_gate / fallback_router / …).",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds since epoch) when this event was created.",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Narrow, optional structured metadata for this event.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    def compact_summary(self) -> Dict[str, Any]:
        """Return a narrow projection-safe summary for status surfaces."""
        return {
            "trace_id": self.trace_id,
            "event_id": self.event_id,
            "stage": self.stage,
            "status": self.status,
            "action_level": self.action_level,
            "intent_id": self.intent_id,
            "runtime_session_id": self.runtime_session_id,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# ExecutionTraceEnvelope — container for a complete lifecycle trace
# ---------------------------------------------------------------------------


class ExecutionTraceEnvelope(BaseModel):
    """Container for all trace events produced by a single execution lifecycle run.

    An envelope collects the events emitted at each stage of one execution
    request so that consumers can inspect the complete lifecycle in one object.

    Fields
    ------
    trace_id
        Shared identifier for all events in this envelope (UUID4).  All
        :class:`ExecutionTraceEvent` objects in :attr:`events` carry the same
        ``trace_id``.
    runtime_session_id
        Active runtime / OpenClawd session ID.  ``None`` when unavailable.
    intent_id
        ID of the originating
        :class:`~core.execution.intent_profile.ExecutionIntentProfile`.
        ``None`` when unavailable.
    events
        Ordered list of :class:`ExecutionTraceEvent` objects, one per
        stage reached during this lifecycle run.
    final_status
        Aggregate final status across all events
        (:class:`ExecutionTraceStatus` value string).  Derived from the
        last substantive event when not explicitly set.
    created_at
        Unix timestamp (seconds since epoch) when the envelope was created.
    """

    trace_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Shared trace identifier for all events in this envelope.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Active runtime / OpenClawd session ID.",
    )
    intent_id: Optional[str] = Field(
        default=None,
        description="ExecutionIntentProfile ID that originated this lifecycle.",
    )
    events: List[ExecutionTraceEvent] = Field(
        default_factory=list,
        description="Ordered list of trace events, one per lifecycle stage.",
    )
    final_status: str = Field(
        default=ExecutionTraceStatus.PENDING.value,
        description="Aggregate final status across all events.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds since epoch) when the envelope was created.",
    )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def append(self, event: ExecutionTraceEvent) -> None:
        """Append *event* to :attr:`events` and update :attr:`final_status`."""
        self.events.append(event)
        # Update final_status based on the most recent substantive outcome
        if event.status not in (
            ExecutionTraceStatus.PENDING.value,
            ExecutionTraceStatus.SKIPPED.value,
        ):
            self.final_status = event.status

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        d = self.model_dump()
        d["events"] = [e.to_dict() for e in self.events]
        return d

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    def compact_summary(self) -> Dict[str, Any]:
        """Return a narrow projection-safe summary for status surfaces."""
        return {
            "trace_id": self.trace_id,
            "intent_id": self.intent_id,
            "runtime_session_id": self.runtime_session_id,
            "final_status": self.final_status,
            "stage_count": len(self.events),
            "stages": [e.stage for e in self.events],
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Builder functions — from_* adapters
# ---------------------------------------------------------------------------


def from_execution_intent(
    intent_profile: Any,
    *,
    trace_id: Optional[str] = None,
    source: str = "openclawd",
) -> ExecutionTraceEvent:
    """Build an ``intent_created`` :class:`ExecutionTraceEvent` from an intent profile.

    Parameters
    ----------
    intent_profile:
        An :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (or any object with compatible attributes).  ``None`` is tolerated.
    trace_id:
        Shared trace ID to use.  A new UUID4 is generated when ``None``.
    source:
        Originating component identifier.

    Returns
    -------
    ExecutionTraceEvent
        Always returns a valid event; never raises.
    """
    try:
        return _build_intent_event(intent_profile, trace_id=trace_id, source=source)
    except Exception:
        return ExecutionTraceEvent(
            trace_id=trace_id or str(uuid.uuid4()),
            stage=ExecutionTraceStage.INTENT_CREATED.value,
            status=ExecutionTraceStatus.PENDING.value,
            source=source,
        )


def from_readiness_result(
    readiness_result: Any,
    *,
    intent_profile: Optional[Any] = None,
    trace_id: Optional[str] = None,
    source: str = "readiness_gate",
) -> ExecutionTraceEvent:
    """Build a ``readiness_evaluated`` :class:`ExecutionTraceEvent` from a readiness result.

    Parameters
    ----------
    readiness_result:
        A :class:`~core.execution.readiness_gate.ReadinessResult`
        (or any object with compatible attributes).  ``None`` is tolerated.
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        for supplementary field extraction.
    trace_id:
        Shared trace ID to use.  A new UUID4 is generated when ``None``.
    source:
        Originating component identifier.

    Returns
    -------
    ExecutionTraceEvent
        Always returns a valid event; never raises.
    """
    try:
        return _build_readiness_event(
            readiness_result,
            intent_profile=intent_profile,
            trace_id=trace_id,
            source=source,
        )
    except Exception:
        return ExecutionTraceEvent(
            trace_id=trace_id or str(uuid.uuid4()),
            stage=ExecutionTraceStage.READINESS_EVALUATED.value,
            status=ExecutionTraceStatus.PENDING.value,
            source=source,
        )


def from_fallback_trace(
    fallback_trace: Any,
    *,
    intent_profile: Optional[Any] = None,
    trace_id: Optional[str] = None,
    source: str = "fallback_router",
) -> ExecutionTraceEvent:
    """Build a ``fallback_selected`` :class:`ExecutionTraceEvent` from a fallback decision trace.

    Parameters
    ----------
    fallback_trace:
        A :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
        (or any object with compatible attributes).  ``None`` is tolerated.
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        for supplementary field extraction.
    trace_id:
        Shared trace ID to use.  A new UUID4 is generated when ``None``.
    source:
        Originating component identifier.

    Returns
    -------
    ExecutionTraceEvent
        Always returns a valid event; never raises.
    """
    try:
        return _build_fallback_event(
            fallback_trace,
            intent_profile=intent_profile,
            trace_id=trace_id,
            source=source,
        )
    except Exception:
        return ExecutionTraceEvent(
            trace_id=trace_id or str(uuid.uuid4()),
            stage=ExecutionTraceStage.FALLBACK_SELECTED.value,
            status=ExecutionTraceStatus.PENDING.value,
            source=source,
        )


def from_execution_result(
    execution_result: Any,
    *,
    intent_profile: Optional[Any] = None,
    trace_id: Optional[str] = None,
    source: str = "executor",
) -> ExecutionTraceEvent:
    """Build an ``execution_finished`` or ``execution_blocked``
    :class:`ExecutionTraceEvent` from an execution result dict.

    Parameters
    ----------
    execution_result:
        A dict (or any object) representing the execution result, typically
        containing ``action_taken``, ``success``, ``skipped_reason``, and
        ``target``.  ``None`` is tolerated.
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        for supplementary field extraction.
    trace_id:
        Shared trace ID to use.  A new UUID4 is generated when ``None``.
    source:
        Originating component identifier.

    Returns
    -------
    ExecutionTraceEvent
        Always returns a valid event; never raises.
    """
    try:
        return _build_result_event(
            execution_result,
            intent_profile=intent_profile,
            trace_id=trace_id,
            source=source,
        )
    except Exception:
        return ExecutionTraceEvent(
            trace_id=trace_id or str(uuid.uuid4()),
            stage=ExecutionTraceStage.EXECUTION_BLOCKED.value,
            status=ExecutionTraceStatus.FAILED.value,
            source=source,
        )


def build_trace_envelope(
    *,
    intent_profile: Optional[Any] = None,
    readiness_result: Optional[Any] = None,
    fallback_trace: Optional[Any] = None,
    execution_result: Optional[Any] = None,
    runtime_session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> ExecutionTraceEnvelope:
    """Build a complete :class:`ExecutionTraceEnvelope` spanning an execution lifecycle.

    Collects events for each available stage into a single envelope object.
    All events share the same ``trace_id``.

    Parameters
    ----------
    intent_profile:
        :class:`~core.execution.intent_profile.ExecutionIntentProfile` (PR-22).
    readiness_result:
        :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23).
    fallback_trace:
        :class:`~core.execution.fallback_trace.FallbackDecisionTrace` (PR-24).
    execution_result:
        Execution result dict from
        :meth:`~core.openclawd.OpenClawd._run_execution`.
    runtime_session_id:
        Session ID override; derived from *intent_profile* when ``None``.
    trace_id:
        Shared trace ID; a new UUID4 is generated when ``None``.

    Returns
    -------
    ExecutionTraceEnvelope
        Always returns a valid envelope; never raises.
    """
    try:
        return _build_envelope(
            intent_profile=intent_profile,
            readiness_result=readiness_result,
            fallback_trace=fallback_trace,
            execution_result=execution_result,
            runtime_session_id=runtime_session_id,
            trace_id=trace_id,
        )
    except Exception:
        eff_trace_id = trace_id or str(uuid.uuid4())
        return ExecutionTraceEnvelope(
            trace_id=eff_trace_id,
            runtime_session_id=runtime_session_id,
        )


# ---------------------------------------------------------------------------
# Private implementation helpers
# ---------------------------------------------------------------------------


def _extract_intent_fields(
    intent_profile: Any,
) -> Dict[str, Any]:
    """Safely extract common fields from an intent profile (or compatible object)."""
    out: Dict[str, Any] = {
        "intent_id": None,
        "runtime_session_id": None,
        "action_level": "observe",
        "runtime_domain": None,
        "target_ref": None,
        "source": "openclawd",
    }
    if intent_profile is None:
        return out
    try:
        intent_id = getattr(intent_profile, "intent_id", None)
        out["intent_id"] = str(intent_id) if intent_id else None
        out["runtime_session_id"] = getattr(intent_profile, "runtime_session_id", None)
        action_level = getattr(intent_profile, "action_level", "observe")
        out["action_level"] = str(action_level) if action_level else "observe"
        out["runtime_domain"] = getattr(intent_profile, "runtime_domain", None)
        out["target_ref"] = getattr(intent_profile, "target_ref", None)
        source = getattr(intent_profile, "source", "openclawd")
        out["source"] = str(source) if source else "openclawd"
    except Exception:
        pass
    return out


def _build_intent_event(
    intent_profile: Any,
    *,
    trace_id: Optional[str],
    source: str,
) -> ExecutionTraceEvent:
    fields = _extract_intent_fields(intent_profile)
    eff_trace_id = trace_id or str(uuid.uuid4())

    # Determine status: if intent is degraded, mark as degraded
    status = ExecutionTraceStatus.SUCCESS.value
    reason: Optional[str] = None
    details: Dict[str, Any] = {}

    if intent_profile is not None:
        degrade_reason = getattr(intent_profile, "degrade_reason", None)
        if degrade_reason:
            status = ExecutionTraceStatus.DEGRADED.value
            reason = str(degrade_reason)
        # Capture intent_mode if available
        intent_mode = getattr(intent_profile, "intent_mode", None)
        if intent_mode:
            details["intent_mode"] = str(intent_mode)
        confidence = getattr(intent_profile, "confidence", None)
        if confidence is not None:
            details["confidence"] = float(confidence)
        origin_state = getattr(intent_profile, "origin_state", None)
        if origin_state:
            details["origin_state"] = str(origin_state)

    return ExecutionTraceEvent(
        trace_id=eff_trace_id,
        runtime_session_id=fields["runtime_session_id"],
        intent_id=fields["intent_id"],
        stage=ExecutionTraceStage.INTENT_CREATED.value,
        status=status,
        action_level=fields["action_level"],
        runtime_domain=fields["runtime_domain"],
        target_ref=fields["target_ref"],
        reason=reason,
        source=source or fields["source"],
        details=details,
    )


def _build_readiness_event(
    readiness_result: Any,
    *,
    intent_profile: Optional[Any],
    trace_id: Optional[str],
    source: str,
) -> ExecutionTraceEvent:
    eff_trace_id = trace_id or str(uuid.uuid4())
    intent_fields = _extract_intent_fields(intent_profile)

    if readiness_result is None:
        return ExecutionTraceEvent(
            trace_id=eff_trace_id,
            runtime_session_id=intent_fields["runtime_session_id"],
            intent_id=intent_fields["intent_id"],
            stage=ExecutionTraceStage.READINESS_EVALUATED.value,
            status=ExecutionTraceStatus.SKIPPED.value,
            action_level=intent_fields["action_level"],
            runtime_domain=intent_fields["runtime_domain"],
            source=source,
        )

    ready = bool(getattr(readiness_result, "ready", True))
    readiness_status = str(getattr(readiness_result, "status", "") or "")
    blocked_by = str(getattr(readiness_result, "blocked_by", "none") or "none")
    reason_str = str(getattr(readiness_result, "reason", "") or "")
    requires_confirmation = bool(getattr(readiness_result, "requires_confirmation", False))
    policy_band = getattr(readiness_result, "policy_band", None)
    runtime_session = (
        getattr(readiness_result, "runtime_session_id", None)
        or intent_fields["runtime_session_id"]
    )
    intent_id_val = (
        getattr(readiness_result, "intent_id", None)
        or intent_fields["intent_id"]
    )
    action_level_val = (
        str(getattr(readiness_result, "action_level", "") or "")
        or intent_fields["action_level"]
    )
    runtime_domain_val = (
        getattr(readiness_result, "runtime_domain", None)
        or intent_fields["runtime_domain"]
    )

    # Map to ExecutionTraceStatus
    if ready and not requires_confirmation:
        status = ExecutionTraceStatus.SUCCESS.value
    elif ready and requires_confirmation:
        status = ExecutionTraceStatus.PENDING.value
    elif readiness_status == "observe_only":
        status = ExecutionTraceStatus.SKIPPED.value
    else:
        status = ExecutionTraceStatus.BLOCKED.value

    details: Dict[str, Any] = {}
    if readiness_status:
        details["readiness_status"] = readiness_status
    if blocked_by and blocked_by != "none":
        details["blocked_by"] = blocked_by
    if requires_confirmation:
        details["requires_confirmation"] = requires_confirmation
    if policy_band:
        details["policy_band"] = str(policy_band)

    return ExecutionTraceEvent(
        trace_id=eff_trace_id,
        runtime_session_id=runtime_session,
        intent_id=intent_id_val,
        stage=ExecutionTraceStage.READINESS_EVALUATED.value,
        status=status,
        action_level=action_level_val,
        runtime_domain=runtime_domain_val,
        target_ref=intent_fields["target_ref"],
        reason=reason_str or None,
        source=source,
        details=details,
    )


def _build_fallback_event(
    fallback_trace: Any,
    *,
    intent_profile: Optional[Any],
    trace_id: Optional[str],
    source: str,
) -> ExecutionTraceEvent:
    eff_trace_id = trace_id or str(uuid.uuid4())
    intent_fields = _extract_intent_fields(intent_profile)

    if fallback_trace is None:
        return ExecutionTraceEvent(
            trace_id=eff_trace_id,
            runtime_session_id=intent_fields["runtime_session_id"],
            intent_id=intent_fields["intent_id"],
            stage=ExecutionTraceStage.FALLBACK_SELECTED.value,
            status=ExecutionTraceStatus.SKIPPED.value,
            action_level=intent_fields["action_level"],
            runtime_domain=intent_fields["runtime_domain"],
            source=source,
        )

    # Extract from FallbackDecisionTrace (PR-24) or compatible object
    runtime_session = (
        getattr(fallback_trace, "runtime_session_id", None)
        or intent_fields["runtime_session_id"]
    )
    intent_id_val = (
        getattr(fallback_trace, "intent_id", None)
        or intent_fields["intent_id"]
    )
    action_level_val = (
        str(getattr(fallback_trace, "action_level", "") or "")
        or intent_fields["action_level"]
    )
    outcome = str(getattr(fallback_trace, "outcome", "blocked") or "blocked")
    primary_block_reason = getattr(fallback_trace, "primary_block_reason", None)
    fallback_path = getattr(fallback_trace, "fallback_path", None)
    fallback_reason = getattr(fallback_trace, "fallback_reason", None)
    decision_source = getattr(fallback_trace, "decision_source", None)

    # Map fallback outcome to trace status
    _outcome_to_status = {
        "selected": ExecutionTraceStatus.SUCCESS.value,
        "blocked": ExecutionTraceStatus.BLOCKED.value,
        "noop": ExecutionTraceStatus.SKIPPED.value,
        "degraded": ExecutionTraceStatus.DEGRADED.value,
        "failed": ExecutionTraceStatus.FAILED.value,
    }
    status = _outcome_to_status.get(outcome, ExecutionTraceStatus.BLOCKED.value)

    reason_str = primary_block_reason or fallback_reason or None
    if reason_str:
        reason_str = str(reason_str)

    details: Dict[str, Any] = {}
    if outcome:
        details["outcome"] = outcome
    if fallback_path:
        details["fallback_path"] = str(fallback_path)
    if decision_source:
        details["decision_source"] = str(decision_source)

    return ExecutionTraceEvent(
        trace_id=eff_trace_id,
        runtime_session_id=runtime_session,
        intent_id=intent_id_val,
        stage=ExecutionTraceStage.FALLBACK_SELECTED.value,
        status=status,
        action_level=action_level_val,
        runtime_domain=intent_fields["runtime_domain"],
        target_ref=intent_fields["target_ref"],
        reason=reason_str,
        source=source,
        details=details,
    )


def _build_result_event(
    execution_result: Any,
    *,
    intent_profile: Optional[Any],
    trace_id: Optional[str],
    source: str,
) -> ExecutionTraceEvent:
    eff_trace_id = trace_id or str(uuid.uuid4())
    intent_fields = _extract_intent_fields(intent_profile)

    if execution_result is None:
        return ExecutionTraceEvent(
            trace_id=eff_trace_id,
            runtime_session_id=intent_fields["runtime_session_id"],
            intent_id=intent_fields["intent_id"],
            stage=ExecutionTraceStage.EXECUTION_BLOCKED.value,
            status=ExecutionTraceStatus.BLOCKED.value,
            action_level=intent_fields["action_level"],
            runtime_domain=intent_fields["runtime_domain"],
            reason="execution_result_unavailable",
            source=source,
        )

    # Support both dict and object-style results
    if isinstance(execution_result, dict):
        action_taken = str(execution_result.get("action_taken", "none") or "none")
        success = bool(execution_result.get("success", False))
        skipped_reason = str(execution_result.get("skipped_reason", "") or "")
        target = execution_result.get("target")
        metadata = execution_result.get("metadata") or {}
    else:
        action_taken = str(getattr(execution_result, "action_taken", "none") or "none")
        success = bool(getattr(execution_result, "success", False))
        skipped_reason = str(getattr(execution_result, "skipped_reason", "") or "")
        target = getattr(execution_result, "target", None)
        metadata = getattr(execution_result, "metadata", None) or {}

    target_ref = (
        str(target) if target is not None else intent_fields["target_ref"]
    )

    # Determine stage and status
    if action_taken == "error":
        stage = ExecutionTraceStage.EXECUTION_BLOCKED.value
        status = ExecutionTraceStatus.FAILED.value
    elif action_taken in ("none", "noop") and not success:
        # Blocked (skipped_reason usually explains why)
        stage = ExecutionTraceStage.EXECUTION_BLOCKED.value
        status = ExecutionTraceStatus.BLOCKED.value
    elif action_taken in ("none", "noop") and success:
        stage = ExecutionTraceStage.EXECUTION_FINISHED.value
        status = ExecutionTraceStatus.SKIPPED.value
    elif success:
        stage = ExecutionTraceStage.EXECUTION_FINISHED.value
        status = ExecutionTraceStatus.SUCCESS.value
    else:
        stage = ExecutionTraceStage.EXECUTION_FINISHED.value
        status = ExecutionTraceStatus.FAILED.value

    reason_str = skipped_reason or None

    details: Dict[str, Any] = {}
    if action_taken:
        details["action_taken"] = action_taken
    if isinstance(metadata, dict) and metadata:
        details["metadata"] = metadata

    return ExecutionTraceEvent(
        trace_id=eff_trace_id,
        runtime_session_id=intent_fields["runtime_session_id"],
        intent_id=intent_fields["intent_id"],
        stage=stage,
        status=status,
        action_level=intent_fields["action_level"],
        runtime_domain=intent_fields["runtime_domain"],
        target_ref=target_ref,
        reason=reason_str,
        source=source,
        details=details,
    )


def _build_envelope(
    *,
    intent_profile: Optional[Any],
    readiness_result: Optional[Any],
    fallback_trace: Optional[Any],
    execution_result: Optional[Any],
    runtime_session_id: Optional[str],
    trace_id: Optional[str],
) -> ExecutionTraceEnvelope:
    """Internal implementation for :func:`build_trace_envelope`."""
    intent_fields = _extract_intent_fields(intent_profile)
    eff_trace_id = trace_id or str(uuid.uuid4())
    eff_session_id = runtime_session_id or intent_fields["runtime_session_id"]
    eff_intent_id = intent_fields["intent_id"]

    envelope = ExecutionTraceEnvelope(
        trace_id=eff_trace_id,
        runtime_session_id=eff_session_id,
        intent_id=eff_intent_id,
    )

    # Stage 1: intent_created
    if intent_profile is not None:
        event = _build_intent_event(intent_profile, trace_id=eff_trace_id, source="openclawd")
        envelope.append(event)

    # Stage 2: readiness_evaluated
    if readiness_result is not None or intent_profile is not None:
        event = _build_readiness_event(
            readiness_result,
            intent_profile=intent_profile,
            trace_id=eff_trace_id,
            source="readiness_gate",
        )
        envelope.append(event)

    # Stage 3: fallback_selected
    if fallback_trace is not None:
        event = _build_fallback_event(
            fallback_trace,
            intent_profile=intent_profile,
            trace_id=eff_trace_id,
            source="fallback_router",
        )
        envelope.append(event)

    # Stage 4/5: execution_finished or execution_blocked
    if execution_result is not None:
        event = _build_result_event(
            execution_result,
            intent_profile=intent_profile,
            trace_id=eff_trace_id,
            source="executor",
        )
        envelope.append(event)

    return envelope
