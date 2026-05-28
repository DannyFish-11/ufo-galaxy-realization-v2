#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/bounded_subject_platform_boundary.py
==========================================
PR-14V2: Bounded Subject Platform Boundary — Final Convergence.

Purpose
-------
This module is the **final convergence declaration** for the bounded subject
platform boundary.  It does **not** reassemble authority, truth, dispatch,
or closure — all of those are already established by the prior canonical
governance, distributed subject contract, operator governance, and
observability/evidence contracts.

What this module does
---------------------
It declares, in a single machine-checkable location, the five boundary axes
that define the stable *quasi-platform state* (准平台态):

1. **Canonical Center Boundary** — V2 is the sole canonical governance /
   truth convergence / dispatch arbitration / closure authority center.
   Code evidence: ``core.center_authority_boundary``.

2. **Bounded Subject Boundary** — Android and any future bounded relative
   subjects have local lifecycle, local AI consumption, local execution
   judgment, and local visible surfaces, but no global truth finalization
   or global dispatch authority.  Code evidence:
   ``contracts.distributed_subject_contract_v1``,
   ``core.android_participant_truth_ingress``.

3. **Participant Governance Boundary** — Participant lifecycle state
   transitions are authoritative only when issued by V2 canonical
   governance.  A bounded relative subject may signal readiness / posture /
   busy, but it cannot unilaterally promote or demote its own participant
   lifecycle state.  Code evidence:
   ``core.operator_action_governance``,
   ``core.execution_governance_audit_authority``.

4. **Observability / Diagnostics / Evidence Boundary** — The four-level
   visibility taxonomy (LOCAL_VISIBLE, RUNTIME_VISIBLE, OPERATOR_VISIBLE,
   PRODUCT_VISIBLE) and five evidence contract kinds are declared in
   ``core.cross_subject_observability_contract``.  No new parallel
   observability center is introduced here.

5. **Outward Consumption Boundary** — Outward-facing / product-facing /
   operator-facing / projection-facing surfaces are consumption layers only.
   They MUST NOT reassemble authority, truth, dispatch, or closure.  Code
   evidence: ``core.final_acceptance_surface_boundary``,
   ``core.outward_runtime_truth``.

System definition
-----------------
Based on all prior PR evidence, the system is formally defined as:

    真实一体化协同的中心治理型多相对主体分布式 AI runtime 系统
    (Genuinely integrated, canonically-governed, multi-bounded-subject
     distributed AI runtime system)

This definition is NOT a claim of "fully mature distributed platform" —
it is the minimum honest description of what the dual-repo system has
actually become through PRs 1–13v2 and their Android counterparts.

Quasi-platform state definition
--------------------------------
The system reaches **stable quasi-platform state** when ALL of the
following are simultaneously satisfied:

* canonical center boundary is INTACT (four authority domains all INTACT).
* bounded subject boundary is declared and non-drifting.
* participant governance boundary is declared and enforced.
* observability / evidence boundary is declared and non-conflated.
* outward consumption boundary is declared and consumption-only.
* Android ↔ V2 system definition is consistent (no parallel canonical
  center claims from any bounded subject).

Hard constraints
-----------------
1. This module MUST NOT redefine authority, truth, dispatch, or closure.
2. Android and any participant MUST NOT be elevated to parallel canonical
   center by any code in this module.
3. Outward-facing layers MUST NOT be elevated to new platform sovereignty
   layer by any code in this module.
4. All five boundary axes MUST reference the real, already-established
   canonical modules; no abstract drift is permitted.
5. This module MUST remain consistent with all prior PR system definitions
   and contracts.

Public API
----------
Authority sentinels::

    BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY
    BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL
    QUASI_PLATFORM_STATE_DEFINITION

Policy sentinels::

    CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY
    BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY
    PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY
    OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY
    OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY

Enums::

    PlatformBoundaryAxis

Data classes::

    BoundaryAxisDescriptor
    PlatformBoundarySnapshot

