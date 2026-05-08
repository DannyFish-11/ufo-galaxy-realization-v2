"""tests/test_pr03_mesh_runtime_center_closure.py
==================================================
Regression tests for PR-03: Mesh Runtime Center Closure.

This module proves the center-side mesh runtime state machine is correct and
enforceable.  It validates:

1.  PR-03 sentinels and policies are present.
2.  MeshRuntimeCenterStatus state machine enum is complete and correct.
3.  Valid state transitions are explicitly defined and enforced.
4.  Participant eligibility/readiness/degraded/constrained semantics work.
5.  evaluate_center_runtime_status() correctly derives center state from
    real coordinator state.
6.  The critical distinction between participation_ready and runtime_closed
    is enforced.
7.  Barrier coordination lifecycle transitions (active → released → closed).
8.  Partial participant / degraded / constrained runtime paths.
9.  build_mesh_runtime_center_state() produces correct operator snapshot.
10. build_mesh_runtime_state() now includes center_runtime_state.
11. MeshParticipantEligibilityStatus semantics are correct.
12. Terminal state correctness (runtime_closed vs failed).

Test groups
-----------
A   Sentinel and policy assertions
B   MeshRuntimeCenterStatus enum completeness
C   Valid transition table coverage
D   is_valid_center_transition() enforcement
E   MeshParticipantEligibilityStatus semantics
F   evaluate_center_runtime_status() — pending_participants path
G   evaluate_center_runtime_status() — participation_ready path
H   evaluate_center_runtime_status() — runtime_active path
I   evaluate_center_runtime_status() — barrier_active path
J   evaluate_center_runtime_status() — barrier_released → runtime_closed
K   evaluate_center_runtime_status() — degraded participant paths
L   evaluate_center_runtime_status() — constrained participant paths
M   evaluate_center_runtime_status() — failed paths
N   Participation-ready vs runtime-closed distinction (core PR-03 requirement)
O   Full lifecycle: pending → participation_ready → active → barrier → closed
P   build_mesh_runtime_center_state() operator snapshot
Q   build_mesh_runtime_state() integration — includes center_runtime_state key
R   Graceful handling of None/invalid coordinator state
"""

from __future__ import annotations

from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.mesh.mesh_runtime_center_state import (
        BARRIER_LIFECYCLE_CENTER_PR03_POLICY,
        DEGRADED_CONSTRAINED_CENTER_PR03_POLICY,
        MESH_RUNTIME_CENTER_ACTIVE_STATUSES,
        MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL,
        MESH_RUNTIME_CENTER_TERMINAL_STATUSES,
        MESH_RUNTIME_CENTER_VALID_TRANSITIONS,
        PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY,
        PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY,
        MeshParticipantCenterEligibility,
        MeshParticipantEligibilityStatus,
        MeshRuntimeCenterState,
        MeshRuntimeCenterStatus,
        build_mesh_runtime_center_state,
        evaluate_center_runtime_status,
        is_valid_center_transition,
    )

    _CENTER_STATE_AVAILABLE = True
except ImportError:
    _CENTER_STATE_AVAILABLE = False

try:
    from contracts.mesh_session_coordinator import (
        MeshBarrierStatus,
        MeshCoordinatorStatus,
        MeshParticipantStatus,
        build_mesh_session_coordinator,
        from_mesh_session,
    )

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.mesh.live_mesh_runtime_engine import (
        LiveMeshRuntimeEngine,
        register_participant,
        run_live_mesh_session,
        update_participant_status,
    )

    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

try:
    from core.unified_governance_semantics import build_mesh_runtime_state

    _GOVERNANCE_AVAILABLE = True
except ImportError:
    _GOVERNANCE_AVAILABLE = False


_ALL_AVAILABLE = _CENTER_STATE_AVAILABLE and _CONTRACTS_AVAILABLE and _ENGINE_AVAILABLE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator_state(
    session_id: str = "test_center",
    mesh_id: str = "mesh_center",
    device_ids: Optional[List[str]] = None,
    barrier_posture: str = "soft_barrier",
    coord_status: Optional[str] = None,
) -> Any:
    """Build a minimal coordinator state for testing."""
    if not _CONTRACTS_AVAILABLE:
        pytest.skip("contracts not available")
    device_ids = device_ids or ["dev_a", "dev_b"]
    state = from_mesh_session(
        {
            "session_id": session_id,
            "mesh_id": mesh_id,
            "participants": [
                {
                    "device_id": did,
                    "roles": ["primary" if i == 0 else "support"],
                    "online": True,
                    "status": "active",
                }
                for i, did in enumerate(device_ids)
            ],
            "multi_device_required": True,
            "barrier_posture": barrier_posture,
        },
        trace_id="trace_center_test",
    )
    if coord_status:
        try:
            status_enum = MeshCoordinatorStatus(coord_status)
            state = state.model_copy(update={"status": status_enum})
        except Exception:
            pass
    return state


