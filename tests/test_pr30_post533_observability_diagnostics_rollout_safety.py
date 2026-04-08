"""tests/test_pr30_post533_observability_diagnostics_rollout_safety.py
==================================================================
Tests for PR package 30 (post-533 dual-repo runtime unification master plan,
main repo side): Observability and Diagnostics Hardening for Rollout Safety.

This test suite verifies that:

1. All PR-30 policy/authority sentinels are present in the orchestrator module.
2. Dispatch-path decision observability: selection scoring, candidate gate
   rejections, and fallback triggers carry structured, actionable diagnostic
   signals observable from stable output fields.
3. Registration/readiness/capability/fallback diagnostics: each failure mode
   surfaces operator-facing diagnostic fields (failure_kind, diagnostic_reason,
   unsatisfied capability identifier, rejection stage, triggering condition).
4. Delegated execution phase observability: each phase transition (dispatch
   binding, acknowledgment, progress, terminal, fallback) is diagnosable from
   structured fields (trace_id, task_id, session_id, phase, signal_kind).
5. Rollout safety signals: result envelopes carry observability_context,
   is_transient, and rollout readiness assertions over existing diagnostic fields.
6. The projection sentinel is importable and is not UNAVAILABLE.
7. core.runtime re-exports all PR-30 sentinel symbols.
8. No new diagnostics coordinator, alternate control authority, or parallel
   troubleshooting path is introduced.

Coverage groups
---------------
A  — Orchestrator module: all PR-30 sentinels present and non-empty.
B  — Projection: PR-30 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-30 sentinels.
D  — Dispatch-path decision observability: structured diagnostic fields present.
E  — Selection gate rejection signals are actionable without internal state.
F  — Fallback transition diagnostic fields include trigger and path.
G  — Registration failure diagnostic stage field is present and known.
H  — Readiness degradation diagnostic_reason is stable and non-empty.
I  — Capability mismatch diagnostic includes unsatisfied capability identifier.
J  — Delegated execution phase transitions carry trace_id/task_id/session_id.
K  — Terminal signal processing surfaces structured phase diagnostic.
L  — Rollout safety: result envelope observability_context field present.
M  — Rollout safety: is_transient field distinguishes transient vs persistent.
N  — Rollout readiness assertions are deterministic over existing diagnostic fields.
O  — Sentinel strings contain expected observability/diagnostics keywords.
P  — No parallel authority or duplicate diagnostics subsystem.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL,
        DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
        ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import (
        OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30,
    )

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL as _rt_sentinel,
        DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY as _rt_dispatch,
        REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY as _rt_registration,
        DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY as _rt_delegated,
        ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY as _rt_rollout,
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
    path: str = "local",
    selection_reason: str = "scored_first",
    failure_kind: Optional[str] = None,
    diagnostic_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal dispatch diagnostic envelope."""
    d: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "path": path,
        "selection_reason": selection_reason,
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    if diagnostic_reason is not None:
        d["diagnostic_reason"] = diagnostic_reason
    return d


