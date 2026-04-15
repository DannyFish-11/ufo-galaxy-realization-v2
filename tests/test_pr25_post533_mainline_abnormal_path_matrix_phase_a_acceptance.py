"""tests/test_pr25_post533_mainline_abnormal_path_matrix_phase_a_acceptance.py
==============================================================================
Tests for PR package 25 (post-533 dual-repo runtime unification master plan,
main repo side): Mainline Abnormal-Path Matrix + Phase A Acceptance.

This test suite verifies that:

1. All PR-25 policy/authority sentinels are present in the orchestrator module.
2. Remote task blocks local loop — when mode is remote_handoff and remote
   succeeds, local execution is NOT attempted.
3. Local fallback after remote failure — when remote handoff fails, the result
   records effective_mode=fallback_local and errors list is non-empty.
4. Delegated execution failure preserves session truth — registry state is not
   altered as a side-effect of a failed remote dispatch.
5. Selection fallback under degraded conditions is stable — when all candidates
   fail the readiness/participation gates, select_dispatch_target returns None
   (not a random active session), and select_dispatch_mode falls back to local.
6. Session truth consistency under failure transitions — the registry remains
   the single truth source before and after an abnormal dispatch transition.
7. select_dispatch_mode: force_remote without target falls back to local.
8. select_dispatch_mode: blocked path returns blocked mode.
9. orchestrate_source_runtime_dispatch: blocked mode returns failure result.
10. select_dispatch_target: no active sessions → None (degraded path).
11. select_dispatch_target: candidate rejected by readiness → None.
12. select_dispatch_target: candidate rejected by participation → None.
13. Remote handoff error path (exception raised) → fallback_local.
14. Remote handoff no_target_or_envelope path → fallback_local.
15. The projection sentinel is importable and is not UNAVAILABLE.
16. core.runtime re-exports all PR-25 sentinel symbols.

Coverage groups
---------------
A  — Orchestrator module: all PR-25 sentinels present.
B  — Projection: PR-25 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-25 sentinels.
D  — Remote task blocks local loop (remote success → no local execution).
E  — Local fallback after remote failure (remote failed → fallback_local).
F  — Local fallback after remote exception (remote raised → fallback_local).
G  — No-target-or-envelope path → fallback_local.
H  — Blocked mode returns failure result, not local execution.
I  — select_dispatch_mode: force_remote without target → local fallback reason.
J  — select_dispatch_mode: policy_alignment blocked → blocked mode.
K  — select_dispatch_mode: governance execution_not_allowed → blocked.
L  — select_dispatch_target: empty registry → None (degraded path).
M  — select_dispatch_target: readiness gate fails → None.
N  — select_dispatch_target: participation gate fails → None.
O  — select_dispatch_target: all gates pass → target selected.
P  — Session truth preserved: registry unchanged after remote failure.
Q  — Abnormal path fallback_reason is non-empty and stable.
R  — Phase A sentinel strings are non-empty and contain policy keywords.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest
from core.participant_tier import ParticipantTier

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL,
        REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY,
        LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY,
        DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY,
        SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY,
        PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY,
        select_dispatch_mode,
        select_dispatch_target,
        build_source_dispatch_plan,
        orchestrate_source_runtime_dispatch,
        _select_target_from_candidates,
        _score_candidate,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState,
        register_session,
        detach_session,
        invalidate_session,
        InvalidationReason,
        list_active_sessions as _list_active_sessions,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.routes.projection import MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    import core.runtime as _core_runtime

    _CORE_RUNTIME_AVAILABLE = True
except ImportError:
    _CORE_RUNTIME_AVAILABLE = False

try:
    from contracts.source_dispatch import SourceDispatchMode, SourceDispatchResult, SourceDispatchTarget

    _SOURCE_DISPATCH_AVAILABLE = True
except ImportError:
    _SOURCE_DISPATCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness(*, registered: bool = True, routable: bool = True) -> Any:
    r = MagicMock()
    r.registered = registered
    r.routable = routable
    return r


def _make_participation(*, orchestration_eligible: bool = True) -> Any:
    p = MagicMock()
    p.orchestration_eligible = orchestration_eligible
    return p


def _make_registry_entry(*, device_id: str, session_id: str, runtime_id: str = "rt-1") -> Any:
    e = MagicMock()
    e.device_id = device_id
    e.session_id = session_id
    e.runtime_session_id = runtime_id
    e.attachment_state = RegistryEntryState.active if _REGISTRY_AVAILABLE else "active"
    return e


def _make_fake_plan(
    *,
    mode: Any,
    target_device_id: str = "device-remote",
    has_envelope: bool = True,
) -> Any:
    """Return a realistic mock plan with a proper SourceDispatchTarget."""
    fake_target = (
        SourceDispatchTarget(
            target_device_id=target_device_id,
            selection_reason="test:explicit",
        )
        if _SOURCE_DISPATCH_AVAILABLE
        else MagicMock()
    )
    fake_plan = MagicMock()
    fake_plan.mode = mode
    fake_plan.selected_target = fake_target
    fake_plan.handoff_envelope = {"envelope_id": "env-test"} if has_envelope else None
    fake_plan.dispatch_id = "disp-test"
    fake_plan.readiness_notes = []
    fake_plan.governance_snapshot = None
    fake_plan.policy_alignment = None
    fake_plan.mesh_session = None
    return fake_plan


def _make_fake_plan_no_target(*, mode: Any) -> Any:
    """Return a mock plan with no selected target."""
    fake_plan = MagicMock()
    fake_plan.mode = mode
    fake_plan.selected_target = None
    fake_plan.handoff_envelope = None
    fake_plan.dispatch_id = "disp-notarget"
    fake_plan.readiness_notes = []
    fake_plan.governance_snapshot = None
    fake_plan.policy_alignment = None
    fake_plan.mesh_session = None
    return fake_plan


# ---------------------------------------------------------------------------
# Group A — Orchestrator: all PR-25 sentinels present
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="source_dispatch_orchestrator not available",
)


class TestGroupA_PR25SentinelsPresent:
    def test_a1_main_sentinel_is_string(self):
        assert isinstance(MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL, str)
        assert MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL

    def test_a2_remote_blocks_local_policy_is_string(self):
        assert isinstance(REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY, str)
        assert REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY

    def test_a3_local_fallback_policy_is_string(self):
        assert isinstance(LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY, str)
        assert LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY

    def test_a4_session_truth_policy_is_string(self):
        assert isinstance(
            DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY, str
        )
        assert DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY

    def test_a5_degraded_fallback_policy_is_string(self):
        assert isinstance(
            SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY, str
        )
        assert SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY

    def test_a6_phase_a_acceptance_policy_is_string(self):
        assert isinstance(PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY, str)
        assert PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY

    def test_a7_main_sentinel_contains_pr25_package_marker(self):
        assert "package=25" in MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL

    def test_a8_all_policies_contain_pr25_marker(self):
        for policy in [
            REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY,
            LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY,
            DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY,
            SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY,
            PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY,
        ]:
            assert "PR25" in policy, f"Missing PR25 marker in: {policy[:60]}"


# ---------------------------------------------------------------------------
# Group B — Projection sentinel
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection not available")
class TestGroupB_ProjectionSentinel:
    def test_b1_projection_sentinel_is_string(self):
        assert isinstance(MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25, str)

    def test_b2_projection_sentinel_is_not_unavailable(self):
        assert "UNAVAILABLE" not in MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25

    def test_b3_projection_sentinel_contains_v1(self):
        assert "_V1" in MAINLINE_ABNORMAL_PATH_MATRIX_PHASE_A_ALIGNED_PR25


# ---------------------------------------------------------------------------
# Group C — core.runtime re-exports
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CORE_RUNTIME_AVAILABLE, reason="core.runtime not available")
class TestGroupC_CoreRuntimeReexports:
    def test_c1_main_sentinel(self):
        assert hasattr(_core_runtime, "MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL")
        assert _core_runtime.MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL

    def test_c2_remote_blocks_local_policy(self):
        assert hasattr(
            _core_runtime, "REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY"
        )

    def test_c3_local_fallback_policy(self):
        assert hasattr(
            _core_runtime, "LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY"
        )

    def test_c4_session_truth_policy(self):
        assert hasattr(
            _core_runtime,
            "DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY",
        )

    def test_c5_degraded_fallback_policy(self):
        assert hasattr(
            _core_runtime,
            "SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY",
        )

    def test_c6_phase_a_policy(self):
        assert hasattr(_core_runtime, "PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY")


# ---------------------------------------------------------------------------
# Group D — Remote task blocks local loop
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupD_RemoteTaskBlocksLocalLoop:
    """When remote handoff succeeds, local execution must NOT be attempted."""

    def test_d1_remote_success_no_local_execution(self):
        """orchestrate: when remote succeeds, exec path stays remote_handoff."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                return_value={"success": True, "action_taken": "remote_handoff"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            ) as mock_local,
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace-d1",
                task_id="task-d1",
                target_device_id="device-remote",
            )

            # Local execution must NOT have been called
            mock_local.assert_not_called()
            assert result is not None

    def test_d2_remote_handoff_mode_does_not_run_local_if_no_success_flag_set(self):
        """When remote_handoff mode with no target/envelope, result is fallback_local."""
        with patch(
            "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
            return_value=_make_fake_plan_no_target(mode=SourceDispatchMode.remote_handoff),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace-d2",
                task_id="task-d2",
            )
            assert result is not None
            # effective_mode should be fallback_local
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            mode_val = result_dict.get("mode", "")
            assert mode_val in ("fallback_local", "local", "unknown"), (
                f"Expected fallback path, got mode={mode_val}"
            )


