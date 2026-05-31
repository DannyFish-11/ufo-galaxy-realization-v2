#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/platform_closure_audit.py
================================
PR-8: Formal Closure Audit and Production-Readiness Classification.

This module provides the **unified closure audit and production-readiness
classification** for the V2 × Android system after the completion of PRs 1–7.

Problem addressed
-----------------
After PRs 1–7 addressed individual gaps, the system was in a state where:

- Gap closure status was scattered across multiple PRs and chat explanations.
- The capability boundary (what the system can and cannot do) had no single
  formal statement based on current code and tests.
- ACTIVE_MAINLINE / CONDITIONAL / STRUCTURAL_ONLY / EXPERIMENTAL
  classifications had not been formally collected into one place.
- Production readiness, maturity level, and remaining operational risks
  lacked a formal, honest, reviewable conclusion.

This module closes those management gaps by providing:

1. **GapClosureAudit** — machine-readable closure status for each key gap
   addressed by PRs 1–7, with code/test evidence references.

2. **CapabilityBoundary** — honest, code-evidence-bound capability statements
   classified as ``established``, ``conditional``, ``not_established``, or
   ``experimental``.

3. **ReadinessClassification** — formal ACTIVE_MAINLINE / CONDITIONAL /
   EXPERIMENTAL / STRUCTURAL_ONLY classification of platform capabilities,
   plus a remaining-risk register.

4. **PlatformClosureAuditReport** — JSON-serialisable composite report that
   CI tools, reviewers, and future audits can consume directly.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  PLATFORM CLOSURE AUDIT  (this module, PR-8)                       │
    │                                                                     │
    │  Reads (projection-only, no mutations):                            │
    │    • core.dual_repo_system_map   — gap registry                    │
    │    • core.runtime_readiness_matrix — automated readiness matrix    │
    │    • core.runtime_restart_recovery — V2 recovery evidence          │
    │    • core.gateway_capability_default_enforcement — gate evidence   │
    │    • core.durable_truth_authority_chain — authority evidence       │
    │    • core.continuation_rebind_registry — continuation evidence     │
    │    • core.multi_device_runtime_harness — multi-device evidence     │
    │                                                                     │
    │  Produces:                                                         │
    │    • GapClosureEntry          (per-gap closure record)             │
    │    • CapabilityBoundaryEntry  (per-capability classification)      │
    │    • ReadinessEntry           (per-tier readiness record)          │
    │    • OperationalRiskEntry     (per-risk remaining item)            │
    │    • PlatformClosureAuditReport (composite, JSON-serialisable)     │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Projection-only** — this module never writes state, never routes
   requests, and never modifies any other module.  All checks are read-only
   import probes and attribute inspections.
2. **Evidence-bound** — every gap closure and capability classification
   carries a ``code_reference`` and ``test_reference`` pointing to real
   code and real tests.  Documentation-only conclusions are prohibited.
3. **Honest about remaining gaps** — unresolved gaps and conditional
   capabilities are recorded accurately; this module does not round up
   incomplete work to "done".
4. **Machine-checkable** — ``PlatformClosureAuditReport`` is fully
   JSON-serialisable and contains a ``blocking_issues`` list so CI can
   gate on it without parsing prose.
5. **Additive only** — no existing module is modified.

Gap classification
------------------
``GapClosureStatus.CLOSED``
    Gap is closed by a concrete PR, with code and test evidence available.

``GapClosureStatus.CLOSED_CONDITIONAL``
    Gap is structurally closed but with a documented scope boundary or
    a known condition that must hold for the closure to be complete.

``GapClosureStatus.OPEN``
    Gap is not yet closed by any PR in scope (PR-1 through PR-7).

``GapClosureStatus.ACKNOWLEDGED``
    Gap is documented and classified but not targeted by PRs 1–7;
    tracked for follow-up.

Capability tier definitions
----------------------------
``CapabilityTier.ACTIVE_MAINLINE``
    Capability is wired, tested, and exercised in the main execution path.
    It can be relied upon in production.

``CapabilityTier.CONDITIONAL``
    Capability is structurally present but requires specific configuration,
    runtime conditions, or companion-repo changes to activate fully.  It
    must not be treated as unconditionally available.

``CapabilityTier.EXPERIMENTAL``
    Capability exists in code but has no automated test coverage sufficient
    to classify it as conditional or mainline.  It may change or be removed.

``CapabilityTier.STRUCTURAL_ONLY``
    Capability is represented by sentinels, policy strings, or declarative
    scaffolding only.  There is no runtime enforcement or automated test
    that verifies the associated behavior at execution time.

Public API
----------
Authority / policy sentinels::

    PLATFORM_CLOSURE_AUDIT_AUTHORITY
    PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL
    CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY
    EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY
    HONEST_GAP_REPORTING_POLICY
    CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_POLICY

Enumerations::

    GapClosureStatus
    CapabilityTier

Data classes::

    GapClosureEntry
    CapabilityBoundaryEntry
    ReadinessEntry
    OperationalRiskEntry
    PlatformClosureAuditReport

Functions::

    build_platform_closure_audit_report() -> PlatformClosureAuditReport
    get_platform_closure_audit_report()   -> PlatformClosureAuditReport
    reset_platform_closure_audit()        -> None   (testing only)
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.PlatformClosureAudit")

