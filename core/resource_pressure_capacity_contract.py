#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/resource_pressure_capacity_contract.py
=============================================
PR-17: Resource Pressure / Degraded-Capacity / Admission Semantics Contract.

Background
----------
The Galaxy V2 system already possesses substantial resource management and
execution infrastructure: task lifecycle, participant readiness, execution
policy, scheduling / admission, backpressure signals, degraded-operation
envelopes, and recovery / resilience surfaces.  This demonstrates that the
system is not oblivious to resource constraints.

However, before this module the system had no formal operational contract that
distinguished *having some remaining capacity* from *operating at normal
capacity*.  The practical risk was silent optimism: a system still accepting
some tasks under resource pressure could be classified — or report itself — as
"fully operational / normal capacity" merely because it had not yet become
completely unavailable.

Specifically, the following distinctions were absent:

* **normal_capacity** vs **degraded_capacity** — is the system operating at
  its expected throughput and latency envelopes with no active resource
  pressure, or has performance degraded below the nominal baseline due to
  resource constraints?
* **admission_limited** — the system is actively gating admission; some
  arriving tasks are being queued, deferred, or rejected at the admission
  boundary.  This is NOT normal_capacity even if currently-admitted tasks are
  running.
* **best_effort_only** — the system is operating with severely degraded
  resources; it can only attempt work without any service-level guarantees.
  Throughput and latency bounds are not enforced.
* **unavailable** — the system cannot accept or process requests; no
  meaningful capacity remains.

Without these distinctions, ``runtime truth`` / ``acceptance`` /
``readiness`` / ``governance`` surfaces cannot distinguish "still processing
something" from "operating at normal operational capacity".

This module closes that gap by establishing the **Resource Pressure /
Degraded-Capacity / Admission Semantics Contract** — a formal classification
contract that:

1. Defines five mutually exclusive and exhaustive
   :class:`CapacityClass` values.
2. Specifies precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient, ambiguous,
   or pressure-indicating evidence always produces the lowest defensible
   class rather than the optimistic one.
4. Prohibits treating partial service continuation, backpressure survival,
   admission gating, or best-effort operation as equivalent to normal
   operational capacity.
5. Provides a :class:`CapacityVerdict` dataclass consumable by runtime
   truth / acceptance / readiness / governance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  RESOURCE PRESSURE / CAPACITY CONTRACT  (this module — PR-17)      │
    │                                                                     │
    │  Five capacity classes (strictly ordered by operational level):     │
    │    1. normal_capacity       (highest — all admission gates open,   │
    │       resource pressure within normal bounds, throughput at         │
    │       nominal level, no backpressure, no shed load)                 │
    │    2. degraded_capacity     (resource pressure observed or          │
    │       throughput degraded; system still processing but below        │
    │       nominal; backpressure or shed load may be active)             │
    │    3. admission_limited     (admission gate is actively restricting │
    │       new work; some requests are queued, deferred, or rejected;    │
    │       currently-running tasks continue but new admissions are       │
    │       gated)                                                         │
    │    4. best_effort_only      (severely resource-constrained; system  │
    │       attempts work without SLO guarantees; throughput and latency  │
    │       bounds are not enforced; no normal-capacity claim is valid)   │
    │    5. unavailable           (lowest — system cannot accept or       │
    │       process requests; no meaningful capacity remains)             │
    │                                                                     │
    │  Evidence dimensions evaluated:                                     │
    │    • resource_pressure_within_normal_bounds — no resource pressure  │
    │    • all_admission_gates_open    — no admission gating active       │
    │    • throughput_at_nominal_level — throughput is nominal            │
    │    • no_backpressure_active      — no backpressure signals          │
    │    • no_shed_load_active         — no shed load active              │
    │    • admission_gate_active       — admission gating is occurring    │
    │    • degraded_throughput_observed — throughput below nominal        │
    │    • backpressure_active         — backpressure signals present     │
    │    • shed_load_active            — load shedding is occurring       │
    │    • best_effort_mode_active     — system in best-effort mode       │
    │    • resource_pressure_observed  — resource pressure present        │
    │    • capacity_uncertainty        — capacity state is uncertain      │
    │    • explicit_unavailable        — system declared unavailable      │
    │                                                                     │
    │  Downgrade semantics:                                               │
    │    • explicit_unavailable → ALWAYS unavailable                      │
    │    • best_effort_mode_active → NEVER normal_capacity,               │
    │      degraded_capacity, or admission_limited                        │
    │    • admission_gate_active → NEVER normal_capacity                  │
    │    • backpressure_active or shed_load_active → NEVER                │
    │      normal_capacity; at most degraded_capacity                     │
    │    • resource_pressure_observed → NEVER normal_capacity             │
    │    • degraded_throughput_observed → NEVER normal_capacity           │
    │    • capacity_uncertainty → NEVER normal_capacity                   │
    │    • no positive evidence → unavailable (fail-conservative)         │
    │                                                                     │
    │  Produces:                                                          │
    │    • CapacityVerdict  (structured output)                           │
    │                                                                     │
    │  Consumed by:                                                       │
    │    • system_final_acceptance_verdict                                │
    │      (resource_pressure_capacity dimension)                         │
    │    • runtime truth / acceptance / readiness / governance surfaces   │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class (``unavailable``) rather than the optimistic one.