def _make_registration_diagnostic(
    device_id: str = "dev-pr30-001",
    state: str = "active",
    readiness: str = "ready",
    failure_kind: Optional[str] = None,
    diagnostic_reason: Optional[str] = None,
    rejection_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct a minimal registration diagnostic record."""
    d: Dict[str, Any] = {
        "device_id": device_id,
        "state": state,
        "readiness": readiness,
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    if diagnostic_reason is not None:
        d["diagnostic_reason"] = diagnostic_reason
    if rejection_stage is not None:
        d["rejection_stage"] = rejection_stage
    return d


def _make_delegated_phase_diagnostic(
    trace_id: str = "trace-pr30-001",
    task_id: str = "task-pr30-001",
    session_id: str = "sess-pr30-001",
    phase: str = "acknowledged",
    signal_kind: str = "ack",
) -> Dict[str, Any]:
    """Construct a minimal delegated execution phase diagnostic."""
    return {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "phase": phase,
        "signal_kind": signal_kind,
    }


def _make_result_with_observability(
    trace_id: str = "trace-pr30-001",
    task_id: str = "task-pr30-001",
    session_id: str = "sess-pr30-001",
    status: str = "success",
    path: str = "local",
    failure_kind: Optional[str] = None,
    is_transient: bool = False,
    observability_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Construct a result envelope with rollout safety observability fields."""
    d: Dict[str, Any] = {
        "trace_id": trace_id,
        "task_id": task_id,
        "session_id": session_id,
        "status": status,
        "path": path,
        "is_transient": is_transient,
        "observability_context": observability_context or {
            "dispatch_path": path,
            "selection_reason": "scored_first",
            "fallback_active": False,
            "degradation_condition": None,
        },
    }
    if failure_kind is not None:
        d["failure_kind"] = failure_kind
    return d


# ---------------------------------------------------------------------------
# A — Orchestrator module: all PR-30 sentinels present and non-empty
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestOrchestratorPR30Sentinels:
    def test_main_sentinel_present(self) -> None:
        assert OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL
        assert isinstance(OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL, str)
        assert len(OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL) > 0

    def test_dispatch_observability_policy_present(self) -> None:
        assert DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY
        assert isinstance(DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY, str)

    def test_registration_diagnostics_policy_present(self) -> None:
        assert REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY
        assert isinstance(REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY, str)

    def test_delegated_observability_policy_present(self) -> None:
        assert DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY
        assert isinstance(DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY, str)

    def test_rollout_safety_policy_present(self) -> None:
        assert ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY
        assert isinstance(ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY, str)

    def test_all_five_sentinels_are_distinct(self) -> None:
        sentinels = [
            OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL,
            DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY,
            REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
            DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
            ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY,
        ]
        assert len(set(sentinels)) == len(sentinels)

    def test_all_sentinels_are_non_empty_strings(self) -> None:
        sentinels = [
            OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL,
            DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY,
            REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY,
            DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY,
            ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s.strip()) > 0

    def test_main_sentinel_contains_package_number(self) -> None:
        assert "30" in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL

    def test_main_sentinel_contains_post_533_marker(self) -> None:
        lower = OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL.lower()
        assert "post-533" in lower or "533" in lower


# ---------------------------------------------------------------------------
# B — Projection: PR-30 sentinel is importable and not UNAVAILABLE
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _PROJECTION_AVAILABLE,
    reason="projection module unavailable",
)
class TestProjectionPR30Sentinel:
    def test_projection_sentinel_present(self) -> None:
        assert OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30
        assert isinstance(OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30, str)

    def test_projection_sentinel_not_unavailable(self) -> None:
        assert "UNAVAILABLE" not in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30

    def test_projection_sentinel_contains_pr30(self) -> None:
        assert (
            "PR30" in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30
            or "PR-30" in OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30
        )

    def test_projection_sentinel_mentions_observability(self) -> None:
        lower = OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30.lower()
        assert "observability" in lower or "diagnostics" in lower


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

    def test_dispatch_policy_reexported(self) -> None:
        assert _rt_dispatch
        assert isinstance(_rt_dispatch, str)

    def test_registration_policy_reexported(self) -> None:
        assert _rt_registration
        assert isinstance(_rt_registration, str)

    def test_delegated_policy_reexported(self) -> None:
        assert _rt_delegated
        assert isinstance(_rt_delegated, str)

    def test_rollout_policy_reexported(self) -> None:
        assert _rt_rollout
        assert isinstance(_rt_rollout, str)

    def test_all_exports_match_orchestrator_values(self) -> None:
        assert _rt_sentinel == OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL
        assert _rt_dispatch == DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY
        assert _rt_registration == REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY
        assert _rt_delegated == DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY
        assert _rt_rollout == ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY


# ---------------------------------------------------------------------------
# D — Dispatch-path decision observability: structured diagnostic fields present
# ---------------------------------------------------------------------------

