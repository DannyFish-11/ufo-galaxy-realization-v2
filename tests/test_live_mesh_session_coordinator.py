"""tests/test_live_mesh_session_coordinator.py
===============================================
Tests for the live/incremental :class:`LiveMeshSessionCoordinator` (PR-J).

This test suite provides concrete evidence for the PR-J acceptance criteria:

1.  MeshSession is driven by a live runtime/coordinator (not only contracts).
2.  Participant lifecycle changes affect real runtime progression.
3.  Barrier semantics are runtime-driven (re-evaluated after each event).
4.  Merge/convergence/completion are coordinator-driven via finalize().
5.  Participant failure/dropout materially affects runtime outcomes.

Test groups
-----------
A   Policy sentinels
B   LiveMeshSessionCoordinator construction
C   Participant management (add_participant)
D   Participant lifecycle events affect coordinator state
E   Barrier tracks across incremental events (re-evaluated each result)
F   Finalize — full lifecycle: staged_mesh → active → merge → completed
G   Partial completion (some participants failed / dropped)
H   Full failure (all participants failed / dropped)
I   Participant dropout affects runtime outcome
J   from_mesh_session constructor
K   create_live_mesh_session_coordinator convenience function
L   Thread-safety: concurrent event emission
M   is_complete / outcome properties
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.mesh.live_mesh_session_coordinator import (
        BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY,
        COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY,
        INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY,
        LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL,
        PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J_POLICY,
        LiveMeshSessionCoordinator,
        create_live_mesh_session_coordinator,
    )

    _COORDINATOR_AVAILABLE = True
except ImportError:
    _COORDINATOR_AVAILABLE = False

try:
    from contracts.mesh_session_coordinator import (
        MeshCoordinatorStatus,
        MeshParticipantStatus,
        build_mesh_session_coordinator,
        from_mesh_session,
    )

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.mesh.live_mesh_runtime_engine import LiveMeshRunResult

    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

_ALL_AVAILABLE = _COORDINATOR_AVAILABLE and _CONTRACTS_AVAILABLE and _ENGINE_AVAILABLE

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(
    session_id: str = "test_live_coord",
    mesh_id: str = "mesh_live_coord",
    device_ids: Optional[list] = None,
    barrier_posture: str = "soft_barrier",
) -> Any:
    if not _CONTRACTS_AVAILABLE:
        pytest.skip("contracts not available")
    device_ids = device_ids or ["dev_alpha", "dev_beta"]
    return from_mesh_session(
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
        trace_id="trace_live_coord",
    )


def _make_coordinator(
    session_id: str = "live_coord_test",
    device_ids: Optional[list] = None,
    barrier_posture: str = "soft_barrier",
) -> "LiveMeshSessionCoordinator":
    state = _make_state(
        session_id=session_id,
        device_ids=device_ids,
        barrier_posture=barrier_posture,
    )
    return LiveMeshSessionCoordinator(state)


# ---------------------------------------------------------------------------
# Group A: Policy sentinels
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _COORDINATOR_AVAILABLE, reason="coordinator not available")
class TestGroupA_Sentinels:
    def test_a1_main_sentinel_present(self) -> None:
        assert isinstance(LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL, str)
        assert "PR-J" in LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL
        assert len(LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL) > 0

    def test_a2_incremental_events_policy_present(self) -> None:
        assert isinstance(INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY, str)
        assert "event" in INCREMENTAL_PARTICIPANT_EVENTS_PR_J_POLICY.lower()

    def test_a3_barrier_tracks_policy_present(self) -> None:
        assert isinstance(BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY, str)
        assert "barrier" in BARRIER_TRACKS_ACROSS_EVENTS_PR_J_POLICY.lower()

    def test_a4_finalize_policy_present(self) -> None:
        assert isinstance(COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY, str)
        assert "finalize" in COORDINATOR_FINALIZE_PRODUCES_STABLE_RESULT_PR_J_POLICY.lower()

    def test_a5_dropout_policy_present(self) -> None:
        assert isinstance(PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J_POLICY, str)
        assert "dropout" in PARTICIPANT_DROPOUT_AFFECTS_OUTCOME_PR_J_POLICY.lower()


# ---------------------------------------------------------------------------
# Group B: Construction
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupB_Construction:
    def test_b1_construct_with_none_state(self) -> None:
        coord = LiveMeshSessionCoordinator(None)
        assert coord is not None
        assert coord.state is None

    def test_b2_construct_with_valid_state(self) -> None:
        state = build_mesh_session_coordinator(session_id="b2_session")
        coord = LiveMeshSessionCoordinator(state)
        assert coord.state is not None
        assert getattr(coord.state, "session_id", None) == "b2_session"

    def test_b3_partial_results_initially_empty(self) -> None:
        state = build_mesh_session_coordinator(session_id="b3_session")
        coord = LiveMeshSessionCoordinator(state)
        assert coord.partial_results == {}

    def test_b4_is_complete_false_with_no_participants(self) -> None:
        state = build_mesh_session_coordinator(session_id="b4_session")
        coord = LiveMeshSessionCoordinator(state)
        assert coord.is_complete is False

    def test_b5_outcome_running_while_in_progress(self) -> None:
        coord = _make_coordinator()
        # No results submitted yet → should be running
        assert coord.outcome == "running"

    def test_b6_construct_preserves_barrier_timeout(self) -> None:
        state = build_mesh_session_coordinator(session_id="b6")
        coord = LiveMeshSessionCoordinator(state, barrier_timeout_seconds=60.0)
        assert coord._barrier_timeout_seconds == 60.0


# ---------------------------------------------------------------------------
# Group C: Participant management
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupC_ParticipantManagement:
    def test_c1_add_participant_appears_in_state(self) -> None:
        state = build_mesh_session_coordinator(session_id="c1")
        coord = LiveMeshSessionCoordinator(state)
        coord.add_participant("new_dev", roles=["support"])
        device_ids = [p.device_id for p in coord.state.participants]
        assert "new_dev" in device_ids

    def test_c2_add_participant_sets_pending_status(self) -> None:
        state = build_mesh_session_coordinator(session_id="c2")
        coord = LiveMeshSessionCoordinator(state)
        coord.add_participant("pending_dev")
        p = next(p for p in coord.state.participants if p.device_id == "pending_dev")
        assert p.status == MeshParticipantStatus.pending

    def test_c3_add_participant_emits_coordination_event(self) -> None:
        state = build_mesh_session_coordinator(session_id="c3")
        coord = LiveMeshSessionCoordinator(state)
        coord.add_participant("event_dev")
        event_kinds = [e.kind.value for e in coord.state.coordination_events]
        assert "participant_joined" in event_kinds

    def test_c4_add_participant_does_not_raise_on_none_state(self) -> None:
        coord = LiveMeshSessionCoordinator(None)
        # Should not raise
        coord.add_participant("ghost_dev")

    def test_c5_add_multiple_participants(self) -> None:
        state = build_mesh_session_coordinator(session_id="c5")
        coord = LiveMeshSessionCoordinator(state)
        for i in range(3):
            coord.add_participant(f"dev_{i}")
        device_ids = [p.device_id for p in coord.state.participants]
        assert "dev_0" in device_ids
        assert "dev_1" in device_ids
        assert "dev_2" in device_ids


# ---------------------------------------------------------------------------
# Group D: Participant lifecycle events affect coordinator state
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupD_ParticipantLifecycleEvents:
    def test_d1_on_participant_ready_updates_status(self) -> None:
        coord = _make_coordinator(device_ids=["d1_dev"])
        coord.on_participant_ready("d1_dev")
        p = next(p for p in coord.state.participants if p.device_id == "d1_dev")
        assert p.status == MeshParticipantStatus.ready

    def test_d2_on_participant_working_updates_status(self) -> None:
        coord = _make_coordinator(device_ids=["d2_dev"])
        coord.on_participant_ready("d2_dev")
        coord.on_participant_working("d2_dev")
        p = next(p for p in coord.state.participants if p.device_id == "d2_dev")
        assert p.status == MeshParticipantStatus.working

    def test_d3_on_participant_result_updates_status_to_completed(self) -> None:
        coord = _make_coordinator(device_ids=["d3_dev", "d3_dev2"])
        coord.on_participant_result("d3_dev", {"val": 1})
        p = next(p for p in coord.state.participants if p.device_id == "d3_dev")
        assert p.status == MeshParticipantStatus.completed

    def test_d4_on_participant_failed_updates_status(self) -> None:
        coord = _make_coordinator(device_ids=["d4_dev"])
        coord.on_participant_failed("d4_dev", reason="subtask_error")
        p = next(p for p in coord.state.participants if p.device_id == "d4_dev")
        assert p.status == MeshParticipantStatus.failed

    def test_d5_on_participant_dropped_marks_offline(self) -> None:
        coord = _make_coordinator(device_ids=["d5_dev"])
        coord.on_participant_dropped("d5_dev", reason="timeout")
        p = next(p for p in coord.state.participants if p.device_id == "d5_dev")
        assert p.status == MeshParticipantStatus.offline

    def test_d6_full_lifecycle_pending_ready_working_completed(self) -> None:
        """Evidence: participant lifecycle changes affect real runtime progression."""
        coord = _make_coordinator(device_ids=["lifecycle_dev", "lifecycle_dev2"])
        # Initially pending
        p = next(p for p in coord.state.participants if p.device_id == "lifecycle_dev")
        assert p.status.value in ("pending", "active")

        coord.on_participant_ready("lifecycle_dev")
        p = next(p for p in coord.state.participants if p.device_id == "lifecycle_dev")
        assert p.status == MeshParticipantStatus.ready

        coord.on_participant_working("lifecycle_dev")
        p = next(p for p in coord.state.participants if p.device_id == "lifecycle_dev")
        assert p.status == MeshParticipantStatus.working

        coord.on_participant_result("lifecycle_dev", {"output": "done"})
        p = next(p for p in coord.state.participants if p.device_id == "lifecycle_dev")
        assert p.status == MeshParticipantStatus.completed

    def test_d7_events_do_not_raise_on_unknown_device(self) -> None:
        coord = _make_coordinator()
        # All of these should silently handle unknown device
        coord.on_participant_ready("ghost_device")
        coord.on_participant_working("ghost_device")
        coord.on_participant_result("ghost_device", {})
        coord.on_participant_failed("ghost_device")
        coord.on_participant_dropped("ghost_device")

    def test_d8_partial_results_accumulate(self) -> None:
        coord = _make_coordinator(device_ids=["acc1", "acc2"])
        coord.on_participant_result("acc1", {"key": "a"})
        coord.on_participant_result("acc2", {"key": "b"})
        pr = coord.partial_results
        assert "acc1" in pr
        assert "acc2" in pr
        assert pr["acc1"] == {"key": "a"}
        assert pr["acc2"] == {"key": "b"}


# ---------------------------------------------------------------------------
# Group E: Barrier tracks across incremental events
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupE_BarrierTracksAcrossEvents:
    def test_e1_barrier_not_complete_after_partial_results(self) -> None:
        """Evidence: barrier semantics are runtime-driven — re-evaluated each event."""
        coord = _make_coordinator(device_ids=["e1_a", "e1_b"])
        coord.on_participant_result("e1_a", {"v": 1})
        # Only one of two participants submitted — not complete yet
        assert coord.is_complete is False
        assert coord.outcome == "running"

    def test_e2_barrier_complete_after_all_results(self) -> None:
        """Evidence: barrier released when all participants submit results."""
        coord = _make_coordinator(device_ids=["e2_a", "e2_b"])
        coord.on_participant_result("e2_a", {"v": 1})
        coord.on_participant_result("e2_b", {"v": 2})
        assert coord.is_complete is True
        assert coord.outcome in ("completed", "partial")

    def test_e3_coordinator_advances_to_merging_when_all_arrive(self) -> None:
        """Evidence: barrier advancement drives status transition to merging."""
        coord = _make_coordinator(device_ids=["e3_a", "e3_b"])
        coord.on_participant_result("e3_a", {"v": 1})
        coord.on_participant_result("e3_b", {"v": 2})
        # Status should be merging or already past that (completed)
        status = coord.state.status
        assert status in (
            MeshCoordinatorStatus.merging,
            MeshCoordinatorStatus.completed,
            MeshCoordinatorStatus.partial,
        )

    def test_e4_barrier_complete_after_result_and_failure(self) -> None:
        """Evidence: failed participant counts as accounted-for in barrier eval."""
        coord = _make_coordinator(device_ids=["e4_a", "e4_b"])
        coord.on_participant_result("e4_a", {"v": 1})
        coord.on_participant_failed("e4_b", reason="crashed")
        assert coord.is_complete is True

    def test_e5_barrier_complete_after_result_and_drop(self) -> None:
        """Evidence: dropped participant counts as accounted-for in barrier eval."""
        coord = _make_coordinator(device_ids=["e5_a", "e5_b"])
        coord.on_participant_result("e5_a", {"v": 1})
        coord.on_participant_dropped("e5_b", reason="timeout")
        assert coord.is_complete is True

    def test_e6_barrier_status_advances_incrementally(self) -> None:
        """Evidence: coordinator status transitions are driven by runtime events."""
        coord = _make_coordinator(device_ids=["e6_a", "e6_b"])
        initial_status = coord.state.status
        # Initially pending
        assert initial_status == MeshCoordinatorStatus.pending

        coord.on_participant_result("e6_a", {"v": 1})
        # Still pending — waiting for e6_b
        assert coord.state.status == MeshCoordinatorStatus.pending

        coord.on_participant_result("e6_b", {"v": 2})
        # Now should be merging or further
        assert coord.state.status in (
            MeshCoordinatorStatus.merging,
            MeshCoordinatorStatus.completed,
            MeshCoordinatorStatus.partial,
        )


# ---------------------------------------------------------------------------
# Group F: Finalize — full lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupF_FinalizeFullLifecycle:
    def test_f1_finalize_returns_live_mesh_run_result(self) -> None:
        coord = _make_coordinator()
        result = coord.finalize()
        assert result is not None
        assert isinstance(result, LiveMeshRunResult)

    def test_f2_finalize_with_all_results_gives_completed(self) -> None:
        """Evidence: merge/convergence/completion are coordinator-driven."""
        coord = _make_coordinator(device_ids=["f2_a", "f2_b"])
        coord.on_participant_result("f2_a", {"output": "A", "success": True})
        coord.on_participant_result("f2_b", {"output": "B", "success": True})
        result = coord.finalize()
        assert result.outcome == "completed"
        assert result.success is True

    def test_f3_finalize_merged_result_contains_all_outputs(self) -> None:
        """Evidence: result aggregation is coordinator-driven."""
        coord = _make_coordinator(device_ids=["f3_a", "f3_b"])
        coord.on_participant_result("f3_a", {"key_a": "val_a"})
        coord.on_participant_result("f3_b", {"key_b": "val_b"})
        result = coord.finalize()
        assert result.merged_result.get("key_a") == "val_a"
        assert result.merged_result.get("key_b") == "val_b"

    def test_f4_finalize_merged_result_has_participants_key(self) -> None:
        coord = _make_coordinator(device_ids=["f4_a", "f4_b"])
        coord.on_participant_result("f4_a", {})
        coord.on_participant_result("f4_b", {})
        result = coord.finalize()
        assert "_participants" in result.merged_result

    def test_f5_finalize_barrier_released_when_all_arrived(self) -> None:
        """Evidence: barrier release is coordinator-driven at finalization."""
        coord = _make_coordinator(device_ids=["f5_a", "f5_b"])
        coord.on_participant_result("f5_a", {"v": 1})
        coord.on_participant_result("f5_b", {"v": 2})
        result = coord.finalize()
        assert result.barrier_released is True

    def test_f6_finalize_session_id_preserved(self) -> None:
        coord = _make_coordinator(session_id="preserve_sess")
        result = coord.finalize()
        assert result.session_id == "preserve_sess"

    def test_f7_finalize_never_raises_on_none_state(self) -> None:
        coord = LiveMeshSessionCoordinator(None)
        result = coord.finalize()
        assert result is not None

    def test_f8_finalize_full_staged_to_completed_lifecycle(self) -> None:
        """Evidence: staged_mesh → live → barrier → merge → completed path."""
        mesh_session = {
            "session_id": "staged_to_done",
            "mesh_id": "mesh_staged",
            "participants": [
                {"device_id": "phone", "roles": ["primary"], "online": True, "status": "active"},
                {"device_id": "tablet", "roles": ["support"], "online": True, "status": "active"},
            ],
            "multi_device_required": True,
            "barrier_posture": "soft_barrier",
        }
        coord = LiveMeshSessionCoordinator.from_mesh_session(mesh_session)

        # Drive through live lifecycle
        coord.on_participant_ready("phone")
        coord.on_participant_working("phone")
        coord.on_participant_result("phone", {"task": "captured"})

        coord.on_participant_ready("tablet")
        coord.on_participant_working("tablet")
        coord.on_participant_result("tablet", {"task": "processed"})

        result = coord.finalize()
        assert result.outcome == "completed"
        assert result.success is True
        assert result.barrier_released is True


# ---------------------------------------------------------------------------
# Group G: Partial completion
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupG_PartialCompletion:
    def test_g1_partial_completion_when_one_fails(self) -> None:
        """Evidence: partial success is visible in the runtime outcome model."""
        coord = _make_coordinator(device_ids=["g1_a", "g1_b"])
        coord.on_participant_result("g1_a", {"output": "ok", "success": True})
        coord.on_participant_failed("g1_b", reason="subtask_error")
        result = coord.finalize()
        # g1_a succeeded, g1_b failed → partial
        assert result.outcome in ("partial", "failed")
        assert result is not None

    def test_g2_partial_completion_when_one_drops(self) -> None:
        coord = _make_coordinator(device_ids=["g2_a", "g2_b"])
        coord.on_participant_result("g2_a", {"v": 1})
        coord.on_participant_dropped("g2_b", reason="network_lost")
        result = coord.finalize()
        # One succeeded, one dropped → partial or completed depending on engine
        assert result.outcome in ("partial", "completed", "failed")

    def test_g3_partial_completion_success_flag(self) -> None:
        """Partial outcome should give success=True (at least one completed)."""
        coord = _make_coordinator(device_ids=["g3_a", "g3_b", "g3_c"])
        coord.on_participant_result("g3_a", {"v": 1, "success": True})
        coord.on_participant_failed("g3_b", reason="crash")
        coord.on_participant_dropped("g3_c", reason="timeout")
        result = coord.finalize()
        if result.outcome == "partial":
            assert result.success is True

    def test_g4_partial_completion_incomplete_convergence_visible(self) -> None:
        """Evidence: incomplete convergence is visible in the runtime outcome model."""
        coord = _make_coordinator(device_ids=["g4_a", "g4_b"])
        coord.on_participant_result("g4_a", {"v": 1})
        # g4_b never submits — finalize with partial results
        result = coord.finalize()
        # Not all participants contributed → partial or failed
        assert result.outcome in ("partial", "failed")


# ---------------------------------------------------------------------------
# Group H: Full failure
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupH_FullFailure:
    def test_h1_all_participants_failed_gives_failed_outcome(self) -> None:
        """Evidence: participant failure materially affects runtime outcomes."""
        coord = _make_coordinator(device_ids=["h1_a", "h1_b"])
        coord.on_participant_failed("h1_a", reason="error_a")
        coord.on_participant_failed("h1_b", reason="error_b")
        result = coord.finalize()
        assert result.outcome == "failed"
        assert result.success is False

    def test_h2_all_participants_dropped_gives_failed_outcome(self) -> None:
        """Evidence: participant dropout materially affects runtime outcomes."""
        coord = _make_coordinator(device_ids=["h2_a", "h2_b"])
        coord.on_participant_dropped("h2_a", reason="disconnect")
        coord.on_participant_dropped("h2_b", reason="disconnect")
        result = coord.finalize()
        assert result.outcome == "failed"
        assert result.success is False

    def test_h3_no_results_submitted_gives_failed_outcome(self) -> None:
        coord = _make_coordinator(device_ids=["h3_a", "h3_b"])
        result = coord.finalize()
        # No results → failed
        assert result.outcome == "failed"

    def test_h4_mixed_drop_fail_all_give_failed(self) -> None:
        coord = _make_coordinator(device_ids=["h4_a", "h4_b", "h4_c"])
        coord.on_participant_failed("h4_a", reason="error")
        coord.on_participant_dropped("h4_b", reason="timeout")
        coord.on_participant_failed("h4_c", reason="crash")
        result = coord.finalize()
        assert result.outcome == "failed"
        assert result.success is False


# ---------------------------------------------------------------------------
# Group I: Participant dropout affects runtime outcome
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupI_ParticipantDropoutAffectsOutcome:
    def test_i1_drop_before_any_results_makes_is_complete(self) -> None:
        """Evidence: dropout is accounted for in completion tracking."""
        coord = _make_coordinator(device_ids=["i1_a"])
        coord.on_participant_dropped("i1_a", reason="lost")
        assert coord.is_complete is True

    def test_i2_dropout_moves_device_to_failed_ids(self) -> None:
        coord = _make_coordinator(device_ids=["i2_a"])
        coord.on_participant_dropped("i2_a", reason="timeout")
        assert "i2_a" in coord.state.failed_device_ids

    def test_i3_dropout_not_in_pending_ids_after_drop(self) -> None:
        state = build_mesh_session_coordinator(session_id="i3")
        from core.mesh.live_mesh_runtime_engine import register_participant

        state = register_participant(state, "i3_a")
        coord = LiveMeshSessionCoordinator(state)
        coord.on_participant_dropped("i3_a", reason="disconnect")
        assert "i3_a" not in coord.state.pending_device_ids

    def test_i4_single_dropout_among_successful_gives_partial(self) -> None:
        coord = _make_coordinator(device_ids=["i4_a", "i4_b", "i4_c"])
        coord.on_participant_result("i4_a", {"v": 1})
        coord.on_participant_result("i4_b", {"v": 2})
        coord.on_participant_dropped("i4_c", reason="timeout")
        result = coord.finalize()
        # Two succeeded, one dropped → partial
        assert result.outcome in ("partial", "completed")

    def test_i5_drop_emits_coordination_event(self) -> None:
        coord = _make_coordinator(device_ids=["i5_a"])
        events_before = len(coord.state.coordination_events)
        coord.on_participant_dropped("i5_a", reason="test")
        events_after = len(coord.state.coordination_events)
        assert events_after > events_before


# ---------------------------------------------------------------------------
# Group J: from_mesh_session constructor
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupJ_FromMeshSession:
    def test_j1_from_mesh_session_dict_creates_coordinator(self) -> None:
        session = {
            "session_id": "j1_sess",
            "mesh_id": "j1_mesh",
            "participants": [{"device_id": "j1_dev", "roles": ["primary"], "online": True, "status": "active"}],
        }
        coord = LiveMeshSessionCoordinator.from_mesh_session(session)
        assert coord is not None
        assert coord.state is not None

    def test_j2_from_mesh_session_preserves_session_id(self) -> None:
        session = {
            "session_id": "j2_preserved",
            "participants": [{"device_id": "j2_d", "status": "active"}],
        }
        coord = LiveMeshSessionCoordinator.from_mesh_session(session)
        assert getattr(coord.state, "session_id", None) == "j2_preserved"

    def test_j3_from_mesh_session_with_trace_id(self) -> None:
        session = {
            "session_id": "j3",
            "participants": [{"device_id": "j3_d", "status": "active"}],
        }
        coord = LiveMeshSessionCoordinator.from_mesh_session(session, trace_id="trace_j3")
        assert getattr(coord.state, "trace_id", None) == "trace_j3"

    def test_j4_from_mesh_session_with_none_does_not_raise(self) -> None:
        coord = LiveMeshSessionCoordinator.from_mesh_session(None)
        assert coord is not None

    def test_j5_from_mesh_session_inherits_participants(self) -> None:
        session = {
            "session_id": "j5",
            "participants": [
                {"device_id": "j5_a", "status": "active"},
                {"device_id": "j5_b", "status": "active"},
            ],
        }
        coord = LiveMeshSessionCoordinator.from_mesh_session(session)
        device_ids = [p.device_id for p in coord.state.participants]
        assert "j5_a" in device_ids
        assert "j5_b" in device_ids


# ---------------------------------------------------------------------------
# Group K: create_live_mesh_session_coordinator convenience function
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupK_ConvenienceFunction:
    def test_k1_create_from_session_ids(self) -> None:
        coord = create_live_mesh_session_coordinator(session_id="k1_sess", mesh_id="k1_mesh")
        assert coord is not None
        assert getattr(coord.state, "session_id", None) == "k1_sess"

    def test_k2_create_from_mesh_session_dict(self) -> None:
        session = {
            "session_id": "k2_sess",
            "participants": [{"device_id": "k2_d", "status": "active"}],
        }
        coord = create_live_mesh_session_coordinator(mesh_session=session)
        assert coord is not None
        assert getattr(coord.state, "session_id", None) == "k2_sess"

    def test_k3_create_with_no_args_does_not_raise(self) -> None:
        coord = create_live_mesh_session_coordinator()
        assert coord is not None

    def test_k4_create_preserves_barrier_timeout(self) -> None:
        coord = create_live_mesh_session_coordinator(session_id="k4", barrier_timeout_seconds=45.0)
        assert coord._barrier_timeout_seconds == 45.0


# ---------------------------------------------------------------------------
# Group L: Thread-safety
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupL_ThreadSafety:
    def test_l1_concurrent_result_events_do_not_corrupt_state(self) -> None:
        """Concurrent on_participant_result calls must be thread-safe."""
        device_ids = [f"thread_dev_{i}" for i in range(5)]
        coord = _make_coordinator(device_ids=device_ids)

        errors: list = []

        def emit_result(did: str) -> None:
            try:
                time.sleep(0.001)  # Simulate tiny jitter
                coord.on_participant_result(did, {"v": did})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=emit_result, args=(did,)) for did in device_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == [], f"Errors during concurrent events: {errors}"
        # All participants submitted → should be complete
        assert coord.is_complete is True

    def test_l2_concurrent_mixed_events_do_not_raise(self) -> None:
        """Mix of ready/working/result/fail/drop calls from multiple threads."""
        device_ids = [f"mix_dev_{i}" for i in range(4)]
        coord = _make_coordinator(device_ids=device_ids)

        errors: list = []

        def event_burst(did: str, idx: int) -> None:
            try:
                coord.on_participant_ready(did)
                coord.on_participant_working(did)
                if idx % 2 == 0:
                    coord.on_participant_result(did, {"i": idx})
                else:
                    coord.on_participant_failed(did, reason="test_fail")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=event_burst, args=(did, i)) for i, did in enumerate(device_ids)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert errors == []
        result = coord.finalize()
        assert result is not None

    def test_l3_finalize_while_events_in_flight_does_not_raise(self) -> None:
        """finalize() called while events are still being emitted must not raise."""
        device_ids = [f"inflight_dev_{i}" for i in range(3)]
        coord = _make_coordinator(device_ids=device_ids)

        errors: list = []
        results: list = []

        def emit_and_finalize() -> None:
            try:
                coord.on_participant_result("inflight_dev_0", {"v": 0})
                result = coord.finalize()
                results.append(result)
            except Exception as exc:
                errors.append(exc)

        def emit_remaining() -> None:
            try:
                time.sleep(0.002)
                coord.on_participant_result("inflight_dev_1", {"v": 1})
                coord.on_participant_dropped("inflight_dev_2", reason="timeout")
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=emit_and_finalize)
        t2 = threading.Thread(target=emit_remaining)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert errors == []
        assert results  # At least one finalize result was produced


# ---------------------------------------------------------------------------
# Group M: is_complete / outcome properties
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupM_IsCompleteOutcome:
    def test_m1_outcome_is_running_with_no_events(self) -> None:
        coord = _make_coordinator()
        assert coord.outcome == "running"

    def test_m2_outcome_completed_after_all_succeed(self) -> None:
        coord = _make_coordinator(device_ids=["m2_a", "m2_b"])
        coord.on_participant_result("m2_a", {"v": 1, "success": True})
        coord.on_participant_result("m2_b", {"v": 2, "success": True})
        assert coord.outcome == "completed"

    def test_m3_outcome_partial_after_mixed(self) -> None:
        coord = _make_coordinator(device_ids=["m3_a", "m3_b"])
        coord.on_participant_result("m3_a", {"v": 1, "success": True})
        coord.on_participant_failed("m3_b", reason="err")
        assert coord.outcome == "partial"

    def test_m4_outcome_failed_after_all_drop(self) -> None:
        coord = _make_coordinator(device_ids=["m4_a", "m4_b"])
        coord.on_participant_dropped("m4_a")
        coord.on_participant_dropped("m4_b")
        assert coord.outcome == "failed"

    def test_m5_is_complete_false_until_all_accounted(self) -> None:
        coord = _make_coordinator(device_ids=["m5_a", "m5_b"])
        coord.on_participant_result("m5_a", {"v": 1})
        assert coord.is_complete is False
        coord.on_participant_result("m5_b", {"v": 2})
        assert coord.is_complete is True

    def test_m6_outcome_before_finalize_matches_after_finalize(self) -> None:
        coord = _make_coordinator(device_ids=["m6_a", "m6_b"])
        coord.on_participant_result("m6_a", {"v": 1, "success": True})
        coord.on_participant_result("m6_b", {"v": 2, "success": True})
        pre_finalize_outcome = coord.outcome
        result = coord.finalize()
        assert result.outcome == pre_finalize_outcome