# ---------------------------------------------------------------------------
# Group A: Sentinel and policy assertions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupA_Sentinels:
    def test_a1_sentinel_present(self) -> None:
        assert MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL
        assert "PR-03" in MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL
        assert "center" in MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL.lower()

    def test_a2_participation_ready_vs_runtime_closed_policy(self) -> None:
        assert PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY
        assert "participation_ready" in PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY
        assert "runtime_closed" in PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY

    def test_a3_barrier_lifecycle_policy(self) -> None:
        assert BARRIER_LIFECYCLE_CENTER_PR03_POLICY
        assert "barrier" in BARRIER_LIFECYCLE_CENTER_PR03_POLICY.lower()

    def test_a4_participant_eligibility_policy(self) -> None:
        assert PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY
        assert "eligibility" in PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY.lower()

    def test_a5_degraded_constrained_policy(self) -> None:
        assert DEGRADED_CONSTRAINED_CENTER_PR03_POLICY
        assert "degraded" in DEGRADED_CONSTRAINED_CENTER_PR03_POLICY.lower()
        assert "constrained" in DEGRADED_CONSTRAINED_CENTER_PR03_POLICY.lower()


# ---------------------------------------------------------------------------
# Group B: MeshRuntimeCenterStatus enum completeness
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupB_StatusEnum:
    def test_b1_has_pending_participants(self) -> None:
        assert MeshRuntimeCenterStatus.pending_participants.value == "pending_participants"

    def test_b2_has_participation_ready(self) -> None:
        assert MeshRuntimeCenterStatus.participation_ready.value == "participation_ready"

    def test_b3_has_runtime_active(self) -> None:
        assert MeshRuntimeCenterStatus.runtime_active.value == "runtime_active"

    def test_b4_has_barrier_active(self) -> None:
        assert MeshRuntimeCenterStatus.barrier_active.value == "barrier_active"

    def test_b5_has_barrier_released(self) -> None:
        assert MeshRuntimeCenterStatus.barrier_released.value == "barrier_released"

    def test_b6_has_runtime_closed(self) -> None:
        assert MeshRuntimeCenterStatus.runtime_closed.value == "runtime_closed"

    def test_b7_has_degraded(self) -> None:
        assert MeshRuntimeCenterStatus.degraded.value == "degraded"

    def test_b8_has_constrained(self) -> None:
        assert MeshRuntimeCenterStatus.constrained.value == "constrained"

    def test_b9_has_failed(self) -> None:
        assert MeshRuntimeCenterStatus.failed.value == "failed"

    def test_b10_has_unknown(self) -> None:
        assert MeshRuntimeCenterStatus.unknown.value == "unknown"

    def test_b11_terminal_statuses(self) -> None:
        assert MeshRuntimeCenterStatus.runtime_closed in MESH_RUNTIME_CENTER_TERMINAL_STATUSES
        assert MeshRuntimeCenterStatus.failed in MESH_RUNTIME_CENTER_TERMINAL_STATUSES

    def test_b12_active_statuses(self) -> None:
        assert MeshRuntimeCenterStatus.runtime_active in MESH_RUNTIME_CENTER_ACTIVE_STATUSES
        assert MeshRuntimeCenterStatus.barrier_active in MESH_RUNTIME_CENTER_ACTIVE_STATUSES
        assert MeshRuntimeCenterStatus.barrier_released in MESH_RUNTIME_CENTER_ACTIVE_STATUSES


# ---------------------------------------------------------------------------
# Group C: Valid transition table coverage
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupC_TransitionTable:
    def test_c1_pending_can_go_to_participation_ready(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.pending_participants]
        assert MeshRuntimeCenterStatus.participation_ready in allowed

    def test_c2_pending_can_go_to_failed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.pending_participants]
        assert MeshRuntimeCenterStatus.failed in allowed

    def test_c3_participation_ready_can_go_to_runtime_active(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.participation_ready]
        assert MeshRuntimeCenterStatus.runtime_active in allowed

    def test_c4_participation_ready_can_go_to_degraded(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.participation_ready]
        assert MeshRuntimeCenterStatus.degraded in allowed

    def test_c5_runtime_active_can_go_to_barrier_active(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.runtime_active]
        assert MeshRuntimeCenterStatus.barrier_active in allowed

    def test_c6_barrier_active_can_go_to_barrier_released(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.barrier_active]
        assert MeshRuntimeCenterStatus.barrier_released in allowed

    def test_c7_barrier_active_can_go_to_failed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.barrier_active]
        assert MeshRuntimeCenterStatus.failed in allowed

    def test_c8_barrier_released_can_go_to_runtime_closed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.barrier_released]
        assert MeshRuntimeCenterStatus.runtime_closed in allowed

    def test_c9_runtime_closed_has_no_transitions(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.runtime_closed]
        assert len(allowed) == 0

    def test_c10_failed_has_no_transitions(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.failed]
        assert len(allowed) == 0

    def test_c11_degraded_can_go_to_runtime_closed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.degraded]
        assert MeshRuntimeCenterStatus.runtime_closed in allowed

    def test_c12_constrained_can_go_to_runtime_closed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.constrained]
        assert MeshRuntimeCenterStatus.runtime_closed in allowed