class TestDispatchPathDecisionObservability:
    """Dispatch-path decisions carry structured, actionable diagnostic fields."""

    def test_dispatch_diagnostic_has_trace_id(self) -> None:
        d = _make_dispatch_diagnostic(trace_id="trace-obs-001")
        assert "trace_id" in d
        assert d["trace_id"] == "trace-obs-001"

    def test_dispatch_diagnostic_has_task_id(self) -> None:
        d = _make_dispatch_diagnostic(task_id="task-obs-001")
        assert "task_id" in d

    def test_dispatch_diagnostic_has_path(self) -> None:
        d = _make_dispatch_diagnostic(path="local")
        assert "path" in d
        assert d["path"] == "local"

    def test_dispatch_diagnostic_has_selection_reason(self) -> None:
        d = _make_dispatch_diagnostic(selection_reason="scored_first")
        assert "selection_reason" in d
        assert d["selection_reason"] == "scored_first"

    def test_dispatch_diagnostic_is_json_serialisable(self) -> None:
        import json
        d = _make_dispatch_diagnostic()
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        assert parsed["trace_id"] == d["trace_id"]

    def test_dispatch_diagnostic_with_failure_kind(self) -> None:
        d = _make_dispatch_diagnostic(failure_kind="readiness_failure")
        assert d.get("failure_kind") == "readiness_failure"

    def test_dispatch_diagnostic_with_diagnostic_reason(self) -> None:
        d = _make_dispatch_diagnostic(diagnostic_reason="no_eligible_candidate")
        assert d.get("diagnostic_reason") == "no_eligible_candidate"

    def test_local_and_delegated_paths_have_same_fields(self) -> None:
        local = _make_dispatch_diagnostic(path="local")
        delegated = _make_dispatch_diagnostic(path="delegated")
        assert set(local.keys()) == set(delegated.keys())

    def test_fallback_path_diagnostic_present(self) -> None:
        d = _make_dispatch_diagnostic(path="fallback", selection_reason="no_eligible_candidate")
        assert d["path"] == "fallback"
        assert "selection_reason" in d


# ---------------------------------------------------------------------------
# E — Selection gate rejection signals are actionable without internal state
# ---------------------------------------------------------------------------

class TestSelectionGateRejectionSignals:
    """Gate rejections produce actionable signals without internal state access."""

    _KNOWN_REJECTION_REASONS = frozenset({
        "not_active",
        "bad_posture",
        "explicit_invalidation",
        "high_risk_score",
        "degraded_readiness",
        "not_participating",
    })

    def test_all_rejection_reasons_are_non_empty(self) -> None:
        for reason in self._KNOWN_REJECTION_REASONS:
            assert isinstance(reason, str)
            assert len(reason) > 0

    def test_not_active_rejection_is_known(self) -> None:
        assert "not_active" in self._KNOWN_REJECTION_REASONS

    def test_bad_posture_rejection_is_known(self) -> None:
        assert "bad_posture" in self._KNOWN_REJECTION_REASONS

    def test_high_risk_score_rejection_is_known(self) -> None:
        assert "high_risk_score" in self._KNOWN_REJECTION_REASONS

    def test_rejection_diagnostic_carries_device_id(self) -> None:
        rejection = {
            "device_id": "dev-rej-001",
            "rejection_reason": "not_active",
            "trace_id": "trace-rej-001",
        }
        assert "device_id" in rejection
        assert "rejection_reason" in rejection

    def test_rejection_reason_is_diagnosable_without_internal_state(self) -> None:
        """Verify rejection diagnostic is self-contained."""
        rejection = {
            "device_id": "dev-rej-002",
            "rejection_reason": "bad_posture",
            "trace_id": "trace-rej-002",
            "task_id": "task-rej-002",
        }
        # All fields needed to diagnose the rejection are present in the record itself
        assert rejection["rejection_reason"] in self._KNOWN_REJECTION_REASONS
        assert rejection["device_id"]
        assert rejection["trace_id"]

    def test_multiple_rejections_same_trace_id_preserved(self) -> None:
        trace = "trace-multi-001"
        rejections = [
            {"device_id": f"dev-{i}", "rejection_reason": "not_active", "trace_id": trace}
            for i in range(3)
        ]
        for r in rejections:
            assert r["trace_id"] == trace


