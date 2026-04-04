"""tests/test_pr2_posture_aware_dispatch.py
=============================================
Tests for PR-2 (post-533 dual-repo runtime host unification, MAIN repo side):
Make source runtime posture drive OpenClawd/main-runtime dispatch decisions.

Coverage groups
---------------
A  — Authority and policy sentinel presence.
B  — SourceExecutionEligibility dataclass: construction, to_dict(), properties.
C  — resolve_posture_for_eligibility: normalisation rules.
D  — check_source_execution_eligibility: control_only ineligible, join_runtime eligible.
E  — is_source_eligible_for_local_execution: convenience shorthand.
F  — select_dispatch_mode: control_only with remote target → remote_handoff.
G  — select_dispatch_mode: control_only without remote target → blocked.
H  — select_dispatch_mode: join_runtime → normal dispatch (local or remote).
I  — select_dispatch_mode: force_local bypasses posture gate.
J  — build_source_dispatch_plan: control_only + no target → blocked plan.
K  — build_source_dispatch_plan: control_only + target → remote_handoff plan.
L  — build_source_dispatch_plan: join_runtime + no target → local plan.
M  — orchestrate_source_runtime_dispatch: control_only → blocked result.
N  — orchestrate_source_runtime_dispatch: join_runtime → attempts local.
O  — SourceDispatchOrchestrator.dispatch: passes posture to orchestrator.
P  — SourceDispatchOrchestrator.plan: passes posture to plan builder.
Q  — DeviceRouter sentinel: DEVICE_ROUTER_POSTURE_AWARE_DISPATCH present.
R  — core.runtime re-exports: eligibility symbols accessible from core.runtime.
S  — Backwards safety: existing callers without posture get control_only default.
T  — Result posture field: posture propagates through to SourceDispatchResult.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy_alignment(
    blocked: bool = False,
    can_execute_locally: bool = True,
    can_expand_cross_device: bool = False,
) -> dict:
    return {
        "alignment_id": str(uuid.uuid4()),
        "aligned": not blocked,
        "blocked": blocked,
        "degraded": False,
        "alignment_hints": {
            "can_execute_locally": can_execute_locally,
            "can_expand_cross_device": can_expand_cross_device,
            "is_blocked": blocked,
            "preferred_domain": None,
        },
        "timestamp": 1700000000.0,
    }


def _make_governance_snapshot(execution_allowed: bool = True) -> dict:
    return {
        "snapshot_id": str(uuid.uuid4()),
        "execution_allowed": execution_allowed,
        "timestamp": 1700000000.0,
    }


# ---------------------------------------------------------------------------
# A — Authority and policy sentinel presence
# ---------------------------------------------------------------------------


class TestSentinelPresence:
    """Group A: sentinel strings are present and non-empty."""

    def test_source_dispatch_posture_aware_authority(self):
        from core.source_execution_eligibility import SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY
        assert isinstance(SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY, str)
        assert len(SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY) > 10

    def test_control_only_ineligible_policy(self):
        from core.source_execution_eligibility import CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY
        assert isinstance(CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY, str)
        assert "control_only" in CONTROL_ONLY_SOURCE_INELIGIBLE_FOR_LOCAL_EXECUTION_POLICY.lower()

    def test_join_runtime_eligible_policy(self):
        from core.source_execution_eligibility import JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY
        assert isinstance(JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY, str)
        assert "join_runtime" in JOIN_RUNTIME_SOURCE_ELIGIBLE_FOR_LOCAL_EXECUTION_POLICY.lower()

    def test_posture_gated_local_execution_policy(self):
        from core.source_execution_eligibility import POSTURE_GATED_LOCAL_EXECUTION_POLICY
        assert isinstance(POSTURE_GATED_LOCAL_EXECUTION_POLICY, str)
        assert len(POSTURE_GATED_LOCAL_EXECUTION_POLICY) > 10

    def test_posture_aware_dispatch_integrated_sentinel(self):
        from core.source_execution_eligibility import POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL
        assert isinstance(POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL, str)
        assert "PR-2" in POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL


# ---------------------------------------------------------------------------
# B — SourceExecutionEligibility dataclass
# ---------------------------------------------------------------------------


class TestSourceExecutionEligibility:
    """Group B: SourceExecutionEligibility construction and properties."""

    def test_construction_eligible(self):
        from core.source_execution_eligibility import SourceExecutionEligibility
        e = SourceExecutionEligibility(eligible=True, posture="join_runtime", reason="test")
        assert e.eligible is True
        assert e.posture == "join_runtime"
        assert e.reason == "test"

    def test_construction_ineligible(self):
        from core.source_execution_eligibility import SourceExecutionEligibility
        e = SourceExecutionEligibility(eligible=False, posture="control_only", reason="blocked")
        assert e.eligible is False
        assert e.posture == "control_only"

    def test_frozen_dataclass(self):
        from core.source_execution_eligibility import SourceExecutionEligibility
        e = SourceExecutionEligibility(eligible=True, posture="join_runtime", reason="r")
        with pytest.raises((AttributeError, TypeError)):
            e.eligible = False  # type: ignore[misc]

    def test_to_dict_keys(self):
        from core.source_execution_eligibility import SourceExecutionEligibility
        e = SourceExecutionEligibility(eligible=False, posture="control_only", reason="r")
        d = e.to_dict()
        assert "eligible" in d
        assert "posture" in d
        assert "reason" in d
        assert "authority" in d
        assert d["eligible"] is False
        assert d["posture"] == "control_only"

    def test_to_dict_authority_matches_sentinel(self):
        from core.source_execution_eligibility import (
            SourceExecutionEligibility,
            SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY,
        )
        e = SourceExecutionEligibility(eligible=True, posture="join_runtime", reason="r")
        assert e.to_dict()["authority"] == SOURCE_DISPATCH_POSTURE_AWARE_AUTHORITY


# ---------------------------------------------------------------------------
# C — resolve_posture_for_eligibility
# ---------------------------------------------------------------------------


class TestResolvePostureForEligibility:
    """Group C: normalisation helper behaviour."""

    def test_none_resolves_to_control_only(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility(None) == "control_only"

    def test_empty_resolves_to_control_only(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("") == "control_only"

    def test_control_only_passthrough(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("control_only") == "control_only"

    def test_join_runtime_passthrough(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("join_runtime") == "join_runtime"

    def test_unknown_resolves_to_control_only(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("executor") == "control_only"
        assert resolve_posture_for_eligibility("UNKNOWN") == "control_only"

    def test_case_insensitive(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("JOIN_RUNTIME") == "join_runtime"
        assert resolve_posture_for_eligibility("CONTROL_ONLY") == "control_only"

    def test_whitespace_stripped(self):
        from core.source_execution_eligibility import resolve_posture_for_eligibility
        assert resolve_posture_for_eligibility("  join_runtime  ") == "join_runtime"


# ---------------------------------------------------------------------------
# D — check_source_execution_eligibility
# ---------------------------------------------------------------------------


class TestCheckSourceExecutionEligibility:
    """Group D: primary eligibility API."""

    def test_control_only_is_ineligible(self):
        from core.source_execution_eligibility import check_source_execution_eligibility
        result = check_source_execution_eligibility("control_only")
        assert result.eligible is False
        assert result.posture == "control_only"
        assert "control_only" in result.reason

    def test_join_runtime_is_eligible(self):
        from core.source_execution_eligibility import check_source_execution_eligibility
        result = check_source_execution_eligibility("join_runtime")
        assert result.eligible is True
        assert result.posture == "join_runtime"
        assert "join_runtime" in result.reason

    def test_none_defaults_to_ineligible(self):
        from core.source_execution_eligibility import check_source_execution_eligibility
        result = check_source_execution_eligibility(None)
        assert result.eligible is False
        assert result.posture == "control_only"

    def test_unknown_defaults_to_ineligible(self):
        from core.source_execution_eligibility import check_source_execution_eligibility
        result = check_source_execution_eligibility("observer")
        assert result.eligible is False

    def test_returns_source_execution_eligibility_type(self):
        from core.source_execution_eligibility import (
            check_source_execution_eligibility,
            SourceExecutionEligibility,
        )
        result = check_source_execution_eligibility("join_runtime")
        assert isinstance(result, SourceExecutionEligibility)

    def test_to_dict_round_trip(self):
        from core.source_execution_eligibility import check_source_execution_eligibility
        result = check_source_execution_eligibility("join_runtime")
        d = result.to_dict()
        assert d["eligible"] is True
        assert d["posture"] == "join_runtime"


# ---------------------------------------------------------------------------
# E — is_source_eligible_for_local_execution
# ---------------------------------------------------------------------------


class TestIsSourceEligibleForLocalExecution:
    """Group E: convenience bool shorthand."""

    def test_control_only_returns_false(self):
        from core.source_execution_eligibility import is_source_eligible_for_local_execution
        assert is_source_eligible_for_local_execution("control_only") is False

    def test_join_runtime_returns_true(self):
        from core.source_execution_eligibility import is_source_eligible_for_local_execution
        assert is_source_eligible_for_local_execution("join_runtime") is True

    def test_none_returns_false(self):
        from core.source_execution_eligibility import is_source_eligible_for_local_execution
        assert is_source_eligible_for_local_execution(None) is False

    def test_unknown_returns_false(self):
        from core.source_execution_eligibility import is_source_eligible_for_local_execution
        assert is_source_eligible_for_local_execution("something_else") is False


# ---------------------------------------------------------------------------
# F — select_dispatch_mode: control_only + remote target → remote_handoff
# ---------------------------------------------------------------------------


class TestSelectDispatchModeControlOnlyWithTarget:
    """Group F: control_only posture with a remote target redirects to remote_handoff."""

    def test_control_only_with_target_returns_remote_handoff(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        mode, reason = select_dispatch_mode(
            target_device_id="device_android_01",
            source_runtime_posture="control_only",
        )
        from contracts.source_dispatch import SourceDispatchMode
        assert mode == SourceDispatchMode.remote_handoff

    def test_control_only_with_target_reason_mentions_posture(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        _, reason = select_dispatch_mode(
            target_device_id="device_android_01",
            source_runtime_posture="control_only",
        )
        assert "posture" in reason
        assert "control_only" in reason

    def test_control_only_overrides_default_local_when_target_present(self):
        """Without posture gate, explicit target_device_id also returns remote_handoff."""
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode
        # With posture=control_only and target: remote_handoff
        mode_with, _ = select_dispatch_mode(
            target_device_id="device_01",
            source_runtime_posture="control_only",
        )
        assert mode_with == SourceDispatchMode.remote_handoff


# ---------------------------------------------------------------------------
# G — select_dispatch_mode: control_only without remote target → blocked
# ---------------------------------------------------------------------------


class TestSelectDispatchModeControlOnlyNoTarget:
    """Group G: control_only posture without any remote target produces blocked."""

    def test_control_only_no_target_returns_blocked(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        # No target, no policy overrides, no mesh — default would be local.
        # With posture=control_only, must become blocked.
        mode, reason = select_dispatch_mode(
            source_runtime_posture="control_only",
        )
        assert mode == SourceDispatchMode.blocked

    def test_control_only_no_target_reason_mentions_ineligible(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        _, reason = select_dispatch_mode(
            source_runtime_posture="control_only",
        )
        assert "ineligible" in reason or "control_only" in reason

    def test_control_only_no_target_reason_mentions_no_remote(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        _, reason = select_dispatch_mode(
            source_runtime_posture="control_only",
        )
        assert "no_remote" in reason or "blocked" in reason.lower()


# ---------------------------------------------------------------------------
# H — select_dispatch_mode: join_runtime → normal dispatch
# ---------------------------------------------------------------------------


class TestSelectDispatchModeJoinRuntime:
    """Group H: join_runtime posture does not block local or remote dispatch."""

    def test_join_runtime_no_target_returns_local(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(
            source_runtime_posture="join_runtime",
        )
        assert mode == SourceDispatchMode.local

    def test_join_runtime_no_target_reason_default_local(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        _, reason = select_dispatch_mode(
            source_runtime_posture="join_runtime",
        )
        assert "local" in reason

    def test_join_runtime_with_target_returns_remote_handoff(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(
            target_device_id="device_01",
            source_runtime_posture="join_runtime",
        )
        assert mode == SourceDispatchMode.remote_handoff

    def test_none_posture_preserves_default_local_behavior(self):
        """None posture = no posture gate applied; default_local is preserved."""
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        # Without explicit posture, the pre-PR-2 default_local path applies.
        mode, _ = select_dispatch_mode(source_runtime_posture=None)
        assert mode == SourceDispatchMode.local


# ---------------------------------------------------------------------------
# I — select_dispatch_mode: force_local bypasses posture gate
# ---------------------------------------------------------------------------


class TestSelectDispatchModeForceLocalBypassesPosture:
    """Group I: force_local overrides posture check for local execution."""

    def test_force_local_with_control_only_returns_local(self):
        """force_local is an explicit canonical exception — bypasses posture gate."""
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, reason = select_dispatch_mode(
            force_local=True,
            source_runtime_posture="control_only",
        )
        assert mode == SourceDispatchMode.local

    def test_force_local_reason_mentions_force_local(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        _, reason = select_dispatch_mode(
            force_local=True,
            source_runtime_posture="control_only",
        )
        assert "force_local" in reason


# ---------------------------------------------------------------------------
# J — build_source_dispatch_plan: control_only + no target → blocked
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanControlOnlyNoTarget:
    """Group J: control_only with no remote target produces a blocked plan."""

    def test_plan_is_blocked_when_control_only_no_target(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_j01",
                task_id="task_j01",
                source_runtime_posture="control_only",
            )
        assert plan.mode == SourceDispatchMode.blocked

    def test_plan_not_ready_when_control_only_no_target(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_j02",
                source_runtime_posture="control_only",
            )
        assert plan.ready is False

    def test_plan_readiness_notes_not_empty_when_blocked(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_j03",
                source_runtime_posture="control_only",
            )
        if plan.mode == SourceDispatchMode.blocked:
            assert plan.readiness_notes


# ---------------------------------------------------------------------------
# K — build_source_dispatch_plan: control_only + target → remote_handoff
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanControlOnlyWithTarget:
    """Group K: control_only with an explicit target produces remote_handoff plan."""

    def test_plan_is_remote_handoff_when_control_only_with_target(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_k01",
                target_device_id="android_device_01",
                source_runtime_posture="control_only",
            )
        assert plan.mode == SourceDispatchMode.remote_handoff


# ---------------------------------------------------------------------------
# L — build_source_dispatch_plan: join_runtime + no target → local
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanJoinRuntime:
    """Group L: join_runtime without a target produces a local plan."""

    def test_plan_is_local_when_join_runtime_no_target(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_l01",
                source_runtime_posture="join_runtime",
            )
        assert plan.mode == SourceDispatchMode.local

    def test_plan_is_ready_when_join_runtime_local(self):
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(
                trace_id="trace_l02",
                source_runtime_posture="join_runtime",
            )
        assert plan.ready is True


# ---------------------------------------------------------------------------
# M — orchestrate_source_runtime_dispatch: control_only → blocked result
# ---------------------------------------------------------------------------


class TestOrchestrateControlOnlyBlocked:
    """Group M: orchestrate with control_only and no target produces blocked result."""

    def test_result_is_not_successful_when_control_only_no_target(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_m01",
                task_id="task_m01",
                source_runtime_posture="control_only",
            )
        assert result.success is False

    def test_result_mode_is_blocked_when_control_only_no_target(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_m02",
                source_runtime_posture="control_only",
            )
        assert result.mode == SourceDispatchMode.blocked

    def test_result_has_errors_when_control_only_blocked(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_m03",
                source_runtime_posture="control_only",
            )
        assert result.errors

    def test_local_execution_not_called_when_control_only(self):
        """_try_run_local_execution must NOT be invoked when posture is control_only."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution"
            ) as mock_local,
        ):
            orchestrate_source_runtime_dispatch(
                trace_id="trace_m04",
                source_runtime_posture="control_only",
            )
        mock_local.assert_not_called()


