"""core.decision_timeline — Decision Timeline Replay and Explainability Traces (PR-34)
=======================================================================================

**Unified-Subject Architecture — Control-Loop Explainability**
--------------------------------------------------------------
This module introduces **canonical decision timeline** and
**explainability trace** artifacts so important control-loop outcomes can be
replayed, inspected, and surfaced consistently.

Architecture ownership rules
-----------------------------
- **OpenClawd core** (:mod:`core.openclawd`) is the **sole producer** of
  :class:`DecisionTraceRecord` entries.  Decisions are recorded from real
  control outcomes, not reconstructed later from incidental logs.
- **Runtime shell** (:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`)
  is the downstream consumer: it may present and replay timeline artifacts, but
  must not act as an independent truth source.
- **Projection / diagnostics layers** consume canonical
  :class:`ExplainabilitySnapshot` artifacts; they do not reconstruct separate
  explanations.

Represented concepts
---------------------
Every :class:`DecisionTraceRecord` captures one of the following decision
kinds (see :class:`DecisionKind`):

``route_selection``
    Model / provider selected by the routing authority.  Carries the chosen
    route tier, the preferred model, and the rationale for the selection.

``fallback_transition``
    System degraded from a higher route tier to a lower one (e.g.
    ``native_multimodal`` → ``text_only``).  Carries the previous tier, new
    tier, and why the transition occurred.

``source_switch``
    Primary audio or video source changed (re-election, recovery, eviction).
    Carries previous and new source IDs and the switch rationale.

``operator_override``
    An operator-committed override influenced the final decision.  Carries
    which domains were overridden and the operator-supplied reason.

``trust_safety_gating``
    Trust or safety state gated or constrained a control decision.  Carries
    the gating reason and which domains were affected.

``execution_locality_change``
    The execution locality policy changed (local→remote or remote→local).
    Carries the previous and new locality and the causal policy.

Public structures
-----------------
:class:`DecisionKind`
    Stable enum of trace-record kinds, safe for serialisation and replay.

:class:`DecisionTraceRecord`
    Structured, serialisable record for a single control-loop decision.
    Always produced by :func:`record_decision_event`.

:class:`ControlTimelineEvent`
    Thin envelope wrapping a :class:`DecisionTraceRecord` with stable
    sequence/ordering semantics suitable for replay.

:class:`ExplainabilitySnapshot`
    Point-in-time, JSON-serialisable snapshot of all
    :class:`ControlTimelineEvent` entries in the current session timeline.
    Suitable for shell-facing replay, diagnostics dashboards, and regression
    tests.

:class:`DecisionTimeline`
    Thread-safe singleton that records events and produces snapshots.
    Use :func:`get_decision_timeline` to access the global singleton.

Public builders
---------------
:func:`record_decision_event`
    Primary integration point for OpenClawd: build a
    :class:`DecisionTraceRecord` from canonical decision dicts, append it to
    the timeline, and return the :class:`ControlTimelineEvent`.

:func:`build_explainability_snapshot`
    Build an :class:`ExplainabilitySnapshot` from the current global timeline.

:func:`get_decision_timeline`
    Return the global :class:`DecisionTimeline` singleton.

:func:`reset_decision_timeline`
    Reset the global singleton (primarily for tests).

Serialisation
-------------
All public dataclasses expose ``to_dict()`` / ``from_dict()`` round-trip
methods.  All stored values are plain Python primitives (str, int, float,
bool, list, dict) so that ``json.dumps(obj.to_dict())`` always succeeds.

Usage::

    from core.decision_timeline import (
        DecisionKind,
        record_decision_event,
        build_explainability_snapshot,
        get_decision_timeline,
        reset_decision_timeline,
    )

    # In OpenClawd after a routing decision:
    event = record_decision_event(
        kind=DecisionKind.ROUTE_SELECTION,
        decision_summary="native_multimodal selected via tier-1 routing",
        rationale="perception confidence above threshold; native MM provider available",
        route_kind="native_multimodal",
        selected_model="gpt-4o",
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
    )

    # Build a snapshot for response metadata:
    snap = build_explainability_snapshot(trace_id=trace_id)
    response["metadata"]["decision_timeline_snapshot"] = snap.to_dict()
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Maximum number of events retained in the timeline singleton between resets.
_MAX_TIMELINE_EVENTS: int = 200


# ---------------------------------------------------------------------------
# DecisionKind
# ---------------------------------------------------------------------------


class DecisionKind(str, Enum):
    """Stable enum of decision trace record kinds.

    Values are lowercase strings safe for serialisation, counter keys, and
    replay tooling.
    """

    ROUTE_SELECTION = "route_selection"
    """Model / provider selected by the routing authority."""

    FALLBACK_TRANSITION = "fallback_transition"
    """System degraded from a higher route tier to a lower one."""

    SOURCE_SWITCH = "source_switch"
    """Primary audio or video source changed."""

    OPERATOR_OVERRIDE = "operator_override"
    """An operator-committed override influenced the final decision."""

    TRUST_SAFETY_GATING = "trust_safety_gating"
    """Trust or safety state gated or constrained a control decision."""

    EXECUTION_LOCALITY_CHANGE = "execution_locality_change"
    """Execution locality policy changed (local→remote or remote→local)."""

    UNKNOWN = "unknown"
    """Fallback kind for unrecognised inputs; never produced by canonical code."""

    @classmethod
    def from_string(cls, value: str) -> "DecisionKind":
        """Return a :class:`DecisionKind` from a raw string, defaulting to
        :attr:`UNKNOWN` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# DecisionTraceRecord