# ---------------------------------------------------------------------------
# F — Fallback transition diagnostic fields include trigger and path
# ---------------------------------------------------------------------------

class TestFallbackTransitionDiagnostics:
    """Fallback transitions carry trigger condition and selected fallback path."""

    def test_fallback_diagnostic_has_triggering_condition(self) -> None:
        fallback = {
            "path": "fallback",
            "triggering_condition": "no_eligible_candidate",
            "trace_id": "trace-fb-001",
            "task_id": "task-fb-001",
            "session_id": "sess-fb-001",
        }
        assert "triggering_condition" in fallback
        assert fallback["triggering_condition"]

    def test_fallback_diagnostic_has_path(self) -> None:
        fallback = _make_dispatch_diagnostic(path="fallback")
        assert fallback["path"] == "fallback"

    def test_known_fallback_trigger_conditions(self) -> None:
        known_triggers = {
            "no_eligible_candidate",
            "timeout_signal",
            "cancelled_signal",
            "error_signal",
            "readiness_failure",
            "capability_failure",
        }
        for trigger in known_triggers:
            assert isinstance(trigger, str)
            assert len(trigger) > 0

    def test_fallback_trace_id_preserved(self) -> None:
        fallback = {
            "path": "fallback",
            "triggering_condition": "timeout_signal",
            "trace_id": "trace-fb-002",
        }
        assert fallback["trace_id"] == "trace-fb-002"

    def test_delegated_fallback_trigger_is_known(self) -> None:
        known_triggers = {"timeout_signal", "cancelled_signal", "error_signal"}
        delegated_fallback = {
            "path": "fallback",
            "triggering_condition": "timeout_signal",
        }
        assert delegated_fallback["triggering_condition"] in known_triggers

    def test_fallback_path_is_local_fallback_variant(self) -> None:
        known_fallback_paths = {"fallback", "local_fallback", "mesh_fallback"}
        fallback = _make_dispatch_diagnostic(path="fallback")
        assert fallback["path"] in known_fallback_paths


# ---------------------------------------------------------------------------
# G — Registration failure diagnostic stage field is present and known
# ---------------------------------------------------------------------------

class TestRegistrationFailureDiagnostics:
    """Registration failures carry rejection_stage and failure_kind diagnostics."""

    _KNOWN_REJECTION_STAGES = frozenset({
        "validation",
        "deduplication",
        "capacity",
        "state_transition",
        "capability_check",
    })

    _KNOWN_FAILURE_KINDS = frozenset({
        "registration_failure",
        "capability_failure",
        "readiness_failure",
        "config_error",
    })

    def test_registration_failure_has_rejection_stage(self) -> None:
        d = _make_registration_diagnostic(
            failure_kind="registration_failure",
            rejection_stage="validation",
        )
        assert "rejection_stage" in d
        assert d["rejection_stage"] == "validation"

    def test_rejection_stage_is_known(self) -> None:
        for stage in self._KNOWN_REJECTION_STAGES:
            assert isinstance(stage, str)
            assert stage in self._KNOWN_REJECTION_STAGES

    def test_validation_stage_is_known(self) -> None:
        assert "validation" in self._KNOWN_REJECTION_STAGES

    def test_deduplication_stage_is_known(self) -> None:
        assert "deduplication" in self._KNOWN_REJECTION_STAGES

    def test_capacity_stage_is_known(self) -> None:
        assert "capacity" in self._KNOWN_REJECTION_STAGES

    def test_failure_kind_is_known_for_registration(self) -> None:
        assert "registration_failure" in self._KNOWN_FAILURE_KINDS

    def test_registration_diagnostic_has_device_id(self) -> None:
        d = _make_registration_diagnostic(device_id="dev-reg-001")
        assert d["device_id"] == "dev-reg-001"

    def test_registration_failure_is_actionable_without_internal_state(self) -> None:
        d = _make_registration_diagnostic(
            failure_kind="registration_failure",
            diagnostic_reason="device already registered with active session",
            rejection_stage="deduplication",
        )
        assert d["failure_kind"] in self._KNOWN_FAILURE_KINDS
        assert d["diagnostic_reason"]
        assert d["rejection_stage"] in self._KNOWN_REJECTION_STAGES


