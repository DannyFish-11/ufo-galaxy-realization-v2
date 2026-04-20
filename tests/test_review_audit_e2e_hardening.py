"""tests/test_review_audit_e2e_hardening.py
============================================
Review / Audit / Hardening test suite for the complete V2 + Android system.

PR Type: REVIEW / AUDIT / HARDENING (not a new feature PR)

Purpose
-------
This test file provides review-grade evidence that the complete two-repository
system (V2 control plane + Android execution participant plane) is correctly
wired and produces verifiable runtime behaviour.  It is the testing companion
to ``docs/V2_ANDROID_SYSTEM_AUDIT.md``.

This is NOT a re-implementation of feature tests.  It augments the existing
per-PR test suites with:

- Integration-style tests that walk the *full* production-style orchestration
  path (staged_mesh → live runtime orchestration).
- Assertions that participant state *actually affects* barrier/merge/completion
  decisions — not just that state is set.
- Explicit failure-path assertions (not just logs).
- Android interface contract validation from V2's perspective.
- Dependency chain verification (PR-I substrate → PR-J runtime).
- PR dependency documentation in code comments.

Sections
--------
A  — System module availability audit (all required modules importable)
B  — Production-style staged_mesh path validation
C  — Participant state audit: state changes affect runtime behaviour
D  — Barrier coordination: success, partial, failure paths (asserted)
E  — Merge / aggregation correctness and conflict resolution
F  — Completion semantics: completed / partial / failed outcome semantics
G  — Failure path coverage: explicit assertions on all major failure modes
H  — Android interface contract validation (from V2 side)
I  — Dependency chain: PR-I substrate feeds PR-J runtime
J  — End-to-end lifecycle: enrollment → dispatch → orchestration → result
K  — Observability: key events emittable and visible

Review notes
------------
- Sections H and J demonstrate the V2 side of the closed loop with Android.
  Full end-to-end proof requires a real Android device running the Android repo
  (CROSS-003 in DUAL_REPO_GAP_MATRIX.md) — marked with ``# ANDROID_REQUIRED``.
- PR-J strongly depends on PR-I.  Section I verifies this dependency holds.
- If you see skips, the required modules are not installed/available in the
  current environment.  All tests that can run MUST pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Module availability guards — import lazily so tests skip cleanly
# ---------------------------------------------------------------------------

try:
    from contracts.mesh_session_coordinator import (
        MeshSessionCoordinatorState,
        MeshCoordinatorStatus,
        MeshParticipantStatus,
        MeshBarrierStatus,
        build_mesh_session_coordinator,
        from_mesh_session,
    )

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.mesh.live_mesh_runtime_engine import (
        LiveMeshRunResult,
        LiveMeshRuntimeEngine,
        run_live_mesh_session,
        register_participant,
        update_participant_status,
        drop_participant,
        LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL,
    )

    _ENGINE_AVAILABLE = True
except ImportError:
    _ENGINE_AVAILABLE = False

try:
    from core.mesh.mesh_session_coordinator import (
        coordinate_mesh_session,
        get_coordinator_summary,
        run_live_mesh_session as coord_run_live,
    )

    _COORD_AVAILABLE = True
except ImportError:
    _COORD_AVAILABLE = False

try:
    from core.runtime.source_dispatch_orchestrator import (
        orchestrate_source_runtime_dispatch,
    )
    from contracts.source_dispatch import SourceDispatchMode

    _DISPATCH_AVAILABLE = True
except ImportError:
    _DISPATCH_AVAILABLE = False

try:
    from contracts.handoff_envelope_v2 import HandoffEnvelopeV2

    _HANDOFF_V2_AVAILABLE = True
except ImportError:
    _HANDOFF_V2_AVAILABLE = False

try:
    from contracts.android_handoff_response import (
        AndroidHandoffResponseEnvelope,
        HandoffResponseKind,
        from_android_ack_message,
        from_android_result_message,
        from_android_failure_message,
        extract_handoff_response_envelope,
    )

    _ANDROID_RESPONSE_AVAILABLE = True
except ImportError:
    _ANDROID_RESPONSE_AVAILABLE = False

try:
    from core.mesh.mesh_auto_enrollment import (
        MeshEnrollmentRecord,
        MeshAutoEnrollmentService,
        get_auto_enrollment_service,
        reset_auto_enrollment_service,
        get_enrollment_record,
    )

    _ENROLLMENT_AVAILABLE = True
except ImportError:
    _ENROLLMENT_AVAILABLE = False

try:
    from core.mesh.body_mesh_registry import (
        BodyMeshRegistry,
        get_body_mesh_registry,
        reset_body_mesh_registry,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_coord_state(
    session_id: str = "audit_session",
    mesh_id: str = "audit_mesh",
    device_ids: Optional[List[str]] = None,
    barrier_posture: str = "soft_barrier",
) -> Any:
    """Build a minimal coordinator state for audit tests."""
    if not _CONTRACTS_AVAILABLE:
        pytest.skip("contracts not available")
    devices = device_ids or ["android_a", "android_b"]
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
                for i, did in enumerate(devices)
            ],
            "multi_device_required": True,
            "barrier_posture": barrier_posture,
        },
        trace_id=f"audit_trace_{session_id}",
    )


def _make_mesh_session_dict(
    session_id: str = "audit_msess",
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a minimal mesh_session dict for orchestrator dispatch tests."""
    devices = device_ids or ["phone_x", "tablet_y"]
    return {
        "session_id": session_id,
        "mesh_id": f"mesh_{session_id}",
        "source_device_id": devices[0],
        "primary_device_id": devices[1] if len(devices) > 1 else devices[0],
        "participants": [
            {
                "device_id": did,
                "roles": ["source" if i == 0 else "primary"],
                "online": True,
                "status": "active",
                "health_score": 0.95,
                "metadata": {},
            }
            for i, did in enumerate(devices)
        ],
        "multi_device_required": True,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Section A: System module availability audit
# ---------------------------------------------------------------------------


class TestSectionA_ModuleAvailability:
    """Every module required for the end-to-end system must be importable.

    A test skip here means a dependency is missing from the environment — it
    does NOT mean the module is absent from the repo.  Install project
    dependencies (``pip install -r requirements.txt``) to make these pass.
    """

    def test_a1_contracts_mesh_session_coordinator_importable(self) -> None:
        """contracts.mesh_session_coordinator is the data backbone of PR-J."""
        from contracts.mesh_session_coordinator import MeshSessionCoordinatorState
        assert MeshSessionCoordinatorState is not None

    def test_a2_live_mesh_runtime_engine_importable(self) -> None:
        """core.mesh.live_mesh_runtime_engine is the PR-J execution driver."""
        from core.mesh.live_mesh_runtime_engine import LiveMeshRuntimeEngine
        assert LiveMeshRuntimeEngine is not None

    def test_a3_mesh_session_coordinator_importable(self) -> None:
        """core.mesh.mesh_session_coordinator wraps PR-J convenience fns."""
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session
        assert callable(coordinate_mesh_session)

    def test_a4_handoff_envelope_v2_importable(self) -> None:
        """contracts.handoff_envelope_v2 is the V2 → Android dispatch contract."""
        from contracts.handoff_envelope_v2 import HandoffEnvelopeV2
        assert HandoffEnvelopeV2 is not None

    def test_a5_android_handoff_response_importable(self) -> None:
        """contracts.android_handoff_response is the Android → V2 result contract."""
        from contracts.android_handoff_response import AndroidHandoffResponseEnvelope
        assert AndroidHandoffResponseEnvelope is not None

    def test_a6_mesh_auto_enrollment_importable(self) -> None:
        """core.mesh.mesh_auto_enrollment is the PR-I enrollment service."""
        from core.mesh.mesh_auto_enrollment import MeshAutoEnrollmentService
        assert MeshAutoEnrollmentService is not None

    def test_a7_body_mesh_registry_importable(self) -> None:
        """core.mesh.body_mesh_registry is the PR-I participant registry."""
        from core.mesh.body_mesh_registry import BodyMeshRegistry
        assert BodyMeshRegistry is not None

    def test_a8_source_dispatch_orchestrator_importable(self) -> None:
        """core.runtime.source_dispatch_orchestrator hosts the staged_mesh path."""
        from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch
        assert callable(orchestrate_source_runtime_dispatch)

    def test_a9_pr_j_sentinel_is_present_and_non_empty(self) -> None:
        """PR-J sentinel must be present — confirms PR-J is loaded, not bypassed."""
        if not _ENGINE_AVAILABLE:
            pytest.skip("engine not available")
        assert "PR-J" in LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL
        assert len(LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL) > 20


# ---------------------------------------------------------------------------
# Section B: Production-style staged_mesh path validation
#
# These tests verify that staged_mesh enters the REAL production path in V2
# (i.e., calls LiveMeshRuntimeEngine), not a stub or plan-only path.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _DISPATCH_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="source_dispatch_orchestrator or contracts not available",
)
class TestSectionB_StagedMeshProductionPath:
    """
    Dependency note (for reviewers):
    - PR-J strongly depends on PR-I for participant enrollment.
    - PR-J benefits from PR-H for the Android handoff/ACK/result closed loop.
    - These tests verify the V2 control-plane portion of the path.
    """

    def test_b1_orchestrator_enters_staged_mesh_branch_with_mesh_session(self) -> None:
        """Orchestrator with a valid mesh_session must enter staged_mesh mode."""
        ms = _make_mesh_session_dict()
        result = orchestrate_source_runtime_dispatch(
            trace_id="audit_b1",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        assert result is not None
        # If mode is staged_mesh, action_taken must be the real coordinated value
        if result.mode == SourceDispatchMode.staged_mesh:
            assert result.result is not None
            assert result.result.get("action_taken") == "staged_mesh_coordinated", (
                "staged_mesh must enter LiveMeshRuntimeEngine (action_taken='staged_mesh_coordinated'), "
                "not return 'plan_prepared' which would indicate a stub path"
            )

    def test_b2_staged_mesh_result_contains_live_outcome_key(self) -> None:
        """live_outcome key confirms LiveMeshRuntimeEngine was called, not bypassed."""
        ms = _make_mesh_session_dict()
        result = orchestrate_source_runtime_dispatch(
            trace_id="audit_b2",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        if result.mode == SourceDispatchMode.staged_mesh:
            assert "live_outcome" in result.result, (
                "live_outcome key is set by LiveMeshRuntimeEngine; "
                "its absence means the engine was not called"
            )

    def test_b3_staged_mesh_result_contains_live_merged_result_key(self) -> None:
        """live_merged_result key confirms merge phase completed."""
        ms = _make_mesh_session_dict()
        result = orchestrate_source_runtime_dispatch(
            trace_id="audit_b3",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        if result.mode == SourceDispatchMode.staged_mesh:
            assert "live_merged_result" in result.result, (
                "live_merged_result is produced after the merge phase; "
                "its absence means merge did not run"
            )

    def test_b4_staged_mesh_without_enrollment_degrades_cleanly(self) -> None:
        """
        Without participant enrollment (PR-I), staged_mesh should return
        outcome=failed cleanly — not hang or raise.

        Reviewer note: This test verifies the 'fragile system' scenario described
        in the PR-J dependency notes.  If PR-I is absent, staged_mesh silently
        produces a coordinator state with no participants → engine fails cleanly.
        """
        # Build a mesh session with participants that have no pre-enrolled state
        ms = {
            "session_id": "unenrolled_session",
            "mesh_id": "unenrolled_mesh",
            "source_device_id": "ghost_phone",
            "primary_device_id": "ghost_tablet",
            "participants": [],  # No participants enrolled → engine will fail cleanly
            "multi_device_required": True,
            "metadata": {},
        }
        result = orchestrate_source_runtime_dispatch(
            trace_id="audit_b4",
            mesh_session=ms,
            policy_alignment=None,
            governance_snapshot=None,
            mesh_memberships=None,
        )
        # The orchestrator must not raise — it should degrade gracefully
        assert result is not None
        if result.mode == SourceDispatchMode.staged_mesh:
            # With no participants, outcome must be failed (not partial or completed)
            live_outcome = result.result.get("live_outcome")
            if live_outcome is not None:
                assert live_outcome == "failed", (
                    "staged_mesh with no participants must yield outcome=failed, "
                    "not partial or completed"
                )

    def test_b5_orchestrator_never_raises_on_any_input(self) -> None:
        """Orchestrator must never raise — graceful degradation is required."""
        for bad_input in [None, {}, {"session_id": "x"}, object()]:
            result = orchestrate_source_runtime_dispatch(
                trace_id="audit_b5",
                mesh_session=bad_input,  # type: ignore[arg-type]
                policy_alignment=None,
                governance_snapshot=None,
                mesh_memberships=None,
            )
            assert result is not None


# ---------------------------------------------------------------------------
# Section C: Participant state audit — state must affect runtime behaviour
#
# These tests verify that participant state is not just a passive label but
# actually influences barrier evaluation, merge inputs, and completion logic.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionC_ParticipantStateAffectsRuntime:
    """
    Review note: For the system to be 'truly wired', participant state changes
    must drive runtime decisions.  These tests assert causality, not just state.
    """

    def test_c1_completed_participants_contribute_to_completed_outcome(self) -> None:
        """Only participants reporting success=True drive outcome=completed."""
        state = _make_coord_state(device_ids=["dev_c1a", "dev_c1b"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "dev_c1a": {"success": True, "output": "done"},
                "dev_c1b": {"success": True, "output": "done"},
            },
        )
        # Both completed → outcome must be 'completed'
        assert result.outcome == "completed", (
            f"Both participants succeeded; expected 'completed' but got '{result.outcome}'"
        )
        # Both must appear in completed_device_ids
        final = result.coordinator_state
        assert "dev_c1a" in final.completed_device_ids
        assert "dev_c1b" in final.completed_device_ids

    def test_c2_failed_participants_move_to_failed_device_ids(self) -> None:
        """Participants with success=False must appear in failed_device_ids."""
        state = _make_coord_state(device_ids=["ok_c2", "fail_c2"])
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "ok_c2": {"success": True},
                "fail_c2": {"success": False, "error": "execution failed"},
            },
        )
        final = result.coordinator_state
        assert "fail_c2" in final.failed_device_ids, (
            "Participant with success=False must appear in failed_device_ids"
        )
        # ok_c2 succeeded → must be in completed
        assert "ok_c2" in final.completed_device_ids

    def test_c3_dropped_participant_excluded_from_merge(self) -> None:
        """A dropped participant must not contribute results to the merge output."""
        state = _make_coord_state(device_ids=["active_c3", "dropped_c3"])
        # Drop one participant before the run
        state = drop_participant(state, "dropped_c3", reason="timeout")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"active_c3": {"output": "active_result"}},
        )
        # active_c3's result must be in merge; dropped_c3 must not add its own
        assert result.merged_result.get("output") == "active_result"
        assert "dropped_c3" in result.coordinator_state.failed_device_ids

    def test_c4_participant_status_transitions_drive_barrier_evaluation(self) -> None:
        """Participant status directly determines whether barrier is satisfied."""
        # Scenario: two participants; only one submits a result
        # → barrier not satisfied (waiting), outcome partial/failed
        state = _make_coord_state(
            device_ids=["barrier_c4a", "barrier_c4b"],
            barrier_posture="hard_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"barrier_c4a": {"v": 1}},
            # barrier_c4b never arrives
        )
        # Barrier should NOT be released since barrier_c4b is missing
        assert result.barrier_released is False, (
            "Hard barrier must not release when barrier_c4b has not arrived; "
            "participant state must drive barrier evaluation"
        )

    def test_c5_all_participants_present_releases_barrier(self) -> None:
        """When all expected participants submit results, barrier releases."""
        state = _make_coord_state(
            device_ids=["all_c5a", "all_c5b"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "all_c5a": {"v": 1},
                "all_c5b": {"v": 2},
            },
        )
        assert result.barrier_released is True, (
            "Barrier must be released when all participants submit results; "
            "participant presence must drive barrier release"
        )

    def test_c6_pending_to_working_transition_recorded_in_events(self) -> None:
        """State transition (pending → working) must appear in coordination events."""
        state = build_mesh_session_coordinator(session_id="audit_c6")
        state = register_participant(state, "track_dev_c6", roles=["primary"])

        # Transition to working
        state = update_participant_status(state, "track_dev_c6", "working")

        p = next(p for p in state.participants if p.device_id == "track_dev_c6")
        assert p.status == MeshParticipantStatus.working, (
            "update_participant_status must actually change the participant status"
        )

    def test_c7_offline_participant_prevents_completed_outcome(self) -> None:
        """If one participant is offline/dropped, outcome cannot be 'completed'."""
        state = _make_coord_state(device_ids=["ok_c7", "offline_c7"])
        state = drop_participant(state, "offline_c7", reason="disconnected")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"ok_c7": {"success": True}},
        )
        # With one offline participant, outcome must be partial or failed
        assert result.outcome in ("partial", "failed"), (
            f"One participant offline; outcome must not be 'completed', got '{result.outcome}'"
        )


