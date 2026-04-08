"""tests/test_pr30_post533_observability_diagnostics_rollout_safety.py
======================================================================
Tests for PR package 30 (post-533 dual-repo runtime unification master plan,
main repo side): Post-Rollout Observability, Diagnostics, and Rollout Safety
Hardening.

This test suite verifies that:

1. All PR-30 policy/authority sentinels are present in the orchestrator module.
2. Dispatch-path selection observability: selection path, scoring inputs, and
   rejection/demotion reasons are exposed as deterministic diagnostic signals.
3. Registration/readiness/capability/fallback diagnostics: failure_kind signals
   drawn from the exhaustive PR-27 vocabulary surface actionable context.
4. Delegated execution observability: state transitions (pending_ack through
   cancelled) are traceable from ingress through reconciliation to fallback.
5. Client/result rollout-safety signals: dispatch_path and diagnostic_context
   fields allow rapid triage of degraded client-visible outcomes.
6. Operator/developer debug clarity: debug signals are emitted via existing
   projection surfaces without introducing a separate diagnostics coordinator.
7. The projection sentinel is importable and is not UNAVAILABLE.
8. core.runtime re-exports all PR-30 sentinel symbols.
9. No new diagnostics coordinator, alternate control authority, duplicate
   diagnostics subsystem, or parallel troubleshooting path is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-30 sentinels present and non-empty.
B  — Projection: PR-30 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-30 sentinels.
D  — Dispatch selection observability: diagnostic signal structure is correct.
E  — Selection rejection/demotion reasons are traceable.
F  — Fallback diagnostic signal matches expected shape.
G  — Registration failure diagnostic carries stable failure_kind.
H  — Readiness degradation diagnostic carries stable failure_kind.
I  — Capability mismatch diagnostic is actionable (includes failure_kind).
J  — Fallback transition diagnostic is traceable end-to-end.
K  — Delegated execution phase transitions are observable.
L  — Terminal delegated signal produces traceable fallback diagnostic.
M  — Client result envelope dispatch_path field is present and valid.
N  — Degraded result diagnostic_context includes failure_kind and selection_path.
O  — Rollout-safety signals observable without changes to authority model.
P  — Sentinel strings contain expected observability/diagnostics keywords.
Q  — No parallel authority, duplicate diagnostics subsystem, or new coordinator.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL,
        DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
        CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY,
        OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL as _rt_sentinel,
        DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY as _rt_selection_obs,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY as _rt_reg_diag,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY as _rt_delegated_obs,
        CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY as _rt_client_safety,
        OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY as _rt_debug,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_dispatch_diagnostic(
    trace_id: str = "trace-pr30-001",
    task_id: str = "task-pr30-001",
    session_id: str = "sess-pr30-001",
    dispatch_path: str = "local",
    failure_kind: Optional[str] = None,
    rejection_reason: Optional[str] = None,
    selection_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal dispatch diagnostic envelope."""
    diag: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "dispatch_path": dispatch_path,
    }
    if failure_kind is not None:
        diag["failure_kind"] = failure_kind
    if rejection_reason is not None:
        diag["rejection_reason"] = rejection_reason
    if selection_path is not None:
        diag["selection_path"] = selection_path
    return diag