Functions::

    build_platform_boundary_snapshot() -> PlatformBoundarySnapshot
    assert_quasi_platform_state_intact() -> None
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from core.final_acceptance_surface_boundary import build_final_acceptance_surface_boundary


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY: str = (
    "BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY_V1: "
    "core.bounded_subject_platform_boundary is the final convergence "
    "declaration for the five boundary axes that define the stable "
    "quasi-platform state.  It composes — and does not reassemble — "
    "the already-established canonical governance, distributed subject "
    "contract, participant governance, observability/evidence contract, "
    "and outward consumption boundary.  V2 remains the sole canonical "
    "governance / truth convergence / dispatch arbitration / closure "
    "authority center.  Android and all other bounded subjects remain "
    "bounded relative subject runtimes with no global truth finalization "
    "or global dispatch authority."
)

BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL: str = (
    "BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL::"
    "package=14v2::profile=bounded-subject-platform-boundary-v1"
)

QUASI_PLATFORM_STATE_DEFINITION: str = (
    "QUASI_PLATFORM_STATE_DEFINITION_V1: "
    "The system is defined as a 真实一体化协同的中心治理型多相对主体分布式 AI runtime 系统 "
    "(genuinely integrated, canonically-governed, multi-bounded-subject "
    "distributed AI runtime system).  This definition is stable when: "
    "(1) canonical center boundary is INTACT, "
    "(2) bounded subject boundary is declared and non-drifting, "
    "(3) participant governance boundary is enforced by the canonical center, "
    "(4) observability/evidence boundary is non-conflated with canonical truth, "
    "(5) outward consumption boundary is consumption-only with no authority reassembly."
)


# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY: str = (
    "POLICY::CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_V14: "
    "V2 is the sole canonical governance / truth convergence / dispatch "
    "arbitration / closure authority center.  No bounded subject (Android, "
    "desktop presence runtime, external device, or sub-runtime) may be "
    "elevated to a parallel canonical center.  "
    "Code evidence: core.center_authority_boundary."
)

BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY: str = (
    "POLICY::BOUNDED_SUBJECT_NO_GLOBAL_TRUTH_FINALIZATION_V14: "
    "Android and all other bounded relative subjects have local lifecycle, "
    "local AI consumption, local execution judgment, and local visible "
    "surfaces, but they do not hold global truth finalization or global "
    "dispatch authority.  Participant truth evidence must travel the "
    "declared canonical uplink path (core.android_participant_truth_ingress) "
    "and be accepted by V2 canonical governance before being promoted.  "
    "Code evidence: contracts.distributed_subject_contract_v1, "
    "core.android_participant_truth_ingress."
)

PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY: str = (
    "POLICY::PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_V14: "
    "Participant lifecycle state transitions are authoritative only when "
    "issued by V2 canonical governance.  A bounded relative subject may "
    "signal readiness, posture, or busy state, but it cannot unilaterally "
    "promote or demote its own participant lifecycle state.  "
    "Code evidence: core.operator_action_governance, "
    "core.execution_governance_audit_authority."
)

OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY: str = (
    "POLICY::OBSERVABILITY_BOUNDARY_NOT_PARALLEL_AUTHORITY_V14: "
    "The four-level visibility taxonomy (LOCAL_VISIBLE, RUNTIME_VISIBLE, "
    "OPERATOR_VISIBLE, PRODUCT_VISIBLE) classifies diagnostics and evidence "
    "outputs from all subjects.  No visibility level constitutes a parallel "
    "observability authority or canonical truth source.  Observability "
    "surfaces are classification and consumption layers only.  "
    "Code evidence: core.cross_subject_observability_contract."
)

OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY: str = (
    "POLICY::OUTWARD_CONSUMPTION_BOUNDARY_CONSUMPTION_ONLY_V14: "
    "Outward-facing, product-facing, operator-facing, and projection-facing "
    "surfaces are consumption layers only.  They MUST NOT reassemble "
    "authority, truth, dispatch, or closure.  They MUST only consume "
    "canonical outputs produced by the V2 canonical center.  "
    "Code evidence: core.final_acceptance_surface_boundary, "
    "core.outward_runtime_truth."
)

