#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/flow_level_operator_surface.py
=====================================
PR-7V2 (post-533 dual-repo runtime host unification track):
Flow-Level Operator Surface — Canonical Projection for Delegated Flows.

Background
----------
The existing :class:`~core.operator_surface.OperatorSurface` exposes strong
task-level observability (task lifecycle, route, executor, lineage, recovery)
but offers no canonical projection of the delegated flow as it executes on
the Android side.  Operators can see "V2 did what" and "task lifecycle is X"
but cannot answer:

* "Is Android currently in planning or grounding?"
* "Which LoopController step is the flow on?"
* "Did a replan happen?  Did stagnation trigger?"
* "Which policy gate is blocking the flow?"
* "How does the Android execution history align with recovery / truth /
  result artifacts?"

This module closes that gap by establishing a **flow-level operator surface**
that projects the delegated flow's canonical state as a single, operator-
readable view regardless of which component currently holds the execution
truth.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  FLOW-LEVEL OPERATOR SURFACE  (this module, layer 10+)             │
    │                                                                     │
    │  Consumes (read-only) from:                                        │
    │    • DelegatedFlowEntityRuntime  — flow identity / phase           │
    │    • FlowTruthAlignmentRuntime   — truth alignment history         │
    │    • FlowAwareConvergence        — result convergence artifacts     │
    │    • DelegatedFlowRecovery       — recovery decision artifacts      │
    │    • OperatorSurface             — task / recovery / lineage views  │
    │                                                                     │
    │  Exposes (read-only projections):                                  │
    │    • inspect_flow(flow_id)       → FlowOperatorProjection | None   │
    │                                                                     │
    │  Operator-facing artifacts on FlowOperatorProjection:             │
    │    • current_execution_phase   (AndroidExecutionPhase)             │
    │    • last_android_execution_event                                  │
    │    • blocking_reason                                               │
    │    • recovery_status                                               │
    │    • truth_alignment_status                                        │
    │    • canonical_result_status                                       │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Projection-only** — no mutation of canonical state.
2. **Graceful degradation** — missing runtime layers yield empty/default
   fields rather than raising.
3. **Source-annotated** — every projection carries ``_source`` so downstream
   consumers can verify provenance.
4. **Authority-declared** — sentinels enable downstream consumers to assert
   that they are reading from the canonical flow-level surface.

Public API
----------
Authority sentinels::

    FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY
    FLOW_LEVEL_OPERATOR_SURFACE_POLICY

Enumerations::

    AndroidExecutionPhase

Dataclasses::

    AndroidCanonicalExecutionEvent
    FlowOperatorProjection

Class::

    FlowLevelOperatorSurface

Helpers::

    get_flow_level_operator_surface() -> FlowLevelOperatorSurface
    reset_flow_level_operator_surface() -> None  # testing only
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.FlowLevelOperatorSurface")