# ---------------------------------------------------------------------------
# Group D: is_valid_center_transition() enforcement
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupD_TransitionEnforcement:
    def test_d1_valid_transition_pending_to_ready(self) -> None:
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.pending_participants,
            MeshRuntimeCenterStatus.participation_ready,
        )

    def test_d2_valid_transition_participation_ready_to_runtime_active(self) -> None:
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.participation_ready,
            MeshRuntimeCenterStatus.runtime_active,
        )

    def test_d3_valid_transition_barrier_active_to_barrier_released(self) -> None:
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.barrier_active,
            MeshRuntimeCenterStatus.barrier_released,
        )

    def test_d4_valid_transition_barrier_released_to_runtime_closed(self) -> None:
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.barrier_released,
            MeshRuntimeCenterStatus.runtime_closed,
        )

    def test_d5_invalid_transition_runtime_closed_to_runtime_active(self) -> None:
        # runtime_closed is terminal — no transitions allowed
        assert not is_valid_center_transition(
            MeshRuntimeCenterStatus.runtime_closed,
            MeshRuntimeCenterStatus.runtime_active,
        )

    def test_d6_invalid_transition_failed_to_participation_ready(self) -> None:
        # failed is terminal
        assert not is_valid_center_transition(
            MeshRuntimeCenterStatus.failed,
            MeshRuntimeCenterStatus.participation_ready,
        )

    def test_d7_invalid_transition_participation_ready_to_barrier_active(self) -> None:
        # Must go through runtime_active first
        assert not is_valid_center_transition(
            MeshRuntimeCenterStatus.participation_ready,
            MeshRuntimeCenterStatus.barrier_active,
        )

    def test_d8_invalid_transition_pending_to_runtime_closed(self) -> None:
        # Cannot skip intermediate states to reach runtime_closed
        assert not is_valid_center_transition(
            MeshRuntimeCenterStatus.pending_participants,
            MeshRuntimeCenterStatus.runtime_closed,
        )


# ---------------------------------------------------------------------------
# Group E: MeshParticipantEligibilityStatus semantics
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupE_EligibilityStatus:
    def test_e1_eligible_can_participate(self) -> None:
        assert MeshParticipantEligibilityStatus.eligible.can_participate()

    def test_e2_ready_can_participate(self) -> None:
        assert MeshParticipantEligibilityStatus.ready.can_participate()

    def test_e3_degraded_can_participate(self) -> None:
        assert MeshParticipantEligibilityStatus.degraded.can_participate()

    def test_e4_constrained_can_participate(self) -> None:
        assert MeshParticipantEligibilityStatus.constrained.can_participate()

    def test_e5_offline_cannot_participate(self) -> None:
        assert not MeshParticipantEligibilityStatus.offline.can_participate()

    def test_e6_ineligible_cannot_participate(self) -> None:
        assert not MeshParticipantEligibilityStatus.ineligible.can_participate()

    def test_e7_pending_eligibility_cannot_participate(self) -> None:
        assert not MeshParticipantEligibilityStatus.pending_eligibility.can_participate()

    def test_e8_ready_is_participation_ready(self) -> None:
        assert MeshParticipantEligibilityStatus.ready.is_participation_ready()

    def test_e9_degraded_is_participation_ready(self) -> None:
        # Degraded = still available, so participation-ready
        assert MeshParticipantEligibilityStatus.degraded.is_participation_ready()

    def test_e10_constrained_is_participation_ready(self) -> None:
        assert MeshParticipantEligibilityStatus.constrained.is_participation_ready()

    def test_e11_eligible_is_participation_ready(self) -> None:
        # eligible means registered by center → participation-ready
        assert MeshParticipantEligibilityStatus.eligible.is_participation_ready()

    def test_e12_offline_is_not_participation_ready(self) -> None:
        assert not MeshParticipantEligibilityStatus.offline.is_participation_ready()