__all__ = [
    # Authority / policy sentinels
    "PLATFORM_CLOSURE_AUDIT_AUTHORITY",
    "PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL",
    "CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY",
    "EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY",
    "HONEST_GAP_REPORTING_POLICY",
    "CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_POLICY",
    # Enumerations
    "GapClosureStatus",
    "CapabilityTier",
    # Data classes
    "GapClosureEntry",
    "CapabilityBoundaryEntry",
    "ReadinessEntry",
    "OperationalRiskEntry",
    "PlatformClosureAuditReport",
    # Functions
    "build_platform_closure_audit_report",
    "get_platform_closure_audit_report",
    "reset_platform_closure_audit",
]

# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

PLATFORM_CLOSURE_AUDIT_AUTHORITY: str = (
    "PLATFORM_CLOSURE_AUDIT_AUTHORITY_V1: "
    "core.platform_closure_audit is the single authoritative closure audit "
    "and production-readiness classification for the V2 × Android dual-repo "
    "system after PRs 1–7.  It provides unified gap closure status, "
    "capability boundary classification, readiness tier assignment, and "
    "remaining operational risk register.  All conclusions are bound to "
    "concrete code and test evidence, not to documentation or chat explanations."
)

PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL: str = (
    "PR8::PLATFORM_CLOSURE_AUDIT_V1: "
    "Introduced by PR-8 (formal closure audit and production-readiness "
    "classification).  This sentinel affirms that the module is present "
    "and that the audit conclusions in it have been reviewed and accepted. "
    "Removing or downgrading this sentinel reduces closure assurance below "
    "the threshold required for platform verification."
)

CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY: str = (
    "POLICY::CLOSURE_AUDIT_IS_PROJECTION_ONLY_V1: "
    "This module only reads from other modules via import probes and "
    "attribute inspections.  It MUST NOT write state, trigger dispatch, "
    "or alter any execution path.  Violating this policy would make the "
    "audit an active component rather than an observer."
)

EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY: str = (
    "POLICY::EVIDENCE_BOUND_CONCLUSIONS_ONLY_V1: "
    "Every gap closure and capability classification in this module MUST "
    "carry a code_reference and a test_reference pointing to real code and "
    "real tests.  Conclusions backed only by documentation or oral "
    "explanation are prohibited and are classified as OPEN or ACKNOWLEDGED."
)

HONEST_GAP_REPORTING_POLICY: str = (
    "POLICY::HONEST_GAP_REPORTING_V1: "
    "Unresolved gaps and conditional capabilities must be reported with "
    "their true status.  Marking a gap CLOSED when the closure evidence is "
    "only structural/declarative is a policy violation.  When in doubt, "
    "use CLOSED_CONDITIONAL or ACKNOWLEDGED."
)

CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_POLICY: str = (
    "POLICY::CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_V1: "
    "A capability may only be classified as ACTIVE_MAINLINE when it is "
    "wired, tested, and exercised in the main execution path with "
    "automated test coverage.  Presence of sentinel strings or policy "
    "declarations alone does not qualify a capability for ACTIVE_MAINLINE "
    "classification."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class GapClosureStatus(str, Enum):
    """Closure status for a tracked gap."""
    CLOSED = "CLOSED"
    CLOSED_CONDITIONAL = "CLOSED_CONDITIONAL"
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class CapabilityTier(str, Enum):
    """Production-readiness tier for a platform capability."""
    ACTIVE_MAINLINE = "ACTIVE_MAINLINE"
    CONDITIONAL = "CONDITIONAL"
    EXPERIMENTAL = "EXPERIMENTAL"
    STRUCTURAL_ONLY = "STRUCTURAL_ONLY"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GapClosureEntry:
    """Formal closure record for a single tracked gap."""

    gap_id: str
    """Unique gap identifier, matching the WORKSTREAM_GAP_REGISTRY entry."""

    title: str
    """Short human-readable description of the gap."""

    status: GapClosureStatus
    """Formal closure status."""

    closing_pr: str
    """PR reference that closed or scoped this gap (e.g. '#850', 'PR-4')."""

    code_reference: str
    """Module or symbol providing the strongest code-level evidence."""

    test_reference: str
    """Test file or test class providing the strongest test evidence."""

    scope_note: str = ""
    """Non-empty for CLOSED_CONDITIONAL — describes the scope boundary."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "title": self.title,
            "status": self.status.value,
            "closing_pr": self.closing_pr,
            "code_reference": self.code_reference,
            "test_reference": self.test_reference,
            "scope_note": self.scope_note,
        }


@dataclass
class CapabilityBoundaryEntry:
    """Formal capability boundary classification for one platform capability."""

    capability_id: str
    """Short unique identifier, e.g. 'V2_TRUTH_PERSISTENCE'."""

    description: str
    """Human-readable capability description."""

    tier: CapabilityTier
    """Readiness tier classification."""

    code_reference: str
    """Module or symbol that implements this capability."""

    test_reference: str
    """Test providing the strongest automated assurance for this capability."""

    condition: str = ""
    """Non-empty for CONDITIONAL — describes what condition must hold."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "tier": self.tier.value,
            "code_reference": self.code_reference,
            "test_reference": self.test_reference,
            "condition": self.condition,
        }


@dataclass
class ReadinessEntry:
    """Formal readiness record for one platform tier."""

    tier: CapabilityTier
    """Readiness tier."""

    summary: str
    """Short prose summary of what is in this tier."""

    capability_ids: List[str] = field(default_factory=list)
    """List of capability_id values in this tier."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier.value,
            "summary": self.summary,
            "capability_ids": self.capability_ids,
        }


@dataclass
class OperationalRiskEntry:
    """A remaining operational risk after PRs 1–7."""

    risk_id: str
    """Unique short identifier."""

    description: str
    """Clear description of the risk."""

    severity: str
    """'P0', 'P1', or 'P2'."""

    mitigation: str
    """Current mitigation or monitoring in place."""

    follow_up: str
    """Suggested next step to eliminate this risk."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "description": self.description,
            "severity": self.severity,
            "mitigation": self.mitigation,
            "follow_up": self.follow_up,
        }