# ---------------------------------------------------------------------------


@dataclass
class DecisionTraceRecord:
    """Structured, serialisable record for a single control-loop decision.

    Attributes
    ----------
    record_id
        Unique identifier for this record (UUID4 by default).
    kind
        :class:`DecisionKind` describing which type of decision this record
        represents.
    decision_summary
        Short, human-readable description of the decision outcome.
    rationale
        Explanation of *why* this decision was made — the canonical
        reasoning text derived from the control-loop artifacts.
    route_kind
        The route tier selected (e.g. ``"native_multimodal"``,
        ``"text_only"``).  Relevant for ``route_selection`` and
        ``fallback_transition`` kinds; ``None`` otherwise.
    selected_model
        The provider/model chosen.  Relevant for ``route_selection``; ``None``
        otherwise.
    previous_route_kind
        The route tier before a fallback transition.  Relevant for
        ``fallback_transition``; ``None`` otherwise.
    fallback_reason
        Human-readable reason for the fallback.  Relevant for
        ``fallback_transition``; ``None`` otherwise.
    source_modality
        Modality of the source that switched (``"audio"``, ``"video"``).
        Relevant for ``source_switch``; ``None`` otherwise.
    previous_source_id
        Source ID before the switch.  Relevant for ``source_switch``; ``None``
        otherwise.
    new_source_id
        Source ID after the switch.  Relevant for ``source_switch``; ``None``
        otherwise.
    source_switch_reason
        Human-readable reason for the source switch.  Relevant for
        ``source_switch``; ``None`` otherwise.
    override_domains
        List of override domain names that were active.  Relevant for
        ``operator_override``; empty list otherwise.
    override_reason
        Operator-supplied reason for the override.  Relevant for
        ``operator_override``; ``None`` otherwise.
    gating_reason
        Trust/safety gating reason string.  Relevant for
        ``trust_safety_gating``; ``None`` otherwise.
    gated_domains
        List of domain names affected by trust/safety gating.  Relevant for
        ``trust_safety_gating``; empty list otherwise.
    previous_locality
        Locality before the change.  Relevant for
        ``execution_locality_change``; ``None`` otherwise.
    new_locality
        Locality after the change.  Relevant for
        ``execution_locality_change``; ``None`` otherwise.
    causal_policy
        Policy name or description that caused the locality change.  Relevant
        for ``execution_locality_change``; ``None`` otherwise.
    trace_id
        Correlation trace identifier, linking this record to a specific
        control-loop iteration.
    runtime_session_id
        Runtime / OpenClawd session identifier.
    timestamp
        Unix timestamp (seconds since epoch) when this record was created.
    extra
        Optional extra metadata dict for forward-compatible extensions.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = DecisionKind.UNKNOWN.value
    decision_summary: str = ""
    rationale: str = ""

    # route_selection / fallback_transition fields
    route_kind: Optional[str] = None
    selected_model: Optional[str] = None
    previous_route_kind: Optional[str] = None
    fallback_reason: Optional[str] = None

    # source_switch fields
    source_modality: Optional[str] = None
    previous_source_id: Optional[str] = None
    new_source_id: Optional[str] = None
    source_switch_reason: Optional[str] = None

    # operator_override fields
    override_domains: List[str] = field(default_factory=list)
    override_reason: Optional[str] = None

    # trust_safety_gating fields
    gating_reason: Optional[str] = None
    gated_domains: List[str] = field(default_factory=list)

    # execution_locality_change fields
    previous_locality: Optional[str] = None
    new_locality: Optional[str] = None
    causal_policy: Optional[str] = None

    # Correlation
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    # Forward-compat extension
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this record."""
        return {
            "record_id": self.record_id,
            "kind": self.kind,
            "decision_summary": self.decision_summary,
            "rationale": self.rationale,
            "route_kind": self.route_kind,
            "selected_model": self.selected_model,
            "previous_route_kind": self.previous_route_kind,
            "fallback_reason": self.fallback_reason,
            "source_modality": self.source_modality,
            "previous_source_id": self.previous_source_id,
            "new_source_id": self.new_source_id,
            "source_switch_reason": self.source_switch_reason,
            "override_domains": list(self.override_domains),
            "override_reason": self.override_reason,
            "gating_reason": self.gating_reason,
            "gated_domains": list(self.gated_domains),
            "previous_locality": self.previous_locality,
            "new_locality": self.new_locality,
            "causal_policy": self.causal_policy,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionTraceRecord":
        """Reconstruct a :class:`DecisionTraceRecord` from a dict produced by
        :meth:`to_dict`.  Unknown keys are silently ignored."""
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            kind=data.get("kind", DecisionKind.UNKNOWN.value),
            decision_summary=data.get("decision_summary", ""),
            rationale=data.get("rationale", ""),
            route_kind=data.get("route_kind"),
            selected_model=data.get("selected_model"),
            previous_route_kind=data.get("previous_route_kind"),
            fallback_reason=data.get("fallback_reason"),
            source_modality=data.get("source_modality"),
            previous_source_id=data.get("previous_source_id"),
            new_source_id=data.get("new_source_id"),
            source_switch_reason=data.get("source_switch_reason"),
            override_domains=list(data.get("override_domains") or []),
            override_reason=data.get("override_reason"),
            gating_reason=data.get("gating_reason"),
            gated_domains=list(data.get("gated_domains") or []),
            previous_locality=data.get("previous_locality"),
            new_locality=data.get("new_locality"),
            causal_policy=data.get("causal_policy"),
            trace_id=data.get("trace_id"),
            runtime_session_id=data.get("runtime_session_id"),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra") or {}),
        )