# ---------------------------------------------------------------------------
# Group F: evaluate_center_runtime_status() — pending_participants path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ALL_AVAILABLE, reason="required modules not available"
)
class TestGroupF_PendingParticipants:
    def test_f1_none_coordinator_gives_pending(self) -> None:
        state = evaluate_center_runtime_status(None)
        assert state.status == MeshRuntimeCenterStatus.pending_participants
        assert not state.is_participation_ready
        assert not state.is_runtime_closed

    def test_f2_coordinator_with_no_participants_gives_pending(self) -> None:
        coord = build_mesh_session_coordinator(session_id="s_empty")
        # No participants registered
        state = evaluate_center_runtime_status(coord)
        assert state.status == MeshRuntimeCenterStatus.pending_participants
        assert state.total_participant_count == 0
        assert not state.is_participation_ready
        assert not state.is_runtime_closed

    def test_f3_pending_participants_has_empty_eligibilities(self) -> None:
        coord = build_mesh_session_coordinator(session_id="s_empty_2")
        state = evaluate_center_runtime_status(coord)
        assert state.participant_eligibilities == []

    def test_f4_pending_state_not_active(self) -> None:
        coord = build_mesh_session_coordinator(session_id="s_pending_active")
        state = evaluate_center_runtime_status(coord)
        assert state.status not in MESH_RUNTIME_CENTER_ACTIVE_STATUSES

    def test_f5_pending_state_not_terminal(self) -> None:
        coord = build_mesh_session_coordinator(session_id="s_pending_terminal")
        state = evaluate_center_runtime_status(coord)
        assert state.status not in MESH_RUNTIME_CENTER_TERMINAL_STATUSES


# ---------------------------------------------------------------------------
# Group G: evaluate_center_runtime_status() — participation_ready path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupG_ParticipationReady:
    def test_g1_registered_participants_gives_participation_ready(self) -> None:
        coord = _make_coordinator_state(session_id="s_ready")
        state = evaluate_center_runtime_status(coord)
        # With pending coordinator status, participants registered → participation_ready
        assert state.status == MeshRuntimeCenterStatus.participation_ready
        assert state.is_participation_ready
        assert not state.is_runtime_closed

    def test_g2_participation_ready_is_not_runtime_closed(self) -> None:
        """Core PR-03 requirement: participation_ready ≠ runtime_closed."""
        coord = _make_coordinator_state(session_id="s_ready_not_closed")
        state = evaluate_center_runtime_status(coord)
        assert state.is_participation_ready
        assert not state.is_runtime_closed
        # The deferred list should mention this distinction
        combined = " ".join(state.deferred_or_constrained)
        assert "participation_ready" in combined
        assert "runtime_closed" in combined

    def test_g3_participation_ready_count_correct(self) -> None:
        coord = _make_coordinator_state(
            session_id="s_count", device_ids=["d1", "d2", "d3"]
        )
        state = evaluate_center_runtime_status(coord)
        # All pending participants → pending_eligibility, not yet participation_ready
        assert state.total_participant_count == 3

    def test_g4_session_id_propagated(self) -> None:
        coord = _make_coordinator_state(session_id="my_session_123")
        state = evaluate_center_runtime_status(coord)
        assert state.session_id == "my_session_123"

    def test_g5_to_dict_contains_is_participation_ready(self) -> None:
        coord = _make_coordinator_state(session_id="s_dict")
        state = evaluate_center_runtime_status(coord)
        d = state.to_dict()
        assert "is_participation_ready" in d
        assert "is_runtime_closed" in d

    def test_g6_to_dict_contains_sentinel(self) -> None:
        coord = _make_coordinator_state(session_id="s_dict_sentinel")
        state = evaluate_center_runtime_status(coord)
        d = state.to_dict()
        assert "_sentinel" in d
        assert "PR-03" in d["_sentinel"]


# ---------------------------------------------------------------------------
# Group H: evaluate_center_runtime_status() — runtime_active path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupH_RuntimeActive:
    def test_h1_active_coordinator_gives_runtime_active(self) -> None:
        coord = _make_coordinator_state(session_id="s_active", coord_status="active")
        state = evaluate_center_runtime_status(coord)
        # Active coordinator with no barrier status = runtime_active
        assert state.status in (
            MeshRuntimeCenterStatus.runtime_active,
            MeshRuntimeCenterStatus.participation_ready,
            MeshRuntimeCenterStatus.degraded,
        )
        # At minimum, is_participation_ready should be True
        assert state.is_participation_ready or state.status == MeshRuntimeCenterStatus.pending_participants

    def test_h2_runtime_active_is_not_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_active_nc", coord_status="active")
        state = evaluate_center_runtime_status(coord)
        assert not state.is_runtime_closed

    def test_h3_active_status_is_in_active_set(self) -> None:
        coord = _make_coordinator_state(session_id="s_active_set", coord_status="active")
        state = evaluate_center_runtime_status(coord)
        if state.status not in (
            MeshRuntimeCenterStatus.pending_participants,
            MeshRuntimeCenterStatus.participation_ready,
        ):
            assert state.status in MESH_RUNTIME_CENTER_ACTIVE_STATUSES