# ---------------------------------------------------------------------------
# Group E — Local fallback after remote failure (remote returned failure)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupE_LocalFallbackAfterRemoteFailure:
    def test_e1_remote_handoff_failure_triggers_fallback_local(self):
        """When remote handoff returns success=False, result mode is fallback_local."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                return_value={"success": False, "skipped_reason": "bridge_unavailable"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback_exec"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace-e1",
                task_id="task-e1",
                target_device_id="device-remote",
            )

            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            mode_val = result_dict.get("mode", "")
            errors = result_dict.get("errors", [])

            assert mode_val == "fallback_local", (
                f"Expected fallback_local, got {mode_val}"
            )
            assert any("remote_handoff_failed" in str(e) for e in errors), (
                f"Expected remote_handoff_failed in errors, got {errors}"
            )

    def test_e2_remote_failure_errors_list_is_non_empty(self):
        """Fallback result must carry at least one error entry recording the failure."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                return_value={"success": False, "skipped_reason": "timeout"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(trace_id="trace-e2")
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            errors = result_dict.get("errors", [])
            assert len(errors) > 0, "errors list must be non-empty after remote failure"

    def test_e3_decision_reason_identifies_remote_failure(self):
        """decision_reason must contain 'remote_handoff_failed' for traceability."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                return_value={"success": False, "skipped_reason": "refused"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(trace_id="trace-e3")
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            reason = result_dict.get("decision_reason", "") or ""
            assert "remote_handoff_failed" in reason or "fallback_local" in reason, (
                f"decision_reason must identify remote failure: {reason}"
            )


# ---------------------------------------------------------------------------
# Group F — Local fallback after remote exception
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupF_LocalFallbackAfterRemoteException:
    def test_f1_remote_exception_triggers_fallback_local(self):
        """When remote handoff raises an exception, result mode is fallback_local."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                side_effect=RuntimeError("bridge crashed"),
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback_exec"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(trace_id="trace-f1")
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            mode_val = result_dict.get("mode", "")
            errors = result_dict.get("errors", [])
            assert mode_val == "fallback_local", f"Expected fallback_local, got {mode_val}"
            assert any("remote_handoff_error" in str(e) for e in errors), (
                f"Expected remote_handoff_error in errors: {errors}"
            )