# ---------------------------------------------------------------------------
# ControlTimelineEvent
# ---------------------------------------------------------------------------


@dataclass
class ControlTimelineEvent:
    """Thin envelope wrapping a :class:`DecisionTraceRecord` with stable
    sequence/ordering semantics suitable for replay.

    Attributes
    ----------
    event_id
        Unique identifier for this timeline event (UUID4 by default).
    sequence
        Monotonically increasing integer sequence number within the current
        :class:`DecisionTimeline` session.  Suitable for deterministic replay
        ordering without depending on wall-clock timestamps.
    record
        The canonical :class:`DecisionTraceRecord` for this event.
    emitted_at
        Unix timestamp (seconds since epoch) when this event was appended to
        the timeline.
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sequence: int = 0
    record: DecisionTraceRecord = field(default_factory=DecisionTraceRecord)
    emitted_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this event."""
        return {
            "event_id": self.event_id,
            "sequence": self.sequence,
            "record": self.record.to_dict(),
            "emitted_at": self.emitted_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControlTimelineEvent":
        """Reconstruct a :class:`ControlTimelineEvent` from a dict produced by
        :meth:`to_dict`.  Unknown keys are silently ignored."""
        raw_record = data.get("record")
        record = (
            DecisionTraceRecord.from_dict(raw_record)
            if isinstance(raw_record, dict)
            else DecisionTraceRecord()
        )
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            sequence=int(data.get("sequence", 0)),
            record=record,
            emitted_at=float(data.get("emitted_at", time.time())),
        )