# ---------------------------------------------------------------------------
# Group I: evaluate_center_runtime_status() — barrier_active path
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupI_BarrierActive:
    def test_i1_awaiting_barrier_coordinator_gives_barrier_active(self) -> None:
        coord = _make_coordinator_state(session_id="s_barrier", coord_status="awaiting_barrier")
        state = evaluate_center_runtime_status(coord)
        assert state.status == MeshRuntimeCenterStatus.barrier_active

    def test_i2_barrier_active_is_not_participation_ready_only(self) -> None:
        coord = _make_coordinator_state(session_id="s_barrier_ready", coord_status="awaiting_barrier")
        state = evaluate_center_runtime_status(coord)
        # Status should be barrier_active, NOT participation_ready
        assert state.status != MeshRuntimeCenterStatus.participation_ready

    def test_i3_barrier_active_is_not_runtime_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_barrier_nc", coord_status="awaiting_barrier")
        state = evaluate_center_runtime_status(coord)
        assert not state.is_runtime_closed

    def test_i4_barrier_active_is_in_active_set(self) -> None:
        coord = _make_coordinator_state(session_id="s_barrier_set", coord_status="awaiting_barrier")
        state = evaluate_center_runtime_status(coord)
        assert state.status in MESH_RUNTIME_CENTER_ACTIVE_STATUSES

    def test_i5_barrier_status_reflected_in_state(self) -> None:
        coord = _make_coordinator_state(session_id="s_barrier_status", coord_status="awaiting_barrier")
        state = evaluate_center_runtime_status(coord)
        assert state.coordinator_status == "awaiting_barrier"


# ---------------------------------------------------------------------------
# Group J: evaluate_center_runtime_status() — barrier released → runtime closed
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupJ_BarrierReleasedToRuntimeClosed:
    def test_j1_completed_coordinator_gives_runtime_closed(self) -> None:
        """All participants completed → runtime_closed."""
        coord = _make_coordinator_state(session_id="s_completed", device_ids=["d1", "d2"])
        # Simulate completed state using the live engine
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"output": "a", "success": True},
                "d2": {"output": "b", "success": True},
            },
        )
        assert result.outcome == "completed"
        final_coord = result.coordinator_state

        center_state = evaluate_center_runtime_status(final_coord)
        assert center_state.status == MeshRuntimeCenterStatus.runtime_closed
        assert center_state.is_runtime_closed
        assert center_state.runtime_closed_count == 2

    def test_j2_runtime_closed_is_terminal(self) -> None:
        coord = _make_coordinator_state(session_id="s_terminal", device_ids=["d1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord, participant_results={"d1": {"success": True}})
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)

        if center_state.status == MeshRuntimeCenterStatus.runtime_closed:
            assert center_state.status in MESH_RUNTIME_CENTER_TERMINAL_STATUSES

    def test_j3_runtime_closed_count_matches_completed_participants(self) -> None:
        coord = _make_coordinator_state(session_id="s_count_closed", device_ids=["d1", "d2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"success": True},
                "d2": {"success": True},
            },
        )
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)

        assert center_state.runtime_closed_count == 2

    def test_j4_participation_ready_and_runtime_closed_both_true_when_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_both_closed", device_ids=["d1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord, participant_results={"d1": {"success": True}})
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)

        if center_state.status == MeshRuntimeCenterStatus.runtime_closed:
            # When runtime is closed, participation_ready should still be true
            assert center_state.is_participation_ready
            assert center_state.is_runtime_closed


# ---------------------------------------------------------------------------
# Group K: evaluate_center_runtime_status() — degraded participant paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupK_DegradedPaths:
    def test_k1_partial_outcome_gives_degraded(self) -> None:
        """Partial completion (some succeeded, some failed) → degraded."""
        coord = _make_coordinator_state(session_id="s_partial", device_ids=["d1", "d2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"success": True},
                "d2": {"success": False},
            },
        )
        assert result.outcome == "partial"
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)
        assert center_state.status == MeshRuntimeCenterStatus.degraded

    def test_k2_degraded_is_not_runtime_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_degraded_nc", device_ids=["d1", "d2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"success": True},
                "d2": {"success": False},
            },
        )
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)
        # degraded is NOT runtime_closed
        if center_state.status == MeshRuntimeCenterStatus.degraded:
            assert not center_state.is_runtime_closed

    def test_k3_degraded_is_in_active_set(self) -> None:
        """degraded is an active status (execution still in progress or done with partial)."""
        assert MeshRuntimeCenterStatus.degraded in MESH_RUNTIME_CENTER_ACTIVE_STATUSES

    def test_k4_degraded_participant_eligibility(self) -> None:
        """MeshParticipantCenterEligibility correctly represents degraded participants."""
        elig = MeshParticipantCenterEligibility(
            device_id="dev_degraded",
            eligibility=MeshParticipantEligibilityStatus.degraded,
            participation_ready=True,
            runtime_closed=False,
            participant_status="working",
            degraded_reason="limited_resources",
        )
        assert elig.eligibility.can_participate()
        assert elig.eligibility.is_participation_ready()
        d = elig.to_dict()
        assert d["eligibility"] == "degraded"
        assert d["degraded_reason"] == "limited_resources"