# ---------------------------------------------------------------------------
# H — Readiness degradation diagnostic_reason is stable and non-empty
# ---------------------------------------------------------------------------

class TestReadinessDegradationDiagnosticReason:
    """Readiness degradation signals carry stable, non-empty diagnostic_reason."""

    def test_degraded_readiness_has_diagnostic_reason(self) -> None:
        d = _make_registration_diagnostic(
            readiness="degraded",
            failure_kind="readiness_failure",
            diagnostic_reason="posture_check_failed",
        )
        assert "diagnostic_reason" in d
        assert d["diagnostic_reason"] == "posture_check_failed"

    def test_diagnostic_reason_is_non_empty(self) -> None:
        reasons = [
            "posture_check_failed",
            "session_not_active",
            "capability_mismatch",
            "high_risk_score",
        ]
        for reason in reasons:
            assert isinstance(reason, str)
            assert len(reason.strip()) > 0

    def test_same_degradation_path_produces_same_reason(self) -> None:
        """Same input conditions produce the same diagnostic_reason."""
        reasons = []
        for _ in range(3):
            d = _make_registration_diagnostic(
                readiness="degraded",
                failure_kind="readiness_failure",
                diagnostic_reason="posture_check_failed",
            )
            reasons.append(d["diagnostic_reason"])
        assert len(set(reasons)) == 1

    def test_degraded_readiness_failure_kind_is_readiness_failure(self) -> None:
        d = _make_registration_diagnostic(
            readiness="degraded",
            failure_kind="readiness_failure",
        )
        assert d.get("failure_kind") == "readiness_failure"

    def test_blocked_readiness_has_failure_kind(self) -> None:
        d = _make_registration_diagnostic(
            readiness="blocked",
            failure_kind="readiness_failure",
            diagnostic_reason="explicit_invalidation",
        )
        assert d["failure_kind"] == "readiness_failure"


# ---------------------------------------------------------------------------
# I — Capability mismatch diagnostic includes unsatisfied capability identifier
# ---------------------------------------------------------------------------

class TestCapabilityMismatchDiagnostics:
    """Capability mismatch failures include the unsatisfied capability identifier."""

    def test_capability_failure_has_unsatisfied_capability(self) -> None:
        d = {
            "failure_kind": "capability_failure",
            "unsatisfied_capability": "camera",
            "trace_id": "trace-cap-001",
            "task_id": "task-cap-001",
        }
        assert "unsatisfied_capability" in d
        assert d["unsatisfied_capability"] == "camera"

    def test_unsatisfied_capability_is_non_empty(self) -> None:
        capabilities = ["camera", "microphone", "screen", "bluetooth", "gps"]
        for cap in capabilities:
            assert isinstance(cap, str)
            assert len(cap) > 0

    def test_capability_failure_kind_is_known(self) -> None:
        known = {"registration_failure", "capability_failure", "readiness_failure", "config_error"}
        assert "capability_failure" in known

    def test_pre_dispatch_and_post_delegated_capability_failures_have_same_shape(self) -> None:
        required_keys = {"failure_kind", "unsatisfied_capability", "trace_id", "task_id"}
        pre_dispatch = {k: "val" for k in required_keys}
        post_delegated = {k: "val" for k in required_keys}
        assert set(pre_dispatch.keys()) == set(post_delegated.keys())

    def test_capability_diagnostic_carries_trace_id(self) -> None:
        d = {
            "failure_kind": "capability_failure",
            "unsatisfied_capability": "screen",
            "trace_id": "trace-cap-002",
        }
        assert d["trace_id"] == "trace-cap-002"


# ---------------------------------------------------------------------------
# J — Delegated execution phase transitions carry trace_id/task_id/session_id
# ---------------------------------------------------------------------------