# PR-AGENT-BOUNDED-AUTONOMY: Agent self-action constraint on bounded subjects.
# The Agent running on a bounded subject (Android) has local execution judgment
# and local action capability, but it MUST NOT autonomously decide:
#   1. Participant lifecycle state transitions (attach/detach/terminal).
#   2. Cross-device dispatch mode selection (local vs handoff vs mesh).
#   3. Truth finalization or result authority claims.
#   4. Closure decisions (task completion confirmation).
# These decisions require canonical center governance and must travel the
# declared uplink path to V2 for authoritative resolution.
# TODO(PR-AGENT-BOUNDED): Formalize this as a runtime-enforced constraint
# in the Android agent sandbox, not just a policy statement.
BOUNDED_SUBJECT_AGENT_AUTONOMY_CONSTRAINT: str = (
    "POLICY::BOUNDED_SUBJECT_AGENT_AUTONOMY_LIMITED_V14: "
    "An Agent executing on a bounded subject (Android) has local perception, "
    "local reasoning, and local action capability, but it MUST NOT "
    "autonomously decide participant lifecycle transitions, dispatch modes, "
    "truth finalization, or closure authority.  These decisions require "
    "canonical center governance.  The bounded subject Agent may propose, "
    "signal, and report, but authoritative decisions flow from V2."
)


# ---------------------------------------------------------------------------
# Boundary axis enum
# ---------------------------------------------------------------------------

class PlatformBoundaryAxis(str, Enum):
    """The five boundary axes that define the stable quasi-platform state."""

    CANONICAL_CENTER = "canonical_center"
    BOUNDED_SUBJECT = "bounded_subject"
    PARTICIPANT_GOVERNANCE = "participant_governance"
    OBSERVABILITY_EVIDENCE = "observability_evidence"
    OUTWARD_CONSUMPTION = "outward_consumption"


# ---------------------------------------------------------------------------
# Boundary axis descriptor
# ---------------------------------------------------------------------------

@dataclass
class BoundaryAxisDescriptor:
    """Machine-checkable descriptor for one platform boundary axis."""

    axis: PlatformBoundaryAxis
    description: str
    policy_sentinel: str
    code_evidence: Tuple[str, ...]
    android_v2_consistent: bool
    no_parallel_authority: bool
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "axis": self.axis.value,
            "description": self.description,
            "policy_sentinel": self.policy_sentinel,
            "code_evidence": list(self.code_evidence),
            "android_v2_consistent": self.android_v2_consistent,
            "no_parallel_authority": self.no_parallel_authority,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Platform boundary snapshot
# ---------------------------------------------------------------------------

@dataclass
class PlatformBoundarySnapshot:
    """Aggregate snapshot of all five platform boundary axes."""

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    system_definition: str = QUASI_PLATFORM_STATE_DEFINITION
    authority_sentinel: str = BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY
    pr14v2_sentinel: str = BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL
    axes: List[BoundaryAxisDescriptor] = field(default_factory=list)
    quasi_platform_state_intact: bool = False
    violations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "system_definition": self.system_definition,
            "authority_sentinel": self.authority_sentinel,
            "pr14v2_sentinel": self.pr14v2_sentinel,
            "axes": [a.to_dict() for a in self.axes],
            "quasi_platform_state_intact": self.quasi_platform_state_intact,
            "violations": self.violations,
            "axis_count": len(self.axes),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Canonical boundary axis registry
# ---------------------------------------------------------------------------

def _build_canonical_center_axis() -> BoundaryAxisDescriptor:
    return BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.CANONICAL_CENTER,
        description=(
            "V2 is the sole canonical governance / truth convergence / "
            "dispatch arbitration / closure authority center.  Four authority "
            "domains are explicitly owned: COMPLETION_TRUTH, "
            "CONTINUITY_LEGALITY_TRUTH, DISPATCH_READINESS_TRUTH, "
            "ORCHESTRATION_TRUTH."
        ),
        policy_sentinel=CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY,
        code_evidence=(
            "core.center_authority_boundary.assert_center_authority_intact",
            "core.center_authority_boundary.evaluate_center_authority_boundary",
            "core.unified_result_ingress.UnifiedResultIngress",
            "core.unified_continuity_legality_authority.UnifiedContinuityLegalityAuthority",
            "core.canonical_dispatch_slot_authority.CanonicalDispatchSlotAuthority",
            "core.unified_orchestration_spine",
        ),
        android_v2_consistent=True,
        no_parallel_authority=True,
        notes=(
            "Established by PR-V6 center_authority_boundary.  "
            "assert_center_authority_intact() is the CI gate for this axis."
        ),
    )