__all__ = [
    # Authority sentinels
    "FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY",
    "FLOW_LEVEL_OPERATOR_SURFACE_POLICY",
    # Enumerations
    "AndroidExecutionPhase",
    # Dataclasses
    "AndroidCanonicalExecutionEvent",
    "FlowOperatorProjection",
    # Class
    "FlowLevelOperatorSurface",
    # Helpers
    "get_flow_level_operator_surface",
    "reset_flow_level_operator_surface",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY: str = "FLOW_LEVEL_OPERATOR_SURFACE_V1"
"""Sentinel: this module is the canonical flow-level operator surface authority.

Import to assert that a UI/console component reads flow-level state exclusively
from this canonical projection rather than from raw Android execution signals
or individual subsystem internals."""

FLOW_LEVEL_OPERATOR_SURFACE_POLICY: str = (
    "REQUIRED: All operator/UI surfaces that expose delegated-flow state MUST "
    "consume flow-level projections from FlowLevelOperatorSurface; no surface "
    "may infer Android execution state from raw Android signals or subsystem "
    "internals.  PR-7V2, flow-level operator surface."
)
"""Policy: flow-level surfaces read projections only, never assemble truth independently."""

# ---------------------------------------------------------------------------
# AndroidExecutionPhase
# ---------------------------------------------------------------------------


class AndroidExecutionPhase(str, Enum):
    """Canonical enum for the Android-side execution phase as seen from V2.

    These phases correspond to the major logical stages within an Android
    delegated execution run.  V2 infers the current phase from absorbed
    canonical execution events; it never directly observes the Android
    LoopController state.

    Values
    ------
    planning
        The Android runtime is planning the execution strategy for the
        delegated goal.  Corresponds to early LoopController / agent
        pipeline initialisation phases.
    grounding
        The Android runtime is grounding the plan into concrete UI actions
        (screenshot analysis, element detection, action graph construction).
    execution
        The Android runtime is executing grounded actions step-by-step.
    replan
        The Android runtime determined that the current plan is no longer
        valid and is in the process of replanning.
    stagnation
        The Android runtime has detected stagnation (repeated state with no
        progress) and is evaluating whether to abort, retry, or replan.
    gate_decision
        A policy gate on the Android side is evaluating whether execution
        should continue (safety check, capability guard, operator override
        request, etc.).
    takeover
        A takeover request has been initiated — another agent or the user
        is assuming control of the execution.
    collaboration
        The Android runtime is in a collaborative execution phase involving
        multiple local agents or a joint V2/Android execution segment.
    completed
        The Android runtime has finished execution and a result is being
        or has been returned to V2.
    failed
        The Android runtime has failed the execution and is returning an
        error result.
    unknown
        The current Android execution phase cannot be determined from the
        information available to V2.
    """

    planning = "planning"
    grounding = "grounding"
    execution = "execution"
    replan = "replan"
    stagnation = "stagnation"
    gate_decision = "gate_decision"
    takeover = "takeover"
    collaboration = "collaboration"
    completed = "completed"
    failed = "failed"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "AndroidExecutionPhase":
        """Return the enum member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown

    def is_terminal(self) -> bool:
        """Return True when this phase is a terminal execution phase."""
        return self in (AndroidExecutionPhase.completed, AndroidExecutionPhase.failed)

    def is_blocking(self) -> bool:
        """Return True when this phase represents a blocking / stalled condition."""
        return self in (
            AndroidExecutionPhase.stagnation,
            AndroidExecutionPhase.gate_decision,
        )


# ---------------------------------------------------------------------------
# AndroidCanonicalExecutionEvent
# ---------------------------------------------------------------------------


@dataclass
class AndroidCanonicalExecutionEvent:
    """A single canonical execution event absorbed from the Android runtime.

    This is the V2-side projection of an event that occurred on the Android
    device during a delegated flow execution.  Events are absorbed via the
    truth ingress path and projected into this canonical form so that the
    operator surface can display them without raw Android signal exposure.

    Attributes
    ----------
    event_id
        Unique identifier for this event record.  Auto-generated if not
        provided.
    flow_id
        ``delegated_flow_id`` of the flow this event belongs to.
    phase
        :class:`AndroidExecutionPhase` that this event represents.
    step_index
        Zero-based step index within the current LoopController execution
        cycle, if known.  ``-1`` when the step index is not available.
    detail
        Human-readable detail describing what happened at this event.
    is_blocking
        ``True`` when this event represents a blocking condition (gate,
        stagnation, etc.) that is preventing execution progress.
    blocking_reason
        Human-readable reason why execution is blocked, if applicable.
    policy_gate
        Name of the policy gate that triggered this event, if any.
    absorbed_at
        Unix timestamp when V2 absorbed this event from the Android runtime.
    android_ts
        Optional timestamp from the Android runtime itself.  May differ from
        ``absorbed_at`` due to clock skew or buffering.
    evidence
        Free-form evidence dict forwarded to operator surfaces for
        postmortem diagnostics.
    """

    event_id: str = field(default_factory=lambda: f"ace_{uuid.uuid4().hex[:12]}")
    flow_id: str = ""
    phase: AndroidExecutionPhase = AndroidExecutionPhase.unknown
    step_index: int = -1
    detail: str = ""
    is_blocking: bool = False
    blocking_reason: str = ""
    policy_gate: str = ""
    absorbed_at: float = field(default_factory=time.time)
    android_ts: Optional[float] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "event_id": self.event_id,
            "flow_id": self.flow_id,
            "phase": self.phase.value,
            "step_index": self.step_index,
            "detail": self.detail,
            "is_blocking": self.is_blocking,
            "blocking_reason": self.blocking_reason,
            "policy_gate": self.policy_gate,
            "absorbed_at": self.absorbed_at,
            "android_ts": self.android_ts,
            "evidence": dict(self.evidence),
        }


# ---------------------------------------------------------------------------
# FlowOperatorProjection
# ---------------------------------------------------------------------------


@dataclass
class FlowOperatorProjection:
    """Canonical read-only projection of a delegated flow for the operator console.

    This is the **primary operator-facing view** of a delegated flow.  It
    aggregates identity, lineage, binding, execution phase, recovery status,
    truth alignment, and result convergence into a single, serialisable record
    that operators can inspect to understand "what is this flow doing, and
    where is it stuck?"

    Attributes
    ----------
    flow_id
        Canonical ``delegated_flow_id``.
    flow_lineage_id
        Lineage identifier shared across all segments of the same logical
        work unit.
    flow_segment_id
        Optional segment discriminator within a lineage.
    trace_id
        Distributed trace identifier propagated from the originating request.
    flow_kind
        Origin type of the delegated flow (task_assign, goal_execution,
        parallel_subtask, takeover_request).
    flow_phase
        Current unified delegated flow phase from
        :class:`~core.delegated_flow_entity.DelegatedFlowPhase`.
    canonical_task_id
        ``CanonicalTask`` id that originated this flow.
    dispatch_record_id
        ``DelegatedRuntimeDispatchRecord`` id for this flow.
    contract_id
        ``DelegatedHandoffContractRecord`` id for this flow.
    binding_id
        ``AndroidRuntimeDispatchBindingRecord`` id for this flow.
    device_id
        Target Android device / runtime host id.
    android_flow_id
        Android-side flow/activation id assigned by the Android runtime,
        if known.
    current_execution_phase
        Most recently known :class:`AndroidExecutionPhase` for the Android
        runtime execution.  ``unknown`` when no execution events have been
        absorbed.
    last_android_execution_event
        Most recent :class:`AndroidCanonicalExecutionEvent` absorbed from
        the Android runtime, or ``None`` if no events have been absorbed.
    blocking_reason
        Human-readable description of why the flow is currently blocked,
        or ``""`` when the flow is not blocked.
    recovery_status
        Summary of recovery disposition for this flow:
        ``"not_recovered"``, ``"resumable"``, ``"replay_only"``,
        ``"reissuable"``, ``"terminal_on_interrupt"``, or ``""`` when
        recovery has not been evaluated.
    truth_alignment_status
        Summary of the most recent truth alignment decision for this flow
        from :class:`~core.flow_level_truth_ownership.FlowTruthDecisionKind`,
        e.g. ``"accept_as_authoritative"``, ``"accept_as_advisory"``,
        ``"quarantine_due_to_posture_conflict"``.  ``""`` when no alignment
        decision has been recorded.
    canonical_result_status
        Summary of the result convergence state for this flow from
        :class:`~core.flow_aware_result_convergence.ConvergenceDecisionKind`,
        e.g. ``"promote_final_as_canonical"``, ``"accept_partial_for_flow"``.
        ``""`` when no result convergence decision exists.
    created_at
        Unix timestamp when the delegated flow entity was created.
    last_updated_at
        Unix timestamp of the most recent entity update.
    review_notes
        List of human-readable notes about notable findings or evidence gaps
        encountered while building this projection.
    _source
        Provenance tag for this projection.
    """

    # Identity / lineage / delegated binding
    flow_id: str = ""
    flow_lineage_id: str = ""
    flow_segment_id: str = ""
    trace_id: str = ""
    flow_kind: str = ""
    flow_phase: str = ""

    # Object mapping (binding to existing system objects)
    canonical_task_id: str = ""
    dispatch_record_id: str = ""
    contract_id: str = ""
    binding_id: str = ""
    device_id: str = ""
    android_flow_id: str = ""

    # Android canonical execution phase summary
    current_execution_phase: str = AndroidExecutionPhase.unknown.value
    last_android_execution_event: Optional[AndroidCanonicalExecutionEvent] = None

    # V2-side absorption timestamp of the most recent Android execution event
    # absorbed for this flow.  None when no execution events have been absorbed.
    # Distinct from last_updated_at (which reflects the entity update time) —
    # this specifically tracks when the last Android-side event reached V2,
    # allowing operators to detect event ingestion staleness.
    last_event_absorbed_at: Optional[float] = None

    # Current blocking / gate / stagnation / waiting reason
    blocking_reason: str = ""

    # Recovery / truth / result convergence status
    recovery_status: str = ""
    truth_alignment_status: str = ""
    canonical_result_status: str = ""

    # Timestamps
    created_at: Optional[float] = None
    last_updated_at: Optional[float] = None

    # Operator notes
    review_notes: List[str] = field(default_factory=list)

    _source: str = "flow_level_operator_surface"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "_authority": FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY,
            "flow_id": self.flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "flow_segment_id": self.flow_segment_id,
            "trace_id": self.trace_id,
            "flow_kind": self.flow_kind,
            "flow_phase": self.flow_phase,
            "canonical_task_id": self.canonical_task_id,
            "dispatch_record_id": self.dispatch_record_id,
            "contract_id": self.contract_id,
            "binding_id": self.binding_id,
            "device_id": self.device_id,
            "android_flow_id": self.android_flow_id,
            "current_execution_phase": self.current_execution_phase,
            "last_android_execution_event": (
                self.last_android_execution_event.to_dict()
                if self.last_android_execution_event is not None
                else None
            ),
            "last_event_absorbed_at": self.last_event_absorbed_at,
            "blocking_reason": self.blocking_reason,
            "recovery_status": self.recovery_status,
            "truth_alignment_status": self.truth_alignment_status,
            "canonical_result_status": self.canonical_result_status,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "review_notes": list(self.review_notes),
            "_source": self._source,
        }


# ---------------------------------------------------------------------------
# FlowLevelOperatorSurface
# ---------------------------------------------------------------------------


class FlowLevelOperatorSurface:
    """Flow-level operator surface — canonical projection owner for delegated flows.

    This is the **sole** authority for all operator-visible state about a
    delegated flow's execution on the Android side.  It reads from canonical
    runtime projections and exposes read-only views.

    Design invariants
    -----------------
    1.  **Read-only projections only.**  No mutation of canonical state.
    2.  **Graceful degradation.**  Missing runtime layers yield default
        projections rather than raising.
    3.  **Source-annotated.**  Every projection carries a ``_source`` field.
    4.  **Authority-declared.**  Sentinels allow downstream consumers to
        verify provenance.

    Methods
    -------
    inspect_flow(flow_id)
        Return a :class:`FlowOperatorProjection` for the given
        ``delegated_flow_id``, or ``None`` if the flow is unknown.
    """

    def __init__(self) -> None:
        self._surface_id: str = f"flos_{uuid.uuid4().hex[:8]}"

    # ── Flow Inspection ──────────────────────────────────────────────────

    def inspect_flow(self, flow_id: str) -> Optional[FlowOperatorProjection]:
        """Return a read-only :class:`FlowOperatorProjection` for *flow_id*.

        Aggregates:
        - flow identity / lineage / delegated binding from
          :class:`~core.delegated_flow_entity.DelegatedFlowEntity`
        - Android canonical execution phase from absorbed execution events
          (via the FlowTruthAlignmentRuntime metadata)
        - recovery / truth / result convergence status summaries from the
          respective canonical runtime layers

        Returns ``None`` if *flow_id* is not known to the delegated flow
        entity runtime.
        """
        # ── Load the DelegatedFlowEntity ─────────────────────────────────
        entity = self._load_flow_entity(flow_id)
        if entity is None:
            return None

        proj = FlowOperatorProjection(
            flow_id=entity.identity.delegated_flow_id,
            flow_lineage_id=entity.identity.flow_lineage_id,
            flow_segment_id=entity.identity.flow_segment_id,
            trace_id=entity.identity.trace_id,
            flow_kind=entity.identity.flow_kind.value,
            flow_phase=entity.phase.value,
            canonical_task_id=entity.object_mapping.canonical_task_id,
            dispatch_record_id=entity.object_mapping.dispatch_record_id,
            contract_id=entity.object_mapping.contract_id,
            binding_id=entity.object_mapping.binding_id,
            device_id=entity.object_mapping.device_id,
            android_flow_id=entity.object_mapping.android_flow_id,
            created_at=entity.created_at,
            last_updated_at=entity.last_updated_at,
        )

        notes: List[str] = []

        # ── Android execution phase (from truth alignment metadata) ───────
        last_event, phase_summary = self._derive_android_execution_phase(flow_id)
        proj.current_execution_phase = phase_summary
        proj.last_android_execution_event = last_event
        if last_event is not None and last_event.is_blocking:
            proj.blocking_reason = last_event.blocking_reason or (
                f"Blocked at phase={last_event.phase.value}"
            )

        # ── last_event_absorbed_at — V2 ingestion timestamp of most recent event ──
        try:
            meta = getattr(entity, "metadata", None) or {}
            _ts = meta.get("_last_android_event_absorbed_at")
            if isinstance(_ts, (int, float)):
                proj.last_event_absorbed_at = float(_ts)
        except Exception:
            pass

        # ── Recovery status ───────────────────────────────────────────────
        proj.recovery_status = self._derive_recovery_status(
            entity.object_mapping.canonical_task_id
        )

        # ── Truth alignment status ────────────────────────────────────────
        proj.truth_alignment_status = self._derive_truth_alignment_status(flow_id)

        # ── Result convergence status ─────────────────────────────────────
        proj.canonical_result_status = self._derive_result_convergence_status(flow_id)

        # ── Build review notes ────────────────────────────────────────────
        if not entity.object_mapping.canonical_task_id:
            notes.append(
                "Flow has no canonical_task_id mapping — task-level "
                "inspect_task / inspect_recovery will return None."
            )
        if proj.current_execution_phase == AndroidExecutionPhase.unknown.value:
            notes.append(
                "No Android canonical execution events have been absorbed for "
                "this flow — current_execution_phase is unknown."
            )
        if proj.truth_alignment_status == "":
            notes.append(
                "No truth alignment decisions recorded for this flow — "
                "truth_alignment_status is empty."
            )
        if proj.canonical_result_status == "":
            notes.append(
                "No result convergence decisions recorded for this flow — "
                "canonical_result_status is empty."
            )
        proj.review_notes = notes
        return proj

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _load_flow_entity(flow_id: str) -> Optional[Any]:
        """Load a DelegatedFlowEntity by id, returning None on any failure."""
        try:
            from core.delegated_flow_entity import get_delegated_flow
            return get_delegated_flow(flow_id)
        except Exception as exc:
            logger.warning("_load_flow_entity(%s) failed: %s", flow_id, exc)
            return None

    @staticmethod
    def _derive_android_execution_phase(
        flow_id: str,
    ) -> Tuple[Optional[AndroidCanonicalExecutionEvent], str]:
        """Derive the current Android execution phase for *flow_id*.

        Resolution order
        ----------------
        1.  **Entity metadata** (primary) — checks ``_last_android_execution_event``
            written by :func:`~core.android_device_state_store._forward_execution_event_to_flow_surface`
            when a ``DEVICE_EXECUTION_EVENT`` is absorbed.  This is the most
            direct path: a real Android execution event carries an explicit
            phase string that should take precedence over inferred mappings.
        2.  **FlowTruthAlignmentRuntime** (fallback) — checks the most recent
            truth alignment record for an ``android_execution_phase`` evidence
            field, then falls back to ``_truth_kind_to_execution_phase`` mapping.
            This path fires when no direct execution events have been received
            but truth alignment has progressed (e.g. result delivery, cancel).

        Returns a tuple of (last_event_or_None, phase_string).  When no
        execution events have been absorbed for this flow the returned phase
        string is ``AndroidExecutionPhase.unknown.value``.
        """
        last_event: Optional[AndroidCanonicalExecutionEvent] = None
        phase_str = AndroidExecutionPhase.unknown.value

        # ── 1. Entity metadata (primary) ─────────────────────────────────
        try:
            from core.delegated_flow_entity import get_delegated_flow_entity_runtime
            runtime = get_delegated_flow_entity_runtime()
            entity = runtime.get_by_flow_id(flow_id)
            if entity is not None:
                meta = getattr(entity, "metadata", None) or {}
                ace_dict = meta.get("_last_android_execution_event")
                if isinstance(ace_dict, dict):
                    ev_phase = AndroidExecutionPhase.from_string(
                        ace_dict.get("phase", "unknown")
                    )
                    last_event = AndroidCanonicalExecutionEvent(
                        event_id=ace_dict.get("event_id", ""),
                        flow_id=flow_id,
                        phase=ev_phase,
                        step_index=ace_dict.get("step_index", -1),
                        detail=ace_dict.get("detail", ""),
                        is_blocking=bool(ace_dict.get("is_blocking", False)),
                        blocking_reason=ace_dict.get("blocking_reason", ""),
                        policy_gate=ace_dict.get("policy_gate", ""),
                        absorbed_at=ace_dict.get("absorbed_at", 0.0),
                        android_ts=ace_dict.get("android_ts"),
                        evidence=dict(ace_dict.get("evidence") or {}),
                    )
                    phase_str = ev_phase.value
                    return last_event, phase_str
        except Exception as exc:
            logger.debug(
                "_derive_android_execution_phase(%s) entity-metadata path failed: %s",
                flow_id, exc,
            )

        # ── 2. FlowTruthAlignmentRuntime (fallback) ───────────────────────
        try:
            from core.flow_level_truth_ownership import (
                get_flow_truth_alignment_runtime,
            )
            ftar = get_flow_truth_alignment_runtime()
            # get_by_flow_id returns list newest-first
            flow_records = ftar.get_by_flow_id(flow_id)
            if not flow_records:
                return last_event, phase_str

            # Most recent record (index 0) for execution-phase derivation
            latest = flow_records[0]
            ev_phase = AndroidExecutionPhase.from_string(
                latest.evidence.get("android_execution_phase", "unknown")
            )
            # Promote the truth_kind to a recognisable execution phase when
            # no explicit android_execution_phase evidence is present.
            if ev_phase is AndroidExecutionPhase.unknown:
                truth_kind = latest.evidence.get("truth_kind", "")
                ev_phase = _truth_kind_to_execution_phase(truth_kind)

            phase_str = ev_phase.value
            is_blocking = ev_phase.is_blocking()
            blocking_reason = latest.evidence.get("blocking_reason", "")
            policy_gate = latest.evidence.get("policy_gate", "")

            last_event = AndroidCanonicalExecutionEvent(
                flow_id=flow_id,
                phase=ev_phase,
                detail=latest.reason,
                is_blocking=is_blocking,
                blocking_reason=blocking_reason,
                policy_gate=policy_gate,
                absorbed_at=latest.timestamp,
                evidence=dict(latest.evidence),
            )
        except Exception as exc:
            logger.debug(
                "_derive_android_execution_phase(%s) truth-alignment path failed: %s",
                flow_id, exc,
            )

        return last_event, phase_str

    @staticmethod
    def _derive_recovery_status(canonical_task_id: str) -> str:
        """Return a recovery status string for the canonical task.

        Uses the task-level recovery inspection from OperatorSurface if a
        canonical_task_id is available.  Returns ``""`` when unavailable.
        """
        if not canonical_task_id:
            return ""
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            rec = surface.inspect_recovery(canonical_task_id)
            if rec is None:
                return "not_recovered"
            return rec.recovery_disposition or "not_recovered"
        except Exception as exc:
            logger.debug(
                "_derive_recovery_status(%s) failed: %s", canonical_task_id, exc
            )
            return ""

    @staticmethod
    def _derive_truth_alignment_status(flow_id: str) -> str:
        """Return the most recent truth alignment decision string for *flow_id*.

        Reads from the :class:`~core.flow_level_truth_ownership.FlowTruthAlignmentRuntime`
        ring-buffer via ``get_by_flow_id``.  Returns ``""`` when no decisions
        have been recorded.
        """
        try:
            from core.flow_level_truth_ownership import (
                get_flow_truth_alignment_runtime,
            )
            runtime = get_flow_truth_alignment_runtime()
            flow_records = runtime.get_by_flow_id(flow_id)
            if not flow_records:
                return ""
            latest = flow_records[0]
            decision_val = latest.decision
            if hasattr(decision_val, "value"):
                return decision_val.value
            return str(decision_val)
        except Exception as exc:
            logger.debug(
                "_derive_truth_alignment_status(%s) failed: %s", flow_id, exc
            )
            return ""

    @staticmethod
    def _derive_result_convergence_status(flow_id: str) -> str:
        """Return the most recent result convergence decision string for *flow_id*.

        Reads from the :class:`~core.flow_aware_result_convergence.FlowAwareConvergenceCoordinator`
        ring-buffer by filtering on ``flow_id``.  Returns ``""`` when no
        convergence decisions have been recorded for this flow.
        """
        try:
            from core.flow_aware_result_convergence import (
                get_flow_aware_convergence_coordinator,
            )
            coordinator = get_flow_aware_convergence_coordinator()
            artifacts = coordinator.list_recent_artifacts(max_count=256)
            # list_recent_artifacts returns oldest-first; iterate newest-first
            for art in reversed(artifacts):
                if art.flow_id == flow_id:
                    if hasattr(art.decision, "value"):
                        return art.decision.value
                    return str(art.decision)
            return ""
        except Exception as exc:
            logger.debug(
                "_derive_result_convergence_status(%s) failed: %s", flow_id, exc
            )
            return ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truth_kind_to_execution_phase(truth_kind: str) -> AndroidExecutionPhase:
    """Map a FlowTruthSemanticKind string to the closest AndroidExecutionPhase.

    This is a best-effort mapping used when no explicit
    ``android_execution_phase`` evidence field is present in a truth alignment
    record.  It allows the operator surface to derive a coarse execution phase
    from the truth kind even before Android PR7 sends explicit phase events.

    Mapping rationale
    -----------------
    * ``result`` / ``task_phase`` completed → execution completed
    * ``cancel`` / ``failure`` → execution failed
    * ``partial_result`` / ``execution_evidence`` → execution (in progress)
    * ``planning`` → planning phase
    * ``grounding`` → grounding phase
    * ``replan`` → replan
    * ``stagnation`` → stagnation
    * ``gate_decision`` → gate_decision
    * everything else → unknown
    """
    _MAP: Dict[str, AndroidExecutionPhase] = {
        "result": AndroidExecutionPhase.completed,
        "task_phase": AndroidExecutionPhase.execution,
        "cancel": AndroidExecutionPhase.failed,
        "failure": AndroidExecutionPhase.failed,
        "partial_result": AndroidExecutionPhase.execution,
        "execution_evidence": AndroidExecutionPhase.execution,
        "planning": AndroidExecutionPhase.planning,
        "grounding": AndroidExecutionPhase.grounding,
        "replan": AndroidExecutionPhase.replan,
        "stagnation": AndroidExecutionPhase.stagnation,
        "gate_decision": AndroidExecutionPhase.gate_decision,
        "takeover": AndroidExecutionPhase.takeover,
        "collaboration": AndroidExecutionPhase.collaboration,
    }
    if not isinstance(truth_kind, str):
        return AndroidExecutionPhase.unknown
    return _MAP.get(truth_kind.lower().strip(), AndroidExecutionPhase.unknown)


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_FLOW_SURFACE: Optional[FlowLevelOperatorSurface] = None


def get_flow_level_operator_surface() -> FlowLevelOperatorSurface:
    """Return the singleton :class:`FlowLevelOperatorSurface` instance."""
    global _FLOW_SURFACE
    if _FLOW_SURFACE is None:
        _FLOW_SURFACE = FlowLevelOperatorSurface()
    return _FLOW_SURFACE


def reset_flow_level_operator_surface() -> None:
    """Reset the singleton — for testing only."""
    global _FLOW_SURFACE
    _FLOW_SURFACE = None