# ---------------------------------------------------------------------------
# ExplainabilitySnapshot
# ---------------------------------------------------------------------------


@dataclass
class ExplainabilitySnapshot:
    """Point-in-time, JSON-serialisable snapshot of the decision timeline.

    Suitable for shell-facing replay, diagnostics dashboards, and regression
    tests.

    Attributes
    ----------
    snapshot_id
        Unique identifier for this snapshot (UUID4 by default).
    events
        Ordered list of :class:`ControlTimelineEvent` entries captured at the
        time the snapshot was taken.  Ordered by ascending sequence number.
    total_events
        Total number of events captured (equals ``len(events)`` after snapshot).
    trace_id
        Correlation trace identifier from the calling control-loop iteration.
    runtime_session_id
        Runtime / OpenClawd session identifier.
    captured_at
        Unix timestamp (seconds since epoch) when this snapshot was captured.
    kind_counts
        Dict mapping :class:`DecisionKind` value strings to event counts.
        Useful for quick summary without iterating all events.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    events: List[ControlTimelineEvent] = field(default_factory=list)
    total_events: int = 0
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    captured_at: float = field(default_factory=time.time)
    kind_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation of this snapshot."""
        return {
            "snapshot_id": self.snapshot_id,
            "events": [e.to_dict() for e in self.events],
            "total_events": self.total_events,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "captured_at": self.captured_at,
            "kind_counts": dict(self.kind_counts),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExplainabilitySnapshot":
        """Reconstruct an :class:`ExplainabilitySnapshot` from a dict produced
        by :meth:`to_dict`.  Unknown keys are silently ignored."""
        raw_events = data.get("events") or []
        events = [
            ControlTimelineEvent.from_dict(e) if isinstance(e, dict) else ControlTimelineEvent()
            for e in raw_events
        ]
        return cls(
            snapshot_id=data.get("snapshot_id", str(uuid.uuid4())),
            events=events,
            total_events=int(data.get("total_events", len(events))),
            trace_id=data.get("trace_id"),
            runtime_session_id=data.get("runtime_session_id"),
            captured_at=float(data.get("captured_at", time.time())),
            kind_counts=dict(data.get("kind_counts") or {}),
        )


# ---------------------------------------------------------------------------
# DecisionTimeline (thread-safe singleton)
# ---------------------------------------------------------------------------


class DecisionTimeline:
    """Thread-safe singleton that records decision events and produces snapshots.

    The timeline retains the last :data:`_MAX_TIMELINE_EVENTS` events.  Older
    events are evicted (FIFO) when the buffer fills so that long-running
    sessions do not accumulate unbounded memory.

    Use :func:`get_decision_timeline` to obtain the process-wide singleton.
    Use :func:`reset_decision_timeline` to reset it (primarily for tests).
    """

    def __init__(self, max_events: int = _MAX_TIMELINE_EVENTS) -> None:
        self._lock = threading.Lock()
        self._events: List[ControlTimelineEvent] = []
        self._sequence: int = 0
        self._max_events: int = max_events

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, record: DecisionTraceRecord) -> ControlTimelineEvent:
        """Append *record* to the timeline and return the wrapped
        :class:`ControlTimelineEvent`.

        Thread-safe.  Evicts the oldest event when the buffer is full.
        """
        with self._lock:
            self._sequence += 1
            event = ControlTimelineEvent(
                sequence=self._sequence,
                record=record,
                emitted_at=time.time(),
            )
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events.pop(0)
            return event

    def snapshot(
        self,
        *,
        trace_id: Optional[str] = None,
        runtime_session_id: Optional[str] = None,
    ) -> ExplainabilitySnapshot:
        """Return a point-in-time :class:`ExplainabilitySnapshot` of all
        currently retained events.

        Thread-safe.  Events are copied so that subsequent mutations of the
        timeline do not affect the returned snapshot.
        """
        with self._lock:
            events_copy = list(self._events)

        kind_counts: Dict[str, int] = {}
        for ev in events_copy:
            kind_counts[ev.record.kind] = kind_counts.get(ev.record.kind, 0) + 1

        return ExplainabilitySnapshot(
            events=events_copy,
            total_events=len(events_copy),
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            captured_at=time.time(),
            kind_counts=kind_counts,
        )

    def clear(self) -> None:
        """Clear all recorded events and reset the sequence counter.

        Thread-safe.  Intended for test isolation via
        :func:`reset_decision_timeline`.
        """
        with self._lock:
            self._events.clear()
            self._sequence = 0

    @property
    def event_count(self) -> int:
        """Current number of events in the timeline buffer."""
        with self._lock:
            return len(self._events)