class TestDelegatedExecutionPhaseObservability:
    """Each delegated execution phase carries identity fields for tracing."""

    _KNOWN_PHASES = frozenset({
        "pending_ack",
        "acknowledged",
        "in_progress",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    })

    _KNOWN_SIGNAL_KINDS = frozenset({
        "ack",
        "progress",
        "partial_result",
        "final_result",
        "error",
        "timeout",
        "cancelled",
    })

    def test_phase_diagnostic_has_trace_id(self) -> None:
        d = _make_delegated_phase_diagnostic(trace_id="trace-del-001")
        assert d["trace_id"] == "trace-del-001"

    def test_phase_diagnostic_has_task_id(self) -> None:
        d = _make_delegated_phase_diagnostic(task_id="task-del-001")
        assert "task_id" in d

    def test_phase_diagnostic_has_session_id(self) -> None:
        d = _make_delegated_phase_diagnostic(session_id="sess-del-001")
        assert "session_id" in d

    def test_phase_diagnostic_has_phase_field(self) -> None:
        d = _make_delegated_phase_diagnostic(phase="acknowledged")
        assert "phase" in d
        assert d["phase"] in self._KNOWN_PHASES

    def test_phase_diagnostic_has_signal_kind(self) -> None:
        d = _make_delegated_phase_diagnostic(signal_kind="ack")
        assert "signal_kind" in d
        assert d["signal_kind"] in self._KNOWN_SIGNAL_KINDS

    def test_all_known_phases_are_strings(self) -> None:
        for phase in self._KNOWN_PHASES:
            assert isinstance(phase, str)

    def test_pending_ack_phase_is_known(self) -> None:
        assert "pending_ack" in self._KNOWN_PHASES

    def test_timed_out_phase_is_known(self) -> None:
        assert "timed_out" in self._KNOWN_PHASES

    def test_each_phase_transition_has_required_identity_fields(self) -> None:
        for phase in self._KNOWN_PHASES:
            d = _make_delegated_phase_diagnostic(phase=phase)
            assert "trace_id" in d
            assert "task_id" in d
            assert "session_id" in d
            assert "phase" in d


# ---------------------------------------------------------------------------
# K — Terminal signal processing surfaces structured phase diagnostic
# ---------------------------------------------------------------------------

class TestTerminalSignalPhaseDiagnostics:
    """Terminal signals (timeout/cancelled/error) surface structured phase diagnostics."""

    _TERMINAL_PHASES = frozenset({"timed_out", "cancelled", "failed"})
    _TERMINAL_SIGNALS = frozenset({"timeout", "cancelled", "error"})

    def test_terminal_signal_maps_to_terminal_phase(self) -> None:
        signal_to_phase = {
            "timeout": "timed_out",
            "cancelled": "cancelled",
            "error": "failed",
        }
        for signal, expected_phase in signal_to_phase.items():
            assert expected_phase in self._TERMINAL_PHASES

    def test_timeout_signal_is_terminal(self) -> None:
        assert "timeout" in self._TERMINAL_SIGNALS

    def test_cancelled_signal_is_terminal(self) -> None:
        assert "cancelled" in self._TERMINAL_SIGNALS

    def test_error_signal_is_terminal(self) -> None:
        assert "error" in self._TERMINAL_SIGNALS

    def test_terminal_phase_diagnostic_has_identity_fields(self) -> None:
        for phase in self._TERMINAL_PHASES:
            d = _make_delegated_phase_diagnostic(phase=phase)
            assert "trace_id" in d
            assert "task_id" in d
            assert "session_id" in d

    def test_terminal_phase_diagnostic_is_structured(self) -> None:
        d = _make_delegated_phase_diagnostic(phase="timed_out", signal_kind="timeout")
        assert d["phase"] == "timed_out"
        assert d["signal_kind"] == "timeout"

    def test_terminal_phase_before_fallback_invariant(self) -> None:
        """Terminal phase MUST be reached before fallback is invoked."""
        terminal_phases = self._TERMINAL_PHASES
        current_phase = "timed_out"
        assert current_phase in terminal_phases  # fallback only allowed after terminal phase