def _build_bounded_subject_axis() -> BoundaryAxisDescriptor:
    return BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.BOUNDED_SUBJECT,
        description=(
            "Android is a bounded relative subject runtime with local "
            "lifecycle, local AI consumption, local execution judgment, and "
            "local visible surfaces, but no global truth finalization or "
            "global dispatch authority.  Participant truth evidence must "
            "travel the declared canonical uplink path."
        ),
        policy_sentinel=BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY,
        code_evidence=(
            "contracts.distributed_subject_contract_v1.DISTRIBUTED_SUBJECT_CONTRACT_V1_SENTINEL",
            "contracts.distributed_subject_contract_v1.PARTICIPANT_LIFECYCLE_IS_GOVERNED_BY_CENTER",
            "contracts.distributed_subject_contract_v1.SUBJECT_EVIDENCE_IS_NOT_CANONICAL_TRUTH",
            "core.android_participant_truth_ingress.ingest_android_participant_truth_message",
            "core.v2_android_truth_ssot.build_v2_android_truth_block",
            "core.android_runtime_host.AndroidRuntimeHostRole",
        ),
        android_v2_consistent=True,
        no_parallel_authority=True,
        notes=(
            "Established by PR-Task3 distributed_subject_contract_v1.  "
            "Android runtime host role is bounded; no parallel center claim."
        ),
    )


def _build_participant_governance_axis() -> BoundaryAxisDescriptor:
    return BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.PARTICIPANT_GOVERNANCE,
        description=(
            "Participant lifecycle state transitions are authoritative only "
            "when issued by V2 canonical governance.  Bounded subjects may "
            "signal readiness / posture / busy but cannot unilaterally "
            "promote or demote their own participant lifecycle state.  "
            "Operator actions are governed by the operator action governance "
            "plane."
        ),
        policy_sentinel=PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY,
        code_evidence=(
            "core.operator_action_governance",
            "core.execution_governance_audit_authority.ExecutionGovernanceAuditAuthority",
            "core.android_participant_truth_ingress",
            "core.v2_android_truth_ssot",
        ),
        android_v2_consistent=True,
        no_parallel_authority=True,
        notes=(
            "Established by PR-Task4 operator governance plane.  "
            "Participant lifecycle is center-authoritative."
        ),
    )


def _build_observability_evidence_axis() -> BoundaryAxisDescriptor:
    return BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.OBSERVABILITY_EVIDENCE,
        description=(
            "The four-level visibility taxonomy (LOCAL_VISIBLE, RUNTIME_VISIBLE, "
            "OPERATOR_VISIBLE, PRODUCT_VISIBLE) and five evidence contract kinds "
            "are declared in core.cross_subject_observability_contract.  No new "
            "parallel observability center or diagnostics authority is introduced.  "
            "Observability surfaces are classification and consumption layers only."
        ),
        policy_sentinel=OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY,
        code_evidence=(
            "core.cross_subject_observability_contract.CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY",
            "core.cross_subject_observability_contract.VisibilityLevel",
            "core.cross_subject_observability_contract.EvidenceContractKind",
            "core.cross_subject_observability_contract.get_canonical_evidence_uplink_path",
            "core.cross_subject_observability_contract.NO_PARALLEL_OBSERVABILITY_CENTER_POLICY",
        ),
        android_v2_consistent=True,
        no_parallel_authority=True,
        notes=(
            "Established by PR-12V2 cross_subject_observability_contract.  "
            "No observability surface acts as canonical truth source."
        ),
    )


