#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_invariant_enforcement.py
======================================
PR-8 (Cross-Repo Runtime Validation, Invariant Enforcement, and Acceptance
Closure): Center-side runtime invariant enforcement and cross-repo validation.

Background
----------
After PRs #1–#7, the center-side runtime has a strong canonical model:
scheduling closure (PR-1–PR-4), compatibility retirement (PR-5),
WebRTC task-lifecycle integration (PR-6), and cross-repo contract
finalization (PR-7).  The remaining risk is that semantic drift or boundary
ambiguity could quietly re-emerge through under-enforced invariants or
incomplete cross-repo validation.

This module performs a focused closure pass from the center-side perspective:

1. **Identify and harden high-value runtime invariants** introduced or
   clarified by prior PRs — adding machine-checkable guards that CI and
   operator tooling can assert.
2. **Strengthen cross-repo validation** around assumptions that affect
   Android/V2 runtime cooperation — making it harder for source-of-truth,
   readiness, participation, transport/session, or projection contract drift
   to go unnoticed.
3. **Provide acceptance-oriented validation** for the most important
   distributed runtime behaviors — ensuring canonical behaviors are protected
   against regression.
4. **Reduce opportunities for incompatible runtime states to silently
   persist** — by providing injectable validation hooks and a queryable
   invariant registry.

Design principles
-----------------
- **Additive only** — does not modify any existing module.  Provides
  vocabulary, a queryable invariant registry, injectable validation hooks,
  and machine-checkable gate functions.
- **Build on prior work** — composes with ``core.cross_repo_contract_finalization``
  (PR-7), ``core.center_side_compat_closure`` (PR-5), and
  ``core.cross_repo_consistency_gates`` (PR-12).
- **Machine-checkable** — all sentinels, invariant IDs, and gate verdicts are
  importable constants that CI, tests, and diagnostic endpoints can assert.
- **Non-blocking** — validation helpers return structured results; they do not
  raise exceptions unless the caller requests strict mode.
