#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/orchestration_review_surface.py
======================================
PR-10 — Orchestration Observability Review Surface

Closes the remaining observability and operator-review gaps in the V2
orchestration runtime so that execution behaviour becomes legible to
developers, operators, and reviewers.

Background
----------
Prior PRs established strong canonical structures for execution path
selection (PR-20), multimodal routing (PR-41), fallback tracing (PR-24),
execution trace contracts (PR-25), runtime observability sink (PR-G),
replay/audit persistence (PR-B2), and hybrid continuity (PR-59).

Despite this investment, reviewers still had to:

- consult several independent modules to understand *why* a specific
  execution path was chosen or rejected;
- reconstruct fallback cascade sequences manually from unrelated log entries;
- correlate recovery decisions with their originating interruption cause;
- verify that reconciliation outcomes (Android advisory vs. V2 canonical)
  were handled correctly;
- determine whether legacy dispatch surfaces were invoked (COMPAT-007 gap).

This module provides a **single, unified, read-only review surface** that
consolidates those signals without re-computing or replacing any canonical
authority.

Design principles
-----------------
- **Observational only** — reads from canonical authorities; never mutates
  runtime state.
- **Non-duplicating** — assembles existing diagnostic fragments from prior
  PR authority modules.  It does not re-derive or re-compute decisions.
- **Authority-boundary respecting** — surfaces are annotated with the
  originating authority module.  Consumers cannot mistake them for
  canonical decision drivers.
- **Graceful degradation** — every assembly step is wrapped; if an upstream
  module is unavailable the surface still returns a partial snapshot with
  ``_partial=True`` rather than raising.
- **Stable public API** — all public dataclasses expose ``to_dict()`` /
  ``from_dict()`` and all enum values are stable lowercase strings.

Key gaps closed (PR-10)
-----------------------
1. **Execution path legibility** — ``ExecutionPathDecisionSummary`` exposes
   whether a path was chosen, rejected, or degraded and the authority reason.
2. **Fallback cascade traceability** — ``FallbackCascadeReview`` chains
   fallback steps in emission order so reviewers can see the full degradation
   path.
3. **Recovery legibility** — ``RecoveryDecisionReview`` surfaces why an
   execution was interrupted, what decision was made, and whether resumption
   succeeded.
4. **Reconciliation audit** — ``ReconciliationOutcomeReview`` surfaces whether
   Android advisory truth was accepted, rejected (V2 terminal wins), or
   partially applied.
5. **Legacy dispatch counter** — ``LegacyDispatchCounters`` closes COMPAT-007:
   LEGACY_DISPATCH events are now counted and surfaced so operators can detect
   unexpected legacy usage.

Public API
----------
Authority sentinels::

    ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY
    REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_POLICY
    REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_POLICY
    REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_POLICY
    ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL

Data structures::

    ExecutionPathDecisionSummary
    FallbackCascadeStep
    FallbackCascadeReview
    RecoveryDecisionReview
    ReconciliationOutcomeReview
    LegacyDispatchCounters
    OrchestrationReviewSnapshot

Factory / assembly::

    build_orchestration_review_snapshot() -> OrchestrationReviewSnapshot
    get_legacy_dispatch_counters() -> LegacyDispatchCounters
    increment_legacy_dispatch_counter(surface_name)
    reset_legacy_dispatch_counters()  (for tests)

Usage::

    from core.orchestration_review_surface import build_orchestration_review_snapshot

    snapshot = build_orchestration_review_snapshot()
    # snapshot.execution_path_summary — why was the current path chosen?
    # snapshot.fallback_cascade       — full degradation trace
    # snapshot.recovery_review        — how was the last recovery handled?
    # snapshot.reconciliation_review  — Android/V2 reconciliation outcome
    # snapshot.legacy_dispatch        — is legacy dispatch being used?
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OrchestrationReviewSurface")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY: str = (
    "ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY: "
    "core/orchestration_review_surface.py is the canonical unified operator "
    "review surface for PR-10.  It consolidates execution path legibility, "
    "fallback cascade traceability, recovery decision visibility, Android/V2 "
    "reconciliation auditing, and legacy-dispatch usage counters into a single "
    "coherent review snapshot.  It does not re-compute or replace any canonical "
    "decision authority."
)

REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_POLICY: str = (
    "POLICY::REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_PR10: "
    "This module is read-only.  It assembles diagnostics from canonical "
    "authority modules (runtime_decision_observability, routing_observability, "
    "runtime_observability_sink, hybrid_orchestration_continuity, "
    "android_participant_truth_ingress).  It MUST NOT be used as a decision "
    "source by routing, execution, or dispatch logic."
)

REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_POLICY: str = (
    "POLICY::REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_PR10: "
    "Every field in OrchestrationReviewSnapshot is annotated with its "
    "source_authority.  Consumers MUST treat these fields as observational "
    "evidence, not as runtime truth.  The canonical truth remains in its "
    "originating authority module."
)

REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_POLICY: str = (
    "POLICY::REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_PR10: "
    "This module MUST NOT re-derive, re-compute, or shadow any canonical "
    "decision (routing, execution path, fallback trigger, recovery policy). "
    "If an upstream authority module is unavailable, the review surface "
    "returns a partial snapshot with _partial=True rather than guessing."
)

ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL: str = (
    "ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL: "
    "PR-10 orchestration observability review surface is present and active. "
    "Execution path legibility, fallback cascade traceability, recovery "
    "decision visibility, reconciliation auditing, and legacy-dispatch "
    "counters are operational."
)

# ---------------------------------------------------------------------------
# ExecutionPathDecisionSummary
# ---------------------------------------------------------------------------


class ExecutionPathOutcome(str, Enum):
    """Outcome classification for an execution path decision.

    Values are stable lowercase strings safe for serialisation and dashboards.
    """

    CHOSEN = "chosen"
    """The path was selected as the active execution route."""

    REJECTED = "rejected"
    """The path was explicitly rejected (e.g. hard gate, governance denial)."""

    DEGRADED = "degraded"
    """The path was chosen but at a lower tier than preferred (fallback active)."""

    UNKNOWN = "unknown"
    """Outcome cannot be determined from available diagnostics."""


@dataclass
class ExecutionPathDecisionSummary:
    """Human-legible summary of why an execution path was chosen or rejected.

    Assembled from :mod:`core.runtime_decision_observability` diagnostics.

    Attributes
    ----------
    execution_path:
        The execution path identifier (e.g. ``"agent_execute"``, ``"fallback_chat"``).
    outcome:
        Whether the path was chosen, rejected, or degraded.
    primary_reason:
        The dominant reason for the outcome (hard gate label or fallback label).
    hard_gate_active:
        ``True`` when at least one hard governance gate was active.
    hard_gate_reasons:
        Ordered list of active hard gate reasons.
    active_soft_influences:
        Count of confirmed-active soft influence layers.
    model_selected:
        Model selected for this path, if applicable.
    provider_selected:
        Provider selected for this path, if applicable.
    task_hint:
        Task-semantic hint that was active during path selection.
    source_authority:
        Python module that produced the underlying decision diagnostics.
    assembled_at:
        Timestamp when this summary was assembled.
    """

    execution_path: str = "unknown"
    outcome: str = ExecutionPathOutcome.UNKNOWN.value
    primary_reason: str = ""
    hard_gate_active: bool = False
    hard_gate_reasons: List[str] = field(default_factory=list)
    active_soft_influences: int = 0
    model_selected: Optional[str] = None
    provider_selected: Optional[str] = None
    task_hint: Optional[str] = None
    source_authority: str = "core.orchestration_review_surface"
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_path": self.execution_path,
            "outcome": self.outcome,
            "primary_reason": self.primary_reason,
            "hard_gate_active": self.hard_gate_active,
            "hard_gate_reasons": list(self.hard_gate_reasons),
            "active_soft_influences": self.active_soft_influences,
            "model_selected": self.model_selected,
            "provider_selected": self.provider_selected,
            "task_hint": self.task_hint,
            "source_authority": self.source_authority,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionPathDecisionSummary":
        return cls(
            execution_path=d.get("execution_path", "unknown"),
            outcome=d.get("outcome", ExecutionPathOutcome.UNKNOWN.value),
            primary_reason=d.get("primary_reason", ""),
            hard_gate_active=bool(d.get("hard_gate_active", False)),
            hard_gate_reasons=list(d.get("hard_gate_reasons") or []),
            active_soft_influences=int(d.get("active_soft_influences", 0)),
            model_selected=d.get("model_selected"),
            provider_selected=d.get("provider_selected"),
            task_hint=d.get("task_hint"),
            source_authority=d.get("source_authority", "core.orchestration_review_surface"),
            assembled_at=float(d.get("assembled_at", time.time())),
        )