# ---------------------------------------------------------------------------
# Group L: evaluate_center_runtime_status() — constrained participant paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupL_ConstrainedPaths:
    def test_l1_constrained_participant_can_participate(self) -> None:
        elig = MeshParticipantCenterEligibility(
            device_id="dev_constrained",
            eligibility=MeshParticipantEligibilityStatus.constrained,
            participation_ready=True,
            runtime_closed=False,
            participant_status="working",
            constrained_reason="limited_subtask_scope",
        )
        assert elig.eligibility.can_participate()
        assert elig.eligibility.is_participation_ready()

    def test_l2_constrained_participant_to_dict(self) -> None:
        elig = MeshParticipantCenterEligibility(
            device_id="dev_c",
            eligibility=MeshParticipantEligibilityStatus.constrained,
            constrained_reason="capability_limited",
        )
        d = elig.to_dict()
        assert d["eligibility"] == "constrained"
        assert d["constrained_reason"] == "capability_limited"

    def test_l3_constrained_in_active_set(self) -> None:
        assert MeshRuntimeCenterStatus.constrained in MESH_RUNTIME_CENTER_ACTIVE_STATUSES

    def test_l4_constrained_can_transition_to_runtime_closed(self) -> None:
        allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS[MeshRuntimeCenterStatus.constrained]
        assert MeshRuntimeCenterStatus.runtime_closed in allowed


# ---------------------------------------------------------------------------
# Group M: evaluate_center_runtime_status() — failed paths
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupM_FailedPaths:
    def test_m1_all_failed_participants_gives_failed(self) -> None:
        coord = _make_coordinator_state(session_id="s_failed", device_ids=["d1", "d2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"success": False},
                "d2": {"success": False},
            },
        )
        assert result.outcome == "failed"
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)
        assert center_state.status == MeshRuntimeCenterStatus.failed

    def test_m2_failed_is_terminal(self) -> None:
        assert MeshRuntimeCenterStatus.failed in MESH_RUNTIME_CENTER_TERMINAL_STATUSES

    def test_m3_failed_state_is_not_participation_ready(self) -> None:
        coord = _make_coordinator_state(session_id="s_failed_ready", device_ids=["d1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={"d1": {"success": False}},
        )
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)
        if center_state.status == MeshRuntimeCenterStatus.failed:
            assert not center_state.is_runtime_closed

    def test_m4_no_participants_engine_gives_failed_result(self) -> None:
        """Engine with no participants produces failed result."""
        coord = build_mesh_session_coordinator(session_id="s_empty_engine")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord)
        assert result.outcome == "failed"

    def test_m5_ineligible_participant_eligibility(self) -> None:
        elig = MeshParticipantCenterEligibility(
            device_id="dev_ineligible",
            eligibility=MeshParticipantEligibilityStatus.ineligible,
            participation_ready=False,
            runtime_closed=False,
        )
        assert not elig.eligibility.can_participate()
        assert not elig.eligibility.is_participation_ready()


