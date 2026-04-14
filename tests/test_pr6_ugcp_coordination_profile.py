"""Tests for PR-6 UGCP coordination profile alignment."""

from __future__ import annotations

import importlib.util

import pytest

from core.ugcp_coordination_profile import (
    COORDINATION_ALLOWED_TRANSITIONS,
    UGCP_COORDINATION_PROFILE_AUTHORITY,
    UGCP_COORDINATION_PROFILE_PR6_SENTINEL,
    CoordinationAggregationSemantics,
    CoordinationAuthorityScope,
    CoordinationBarrierSemantics,
    CoordinationLifecycleState,
    CoordinationParticipantRole,
    CoordinationTerminalOutcome,
    build_coordination_durable_snapshot,
    build_coordination_merge_reason,
    build_coordination_truth_event,
    can_transition,
    infer_terminal_outcome,
    map_from_aggregation_mode,
    map_from_authority_scope,
    map_from_barrier_status,
    map_from_coordinator_status,
    map_from_mesh_session_status,
    map_from_participant_role,
)

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


def test_sentinels_present() -> None:
    assert UGCP_COORDINATION_PROFILE_AUTHORITY.startswith("UGCP_COORDINATION_PROFILE_AUTHORITY::")
    assert "canonical mapping authority" in UGCP_COORDINATION_PROFILE_AUTHORITY
    assert "mesh/coordinator coordination semantics" in UGCP_COORDINATION_PROFILE_AUTHORITY
    assert "package=6" in UGCP_COORDINATION_PROFILE_PR6_SENTINEL


def test_state_graph_terminal_absorbing() -> None:
    assert can_transition(CoordinationLifecycleState.completed, CoordinationLifecycleState.active) is False
    assert can_transition(CoordinationLifecycleState.failed, CoordinationLifecycleState.merging) is False


def test_state_graph_mainline_progression() -> None:
    assert can_transition(CoordinationLifecycleState.pending, CoordinationLifecycleState.active) is True
    assert can_transition(CoordinationLifecycleState.active, CoordinationLifecycleState.awaiting_barrier) is True
    assert can_transition(CoordinationLifecycleState.awaiting_barrier, CoordinationLifecycleState.merging) is True
    assert can_transition(CoordinationLifecycleState.merging, CoordinationLifecycleState.completed) is True
    assert CoordinationLifecycleState.unknown in COORDINATION_ALLOWED_TRANSITIONS


def test_mesh_and_coordinator_status_mapping() -> None:
    assert map_from_mesh_session_status("active") == CoordinationLifecycleState.active
    assert map_from_mesh_session_status("cancelled") == CoordinationLifecycleState.cancelled
    assert map_from_coordinator_status("partial") == CoordinationLifecycleState.partial


def test_role_and_authority_mapping() -> None:
    assert map_from_participant_role("merge-owner") == CoordinationParticipantRole.merge_owner
    assert map_from_participant_role("support") == CoordinationParticipantRole.support
    assert map_from_authority_scope("observer") == CoordinationAuthorityScope.observation_only
    assert map_from_authority_scope("mesh_authority") == CoordinationAuthorityScope.mesh_authority


def test_barrier_and_aggregation_mapping() -> None:
    assert map_from_barrier_status("none") == CoordinationBarrierSemantics.not_required
    assert map_from_barrier_status("waiting") == CoordinationBarrierSemantics.waiting
    assert map_from_aggregation_mode("barrier") == CoordinationAggregationSemantics.barrier
    assert map_from_aggregation_mode("owner_decides") == CoordinationAggregationSemantics.owner_decides


def test_terminal_outcome_inference() -> None:
    assert infer_terminal_outcome(CoordinationLifecycleState.failed) == CoordinationTerminalOutcome.failed
    assert infer_terminal_outcome(
        CoordinationLifecycleState.failed,
        raw_reason="merge_error",
    ) == CoordinationTerminalOutcome.merge_failed


def test_build_coordination_truth_event_payload() -> None:
    event = build_coordination_truth_event(
        current_state=CoordinationLifecycleState.awaiting_barrier,
        previous_state=CoordinationLifecycleState.active,
        authority_scope=CoordinationAuthorityScope.barrier_authority,
        role=CoordinationParticipantRole.primary,
        trace_id="trace_1",
        task_id="task_1",
        control_session_id="ctrl_1",
        runtime_session_id="run_1",
        mesh_session_id="mesh_1",
        coordinator_id="mcoord_1",
        barrier=CoordinationBarrierSemantics.waiting,
        aggregation=CoordinationAggregationSemantics.barrier,
        quorum_reached=False,
    )
    payload = event.payload
    assert event.event_type == "ugcp.coordination.transition.v1"
    assert payload["profile"] == "ugcp_coordination_v1"
    assert payload["current_state"] == "awaiting_barrier"
    assert payload["previous_state"] == "active"
    assert payload["authority_scope"] == "barrier_authority"
    assert payload["barrier"] == "waiting"
    assert payload["is_terminal"] is False


def test_build_coordination_durable_snapshot() -> None:
    snapshot = build_coordination_durable_snapshot(
        mesh_session_id="mesh_1",
        coordinator_id="mcoord_1",
        state=CoordinationLifecycleState.partial,
        authority_scope=CoordinationAuthorityScope.shared,
        barrier=CoordinationBarrierSemantics.released,
        aggregation=CoordinationAggregationSemantics.parallel,
        quorum_reached=True,
        terminal_outcome=CoordinationTerminalOutcome.partial,
        metadata={"source": "test"},
    )
    assert snapshot["profile"] == "ugcp_coordination_v1"
    assert snapshot["coordination_state"] == "partial"
    assert snapshot["is_terminal"] is True
    assert snapshot["authority_scope"] == "shared"
    assert snapshot["terminal_outcome"] == "partial"
    assert snapshot["metadata"]["source"] == "test"


def test_build_coordination_merge_reason() -> None:
    reason = build_coordination_merge_reason(
        CoordinationLifecycleState.failed,
        CoordinationTerminalOutcome.merge_failed,
    )
    assert reason == "ugcp_coordination_v1:failed:merge_failed"


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.UGCP_COORDINATION_PROFILE_ALIGNED_PR6
    assert "UGCP_COORDINATION_PROFILE_ALIGNED_PR6" in sentinel
    assert "UNAVAILABLE" not in sentinel
    can_transition_fn = getattr(projection, "_coordination_can_transition", None)
    assert callable(can_transition_fn)
    assert can_transition_fn("pending", "active") is True