# ---------------------------------------------------------------------------
# Group G — No-target-or-envelope path → fallback_local
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupG_NoTargetOrEnvelope:
    def test_g1_no_target_no_envelope_produces_fallback_local(self):
        """remote_handoff with no target AND no envelope falls back to local."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan_no_target(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            result = orchestrate_source_runtime_dispatch(trace_id="trace-g1")
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            mode_val = result_dict.get("mode", "")
            errors = result_dict.get("errors", [])

            assert mode_val in ("fallback_local", "local"), (
                f"Expected fallback, got {mode_val}"
            )
            assert any("no_target_or_envelope" in str(e) for e in errors), (
                f"Expected no_target_or_envelope in errors: {errors}"
            )


# ---------------------------------------------------------------------------
# Group H — Blocked mode
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupH_BlockedMode:
    def test_h1_blocked_mode_returns_failure(self):
        """When mode=blocked, orchestrate returns success=False."""
        with patch(
            "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
            return_value=_make_fake_plan_no_target(mode=SourceDispatchMode.blocked),
        ) as mock_plan:
            # Override readiness_notes on the returned mock
            mock_plan.return_value.readiness_notes = ["policy_alignment:blocked"]
            result = orchestrate_source_runtime_dispatch(trace_id="trace-h1")
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
            assert result_dict.get("success") is False, (
                f"Blocked mode must produce success=False: {result_dict}"
            )

    def test_h2_blocked_mode_does_not_run_local_execution(self):
        """Blocked mode must short-circuit before reaching local execution."""
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
            ) as mock_local,
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan_no_target(mode=SourceDispatchMode.blocked),
            ),
        ):
            orchestrate_source_runtime_dispatch(trace_id="trace-h2")
            mock_local.assert_not_called()


# ---------------------------------------------------------------------------
# Group I — select_dispatch_mode abnormal paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupI_SelectDispatchModeAbnormalPaths:
    def test_i1_force_remote_without_target_falls_back_to_local(self):
        """force_remote=True without target_device_id → local with fallback reason."""
        mode, reason = select_dispatch_mode(force_remote=True, target_device_id=None)
        assert mode == SourceDispatchMode.local
        assert "fallback_local" in reason

    def test_i2_policy_alignment_blocked_returns_blocked(self):
        """policy_alignment with blocked=True → blocked mode."""
        mode, reason = select_dispatch_mode(
            policy_alignment={"blocked": True},
        )
        assert mode == SourceDispatchMode.blocked
        assert "blocked" in reason

    def test_i3_governance_execution_not_allowed_returns_blocked(self):
        """governance snapshot with execution_allowed=False → blocked mode."""
        mode, reason = select_dispatch_mode(
            governance_snapshot={"execution_allowed": False},
        )
        assert mode == SourceDispatchMode.blocked
        assert "execution_not_allowed" in reason or "blocked" in reason

    def test_i4_policy_local_not_allowed_no_target_returns_blocked(self):
        """policy alignment can_execute_locally=False + no target → blocked."""
        mode, reason = select_dispatch_mode(
            policy_alignment={"alignment_hints": {"can_execute_locally": False}},
            target_device_id=None,
        )
        assert mode == SourceDispatchMode.blocked

    def test_i5_policy_local_not_allowed_with_target_returns_remote(self):
        """policy alignment can_execute_locally=False + target → remote_handoff."""
        mode, reason = select_dispatch_mode(
            policy_alignment={"alignment_hints": {"can_execute_locally": False}},
            target_device_id="device-x",
        )
        assert mode == SourceDispatchMode.remote_handoff

    def test_i6_control_only_posture_no_target_returns_blocked(self):
        """source_runtime_posture=control_only without target → blocked."""
        mode, reason = select_dispatch_mode(
            source_runtime_posture="control_only",
            target_device_id=None,
        )
        assert mode == SourceDispatchMode.blocked
        assert "ineligible" in reason or "control_only" in reason

    def test_i7_control_only_posture_with_target_returns_remote(self):
        """source_runtime_posture=control_only with target → remote_handoff."""
        mode, reason = select_dispatch_mode(
            source_runtime_posture="control_only",
            target_device_id="device-y",
        )
        assert mode == SourceDispatchMode.remote_handoff

    def test_i8_default_fallback_returns_local(self):
        """No constraints → local mode."""
        mode, reason = select_dispatch_mode()
        assert mode == SourceDispatchMode.local
        assert reason  # must be non-empty


# ---------------------------------------------------------------------------
# Group J — Governance blocked mode (via select_dispatch_mode)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupJ_GovernanceBlockedMode:
    def test_j1_governance_blocked_mode_stable(self):
        """select_dispatch_mode always returns blocked when governance says no."""
        for _ in range(3):
            mode, reason = select_dispatch_mode(
                governance_snapshot={"execution_allowed": False},
            )
            assert mode == SourceDispatchMode.blocked
            assert reason  # must be non-empty and stable


# ---------------------------------------------------------------------------
# Group K — select_dispatch_mode: governance mode not blocking
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator or source_dispatch not available",
)
class TestGroupK_GovernanceAllowed:
    def test_k1_governance_allowed_proceeds_normally(self):
        """governance snapshot with execution_allowed=True does not block."""
        mode, reason = select_dispatch_mode(
            governance_snapshot={"execution_allowed": True},
        )
        assert mode != SourceDispatchMode.blocked


# ---------------------------------------------------------------------------
# Group L — select_dispatch_target: empty registry → None
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="orchestrator not available",
)
class TestGroupL_EmptyRegistry:
    def test_l1_no_active_sessions_returns_none(self):
        """With an empty registry, select_dispatch_target returns None."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={},
            participation_inputs={},
            reuse_inputs={},
        )
        assert result is None

    def test_l2_registry_list_raises_returns_none(self):
        """When list_active_sessions raises, select_dispatch_target returns None."""
        with patch(
            "core.attached_runtime_session_registry.list_active_sessions",
            side_effect=RuntimeError("registry down"),
        ):
            result = select_dispatch_target(
                readiness_inputs={},
                participation_inputs={},
                reuse_inputs={},
            )
        assert result is None