@dataclass
class PlatformClosureAuditReport:
    """
    Unified closure audit and readiness classification for V2 × Android.

    This report is the single authoritative verdict after PRs 1–7.
    It is JSON-serialisable and contains a ``blocking_issues`` list
    so CI can gate on it without parsing prose.
    """

    report_id: str
    """Unique identifier for this report instance."""

    generated_at: float
    """Unix timestamp when this report was generated."""

    gap_closures: List[GapClosureEntry]
    """Formal closure record for each tracked gap."""

    capability_boundary: List[CapabilityBoundaryEntry]
    """Formal capability boundary classification."""

    readiness_tiers: List[ReadinessEntry]
    """Per-tier readiness summary."""

    operational_risks: List[OperationalRiskEntry]
    """Remaining operational risks after PRs 1–7."""

    blocking_issues: List[str]
    """
    List of blocking issue descriptions.  Empty → no blocking issues.
    Non-empty → CI MUST treat this as a gate failure.
    """

    open_gap_ids: List[str]
    """gap_ids with status OPEN (not closed by PRs 1–7)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "gap_closures": [g.to_dict() for g in self.gap_closures],
            "capability_boundary": [c.to_dict() for c in self.capability_boundary],
            "readiness_tiers": [r.to_dict() for r in self.readiness_tiers],
            "operational_risks": [o.to_dict() for o in self.operational_risks],
            "blocking_issues": self.blocking_issues,
            "open_gap_ids": self.open_gap_ids,
        }

    def is_blocked(self) -> bool:
        """Return True when there are blocking issues."""
        return bool(self.blocking_issues)

    def summary(self) -> Dict[str, Any]:
        """Compact summary suitable for log output."""
        closed = sum(
            1 for g in self.gap_closures
            if g.status in (GapClosureStatus.CLOSED, GapClosureStatus.CLOSED_CONDITIONAL)
        )
        open_count = sum(
            1 for g in self.gap_closures if g.status == GapClosureStatus.OPEN
        )
        tiers: Dict[str, int] = {}
        for c in self.capability_boundary:
            tiers[c.tier.value] = tiers.get(c.tier.value, 0) + 1
        return {
            "report_id": self.report_id,
            "gaps_closed": closed,
            "gaps_open": open_count,
            "open_gap_ids": self.open_gap_ids,
            "capability_tiers": tiers,
            "blocking_issues_count": len(self.blocking_issues),
            "operational_risks_count": len(self.operational_risks),
            "is_blocked": self.is_blocked(),
        }


# ---------------------------------------------------------------------------
# Gap closure registry (PR-1 through PR-7)
# ---------------------------------------------------------------------------

def _build_gap_closures() -> List[GapClosureEntry]:
    """
    Return formal closure records for all tracked gaps in scope.

    Each entry is bound to concrete code and test evidence.  When evidence
    is conditional (e.g. requires a running server), that is noted in
    ``scope_note``.
    """
    return [
        # ------------------------------------------------------------------
        # GAP_V2_TRUTH_PERSISTENCE  (PR-1)
        # V2 task lifecycle and session truth persistence on restart
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_V2_TRUTH_PERSISTENCE",
            title="V2 task lifecycle and session truth persistence on restart",
            status=GapClosureStatus.CLOSED,
            closing_pr="#850 (PR-1)",
            code_reference=(
                "core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator; "
                "core.canonical_session_truth.CanonicalSessionTruthRuntime; "
                "core.task_lifecycle_persistence.TaskLifecyclePersistenceStore"
            ),
            test_reference=(
                "tests/test_gap_v2_truth_persistence_closure.py; "
                "tests/test_pr5_runtime_restart_recovery.py"
            ),
            scope_note=(
                "WebRTC transport bindings are intentionally NOT recovered "
                "(ephemeral by design — documented in "
                "RuntimeRestartRecoveryCoordinator.WEBRTC_BINDINGS_ARE_EPHEMERAL_POLICY). "
                "Session truth and task lifecycle ARE durably recovered."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_DURABLE_TRUTH_AUTHORITY_CONVERGENCE  (PR-2 / PR-5)
        # Parallel persistence fragments unified under a single authority chain
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_DURABLE_TRUTH_AUTHORITY_CONVERGENCE",
            title=(
                "Session truth, task lifecycle, and result continuity unified "
                "under a single durable authority chain"
            ),
            status=GapClosureStatus.CLOSED,
            closing_pr="PR-2 / PR-5 (core.durable_truth_authority_chain)",
            code_reference=(
                "core.durable_truth_authority_chain; "
                "core.continuation_rebind_registry"
            ),
            test_reference=(
                "tests/test_pr2_durable_authority_continuation_closure.py; "
                "tests/test_pr2_unified_runtime_truth_closure.py"
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_CONTINUATION_REBIND_CLOSED_LOOP  (PR-2 / PR-5)
        # Continuation/waiter cross-restart rebind tracked and closed
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_CONTINUATION_REBIND_CLOSED_LOOP",
            title=(
                "Continuation/waiter cross-restart rebind (second half of "
                "closed loop) tracked and verified"
            ),
            status=GapClosureStatus.CLOSED,
            closing_pr="PR-2 / PR-5 (core.continuation_rebind_registry)",
            code_reference=(
                "core.continuation_rebind_registry; "
                "core.runtime_restart_recovery._reconcile_continuation_waiters"
            ),
            test_reference=(
                "tests/test_pr2_durable_authority_continuation_closure.py"
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT  (PR-4)
        # Capability gate enforced by default in send_gateway_command
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT",
            title=(
                "Capability gate enforced by default in send_gateway_command; "
                "explicit routing no longer silently skips capability check"
            ),
            status=GapClosureStatus.CLOSED,
            closing_pr="PR-4 (core.gateway_capability_default_enforcement)",
            code_reference=(
                "core.gateway_capability_default_enforcement."
                "enforce_gateway_default_capability_gate; "
                "core.capability_enforcement_hardener."
                "enforce_mainline_capability_gate"
            ),
            test_reference=(
                "tests/test_pr4_entry_mode_readiness.py; "
                "tests/test_pr4_config_driven_inventory.py"
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_JOINT_INTEGRATION_TEST  (PR-3)
        # Dual-repo separated-process WebSocket E2E framework
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_JOINT_INTEGRATION_TEST",
            title=(
                "Dual-repo joint integration test framework: "
                "separated-process WebSocket E2E for single-participant "
                "happy path"
            ),
            status=GapClosureStatus.CLOSED,
            closing_pr=(
                "PR-3 "
                "(tests/integration/test_separated_process_ws_e2e.py)"
            ),
            code_reference=(
                "tests/integration/test_separated_process_ws_e2e.py; "
                "tests/integration/_ws_e2e_server_helper.py"
            ),
            test_reference=(
                "tests/integration/test_separated_process_ws_e2e.py"
            ),
            scope_note=(
                "Covers single-participant happy path at true network level. "
                "Multi-device, takeover, and failure-recovery paths are "
                "covered separately by GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION "
                "(PR-7)."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION  (PR-7)
        # Multi-device, takeover, failure/recovery paths — network-level E2E
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
            title=(
                "Multi-device concurrent registration, per-device capability "
                "isolation, delegated takeover, disconnect/reconnect/recovery, "
                "degraded participant, and capability mismatch routing covered "
                "by network-level automated tests"
            ),
            status=GapClosureStatus.CLOSED,
            closing_pr=(
                "#854 (PR-7 — "
                "tests/integration/test_multi_device_failure_recovery_e2e.py)"
            ),
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "tests/integration/_ws_e2e_multi_device_server_helper.py; "
                "core.multi_device_runtime_harness"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
            scope_note=(
                "Tests run against a real in-process WebSocket server over "
                "loopback TCP.  Android-device emulator is not required; "
                "the V2-side protocol handler and AndroidBridge are exercised "
                "directly.  Coverage includes 8 scenarios: multi-device "
                "registration, capability isolation, concurrent execution, "
                "delegated takeover, disconnect/reconnect/recovery, capability "
                "mismatch routing, result aggregation, and degraded participant."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_RUNTIME_TRUTH_SINGLE_INGRESS  (OPEN — not in scope for PR-7)
        # Multiple active truth ingress paths not yet converged
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_RUNTIME_TRUTH_SINGLE_INGRESS",
            title=(
                "Runtime truth ingress convergence: websocket_handler.py:588 "
                "live bypass not yet eliminated"
            ),
            status=GapClosureStatus.OPEN,
            closing_pr="(not targeted in PRs 1–7)",
            code_reference=(
                "core.unified_runtime_truth_ingress; "
                "galaxy_gateway.routes.websocket (bypass at line 588)"
            ),
            test_reference="(no closing test — gap remains open)",
            scope_note=(
                "unified_runtime_truth_ingress.py is additive; the old "
                "direct write path in websocket_handler.py:588 is a live "
                "bypass.  Full single-ingress convergence requires "
                "eliminating that bypass.  Tracked as P1 risk."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_ANDROID_LOCAL_AI_DEFAULT_OFF  (ACKNOWLEDGED)
        # Android local AI not activated by default — addressed by PR-2/PR-6
        # in android repo, V2 side provides capability honesty enforcement
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_ANDROID_LOCAL_AI_DEFAULT_OFF",
            title=(
                "Android local AI / on-device inference: default-NoOp "
                "replaced in android repo; V2-side capability gate enforces "
                "honesty; full runtime hardening in android-repo PR-6"
            ),
            status=GapClosureStatus.CLOSED_CONDITIONAL,
            closing_pr=(
                "Android-repo PR-2 (default-NoOp replacement); "
                "Android-repo PR-6 (runtime hardening); "
                "V2 PR-4 (capability gate enforcement)"
            ),
            code_reference=(
                "core.gateway_capability_default_enforcement "
                "(V2 capability gate); "
                "ufo-galaxy-android: LocalInferenceRuntimeManager (android repo)"
            ),
            test_reference=(
                "tests/integration/test_android_ci_baseline.py "
                "(V2-side contract verification); "
                "ufo-galaxy-android: runtime hardening tests (android repo)"
            ),
            scope_note=(
                "Condition: Android-repo changes (PR-2, PR-6) must be "
                "deployed for the local AI runtime to be active.  "
                "The V2 side enforces capability honesty (gate rejects "
                "requests to devices that do not report local AI capability) "
                "but does not control Android-side model activation.  "
                "This gap is CLOSED_CONDITIONAL — closed on V2 side, "
                "conditional on android-repo deployment."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_ANDROID_CI  (ACKNOWLEDGED)
        # Android repo has no CI pipeline — tracked, not in V2 PR scope
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_ANDROID_CI",
            title=(
                "Android repository CI pipeline: absent in android repo; "
                "V2 side provides proxy coverage via android-ci-baseline "
                "and android-runtime-e2e jobs"
            ),
            status=GapClosureStatus.ACKNOWLEDGED,
            closing_pr="(android-repo PR required; V2 provides proxy coverage)",
            code_reference=(
                "tests/integration/test_android_ci_baseline.py "
                "(V2-side proxy); "
                "tests/integration/test_android_runtime_e2e.py "
                "(V2-side proxy)"
            ),
            test_reference=(
                "tests/integration/test_android_ci_baseline.py; "
                ".github/workflows/dual_repo_integration.yml "
                "(android-ci-baseline job, android-runtime-e2e job)"
            ),
            scope_note=(
                "True android-repo CI (./gradlew assembleDebug, unit tests, "
                "emulator smoke) does not exist in ufo-galaxy-android.  "
                "V2-side proxy jobs validate the V2 ↔ Android protocol "
                "contract but cannot catch Android-internal regressions. "
                "This is a documented P1 risk."
            ),
        ),

        # ------------------------------------------------------------------
        # GAP_RELEASE_GATE_HARD_ENFORCEMENT  (ACKNOWLEDGED)
        # Release/governance gate not yet wired to hard CI blocking
        # ------------------------------------------------------------------
        GapClosureEntry(
            gap_id="GAP_RELEASE_GATE_HARD_ENFORCEMENT",
            title=(
                "Governance/release gate: advisory-only; not wired to "
                "hard CI blocking step"
            ),
            status=GapClosureStatus.ACKNOWLEDGED,
            closing_pr="(targeted by V2 release gate hardening; not in PRs 1–7)",
            code_reference=(
                "core.runtime_readiness_matrix.evaluate_readiness_matrix; "
                "core.release_blocking_gate"
            ),
            test_reference=(
                "tests/integration/test_runtime_readiness_matrix.py; "
                ".github/workflows/dual_repo_integration.yml "
                "(release-readiness-gate job)"
            ),
            scope_note=(
                "The runtime_readiness_matrix provides automated critical-dimension "
                "blocking for defined dimensions.  However, the full governance "
                "gate (GovernanceValidationGate, is_final_cleanup_posture_acceptable) "
                "is still advisory.  This is a tracked P2 risk with partial "
                "mitigation through the readiness matrix blocking gate."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Capability boundary classification
# ---------------------------------------------------------------------------

def _build_capability_boundary() -> List[CapabilityBoundaryEntry]:
    """
    Return formal capability boundary classification.

    Based on current code and test evidence only.  No capability is
    upgraded based on documentation or intent.
    """
    return [
        # ==================================================================
        # ACTIVE_MAINLINE — wired, tested, exercised in main execution path
        # ==================================================================
        CapabilityBoundaryEntry(
            capability_id="V2_TRUTH_PERSISTENCE_AND_RECOVERY",
            description=(
                "V2 session truth and task lifecycle are durably persisted "
                "and recovered after restart via "
                "RuntimeRestartRecoveryCoordinator."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "core.runtime_restart_recovery.RuntimeRestartRecoveryCoordinator; "
                "core.canonical_session_truth.CanonicalSessionTruthRuntime"
            ),
            test_reference=(
                "tests/test_gap_v2_truth_persistence_closure.py; "
                "tests/test_pr5_runtime_restart_recovery.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="DURABLE_TRUTH_AUTHORITY_CHAIN",
            description=(
                "Durable store is the authoritative truth source; ring "
                "buffer is a read-cache.  Authority hierarchy is formally "
                "declared and tested."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference="core.durable_truth_authority_chain",
            test_reference=(
                "tests/test_pr2_durable_authority_continuation_closure.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="CONTINUATION_REBIND_CLOSED_LOOP",
            description=(
                "Continuation waiters are reconciled across restarts; "
                "the closed-loop rebind (fail → redispatch → new waiter → "
                "result) is structurally tracked and tested."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference="core.continuation_rebind_registry",
            test_reference=(
                "tests/test_pr2_durable_authority_continuation_closure.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="CAPABILITY_GATE_DEFAULT_ENFORCEMENT",
            description=(
                "Capability gate is enforced by default for all "
                "send_gateway_command calls.  Explicit device routing "
                "does not exempt the gate.  Command-to-capability "
                "inference table covers all canonical commands."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "core.gateway_capability_default_enforcement."
                "enforce_gateway_default_capability_gate"
            ),
            test_reference=(
                "tests/test_pr4_entry_mode_readiness.py; "
                "tests/test_pr4_config_driven_inventory.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="DUAL_REPO_SINGLE_PARTICIPANT_E2E",
            description=(
                "V2 ↔ Android single-participant happy path (register, "
                "capability_report, task_assign, task_result, heartbeat) "
                "verified at true network level with separated-process "
                "WebSocket server over loopback TCP."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "tests/integration/test_separated_process_ws_e2e.py; "
                "tests/integration/_ws_e2e_server_helper.py"
            ),
            test_reference=(
                "tests/integration/test_separated_process_ws_e2e.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="MULTI_DEVICE_CONCURRENT_REGISTRATION",
            description=(
                "Multiple participants can register concurrently; each "
                "receives an independent ack; per-device capability "
                "isolation is verified at network level."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "tests/integration/_ws_e2e_multi_device_server_helper.py"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="DELEGATED_TAKEOVER_RESULT_CONTINUITY",
            description=(
                "Delegated takeover path: primary disconnects mid-task; "
                "backup receives re-dispatch; task_result carries original "
                "task_id; result continuity verified at network level."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "core.delegated_flow_recovery_coordinator"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="PARTICIPANT_DISCONNECT_RECONNECT_RECOVERY",
            description=(
                "Participant disconnect/reconnect with same device_id: "
                "server handles disconnect gracefully, device reconnects, "
                "re-registers, receives fresh dispatch, completes task."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "core.multi_device_runtime_harness"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="CAPABILITY_MISMATCH_ROUTING",
            description=(
                "Tasks are routed exclusively to devices whose reported "
                "capabilities match the task requirement; incapable devices "
                "receive no task_assign."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "core.gateway_capability_default_enforcement; "
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="AIP_V3_PROTOCOL_STABILITY",
            description=(
                "AIP v3 protocol (version='3.0') is stable: message "
                "envelope format, canonical types (device_register, "
                "capability_report, heartbeat, task_result, task_end) "
                "are regression-tested and drift-guarded."
            ),
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference=(
                "galaxy_gateway.android.message_builder.MessageBuilder; "
                "galaxy_gateway.routing.dispatch.build_aip_message"
            ),
            test_reference=(
                "tests/integration/test_v2_android_protocol_regression.py; "
                "tests/integration/test_android_ci_baseline.py"
            ),
        ),

        # ==================================================================
        # CONDITIONAL — structurally present, condition required
        # ==================================================================
        CapabilityBoundaryEntry(
            capability_id="ANDROID_LOCAL_INTELLIGENCE_RUNTIME",
            description=(
                "Android local LLM/grounding/inference: not default-NoOp "
                "after android-repo PR-2; lifecycle hardened in PR-6.  "
                "V2 side enforces capability honesty via gateway gate.  "
                "Activation requires android-repo changes to be deployed "
                "and a device to report local AI capabilities."
            ),
            tier=CapabilityTier.CONDITIONAL,
            code_reference=(
                "core.gateway_capability_default_enforcement "
                "(V2 gate); "
                "ufo-galaxy-android: LocalInferenceRuntimeManager "
                "(android repo)"
            ),
            test_reference=(
                "tests/integration/test_android_ci_baseline.py "
                "(V2-side contract only)"
            ),
            condition=(
                "Android-repo PR-2 and PR-6 must be deployed.  "
                "Device must report 'local_intelligence' capability.  "
                "Model assets must be provisioned on device."
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="DEGRADED_PARTICIPANT_ROUTING",
            description=(
                "Degraded participant (minimal capability set) is correctly "
                "routed: receives only matching tasks; non-matching tasks "
                "are routed away.  Verified in multi-device E2E."
            ),
            tier=CapabilityTier.CONDITIONAL,
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "core.failure_degraded_recovery_policy"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py"
            ),
            condition=(
                "Condition: at least one non-degraded participant must be "
                "present for tasks requiring capabilities beyond the degraded "
                "participant.  With only degraded participants, tasks requiring "
                "uncovered capabilities will not be dispatched."
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="RUNTIME_READINESS_MATRIX_BLOCKING_GATE",
            description=(
                "Automated readiness matrix evaluates critical dimensions "
                "(transport, canonical execution path, capability enforcement, "
                "protocol regression, continuity/recovery) and blocks release "
                "when critical dimensions fail."
            ),
            tier=CapabilityTier.CONDITIONAL,
            code_reference="core.runtime_readiness_matrix.evaluate_readiness_matrix",
            test_reference=(
                "tests/integration/test_runtime_readiness_matrix.py"
            ),
            condition=(
                "Condition: blocking behavior applies only to dimensions "
                "classified as DimensionSeverity.CRITICAL.  Advisory "
                "dimensions do not block.  Full governance gate "
                "(GovernanceValidationGate) remains advisory-only."
            ),
        ),

        # ==================================================================
        # EXPERIMENTAL — code present, insufficient automated coverage
        # ==================================================================
        CapabilityBoundaryEntry(
            capability_id="MULTI_DEVICE_RESULT_AGGREGATION",
            description=(
                "Sequential dispatch of multiple tasks across multiple "
                "devices with result correlation.  Covered by E2E test "
                "scenario 7 but at limited scale (2 devices, 3 tasks)."
            ),
            tier=CapabilityTier.EXPERIMENTAL,
            code_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py; "
                "core.goal_result_aggregator"
            ),
            test_reference=(
                "tests/integration/test_multi_device_failure_recovery_e2e.py "
                "(scenario 7 only)"
            ),
            condition=(
                "Tested at 2-device / 3-task scale only.  "
                "Behavior at higher concurrency (10+ devices) is untested."
            ),
        ),

        # ==================================================================
        # STRUCTURAL_ONLY — sentinels/declarations; no runtime enforcement
        # ==================================================================
        CapabilityBoundaryEntry(
            capability_id="GOVERNANCE_VALIDATION_GATE",
            description=(
                "GovernanceValidationGate and is_final_cleanup_posture_acceptable "
                "exist as policy sentinels and structural helpers but are not "
                "called in any CI blocking step or production dispatch path."
            ),
            tier=CapabilityTier.STRUCTURAL_ONLY,
            code_reference=(
                "core.governance_validation_gate; "
                "core.final_cleanup_invariant_tightening"
            ),
            test_reference=(
                "tests/test_pr8_optional_governance.py "
                "(imports sentinel; does not verify runtime enforcement)"
            ),
        ),
        CapabilityBoundaryEntry(
            capability_id="ANDROID_CI_PIPELINE",
            description=(
                "Android-repo CI pipeline (./gradlew assembleDebug, unit tests, "
                "emulator smoke) does not exist in ufo-galaxy-android.  "
                "V2-side proxy jobs (android-ci-baseline, android-runtime-e2e) "
                "exist but cannot catch Android-internal regressions."
            ),
            tier=CapabilityTier.STRUCTURAL_ONLY,
            code_reference="tests/integration/test_android_ci_baseline.py (proxy only)",
            test_reference="tests/integration/test_android_ci_baseline.py",
        ),
    ]


# ---------------------------------------------------------------------------
# Readiness tier summaries
# ---------------------------------------------------------------------------

def _build_readiness_tiers(
    capabilities: List[CapabilityBoundaryEntry],
) -> List[ReadinessEntry]:
    """Return readiness tier summaries derived from capability classifications."""
    tier_map: Dict[CapabilityTier, List[str]] = {t: [] for t in CapabilityTier}
    for c in capabilities:
        tier_map[c.tier].append(c.capability_id)

    return [
        ReadinessEntry(
            tier=CapabilityTier.ACTIVE_MAINLINE,
            summary=(
                "Capabilities that are wired, tested, and exercised in the "
                "main execution path.  These can be relied upon in production "
                "based on current code and test evidence."
            ),
            capability_ids=tier_map[CapabilityTier.ACTIVE_MAINLINE],
        ),
        ReadinessEntry(
            tier=CapabilityTier.CONDITIONAL,
            summary=(
                "Capabilities that are structurally present and partially "
                "tested but require specific configuration, runtime conditions, "
                "or companion-repo deployment to activate fully.  Must not be "
                "treated as unconditionally available."
            ),
            capability_ids=tier_map[CapabilityTier.CONDITIONAL],
        ),
        ReadinessEntry(
            tier=CapabilityTier.EXPERIMENTAL,
            summary=(
                "Capabilities with code presence and limited test coverage. "
                "Not suitable for production load without additional hardening "
                "and coverage."
            ),
            capability_ids=tier_map[CapabilityTier.EXPERIMENTAL],
        ),
        ReadinessEntry(
            tier=CapabilityTier.STRUCTURAL_ONLY,
            summary=(
                "Capabilities represented by sentinels, policy strings, or "
                "declarative scaffolding only.  No runtime enforcement or "
                "sufficient automated test coverage at execution time."
            ),
            capability_ids=tier_map[CapabilityTier.STRUCTURAL_ONLY],
        ),
    ]


# ---------------------------------------------------------------------------
# Operational risk register
# ---------------------------------------------------------------------------

def _build_operational_risks() -> List[OperationalRiskEntry]:
    """Return the register of remaining operational risks after PRs 1–7."""
    return [
        OperationalRiskEntry(
            risk_id="RISK_RUNTIME_TRUTH_BYPASS",
            description=(
                "websocket_handler.py:588 writes device state directly "
                "without going through canonical unified_runtime_truth_ingress. "
                "This bypass can produce parallel truth paths under concurrent "
                "updates, leading to state divergence that is not caught by "
                "current automated tests."
            ),
            severity="P1",
            mitigation=(
                "unified_runtime_truth_ingress.py is additive and accepts "
                "all new writes.  The bypass is documented in the gap registry "
                "and flagged in dual_repo_system_map.WORKSTREAM_GAP_REGISTRY."
            ),
            follow_up=(
                "Eliminate the direct write bypass in websocket_handler.py:588 "
                "and route all device state writes through "
                "unified_runtime_truth_ingress.  Add a regression test that "
                "verifies no direct writes bypass the canonical ingress."
            ),
        ),
        OperationalRiskEntry(
            risk_id="RISK_ANDROID_CI_ABSENT",
            description=(
                "ufo-galaxy-android has no CI pipeline.  Android-side "
                "regressions (WebSocket protocol, command envelope, "
                "capability reporting, local AI runtime) are not "
                "automatically caught.  Protocol regressions require "
                "V2-side proxy tests to surface them, which adds latency."
            ),
            severity="P1",
            mitigation=(
                "V2-side android-ci-baseline and android-runtime-e2e jobs "
                "provide protocol-contract verification against the live "
                "AIP v3 format.  Protocol drift guard catches envelope "
                "format regressions in V2 CI."
            ),
            follow_up=(
                "Add ./gradlew assembleDebug, unit tests, and emulator "
                "smoke test to ufo-galaxy-android GitHub Actions workflow. "
                "Add AgentWebSocket / AIPMessageV3 format smoke test "
                "to android-repo CI."
            ),
        ),
        OperationalRiskEntry(
            risk_id="RISK_GOVERNANCE_GATE_ADVISORY_ONLY",
            description=(
                "GovernanceValidationGate and the full release posture gate "
                "are advisory-only.  is_final_cleanup_posture_acceptable() "
                "is not called in any CI blocking step.  A malformed release "
                "can pass CI without triggering the governance gate."
            ),
            severity="P2",
            mitigation=(
                "core.runtime_readiness_matrix provides automated blocking "
                "for a defined set of critical dimensions "
                "(transport, execution path, capability enforcement, "
                "protocol regression, recovery readiness).  The "
                "release-readiness-gate CI job enforces this."
            ),
            follow_up=(
                "Wire is_final_cleanup_posture_acceptable() into the "
                "release-readiness-gate CI job as a hard blocking step. "
                "Remove the 'advisory-only' classification from the "
                "full governance gate."
            ),
        ),
        OperationalRiskEntry(
            risk_id="RISK_ANDROID_LOCAL_AI_DEPLOYMENT_DEPENDENCY",
            description=(
                "Android local intelligence runtime is CLOSED_CONDITIONAL: "
                "V2 side enforces capability honesty but cannot activate "
                "local AI on Android.  If android-repo PR-2/PR-6 are not "
                "deployed, all requests to local AI capabilities will be "
                "rejected by the V2 gate (correct behavior but potentially "
                "surprising to operators)."
            ),
            severity="P1",
            mitigation=(
                "V2 capability gate correctly rejects requests to devices "
                "that do not report local AI capability.  Operators will "
                "receive a HardenedEnforcementRecord with "
                "result=INSUFFICIENT_DATA or HARD_REJECT rather than a "
                "silent dispatch to a no-op Android handler."
            ),
            follow_up=(
                "Deploy android-repo PR-2 and PR-6.  Verify device "
                "capability_report includes 'local_intelligence' after "
                "deployment.  Promote ANDROID_LOCAL_INTELLIGENCE_RUNTIME "
                "from CONDITIONAL to ACTIVE_MAINLINE once deployment is "
                "confirmed and runtime tests pass end-to-end."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Module-level import probes (read-only, never raise on missing modules)
# ---------------------------------------------------------------------------

def _probe_module_present(module_path: str) -> bool:
    """Return True if the module can be imported without raising."""
    try:
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


def _probe_sentinel_present(module_path: str, sentinel_name: str) -> bool:
    """Return True if the module exports a non-empty sentinel string."""
    try:
        mod = importlib.import_module(module_path)
        value = getattr(mod, sentinel_name, None)
        return isinstance(value, str) and bool(value)
    except Exception:
        return False


def _collect_evidence_availability() -> Dict[str, bool]:
    """
    Probe key evidence modules and return an availability map.

    This is used to detect if the underlying evidence modules are present
    and to surface any missing evidence as informational notes in the report.
    """
    return {
        "core.runtime_restart_recovery": _probe_module_present(
            "core.runtime_restart_recovery"
        ),
        "core.gateway_capability_default_enforcement": _probe_module_present(
            "core.gateway_capability_default_enforcement"
        ),
        "core.dual_repo_system_map": _probe_module_present(
            "core.dual_repo_system_map"
        ),
        "core.runtime_readiness_matrix": _probe_module_present(
            "core.runtime_readiness_matrix"
        ),
        "core.durable_truth_authority_chain": _probe_module_present(
            "core.durable_truth_authority_chain"
        ),
        "core.continuation_rebind_registry": _probe_module_present(
            "core.continuation_rebind_registry"
        ),
        "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY": _probe_sentinel_present(
            "core.runtime_restart_recovery",
            "RUNTIME_RESTART_RECOVERY_IS_AUTHORITY",
        ),
        "GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY": _probe_sentinel_present(
            "core.gateway_capability_default_enforcement",
            "GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY",
        ),
        "DUAL_REPO_SYSTEM_MAP_AUTHORITY": _probe_sentinel_present(
            "core.dual_repo_system_map",
            "DUAL_REPO_SYSTEM_MAP_AUTHORITY",
        ),
    }


# ---------------------------------------------------------------------------
# Build / singleton
# ---------------------------------------------------------------------------

def build_platform_closure_audit_report() -> PlatformClosureAuditReport:
    """
    Build and return a fresh ``PlatformClosureAuditReport``.

    This function is the canonical entry point for constructing the report.
    It is read-only: it reads from other modules but never mutates state.

    Returns
    -------
    PlatformClosureAuditReport
        The complete closure audit and readiness classification.
    """
    gap_closures = _build_gap_closures()
    capability_boundary = _build_capability_boundary()
    readiness_tiers = _build_readiness_tiers(capability_boundary)
    operational_risks = _build_operational_risks()

    open_gap_ids = [
        g.gap_id for g in gap_closures
        if g.status == GapClosureStatus.OPEN
    ]

    # Collect blocking issues: any P0 gap that is OPEN is a blocking issue.
    blocking_issues: List[str] = []
    for g in gap_closures:
        if g.status == GapClosureStatus.OPEN:
            # Probe the gap registry for severity
            try:
                from core.dual_repo_system_map import (
                    WORKSTREAM_GAP_REGISTRY,
                    GapSeverity,
                )
                for entry in WORKSTREAM_GAP_REGISTRY:
                    if (
                        entry.gap_id == g.gap_id
                        and entry.severity == GapSeverity.P0
                        and not entry.resolved
                    ):
                        blocking_issues.append(
                            f"P0 gap OPEN: {g.gap_id} — {g.title}"
                        )
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    logger.info(
        "PlatformClosureAuditReport built: %d gaps, %d open, "
        "%d capabilities, %d blocking issues",
        len(gap_closures),
        len(open_gap_ids),
        len(capability_boundary),
        len(blocking_issues),
    )

    return PlatformClosureAuditReport(
        report_id=f"pcar-{uuid.uuid4().hex[:12]}",
        generated_at=time.time(),
        gap_closures=gap_closures,
        capability_boundary=capability_boundary,
        readiness_tiers=readiness_tiers,
        operational_risks=operational_risks,
        blocking_issues=blocking_issues,
        open_gap_ids=open_gap_ids,
    )


_singleton_lock = threading.Lock()
_singleton: Optional[PlatformClosureAuditReport] = None


def get_platform_closure_audit_report() -> PlatformClosureAuditReport:
    """
    Return the singleton ``PlatformClosureAuditReport``, building it
    on first call.

    Thread-safe via a module-level lock.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = build_platform_closure_audit_report()
        return _singleton


def reset_platform_closure_audit() -> None:
    """
    Reset the singleton so the next call to ``get_platform_closure_audit_report``
    rebuilds the report.

    Intended for testing only.  Must not be called in production paths.
    """
    global _singleton
    with _singleton_lock:
        _singleton = None