3. **No optimistic promotion** — partial service continuation, backpressure
   survival, admission gating, and best-effort operation are explicitly
   excluded from being promoted to ``normal_capacity``.
4. **Taxonomy boundary enforcement** — "still processing some requests"
   does NOT imply "normal capacity"; "admission gate active" does NOT imply
   "operating normally"; "can run in best-effort mode" does NOT imply "has
   normal operational capacity".
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as normal_capacity vs what does not
------------------------------------------------------------------
- **Partial service continuation under resource pressure** — does NOT
  constitute normal_capacity; the system is operating in a degraded envelope
  even if some tasks continue to be processed.
- **Backpressure survival** — does NOT constitute normal_capacity;
  backpressure signals that the system is near or beyond its normal throughput
  bounds.
- **Admission gating** — does NOT constitute normal_capacity; active
  admission restrictions indicate the system cannot accept new work at its
  normal rate.
- **Best-effort processing** — does NOT constitute normal_capacity or
  degraded_capacity; best-effort mode explicitly means SLO guarantees are
  suspended.
- **No evidence** — cannot be treated as normal_capacity; the absence of
  capacity and health confirmation is the conservative default (unavailable).

Public API
----------
Authority sentinels::

    RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY
    RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL

Policy sentinels::

    CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY
    PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY
    BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY
    ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY
    SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY
    BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY
    CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY

Enumerations::

    CapacityClass
    ResourcePressureLevel

Data classes::

    CapacityEvidence
    CapacityVerdict

Functions::

    classify_capacity(evidence) -> CapacityVerdict
    build_capacity_verdict(evidence) -> CapacityVerdict
    build_baseline_capacity_verdict() -> CapacityVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ResourcePressureCapacityContract")