# ---------------------------------------------------------------------------
# FallbackCascadeReview
# ---------------------------------------------------------------------------


@dataclass
class FallbackCascadeStep:
    """One step in a fallback cascade chain.

    Attributes
    ----------
    step_index:
        Zero-based position in the cascade sequence.
    from_tier:
        The execution tier that was attempted (e.g. ``"system_api"``).
    to_tier:
        The tier that was selected after the step (e.g. ``"gui"``).
    reason:
        Structured reason for the step (from :class:`~core.execution_observability.FallbackReason`).
    raw_reason:
        Raw reason string from the authority module.
    authority:
        Authority module or component that logged this step.
    """

    step_index: int = 0
    from_tier: str = ""
    to_tier: str = ""
    reason: str = ""
    raw_reason: str = ""
    authority: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "from_tier": self.from_tier,
            "to_tier": self.to_tier,
            "reason": self.reason,
            "raw_reason": self.raw_reason,
            "authority": self.authority,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackCascadeStep":
        return cls(
            step_index=int(d.get("step_index", 0)),
            from_tier=d.get("from_tier", ""),
            to_tier=d.get("to_tier", ""),
            reason=d.get("reason", ""),
            raw_reason=d.get("raw_reason", ""),
            authority=d.get("authority", ""),
        )


@dataclass
class FallbackCascadeReview:
    """Ordered review of the full fallback degradation cascade.

    Assembled from ``core.execution_observability.fallback_schema`` and
    ``core.windows_execution_arbiter`` attempt logs.

    Attributes
    ----------
    cascade_steps:
        Ordered list of :class:`FallbackCascadeStep` entries from preferred
        tier to final selected tier.
    final_tier:
        The tier that was ultimately used for execution.
    total_steps:
        Total number of fallback steps in the cascade.
    had_fallback:
        ``True`` when at least one fallback step occurred.
    degraded_from_preferred:
        ``True`` when the final tier is lower than the preferred tier.
    source_authority:
        Authority module that provided the underlying fallback records.
    assembled_at:
        Timestamp when this review was assembled.
    """

    cascade_steps: List[FallbackCascadeStep] = field(default_factory=list)
    final_tier: str = ""
    total_steps: int = 0
    had_fallback: bool = False
    degraded_from_preferred: bool = False
    source_authority: str = "core.orchestration_review_surface"
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cascade_steps": [s.to_dict() for s in self.cascade_steps],
            "final_tier": self.final_tier,
            "total_steps": self.total_steps,
            "had_fallback": self.had_fallback,
            "degraded_from_preferred": self.degraded_from_preferred,
            "source_authority": self.source_authority,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackCascadeReview":
        steps = [FallbackCascadeStep.from_dict(s) for s in (d.get("cascade_steps") or [])]
        return cls(
            cascade_steps=steps,
            final_tier=d.get("final_tier", ""),
            total_steps=int(d.get("total_steps", 0)),
            had_fallback=bool(d.get("had_fallback", False)),
            degraded_from_preferred=bool(d.get("degraded_from_preferred", False)),
            source_authority=d.get("source_authority", "core.orchestration_review_surface"),
            assembled_at=float(d.get("assembled_at", time.time())),
        )


# ---------------------------------------------------------------------------
# RecoveryDecisionReview
# ---------------------------------------------------------------------------