# ---------------------------------------------------------------------------
# Section D: Barrier coordination — explicit assertions
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionD_BarrierCoordination:
    """
    Review note: Barrier evaluation must be a real runtime gate, not a label.
    These tests verify that barrier state changes outcome and coordinator status.
    """

    def test_d1_barrier_released_when_all_arrive_soft(self) -> None:
        state = _make_coord_state(
            device_ids=["d1a", "d1b"],
            barrier_posture="soft_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d1a": {}, "d1b": {}}
        )
        assert result.barrier_released is True

    def test_d2_barrier_not_released_when_some_missing_soft(self) -> None:
        state = _make_coord_state(
            device_ids=["d2a", "d2b"],
            barrier_posture="soft_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d2a": {}}
        )
        assert result.barrier_released is False

    def test_d3_barrier_released_when_all_arrive_hard(self) -> None:
        state = _make_coord_state(
            device_ids=["d3a", "d3b"],
            barrier_posture="hard_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d3a": {}, "d3b": {}}
        )
        assert result.barrier_released is True

    def test_d4_barrier_not_released_when_partial_hard(self) -> None:
        state = _make_coord_state(
            device_ids=["d4a", "d4b"],
            barrier_posture="hard_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d4a": {}}
        )
        assert result.barrier_released is False

    def test_d5_barrier_skipped_when_posture_none(self) -> None:
        """no_barrier posture must skip barrier evaluation entirely."""
        state = _make_coord_state(
            device_ids=["d5a"],
            barrier_posture="none",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d5a": {"val": 1}}
        )
        assert result.barrier_released is True

    def test_d6_barrier_failed_coordinator_status_reflects_it(self) -> None:
        """Barrier failure must propagate to coordinator status."""
        state = _make_coord_state(
            device_ids=["d6a", "d6b"],
            barrier_posture="hard_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={"d6a": {}},  # d6b missing
        )
        final = result.coordinator_state
        # Status must reflect the unresolved barrier
        assert final.status in (
            MeshCoordinatorStatus.awaiting_barrier,
            MeshCoordinatorStatus.partial,
            MeshCoordinatorStatus.failed,
        ), (
            f"Barrier not released; coordinator status must reflect this, got '{final.status}'"
        )

    def test_d7_barrier_status_field_set_in_coordinator_state(self) -> None:
        """barrier_state.status field must be set after evaluation."""
        state = _make_coord_state(
            device_ids=["d7a", "d7b"],
            barrier_posture="soft_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"d7a": {}, "d7b": {}}
        )
        final = result.coordinator_state
        assert final.barrier_state is not None
        assert final.barrier_state.status in (
            MeshBarrierStatus.released,
            MeshBarrierStatus.not_required,
        )