# ---------------------------------------------------------------------------
# N — orchestrate_source_runtime_dispatch: join_runtime → attempts local
# ---------------------------------------------------------------------------


class TestOrchestrateJoinRuntimeLocal:
    """Group N: orchestrate with join_runtime and no target attempts local execution."""

    def test_local_execution_called_when_join_runtime(self):
        """_try_run_local_execution IS called when posture is join_runtime."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        _mock_exec = MagicMock(return_value={"success": True, "action_taken": "executed"})

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                _mock_exec,
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_n01",
                source_runtime_posture="join_runtime",
            )
        _mock_exec.assert_called_once()

    def test_result_is_successful_when_join_runtime_local_succeeds(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True, "action_taken": "executed"},
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_n02",
                source_runtime_posture="join_runtime",
            )
        assert result.success is True

    def test_result_mode_is_local_when_join_runtime(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True},
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_n03",
                source_runtime_posture="join_runtime",
            )
        assert result.mode == SourceDispatchMode.local


# ---------------------------------------------------------------------------
# O — SourceDispatchOrchestrator.dispatch passes posture
# ---------------------------------------------------------------------------


class TestSourceDispatchOrchestratorDispatch:
    """Group O: orchestrator class .dispatch() accepts and propagates posture."""

    def test_dispatch_control_only_no_target_is_not_successful(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        handler = SourceDispatchOrchestrator()
        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = handler.dispatch(
                trace_id="trace_o01",
                source_runtime_posture="control_only",
            )
        assert result.success is False

    def test_dispatch_join_runtime_attempts_local(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        handler = SourceDispatchOrchestrator()
        _mock_exec = MagicMock(return_value={"success": True})
        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                _mock_exec,
            ),
        ):
            handler.dispatch(
                trace_id="trace_o02",
                source_runtime_posture="join_runtime",
            )
        _mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# P — SourceDispatchOrchestrator.plan passes posture
# ---------------------------------------------------------------------------


class TestSourceDispatchOrchestratorPlan:
    """Group P: orchestrator class .plan() accepts and propagates posture."""

    def test_plan_control_only_no_target_is_blocked(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator
        from contracts.source_dispatch import SourceDispatchMode

        handler = SourceDispatchOrchestrator()
        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = handler.plan(
                trace_id="trace_p01",
                source_runtime_posture="control_only",
            )
        assert plan.mode == SourceDispatchMode.blocked

    def test_plan_join_runtime_no_target_is_local(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator
        from contracts.source_dispatch import SourceDispatchMode

        handler = SourceDispatchOrchestrator()
        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = handler.plan(
                trace_id="trace_p02",
                source_runtime_posture="join_runtime",
            )
        assert plan.mode == SourceDispatchMode.local


# ---------------------------------------------------------------------------
# Q — DeviceRouter sentinel present
# ---------------------------------------------------------------------------


class TestDeviceRouterPostureSentinel:
    """Group Q: DEVICE_ROUTER_POSTURE_AWARE_DISPATCH sentinel is present."""

    def test_posture_aware_dispatch_sentinel_present(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_POSTURE_AWARE_DISPATCH
        assert isinstance(DEVICE_ROUTER_POSTURE_AWARE_DISPATCH, str)
        assert "PR-2" in DEVICE_ROUTER_POSTURE_AWARE_DISPATCH

    def test_posture_aware_dispatch_sentinel_mentions_control_only(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_POSTURE_AWARE_DISPATCH
        assert "control_only" in DEVICE_ROUTER_POSTURE_AWARE_DISPATCH

    def test_posture_aware_dispatch_sentinel_mentions_join_runtime(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_POSTURE_AWARE_DISPATCH
        assert "join_runtime" in DEVICE_ROUTER_POSTURE_AWARE_DISPATCH


# ---------------------------------------------------------------------------
# R — core.runtime re-exports eligibility symbols
# ---------------------------------------------------------------------------


class TestCoreRuntimeReExports:
    """Group R: eligibility symbols accessible from core.runtime."""

    def test_check_source_execution_eligibility_importable_from_core_runtime(self):
        from core.runtime import check_source_execution_eligibility
        assert callable(check_source_execution_eligibility)

    def test_is_source_eligible_importable_from_core_runtime(self):
        from core.runtime import is_source_eligible_for_local_execution
        assert callable(is_source_eligible_for_local_execution)

    def test_source_execution_eligibility_importable_from_core_runtime(self):
        from core.runtime import SourceExecutionEligibility
        e = SourceExecutionEligibility(eligible=True, posture="join_runtime", reason="r")
        assert e.eligible is True

    def test_posture_aware_sentinel_importable_from_core_runtime(self):
        from core.runtime import POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL
        assert isinstance(POSTURE_AWARE_DISPATCH_INTEGRATED_SENTINEL, str)


# ---------------------------------------------------------------------------
# S — Backwards safety: no posture → control_only default
# ---------------------------------------------------------------------------


class TestBackwardsSafetyNoPosture:
    """Group S: existing callers that don't pass posture get safe defaults."""

    def test_select_dispatch_mode_no_posture_no_target_remains_local(self):
        """No posture arg → no posture gate → pre-PR-2 default_local behavior."""
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        # Without explicit posture, the posture gate is not applied; default is local.
        mode, _ = select_dispatch_mode()
        assert mode == SourceDispatchMode.local

    def test_select_dispatch_mode_no_posture_with_target_becomes_remote_handoff(self):
        """No posture + target → remote_handoff (unchanged from pre-PR-2)."""
        from core.runtime.source_dispatch_orchestrator import select_dispatch_mode
        from contracts.source_dispatch import SourceDispatchMode

        mode, _ = select_dispatch_mode(target_device_id="dev_01")
        assert mode == SourceDispatchMode.remote_handoff

    def test_build_source_dispatch_plan_no_posture_graceful(self):
        """build_source_dispatch_plan() without posture does not raise."""
        from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
        from contracts.source_dispatch import SourceDispatchMode

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            plan = build_source_dispatch_plan(trace_id="trace_s01")
        # Without posture, default_local behavior applies
        assert plan is not None
        assert plan.mode == SourceDispatchMode.local

    def test_orchestrate_no_posture_is_not_gated(self):
        """orchestrate without posture arg → posture gate not applied → local attempted."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        _mock_exec = MagicMock(return_value={"success": True})
        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                _mock_exec,
            ),
        ):
            result = orchestrate_source_runtime_dispatch(trace_id="trace_s02")
        # Local execution was attempted (not blocked)
        _mock_exec.assert_called_once()


# ---------------------------------------------------------------------------
# T — Result posture field propagation
# ---------------------------------------------------------------------------


class TestResultPosturePropagation:
    """Group T: source_runtime_posture flows through to SourceDispatchResult."""

    def test_result_has_source_runtime_posture_field(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_t01",
                source_runtime_posture="control_only",
            )
        assert hasattr(result, "source_runtime_posture")

    def test_result_posture_value_matches_input_control_only(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_t02",
                source_runtime_posture="control_only",
            )
        assert result.source_runtime_posture == "control_only"

    def test_result_posture_value_matches_input_join_runtime(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
            patch(
                "core.runtime.source_dispatch_orchestrator._try_run_local_execution",
                return_value={"success": True},
            ),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_t03",
                source_runtime_posture="join_runtime",
            )
        assert result.source_runtime_posture == "join_runtime"

    def test_result_to_dict_includes_posture(self):
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

        with (
            patch("core.runtime.source_dispatch_orchestrator._try_policy_alignment", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_governance_snapshot", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_session", return_value=None),
            patch("core.runtime.source_dispatch_orchestrator._try_mesh_memberships", return_value=None),
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_t04",
                source_runtime_posture="control_only",
            )
        d = result.to_dict()
        assert "source_runtime_posture" in d