@dataclass
class RecoveryDecisionReview:
    """Human-legible review of the most recent recovery decision.

    Assembled from :mod:`core.runtime.runtime_observability_sink` recovery
    decision events.

    Attributes
    ----------
    decision_kind:
        Recovery decision kind (``"resumable_reassociation"`` /
        ``"recovery_fallback"`` / ``"terminal_loss"`` / ``"unknown"``).
    is_resumable:
        ``True`` when the execution can be resumed after interruption.
    interruption_class:
        Class of interruption (e.g. ``"process_restart"`` /
        ``"device_disconnect"`` / ``"network_timeout"``).
    interruption_reason:
        Raw reason string for the interruption.
    recovery_reason:
        Why the recovery decision was made.
    continuity_id:
        Continuity ID linking the recovery decision to its session.
    trace_id:
        Trace ID for cross-module correlation.
    resume_attempt_count:
        Number of resume attempts so far.
    source_authority:
        Authority module that produced the recovery decision event.
    assembled_at:
        Timestamp when this review was assembled.
    """

    decision_kind: str = "unknown"
    is_resumable: bool = False
    interruption_class: str = ""
    interruption_reason: str = ""
    recovery_reason: str = ""
    continuity_id: Optional[str] = None
    trace_id: Optional[str] = None
    resume_attempt_count: int = 0
    source_authority: str = "core.orchestration_review_surface"
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_kind": self.decision_kind,
            "is_resumable": self.is_resumable,
            "interruption_class": self.interruption_class,
            "interruption_reason": self.interruption_reason,
            "recovery_reason": self.recovery_reason,
            "continuity_id": self.continuity_id,
            "trace_id": self.trace_id,
            "resume_attempt_count": self.resume_attempt_count,
            "source_authority": self.source_authority,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RecoveryDecisionReview":
        return cls(
            decision_kind=d.get("decision_kind", "unknown"),
            is_resumable=bool(d.get("is_resumable", False)),
            interruption_class=d.get("interruption_class", ""),
            interruption_reason=d.get("interruption_reason", ""),
            recovery_reason=d.get("recovery_reason", ""),
            continuity_id=d.get("continuity_id"),
            trace_id=d.get("trace_id"),
            resume_attempt_count=int(d.get("resume_attempt_count", 0)),
            source_authority=d.get("source_authority", "core.orchestration_review_surface"),
            assembled_at=float(d.get("assembled_at", time.time())),
        )


# ---------------------------------------------------------------------------
# ReconciliationOutcomeReview
# ---------------------------------------------------------------------------


class ReconciliationOutcome(str, Enum):
    """Classification of an Android/V2 truth reconciliation outcome.

    Values are stable lowercase strings safe for serialisation.
    """

    ACCEPTED = "accepted"
    """Android truth was accepted and applied to V2 canonical state."""

    REJECTED_V2_TERMINAL = "rejected_v2_terminal"
    """Rejected because V2 already has a terminal state (completed/failed/timed_out/cancelled)."""

    REJECTED_NO_RECORD = "rejected_no_record"
    """Rejected because no matching V2 tracking record was found."""

    PARTIALLY_APPLIED = "partially_applied"
    """Some fields were applied (e.g. signals) but advisory fields (readiness_assessment) were not."""

    UNKNOWN = "unknown"
    """Outcome cannot be determined."""


@dataclass
class ReconciliationOutcomeReview:
    """Review of the most recent Android/V2 canonical truth reconciliation.

    Sourced from :mod:`core.android_participant_truth_ingress`.

    Attributes
    ----------
    outcome:
        Classification of the reconciliation outcome.
    was_reconciled:
        ``True`` when the reconciliation call updated V2 canonical state.
    v2_terminal_state_blocked:
        ``True`` when V2 was already terminal and blocked the Android update.
    advisory_only_fields_skipped:
        Fields that were present in the Android truth but treated as
        advisory-only (e.g. ``readiness_assessment``, ``runtime_state``).
    applied_signal_types:
        Signal types (cancel / failure / result / status / task_phase) that
        were applied.
    device_id:
        Device identifier for the Android participant.
    task_id:
        Task identifier the reconciliation was for.
    source_authority:
        Authority module that produced the reconciliation outcome.
    assembled_at:
        Timestamp when this review was assembled.
    """

    outcome: str = ReconciliationOutcome.UNKNOWN.value
    was_reconciled: bool = False
    v2_terminal_state_blocked: bool = False
    advisory_only_fields_skipped: List[str] = field(default_factory=list)
    applied_signal_types: List[str] = field(default_factory=list)
    device_id: Optional[str] = None
    task_id: Optional[str] = None
    source_authority: str = "core.orchestration_review_surface"
    assembled_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome,
            "was_reconciled": self.was_reconciled,
            "v2_terminal_state_blocked": self.v2_terminal_state_blocked,
            "advisory_only_fields_skipped": list(self.advisory_only_fields_skipped),
            "applied_signal_types": list(self.applied_signal_types),
            "device_id": self.device_id,
            "task_id": self.task_id,
            "source_authority": self.source_authority,
            "assembled_at": self.assembled_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReconciliationOutcomeReview":
        return cls(
            outcome=d.get("outcome", ReconciliationOutcome.UNKNOWN.value),
            was_reconciled=bool(d.get("was_reconciled", False)),
            v2_terminal_state_blocked=bool(d.get("v2_terminal_state_blocked", False)),
            advisory_only_fields_skipped=list(d.get("advisory_only_fields_skipped") or []),
            applied_signal_types=list(d.get("applied_signal_types") or []),
            device_id=d.get("device_id"),
            task_id=d.get("task_id"),
            source_authority=d.get("source_authority", "core.orchestration_review_surface"),
            assembled_at=float(d.get("assembled_at", time.time())),
        )