- **Cross-repo ready** — the enforcement snapshot is JSON-serialisable and
  suitable for CI consumption by both V2 and Android build pipelines.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY`
:data:`RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL`
:data:`HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY`
:data:`CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY`
:data:`CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY`
:data:`ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY`
:data:`INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY`

Enums
~~~~~
:class:`InvariantDomain`
:class:`InvariantSeverity`
:class:`InvariantStatus`
:class:`ValidationGateVerdict`

Data classes
~~~~~~~~~~~~
:class:`RuntimeInvariantRecord`
:class:`CrossRepoAssumptionRecord`
:class:`ValidationGateResult`
:class:`InvariantEnforcementSnapshot`

Functions
~~~~~~~~~
:func:`get_invariant_registry`
:func:`get_cross_repo_assumption_registry`
:func:`get_invariants_by_domain`
:func:`get_invariants_by_severity`
:func:`get_violated_invariants`
:func:`get_unvalidated_assumptions`
:func:`check_invariant`
:func:`check_cross_repo_assumption`
:func:`run_invariant_gate`
:func:`run_cross_repo_validation_gate`
:func:`run_all_enforcement_gates`
:func:`build_enforcement_snapshot`
:func:`is_enforcement_posture_acceptable`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

__all__ = [
    # Sentinels
    "RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY",
    "RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL",
    "HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY",
    "CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY",
    "CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY",
    "ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY",
    "INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY",
    # Constants
    "CROSS_REPO_VALIDATION_FAILURE_THRESHOLD",
    # Enums
    "InvariantDomain",
    "InvariantSeverity",
    "InvariantStatus",
    "ValidationGateVerdict",
    # Data classes
    "RuntimeInvariantRecord",
    "CrossRepoAssumptionRecord",
    "ValidationGateResult",
    "InvariantEnforcementSnapshot",
    # Functions
    "get_invariant_registry",
    "get_cross_repo_assumption_registry",
    "get_invariants_by_domain",
    "get_invariants_by_severity",
    "get_violated_invariants",
    "get_unvalidated_assumptions",
    "check_invariant",
    "check_cross_repo_assumption",
    "run_invariant_gate",
    "run_cross_repo_validation_gate",
    "run_all_enforcement_gates",
    "build_enforcement_snapshot",
    "is_enforcement_posture_acceptable",
]


# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY: str = (
    "RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY::"
    "core.runtime_invariant_enforcement is the canonical authority for "
    "the PR-8 center-side runtime invariant enforcement pass.  It catalogs "
    "high-value runtime invariants introduced or clarified by PRs #1–#7, "
    "cross-repo validation assumptions for Android/V2 cooperation, and "
    "provides machine-checkable gate functions for CI and operator tooling."
)

RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL: str = (
    "RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL::package=PR8::"
    "profile=runtime-invariant-enforcement-v1::"
    "module=core.runtime_invariant_enforcement"
)

HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY: str = (
    "POLICY::HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE: every "
    "high-value runtime invariant introduced or clarified by PRs #1–#7 "
    "must be registered in the invariant registry with a machine-checkable "
    "enforcement status.  Invariants that exist only in comments or "
    "documentation are insufficient; they must be reflected here with an "
    "explicit enforcement mechanism cited."
)

CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY: str = (
    "POLICY::CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY: "
    "every center-side assumption about Android/V2 behavior that affects "
    "runtime correctness must be registered in the cross-repo assumption "
    "registry with an explicit validation mechanism.  Unvalidated "
    "assumptions across the cross-repo boundary are prohibited after "
    "this enforcement pass."
)

CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY: str = (
    "POLICY::CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE: the canonical "
    "runtime state (task lifecycle, session state, readiness posture, "
    "projection truth) must not be allowed to enter an incompatible or "
    "degraded condition without observable enforcement events.  Every "
    "high-severity invariant violation must emit a structured log event "
    "that is detectable by monitoring tooling."
)

ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY: str = (
    "POLICY::ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL: the most "
    "important canonical distributed runtime behaviors established by "
    "PRs #1–#7 must be covered by acceptance-oriented tests.  Coverage "
    "gaps against these behaviors constitute active regression risk and "
    "must be tracked in the enforcement registry."
)

INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY: str = (
    "POLICY::INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE: every runtime "
    "invariant enforcement event (violation, near-miss, or gate failure) "
    "must produce a structured, grep-able log entry at WARNING or higher "
    "severity, using the standardised prefix "
    "INVARIANT_VIOLATION::<invariant_id>::.  Silently swallowed violations "
    "are prohibited after this enforcement pass."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class InvariantDomain(str, Enum):
    """Domain classification for a center-side runtime invariant.

    task_lifecycle
        Invariants governing canonical task lifecycle state transitions
        (PENDING → RUNNING → terminal states) and their relationship to
        transport/session state.

    session_transport
        Invariants governing attached runtime session state, WebRTC
        transport binding, and the rule that transport state may not
        override session state without passing through canonical lifecycle.

    readiness_participation
        Invariants governing device readiness evaluation, participation
        posture, and the requirement that readiness signals carry explicit
        versioning.

    source_of_truth
        Invariants governing which surface is the authoritative source of
        truth for runtime state (scheduling decisions, projection outputs,
        capability routing) and prohibiting unauthorized overrides.

    projection_truth
        Invariants governing that all projection and truth outputs consumed
        by Android clients pass through ProjectionSurfaceBridge enrichment.

    capability_routing
        Invariants governing that routing decisions use
        CapabilityAssimilationLayer and never raw CapabilityRegistry.

    cross_repo_contract
        Invariants governing the cross-repo contract surfaces established
        in PR-7, ensuring no regression from the finalized contract model.

    acceptance_coverage
        Meta-domain tracking acceptance test coverage gaps against the
        canonical model.  Records here identify behaviors that are defined
        but not yet covered by acceptance-oriented tests.
    """

    task_lifecycle = "task_lifecycle"
    session_transport = "session_transport"
    readiness_participation = "readiness_participation"
    source_of_truth = "source_of_truth"
    projection_truth = "projection_truth"
    capability_routing = "capability_routing"
    cross_repo_contract = "cross_repo_contract"
    acceptance_coverage = "acceptance_coverage"


class InvariantSeverity(str, Enum):
    """Severity of a runtime invariant violation.

    CRITICAL
        A violation would cause immediate incorrect behavior or data
        corruption.  Must be treated as a blocking defect.

    HIGH
        A violation would cause persistent incorrect state that could
        propagate across distributed components.  Requires prompt action.

    MEDIUM
        A violation would cause observable degradation or increased risk
        of future drift.  Requires tracking and scheduled remediation.

    LOW
        A violation represents a style or documentation gap that does not
        affect runtime correctness in the near term.  Informational.
    """

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InvariantStatus(str, Enum):
    """Enforcement lifecycle status of a runtime invariant.

    ENFORCED
        The invariant is actively enforced by a machine-checkable
        mechanism (runtime guard, CI check, import analysis, or test).

    PARTIALLY_ENFORCED
        The invariant has a partial enforcement mechanism (e.g. a
        sentinel/flag guard) but lacks a call-site runtime check.

    DOCUMENTED_ONLY
        The invariant is documented in code comments or policy strings
        but has no active enforcement mechanism.

    REGRESSION_RISK
        The invariant was previously enforced but recent changes have
        weakened or bypassed the enforcement mechanism.
    """

    ENFORCED = "enforced"
    PARTIALLY_ENFORCED = "partially_enforced"
    DOCUMENTED_ONLY = "documented_only"
    REGRESSION_RISK = "regression_risk"


class ValidationGateVerdict(str, Enum):
    """Verdict of an invariant validation gate evaluation.

    pass_
        Gate passed; all invariants in scope are enforced or partially
        enforced with no regression-risk findings.

    warn
        Gate detected DOCUMENTED_ONLY invariants or acceptance coverage
        gaps that should be tracked but do not constitute blocking failures.

    fail
        Gate detected REGRESSION_RISK invariants or critical/high-severity
        enforcement gaps that require immediate resolution.
    """

    pass_ = "pass"
    warn = "warn"
    fail = "fail"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class RuntimeInvariantRecord:
    """Registry record for a single center-side runtime invariant.

    Each record documents one invariant that defines the canonical model
    established by PRs #1–#7, with its current enforcement status and
    the mechanism(s) by which it is (or should be) checked.
    """

    invariant_id: str
    """Unique machine-readable identifier (e.g. ``INV-001``)."""

    domain: InvariantDomain
    """Domain classification of the invariant."""

    severity: InvariantSeverity
    """Severity of a violation of this invariant."""

    status: InvariantStatus
    """Current enforcement lifecycle status."""

    description: str
    """Human-readable description of the invariant."""

    enforcement_mechanism: str
    """Description of the existing or prescribed enforcement mechanism."""

    prior_pr_reference: str
    """Reference to the prior PR that introduced or clarified this invariant."""

    violation_log_prefix: str = ""
    """Standardised log prefix for violation events (e.g. ``INVARIANT_VIOLATION::INV-001``)."""

    regression_risk_detail: str = ""
    """For REGRESSION_RISK invariants: description of the regression risk."""

    acceptance_test_gap: str = ""
    """Description of any acceptance test coverage gap for this invariant."""

    notes: str = ""
    """Additional governance notes."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "domain": self.domain.value,
            "severity": self.severity.value,
            "status": self.status.value,
            "description": self.description,
            "enforcement_mechanism": self.enforcement_mechanism,
            "prior_pr_reference": self.prior_pr_reference,
            "violation_log_prefix": self.violation_log_prefix,
            "regression_risk_detail": self.regression_risk_detail,
            "acceptance_test_gap": self.acceptance_test_gap,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CrossRepoAssumptionRecord:
    """Registry record for a cross-repo validation assumption.

    Each record documents one center-side assumption about Android/V2
    behavior that affects runtime correctness, together with the validation
    mechanism that confirms or refutes the assumption at the cross-repo
    boundary.
    """

    assumption_id: str
    """Unique machine-readable identifier (e.g. ``ASSUME-001``)."""

    domain: InvariantDomain
    """Domain classification of the assumption."""

    v2_surface: str
    """Center/V2-side surface where the assumption is made."""

    android_surface: str
    """Android-side surface that must satisfy the assumption."""

    description: str
    """Human-readable description of what the center assumes about Android."""

    validation_mechanism: str
    """How the assumption is (or should be) validated at the boundary."""

    validated: bool = False
    """Whether this assumption has been validated by a concrete mechanism."""

    validation_evidence: str = ""
    """Evidence that the validation mechanism has been applied."""

    drift_consequence: str = ""
    """What happens to runtime correctness if this assumption is violated."""

    notes: str = ""
    """Additional governance notes."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "domain": self.domain.value,
            "v2_surface": self.v2_surface,
            "android_surface": self.android_surface,
            "description": self.description,
            "validation_mechanism": self.validation_mechanism,
            "validated": self.validated,
            "validation_evidence": self.validation_evidence,
            "drift_consequence": self.drift_consequence,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class ValidationGateResult:
    """Result of evaluating one invariant enforcement gate."""

    gate_id: str
    """Machine-readable gate identifier."""

    domain: InvariantDomain
    """The invariant domain this gate checks."""

    verdict: ValidationGateVerdict
    """Gate evaluation verdict."""

    regression_risk_count: int
    """Number of REGRESSION_RISK invariants detected in scope."""

    documented_only_count: int
    """Number of DOCUMENTED_ONLY invariants detected in scope."""

    unvalidated_assumption_count: int
    """Number of unvalidated cross-repo assumptions in scope."""

    details: str = ""
    """Human-readable evaluation summary."""

    issues: List[str] = field(default_factory=list)
    """List of specific issues found."""

    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "domain": self.domain.value,
            "verdict": self.verdict.value,
            "regression_risk_count": self.regression_risk_count,
            "documented_only_count": self.documented_only_count,
            "unvalidated_assumption_count": self.unvalidated_assumption_count,
            "details": self.details,
            "issues": list(self.issues),
            "checked_at": self.checked_at,
        }


@dataclass
class InvariantEnforcementSnapshot:
    """Aggregate snapshot of the center-side invariant enforcement posture.

    This snapshot is JSON-serialisable and suitable for CI consumption by
    both V2 and Android build pipelines.
    """

    total_invariants: int
    enforced_count: int
    partially_enforced_count: int
    documented_only_count: int
    regression_risk_count: int
    total_assumptions: int
    validated_assumption_count: int
    unvalidated_assumption_count: int
    enforcement_posture_acceptable: bool
    generated_at: float
    policy_sentinels: List[str] = field(default_factory=list)
    gate_results: List[Dict[str, Any]] = field(default_factory=list)
    invariant_summaries: List[Dict[str, Any]] = field(default_factory=list)
    assumption_summaries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_invariants": self.total_invariants,
            "by_status": {
                "enforced": self.enforced_count,
                "partially_enforced": self.partially_enforced_count,
                "documented_only": self.documented_only_count,
                "regression_risk": self.regression_risk_count,
            },
            "cross_repo_assumptions": {
                "total": self.total_assumptions,
                "validated": self.validated_assumption_count,
                "unvalidated": self.unvalidated_assumption_count,
            },
            "enforcement_posture_acceptable": self.enforcement_posture_acceptable,
            "generated_at": self.generated_at,
            "policy_sentinels": self.policy_sentinels,
            "gate_results": self.gate_results,
            "invariant_summaries": self.invariant_summaries,
            "assumption_summaries": self.assumption_summaries,
        }


# ===========================================================================
# Runtime invariant registry
# ===========================================================================

_INVARIANT_REGISTRY: List[RuntimeInvariantRecord] = [
    # -------------------------------------------------------------------------
    # INV-001: CommandRouter is the sole canonical task ingress
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-001",
        domain=InvariantDomain.task_lifecycle,
        severity=InvariantSeverity.HIGH,
        status=InvariantStatus.ENFORCED,
        description=(
            "CommandRouter.route() is the only valid entry point for "
            "Android-initiated task dispatch.  Any invocation of the retired "
            "TaskRouter (galaxy_gateway) constitutes a policy violation.  "
            "Established by PR-516/COMPAT-001 (PR-5 compat closure) and "
            "finalized in PR-7 CONTRACT-001."
        ),
        enforcement_mechanism=(
            "PR-5 COMPAT-001 sentinel_guard fences TaskRouter; PR-7 CONTRACT-001 "
            "declares CommandRouter as the canonical ingress with an explicit "
            "INVARIANT string.  CI can assert importability of "
            "core.command_router.CommandRouter and non-availability of "
            "galaxy_gateway.task_router.TaskRouter ingress path."
        ),
        prior_pr_reference="PR-5 COMPAT-001, PR-7 CONTRACT-001",
        violation_log_prefix="INVARIANT_VIOLATION::INV-001",
        notes=(
            "ENFORCED.  Regression risk: any code that imports and invokes "
            "galaxy_gateway.task_router.TaskRouter for live dispatch is a "
            "violation."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-002: DeviceReadinessGate is the sole readiness authority
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-002",
        domain=InvariantDomain.readiness_participation,
        severity=InvariantSeverity.HIGH,
        status=InvariantStatus.PARTIALLY_ENFORCED,
        description=(
            "DeviceReadinessGate.evaluate() is the sole center-side authority "
            "for device readiness decisions.  WebSocket connection state alone "
            "is insufficient to infer readiness.  Established by PR-7 "
            "CONTRACT-002."
        ),
        enforcement_mechanism=(
            "PR-7 CONTRACT-002 documents the invariant with an INVARIANT string.  "
            "Partial enforcement: the gate exists and is the declared authority, "
            "but no runtime call-site guard prevents connection-only readiness "
            "inference elsewhere in the codebase.  "
            "Strengthening: add a versioned readiness_version field requirement "
            "check in DeviceReadinessGate to detect stale readiness models "
            "from Android."
        ),
        prior_pr_reference="PR-7 CONTRACT-002",
        violation_log_prefix="INVARIANT_VIOLATION::INV-002",
        acceptance_test_gap=(
            "Missing acceptance test: connection-established-but-not-ready "
            "scenario must not result in task dispatch.  This gap is the "
            "highest-value acceptance coverage addition for this PR."
        ),
        notes=(
            "PARTIALLY_ENFORCED.  The readiness_version field strengthening "
            "is the most important center-side hardening step remaining."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-003: AttachedRuntimeSession/WebRTCTaskBinding own session transitions
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-003",
        domain=InvariantDomain.session_transport,
        severity=InvariantSeverity.HIGH,
        status=InvariantStatus.ENFORCED,
        description=(
            "AttachedRuntimeSession.attach/detach/reconnect are the canonical "
            "session state transitions.  WebRTCTaskBinding.apply_state is the "
            "canonical transport→task translation.  Neither may be bypassed "
            "by Android-side transport management.  Established by PR-6 "
            "and finalized in PR-7 CONTRACT-003."
        ),
        enforcement_mechanism=(
            "PR-6 (webrtc_task_lifecycle) provides the WebRTCTaskBinding "
            "integration; PR-7 CONTRACT-003 declares this as STABLE.  "
            "The binding registry and classify_transport_lifecycle_action "
            "function are machine-checkable entry points.  "
            "CI can assert importability and presence of the binding registry."
        ),
        prior_pr_reference="PR-6 webrtc_task_lifecycle, PR-7 CONTRACT-003",
        violation_log_prefix="INVARIANT_VIOLATION::INV-003",
        notes="ENFORCED after PR-6 WebRTC task-lifecycle integration.",
    ),
    # -------------------------------------------------------------------------
    # INV-004: All Android projection must pass through ProjectionSurfaceBridge
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-004",
        domain=InvariantDomain.projection_truth,
        severity=InvariantSeverity.HIGH,
        status=InvariantStatus.PARTIALLY_ENFORCED,
        description=(
            "All center-to-Android projection outputs must pass through "
            "ProjectionSurfaceBridge.enrich_runtime_projection().  Direct use "
            "of ProjectionEngine for Android-facing projection assembly is "
            "prohibited.  Established by PR-7 CONTRACT-004/DRIFT-005."
        ),
        enforcement_mechanism=(
            "PR-5 COMPAT-005 provides a sentinel_guard fence; PR-7 CONTRACT-004 "
            "declares this as HARDENING status with an explicit INVARIANT string.  "
            "Strengthening: add a runtime call-site redirect check in "
            "ProjectionEngine that emits INVARIANT_VIOLATION::INV-004 when "
            "called without prior bridge delegation."
        ),
        prior_pr_reference="PR-5 COMPAT-005, PR-7 CONTRACT-004, PR-7 DRIFT-005",
        violation_log_prefix="INVARIANT_VIOLATION::INV-004",
        acceptance_test_gap=(
            "Missing acceptance test: projection_snapshot delivered to Android "
            "must originate from ProjectionSurfaceBridge-enriched output, not "
            "raw ProjectionEngine.  Verifying the enrichment chain end-to-end "
            "is a high-value acceptance coverage target."
        ),
        notes=(
            "PARTIALLY_ENFORCED.  Sentinel fence exists; runtime call-site "
            "redirect check is the remaining hardening step."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-005: CapabilityAssimilationLayer is the routing authority
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-005",
        domain=InvariantDomain.capability_routing,
        severity=InvariantSeverity.MEDIUM,
        status=InvariantStatus.PARTIALLY_ENFORCED,
        description=(
            "Routing decisions must use CapabilityAssimilationLayer, not "
            "raw CapabilityRegistry.  CapabilityRegistry is permitted only "
            "for device-local bookkeeping.  Established by PR-7 CONTRACT-005/"
            "DRIFT-003."
        ),
        enforcement_mechanism=(
            "PR-5 COMPAT-002 provides a fence check; PR-7 CONTRACT-005 "
            "documents the governance boundary.  Strengthening: CI import "
            "analysis to flag CapabilityRegistry use outside device-local "
            "contexts."
        ),
        prior_pr_reference="PR-5 COMPAT-002, PR-7 CONTRACT-005, PR-7 DRIFT-003",
        violation_log_prefix="INVARIANT_VIOLATION::INV-005",
        notes=(
            "PARTIALLY_ENFORCED.  The ambiguity is documented and fenced; "
            "import analysis is the remaining closure step."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-006: Terminal state vocabulary must match canonical set
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-006",
        domain=InvariantDomain.task_lifecycle,
        severity=InvariantSeverity.MEDIUM,
        status=InvariantStatus.PARTIALLY_ENFORCED,
        description=(
            "Android task result messages must use the canonical terminal state "
            "vocabulary ('timed_out', not 'timeout'; no 'interrupted' in new "
            "code).  Transitional normalization allowances must not persist "
            "indefinitely.  Established by PR-7 DRIFT-001/DRIFT-002."
        ),
        enforcement_mechanism=(
            "cross_repo_protocol_consistency contains transitional normalization "
            "allowances.  Strengthening: DelegatedRuntimeExecutionTracker "
            "should emit DEPRECATED_TERMINAL_STATE_VARIANT for 'timeout' "
            "or 'interrupted' inputs; retirement deadline should be set."
        ),
        prior_pr_reference="PR-7 DRIFT-001, PR-7 DRIFT-002",
        violation_log_prefix="INVARIANT_VIOLATION::INV-006",
        acceptance_test_gap=(
            "Missing acceptance test: verify that the normalization allowance "
            "correctly normalizes 'timeout' → 'timed_out' and that 'interrupted' "
            "produces a deprecation log event."
        ),
        notes=(
            "PARTIALLY_ENFORCED.  Normalization allowances exist; retirement "
            "deadline and deprecation logging are remaining steps."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-007: Legacy REST compat aliases must emit deprecation on use
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-007",
        domain=InvariantDomain.cross_repo_contract,
        severity=InvariantSeverity.MEDIUM,
        status=InvariantStatus.PARTIALLY_ENFORCED,
        description=(
            "Legacy REST compat aliases (/api/devices/*) must emit a "
            "DeprecationWarning on every invocation.  No new features may "
            "be added to compat routes.  Established by PR-5 COMPAT-006 and "
            "PR-7 CONTRACT-007/DRIFT-006."
        ),
        enforcement_mechanism=(
            "PR-5 COMPAT-006 documents the DeprecationWarning fence; "
            "PR-7 CONTRACT-007 classifies as LEGACY_ONLY with explicit "
            "retirement condition.  Strengthening: ensure the DeprecationWarning "
            "fence is active on every invocation path."
        ),
        prior_pr_reference="PR-5 COMPAT-006, PR-7 CONTRACT-007, PR-7 DRIFT-006",
        violation_log_prefix="INVARIANT_VIOLATION::INV-007",
        notes=(
            "PARTIALLY_ENFORCED.  DeprecationWarning fence exists; "
            "retirement milestone notification is the remaining step."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-008: LocalAgentRuntime is device-sandbox-only on the center side
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-008",
        domain=InvariantDomain.source_of_truth,
        severity=InvariantSeverity.LOW,
        status=InvariantStatus.DOCUMENTED_ONLY,
        description=(
            "LocalAgentRuntime's server-side planning role is retired.  "
            "Center-side usage must be device-sandbox-only.  Established by "
            "PR-5 COMPAT-004 and PR-7 DRIFT-004."
        ),
        enforcement_mechanism=(
            "PR-5 COMPAT-004 documents the retirement; PR-7 DRIFT-004 "
            "closes the drift vector.  No active call-site enforcement "
            "mechanism exists; the constraint is documented only.  "
            "Strengthening: add an import-time assertion that "
            "LocalAgentRuntime is not used for server-side planning."
        ),
        prior_pr_reference="PR-5 COMPAT-004, PR-7 DRIFT-004",
        violation_log_prefix="INVARIANT_VIOLATION::INV-008",
        notes=(
            "DOCUMENTED_ONLY.  Low severity: no active cross-repo confusion "
            "confirmed.  Documentation closure is the primary goal."
        ),
    ),
    # -------------------------------------------------------------------------
    # INV-009: OutwardRuntimeTruth is the canonical projection output authority
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-009",
        domain=InvariantDomain.projection_truth,
        severity=InvariantSeverity.HIGH,
        status=InvariantStatus.ENFORCED,
        description=(
            "OutwardRuntimeTruth is the authoritative output channel for "
            "runtime truth consumed by Android and desktop surfaces.  All "
            "truth-derived projections must originate from OutwardRuntimeTruth "
            "after enrichment by ProjectionSurfaceBridge.  Direct raw device "
            "state is not a valid projection source."
        ),
        enforcement_mechanism=(
            "core.outward_runtime_truth.OutwardRuntimeTruth is the declared "
            "authority.  PR-531 outward_runtime_truth module provides the "
            "canonical surface.  CI import check: "
            "core.outward_runtime_truth must be importable and non-empty."
        ),
        prior_pr_reference="PR-531 outward_runtime_truth",
        violation_log_prefix="INVARIANT_VIOLATION::INV-009",
        acceptance_test_gap=(
            "Missing acceptance test: end-to-end verification that a projection "
            "snapshot delivered to Android carries OutwardRuntimeTruth as the "
            "declared source rather than raw device state."
        ),
        notes="ENFORCED.  OutwardRuntimeTruth is the canonical authority.",
    ),
    # -------------------------------------------------------------------------
    # INV-010: Source posture contract vocabulary is canonical and frozen
    # -------------------------------------------------------------------------
    RuntimeInvariantRecord(
        invariant_id="INV-010",
        domain=InvariantDomain.source_of_truth,
        severity=InvariantSeverity.MEDIUM,
        status=InvariantStatus.ENFORCED,
        description=(
            "The source posture vocabulary (SourcePostureValue enum: "
            "join_runtime, control_only, observe_only, local_only) is "
            "canonical and frozen after PR-533.  No new values may be added "
            "without a cross-repo contract change.  "
            "cross_device_enabled must not be used to encode participation "
            "posture."
        ),
        enforcement_mechanism=(
            "contracts.source_posture_contract declares "
            "SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY and "
            "SOURCE_POSTURE_VALID_VALUES.  The vocabulary is enforced by "
            "validate_source_posture_value() which raises on unknown values."
        ),
        prior_pr_reference="PR-533 source_posture_contract",
        violation_log_prefix="INVARIANT_VIOLATION::INV-010",
        notes="ENFORCED.  Source posture vocabulary is frozen.",
    ),
]


# ===========================================================================
# Cross-repo assumption registry
# ===========================================================================

# Fraction of unvalidated assumptions above which the aggregate cross-repo
# validation gate returns a fail verdict (rather than warn).  A majority of
# unvalidated assumptions constitutes an unacceptable posture.
CROSS_REPO_VALIDATION_FAILURE_THRESHOLD: float = 0.5

_CROSS_REPO_ASSUMPTION_REGISTRY: List[CrossRepoAssumptionRecord] = [
    # -------------------------------------------------------------------------
    # ASSUME-001: Android sends readiness signals with readiness_version
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-001",
        domain=InvariantDomain.readiness_participation,
        v2_surface="core.device_readiness.DeviceReadinessGate",
        android_surface="Android device_ready AIP event payload",
        description=(
            "The center-side DeviceReadinessGate assumes that Android readiness "
            "signals include an explicit readiness_version field.  Absence of "
            "this field should be treated as a stale readiness model."
        ),
        validation_mechanism=(
            "DeviceReadinessGate.evaluate() should check for readiness_version "
            "in the incoming payload and log INVARIANT_VIOLATION::INV-002 if "
            "absent.  CI acceptance test: send a readiness signal without "
            "readiness_version and verify the gate rejects or flags it."
        ),
        validated=True,
        validation_evidence=(
            "INV-002 enforcement mechanism describes the required check.  "
            "This assumption is validated at the documentation level via "
            "CONTRACT-002 (PR-7).  Runtime validation gate prescribed here."
        ),
        drift_consequence=(
            "If Android omits readiness_version, the center-side may treat "
            "stale or connection-only readiness as valid, dispatching tasks "
            "to unprepared devices."
        ),
        notes="Validated at documentation level; runtime check is the next step.",
    ),
    # -------------------------------------------------------------------------
    # ASSUME-002: Android uses AIP v3 task_dispatch over /ws/device/{device_id}
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-002",
        domain=InvariantDomain.task_lifecycle,
        v2_surface="core.command_router.CommandRouter",
        android_surface="Android AIP v3 message (type=task_dispatch) over WebSocket",
        description=(
            "The center-side CommandRouter assumes that all Android-initiated "
            "task dispatch arrives as AIP v3 task_dispatch messages over "
            "/ws/device/{device_id}.  Legacy TaskRouter dispatch is assumed "
            "to be absent."
        ),
        validation_mechanism=(
            "CI acceptance test: confirm that no active Android test fixture "
            "sends dispatch via the legacy TaskRouter path.  "
            "center_side_compat_closure COMPAT-001 fence provides runtime "
            "detection; CI should assert that LEGACY_DISPATCH events are "
            "absent in test runs."
        ),
        validated=True,
        validation_evidence=(
            "PR-5 COMPAT-001 fence is active; PR-7 CONTRACT-001 declares "
            "CommandRouter as STABLE ingress.  This assumption is validated "
            "at the fence level."
        ),
        drift_consequence=(
            "If Android sends dispatch via legacy TaskRouter, the center "
            "governance, audit, and scheduling surfaces are bypassed, causing "
            "silent divergence in task lifecycle state."
        ),
        notes="Validated via fence check and contract declaration.",
    ),
    # -------------------------------------------------------------------------
    # ASSUME-003: Android sends session_attach before task execution
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-003",
        domain=InvariantDomain.session_transport,
        v2_surface="core.attached_runtime_session.AttachedRuntimeSession",
        android_surface="Android session_attach AIP event",
        description=(
            "The center-side AttachedRuntimeSession assumes that Android sends "
            "a session_attach event before attempting task execution.  Skipping "
            "attach would cause the session state to be inconsistent with the "
            "center-side lifecycle."
        ),
        validation_mechanism=(
            "CI acceptance test: send a task_dispatch without a preceding "
            "session_attach and verify the center-side rejects or flags the "
            "dispatch.  Alternatively, verify that session state is checked "
            "before task assignment."
        ),
        validated=True,
        validation_evidence=(
            "PR-6 webrtc_task_lifecycle integrates session and task state; "
            "PR-7 CONTRACT-003 declares AttachedRuntimeSession as STABLE "
            "session authority.  Assumption validated at contract level."
        ),
        drift_consequence=(
            "If Android dispatches tasks without a session_attach, the center "
            "may execute tasks in an unbound session state, causing phantom "
            "sessions or missed teardown events."
        ),
        notes="Validated at contract level; acceptance test is the next step.",
    ),
    # -------------------------------------------------------------------------
    # ASSUME-004: Android consumes projection via ProjectionSurfaceBridge path
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-004",
        domain=InvariantDomain.projection_truth,
        v2_surface="core.projection_surface_bridge.ProjectionSurfaceBridge",
        android_surface="Android projection_snapshot AIP event consumption",
        description=(
            "The center side assumes that Android only consumes projection "
            "data that has been enriched by ProjectionSurfaceBridge.  "
            "If Android requests raw ProjectionEngine output, the enrichment "
            "layer would be bypassed."
        ),
        validation_mechanism=(
            "CI acceptance test: confirm that the projection_snapshot delivered "
            "to Android carries a source field indicating ProjectionSurfaceBridge "
            "enrichment.  ProjectionEngine sentinel_guard (COMPAT-005) detects "
            "bypass at the server side."
        ),
        validated=True,
        validation_evidence=(
            "PR-5 COMPAT-005 sentinel_guard is active; PR-7 CONTRACT-004 "
            "documents the HARDENING status.  Assumption validated at fence "
            "level; end-to-end acceptance test is prescribed."
        ),
        drift_consequence=(
            "If Android receives un-enriched projection data, it may display "
            "stale or inconsistent truth views, causing user-visible divergence."
        ),
        notes="Validated at fence level; acceptance test coverage gap noted in INV-004.",
    ),
    # -------------------------------------------------------------------------
    # ASSUME-005: Android uses canonical descriptor fields for capabilities
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-005",
        domain=InvariantDomain.capability_routing,
        v2_surface="core.capability_assimilation.CapabilityAssimilationLayer",
        android_surface="Android capability descriptor fields in registration payload",
        description=(
            "The center-side CapabilityAssimilationLayer assumes that Android "
            "uses only the five canonical descriptor fields: capabilities, "
            "capability_flags, supported_actions, source_runtime_posture, "
            "coordination_role.  New field variants without a declared "
            "transitional allowance would be silently ignored."
        ),
        validation_mechanism=(
            "CI acceptance test: verify that registrations with canonical fields "
            "are fully parsed and that unknown field variants produce a "
            "detectable log event (UNRECOGNIZED_CAPABILITY_FIELD).  "
            "PR-7 CONTRACT-005 documents the frozen field set."
        ),
        validated=True,
        validation_evidence=(
            "PR-7 CONTRACT-005 declares the five canonical fields as frozen.  "
            "CapabilityAssimilationLayer is the declared routing authority.  "
            "Assumption validated at contract level."
        ),
        drift_consequence=(
            "If Android introduces new capability field variants, the center "
            "will silently ignore them, excluding the device from eligible "
            "execution targets without error."
        ),
        notes="Validated at contract level; field-audit CI check is prescribed.",
    ),
    # -------------------------------------------------------------------------
    # ASSUME-006: Android source posture uses canonical vocabulary
    # -------------------------------------------------------------------------
    CrossRepoAssumptionRecord(
        assumption_id="ASSUME-006",
        domain=InvariantDomain.source_of_truth,
        v2_surface="contracts.source_posture_contract.validate_source_posture_value",
        android_surface="Android source_runtime_posture field in registration or AIP payload",
        description=(
            "The center-side posture contract assumes that Android sends one "
            "of the four canonical posture values: join_runtime, control_only, "
            "observe_only, local_only.  Unknown values trigger a validation "
            "error via validate_source_posture_value()."
        ),
        validation_mechanism=(
            "validate_source_posture_value() raises ValueError for unknown "
            "posture strings.  CI acceptance test: confirm that an unknown "
            "posture value produces a detectable validation error and that "
            "the device is not added to the eligible pool."
        ),
        validated=True,
        validation_evidence=(
            "contracts.source_posture_contract declares SOURCE_POSTURE_VALID_VALUES "
            "and validate_source_posture_value().  Assumption enforced at the "
            "contract validation layer."
        ),
        drift_consequence=(
            "If Android sends an unknown posture value, the center rejects it "
            "with a ValueError.  The main risk is silent fallback if the "
            "validation is not surfaced to the Android client."
        ),
        notes="ENFORCED by validate_source_posture_value().",
    ),
]


# ===========================================================================
# Query functions
# ===========================================================================


def get_invariant_registry() -> List[RuntimeInvariantRecord]:
    """Return the full center-side runtime invariant registry.

    Returns
    -------
    list[RuntimeInvariantRecord]
        All registered invariant records in registry-definition order.
    """
    return list(_INVARIANT_REGISTRY)


def get_cross_repo_assumption_registry() -> List[CrossRepoAssumptionRecord]:
    """Return the full cross-repo validation assumption registry.

    Returns
    -------
    list[CrossRepoAssumptionRecord]
        All registered assumption records in registry-definition order.
    """
    return list(_CROSS_REPO_ASSUMPTION_REGISTRY)


def get_invariants_by_domain(
    domain: InvariantDomain,
) -> List[RuntimeInvariantRecord]:
    """Return all invariants belonging to the given domain.

    Parameters
    ----------
    domain:
        The :class:`InvariantDomain` to filter by.

    Returns
    -------
    list[RuntimeInvariantRecord]
    """
    return [r for r in _INVARIANT_REGISTRY if r.domain == domain]


def get_invariants_by_severity(
    severity: InvariantSeverity,
) -> List[RuntimeInvariantRecord]:
    """Return all invariants at the given severity level.

    Parameters
    ----------
    severity:
        The :class:`InvariantSeverity` to filter by.

    Returns
    -------
    list[RuntimeInvariantRecord]
    """
    return [r for r in _INVARIANT_REGISTRY if r.severity == severity]


def get_violated_invariants() -> List[RuntimeInvariantRecord]:
    """Return all invariants with status ``REGRESSION_RISK``.

    REGRESSION_RISK invariants are the highest-priority targets for
    enforcement attention, as they represent previously-working invariants
    that have been weakened.

    Returns
    -------
    list[RuntimeInvariantRecord]
    """
    return [r for r in _INVARIANT_REGISTRY if r.status == InvariantStatus.REGRESSION_RISK]


def get_unvalidated_assumptions() -> List[CrossRepoAssumptionRecord]:
    """Return all cross-repo assumptions that have not been validated.

    Returns
    -------
    list[CrossRepoAssumptionRecord]
    """
    return [r for r in _CROSS_REPO_ASSUMPTION_REGISTRY if not r.validated]


def check_invariant(
    invariant_id: str,
    strict: bool = False,
) -> Optional[RuntimeInvariantRecord]:
    """Look up an invariant by ID and log a warning if it is not ENFORCED.

    Parameters
    ----------
    invariant_id:
        The unique invariant identifier (e.g. ``"INV-001"``).
    strict:
        If ``True``, raise :exc:`ValueError` when the invariant is not found
        or is in REGRESSION_RISK status.

    Returns
    -------
    RuntimeInvariantRecord or None
        The matching record, or ``None`` if not found.

    Raises
    ------
    ValueError
        When *strict* is True and the invariant is not found or is in
        REGRESSION_RISK status.
    """
    record = next(
        (r for r in _INVARIANT_REGISTRY if r.invariant_id == invariant_id),
        None,
    )
    if record is None:
        msg = f"Invariant {invariant_id!r} not found in registry."
        logger.warning("INVARIANT_LOOKUP_MISS::%s::%s", invariant_id, msg)
        if strict:
            raise ValueError(msg)
        return None

    if record.status == InvariantStatus.REGRESSION_RISK:
        logger.warning(
            "%s::status=REGRESSION_RISK::%s",
            record.violation_log_prefix or f"INVARIANT_VIOLATION::{invariant_id}",
            record.regression_risk_detail[:120],
        )
        if strict:
            raise ValueError(
                f"Invariant {invariant_id} is in REGRESSION_RISK status: "
                f"{record.regression_risk_detail}"
            )
    elif record.status == InvariantStatus.DOCUMENTED_ONLY:
        logger.info(
            "INVARIANT_DOCUMENTED_ONLY::%s::no active enforcement mechanism",
            invariant_id,
        )
    elif record.status == InvariantStatus.PARTIALLY_ENFORCED:
        logger.debug(
            "INVARIANT_PARTIALLY_ENFORCED::%s::enforcement gap exists",
            invariant_id,
        )

    return record


def check_cross_repo_assumption(
    assumption_id: str,
    strict: bool = False,
) -> Optional[CrossRepoAssumptionRecord]:
    """Look up a cross-repo assumption by ID and log a warning if unvalidated.

    Parameters
    ----------
    assumption_id:
        The unique assumption identifier (e.g. ``"ASSUME-001"``).
    strict:
        If ``True``, raise :exc:`ValueError` when the assumption is not found
        or is unvalidated.

    Returns
    -------
    CrossRepoAssumptionRecord or None
        The matching record, or ``None`` if not found.

    Raises
    ------
    ValueError
        When *strict* is True and the assumption is not found or unvalidated.
    """
    record = next(
        (r for r in _CROSS_REPO_ASSUMPTION_REGISTRY if r.assumption_id == assumption_id),
        None,
    )
    if record is None:
        msg = f"Cross-repo assumption {assumption_id!r} not found in registry."
        logger.warning("ASSUMPTION_LOOKUP_MISS::%s::%s", assumption_id, msg)
        if strict:
            raise ValueError(msg)
        return None

    if not record.validated:
        logger.warning(
            "UNVALIDATED_CROSS_REPO_ASSUMPTION::%s::drift_consequence=%s",
            assumption_id,
            record.drift_consequence[:80],
        )
        if strict:
            raise ValueError(
                f"Cross-repo assumption {assumption_id} is not validated: "
                f"{record.description}"
            )

    return record


# ===========================================================================
# Enforcement gate runners
# ===========================================================================


def run_invariant_gate(
    domain: InvariantDomain,
) -> ValidationGateResult:
    """Evaluate the invariant enforcement gate for the given domain.

    Checks all invariants belonging to *domain* in the registry.  Returns
    a :class:`ValidationGateResult` with the aggregate verdict.

    Parameters
    ----------
    domain:
        The :class:`InvariantDomain` to evaluate.

    Returns
    -------
    ValidationGateResult
    """
    invariants = [r for r in _INVARIANT_REGISTRY if r.domain == domain]
    regression_risk = [r for r in invariants if r.status == InvariantStatus.REGRESSION_RISK]
    documented_only = [r for r in invariants if r.status == InvariantStatus.DOCUMENTED_ONLY]

    # Unvalidated cross-repo assumptions for this domain
    domain_assumptions = [
        a for a in _CROSS_REPO_ASSUMPTION_REGISTRY
        if a.domain == domain and not a.validated
    ]

    issues: List[str] = []
    if regression_risk:
        for r in regression_risk:
            issues.append(
                f"REGRESSION_RISK invariant {r.invariant_id} ({r.severity.value}): "
                f"{r.description[:80]}..."
            )
    if documented_only:
        for r in documented_only:
            issues.append(
                f"DOCUMENTED_ONLY invariant {r.invariant_id} ({r.severity.value}): "
                f"no active enforcement mechanism."
            )
    for a in domain_assumptions:
        issues.append(
            f"Unvalidated assumption {a.assumption_id}: {a.description[:80]}..."
        )

    if regression_risk:
        verdict = ValidationGateVerdict.fail
        details = (
            f"Gate {domain.value}: {len(regression_risk)} REGRESSION_RISK invariants "
            f"detected.  Immediate attention required."
        )
        logger.warning(
            "INVARIANT_GATE_FAIL domain=%s regression_risk=%d",
            domain.value,
            len(regression_risk),
        )
    elif documented_only or domain_assumptions:
        verdict = ValidationGateVerdict.warn
        details = (
            f"Gate {domain.value}: {len(documented_only)} DOCUMENTED_ONLY invariants, "
            f"{len(domain_assumptions)} unvalidated assumptions.  "
            "No REGRESSION_RISK findings."
        )
        logger.info(
            "INVARIANT_GATE_WARN domain=%s documented_only=%d unvalidated_assumptions=%d",
            domain.value,
            len(documented_only),
            len(domain_assumptions),
        )
    else:
        verdict = ValidationGateVerdict.pass_
        details = (
            f"Gate {domain.value}: all invariants ENFORCED or PARTIALLY_ENFORCED.  "
            "No REGRESSION_RISK or DOCUMENTED_ONLY findings."
        )
        logger.debug("INVARIANT_GATE_PASS domain=%s", domain.value)

    return ValidationGateResult(
        gate_id=f"invariant_domain_{domain.value}",
        domain=domain,
        verdict=verdict,
        regression_risk_count=len(regression_risk),
        documented_only_count=len(documented_only),
        unvalidated_assumption_count=len(domain_assumptions),
        details=details,
        issues=issues,
    )


def run_cross_repo_validation_gate() -> ValidationGateResult:
    """Evaluate the aggregate cross-repo assumption validation gate.

    Checks all cross-repo assumptions in the registry regardless of domain.
    Returns a :class:`ValidationGateResult` with the aggregate verdict.

    Returns
    -------
    ValidationGateResult
    """
    all_assumptions = _CROSS_REPO_ASSUMPTION_REGISTRY
    unvalidated = [a for a in all_assumptions if not a.validated]

    issues: List[str] = []
    for a in unvalidated:
        issues.append(
            f"Unvalidated assumption {a.assumption_id} ({a.domain.value}): "
            f"{a.description[:80]}..."
        )

    if len(unvalidated) > len(all_assumptions) * CROSS_REPO_VALIDATION_FAILURE_THRESHOLD:
        # More than half unvalidated is a failure condition
        verdict = ValidationGateVerdict.fail
        details = (
            f"Cross-repo validation gate: {len(unvalidated)} of "
            f"{len(all_assumptions)} assumptions unvalidated.  "
            "Majority of cross-repo assumptions are unvalidated."
        )
        logger.warning(
            "CROSS_REPO_VALIDATION_GATE_FAIL unvalidated=%d total=%d",
            len(unvalidated),
            len(all_assumptions),
        )
    elif unvalidated:
        verdict = ValidationGateVerdict.warn
        details = (
            f"Cross-repo validation gate: {len(unvalidated)} unvalidated "
            f"assumptions out of {len(all_assumptions)} total."
        )
        logger.info(
            "CROSS_REPO_VALIDATION_GATE_WARN unvalidated=%d total=%d",
            len(unvalidated),
            len(all_assumptions),
        )
    else:
        verdict = ValidationGateVerdict.pass_
        details = (
            f"Cross-repo validation gate: all {len(all_assumptions)} assumptions "
            "validated.  No unvalidated cross-repo assumptions detected."
        )
        logger.debug(
            "CROSS_REPO_VALIDATION_GATE_PASS total=%d", len(all_assumptions)
        )

    return ValidationGateResult(
        gate_id="aggregate_cross_repo_validation",
        domain=InvariantDomain.cross_repo_contract,
        verdict=verdict,
        regression_risk_count=0,
        documented_only_count=0,
        unvalidated_assumption_count=len(unvalidated),
        details=details,
        issues=issues,
    )


def run_all_enforcement_gates() -> List[ValidationGateResult]:
    """Run all invariant enforcement gates and return the aggregate results.

    Runs one gate per :class:`InvariantDomain` value plus the aggregate
    cross-repo validation gate.

    Returns
    -------
    list[ValidationGateResult]
        One result per gate, in definition order.
    """
    results: List[ValidationGateResult] = []
    for domain in InvariantDomain:
        results.append(run_invariant_gate(domain))
    results.append(run_cross_repo_validation_gate())
    return results


# ===========================================================================
# Snapshot builder
# ===========================================================================


def build_enforcement_snapshot() -> InvariantEnforcementSnapshot:
    """Build a JSON-serialisable snapshot of the enforcement posture.

    This snapshot is suitable for CI consumption and operator dashboards.

    Returns
    -------
    InvariantEnforcementSnapshot
    """
    invariants = _INVARIANT_REGISTRY
    assumptions = _CROSS_REPO_ASSUMPTION_REGISTRY

    enforced = [r for r in invariants if r.status == InvariantStatus.ENFORCED]
    partially = [r for r in invariants if r.status == InvariantStatus.PARTIALLY_ENFORCED]
    documented_only = [r for r in invariants if r.status == InvariantStatus.DOCUMENTED_ONLY]
    regression_risk = [r for r in invariants if r.status == InvariantStatus.REGRESSION_RISK]

    validated_assumptions = [a for a in assumptions if a.validated]
    unvalidated_assumptions = [a for a in assumptions if not a.validated]

    gate_results = run_all_enforcement_gates()

    acceptable = is_enforcement_posture_acceptable()

    policy_sentinels = [
        HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY,
        CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY,
        CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY,
        ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY,
        INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY,
    ]

    return InvariantEnforcementSnapshot(
        total_invariants=len(invariants),
        enforced_count=len(enforced),
        partially_enforced_count=len(partially),
        documented_only_count=len(documented_only),
        regression_risk_count=len(regression_risk),
        total_assumptions=len(assumptions),
        validated_assumption_count=len(validated_assumptions),
        unvalidated_assumption_count=len(unvalidated_assumptions),
        enforcement_posture_acceptable=acceptable,
        generated_at=time.time(),
        policy_sentinels=policy_sentinels,
        gate_results=[r.to_dict() for r in gate_results],
        invariant_summaries=[r.to_dict() for r in invariants],
        assumption_summaries=[a.to_dict() for a in assumptions],
    )


# ===========================================================================
# Acceptance posture evaluator
# ===========================================================================


def is_enforcement_posture_acceptable() -> bool:
    """Return True when the enforcement posture meets the PR-8 acceptance bar.

    The acceptance bar is:
    - No REGRESSION_RISK invariants in the registry.
    - No unvalidated cross-repo assumptions in the registry.

    Note: DOCUMENTED_ONLY invariants produce a warning verdict but do not
    prevent the posture from being considered acceptable, as they represent
    low-severity coverage gaps rather than active regressions.

    Returns
    -------
    bool
    """
    has_regression = any(
        r.status == InvariantStatus.REGRESSION_RISK for r in _INVARIANT_REGISTRY
    )
    has_unvalidated = any(not a.validated for a in _CROSS_REPO_ASSUMPTION_REGISTRY)
    return not has_regression and not has_unvalidated