# ---------------------------------------------------------------------------
# Group M — select_dispatch_target: readiness gate fails → None
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="orchestrator not available",
)
class TestGroupM_ReadinessGateFails:
    def test_m1_readiness_unavailable_rejects_candidate(self):
        """Candidate with no readiness entry is rejected; None returned."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-m1", session_id="sess-m1", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-m1": None},
            participation_inputs={"dev-m1": _make_participation()},
            reuse_inputs={"dev-m1": False},
        )
        assert result is None, "Candidate with None readiness must be rejected"

    def test_m2_readiness_not_registered_rejects_candidate(self):
        """Candidate that fails the registered gate is rejected."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-m2", session_id="sess-m2", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-m2": _make_readiness(registered=False)},
            participation_inputs={"dev-m2": _make_participation()},
            reuse_inputs={"dev-m2": False},
        )
        assert result is None, "Candidate with not_registered readiness must be rejected"

    def test_m3_readiness_not_routable_rejects_candidate(self):
        """Candidate that fails the routable gate is rejected."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-m3", session_id="sess-m3", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-m3": _make_readiness(routable=False)},
            participation_inputs={"dev-m3": _make_participation()},
            reuse_inputs={"dev-m3": False},
        )
        assert result is None, "Candidate with not_routable readiness must be rejected"


# ---------------------------------------------------------------------------
# Group N — select_dispatch_target: participation gate fails → None
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="orchestrator not available",
)
class TestGroupN_ParticipationGateFails:
    def test_n1_participation_unavailable_rejects_candidate(self):
        """Candidate with no participation entry is rejected."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-n1", session_id="sess-n1", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-n1": _make_readiness()},
            participation_inputs={"dev-n1": None},
            reuse_inputs={"dev-n1": False},
        )
        assert result is None, "Candidate with None participation must be rejected"

    def test_n2_participation_not_eligible_rejects_candidate(self):
        """Candidate that fails orchestration_eligible gate is rejected."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-n2", session_id="sess-n2", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-n2": _make_readiness()},
            participation_inputs={"dev-n2": _make_participation(orchestration_eligible=False)},
            reuse_inputs={"dev-n2": False},
        )
        assert result is None, "Candidate with orchestration_eligible=False must be rejected"


# ---------------------------------------------------------------------------
# Group O — select_dispatch_target: all gates pass → target selected
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="orchestrator not available",
)
class TestGroupO_TargetSelected:
    def test_o1_all_gates_pass_returns_target(self):
        """When readiness + participation pass, a target is returned."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-o1", session_id="sess-o1", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-o1": _make_readiness()},
            participation_inputs={"dev-o1": _make_participation()},
            reuse_inputs={"dev-o1": False},
        )
        assert result is not None, "All-pass candidate must produce a target"
        assert result.target_device_id == "dev-o1"

    def test_o2_target_has_stable_selection_reason(self):
        """Selected target must carry a non-empty selection_reason."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-o2", session_id="sess-o2", registry=reg)
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-o2": _make_readiness()},
            participation_inputs={"dev-o2": _make_participation()},
            reuse_inputs={"dev-o2": False},
        )
        assert result is not None
        assert result.selection_reason, "selection_reason must be non-empty"

    def test_o3_reuse_eligible_contributes_to_score(self):
        """reuse_eligible=True candidate is preferred over non-reuse candidate."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-o3a", session_id="sess-o3a", registry=reg)
        register_session("dev-o3b", session_id="sess-o3b", registry=reg)

        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={
                "dev-o3a": _make_readiness(),
                "dev-o3b": _make_readiness(),
            },
            participation_inputs={
                "dev-o3a": _make_participation(),
                "dev-o3b": _make_participation(),
            },
            reuse_inputs={"dev-o3a": True, "dev-o3b": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-o3a", (
            "Reuse-eligible candidate must win over non-reuse equal candidate"
        )