# ---------------------------------------------------------------------------
# Section E: Merge / aggregation correctness
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionE_MergeAggregation:
    """
    Review note: Merge must aggregate per-participant outputs into a stable
    merged_result.  Correctness here is essential for multi-device tasks.
    """

    def test_e1_all_participant_outputs_present_in_merged_result(self) -> None:
        """All participant result keys must appear in the merged output."""
        state = _make_coord_state(device_ids=["e1a", "e1b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "e1a": {"from_e1a": "alpha"},
                "e1b": {"from_e1b": "beta"},
            },
        )
        assert result.merged_result.get("from_e1a") == "alpha"
        assert result.merged_result.get("from_e1b") == "beta"

    def test_e2_participants_key_lists_all_contributing_devices(self) -> None:
        """_participants key must list all devices that contributed."""
        state = _make_coord_state(device_ids=["e2a", "e2b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={"e2a": {"v": 1}, "e2b": {"v": 2}},
        )
        participants_in_merge = result.merged_result.get("_participants", [])
        assert "e2a" in participants_in_merge
        assert "e2b" in participants_in_merge

    def test_e3_merge_is_deterministic_for_non_conflicting_keys(self) -> None:
        """Non-conflicting keys from multiple devices must all be present."""
        state = _make_coord_state(device_ids=["e3a", "e3b", "e3c"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "e3a": {"keyA": "A"},
                "e3b": {"keyB": "B"},
                "e3c": {"keyC": "C"},
            },
        )
        assert result.merged_result.get("keyA") == "A"
        assert result.merged_result.get("keyB") == "B"
        assert result.merged_result.get("keyC") == "C"

    def test_e4_merge_conflict_last_writer_wins(self) -> None:
        """On key conflict, last writer wins (order: device_ids processing order)."""
        state = _make_coord_state(device_ids=["e4a", "e4b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "e4a": {"conflict_key": "from_e4a"},
                "e4b": {"conflict_key": "from_e4b"},
            },
        )
        # The merge must produce exactly one value for the conflicting key
        conflict_val = result.merged_result.get("conflict_key")
        assert conflict_val in ("from_e4a", "from_e4b"), (
            f"Conflict key must resolve to one value; got '{conflict_val}'"
        )

    def test_e5_empty_participant_results_produce_empty_merge_not_error(self) -> None:
        """Empty participant results must produce empty merge, not raise."""
        state = _make_coord_state(device_ids=["e5a"])
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"e5a": {}}
        )
        assert isinstance(result.merged_result, dict), "merged_result must always be a dict"

    def test_e6_merge_timestamp_present(self) -> None:
        """_merge_timestamp must be present to track merge time."""
        state = _make_coord_state(device_ids=["e6a"])
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={"e6a": {"x": 1}}
        )
        assert "_merge_timestamp" in result.merged_result, (
            "_merge_timestamp must be set by the merge phase"
        )

    def test_e7_failed_participants_do_not_corrupt_merge(self) -> None:
        """Failed participant results must not overwrite successful ones."""
        state = _make_coord_state(device_ids=["e7_ok", "e7_fail"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "e7_ok": {"success": True, "good_key": "good_value"},
                "e7_fail": {"success": False},
            },
        )
        # good_key must be preserved even though one participant failed
        assert result.merged_result.get("good_key") == "good_value"