# ---------------------------------------------------------------------------
# Singleton global timeline
# ---------------------------------------------------------------------------

_GLOBAL_TIMELINE: Optional[DecisionTimeline] = None
_TIMELINE_LOCK = threading.Lock()


def get_decision_timeline() -> DecisionTimeline:
    """Return the global :class:`DecisionTimeline` singleton."""
    global _GLOBAL_TIMELINE
    if _GLOBAL_TIMELINE is None:
        with _TIMELINE_LOCK:
            if _GLOBAL_TIMELINE is None:
                _GLOBAL_TIMELINE = DecisionTimeline()
    return _GLOBAL_TIMELINE


def reset_decision_timeline() -> None:
    """Reset the global :class:`DecisionTimeline` singleton (primarily for tests)."""
    global _GLOBAL_TIMELINE
    with _TIMELINE_LOCK:
        _GLOBAL_TIMELINE = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_route_selection_record(
    *,
    route_dict: Dict[str, Any],
    trace_id: Optional[str],
    runtime_session_id: Optional[str],
    **extra_kwargs: Any,
) -> DecisionTraceRecord:
    """Derive a ``route_selection`` :class:`DecisionTraceRecord` from an
    OpenClawd routing-decision dict."""
    route_kind = str(route_dict.get("route_type") or route_dict.get("route_kind") or "unknown")
    is_native = bool(route_dict.get("is_native_multimodal", False))
    route_reason = str(route_dict.get("route_reason") or "")
    fallback_reason = route_dict.get("fallback_reason")
    selected_model = route_dict.get("selected_model") or route_dict.get("preferred_model")

    decision_summary = (
        f"{route_kind} route selected"
        + (" (native multimodal)" if is_native else "")
        + (f" via {selected_model}" if selected_model else "")
    )
    rationale = route_reason or "canonical routing decision by OpenClawd"

    return DecisionTraceRecord(
        kind=DecisionKind.ROUTE_SELECTION.value,
        decision_summary=decision_summary,
        rationale=rationale,
        route_kind=route_kind,
        selected_model=str(selected_model) if selected_model else None,
        fallback_reason=str(fallback_reason) if fallback_reason else None,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        extra=extra_kwargs,
    )


def _derive_fallback_transition_record(
    *,
    route_dict: Dict[str, Any],
    previous_route_kind: Optional[str],
    trace_id: Optional[str],
    runtime_session_id: Optional[str],
    **extra_kwargs: Any,
) -> DecisionTraceRecord:
    """Derive a ``fallback_transition`` :class:`DecisionTraceRecord` from the
    routing dict and the previous route kind."""
    new_route = str(route_dict.get("route_type") or route_dict.get("route_kind") or "unknown")
    fallback_reason = str(route_dict.get("fallback_reason") or "degradation policy applied")
    decision_summary = (
        f"fallback from {previous_route_kind or 'unknown'} to {new_route}"
    )
    rationale = fallback_reason

    return DecisionTraceRecord(
        kind=DecisionKind.FALLBACK_TRANSITION.value,
        decision_summary=decision_summary,
        rationale=rationale,
        route_kind=new_route,
        previous_route_kind=str(previous_route_kind) if previous_route_kind else None,
        fallback_reason=fallback_reason,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        extra=extra_kwargs,
    )