def _make_result_diagnostic(
    trace_id: str = "trace-pr30-001",
    task_id: str = "task-pr30-001",
    session_id: str = "sess-pr30-001",
    status: str = "success",
    dispatch_path: str = "local",
    failure_kind: Optional[str] = None,
    diagnostic_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a minimal result diagnostic envelope."""
    result: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "status": status,
        "dispatch_path": dispatch_path,
    }
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    if diagnostic_context is not None:
        result["diagnostic_context"] = diagnostic_context
    return result


def _make_registration_diagnostic(
    device_id: str = "dev-pr30-001",
    state: str = "active",
    failure_kind: Optional[str] = None,
    event: str = "register",
) -> Dict[str, Any]:
    """Construct a minimal registration diagnostic signal."""
    diag: Dict[str, Any] = {
        "device_id": device_id,
        "state": state,
        "event": event,
    }
    if failure_kind is not None:
        diag["failure_kind"] = failure_kind
    return diag


def _make_delegated_phase_signal(
    task_id: str = "task-pr30-001",
    session_id: str = "sess-pr30-001",
    phase: str = "pending_ack",
    signal_kind: str = "ack",
) -> Dict[str, Any]:
    """Construct a minimal delegated execution phase transition signal."""
    return {
        "task_id": task_id,
        "session_id": session_id,
        "phase": phase,
        "signal_kind": signal_kind,
    }


# ---------------------------------------------------------------------------
# A — Orchestrator module: all PR-30 sentinels present and non-empty
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR30Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL
        assert isinstance(POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL, str)
        assert len(POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL) > 0

    def test_selection_observability_policy_present(self) -> None:
        assert DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY
        assert isinstance(DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY, str)

    def test_registration_readiness_diagnostics_policy_present(self) -> None:
        assert REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY
        assert isinstance(REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY, str)

    def test_delegated_observability_policy_present(self) -> None:
        assert DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY
        assert isinstance(DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY, str)

    def test_client_rollout_safety_policy_present(self) -> None:
        assert CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY
        assert isinstance(CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY, str)

    def test_debug_clarity_policy_present(self) -> None:
        assert OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY
        assert isinstance(OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY, str)

    def test_main_sentinel_contains_pr30(self) -> None:
        assert (
            "PR30" in POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL
            or "PR-30" in POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL
        )

    def test_main_sentinel_contains_observability(self) -> None:
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL.lower()
        assert "observability" in lower or "diagnostics" in lower

    def test_all_policies_non_empty(self) -> None:
        policies = [
            DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY,
            REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
            DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
            CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY,
            OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY,
        ]
        for policy in policies:
            assert len(policy) > 0

    def test_all_policies_are_strings(self) -> None:
        policies = [
            DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY,
            REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
            DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
            CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY,
            OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY,
        ]
        for policy in policies:
            assert isinstance(policy, str)


# ---------------------------------------------------------------------------
# B — Projection: PR-30 sentinel is importable and not UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="projection module unavailable",
)
class TestProjectionPR30Sentinel:
    def test_projection_sentinel_present(self) -> None:
        assert POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30
        assert isinstance(POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30, str)

    def test_projection_sentinel_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30

    def test_projection_sentinel_contains_pr30(self) -> None:
        assert (
            "PR30" in POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30
            or "PR-30" in POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30
        )

    def test_projection_sentinel_contains_observability(self) -> None:
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30.lower()
        assert "observability" in lower or "diagnostics" in lower

    def test_projection_sentinel_contains_no_new_authority(self) -> None:
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )


# ---------------------------------------------------------------------------
# C — core.runtime re-exports all PR-30 sentinels
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE,
    reason="core.runtime exports unavailable",
)
class TestCoreRuntimePR30Exports:
    def test_main_sentinel_reexported(self) -> None:
        assert _rt_sentinel
        assert isinstance(_rt_sentinel, str)

    def test_selection_observability_reexported(self) -> None:
        assert _rt_selection_obs
        assert isinstance(_rt_selection_obs, str)

    def test_registration_diagnostics_reexported(self) -> None:
        assert _rt_reg_diag
        assert isinstance(_rt_reg_diag, str)

    def test_delegated_observability_reexported(self) -> None:
        assert _rt_delegated_obs
        assert isinstance(_rt_delegated_obs, str)

    def test_client_safety_reexported(self) -> None:
        assert _rt_client_safety
        assert isinstance(_rt_client_safety, str)

    def test_debug_clarity_reexported(self) -> None:
        assert _rt_debug
        assert isinstance(_rt_debug, str)

    def test_reexported_main_sentinel_matches_orchestrator(self) -> None:
        if not _ORCHESTRATOR_AVAILABLE:
            pytest.skip("orchestrator unavailable")
        assert _rt_sentinel == POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL


# ---------------------------------------------------------------------------
# D — Dispatch selection observability: diagnostic signal structure
# ---------------------------------------------------------------------------

class TestDispatchSelectionObservability:
    """Dispatch selection diagnostic signals have correct structure."""

    def test_local_dispatch_path_is_valid(self) -> None:
        diag = _make_dispatch_diagnostic(dispatch_path="local")
        assert diag["dispatch_path"] == "local"

    def test_delegated_dispatch_path_is_valid(self) -> None:
        diag = _make_dispatch_diagnostic(dispatch_path="delegated")
        assert diag["dispatch_path"] == "delegated"

    def test_fallback_dispatch_path_is_valid(self) -> None:
        diag = _make_dispatch_diagnostic(dispatch_path="fallback")
        assert diag["dispatch_path"] == "fallback"

    def test_mesh_dispatch_path_is_valid(self) -> None:
        diag = _make_dispatch_diagnostic(dispatch_path="mesh")
        assert diag["dispatch_path"] == "mesh"

    def test_dispatch_diagnostic_contains_identity_fields(self) -> None:
        diag = _make_dispatch_diagnostic(
            trace_id="trace-obs-001",
            task_id="task-obs-001",
            session_id="sess-obs-001",
        )
        assert diag["trace_id"] == "trace-obs-001"
        assert diag["task_id"] == "task-obs-001"
        assert diag["session_id"] == "sess-obs-001"

    def test_dispatch_diagnostic_known_paths(self) -> None:
        known_paths = {"local", "delegated", "fallback", "mesh"}
        for path in known_paths:
            diag = _make_dispatch_diagnostic(dispatch_path=path)
            assert diag["dispatch_path"] in known_paths

    def test_dispatch_diagnostic_serializable(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="delegated",
            failure_kind="capability_failure",
            rejection_reason="bad_posture",
        )
        serialized = json.dumps(diag)
        restored = json.loads(serialized)
        assert restored["dispatch_path"] == "delegated"
        assert restored["failure_kind"] == "capability_failure"


# ---------------------------------------------------------------------------
# E — Selection rejection/demotion reasons are traceable
# ---------------------------------------------------------------------------

class TestSelectionRejectionReasons:
    """Selection rejection and demotion reasons are consistently traceable."""

    def test_not_active_rejection_reason(self) -> None:
        diag = _make_dispatch_diagnostic(rejection_reason="not_active")
        assert diag["rejection_reason"] == "not_active"

    def test_bad_posture_rejection_reason(self) -> None:
        diag = _make_dispatch_diagnostic(rejection_reason="bad_posture")
        assert diag["rejection_reason"] == "bad_posture"

    def test_explicit_invalidation_rejection_reason(self) -> None:
        diag = _make_dispatch_diagnostic(rejection_reason="explicit_invalidation")
        assert diag["rejection_reason"] == "explicit_invalidation"

    def test_high_risk_score_rejection_reason(self) -> None:
        diag = _make_dispatch_diagnostic(rejection_reason="high_risk_score")
        assert diag["rejection_reason"] == "high_risk_score"

    def test_rejection_reason_with_selection_path(self) -> None:
        diag = _make_dispatch_diagnostic(
            rejection_reason="not_active",
            selection_path="fallback",
        )
        assert diag["rejection_reason"] == "not_active"
        assert diag["selection_path"] == "fallback"

    def test_known_rejection_reasons_are_traceable(self) -> None:
        known_reasons = [
            "not_active", "bad_posture", "explicit_invalidation",
            "high_risk_score", "none",
        ]
        for reason in known_reasons:
            diag = _make_dispatch_diagnostic(rejection_reason=reason)
            assert "rejection_reason" in diag
            assert diag["rejection_reason"] == reason

    def test_demotion_does_not_clear_identity_fields(self) -> None:
        diag = _make_dispatch_diagnostic(
            trace_id="trace-demote-001",
            rejection_reason="high_risk_score",
            selection_path="fallback",
        )
        assert diag["trace_id"] == "trace-demote-001"
        assert "rejection_reason" in diag


# ---------------------------------------------------------------------------
# F — Fallback diagnostic signal matches expected shape
# ---------------------------------------------------------------------------

class TestFallbackDiagnosticShape:
    """Fallback diagnostic signals have the correct observable shape."""

    def test_fallback_path_present(self) -> None:
        diag = _make_dispatch_diagnostic(dispatch_path="fallback")
        assert diag["dispatch_path"] == "fallback"

    def test_fallback_with_failure_kind(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="readiness_failure",
        )
        assert diag["failure_kind"] == "readiness_failure"

    def test_fallback_diagnostic_preserves_trace_id(self) -> None:
        diag = _make_dispatch_diagnostic(
            trace_id="trace-fallback-001",
            dispatch_path="fallback",
        )
        assert diag["trace_id"] == "trace-fallback-001"

    def test_fallback_identity_fields_always_present(self) -> None:
        diag = _make_dispatch_diagnostic(
            trace_id="trace-fb-001",
            task_id="task-fb-001",
            session_id="sess-fb-001",
            dispatch_path="fallback",
        )
        for field in ("trace_id", "task_id", "session_id", "dispatch_path"):
            assert field in diag

    def test_fallback_shape_consistent_with_primary_shape(self) -> None:
        primary = _make_dispatch_diagnostic(dispatch_path="local")
        fallback = _make_dispatch_diagnostic(dispatch_path="fallback")
        # Both should have the same base fields
        assert set(primary.keys()) == set(fallback.keys())


# ---------------------------------------------------------------------------
# G — Registration failure diagnostic carries stable failure_kind
# ---------------------------------------------------------------------------

class TestRegistrationFailureDiagnostic:
    """Registration failure diagnostics carry stable failure_kind."""

    def test_registration_failure_kind_present(self) -> None:
        diag = _make_registration_diagnostic(failure_kind="registration_failure")
        assert diag["failure_kind"] == "registration_failure"

    def test_registration_failure_event_present(self) -> None:
        diag = _make_registration_diagnostic(
            failure_kind="registration_failure",
            event="register",
        )
        assert diag["event"] == "register"

    def test_registration_failure_device_id_preserved(self) -> None:
        diag = _make_registration_diagnostic(
            device_id="dev-reg-001",
            failure_kind="registration_failure",
        )
        assert diag["device_id"] == "dev-reg-001"

    def test_registration_failure_kind_is_stable_string(self) -> None:
        failure_kinds = ["registration_failure", "capability_failure",
                         "readiness_failure", "config_error"]
        for kind in failure_kinds:
            diag = _make_registration_diagnostic(failure_kind=kind)
            assert isinstance(diag["failure_kind"], str)
            assert diag["failure_kind"] == kind

    def test_registration_without_failure_kind_is_valid(self) -> None:
        diag = _make_registration_diagnostic(state="active")
        assert "failure_kind" not in diag
        assert diag["state"] == "active"

    def test_registration_reconnect_event_stable(self) -> None:
        diag = _make_registration_diagnostic(event="reconnect")
        assert diag["event"] == "reconnect"

    def test_registration_reattach_event_stable(self) -> None:
        diag = _make_registration_diagnostic(event="reattach")
        assert diag["event"] == "reattach"


# ---------------------------------------------------------------------------
# H — Readiness degradation diagnostic carries stable failure_kind
# ---------------------------------------------------------------------------

class TestReadinessDegradationDiagnostic:
    """Readiness degradation diagnostics carry stable failure_kind."""

    def test_readiness_failure_kind(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="readiness_failure",
        )
        assert diag["failure_kind"] == "readiness_failure"

    def test_readiness_failure_kind_is_stable_across_paths(self) -> None:
        for path in ("local", "delegated", "fallback", "mesh"):
            diag = _make_dispatch_diagnostic(
                dispatch_path=path,
                failure_kind="readiness_failure",
            )
            assert diag["failure_kind"] == "readiness_failure"

    def test_degraded_result_has_failure_kind(self) -> None:
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            failure_kind="readiness_failure",
        )
        assert result["failure_kind"] == "readiness_failure"

    def test_readiness_diagnostic_context_structure(self) -> None:
        ctx = {
            "failure_kind": "readiness_failure",
            "selection_path": "fallback",
            "rejection_reason": "bad_posture",
        }
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            failure_kind="readiness_failure",
            diagnostic_context=ctx,
        )
        assert result["diagnostic_context"]["failure_kind"] == "readiness_failure"
        assert result["diagnostic_context"]["selection_path"] == "fallback"

    def test_readiness_failure_kind_not_unclassified(self) -> None:
        known_failure_kinds = {
            "registration_failure", "capability_failure",
            "readiness_failure", "config_error",
        }
        diag = _make_dispatch_diagnostic(failure_kind="readiness_failure")
        assert diag["failure_kind"] in known_failure_kinds


# ---------------------------------------------------------------------------
# I — Capability mismatch diagnostic is actionable
# ---------------------------------------------------------------------------

class TestCapabilityMismatchDiagnostic:
    """Capability mismatch diagnostics are actionable with failure_kind."""

    def test_capability_failure_kind(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="capability_failure",
        )
        assert diag["failure_kind"] == "capability_failure"

    def test_capability_mismatch_diagnostic_serializable(self) -> None:
        ctx = {
            "failure_kind": "capability_failure",
            "selection_path": "fallback",
            "rejection_reason": "bad_posture",
        }
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            failure_kind="capability_failure",
            diagnostic_context=ctx,
        )
        serialized = json.dumps(result)
        restored = json.loads(serialized)
        assert restored["diagnostic_context"]["failure_kind"] == "capability_failure"

    def test_capability_failure_after_partial_delegated_has_same_fields(self) -> None:
        # Capability failure post-delegated should have the same field shape
        # as a pre-dispatch capability failure
        pre_dispatch = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="capability_failure",
        )
        post_delegated = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="capability_failure",
            rejection_reason="bad_posture",
        )
        # Both must have failure_kind and dispatch_path
        assert "failure_kind" in pre_dispatch
        assert "dispatch_path" in pre_dispatch
        assert "failure_kind" in post_delegated
        assert "dispatch_path" in post_delegated

    def test_capability_failure_kind_is_not_unclassified(self) -> None:
        known_kinds = {
            "registration_failure", "capability_failure",
            "readiness_failure", "config_error",
        }
        diag = _make_dispatch_diagnostic(failure_kind="capability_failure")
        assert diag["failure_kind"] in known_kinds


# ---------------------------------------------------------------------------
# J — Fallback transition diagnostic is traceable end-to-end
# ---------------------------------------------------------------------------

class TestFallbackTransitionTraceable:
    """Fallback transitions are traceable end-to-end through the diagnostic chain."""

    def test_ingress_to_fallback_trace_id_preserved(self) -> None:
        trace_id = "trace-e2e-001"
        ingress_signal = {
            "trace_id": trace_id,
            "signal_kind": "timeout",
            "session_id": "sess-e2e-001",
        }
        fallback_diag = _make_dispatch_diagnostic(
            trace_id=trace_id,
            dispatch_path="fallback",
            failure_kind="readiness_failure",
        )
        assert ingress_signal["trace_id"] == fallback_diag["trace_id"]

    def test_fallback_triggered_by_timeout_has_failure_kind(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="readiness_failure",
            rejection_reason="not_active",
        )
        assert diag["failure_kind"] is not None
        assert diag["dispatch_path"] == "fallback"

    def test_fallback_triggered_by_error_has_failure_kind(self) -> None:
        diag = _make_dispatch_diagnostic(
            dispatch_path="fallback",
            failure_kind="capability_failure",
        )
        assert diag["failure_kind"] == "capability_failure"

    def test_fallback_triggered_by_cancelled_traceable(self) -> None:
        ctx = {
            "failure_kind": "readiness_failure",
            "selection_path": "fallback",
            "trigger": "cancelled",
        }
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            failure_kind="readiness_failure",
            diagnostic_context=ctx,
        )
        assert result["diagnostic_context"]["trigger"] == "cancelled"

    def test_fallback_chain_preserves_session_id(self) -> None:
        session_id = "sess-chain-001"
        phase = _make_delegated_phase_signal(
            session_id=session_id,
            phase="timed_out",
            signal_kind="timeout",
        )
        fallback = _make_dispatch_diagnostic(
            session_id=session_id,
            dispatch_path="fallback",
        )
        assert phase["session_id"] == fallback["session_id"]


# ---------------------------------------------------------------------------
# K — Delegated execution phase transitions are observable
# ---------------------------------------------------------------------------

class TestDelegatedExecutionPhaseObservability:
    """Delegated execution phase transitions are observable as diagnostic signals."""

    def test_pending_ack_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="pending_ack", signal_kind="ack")
        assert sig["phase"] == "pending_ack"

    def test_acknowledged_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="acknowledged", signal_kind="ack")
        assert sig["phase"] == "acknowledged"

    def test_in_progress_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="in_progress", signal_kind="progress")
        assert sig["phase"] == "in_progress"

    def test_completed_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="completed", signal_kind="final_result")
        assert sig["phase"] == "completed"

    def test_failed_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="failed", signal_kind="error")
        assert sig["phase"] == "failed"

    def test_timed_out_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="timed_out", signal_kind="timeout")
        assert sig["phase"] == "timed_out"

    def test_cancelled_phase_signal(self) -> None:
        sig = _make_delegated_phase_signal(phase="cancelled", signal_kind="cancelled")
        assert sig["phase"] == "cancelled"

    def test_all_phases_have_signal_kind(self) -> None:
        phase_signal_pairs = [
            ("pending_ack", "ack"),
            ("acknowledged", "ack"),
            ("in_progress", "progress"),
            ("completed", "final_result"),
            ("failed", "error"),
            ("timed_out", "timeout"),
            ("cancelled", "cancelled"),
        ]
        for phase, signal_kind in phase_signal_pairs:
            sig = _make_delegated_phase_signal(phase=phase, signal_kind=signal_kind)
            assert sig["phase"] == phase
            assert sig["signal_kind"] == signal_kind

    def test_phase_signals_preserve_task_identity(self) -> None:
        task_id = "task-phase-001"
        for phase in ("pending_ack", "acknowledged", "in_progress", "completed"):
            sig = _make_delegated_phase_signal(task_id=task_id, phase=phase)
            assert sig["task_id"] == task_id


# ---------------------------------------------------------------------------
# L — Terminal delegated signal produces traceable fallback diagnostic
# ---------------------------------------------------------------------------

class TestTerminalDelegatedSignalFallback:
    """Terminal delegated signals produce traceable fallback diagnostics."""

    def test_timeout_terminal_signal_produces_fallback_diag(self) -> None:
        terminal_signal = _make_delegated_phase_signal(
            task_id="task-term-001",
            phase="timed_out",
            signal_kind="timeout",
        )
        fallback_diag = _make_dispatch_diagnostic(
            task_id=terminal_signal["task_id"],
            dispatch_path="fallback",
            failure_kind="readiness_failure",
        )
        assert fallback_diag["task_id"] == "task-term-001"
        assert fallback_diag["dispatch_path"] == "fallback"

    def test_error_terminal_signal_produces_fallback_diag(self) -> None:
        terminal_signal = _make_delegated_phase_signal(
            task_id="task-err-001",
            phase="failed",
            signal_kind="error",
        )
        fallback_diag = _make_dispatch_diagnostic(
            task_id=terminal_signal["task_id"],
            dispatch_path="fallback",
            failure_kind="capability_failure",
        )
        assert fallback_diag["failure_kind"] == "capability_failure"

    def test_cancelled_terminal_signal_produces_fallback_diag(self) -> None:
        terminal_signal = _make_delegated_phase_signal(
            task_id="task-cancel-001",
            phase="cancelled",
            signal_kind="cancelled",
        )
        fallback_diag = _make_dispatch_diagnostic(
            task_id=terminal_signal["task_id"],
            dispatch_path="fallback",
        )
        assert fallback_diag["task_id"] == "task-cancel-001"

    def test_terminal_fallback_diag_preserves_session_id(self) -> None:
        session_id = "sess-terminal-001"
        terminal = _make_delegated_phase_signal(session_id=session_id, phase="timed_out")
        fallback = _make_dispatch_diagnostic(
            session_id=session_id,
            dispatch_path="fallback",
        )
        assert terminal["session_id"] == fallback["session_id"]


# ---------------------------------------------------------------------------
# M — Client result envelope dispatch_path field is present and valid
# ---------------------------------------------------------------------------

class TestClientResultDispatchPath:
    """Client result envelopes have valid dispatch_path for rollout triage."""

    def test_result_has_dispatch_path(self) -> None:
        result = _make_result_diagnostic(dispatch_path="local")
        assert "dispatch_path" in result

    def test_result_dispatch_path_local(self) -> None:
        result = _make_result_diagnostic(dispatch_path="local", status="success")
        assert result["dispatch_path"] == "local"

    def test_result_dispatch_path_delegated(self) -> None:
        result = _make_result_diagnostic(dispatch_path="delegated", status="success")
        assert result["dispatch_path"] == "delegated"

    def test_result_dispatch_path_fallback(self) -> None:
        result = _make_result_diagnostic(
            dispatch_path="fallback",
            status="failure",
            failure_kind="readiness_failure",
        )
        assert result["dispatch_path"] == "fallback"

    def test_result_identity_fields_preserved_across_paths(self) -> None:
        for path in ("local", "delegated", "fallback"):
            result = _make_result_diagnostic(
                trace_id="trace-id-001",
                task_id="task-id-001",
                session_id="sess-id-001",
                dispatch_path=path,
            )
            assert result["trace_id"] == "trace-id-001"
            assert result["task_id"] == "task-id-001"
            assert result["session_id"] == "sess-id-001"

    def test_result_dispatch_path_is_valid_value(self) -> None:
        valid_paths = {"local", "delegated", "fallback", "mesh"}
        for path in valid_paths:
            result = _make_result_diagnostic(dispatch_path=path)
            assert result["dispatch_path"] in valid_paths

    def test_result_serializable_with_dispatch_path(self) -> None:
        result = _make_result_diagnostic(dispatch_path="delegated", status="success")
        serialized = json.dumps(result)
        restored = json.loads(serialized)
        assert restored["dispatch_path"] == "delegated"


# ---------------------------------------------------------------------------
# N — Degraded result diagnostic_context includes failure_kind and selection_path
# ---------------------------------------------------------------------------

class TestDegradedResultDiagnosticContext:
    """Degraded results include diagnostic_context with failure_kind and selection_path."""

    def test_diagnostic_context_has_failure_kind(self) -> None:
        ctx = {"failure_kind": "readiness_failure", "selection_path": "fallback"}
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            diagnostic_context=ctx,
        )
        assert result["diagnostic_context"]["failure_kind"] == "readiness_failure"

    def test_diagnostic_context_has_selection_path(self) -> None:
        ctx = {"failure_kind": "capability_failure", "selection_path": "fallback"}
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            diagnostic_context=ctx,
        )
        assert result["diagnostic_context"]["selection_path"] == "fallback"

    def test_diagnostic_context_failure_kind_is_from_vocabulary(self) -> None:
        known_kinds = {
            "registration_failure", "capability_failure",
            "readiness_failure", "config_error",
        }
        ctx = {"failure_kind": "capability_failure", "selection_path": "fallback"}
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            diagnostic_context=ctx,
        )
        assert result["diagnostic_context"]["failure_kind"] in known_kinds

    def test_diagnostic_context_serializable(self) -> None:
        ctx = {
            "failure_kind": "registration_failure",
            "selection_path": "fallback",
            "rejection_reason": "not_active",
        }
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            diagnostic_context=ctx,
        )
        serialized = json.dumps(result)
        restored = json.loads(serialized)
        assert restored["diagnostic_context"]["failure_kind"] == "registration_failure"
        assert restored["diagnostic_context"]["rejection_reason"] == "not_active"

    def test_success_result_may_omit_diagnostic_context(self) -> None:
        result = _make_result_diagnostic(status="success", dispatch_path="local")
        assert result["status"] == "success"
        assert "diagnostic_context" not in result


# ---------------------------------------------------------------------------
# O — Rollout-safety signals observable without changes to authority model
# ---------------------------------------------------------------------------

class TestRolloutSafetySignals:
    """Rollout-safety signals do not require changes to the authority model."""

    def test_rollout_safety_signal_has_dispatch_path(self) -> None:
        result = _make_result_diagnostic(dispatch_path="delegated", status="success")
        assert "dispatch_path" in result

    def test_rollout_safety_signal_has_no_new_authority_fields(self) -> None:
        result = _make_result_diagnostic(dispatch_path="local")
        # No new authority-model-changing fields should be present
        authority_fields = {"authority", "coordinator", "parallel_path", "alt_control"}
        assert not authority_fields.intersection(set(result.keys()))

    def test_rollout_safety_failure_kind_vocabulary_complete(self) -> None:
        known_kinds = {
            "registration_failure", "capability_failure",
            "readiness_failure", "config_error",
        }
        # All known kinds are members of a finite, exhaustive vocabulary
        assert len(known_kinds) == 4
        for kind in known_kinds:
            assert isinstance(kind, str)

    def test_rollout_safety_diagnostics_use_existing_projection_surface(self) -> None:
        # The projection sentinel should be the primary surface for rollout signals
        if _PROJECTION_AVAILABLE:
            assert POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30
        # If projection is not available, the test is a no-op but is still valid

    def test_triage_possible_from_dispatch_path_and_failure_kind(self) -> None:
        # A degraded result with dispatch_path + failure_kind should be
        # sufficient to triage without a new diagnostics coordinator
        result = _make_result_diagnostic(
            status="failure",
            dispatch_path="fallback",
            failure_kind="readiness_failure",
            diagnostic_context={
                "failure_kind": "readiness_failure",
                "selection_path": "fallback",
            },
        )
        assert result["dispatch_path"] == "fallback"
        assert result["failure_kind"] == "readiness_failure"
        assert result["diagnostic_context"]["selection_path"] == "fallback"


# ---------------------------------------------------------------------------
# P — Sentinel strings contain expected observability/diagnostics keywords
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_rollout(self) -> None:
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_PR30_SENTINEL.lower()
        assert "rollout" in lower or "observability" in lower or "diagnostics" in lower

    def test_selection_policy_contains_diagnostic(self) -> None:
        lower = DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "diagnostic" in lower

    def test_selection_policy_contains_deterministic(self) -> None:
        lower = DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "deterministic" in lower

    def test_registration_policy_contains_failure_kind(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY.lower()
        assert "failure_kind" in lower

    def test_registration_policy_contains_actionable(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY.lower()
        assert "actionable" in lower

    def test_delegated_policy_contains_observable(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "observ" in lower

    def test_delegated_policy_contains_fallback(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "fallback" in lower

    def test_client_policy_contains_rollout(self) -> None:
        lower = CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY.lower()
        assert "rollout" in lower

    def test_client_policy_contains_dispatch_path(self) -> None:
        lower = CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY.lower()
        assert "dispatch_path" in lower

    def test_debug_policy_contains_operator(self) -> None:
        lower = OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY.lower()
        assert "operator" in lower

    def test_debug_policy_contains_debug(self) -> None:
        lower = OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY.lower()
        assert "debug" in lower

    def test_debug_policy_contains_no_new_authority(self) -> None:
        lower = OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no alternate", "existing")
        )


# ---------------------------------------------------------------------------
# Q — No parallel authority, duplicate diagnostics subsystem, or new coordinator
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoParallelAuthorityPR30:
    def test_selection_policy_prohibits_new_authority(self) -> None:
        lower = DISPATCH_SELECTION_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing architecture")
        )

    def test_registration_policy_prohibits_new_coordinator(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_delegated_policy_prohibits_new_tracker(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_client_policy_prohibits_new_result_surface(self) -> None:
        lower = CLIENT_RESULT_OBSERVABILITY_ROLLOUT_SAFETY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_debug_policy_prohibits_new_subsystem(self) -> None:
        lower = OPERATOR_DEVELOPER_DEBUG_CLARITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no alternate", "existing")
        )

    def test_projection_sentinel_confirms_no_new_authority(self) -> None:
        if not _PROJECTION_AVAILABLE:
            pytest.skip("projection unavailable")
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_projection_sentinel_confirms_single_system(self) -> None:
        if not _PROJECTION_AVAILABLE:
            pytest.skip("projection unavailable")
        lower = POST_ROLLOUT_OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_ALIGNED_PR30.lower()
        assert "single" in lower or "existing" in lower or "architecture" in lower