def _build_outward_consumption_axis() -> BoundaryAxisDescriptor:
    return BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.OUTWARD_CONSUMPTION,
        description=(
            "Outward-facing, product-facing, operator-facing, and projection-facing "
            "surfaces are consumption layers only.  They MUST NOT reassemble "
            "authority, truth, dispatch, or closure.  They consume canonical outputs "
            "produced by the V2 canonical center through declared composition "
            "contracts."
        ),
        policy_sentinel=OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY,
        code_evidence=(
            "core.final_acceptance_surface_boundary.FINAL_ACCEPTANCE_SURFACE_NO_AUTHORITY_REASSEMBLY_POLICY",
            "core.final_acceptance_surface_boundary.build_final_acceptance_surface_boundary",
            "core.outward_runtime_truth.compile_outward_truth",
            "core.routes.operator._operator_consumption_contract_boundary",
            "core.routes.projection._build_truth_acceptance_closure_contract",
            "core.unified_panel_aggregation.UnifiedPanelPayload",
        ),
        android_v2_consistent=True,
        no_parallel_authority=True,
        notes=(
            "Established by PR-13V2 final_acceptance_surface_boundary.  "
            "All outward surfaces are consumption-only."
        ),
    )


PLATFORM_BOUNDARY_AXIS_REGISTRY: List[BoundaryAxisDescriptor] = [
    _build_canonical_center_axis(),
    _build_bounded_subject_axis(),
    _build_participant_governance_axis(),
    _build_observability_evidence_axis(),
    _build_outward_consumption_axis(),
]


# ---------------------------------------------------------------------------
# Quasi-platform state evaluation
# ---------------------------------------------------------------------------

def evaluate_quasi_platform_state(
    axes: List[BoundaryAxisDescriptor],
) -> Tuple[bool, List[str]]:
    """Evaluate whether all five boundary axes satisfy quasi-platform state.

    Returns
    -------
    Tuple[bool, List[str]]
        (intact, violations) where intact is True when all axes satisfy their
        invariants and violations is an empty list.
    """
    violations: List[str] = []
    for axis in axes:
        if not axis.android_v2_consistent:
            violations.append(
                f"axis={axis.axis.value}: android_v2_consistent=False — "
                "Android and V2 system definitions are inconsistent."
            )
        if not axis.no_parallel_authority:
            violations.append(
                f"axis={axis.axis.value}: no_parallel_authority=False — "
                "a parallel authority has been introduced on this axis."
            )
        if not axis.code_evidence:
            violations.append(
                f"axis={axis.axis.value}: code_evidence is empty — "
                "no real code evidence anchors this boundary axis."
            )
    intact = len(violations) == 0
    return intact, violations


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def build_platform_boundary_snapshot() -> PlatformBoundarySnapshot:
    """Build a machine-checkable snapshot of all five platform boundary axes.

    This function composes the five boundary axes from their respective
    canonical modules.  It does NOT reassemble authority, truth, dispatch,
    or closure — those are already established by the prior contracts.

    Returns
    -------
    PlatformBoundarySnapshot
        A fully-populated, serialisable snapshot that can be used by
        acceptance gates, health checks, and CI release-blocking tests.
    """
    axes = list(PLATFORM_BOUNDARY_AXIS_REGISTRY)
    intact, violations = evaluate_quasi_platform_state(axes)
    return PlatformBoundarySnapshot(
        axes=axes,
        quasi_platform_state_intact=intact,
        violations=violations,
    )