__all__ = [
    # Authority sentinels
    "RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY",
    "RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL",
    # Policy sentinels
    "CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY",
    "PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY",
    "BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY",
    "ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY",
    "SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY",
    "BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY",
    "CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY",
    # Enumerations
    "CapacityClass",
    "ResourcePressureLevel",
    # Data classes
    "CapacityEvidence",
    "CapacityVerdict",
    # Functions
    "classify_capacity",
    "build_capacity_verdict",
    "build_baseline_capacity_verdict",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY: str = (
    "RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY::"
    "core.resource_pressure_capacity_contract::PR17::"
    "resource-pressure-degraded-capacity-admission-taxonomy::"
    "formal-capacity-contract-for-galaxy-v2-platform"
)
"""Sentinel: this module is the canonical authority for resource pressure /
degraded-capacity / admission semantics classification in Galaxy V2.

Import this sentinel to assert that a release gate, governance surface,
acceptance evaluator, or runtime truth layer is consuming a formal
capacity classification rather than an implicit "still-running" flag."""

RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL: str = (
    "RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL::"
    "package=PR17::profile=resource-pressure-capacity-contract-v1::"
    "module=core.resource_pressure_capacity_contract"
)
"""Package sentinel for PR-17 resource pressure / capacity contract."""

CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY: str = (
    "POLICY::CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_V1: "
    "Resource pressure / degraded-capacity / admission semantics MUST be "
    "treated as a first-class operational dimension by truth surfaces, "
    "readiness gates, acceptance evaluators, and governance pipelines.  "
    "Surfaces MUST NOT conflate 'still processing some requests' (partial "
    "service continuation) with 'operating at normal operational capacity' "
    "(throughput and latency within nominal bounds, all gates open, no "
    "pressure).  Every capacity verdict MUST include a CapacityVerdict that "
    "identifies the applicable class.  "
    "See: CapacityClass taxonomy in "
    "core.resource_pressure_capacity_contract (PR-17)."
)
"""Policy: capacity taxonomy is a first-class operational dimension."""

PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY: str = (
    "POLICY::PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_V1: "
    "When the system is operating under resource pressure — even if it is "
    "still accepting and processing some requests — the capacity class MUST "
    "NOT be set to normal_capacity.  Partial service continuation under "
    "resource pressure is degraded_capacity at best.  'Still running' is "
    "not the same as 'operating at normal capacity'.  Throughput degradation, "
    "backpressure, shed load, admission gating, or resource exhaustion "
    "signals MUST each independently prevent a normal_capacity classification.  "
    "See: CapacityClass.degraded_capacity in "
    "core.resource_pressure_capacity_contract (PR-17)."
)
"""Policy: partial service continuation must not produce normal_capacity."""

BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY: str = (
    "POLICY::BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_V1: "
    "When backpressure signals are active (consumer is slower than producer, "
    "queues are filling, or flow-control signals are propagating), the capacity "
    "class MUST be downgraded from normal_capacity.  Backpressure is a "
    "structural signal that the system is operating beyond its comfortable "
    "throughput envelope; it MUST NOT be suppressed or ignored when computing "
    "capacity classification.  At most the class is degraded_capacity while "
    "backpressure is active.  "
    "See: backpressure_active flag in classify_capacity() (PR-17)."
)
"""Policy: active backpressure must downgrade from normal_capacity."""

ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY: str = (
    "POLICY::ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_V1: "
    "When an admission gate is actively restricting new work (queuing, "
    "deferring, or rejecting arriving requests), the capacity class MUST NOT "
    "be set to normal_capacity.  Active admission gating indicates the system "
    "cannot accept new work at its normal rate regardless of how existing "
    "in-flight tasks are performing.  The class MUST be at most "
    "admission_limited when an admission gate is active.  "
    "See: admission_gate_active flag in classify_capacity() (PR-17)."
)
"""Policy: active admission gating must not produce normal_capacity."""

SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY: str = (
    "POLICY::SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_V1: "
    "When the system is actively shedding load (dropping, deferring, or "
    "discarding requests to protect itself from overload), the capacity class "
    "MUST be downgraded from normal_capacity.  Load shedding is an explicit "
    "signal of resource exhaustion or overload; it MUST NOT be suppressed "
    "when computing capacity classification.  At most the class is "
    "degraded_capacity while shed load is active.  "
    "See: shed_load_active flag in classify_capacity() (PR-17)."
)
"""Policy: active load shedding must downgrade from normal_capacity."""

BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY: str = (
    "POLICY::BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_V1: "
    "When the system is operating in best-effort mode (SLO guarantees are "
    "suspended, throughput and latency bounds are not enforced), the capacity "
    "class MUST NOT be set to normal_capacity, degraded_capacity, or "
    "admission_limited.  Best-effort mode is an explicit declaration that "
    "normal service guarantees do not apply; it MUST be classified as "
    "best_effort_only.  'Best-effort operation is still happening' is not "
    "the same as 'some degraded capacity exists'.  "
    "See: CapacityClass.best_effort_only in "
    "core.resource_pressure_capacity_contract (PR-17)."
)
"""Policy: best-effort mode must not produce normal_capacity or degraded_capacity."""

CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY: str = (
    "POLICY::CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_V1: "
    "When no positive capacity evidence is present — no confirmation that "
    "resource pressure is within normal bounds, no evidence that admission "
    "gates are open, no throughput normalcy confirmation — the capacity class "
    "MUST default to unavailable.  The absence of capacity evidence is NOT a "
    "signal of normal_capacity; it is a signal of unknown or worst-case "
    "capacity state.  Silence is not operational capacity.  "
    "See: CapacityClass.unavailable in "
    "core.resource_pressure_capacity_contract (PR-17)."
)
"""Policy: absence of capacity evidence defaults to unavailable (fail-conservative)."""


# ---------------------------------------------------------------------------
# CapacityClass
# ---------------------------------------------------------------------------


class CapacityClass(str, Enum):
    """Five-class capacity taxonomy for resource pressure / degraded-capacity /
    admission semantics.

    String values are stable identifiers safe for serialisation, logging,
    and API responses.

    Ordering (from highest to lowest capacity):
      normal_capacity > degraded_capacity > admission_limited >
      best_effort_only > unavailable
    """

    normal_capacity = "normal_capacity"
    """System is operating at its expected throughput and latency envelopes.
    All admission gates are open, resource pressure is within normal bounds,
    no backpressure or shed load is active, and throughput is at its nominal
    level.  This is the only class that represents genuine normal operational
    capacity.

    Requirements (all must hold):
    - resource_pressure_within_normal_bounds = True
    - all_admission_gates_open = True
    - throughput_at_nominal_level = True
    - no_backpressure_active = True
    - no_shed_load_active = True
    - admission_gate_active = False
    - degraded_throughput_observed = False
    - backpressure_active = False
    - shed_load_active = False
    - best_effort_mode_active = False
    - resource_pressure_observed = False
    - capacity_uncertainty = False
    - explicit_unavailable = False
    """

    degraded_capacity = "degraded_capacity"
    """System is processing requests but below its nominal performance
    envelope.  Resource pressure, throughput degradation, backpressure, or
    shed load may be active.  The system is not fully healthy but retains
    meaningful (though diminished) processing capability.  This is NOT
    normal_capacity.

    Requirements:
    - explicit_unavailable = False
    - best_effort_mode_active = False
    - admission_gate_active = False (no active admission gating)
    - At least one of:
        - resource_pressure_observed = True
        - degraded_throughput_observed = True
        - backpressure_active = True
        - shed_load_active = True
        - resource_pressure_within_normal_bounds = False
        - throughput_at_nominal_level = False
        - no_backpressure_active = False
        - no_shed_load_active = False
    """

    admission_limited = "admission_limited"
    """System is actively gating admission; some arriving requests are being
    queued, deferred, or rejected at the admission boundary.  Currently
    in-flight tasks may continue to run, but new admissions are restricted.
    This is NOT normal_capacity and is worse than plain degraded_capacity
    because the system is explicitly turning away or queuing new work.

    Requirements:
    - explicit_unavailable = False
    - best_effort_mode_active = False
    - admission_gate_active = True
    """

    best_effort_only = "best_effort_only"
    """System is severely resource-constrained.  It may attempt to process
    work but without any service-level guarantees.  Throughput and latency
    bounds are not enforced.  The system is not failing completely but its
    operation is not meaningfully capacity-bounded or SLO-governed.  This
    is NOT normal_capacity, degraded_capacity, or admission_limited.

    Requirements:
    - explicit_unavailable = False
    - best_effort_mode_active = True
    """

    unavailable = "unavailable"
    """System cannot accept or process requests.  No meaningful capacity
    remains.  This is the fail-conservative default when no positive capacity
    evidence is present, or when the system has explicitly declared itself
    unavailable.

    Requirements (any of):
    - explicit_unavailable = True
    - No positive capacity evidence at all (fail-conservative default)
    """


# Numeric rank for comparison (lower = worse)
_CLASS_RANK: Dict[str, int] = {
    CapacityClass.unavailable.value: 0,
    CapacityClass.best_effort_only.value: 1,
    CapacityClass.admission_limited.value: 2,
    CapacityClass.degraded_capacity.value: 3,
    CapacityClass.normal_capacity.value: 4,
}


def _worse_or_equal(a: CapacityClass, b: CapacityClass) -> bool:
    """Return True if class *a* is worse than or equal to class *b*."""
    return _CLASS_RANK[a.value] <= _CLASS_RANK[b.value]


# ---------------------------------------------------------------------------
# ResourcePressureLevel
# ---------------------------------------------------------------------------


class ResourcePressureLevel(str, Enum):
    """Describes the level of resource pressure observed.

    Used to provide additional context in the CapacityVerdict.
    """

    none = "none"
    """No resource pressure is observed.  Resources are within their normal
    operating bounds."""

    mild = "mild"
    """Mild resource pressure: metrics are elevated but the system has not
    yet entered a degraded operating state."""

    moderate = "moderate"
    """Moderate resource pressure: performance is measurably affected; the
    system is in a degraded operating state."""

    severe = "severe"
    """Severe resource pressure: the system is significantly constrained;
    normal operation is not possible."""

    critical = "critical"
    """Critical resource pressure: the system is at or beyond its operating
    limits; unavailability is imminent."""

    unknown = "unknown"
    """Resource pressure level is unknown.  Must be treated conservatively."""


# ---------------------------------------------------------------------------
# CapacityEvidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapacityEvidence:
    """Structured evidence input for the capacity classifier.

    All fields have safe (fail-conservative) defaults so that an absent
    signal does not silently produce an optimistic classification.

    Attributes
    ----------
    resource_pressure_within_normal_bounds:
        True only when resource utilisation (CPU, memory, I/O, etc.) has
        been confirmed to be within the system's normal operating bounds.
        Defaults to False (conservative).
    all_admission_gates_open:
        True when every admission gate is open and no new-work gating is
        active.  Defaults to False (conservative).
    throughput_at_nominal_level:
        True only when measured throughput is at or above the nominal
        baseline rate (no throughput degradation).  Defaults to False
        (conservative).
    no_backpressure_active:
        True when no backpressure signals are active in the system (queues
        are not filling, flow-control signals are not propagating).
        Defaults to False (conservative).
    no_shed_load_active:
        True when the system is not actively shedding load (no requests are
        being dropped or discarded to protect from overload).  Defaults to
        False (conservative).
    admission_gate_active:
        True when an admission gate is actively restricting new work
        (queuing, deferring, or rejecting arriving requests).  Defaults to
        False.  When True, ALWAYS prevents normal_capacity classification.
    degraded_throughput_observed:
        True when measured throughput is below the nominal baseline.
        Defaults to False.  When True, prevents normal_capacity.
    backpressure_active:
        True when backpressure signals are detected.  Defaults to False.
        When True, prevents normal_capacity.
    shed_load_active:
        True when load shedding is occurring.  Defaults to False.  When
        True, prevents normal_capacity.
    best_effort_mode_active:
        True when the system is operating in best-effort mode (SLO
        guarantees suspended).  Defaults to False.  When True, ALWAYS
        produces best_effort_only (unless explicit_unavailable is True).
    resource_pressure_observed:
        True when resource pressure (CPU, memory, I/O contention, etc.) has
        been observed.  Defaults to False.  When True, prevents
        normal_capacity.
    capacity_uncertainty:
        True when the capacity state is uncertain (signals are absent or
        contradictory).  Defaults to False.  When True, prevents
        normal_capacity.
    explicit_unavailable:
        True when the system has explicitly declared itself unavailable.
        Defaults to False.  When True, ALWAYS produces unavailable
        regardless of other fields.
    pressure_level:
        The observed resource pressure level for contextual reporting.
        Defaults to ResourcePressureLevel.unknown (conservative).
    participant_id:
        Optional participant or surface identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    extra_context:
        Optional dict of additional context signals.  Not used in
        classification logic but included in the verdict for auditability.
    """

    resource_pressure_within_normal_bounds: bool = False
    all_admission_gates_open: bool = False
    throughput_at_nominal_level: bool = False
    no_backpressure_active: bool = False
    no_shed_load_active: bool = False
    admission_gate_active: bool = False
    degraded_throughput_observed: bool = False
    backpressure_active: bool = False
    shed_load_active: bool = False
    best_effort_mode_active: bool = False
    resource_pressure_observed: bool = False
    capacity_uncertainty: bool = False
    explicit_unavailable: bool = False
    pressure_level: ResourcePressureLevel = ResourcePressureLevel.unknown
    participant_id: Optional[str] = None
    trace_id: Optional[str] = None
    extra_context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "resource_pressure_within_normal_bounds": (
                self.resource_pressure_within_normal_bounds
            ),
            "all_admission_gates_open": self.all_admission_gates_open,
            "throughput_at_nominal_level": self.throughput_at_nominal_level,
            "no_backpressure_active": self.no_backpressure_active,
            "no_shed_load_active": self.no_shed_load_active,
            "admission_gate_active": self.admission_gate_active,
            "degraded_throughput_observed": self.degraded_throughput_observed,
            "backpressure_active": self.backpressure_active,
            "shed_load_active": self.shed_load_active,
            "best_effort_mode_active": self.best_effort_mode_active,
            "resource_pressure_observed": self.resource_pressure_observed,
            "capacity_uncertainty": self.capacity_uncertainty,
            "explicit_unavailable": self.explicit_unavailable,
            "pressure_level": self.pressure_level.value,
            "participant_id": self.participant_id,
            "trace_id": self.trace_id,
            "extra_context": dict(self.extra_context),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapacityEvidence":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        level_raw = data.get("pressure_level", "unknown")
        try:
            pressure_level = ResourcePressureLevel(level_raw)
        except ValueError:
            pressure_level = ResourcePressureLevel.unknown
        return cls(
            resource_pressure_within_normal_bounds=bool(
                data.get("resource_pressure_within_normal_bounds", False)
            ),
            all_admission_gates_open=bool(
                data.get("all_admission_gates_open", False)
            ),
            throughput_at_nominal_level=bool(
                data.get("throughput_at_nominal_level", False)
            ),
            no_backpressure_active=bool(
                data.get("no_backpressure_active", False)
            ),
            no_shed_load_active=bool(data.get("no_shed_load_active", False)),
            admission_gate_active=bool(data.get("admission_gate_active", False)),
            degraded_throughput_observed=bool(
                data.get("degraded_throughput_observed", False)
            ),
            backpressure_active=bool(data.get("backpressure_active", False)),
            shed_load_active=bool(data.get("shed_load_active", False)),
            best_effort_mode_active=bool(
                data.get("best_effort_mode_active", False)
            ),
            resource_pressure_observed=bool(
                data.get("resource_pressure_observed", False)
            ),
            capacity_uncertainty=bool(data.get("capacity_uncertainty", False)),
            explicit_unavailable=bool(data.get("explicit_unavailable", False)),
            pressure_level=pressure_level,
            participant_id=data.get("participant_id"),
            trace_id=data.get("trace_id"),
            extra_context=dict(data.get("extra_context", {})),
        )


# ---------------------------------------------------------------------------
# CapacityVerdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapacityVerdict:
    """Formal capacity verdict for a system surface.

    Produced by :func:`classify_capacity`.

    Attributes
    ----------
    capacity_class:
        The classified :class:`CapacityClass` for this context.
    rationale:
        Human-readable explanation of why this class was assigned.  Always
        non-empty.
    downgrade_reasons:
        List of specific reasons that caused the class to be downgraded from
        an optimistic baseline.  Empty when no downgrade occurred.
    is_normal:
        True only for ``normal_capacity`` class.  MUST NOT be set for any
        other class.
    is_degraded:
        True for ``degraded_capacity``.  Indicates the system is operating
        below normal but still meaningfully.
    is_admission_limited:
        True for ``admission_limited``.  Indicates admission gating is
        active.
    is_best_effort_only:
        True for ``best_effort_only``.  Indicates SLO guarantees are
        suspended.
    is_unavailable:
        True for ``unavailable``.  Indicates no meaningful capacity remains.
    participant_id:
        Identifier of the surface or participant this verdict applies to.
    evidence_present:
        Whether any positive capacity evidence was available during
        classification.
    classified_at:
        Unix timestamp (float) when this verdict was produced.
    verdict_id:
        Unique identifier for this verdict instance.
    trace_id:
        Optional distributed-trace identifier.
    """

    capacity_class: CapacityClass
    rationale: str
    downgrade_reasons: List[str] = field(default_factory=list)
    is_normal: bool = False
    is_degraded: bool = False
    is_admission_limited: bool = False
    is_best_effort_only: bool = False
    is_unavailable: bool = False
    participant_id: Optional[str] = None
    evidence_present: bool = False
    classified_at: float = field(default_factory=time.time)
    verdict_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "capacity_class": self.capacity_class.value,
            "rationale": self.rationale,
            "downgrade_reasons": list(self.downgrade_reasons),
            "is_normal": self.is_normal,
            "is_degraded": self.is_degraded,
            "is_admission_limited": self.is_admission_limited,
            "is_best_effort_only": self.is_best_effort_only,
            "is_unavailable": self.is_unavailable,
            "participant_id": self.participant_id,
            "evidence_present": self.evidence_present,
            "classified_at": self.classified_at,
            "verdict_id": self.verdict_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapacityVerdict":
        """Construct from a dict (round-trip complement of ``to_dict``)."""
        class_raw = data.get("capacity_class", "unavailable")
        try:
            c_class = CapacityClass(class_raw)
        except ValueError:
            c_class = CapacityClass.unavailable
        return cls(
            capacity_class=c_class,
            rationale=data.get("rationale", ""),
            downgrade_reasons=list(data.get("downgrade_reasons", [])),
            is_normal=bool(data.get("is_normal", False)),
            is_degraded=bool(data.get("is_degraded", False)),
            is_admission_limited=bool(data.get("is_admission_limited", False)),
            is_best_effort_only=bool(data.get("is_best_effort_only", False)),
            is_unavailable=bool(data.get("is_unavailable", False)),
            participant_id=data.get("participant_id"),
            evidence_present=bool(data.get("evidence_present", False)),
            classified_at=float(data.get("classified_at", time.time())),
            verdict_id=data.get("verdict_id", uuid.uuid4().hex[:12]),
            trace_id=data.get("trace_id"),
        )


# ---------------------------------------------------------------------------
# Core classifier
# ---------------------------------------------------------------------------


def _classify(evidence: CapacityEvidence) -> CapacityVerdict:
    """Internal classification implementation.

    Priority order:
    1. explicit_unavailable=True → unavailable (always)
    2. best_effort_mode_active=True → best_effort_only (unless unavailable)
    3. admission_gate_active=True → admission_limited
    4. Any degradation signal (resource_pressure_observed,
       degraded_throughput_observed, backpressure_active, shed_load_active,
       NOT resource_pressure_within_normal_bounds, NOT throughput_at_nominal_level,
       NOT no_backpressure_active, NOT no_shed_load_active,
       capacity_uncertainty) → degraded_capacity
    5. All positive signals present (resource_pressure_within_normal_bounds,
       all_admission_gates_open, throughput_at_nominal_level,
       no_backpressure_active, no_shed_load_active, and no degradation
       signals) → normal_capacity
    6. All other cases → unavailable (fail-conservative)
    """
    downgrade_reasons: List[str] = []
    evidence_present = False

    # Rule 1: explicit_unavailable always wins
    if evidence.explicit_unavailable:
        return CapacityVerdict(
            capacity_class=CapacityClass.unavailable,
            rationale=(
                "explicit_unavailable=True: system has explicitly declared "
                "itself unavailable.  No capacity claim is possible."
            ),
            downgrade_reasons=["explicit_unavailable=True"],
            is_unavailable=True,
            participant_id=evidence.participant_id,
            evidence_present=False,
            trace_id=evidence.trace_id,
        )

    # Determine if any positive evidence exists
    positive_signals = [
        evidence.resource_pressure_within_normal_bounds,
        evidence.all_admission_gates_open,
        evidence.throughput_at_nominal_level,
        evidence.no_backpressure_active,
        evidence.no_shed_load_active,
    ]
    degradation_signals = [
        evidence.admission_gate_active,
        evidence.degraded_throughput_observed,
        evidence.backpressure_active,
        evidence.shed_load_active,
        evidence.best_effort_mode_active,
        evidence.resource_pressure_observed,
        evidence.capacity_uncertainty,
    ]
    evidence_present = any(positive_signals) or any(degradation_signals)

    # Rule 2: best_effort_mode_active → best_effort_only
    if evidence.best_effort_mode_active:
        downgrade_reasons.append(
            "best_effort_mode_active=True: SLO guarantees suspended; "
            "system can only attempt work without capacity guarantees."
        )
        return CapacityVerdict(
            capacity_class=CapacityClass.best_effort_only,
            rationale=(
                "best_effort_mode_active=True: system is operating in "
                "best-effort mode.  SLO guarantees are suspended.  "
                "This is NOT normal_capacity, degraded_capacity, or "
                "admission_limited."
            ),
            downgrade_reasons=downgrade_reasons,
            is_best_effort_only=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 3: admission_gate_active → admission_limited
    if evidence.admission_gate_active:
        downgrade_reasons.append(
            "admission_gate_active=True: admission gating is actively "
            "restricting new work; arriving requests are being queued, "
            "deferred, or rejected."
        )
        return CapacityVerdict(
            capacity_class=CapacityClass.admission_limited,
            rationale=(
                "admission_gate_active=True: admission gate is active.  "
                "New work admissions are restricted.  This is NOT "
                "normal_capacity even if in-flight tasks continue."
            ),
            downgrade_reasons=downgrade_reasons,
            is_admission_limited=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Collect degradation signals for rules 4 and 5
    if evidence.resource_pressure_observed:
        downgrade_reasons.append(
            "resource_pressure_observed=True: resource pressure is present."
        )
    if evidence.degraded_throughput_observed:
        downgrade_reasons.append(
            "degraded_throughput_observed=True: throughput is below nominal."
        )
    if evidence.backpressure_active:
        downgrade_reasons.append(
            "backpressure_active=True: backpressure signals are present."
        )
    if evidence.shed_load_active:
        downgrade_reasons.append(
            "shed_load_active=True: load shedding is occurring."
        )
    if not evidence.resource_pressure_within_normal_bounds and any(positive_signals):
        # Only flag if there's some evidence (not pure zero-evidence case)
        if not evidence.resource_pressure_within_normal_bounds:
            downgrade_reasons.append(
                "resource_pressure_within_normal_bounds=False: resource "
                "pressure is not within normal bounds."
            )
    if not evidence.throughput_at_nominal_level and any(positive_signals):
        if not evidence.throughput_at_nominal_level:
            downgrade_reasons.append(
                "throughput_at_nominal_level=False: throughput is not nominal."
            )
    if not evidence.no_backpressure_active and any(positive_signals):
        if not evidence.no_backpressure_active:
            downgrade_reasons.append(
                "no_backpressure_active=False: backpressure may be active."
            )
    if not evidence.no_shed_load_active and any(positive_signals):
        if not evidence.no_shed_load_active:
            downgrade_reasons.append(
                "no_shed_load_active=False: load shedding may be active."
            )
    if evidence.capacity_uncertainty:
        downgrade_reasons.append(
            "capacity_uncertainty=True: capacity state is uncertain."
        )

    # Collect unique reasons
    seen: set = set()
    unique_reasons: List[str] = []
    for r in downgrade_reasons:
        if r not in seen:
            seen.add(r)
            unique_reasons.append(r)
    downgrade_reasons = unique_reasons

    # Rule 4: any degradation signal → degraded_capacity (if system has some
    # evidence of remaining capacity but is not normal)
    has_degradation = bool(
        evidence.resource_pressure_observed
        or evidence.degraded_throughput_observed
        or evidence.backpressure_active
        or evidence.shed_load_active
        or evidence.capacity_uncertainty
        or not evidence.resource_pressure_within_normal_bounds
        or not evidence.throughput_at_nominal_level
        or not evidence.no_backpressure_active
        or not evidence.no_shed_load_active
    )

    if has_degradation and evidence_present:
        return CapacityVerdict(
            capacity_class=CapacityClass.degraded_capacity,
            rationale=(
                "One or more degradation signals are present.  The system "
                "is operating below normal capacity.  This is NOT "
                "normal_capacity."
            ),
            downgrade_reasons=downgrade_reasons,
            is_degraded=True,
            participant_id=evidence.participant_id,
            evidence_present=evidence_present,
            trace_id=evidence.trace_id,
        )

    # Rule 5: all positive conditions met → normal_capacity
    all_normal = (
        evidence.resource_pressure_within_normal_bounds
        and evidence.all_admission_gates_open
        and evidence.throughput_at_nominal_level
        and evidence.no_backpressure_active
        and evidence.no_shed_load_active
        and not evidence.admission_gate_active
        and not evidence.degraded_throughput_observed
        and not evidence.backpressure_active
        and not evidence.shed_load_active
        and not evidence.best_effort_mode_active
        and not evidence.resource_pressure_observed
        and not evidence.capacity_uncertainty
        and not evidence.explicit_unavailable
    )

    if all_normal:
        return CapacityVerdict(
            capacity_class=CapacityClass.normal_capacity,
            rationale=(
                "All capacity conditions met: resource pressure within "
                "normal bounds, all admission gates open, throughput at "
                "nominal level, no backpressure, no shed load, no "
                "degradation signals."
            ),
            downgrade_reasons=[],
            is_normal=True,
            participant_id=evidence.participant_id,
            evidence_present=True,
            trace_id=evidence.trace_id,
        )

    # Rule 6: all other cases → unavailable (fail-conservative)
    return CapacityVerdict(
        capacity_class=CapacityClass.unavailable,
        rationale=(
            "No positive capacity evidence is present and no specific "
            "degradation class applies.  Defaulting to unavailable "
            "(fail-conservative baseline)."
        ),
        downgrade_reasons=["No positive capacity evidence (fail-conservative default)"],
        is_unavailable=True,
        participant_id=evidence.participant_id,
        evidence_present=evidence_present,
        trace_id=evidence.trace_id,
    )


def classify_capacity(evidence: CapacityEvidence) -> CapacityVerdict:
    """Classify the capacity class for a system surface.

    This is the canonical entry point for resource pressure / degraded-capacity
    / admission semantics classification.  It applies the fail-conservative
    downgrade rules defined in the module docstring and enforced by the
    policy sentinels.

    Classification logic (evaluated in priority order):
    1. ``explicit_unavailable=True`` → **unavailable** (always)
    2. ``best_effort_mode_active=True`` → **best_effort_only**
    3. ``admission_gate_active=True`` → **admission_limited**
    4. Any degradation signal present → **degraded_capacity**
    5. All five positive capacity conditions met and no degradation signals
       → **normal_capacity**
    6. All other cases → **unavailable** (fail-conservative)

    Parameters
    ----------
    evidence:
        :class:`CapacityEvidence` describing the resource pressure and
        capacity state.

    Returns
    -------
    CapacityVerdict
        Immutable verdict recording the class, rationale, and any downgrade
        reasons.  Never raises; returns ``unavailable`` on unexpected input.
    """
    try:
        return _classify(evidence)
    except Exception as exc:
        logger.warning(
            "classify_capacity raised unexpectedly: %r — "
            "defaulting to unavailable",
            exc,
        )
        return CapacityVerdict(
            capacity_class=CapacityClass.unavailable,
            rationale=(
                f"classify_capacity raised an unexpected exception: {exc!r}.  "
                "Defaulting to unavailable (fail-conservative)."
            ),
            downgrade_reasons=[f"exception: {exc!r}"],
            is_unavailable=True,
            evidence_present=False,
        )


def build_capacity_verdict(evidence: CapacityEvidence) -> CapacityVerdict:
    """Build a :class:`CapacityVerdict` from explicit evidence.

    This is an alias for :func:`classify_capacity` suitable for use by
    integration layers that prefer a builder-function naming convention.
    """
    return classify_capacity(evidence)


def build_baseline_capacity_verdict() -> CapacityVerdict:
    """Build a zero-evidence (fail-conservative baseline) capacity verdict.

    Returns a verdict with all evidence fields at their conservative defaults.
    The resulting class MUST be ``unavailable`` (no positive evidence implies
    the worst-case capacity state).

    This function is used by acceptance / governance probes to verify that the
    contract module is wired and produces conservative verdicts when no
    positive capacity evidence is fed to it.

    Returns
    -------
    CapacityVerdict
        A verdict with ``capacity_class=CapacityClass.unavailable`` and
        ``evidence_present=False``.
    """
    return classify_capacity(CapacityEvidence())