def _derive_operator_override_record(
    *,
    override_snapshot_dict: Dict[str, Any],
    trace_id: Optional[str],
    runtime_session_id: Optional[str],
    **extra_kwargs: Any,
) -> DecisionTraceRecord:
    """Derive an ``operator_override`` :class:`DecisionTraceRecord` from an
    :class:`~core.operator_override.OperatorOverrideSnapshot` dict."""
    applied_records = override_snapshot_dict.get("applied_records") or []
    domains: List[str] = []
    reasons: List[str] = []
    for rec in applied_records:
        if isinstance(rec, dict):
            if rec.get("domain"):
                domains.append(str(rec["domain"]))
            if rec.get("override_reason"):
                reasons.append(str(rec["override_reason"]))

    active_set = override_snapshot_dict.get("active_override_set") or {}
    if isinstance(active_set, dict):
        override_reason = active_set.get("override_reason") or (
            reasons[0] if reasons else None
        )
    else:
        override_reason = reasons[0] if reasons else None

    decision_summary = (
        f"operator override active on {len(domains)} domain(s): "
        + (", ".join(domains) if domains else "none")
    )
    rationale = override_reason or "operator-committed override via DesktopPresenceRuntime"

    return DecisionTraceRecord(
        kind=DecisionKind.OPERATOR_OVERRIDE.value,
        decision_summary=decision_summary,
        rationale=rationale,
        override_domains=domains,
        override_reason=override_reason,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        extra=extra_kwargs,
    )


def _derive_trust_safety_gating_record(
    *,
    permission_safety_dict: Dict[str, Any],
    trace_id: Optional[str],
    runtime_session_id: Optional[str],
    **extra_kwargs: Any,
) -> DecisionTraceRecord:
    """Derive a ``trust_safety_gating`` :class:`DecisionTraceRecord` from a
    :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot` dict."""
    gating_reason = permission_safety_dict.get("gating_reason") or ""
    risk_tier = permission_safety_dict.get("execution_risk_tier") or ""
    trust_label = permission_safety_dict.get("trust_label") or ""
    gated_domains: List[str] = list(permission_safety_dict.get("gated_domains") or [])

    if not gating_reason:
        annotation = permission_safety_dict.get("execution_trust_annotation") or {}
        if isinstance(annotation, dict):
            gating_reason = annotation.get("gating_reason") or ""
            if not gated_domains:
                gated_domains = list(annotation.get("gated_domains") or [])

    decision_summary = (
        f"trust/safety gating applied"
        + (f" (risk_tier={risk_tier})" if risk_tier else "")
        + (f" (trust={trust_label})" if trust_label else "")
    )
    rationale = gating_reason or "permission/safety state constrained the control decision"

    return DecisionTraceRecord(
        kind=DecisionKind.TRUST_SAFETY_GATING.value,
        decision_summary=decision_summary,
        rationale=rationale,
        gating_reason=gating_reason or None,
        gated_domains=gated_domains,
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        extra=extra_kwargs,
    )