def build_quasi_platform_runtime_assertion_report() -> Dict[str, Any]:
    """Build runtime-checkable quasi-platform integrity assertion report."""
    snapshot = build_platform_boundary_snapshot()
    violations: List[str] = list(snapshot.violations)
    axes = list(snapshot.axes)
    axis_map = {axis.axis: axis for axis in axes}

    if len(axes) != 5:
        violations.append(
            f"axis_registry_count={len(axes)} expected=5"
        )
    if len(axis_map) != len(axes):
        violations.append("axis_registry_contains_duplicate_axis_entries")
    if sum(1 for axis in axes if axis.axis == PlatformBoundaryAxis.CANONICAL_CENTER) != 1:
        violations.append("canonical_center_uniqueness_violation")

    canonical_axis = axis_map.get(PlatformBoundaryAxis.CANONICAL_CENTER)
    if canonical_axis is None:
        violations.append("canonical_center_axis_missing")
    elif (
        "sole canonical governance"
        not in canonical_axis.policy_sentinel.lower()
    ):
        violations.append("canonical_center_policy_anchor_missing")

    bounded_subject_axis = axis_map.get(PlatformBoundaryAxis.BOUNDED_SUBJECT)
    if bounded_subject_axis is None:
        violations.append("bounded_subject_axis_missing")
    elif (
        "global truth finalization"
        not in bounded_subject_axis.policy_sentinel.lower()
    ):
        violations.append("bounded_subject_non_sovereignty_policy_anchor_missing")

    observability_axis = axis_map.get(PlatformBoundaryAxis.OBSERVABILITY_EVIDENCE)
    if observability_axis is None:
        violations.append("observability_axis_missing")
    else:
        observability_policy = observability_axis.policy_sentinel.lower()
        if "canonical truth source" not in observability_policy:
            violations.append("observability_not_truth_authority_policy_anchor_missing")

    outward_axis = axis_map.get(PlatformBoundaryAxis.OUTWARD_CONSUMPTION)
    if outward_axis is None:
        violations.append("outward_consumption_axis_missing")
    else:
        outward_policy = outward_axis.policy_sentinel.lower()
        if "consumption" not in outward_policy:
            violations.append("outward_consumption_only_policy_anchor_missing")

    final_acceptance_boundary = build_final_acceptance_surface_boundary(
        surface="quasi_platform_runtime_assertion",
        consumer_role="runtime_assertion_guard",
        canonical_backend_contract="core.v2_unified_state_contract.build_control_plane_surface_contract",
        product_surface="/internal/runtime/quasi-platform-state",
    )
    if not bool(final_acceptance_boundary.get("no_parallel_final_integration_framework")):
        violations.append("parallel_final_integration_framework_detected")
    if not bool(final_acceptance_boundary.get("outward_surfaces_consume_canonical_outputs_only")):
        violations.append("outward_surfaces_not_consumption_only")

    intact = len(violations) == 0
    return {
        "intact": intact,
        "violations": violations,
        "axis_count": len(axes),
        "checked_axes": [axis.axis.value for axis in axes],
        "final_acceptance_boundary_flags": {
            "no_parallel_final_integration_framework": bool(
                final_acceptance_boundary.get("no_parallel_final_integration_framework")
            ),
            "outward_surfaces_consume_canonical_outputs_only": bool(
                final_acceptance_boundary.get("outward_surfaces_consume_canonical_outputs_only")
            ),
        },
        "snapshot": snapshot.to_dict(),
        "_source": "core.bounded_subject_platform_boundary.build_quasi_platform_runtime_assertion_report",
    }


def assert_quasi_platform_state_intact() -> None:
    """Assert that all five platform boundary axes are intact.

    Raises
    ------
    QuasiPlatformStateBoundaryViolation
        When one or more boundary axes are not intact.
    """
    runtime_report = build_quasi_platform_runtime_assertion_report()
    if not runtime_report["intact"]:
        snapshot_dict = dict(runtime_report.get("snapshot") or {})
        snapshot = PlatformBoundarySnapshot(
            snapshot_id=snapshot_dict.get("snapshot_id", str(uuid.uuid4())),
            timestamp=float(snapshot_dict.get("timestamp", time.time())),
            system_definition=snapshot_dict.get("system_definition", QUASI_PLATFORM_STATE_DEFINITION),
            authority_sentinel=snapshot_dict.get(
                "authority_sentinel",
                BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY,
            ),
            pr14v2_sentinel=snapshot_dict.get(
                "pr14v2_sentinel",
                BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL,
            ),
            axes=get_platform_boundary_axes(),
            quasi_platform_state_intact=False,
            violations=list(runtime_report.get("violations") or []),
        )
        raise QuasiPlatformStateBoundaryViolation(
            f"Quasi-platform state boundary not intact: "
            f"violations={runtime_report['violations']}",
            snapshot=snapshot,
        )


def get_platform_boundary_axes() -> List[BoundaryAxisDescriptor]:
    """Return the canonical list of all five boundary axis descriptors."""
    return list(PLATFORM_BOUNDARY_AXIS_REGISTRY)


def get_system_definition() -> str:
    """Return the formal system definition string."""
    return QUASI_PLATFORM_STATE_DEFINITION


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class QuasiPlatformStateBoundaryViolation(Exception):
    """Raised when the quasi-platform state boundary is not intact."""

    def __init__(
        self,
        message: str,
        snapshot: Optional[PlatformBoundarySnapshot] = None,
    ) -> None:
        super().__init__(message)
        self.snapshot = snapshot