# ---------------------------------------------------------------------------
# Group P — Session truth preserved: registry unchanged after remote failure
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE and _SOURCE_DISPATCH_AVAILABLE),
    reason="orchestrator, registry, or source_dispatch not available",
)
class TestGroupP_SessionTruthPreserved:
    """The registry must not be mutated as a side-effect of remote dispatch failures."""

    def test_p1_registry_active_sessions_unchanged_after_remote_failure(self):
        """After a remote handoff failure, registry active sessions are unchanged."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        # Register a session (correct signature: device_id, session_id=, no runtime_session_id)
        register_session("dev-p1", session_id="sess-p1", registry=reg)
        sessions_before = _list_active_sessions(registry=reg)
        assert len(sessions_before) == 1

        # Simulate a remote dispatch failure via the orchestrate path
        with (
            patch(
                "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
                return_value={"success": False, "skipped_reason": "timeout"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "local_fallback"},
            ),
            patch(
                "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
                return_value=_make_fake_plan(mode=SourceDispatchMode.remote_handoff),
            ),
        ):
            orchestrate_source_runtime_dispatch(trace_id="trace-p1")

        sessions_after = _list_active_sessions(registry=reg)
        assert len(sessions_after) == 1, (
            "Registry active sessions must be unchanged after remote failure"
        )
        assert sessions_after[0].session_id == "sess-p1"

    def test_p2_registry_state_stable_after_blocked_dispatch(self):
        """After a blocked dispatch, registry active sessions are unchanged."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry not available")
        reg = AttachedSessionRegistry()
        register_session("dev-p2", session_id="sess-p2", registry=reg)
        sessions_before = _list_active_sessions(registry=reg)

        blocked_plan = _make_fake_plan_no_target(mode=SourceDispatchMode.blocked)
        blocked_plan.readiness_notes = ["blocked"]

        with patch(
            "core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan",
            return_value=blocked_plan,
        ):
            orchestrate_source_runtime_dispatch(trace_id="trace-p2")

        sessions_after = _list_active_sessions(registry=reg)
        assert len(sessions_after) == len(sessions_before), (
            "Registry must not change after blocked dispatch"
        )