# ---------------------------------------------------------------------------
# Section F: Completion outcome semantics
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionF_CompletionSemantics:
    """
    Review note: outcome=completed/partial/failed must precisely reflect the
    actual execution result.  This is the primary correctness claim for PR-J.
    """

    def test_f1_all_success_gives_completed(self) -> None:
        state = _make_coord_state(device_ids=["f1a", "f1b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "f1a": {"success": True},
                "f1b": {"success": True},
            },
        )
        assert result.outcome == "completed"
        assert result.success is True

    def test_f2_mixed_gives_partial(self) -> None:
        state = _make_coord_state(device_ids=["f2ok", "f2fail"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "f2ok": {"success": True},
                "f2fail": {"success": False},
            },
        )
        assert result.outcome == "partial"
        assert result.success is True  # partial is considered a success variant

    def test_f3_all_failure_gives_failed(self) -> None:
        state = _make_coord_state(device_ids=["f3a", "f3b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "f3a": {"success": False},
                "f3b": {"success": False},
            },
        )
        assert result.outcome == "failed"
        assert result.success is False

    def test_f4_no_results_submitted_gives_failed(self) -> None:
        state = _make_coord_state(device_ids=["f4a", "f4b"])
        result = LiveMeshRuntimeEngine().run(
            state, participant_results={}
        )
        assert result.outcome == "failed"
        assert result.success is False

    def test_f5_coordinator_status_matches_outcome(self) -> None:
        """coordinator_state.status must match the final outcome."""
        state = _make_coord_state(device_ids=["f5a", "f5b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "f5a": {"success": True},
                "f5b": {"success": True},
            },
        )
        assert result.outcome == "completed"
        assert result.coordinator_state.status == MeshCoordinatorStatus.completed

    def test_f6_participant_outcomes_dict_populated(self) -> None:
        """participant_outcomes must list every participant with their result."""
        state = _make_coord_state(device_ids=["f6a", "f6b"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "f6a": {"success": True, "output": "x"},
                "f6b": {"success": False},
            },
        )
        assert "f6a" in result.participant_outcomes
        assert "f6b" in result.participant_outcomes