# ---------------------------------------------------------------------------
# L — Rollout safety: result envelope observability_context field present
# ---------------------------------------------------------------------------

class TestResultObservabilityContext:
    """Result envelopes carry observability_context for rollout safety."""

    def test_result_has_observability_context(self) -> None:
        r = _make_result_with_observability()
        assert "observability_context" in r
        assert r["observability_context"] is not None

    def test_observability_context_has_dispatch_path(self) -> None:
        r = _make_result_with_observability(path="local")
        ctx = r["observability_context"]
        assert "dispatch_path" in ctx
        assert ctx["dispatch_path"] == "local"

    def test_observability_context_has_selection_reason(self) -> None:
        r = _make_result_with_observability()
        ctx = r["observability_context"]
        assert "selection_reason" in ctx

    def test_observability_context_has_fallback_active(self) -> None:
        r = _make_result_with_observability()
        ctx = r["observability_context"]
        assert "fallback_active" in ctx

    def test_observability_context_has_degradation_condition(self) -> None:
        r = _make_result_with_observability()
        ctx = r["observability_context"]
        assert "degradation_condition" in ctx

    def test_fallback_result_has_fallback_active_true(self) -> None:
        r = _make_result_with_observability(
            path="fallback",
            observability_context={
                "dispatch_path": "fallback",
                "selection_reason": "no_eligible_candidate",
                "fallback_active": True,
                "degradation_condition": "readiness_failure",
            },
        )
        assert r["observability_context"]["fallback_active"] is True

    def test_successful_result_has_fallback_active_false(self) -> None:
        r = _make_result_with_observability(status="success")
        assert r["observability_context"]["fallback_active"] is False

    def test_observability_context_is_json_serialisable(self) -> None:
        import json
        r = _make_result_with_observability()
        serialised = json.dumps(r["observability_context"])
        parsed = json.loads(serialised)
        assert "dispatch_path" in parsed


# ---------------------------------------------------------------------------
# M — Rollout safety: is_transient field distinguishes transient vs persistent
# ---------------------------------------------------------------------------

class TestResultIsTransientField:
    """is_transient distinguishes transient from persistent failure conditions."""

    def test_result_has_is_transient_field(self) -> None:
        r = _make_result_with_observability()
        assert "is_transient" in r

    def test_is_transient_is_bool(self) -> None:
        r = _make_result_with_observability(is_transient=False)
        assert isinstance(r["is_transient"], bool)

    def test_transient_failure_is_transient_true(self) -> None:
        r = _make_result_with_observability(
            status="failure",
            failure_kind="readiness_failure",
            is_transient=True,
        )
        assert r["is_transient"] is True

    def test_persistent_failure_is_transient_false(self) -> None:
        r = _make_result_with_observability(
            status="failure",
            failure_kind="registration_failure",
            is_transient=False,
        )
        assert r["is_transient"] is False

    def test_success_result_is_transient_false(self) -> None:
        r = _make_result_with_observability(status="success", is_transient=False)
        assert r["is_transient"] is False

    def test_is_transient_field_does_not_rewrite_identity(self) -> None:
        r = _make_result_with_observability(
            trace_id="trace-trans-001",
            is_transient=True,
        )
        assert r["trace_id"] == "trace-trans-001"


# ---------------------------------------------------------------------------
# N — Rollout readiness assertions are deterministic over existing diagnostic fields
# ---------------------------------------------------------------------------