# ---------------------------------------------------------------------------
# Group Q — Abnormal path fallback_reason is non-empty and stable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE,
    reason="orchestrator not available",
)
class TestGroupQ_FallbackReasonStability:
    def test_q1_score_candidate_readiness_unavailable_stable_reason(self):
        """_score_candidate: None readiness → score=0, stable rejection reason."""
        score, reason = _score_candidate(
            "sess-q1", "dev-q1",
            readiness=None,
            participation=_make_participation(),
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "readiness:unavailable"

    def test_q2_score_candidate_participation_unavailable_stable_reason(self):
        """_score_candidate: None participation → score=0, stable rejection reason."""
        score, reason = _score_candidate(
            "sess-q2", "dev-q2",
            readiness=_make_readiness(),
            participation=None,
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "participation:unavailable"

    def test_q3_score_candidate_not_registered_stable_reason(self):
        """_score_candidate: registered=False → score=0, stable reason."""
        score, reason = _score_candidate(
            "sess-q3", "dev-q3",
            readiness=_make_readiness(registered=False),
            participation=_make_participation(),
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "readiness:not_registered"

    def test_q4_score_candidate_not_routable_stable_reason(self):
        """_score_candidate: routable=False → score=0, stable reason."""
        score, reason = _score_candidate(
            "sess-q4", "dev-q4",
            readiness=_make_readiness(routable=False),
            participation=_make_participation(),
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "readiness:not_routable"

    def test_q5_score_candidate_not_eligible_stable_reason(self):
        """_score_candidate: orchestration_eligible=False → stable reason."""
        score, reason = _score_candidate(
            "sess-q5", "dev-q5",
            readiness=_make_readiness(),
            participation=_make_participation(orchestration_eligible=False),
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "participation:not_orchestration_eligible"

    def test_q5b_score_candidate_command_endpoint_rejected(self):
        """_score_candidate: command endpoint tier cannot be runtime-dispatch target."""
        participation = _make_participation(orchestration_eligible=True)
        participation.participant_tier = ParticipantTier.COMMAND_ENDPOINT.value
        score, reason = _score_candidate(
            "sess-q5b", "dev-q5b",
            readiness=_make_readiness(),
            participation=participation,
            reuse_eligible=False,
        )
        assert score == 0
        assert reason == "participation:tier_not_runtime_dispatchable:COMMAND_ENDPOINT"

    def test_q6_score_candidate_all_pass_empty_reason(self):
        """_score_candidate: all pass → non-zero score, empty reason."""
        score, reason = _score_candidate(
            "sess-q6", "dev-q6",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
        )
        assert score > 0
        assert reason == ""

    def test_q7_score_candidate_reuse_eligible_increases_score(self):
        """_score_candidate: reuse_eligible=True → higher score than without."""
        score_no_reuse, _ = _score_candidate(
            "sess-q7a", "dev-q7",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
        )
        score_with_reuse, _ = _score_candidate(
            "sess-q7b", "dev-q7",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=True,
        )
        assert score_with_reuse > score_no_reuse


# ---------------------------------------------------------------------------
# Group R — Phase A sentinel string quality checks
# ---------------------------------------------------------------------------


class TestGroupR_PhaseASentinelQuality:
    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_r1_phase_a_policy_contains_remote_blocks_local(self):
        """Phase A policy documents the remote-blocks-local abnormal path."""
        assert "remote" in PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY.lower()
        assert "local" in PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY.lower()

    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_r2_phase_a_policy_contains_fallback(self):
        """Phase A policy documents the local-fallback abnormal path."""
        assert "fallback" in PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY.lower()

    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_r3_phase_a_policy_contains_session_truth(self):
        """Phase A policy documents session truth consistency."""
        assert "session" in PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY.lower()

    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_r4_main_sentinel_contains_delegated(self):
        """Main PR25 sentinel references delegated execution path."""
        assert "delegated" in MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL.lower()

    @pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator not available")
    def test_r5_all_policies_are_unique(self):
        """All PR-25 policy strings must be unique."""
        policies = [
            MAINLINE_ABNORMAL_PATH_MATRIX_CLOSED_PR25_SENTINEL,
            REMOTE_TASK_BLOCKS_LOCAL_LOOP_ABNORMAL_PATH_PR25_POLICY,
            LOCAL_FALLBACK_AFTER_REMOTE_FAILURE_ABNORMAL_PATH_PR25_POLICY,
            DELEGATED_EXECUTION_FAILURE_SESSION_TRUTH_IS_PRESERVED_PR25_POLICY,
            SELECTION_FALLBACK_UNDER_DEGRADED_CONDITIONS_IS_STABLE_PR25_POLICY,
            PHASE_A_ACCEPTANCE_ABNORMAL_PATH_PR25_POLICY,
        ]
        assert len(policies) == len(set(policies)), "All PR-25 policy strings must be unique"