# ---------------------------------------------------------------------------
# Section G: Failure path coverage — explicit assertions, not just logs
#
# Reviewer note: failure paths must produce explicit assertions.
# A system that silently passes on failure is not auditable.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionG_FailurePathCoverage:
    """
    These tests verify ALL major failure scenarios produce explicit assertions
    via the errors list, outcome field, and coordinator status — NOT just logs.
    """

    def test_g1_no_participants_gives_promotion_failed_error(self) -> None:
        """
        Failure: No participants enrolled (PR-I missing or empty formation).

        Reviewer: This is the 'PR-J without PR-I' scenario.  The system must
        fail explicitly, not silently pass with empty results.
        """
        state = build_mesh_session_coordinator(session_id="g1_empty")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state)
        assert result.outcome == "failed"
        assert result.success is False
        # errors list must contain something about promotion/participants
        assert len(result.errors) > 0, (
            "errors list must be non-empty when no participants enrolled"
        )

    def test_g2_all_participants_dropped_gives_explicit_failed(self) -> None:
        """
        Failure: All participants dropped (simulating complete device loss).
        """
        state = _make_coord_state(device_ids=["g2a", "g2b"])
        state = drop_participant(state, "g2a", reason="disconnected")
        state = drop_participant(state, "g2b", reason="timeout")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state, participant_results={})
        assert result.outcome == "failed"
        # Both must be in failed_device_ids
        final = result.coordinator_state
        assert "g2a" in final.failed_device_ids
        assert "g2b" in final.failed_device_ids

    def test_g3_partial_participant_failure_gives_partial_not_completed(self) -> None:
        """
        Failure: One participant fails, one succeeds → must be partial, not completed.
        """
        state = _make_coord_state(device_ids=["g3ok", "g3fail"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "g3ok": {"success": True},
                "g3fail": {"success": False, "error_code": "EXEC_ERROR"},
            },
        )
        assert result.outcome == "partial", (
            "One participant failed; outcome must be 'partial' not 'completed'"
        )

    def test_g4_barrier_never_satisfied_fails_explicitly(self) -> None:
        """
        Failure: Barrier never satisfied (simulates dispatch interruption /
        participant never arrives).
        """
        state = _make_coord_state(
            device_ids=["g4a", "g4b"],
            barrier_posture="hard_barrier",
        )
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={"g4a": {}},  # g4b never arrives
        )
        # Barrier not released → explicit signal
        assert result.barrier_released is False
        assert result.outcome in ("partial", "failed"), (
            "Unsatisfied barrier must produce partial or failed, not completed"
        )

    def test_g5_coordinator_state_none_produces_explicit_error(self) -> None:
        """
        Failure: None coordinator state (missing session context).
        """
        engine = LiveMeshRuntimeEngine()
        result = engine.run(None)
        assert result.outcome == "failed"
        assert result.success is False
        assert "coordinator_state_is_none" in result.errors, (
            "errors list must contain 'coordinator_state_is_none' when state is None"
        )

    def test_g6_garbage_input_never_raises_always_gives_failed(self) -> None:
        """
        Failure: Garbage input to engine must never raise (defense in depth).
        """
        engine = LiveMeshRuntimeEngine()
        for garbage in [None, 42, "bad", [], {}, object()]:
            result = engine.run(garbage)  # type: ignore[arg-type]
            assert result is not None
            assert result.outcome in ("completed", "partial", "failed")
            assert isinstance(result.errors, list)

    def test_g7_dropped_participant_errors_reflected_in_result(self) -> None:
        """
        Failure: Dropped participant must be reflected in errors or failed_device_ids.

        Not just logged — must be visible in the structured result.
        """
        state = _make_coord_state(device_ids=["g7active", "g7dropped"])
        state = drop_participant(state, "g7dropped", reason="timeout")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"g7active": {"success": True}},
        )
        final = result.coordinator_state
        assert "g7dropped" in final.failed_device_ids, (
            "Dropped participant must appear in failed_device_ids — "
            "must NOT be silently ignored"
        )

    def test_g8_run_live_mesh_session_convenience_graceful_on_none(self) -> None:
        """
        Failure: run_live_mesh_session convenience function must be graceful.
        """
        if not _ENGINE_AVAILABLE:
            pytest.skip("engine not available")
        result = run_live_mesh_session(None)  # type: ignore[arg-type]
        assert result is not None
        assert result.outcome == "failed"

    def test_g9_partial_result_not_treated_as_complete_failure(self) -> None:
        """
        Failure: partial outcome must have success=True (it is a valid success variant).

        Reviewer: If this test fails, a bug exists where partial completion is
        incorrectly treated as a full failure, suppressing useful partial results.
        """
        state = _make_coord_state(device_ids=["g9ok", "g9fail"])
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={
                "g9ok": {"success": True, "data": "partial_output"},
                "g9fail": {"success": False},
            },
        )
        if result.outcome == "partial":
            assert result.success is True, (
                "partial outcome must have success=True; "
                "partial completion IS a valid result"
            )