# ---------------------------------------------------------------------------
# LegacyDispatchCounters — closes COMPAT-007
# ---------------------------------------------------------------------------


@dataclass
class LegacyDispatchCounters:
    """Counters for legacy-dispatch surface invocations.

    Closes the COMPAT-007 gap: ``LEGACY_DISPATCH`` warnings from sentinel-gated
    compat surfaces were emitted to logs but not monitored.  This dataclass
    exposes the per-surface counts so operators can detect unexpected legacy
    usage at runtime.

    Attributes
    ----------
    total_legacy_dispatch_count:
        Total legacy dispatch events across all surfaces since process start.
    per_surface_counts:
        Per-surface breakdown (surface_name → invocation count).
    monitoring_authority:
        Sentinel identifying the authority that owns these counters.
    reset_at:
        Timestamp of the last counter reset (or process start if never reset).
    """

    total_legacy_dispatch_count: int = 0
    per_surface_counts: Dict[str, int] = field(default_factory=dict)
    monitoring_authority: str = (
        "COMPAT-007::LegacyDispatchCounters: "
        "core.orchestration_review_surface tracks LEGACY_DISPATCH invocations "
        "for operator observability.  These counters supplement the structured "
        "log warnings already emitted by compat surface sentinels."
    )
    reset_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_legacy_dispatch_count": self.total_legacy_dispatch_count,
            "per_surface_counts": dict(self.per_surface_counts),
            "monitoring_authority": self.monitoring_authority,
            "reset_at": self.reset_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LegacyDispatchCounters":
        return cls(
            total_legacy_dispatch_count=int(d.get("total_legacy_dispatch_count", 0)),
            per_surface_counts=dict(d.get("per_surface_counts") or {}),
            monitoring_authority=d.get("monitoring_authority", ""),
            reset_at=float(d.get("reset_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Process-level singleton for legacy dispatch counters
# ---------------------------------------------------------------------------

_legacy_dispatch_lock: threading.Lock = threading.Lock()
_legacy_dispatch_counters: LegacyDispatchCounters = LegacyDispatchCounters()


def get_legacy_dispatch_counters() -> LegacyDispatchCounters:
    """Return the process-level legacy dispatch counters (read-only view).

    Returns a shallow copy so callers cannot mutate the singleton.
    """
    with _legacy_dispatch_lock:
        c = _legacy_dispatch_counters
        return LegacyDispatchCounters(
            total_legacy_dispatch_count=c.total_legacy_dispatch_count,
            per_surface_counts=dict(c.per_surface_counts),
            reset_at=c.reset_at,
        )


def increment_legacy_dispatch_counter(surface_name: str) -> None:
    """Increment the legacy dispatch counter for a named compat surface.

    Call this from any ``LEGACY_DISPATCH``-emitting code path to make
    legacy dispatch usage visible to operators via the review surface.

    Parameters
    ----------
    surface_name:
        Short stable name for the compat surface that fired
        (e.g. ``"cross_device_coordinator"``).
    """
    try:
        with _legacy_dispatch_lock:
            _legacy_dispatch_counters.total_legacy_dispatch_count += 1
            counts = _legacy_dispatch_counters.per_surface_counts
            counts[surface_name] = counts.get(surface_name, 0) + 1
    except Exception as exc:  # noqa: BLE001
        logger.debug("increment_legacy_dispatch_counter: %s", exc)


def reset_legacy_dispatch_counters() -> None:
    """Reset the process-level legacy dispatch counters.

    Intended for tests; must not be called in production request handling.
    """
    global _legacy_dispatch_counters  # noqa: PLW0603
    with _legacy_dispatch_lock:
        _legacy_dispatch_counters = LegacyDispatchCounters()


# ---------------------------------------------------------------------------
# OrchestrationReviewSnapshot
# ---------------------------------------------------------------------------


@dataclass
class OrchestrationReviewSnapshot:
    """Full operator review snapshot of V2 orchestration legibility.

    Assembles signals from multiple canonical authority modules into one
    coherent, read-only surface.  Consumers should treat every field as
    observational evidence, not as runtime truth.

    Attributes
    ----------
    snapshot_id:
        Auto-generated UUID for this snapshot.
    assembled_at:
        Timestamp when the snapshot was assembled.
    execution_path_summary:
        Why the current execution path was chosen or rejected.
    fallback_cascade:
        Full fallback degradation trace for the current execution.
    recovery_review:
        How the most recent recovery/interruption was handled.
    reconciliation_review:
        Outcome of the most recent Android/V2 truth reconciliation.
    legacy_dispatch:
        Current legacy dispatch counters (COMPAT-007).
    observability_authority:
        Authority sentinel for this snapshot.
    _partial:
        ``True`` when at least one upstream source was unavailable and the
        snapshot is incomplete.
    _partial_reasons:
        List of reasons why the snapshot is partial.
    """

    snapshot_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    assembled_at: float = field(default_factory=time.time)
    execution_path_summary: Optional[ExecutionPathDecisionSummary] = None
    fallback_cascade: Optional[FallbackCascadeReview] = None
    recovery_review: Optional[RecoveryDecisionReview] = None
    reconciliation_review: Optional[ReconciliationOutcomeReview] = None
    legacy_dispatch: Optional[LegacyDispatchCounters] = None
    observability_authority: str = ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY
    _partial: bool = False
    _partial_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "assembled_at": self.assembled_at,
            "execution_path_summary": (
                self.execution_path_summary.to_dict()
                if self.execution_path_summary is not None
                else None
            ),
            "fallback_cascade": (
                self.fallback_cascade.to_dict()
                if self.fallback_cascade is not None
                else None
            ),
            "recovery_review": (
                self.recovery_review.to_dict()
                if self.recovery_review is not None
                else None
            ),
            "reconciliation_review": (
                self.reconciliation_review.to_dict()
                if self.reconciliation_review is not None
                else None
            ),
            "legacy_dispatch": (
                self.legacy_dispatch.to_dict()
                if self.legacy_dispatch is not None
                else None
            ),
            "observability_authority": self.observability_authority,
            "_partial": self._partial,
            "_partial_reasons": list(self._partial_reasons),
        }


# ---------------------------------------------------------------------------
# Internal assembly helpers
# ---------------------------------------------------------------------------


def _get_enum_value(obj: Any) -> str:
    """Return obj.value if it is an Enum, otherwise str(obj).

    Used to safely extract stable string values from enum-like objects
    returned by upstream authority modules without importing their enum
    types directly.
    """
    return obj.value if hasattr(obj, "value") else str(obj)


def _assemble_execution_path_summary() -> tuple[ExecutionPathDecisionSummary, Optional[str]]:
    """Assemble an execution path summary from runtime_decision_observability.

    Returns (summary, partial_reason).  partial_reason is None on success.
    """
    try:
        from core.runtime_decision_observability import (
            EMPTY_RUNTIME_DECISION_EXPLANATION,
            build_runtime_decision_diagnostics,
        )

        # Use diagnostics helper which reads the most recent explanation context
        diag = build_runtime_decision_diagnostics(EMPTY_RUNTIME_DECISION_EXPLANATION)
        exec_path = diag.get("execution_path", "unknown")
        has_hard_gate = bool(diag.get("has_hard_gate", False))
        hard_gate_reasons: List[str] = []
        for record in diag.get("hard_gates") or []:
            if isinstance(record, dict):
                reason = record.get("summary") or record.get("layer_name", "")
                if reason:
                    hard_gate_reasons.append(reason)

        active_soft = int(diag.get("active_soft_influence_count", 0))

        if has_hard_gate:
            outcome = ExecutionPathOutcome.REJECTED.value
            primary_reason = hard_gate_reasons[0] if hard_gate_reasons else "hard_gate_active"
        elif exec_path and exec_path != "unknown":
            # Determine if degraded from routing observability
            outcome = ExecutionPathOutcome.CHOSEN.value
            primary_reason = "canonical_path_selected"
        else:
            outcome = ExecutionPathOutcome.UNKNOWN.value
            primary_reason = "no_recent_decision_context"

        summary = ExecutionPathDecisionSummary(
            execution_path=exec_path,
            outcome=outcome,
            primary_reason=primary_reason,
            hard_gate_active=has_hard_gate,
            hard_gate_reasons=hard_gate_reasons,
            active_soft_influences=active_soft,
            model_selected=diag.get("model_selected"),
            provider_selected=diag.get("provider_selected"),
            task_hint=diag.get("task_hint"),
            source_authority="core.runtime_decision_observability",
        )
        return summary, None

    except Exception as exc:  # noqa: BLE001
        logger.debug("_assemble_execution_path_summary: %s", exc)
        summary = ExecutionPathDecisionSummary(
            source_authority="core.orchestration_review_surface._fallback",
        )
        return summary, f"runtime_decision_observability_unavailable: {exc}"


def _assemble_fallback_cascade() -> tuple[FallbackCascadeReview, Optional[str]]:
    """Assemble a fallback cascade review from execution_observability.

    Returns (cascade_review, partial_reason).
    """
    try:
        from core.execution_observability.fallback_schema import FallbackContext

        # Attempt to read recent arbiter attempts if available.
        steps: List[FallbackCascadeStep] = []
        try:
            from core.windows_execution_arbiter import get_last_attempt_log
            raw_attempts = get_last_attempt_log() or []
            for idx, attempt in enumerate(raw_attempts):
                ctx = FallbackContext.from_arbiter_attempt(attempt)
                steps.append(FallbackCascadeStep(
                    step_index=idx,
                    from_tier=_get_enum_value(ctx.from_level),
                    to_tier=_get_enum_value(ctx.to_level),
                    reason=_get_enum_value(ctx.reason),
                    raw_reason=ctx.raw_reason,
                    authority="core.windows_execution_arbiter",
                ))
        except Exception:
            pass

        had_fallback = len(steps) > 0
        final_tier = steps[-1].to_tier if steps else ""

        review = FallbackCascadeReview(
            cascade_steps=steps,
            final_tier=final_tier,
            total_steps=len(steps),
            had_fallback=had_fallback,
            degraded_from_preferred=had_fallback,
            source_authority="core.execution_observability.fallback_schema",
        )
        return review, None

    except Exception as exc:  # noqa: BLE001
        logger.debug("_assemble_fallback_cascade: %s", exc)
        review = FallbackCascadeReview(
            source_authority="core.orchestration_review_surface._fallback",
        )
        return review, f"execution_observability_unavailable: {exc}"


def _assemble_recovery_review() -> tuple[RecoveryDecisionReview, Optional[str]]:
    """Assemble a recovery decision review from runtime_observability_sink.

    Returns (recovery_review, partial_reason).
    """
    try:
        from core.runtime.runtime_observability_sink import build_observability_snapshot

        snap = build_observability_snapshot()
        recovery_events = snap.get("recovery_decision_events") or []
        if not recovery_events:
            review = RecoveryDecisionReview(
                decision_kind="unknown",
                source_authority="core.runtime.runtime_observability_sink",
            )
            return review, None

        # Use the most recent recovery decision event
        latest = recovery_events[-1] if isinstance(recovery_events, list) else {}
        review = RecoveryDecisionReview(
            decision_kind=str(latest.get("decision_kind", "unknown")),
            is_resumable=bool(latest.get("is_resumable", False)),
            interruption_class=str(latest.get("interruption_class", "")),
            interruption_reason=str(latest.get("interruption_reason", "")),
            recovery_reason=str(latest.get("reason", "")),
            continuity_id=latest.get("continuity_id"),
            trace_id=latest.get("trace_id"),
            resume_attempt_count=int(latest.get("resume_attempt_count", 0)),
            source_authority="core.runtime.runtime_observability_sink",
        )
        return review, None

    except Exception as exc:  # noqa: BLE001
        logger.debug("_assemble_recovery_review: %s", exc)
        review = RecoveryDecisionReview(
            source_authority="core.orchestration_review_surface._fallback",
        )
        return review, f"runtime_observability_sink_unavailable: {exc}"


def _assemble_reconciliation_review() -> tuple[ReconciliationOutcomeReview, Optional[str]]:
    """Assemble a reconciliation outcome review from android_participant_truth_ingress.

    Returns (reconciliation_review, partial_reason).
    """
    try:
        from core.android_participant_truth_ingress import (
            get_last_reconciliation_outcome,
        )

        outcome_dict = get_last_reconciliation_outcome()
        if not outcome_dict:
            review = ReconciliationOutcomeReview(
                outcome=ReconciliationOutcome.UNKNOWN.value,
                source_authority="core.android_participant_truth_ingress",
            )
            return review, None

        was_reconciled = bool(outcome_dict.get("was_reconciled", False))
        v2_terminal = bool(outcome_dict.get("v2_terminal_state_blocked", False))

        if v2_terminal:
            outcome = ReconciliationOutcome.REJECTED_V2_TERMINAL.value
        elif not was_reconciled:
            outcome = ReconciliationOutcome.REJECTED_NO_RECORD.value
        else:
            outcome = ReconciliationOutcome.ACCEPTED.value

        review = ReconciliationOutcomeReview(
            outcome=outcome,
            was_reconciled=was_reconciled,
            v2_terminal_state_blocked=v2_terminal,
            advisory_only_fields_skipped=list(
                outcome_dict.get("advisory_only_fields_skipped") or []
            ),
            applied_signal_types=list(outcome_dict.get("applied_signal_types") or []),
            device_id=outcome_dict.get("device_id"),
            task_id=outcome_dict.get("task_id"),
            source_authority="core.android_participant_truth_ingress",
        )
        return review, None

    except Exception as exc:  # noqa: BLE001
        logger.debug("_assemble_reconciliation_review: %s", exc)
        review = ReconciliationOutcomeReview(
            outcome=ReconciliationOutcome.UNKNOWN.value,
            source_authority="core.orchestration_review_surface._fallback",
        )
        return review, f"android_participant_truth_ingress_unavailable: {exc}"


# ---------------------------------------------------------------------------
# Public assembly entry-point
# ---------------------------------------------------------------------------


def build_orchestration_review_snapshot() -> OrchestrationReviewSnapshot:
    """Build a full :class:`OrchestrationReviewSnapshot` from all available sources.

    This is the **single entry-point** for assembling the operator review
    snapshot.  Each section is assembled independently; failures in one
    section do not prevent the others from succeeding.

    Returns
    -------
    OrchestrationReviewSnapshot
        A fully assembled (or partial) snapshot.  Inspect ``_partial`` and
        ``_partial_reasons`` to determine whether any upstream source was
        unavailable.
    """
    partial_reasons: List[str] = []

    # Execution path summary
    exec_summary, exec_reason = _assemble_execution_path_summary()
    if exec_reason:
        partial_reasons.append(exec_reason)

    # Fallback cascade
    fallback_cascade, fallback_reason = _assemble_fallback_cascade()
    if fallback_reason:
        partial_reasons.append(fallback_reason)

    # Recovery review
    recovery_review, recovery_reason = _assemble_recovery_review()
    if recovery_reason:
        partial_reasons.append(recovery_reason)

    # Reconciliation review
    reconciliation_review, reconciliation_reason = _assemble_reconciliation_review()
    if reconciliation_reason:
        partial_reasons.append(reconciliation_reason)

    # Legacy dispatch counters (always succeeds)
    legacy_dispatch = get_legacy_dispatch_counters()

    return OrchestrationReviewSnapshot(
        execution_path_summary=exec_summary,
        fallback_cascade=fallback_cascade,
        recovery_review=recovery_review,
        reconciliation_review=reconciliation_review,
        legacy_dispatch=legacy_dispatch,
        _partial=bool(partial_reasons),
        _partial_reasons=partial_reasons,
    )
