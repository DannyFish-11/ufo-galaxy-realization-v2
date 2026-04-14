"""Tests for PR-7 UGCP truth/event model alignment."""

from __future__ import annotations

import importlib.util

import pytest

from core.ugcp_truth_event_model import (
    AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS_POLICY,
    EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY_POLICY,
    REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT_POLICY,
    SNAPSHOT_IS_DURABLE_READ_MODEL_POLICY,
    TRUTH_EVENT_VOCABULARY_IS_FROZEN_POLICY,
    UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
    UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL,
    CanonicalTruthEventType,
    TruthSurfaceClass,
    build_replay_checkpoint,
    build_runtime_observational_stream_event,
    build_session_truth_authoritative_event,
    build_snapshot_projection_surface,
    get_canonical_transition_event_types,
    is_authoritative_transition_event,
)

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


def test_sentinels_present() -> None:
    assert UGCP_TRUTH_EVENT_MODEL_AUTHORITY.startswith("UGCP_TRUTH_EVENT_MODEL_AUTHORITY::")
    assert "truth/event backbone authority" in UGCP_TRUTH_EVENT_MODEL_AUTHORITY
    assert "package=7" in UGCP_TRUTH_EVENT_MODEL_PR7_SENTINEL
    assert "VOCABULARY_IS_FROZEN" in TRUTH_EVENT_VOCABULARY_IS_FROZEN_POLICY
    assert "AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS" in AUTHORITATIVE_TRUTH_WRITES_EMIT_CANONICAL_EVENTS_POLICY
    assert "EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY" in EVENT_STREAM_IS_OBSERVATIONAL_NOT_AUTHORITY_POLICY
    assert "SNAPSHOT_IS_DURABLE_READ_MODEL" in SNAPSHOT_IS_DURABLE_READ_MODEL_POLICY
    assert "REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT" in REPLAY_RECONSTRUCTION_AVOIDS_SEMANTIC_DRIFT_POLICY


def test_transition_event_vocabulary_contains_profile_transitions() -> None:
    event_types = get_canonical_transition_event_types()
    assert CanonicalTruthEventType.control_transfer_transition.value in event_types
    assert CanonicalTruthEventType.coordination_transition.value in event_types
    assert CanonicalTruthEventType.session_truth_recorded.value in event_types


def test_authoritative_event_from_session_record() -> None:
    envelope = build_session_truth_authoritative_event(
        {
            "record_id": "cst_1",
            "session_id": "sess_1",
            "trace_id": "trace_1",
            "task_id": "task_1",
            "truth_source": "mesh",
            "merge_success": True,
            "primary_unit_id": "u1",
            "reason": "merged",
        },
        event_sequence=11,
    )

    assert envelope.event_type == CanonicalTruthEventType.session_truth_recorded.value
    assert envelope.surface_class == TruthSurfaceClass.authoritative_truth
    assert envelope.authoritative_transition is True
    assert envelope.ordering_key == "sess_1"
    assert is_authoritative_transition_event(envelope.event_type) is True

    event = envelope.to_truth_event()
    assert event.event_type == CanonicalTruthEventType.session_truth_recorded.value
    assert event.payload["surface_class"] == TruthSurfaceClass.authoritative_truth.value
    assert event.payload["event_sequence"] == 11


def test_snapshot_surface_and_replay_checkpoint() -> None:
    snapshot_surface = build_snapshot_projection_surface(
        {
            "snapshot_id": "snap_1",
            "total_records": 3,
            "successful_merge_count": 2,
            "control_only_session_count": 1,
            "join_runtime_session_count": 2,
        },
        source_event_sequence=22,
    )
    assert snapshot_surface["surface_class"] == TruthSurfaceClass.durable_snapshot.value
    assert snapshot_surface["event_type"] == CanonicalTruthEventType.session_truth_snapshot.value
    assert snapshot_surface["source_event_sequence"] == 22

    envelope = build_session_truth_authoritative_event(
        {"session_id": "sess_1", "trace_id": "trace_1", "task_id": "task_1"},
        event_sequence=23,
    )
    checkpoint = build_replay_checkpoint(envelope)
    assert checkpoint["surface_class"] == TruthSurfaceClass.replay_checkpoint.value
    assert checkpoint["event_type"] == CanonicalTruthEventType.session_truth_recorded.value
    assert checkpoint["event_sequence"] == 23
    assert "sess_1" in checkpoint["dedupe_key"]


def test_runtime_stream_is_observational() -> None:
    envelope = build_session_truth_authoritative_event(
        {"session_id": "sess_2", "trace_id": "trace_2"},
        event_sequence=3,
    )
    stream_event = build_runtime_observational_stream_event(envelope, stream_name="truth_updates")
    assert stream_event["surface_class"] == TruthSurfaceClass.observational_stream.value
    assert stream_event["stream_name"] == "truth_updates"
    assert stream_event["authoritative_transition"] is False
    assert stream_event["derived_from_authoritative_transition"] is True


def test_control_and_coordination_profiles_use_frozen_transition_event_types() -> None:
    from core.ugcp_control_transfer_profile import (
        ControlTransferFamily,
        ControlTransferState,
        build_control_transfer_truth_event,
    )
    from core.ugcp_coordination_profile import (
        CoordinationLifecycleState,
        build_coordination_truth_event,
    )

    transfer_event = build_control_transfer_truth_event(
        family=ControlTransferFamily.handoff,
        current_state=ControlTransferState.ready,
    )
    coordination_event = build_coordination_truth_event(
        current_state=CoordinationLifecycleState.active,
    )

    assert transfer_event.event_type == CanonicalTruthEventType.control_transfer_transition.value
    assert coordination_event.event_type == CanonicalTruthEventType.coordination_transition.value


def test_canonical_session_truth_record_includes_truth_event_semantics_metadata() -> None:
    from core.canonical_session_truth import (
        record_session_truth,
        reset_canonical_session_truth_runtime,
    )

    reset_canonical_session_truth_runtime()
    record = record_session_truth(session_id="sess_meta")
    assert record.metadata["truth_event_type"] == CanonicalTruthEventType.session_truth_recorded.value
    assert record.metadata["truth_event_surface_class"] == TruthSurfaceClass.authoritative_truth.value
    assert record.metadata["truth_event_authoritative_transition"] is True


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7
    assert "UGCP_TRUTH_EVENT_MODEL_ALIGNED_PR7" in sentinel
    assert "UNAVAILABLE" not in sentinel
    fn = getattr(projection, "_build_session_truth_authoritative_event", None)
    assert callable(fn)