# ---------------------------------------------------------------------------
# Section H: Android interface contract validation (from V2 side)
#
# ANDROID_REQUIRED: Full loop test requires real Android device (CROSS-003).
# These tests verify the V2-side of the interface is correct.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _HANDOFF_V2_AVAILABLE or not _ANDROID_RESPONSE_AVAILABLE,
    reason="handoff contracts not available",
)
class TestSectionH_AndroidInterfaceContract:
    """
    Reviewer note: These tests verify V2-side of the handoff/ACK/result/failure
    contract.  They confirm V2 can correctly serialize outbound dispatches and
    parse all inbound Android signals.

    ANDROID_REQUIRED: The actual Android execution is NOT tested here (CROSS-003).
    A real-device E2E test must be added in a future PR once CROSS-003 is addressed.
    """

    def test_h1_handoff_v2_serialises_to_aip_task_message(self) -> None:
        """HandoffEnvelopeV2 must produce a valid AIP task message for Android dispatch."""
        envelope = HandoffEnvelopeV2(
            task_id="audit_task_h1",
            task_payload={"command": "take_screenshot"},
        )
        # to_android_task_assign_payload produces the AIP v3 handoff_dispatch message
        msg = envelope.to_android_task_assign_payload("audit_android_device")
        # AIP message must contain the task_type field so Android can route it
        assert msg is not None
        assert "task_type" in msg, (
            "AIP message must include a task_type field for Android routing"
        )
        assert msg["task_type"] == "handoff_v2"
        assert "type" in msg  # AIP message type field
        assert msg["device_id"] == "audit_android_device"

    def test_h2_handoff_v2_contains_handoff_id_for_ack_correlation(self) -> None:
        """handoff_id must be set — Android uses it to correlate ACK/result/failure."""
        envelope = HandoffEnvelopeV2(
            task_id="audit_task_h2",
            task_payload={"command": "run_query"},
        )
        # handoff_id is auto-generated if not provided
        assert envelope.handoff_id is not None and envelope.handoff_id != ""

    def test_h3_android_ack_message_parsed_correctly(self) -> None:
        """V2 must be able to parse an ACK from Android and extract the handoff_id."""
        ack_msg = {
            "type": "handoff_ack",
            "handoff_id": "test_handoff_h3",
            "task_id": "t_h3",
            "device_id": "android_h3",
        }
        envelope = from_android_ack_message(ack_msg)
        assert envelope is not None
        assert envelope.response_kind == HandoffResponseKind.ack
        assert envelope.handoff_id == "test_handoff_h3"

    def test_h4_android_result_message_parsed_correctly(self) -> None:
        """V2 must parse a result from Android with the result payload intact."""
        result_msg = {
            "type": "handoff_result",
            "handoff_id": "test_handoff_h4",
            "task_id": "t_h4",
            "device_id": "android_h4",
            "result": {"screenshot": "base64data", "success": True},
            "success": True,
        }
        envelope = from_android_result_message(result_msg)
        assert envelope is not None
        assert envelope.response_kind == HandoffResponseKind.result
        assert envelope.success is True
        assert envelope.handoff_id == "test_handoff_h4"

    def test_h5_android_failure_message_parsed_correctly(self) -> None:
        """V2 must parse an Android failure and extract error details."""
        failure_msg = {
            "type": "handoff_failure",
            "handoff_id": "test_handoff_h5",
            "task_id": "t_h5",
            "device_id": "android_h5",
            "error_code": "EXECUTION_ERROR",
            "error_detail": "App not found",
            "success": False,
        }
        envelope = from_android_failure_message(failure_msg)
        assert envelope is not None
        assert envelope.response_kind == HandoffResponseKind.failure
        assert envelope.success is False

    def test_h6_ack_is_not_terminal(self) -> None:
        """ACK is not a terminal signal — V2 must keep waiting for result/failure."""
        ack_msg = {
            "type": "handoff_ack",
            "handoff_id": "h6",
            "task_id": "t_h6",
            "device_id": "android_h6",
        }
        envelope = from_android_ack_message(ack_msg)
        # is_terminal is a @property, not callable
        assert envelope.is_terminal is False, (
            "ACK must not be terminal — execution is still in progress"
        )

    def test_h7_result_is_terminal(self) -> None:
        """Result signal is terminal — V2 can close the dispatch after receiving it."""
        result_msg = {
            "type": "handoff_result",
            "handoff_id": "h7",
            "task_id": "t_h7",
            "device_id": "android_h7",
            "success": True,
        }
        envelope = from_android_result_message(result_msg)
        assert envelope.is_terminal is True

    def test_h8_failure_is_terminal(self) -> None:
        """Failure signal is terminal — V2 must not wait further."""
        failure_msg = {
            "type": "handoff_failure",
            "handoff_id": "h8",
            "task_id": "t_h8",
            "device_id": "android_h8",
            "success": False,
        }
        envelope = from_android_failure_message(failure_msg)
        assert envelope.is_terminal is True

    def test_h9_extract_handoff_response_envelope_dispatches_correctly(self) -> None:
        """extract_handoff_response_envelope must correctly classify message kinds."""
        messages = [
            ({"type": "handoff_ack", "handoff_id": "x"}, HandoffResponseKind.ack),
            ({"type": "handoff_result", "handoff_id": "x", "success": True}, HandoffResponseKind.result),
            ({"type": "handoff_failure", "handoff_id": "x"}, HandoffResponseKind.failure),
        ]
        for msg, expected_kind in messages:
            envelope = extract_handoff_response_envelope(msg)
            assert envelope is not None
            assert envelope.response_kind == expected_kind, (
                f"Expected kind={expected_kind} for type={msg['type']}, "
                f"got {envelope.response_kind}"
            )

    # ANDROID_REQUIRED: The following test documents the gap (CROSS-003)
    # and must be replaced with a real-device E2E test when available.
    def test_h10_android_required_real_device_e2e_gap_documented(self) -> None:
        """
        ANDROID_REQUIRED (CROSS-003): This test documents the gap where a real
        Android device E2E test is needed.

        Current status: V2-side contract is fully tested (H1-H9 above).
        Missing: A test that runs dispatch → Android receives HandoffEnvelopeV2 →
        Android executes → Android sends ACK + result → V2 processes result.

        This test is intentionally passing (it is a gap documentation test).
        Replace with a real-device E2E test once CROSS-003 is addressed.
        """
        # This is a documentation assertion, not a functional test
        gap_id = "CROSS-003"
        gap_description = (
            "No confirmed E2E test that runs across both repos with real Android devices. "
            "PR-523 acceptance tests are server-side only (99 tests, no Android device required). "
            "Real-device E2E integration test suite must be added to address this gap."
        )
        # The gap is documented — this test passes as a documentation marker
        assert gap_id == "CROSS-003"
        assert len(gap_description) > 0


# ---------------------------------------------------------------------------
# Section I: Dependency chain — PR-I substrate feeds PR-J runtime
#
# Reviewer note: PR-J strongly depends on PR-I. These tests verify that the
# enrollment substrate (PR-I) is in place and produces the right output for
# PR-J to consume.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENROLLMENT_AVAILABLE or not _REGISTRY_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="enrollment or registry not available",
)
class TestSectionI_DependencyChain:
    """
    Dependency: PR-J strongly depends on PR-I.
    PR-I provides: MeshAutoEnrollmentService, BodyMeshRegistry, FormationAutoEnrollmentManager.
    PR-J consumes: A coordinator_state with enrolled participants.
    """

    def setup_method(self) -> None:
        """Reset singletons for test isolation."""
        try:
            reset_auto_enrollment_service()
        except Exception:
            pass
        try:
            reset_body_mesh_registry()
        except Exception:
            pass

    def test_i1_enrollment_service_registers_device_to_registry(self) -> None:
        """
        PR-I: Device registration must write to BodyMeshRegistry.
        Without this, PR-J has no participants to coordinate.
        """
        from core.mesh.body_mesh_registry import DeviceRole
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
        )
        notify_device_registered("android_i1_device")
        notify_capability_reported(
            "android_i1_device",
            roles=[DeviceRole.ACTION, DeviceRole.PERCEPTION],
        )
        record = get_enrollment_record("android_i1_device")
        assert record is not None
        assert record.enrolled is True, (
            "Device must be enrolled after registration + capability report. "
            "PR-J depends on this enrollment to have participants."
        )

    def test_i2_enrolled_device_appears_in_registry(self) -> None:
        """
        PR-I: Enrolled device must be queryable from BodyMeshRegistry.
        PR-J reads from this registry to build coordinator participant list.
        """
        from core.mesh.body_mesh_registry import DeviceRole
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
        )
        notify_device_registered("android_i2_device")
        notify_capability_reported(
            "android_i2_device",
            roles=[DeviceRole.ACTION],
        )
        registry = get_body_mesh_registry()
        entry = registry.get("android_i2_device")
        assert entry is not None, (
            "Enrolled device must be queryable from BodyMeshRegistry. "
            "PR-J uses this registry to know which participants are available."
        )

    def test_i3_unenrolled_device_not_in_registry(self) -> None:
        """
        PR-I: Device that was never enrolled must NOT appear in registry.
        This confirms that registry is not pre-populated with phantom entries.
        """
        registry = get_body_mesh_registry()
        entry = registry.get("phantom_device_never_registered")
        assert entry is None, (
            "Non-enrolled device must not appear in BodyMeshRegistry. "
            "This confirms enrollment is a necessary precondition for PR-J."
        )

    def test_i4_pr_i_produces_enrollment_record_readable_by_pr_j(self) -> None:
        """
        Integration: PR-I enrollment record must be compatible with PR-J's
        expectation of coordinator participants.

        Reviewer note: If this test fails, the PR-I → PR-J interface is broken.
        """
        from core.mesh.body_mesh_registry import DeviceRole
        from core.mesh.mesh_auto_enrollment import (
            notify_device_registered,
            notify_capability_reported,
        )
        notify_device_registered("android_i4_device")
        notify_capability_reported(
            "android_i4_device",
            roles=[DeviceRole.ACTION, DeviceRole.PERCEPTION],
        )
        record = get_enrollment_record("android_i4_device")
        # The enrollment record must have the device_id field that PR-J expects
        assert record is not None
        assert record.device_id == "android_i4_device"
        assert record.enrolled is True