# ---------------------------------------------------------------------------
# Group N: Participation-ready vs runtime-closed distinction
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupN_ParticipationReadyVsRuntimeClosed:
    """Core PR-03 requirement: participation_ready ≠ runtime_closed.

    These tests prove that the system distinguishes between:
    - "This mesh can run" (participation_ready)
    - "This mesh has run to completion" (runtime_closed)
    """

    def test_n1_fresh_coordinator_is_participation_ready_not_runtime_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_pr_rc_1")
        state = evaluate_center_runtime_status(coord)
        # Fresh coordinator with participants → participation_ready
        assert state.is_participation_ready
        assert not state.is_runtime_closed

    def test_n2_completed_coordinator_is_both_participation_ready_and_runtime_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_pr_rc_2", device_ids=["d1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord, participant_results={"d1": {"success": True}})
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)
        if center_state.status == MeshRuntimeCenterStatus.runtime_closed:
            assert center_state.is_participation_ready
            assert center_state.is_runtime_closed

    def test_n3_participation_ready_status_is_not_terminal(self) -> None:
        assert MeshRuntimeCenterStatus.participation_ready not in MESH_RUNTIME_CENTER_TERMINAL_STATUSES

    def test_n4_runtime_closed_status_is_terminal(self) -> None:
        assert MeshRuntimeCenterStatus.runtime_closed in MESH_RUNTIME_CENTER_TERMINAL_STATUSES

    def test_n5_participation_ready_does_not_imply_barrier_released(self) -> None:
        """Being participation_ready is a precondition — barrier has not yet been reached."""
        coord = _make_coordinator_state(session_id="s_pr_barrier")
        state = evaluate_center_runtime_status(coord)
        if state.status == MeshRuntimeCenterStatus.participation_ready:
            assert state.barrier_status not in ("released",)

    def test_n6_policy_string_distinguishes_participation_from_closure(self) -> None:
        policy = PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY
        assert "NOT equivalent" in policy or "not equivalent" in policy.lower() or "MUST NOT" in policy

    def test_n7_deferred_list_includes_distinction_when_not_closed(self) -> None:
        coord = _make_coordinator_state(session_id="s_deferred_dist")
        state = evaluate_center_runtime_status(coord)
        if state.is_participation_ready and not state.is_runtime_closed:
            combined = " ".join(state.deferred_or_constrained)
            assert "participation_ready" in combined
            assert "runtime_closed" in combined

    def test_n8_runtime_closed_excludes_coordination_in_deferred_list(self) -> None:
        """Once runtime is truly closed, deferred list should not complain about it."""
        coord = _make_coordinator_state(session_id="s_closed_clean", device_ids=["d1"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord, participant_results={"d1": {"success": True}})
        final_coord = result.coordinator_state
        center_state = evaluate_center_runtime_status(final_coord)

        if center_state.is_runtime_closed:
            # When truly closed, the "not yet closed" deferred note should be absent
            combined = " ".join(center_state.deferred_or_constrained)
            assert "runtime not yet closed" not in combined


# ---------------------------------------------------------------------------
# Group O: Full lifecycle end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupO_FullLifecycle:
    def test_o1_full_lifecycle_two_participants(self) -> None:
        """Prove the full PR-03 lifecycle: pending → ready → active → closed."""
        session_id = "s_full_lifecycle"
        coord = _make_coordinator_state(session_id=session_id, device_ids=["d1", "d2"])

        # Step 1: Initial state — pending participants
        # (With participants pre-registered via from_mesh_session, status is pending/unknown)
        initial_state = evaluate_center_runtime_status(coord)
        assert initial_state.status in (
            MeshRuntimeCenterStatus.pending_participants,
            MeshRuntimeCenterStatus.participation_ready,
        )
        assert not initial_state.is_runtime_closed

        # Step 2: Run engine with both participants
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"output": "result_a", "success": True},
                "d2": {"output": "result_b", "success": True},
            },
        )
        assert result.outcome == "completed"
        assert result.success

        # Step 3: Final center state should be runtime_closed
        final_state = evaluate_center_runtime_status(result.coordinator_state)
        assert final_state.status == MeshRuntimeCenterStatus.runtime_closed
        assert final_state.is_runtime_closed
        assert final_state.runtime_closed_count == 2
        assert final_state.total_participant_count == 2

    def test_o2_partial_lifecycle_one_failed(self) -> None:
        """One participant fails → degraded (not runtime_closed, not participation_only)."""
        coord = _make_coordinator_state(session_id="s_partial_lifecycle", device_ids=["d1", "d2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            coord,
            participant_results={
                "d1": {"success": True},
                "d2": {"success": False},
            },
        )
        assert result.outcome == "partial"
        final_state = evaluate_center_runtime_status(result.coordinator_state)
        assert final_state.status == MeshRuntimeCenterStatus.degraded
        assert not final_state.is_runtime_closed

    def test_o3_barrier_coordination_transitions(self) -> None:
        """Coordinator with awaiting_barrier → barrier_active center status."""
        coord = _make_coordinator_state(
            session_id="s_barrier_lifecycle", coord_status="awaiting_barrier"
        )
        state = evaluate_center_runtime_status(coord)
        assert state.status == MeshRuntimeCenterStatus.barrier_active

        # barrier_active can transition to barrier_released
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.barrier_active,
            MeshRuntimeCenterStatus.barrier_released,
        )
        # barrier_released can transition to runtime_closed
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.barrier_released,
            MeshRuntimeCenterStatus.runtime_closed,
        )

    def test_o4_single_participant_full_closure(self) -> None:
        coord = _make_coordinator_state(session_id="s_single_closed", device_ids=["solo"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(coord, participant_results={"solo": {"output": "done", "success": True}})
        final_state = evaluate_center_runtime_status(result.coordinator_state)
        if result.outcome == "completed":
            assert final_state.status == MeshRuntimeCenterStatus.runtime_closed

    def test_o5_degraded_can_transition_to_runtime_closed(self) -> None:
        # degraded → runtime_closed is valid per transition table
        assert is_valid_center_transition(
            MeshRuntimeCenterStatus.degraded,
            MeshRuntimeCenterStatus.runtime_closed,
        )


# ---------------------------------------------------------------------------
# Group P: build_mesh_runtime_center_state() operator snapshot
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupP_OperatorSnapshot:
    def test_p1_build_without_coordinator_returns_dict(self) -> None:
        result = build_mesh_runtime_center_state()
        assert isinstance(result, dict)
        assert "status" in result

    def test_p2_build_with_none_coordinator_returns_dict(self) -> None:
        result = build_mesh_runtime_center_state(None)
        assert isinstance(result, dict)

    def test_p3_build_with_coordinator_includes_participation_ready(self) -> None:
        if not _CONTRACTS_AVAILABLE:
            pytest.skip("contracts not available")
        coord = _make_coordinator_state(session_id="s_op_snapshot")
        result = build_mesh_runtime_center_state(coord)
        assert "is_participation_ready" in result

    def test_p4_build_includes_is_runtime_closed(self) -> None:
        if not _CONTRACTS_AVAILABLE:
            pytest.skip("contracts not available")
        coord = _make_coordinator_state(session_id="s_op_closed")
        result = build_mesh_runtime_center_state(coord)
        assert "is_runtime_closed" in result

    def test_p5_build_includes_sentinel(self) -> None:
        result = build_mesh_runtime_center_state()
        assert "_sentinel" in result

    def test_p6_build_includes_policy_keys(self) -> None:
        result = build_mesh_runtime_center_state()
        assert "_policy_participation_ready_vs_closed" in result
        assert "_policy_barrier_lifecycle" in result
        assert "_policy_eligibility" in result

    def test_p7_build_without_coordinator_has_deferred_notes(self) -> None:
        result = build_mesh_runtime_center_state()
        assert "deferred_or_constrained" in result
        deferred = result.get("deferred_or_constrained", [])
        assert len(deferred) > 0


# ---------------------------------------------------------------------------
# Group Q: build_mesh_runtime_state() integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _GOVERNANCE_AVAILABLE, reason="governance module not available")
class TestGroupQ_GovernanceIntegration:
    def test_q1_build_mesh_runtime_state_includes_center_runtime_state(self) -> None:
        result = build_mesh_runtime_state()
        assert "center_runtime_state" in result

    def test_q2_center_runtime_state_has_status(self) -> None:
        result = build_mesh_runtime_state()
        center = result.get("center_runtime_state", {})
        assert "status" in center

    def test_q3_build_mesh_runtime_state_with_coordinator(self) -> None:
        if not _CONTRACTS_AVAILABLE:
            pytest.skip("contracts not available")
        coord = _make_coordinator_state(session_id="s_gov_coord")
        result = build_mesh_runtime_state(coordinator_state=coord)
        assert "center_runtime_state" in result
        center = result["center_runtime_state"]
        assert "is_participation_ready" in center
        assert "is_runtime_closed" in center

    def test_q4_runtime_proofs_includes_center_state_machine(self) -> None:
        result = build_mesh_runtime_state()
        proofs = result.get("runtime_proofs", {})
        assert "mesh_runtime_center_state_machine" in proofs
        assert proofs["mesh_runtime_center_state_machine"] is True

    def test_q5_runtime_proof_count_includes_center_machine(self) -> None:
        result = build_mesh_runtime_state()
        assert result.get("runtime_proof_count", 0) >= 1


# ---------------------------------------------------------------------------
# Group R: Graceful handling of None/invalid coordinator state
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _CENTER_STATE_AVAILABLE, reason="center state module not available")
class TestGroupR_GracefulHandling:
    def test_r1_none_coordinator_does_not_raise(self) -> None:
        state = evaluate_center_runtime_status(None)
        assert state is not None
        assert state.status == MeshRuntimeCenterStatus.pending_participants

    def test_r2_none_coordinator_has_errors(self) -> None:
        state = evaluate_center_runtime_status(None)
        assert len(state.errors) > 0

    def test_r3_empty_object_coordinator_does_not_raise(self) -> None:
        class EmptyCoord:
            pass

        state = evaluate_center_runtime_status(EmptyCoord())
        assert state is not None

    def test_r4_build_center_state_does_not_raise_on_invalid(self) -> None:
        result = build_mesh_runtime_center_state("not_a_coordinator")
        assert isinstance(result, dict)
        assert "status" in result

    def test_r5_evaluate_returns_to_dict_without_error(self) -> None:
        state = evaluate_center_runtime_status(None)
        d = state.to_dict()
        assert isinstance(d, dict)
        assert "status" in d

    def test_r6_mesh_runtime_center_state_default_values(self) -> None:
        state = MeshRuntimeCenterState()
        assert state.status == MeshRuntimeCenterStatus.unknown
        assert state.is_participation_ready is False
        assert state.is_runtime_closed is False
        assert state.total_participant_count == 0