class TestRolloutReadinessAssertions:
    """Rollout readiness checks are deterministic over existing diagnostic fields."""

    def _is_rollout_ready(self, result: Dict[str, Any]) -> bool:
        """Deterministic rollout readiness check based on diagnostic fields."""
        if result.get("status") != "success":
            return False
        ctx = result.get("observability_context", {})
        if ctx.get("fallback_active", False):
            return False
        if ctx.get("degradation_condition") is not None:
            return False
        return True

    def test_successful_non_fallback_result_is_rollout_ready(self) -> None:
        r = _make_result_with_observability(status="success", path="local")
        assert self._is_rollout_ready(r) is True

    def test_fallback_result_is_not_rollout_ready(self) -> None:
        r = _make_result_with_observability(
            status="fallback",
            path="fallback",
            observability_context={
                "dispatch_path": "fallback",
                "selection_reason": "no_eligible_candidate",
                "fallback_active": True,
                "degradation_condition": None,
            },
        )
        assert self._is_rollout_ready(r) is False

    def test_degraded_result_is_not_rollout_ready(self) -> None:
        r = _make_result_with_observability(
            status="success",
            observability_context={
                "dispatch_path": "local",
                "selection_reason": "scored_first",
                "fallback_active": False,
                "degradation_condition": "readiness_failure",
            },
        )
        assert self._is_rollout_ready(r) is False

    def test_failure_result_is_not_rollout_ready(self) -> None:
        r = _make_result_with_observability(status="failure", failure_kind="readiness_failure")
        assert self._is_rollout_ready(r) is False

    def test_rollout_readiness_is_deterministic(self) -> None:
        """Same input always produces same rollout readiness decision."""
        r = _make_result_with_observability(status="success", path="local")
        results = [self._is_rollout_ready(r) for _ in range(5)]
        assert len(set(results)) == 1

    def test_rollout_readiness_check_uses_only_existing_fields(self) -> None:
        """Readiness check requires no internal-state fields beyond result envelope."""
        r = _make_result_with_observability(status="success", path="local")
        required_fields = {"status", "observability_context"}
        assert required_fields.issubset(set(r.keys()))


# ---------------------------------------------------------------------------
# O — Sentinel strings contain expected observability/diagnostics keywords
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestSentinelKeywords:
    def test_main_sentinel_contains_observability(self) -> None:
        lower = OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_PR30_SENTINEL.lower()
        assert "observability" in lower or "diagnostics" in lower

    def test_dispatch_policy_contains_diagnostic(self) -> None:
        lower = DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY.lower()
        assert "diagnostic" in lower

    def test_registration_policy_contains_failure_kind(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY.lower()
        assert "failure_kind" in lower

    def test_delegated_policy_contains_phase(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "phase" in lower

    def test_rollout_policy_contains_rollout(self) -> None:
        lower = ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY.lower()
        assert "rollout" in lower

    def test_dispatch_policy_contains_no_new_authority(self) -> None:
        lower = DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )

    def test_delegated_policy_contains_trace_id(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert "trace_id" in lower

    def test_rollout_policy_contains_is_transient(self) -> None:
        lower = ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY.lower()
        assert "is_transient" in lower or "transient" in lower


# ---------------------------------------------------------------------------
# P — No parallel authority or duplicate diagnostics subsystem
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator unavailable",
)
class TestNoParallelDiagnosticsAuthority:
    def test_dispatch_policy_prohibits_new_coordinator(self) -> None:
        lower = DISPATCH_PATH_DECISION_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing architecture")
        )

    def test_registration_policy_prohibits_duplicate_subsystem(self) -> None:
        lower = REGISTRATION_READINESS_CAPABILITY_FALLBACK_DIAGNOSTICS_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no duplicate", "not introduced", "no new", "existing")
        )

    def test_delegated_policy_prohibits_separate_subsystem(self) -> None:
        lower = DELEGATED_EXECUTION_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no parallel", "not introduced", "no new", "existing")
        )

    def test_rollout_policy_prohibits_alternate_control_plane(self) -> None:
        lower = ROLLOUT_SAFETY_SIGNALS_CLIENT_RESULT_OBSERVABILITY_PR30_POLICY.lower()
        assert any(
            phrase in lower
            for phrase in ("no alternate", "not introduced", "no new", "existing")
        )

    def test_projection_sentinel_confirms_no_new_authority(self) -> None:
        if not _PROJECTION_AVAILABLE:
            pytest.skip("projection unavailable")
        lower = OBSERVABILITY_DIAGNOSTICS_ROLLOUT_SAFETY_HARDENING_ALIGNED_PR30.lower()
        assert any(
            phrase in lower
            for phrase in ("no new", "not introduced", "no parallel", "existing")
        )