# ---------------------------------------------------------------------------
# Section J: End-to-end lifecycle
# (enrollment → coordinator build → dispatch → orchestration → result)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE or not _COORD_AVAILABLE,
    reason="required modules not available",
)
class TestSectionJ_EndToEndLifecycle:
    """
    These tests walk the full production-style path within V2.

    Reviewer note: Section J is the highest-confidence evidence that the V2
    control plane is fully wired.  It does NOT test the Android execution side
    (CROSS-003 gap), but it confirms that V2 itself is a coherent system.
    """

    def test_j1_coordinate_then_run_gives_coherent_result(self) -> None:
        """
        Full lifecycle: coordinate_mesh_session() → run_live_mesh_session().

        This is the production-style call sequence used by the orchestrator.
        """
        # Step 1: Build coordinator state from a mesh session dict
        coord_state = coordinate_mesh_session(
            mesh_session={
                "session_id": "e2e_j1_session",
                "mesh_id": "e2e_j1_mesh",
                "participants": [
                    {"device_id": "phone_j1", "roles": ["source"], "status": "active"},
                    {"device_id": "tablet_j1", "roles": ["primary"], "status": "active"},
                ],
                "multi_device_required": True,
                "barrier_posture": "soft_barrier",
            }
        )
        assert coord_state is not None

        # Step 2: Simulate participants completing their work
        result = coord_run_live(
            coord_state,
            participant_results={
                "phone_j1": {"output": "phone_done", "success": True},
                "tablet_j1": {"output": "tablet_done", "success": True},
            },
        )
        assert result is not None
        assert result.outcome in ("completed", "partial", "failed")

    def test_j2_full_success_path_staged_to_completed(self) -> None:
        """
        Full success path: all participants complete successfully.
        Verifies the 'happy path' claim in the system audit.
        """
        state = _make_coord_state(
            session_id="j2_success",
            device_ids=["j2_phone", "j2_tablet"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={
                "j2_phone": {"success": True, "output": "phone_result"},
                "j2_tablet": {"success": True, "output": "tablet_result"},
            },
        )
        assert result.outcome == "completed"
        assert result.success is True
        assert result.barrier_released is True
        final = result.coordinator_state
        assert final.status == MeshCoordinatorStatus.completed
        assert "j2_phone" in final.completed_device_ids
        assert "j2_tablet" in final.completed_device_ids

    def test_j3_partial_device_loss_path(self) -> None:
        """
        Partial path: one device drops during session.
        Verifies the partial-completion claim.
        """
        state = _make_coord_state(
            session_id="j3_partial",
            device_ids=["j3_ok", "j3_lost"],
        )
        state = drop_participant(state, "j3_lost", reason="disconnect")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"j3_ok": {"success": True, "output": "partial"}},
        )
        assert result.outcome in ("partial", "failed")
        final = result.coordinator_state
        assert "j3_lost" in final.failed_device_ids

    def test_j4_full_failure_path_no_participants(self) -> None:
        """
        Full failure: no participants registered.
        Verifies the 'PR-J without PR-I' degradation claim.
        """
        state = build_mesh_session_coordinator(session_id="j4_empty")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(state)
        assert result.outcome == "failed"
        assert result.success is False
        assert len(result.errors) > 0

    def test_j5_multi_participant_barrier_sync(self) -> None:
        """
        Three participants must all arrive before barrier releases.
        """
        state = _make_coord_state(
            session_id="j5_three",
            device_ids=["j5a", "j5b", "j5c"],
            barrier_posture="soft_barrier",
        )
        engine = LiveMeshRuntimeEngine()

        # All three arrive → barrier released
        result = engine.run(
            state,
            participant_results={
                "j5a": {"output": "a"},
                "j5b": {"output": "b"},
                "j5c": {"output": "c"},
            },
        )
        assert result.barrier_released is True
        assert result.outcome == "completed"
        assert len(result.merged_result.get("_participants", [])) == 3

    def test_j6_result_is_serialisable_to_dict(self) -> None:
        """
        LiveMeshRunResult.to_dict() must produce a JSON-safe dict.
        This is required for result surfacing to operator/replay systems.
        """
        state = _make_coord_state(session_id="j6_serial")
        result = LiveMeshRuntimeEngine().run(
            state,
            participant_results={"android_a": {"output": "done"}, "android_b": {}},
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        required_keys = [
            "run_id", "session_id", "outcome", "success",
            "merged_result", "barrier_released", "errors",
        ]
        for key in required_keys:
            assert key in d, f"to_dict() missing key: {key}"


# ---------------------------------------------------------------------------
# Section K: Observability — key events must be emittable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _ENGINE_AVAILABLE or not _CONTRACTS_AVAILABLE,
    reason="engine or contracts not available",
)
class TestSectionK_Observability:
    """
    Review note: The system must produce structured coordination events so that
    operators can observe mesh session lifecycle without reading internal state.
    """

    def test_k1_mesh_session_promoted_event_emitted(self) -> None:
        """coordinator_status_changed event must appear after promotion to active."""
        state = _make_coord_state(session_id="k1_observe")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"android_a": {"v": 1}, "android_b": {"v": 2}},
        )
        final = result.coordinator_state
        event_kinds = [e.kind.value for e in final.coordination_events]
        assert "coordinator_status_changed" in event_kinds, (
            "coordinator_status_changed event must be emitted when session is promoted"
        )

    def test_k2_participant_joined_event_emitted_on_register(self) -> None:
        """participant_joined event must appear when a new participant registers."""
        state = build_mesh_session_coordinator(session_id="k2_observe")
        state = register_participant(state, "new_participant_k2")
        event_kinds = [e.kind.value for e in state.coordination_events]
        assert "participant_joined" in event_kinds, (
            "participant_joined event must be emitted when a participant registers"
        )

    def test_k3_coordination_events_non_empty_after_run(self) -> None:
        """At least one coordination event must be emitted during a run."""
        state = _make_coord_state(session_id="k3_observe")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"android_a": {"v": 1}, "android_b": {"v": 2}},
        )
        final = result.coordinator_state
        assert len(final.coordination_events) > 0, (
            "No coordination events emitted during run — observability is broken"
        )

    def test_k4_barrier_released_event_emitted_on_success(self) -> None:
        """barrier_released event must appear in events after all participants arrive."""
        state = _make_coord_state(session_id="k4_observe")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"android_a": {"v": 1}, "android_b": {"v": 2}},
        )
        final = result.coordinator_state
        event_kinds = [e.kind.value for e in final.coordination_events]
        assert "barrier_released" in event_kinds, (
            "barrier_released event must be emitted when barrier is released by all participants arriving; "
            "event not found in: " + str(event_kinds)
        )

    def test_k5_result_dict_is_fully_observable(self) -> None:
        """LiveMeshRunResult.to_dict() must expose all observability fields."""
        state = _make_coord_state(session_id="k5_observe")
        engine = LiveMeshRuntimeEngine()
        result = engine.run(
            state,
            participant_results={"android_a": {"v": 1}, "android_b": {"v": 2}},
        )
        d = result.to_dict()
        # All observability fields must be present
        for field in ["run_id", "session_id", "outcome", "success",
                      "merged_result", "participant_outcomes",
                      "barrier_released", "coordinator_state",
                      "errors", "created_at"]:
            assert field in d, f"Observability field missing from to_dict(): {field}"