def _derive_source_switch_record(
    *,
    source_recovery_dict: Dict[str, Any],
    trace_id: Optional[str],
    runtime_session_id: Optional[str],
    **extra_kwargs: Any,
) -> DecisionTraceRecord:
    """Derive a ``source_switch`` :class:`DecisionTraceRecord` from a
    :class:`~core.multimodal.source_recovery_policy.SourceRecoverySnapshot` dict."""
    switch_events = source_recovery_dict.get("primary_source_switch_events") or []
    if not switch_events:
        return DecisionTraceRecord(
            kind=DecisionKind.SOURCE_SWITCH.value,
            decision_summary="source switch evaluated (no primary change detected)",
            rationale="source recovery cycle ran without primary-source change",
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            extra=extra_kwargs,
        )

    last = switch_events[-1] if isinstance(switch_events[-1], dict) else {}
    modality = last.get("modality") or "unknown"
    previous_id = last.get("previous_primary_id")
    new_id = last.get("new_primary_id")
    reason = last.get("switch_reason") or "re-election by source recovery policy"

    decision_summary = (
        f"primary {modality} source switched"
        + (f" from {previous_id}" if previous_id else "")
        + (f" to {new_id}" if new_id else "")
    )

    return DecisionTraceRecord(
        kind=DecisionKind.SOURCE_SWITCH.value,
        decision_summary=decision_summary,
        rationale=str(reason),
        source_modality=str(modality),
        previous_source_id=str(previous_id) if previous_id else None,
        new_source_id=str(new_id) if new_id else None,
        source_switch_reason=str(reason),
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        extra=extra_kwargs,
    )


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def record_decision_event(
    *,
    kind: DecisionKind,
    decision_summary: str = "",
    rationale: str = "",
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    route_kind: Optional[str] = None,
    selected_model: Optional[str] = None,
    previous_route_kind: Optional[str] = None,
    fallback_reason: Optional[str] = None,
    source_modality: Optional[str] = None,
    previous_source_id: Optional[str] = None,
    new_source_id: Optional[str] = None,
    source_switch_reason: Optional[str] = None,
    override_domains: Optional[List[str]] = None,
    override_reason: Optional[str] = None,
    gating_reason: Optional[str] = None,
    gated_domains: Optional[List[str]] = None,
    previous_locality: Optional[str] = None,
    new_locality: Optional[str] = None,
    causal_policy: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[ControlTimelineEvent]:
    """Build a :class:`DecisionTraceRecord` from explicit fields, append it to
    the global :class:`DecisionTimeline`, and return the wrapped
    :class:`ControlTimelineEvent`.

    This is the primary integration point for OpenClawd and other canonical
    producers.

    Parameters
    ----------
    kind
        The :class:`DecisionKind` for this decision.
    decision_summary
        Short human-readable description of the outcome.
    rationale
        Explanation of why this decision was made.
    trace_id
        Correlation trace ID for the current control-loop iteration.
    runtime_session_id
        Runtime / OpenClawd session identifier.
    route_kind, selected_model, previous_route_kind, fallback_reason
        Route-selection and fallback-transition fields.
    source_modality, previous_source_id, new_source_id, source_switch_reason
        Source-switch fields.
    override_domains, override_reason
        Operator-override fields.
    gating_reason, gated_domains
        Trust/safety-gating fields.
    previous_locality, new_locality, causal_policy
        Execution-locality-change fields.
    extra
        Optional additional metadata.

    Returns
    -------
    :class:`ControlTimelineEvent` or None
        The wrapped event that was appended to the timeline, or ``None`` on
        failure (failure is always non-fatal).
    """
    try:
        record = DecisionTraceRecord(
            kind=kind.value if isinstance(kind, DecisionKind) else str(kind),
            decision_summary=decision_summary,
            rationale=rationale,
            route_kind=route_kind,
            selected_model=selected_model,
            previous_route_kind=previous_route_kind,
            fallback_reason=fallback_reason,
            source_modality=source_modality,
            previous_source_id=previous_source_id,
            new_source_id=new_source_id,
            source_switch_reason=source_switch_reason,
            override_domains=list(override_domains or []),
            override_reason=override_reason,
            gating_reason=gating_reason,
            gated_domains=list(gated_domains or []),
            previous_locality=previous_locality,
            new_locality=new_locality,
            causal_policy=causal_policy,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
            extra=dict(extra or {}),
        )
        return get_decision_timeline().append(record)
    except Exception as _exc:
        logger.debug("record_decision_event failed (swallowed): %s", _exc)
        return None


def record_route_selection_event(
    *,
    route_dict: Dict[str, Any],
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> Optional[ControlTimelineEvent]:
    """Convenience builder: derive and record a ``route_selection`` event from
    an OpenClawd routing-decision dict.

    Emits a ``fallback_transition`` event automatically when the route dict
    indicates a fallback occurred (i.e. ``fallback_reason`` is set and the
    route kind is not ``native_multimodal``).

    Returns
    -------
    :class:`ControlTimelineEvent` or None
        The ``route_selection`` event (the last one appended), or ``None`` on
        failure.
    """
    try:
        # Always emit the route selection record
        route_record = _derive_route_selection_record(
            route_dict=route_dict,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
        route_event = get_decision_timeline().append(route_record)

        # Also emit a fallback transition record when a fallback was detected
        route_kind = str(route_dict.get("route_type") or route_dict.get("route_kind") or "")
        fallback_reason = route_dict.get("fallback_reason")
        if fallback_reason and route_kind != "native_multimodal":
            fallback_record = _derive_fallback_transition_record(
                route_dict=route_dict,
                previous_route_kind="native_multimodal",
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
            get_decision_timeline().append(fallback_record)

        return route_event
    except Exception as _exc:
        logger.debug("record_route_selection_event failed (swallowed): %s", _exc)
        return None


def record_operator_override_event(
    *,
    override_snapshot_dict: Dict[str, Any],
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> Optional[ControlTimelineEvent]:
    """Convenience builder: derive and record an ``operator_override`` event
    from an :class:`~core.operator_override.OperatorOverrideSnapshot` dict.

    Returns ``None`` when there are no active overrides or on failure.
    """
    try:
        # Only emit when there are actually active overrides
        active_set = override_snapshot_dict.get("active_override_set")
        applied = override_snapshot_dict.get("applied_records") or []
        if not active_set and not applied:
            return None

        record = _derive_operator_override_record(
            override_snapshot_dict=override_snapshot_dict,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
        return get_decision_timeline().append(record)
    except Exception as _exc:
        logger.debug("record_operator_override_event failed (swallowed): %s", _exc)
        return None


def record_trust_safety_gating_event(
    *,
    permission_safety_dict: Dict[str, Any],
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> Optional[ControlTimelineEvent]:
    """Convenience builder: derive and record a ``trust_safety_gating`` event
    from a :class:`~core.multimodal.permission_safety_state.PermissionSafetySnapshot`
    dict.

    Returns ``None`` when no gating is active or on failure.
    """
    try:
        gating_reason = permission_safety_dict.get("gating_reason")
        risk_tier = permission_safety_dict.get("execution_risk_tier") or ""
        annotation = permission_safety_dict.get("execution_trust_annotation") or {}
        if isinstance(annotation, dict) and not gating_reason:
            gating_reason = annotation.get("gating_reason")

        # Only emit when gating or elevated risk is present
        if not gating_reason and risk_tier in ("", "low", "unknown"):
            return None

        record = _derive_trust_safety_gating_record(
            permission_safety_dict=permission_safety_dict,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
        return get_decision_timeline().append(record)
    except Exception as _exc:
        logger.debug("record_trust_safety_gating_event failed (swallowed): %s", _exc)
        return None


def record_source_switch_event(
    *,
    source_recovery_dict: Dict[str, Any],
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> Optional[ControlTimelineEvent]:
    """Convenience builder: derive and record a ``source_switch`` event from a
    :class:`~core.multimodal.source_recovery_policy.SourceRecoverySnapshot` dict.

    Returns ``None`` when no primary-source switch is present in the snapshot or
    on failure.
    """
    try:
        switch_events = source_recovery_dict.get("primary_source_switch_events") or []
        if not switch_events:
            return None

        record = _derive_source_switch_record(
            source_recovery_dict=source_recovery_dict,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
        return get_decision_timeline().append(record)
    except Exception as _exc:
        logger.debug("record_source_switch_event failed (swallowed): %s", _exc)
        return None


def build_explainability_snapshot(
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> ExplainabilitySnapshot:
    """Build an :class:`ExplainabilitySnapshot` from the current global
    :class:`DecisionTimeline`.

    Parameters
    ----------
    trace_id
        Correlation trace ID to embed in the snapshot.
    runtime_session_id
        Runtime session identifier to embed in the snapshot.

    Returns
    -------
    :class:`ExplainabilitySnapshot`
        Never raises; returns an empty snapshot on failure.
    """
    try:
        return get_decision_timeline().snapshot(
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
    except Exception as _exc:
        logger.debug("build_explainability_snapshot failed (swallowed): %s", _exc)
        return ExplainabilitySnapshot(
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )
