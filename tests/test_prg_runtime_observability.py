"""tests/test_prg_runtime_observability.py
==========================================
Tests for PR-G: Production-grade runtime observability for device lifecycle,
mesh session transitions, and dispatch decisions.

Coverage:
  A.  DeviceLifecycleEventKind enum has all required values.
  B.  DeviceLifecycleEvent round-trips through to_dict / from_dict.
  C.  build_device_lifecycle_event populates all identity fields.
  D.  MeshSessionTransitionKind enum has all required values.
  E.  MeshSessionTransitionEvent round-trips through to_dict / from_dict.
  F.  build_mesh_session_transition_event populates prior/new status.
  G.  DispatchDecisionEventKind enum has all required values.
  H.  DispatchDecisionEvent round-trips through to_dict / from_dict.
  I.  build_dispatch_decision_event captures mode and decision_reason.
  J.  RecoveryDecisionKind enum has all required values (resumable/terminal/fallback).
  K.  RecoveryDecisionEvent round-trips through to_dict / from_dict.
  L.  build_recovery_decision_event sets is_resumable correctly.
  M.  RuntimeObservabilitySink stores device lifecycle events.
  N.  RuntimeObservabilitySink stores mesh session transition events.
  O.  RuntimeObservabilitySink stores dispatch decision events.
  P.  RuntimeObservabilitySink stores recovery decision events.
  Q.  RuntimeObservabilitySink is bounded (ring-buffer maxlen respected).
  R.  RuntimeObservabilitySink.counters() returns correct total counts.
  S.  RuntimeObservabilitySink.snapshot() returns ObservabilitySnapshot.
  T.  ObservabilitySnapshot round-trips through to_dict / to_json.
  U.  emit_device_lifecycle_event returns a DeviceLifecycleEvent and records it.
  V.  emit_mesh_session_transition_event returns event and records it.
  W.  emit_dispatch_decision_event returns event and records it.
  X.  emit_recovery_decision_event returns event and records it.
  Y.  build_observability_snapshot returns a populated snapshot.
  Z.  Sentinel constants are importable from contracts.runtime_observability.
  AA. Sentinel constants are importable from
      core.runtime.runtime_observability_sink.
  AB. emit_* helpers are gracefully non-raising (no-exception policy).
  AC. reset_observability_sink() clears the singleton.
  AD. DeviceLifecycleEvent.to_json() round-trips correctly.
  AE. RecoveryDecisionEvent with terminal_loss has is_resumable=False.
  AF. RecoveryDecisionEvent with resumable_reassociation has is_resumable=True.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

import pytest

from contracts.runtime_observability import (
    DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY,
    DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY,
    MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY,
    RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY,
    RUNTIME_OBSERVABILITY_IS_AUTHORITY,
    RUNTIME_OBSERVABILITY_PR_G_SENTINEL,
    DeviceLifecycleEvent,
    DeviceLifecycleEventKind,
    DispatchDecisionEvent,
    DispatchDecisionEventKind,
    MeshSessionTransitionEvent,
    MeshSessionTransitionKind,
    RecoveryDecisionEvent,
    RecoveryDecisionKind,
    build_device_lifecycle_event,
    build_dispatch_decision_event,
    build_mesh_session_transition_event,
    build_recovery_decision_event,
)
from core.runtime.runtime_observability_sink import (
    RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY,
    RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL,
    SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY,
    SINK_IS_BOUNDED_POLICY,
    SINK_MAX_EVENTS_PER_KIND,
    ObservabilitySnapshot,
    RuntimeObservabilitySink,
    build_observability_snapshot,
    emit_device_lifecycle_event,
    emit_dispatch_decision_event,
    emit_mesh_session_transition_event,
    emit_recovery_decision_event,
    get_observability_sink,
    reset_observability_sink,
)


# ===========================================================================
# A. DeviceLifecycleEventKind enum
# ===========================================================================


class TestDeviceLifecycleEventKindEnum:
    """DeviceLifecycleEventKind has all required values."""

    def test_attach(self):
        assert DeviceLifecycleEventKind.attach == "attach"

    def test_detach(self):
        assert DeviceLifecycleEventKind.detach == "detach"

    def test_reconnect(self):
        assert DeviceLifecycleEventKind.reconnect == "reconnect"

    def test_readiness_change(self):
        assert DeviceLifecycleEventKind.readiness_change == "readiness_change"

    def test_degraded(self):
        assert DeviceLifecycleEventKind.degraded == "degraded"

    def test_lost(self):
        assert DeviceLifecycleEventKind.lost == "lost"

    def test_heartbeat_miss(self):
        assert DeviceLifecycleEventKind.heartbeat_miss == "heartbeat_miss"

    def test_unknown(self):
        assert DeviceLifecycleEventKind.unknown == "unknown"

    def test_is_str_enum(self):
        assert isinstance(DeviceLifecycleEventKind.attach, str)

    def test_required_values_present(self):
        values = {e.value for e in DeviceLifecycleEventKind}
        for required in ("attach", "detach", "reconnect", "readiness_change", "degraded", "lost"):
            assert required in values


# ===========================================================================
# B. DeviceLifecycleEvent round-trip
# ===========================================================================


class TestDeviceLifecycleEventRoundTrip:
    """DeviceLifecycleEvent round-trips through to_dict / from_dict."""

    def test_basic_round_trip(self):
        evt = DeviceLifecycleEvent(
            event_kind="attach",
            device_id="android_01",
            trace_id="trace_abc",
            session_id="sess_001",
            mesh_session_id="mesh_xyz",
            prior_state="detached",
            new_state="attached",
            reason="device_registered",
        )
        d = evt.to_dict()
        restored = DeviceLifecycleEvent.from_dict(d)
        assert restored.event_kind == "attach"
        assert restored.device_id == "android_01"
        assert restored.trace_id == "trace_abc"
        assert restored.session_id == "sess_001"
        assert restored.mesh_session_id == "mesh_xyz"
        assert restored.prior_state == "detached"
        assert restored.new_state == "attached"
        assert restored.reason == "device_registered"

    def test_to_dict_is_json_serialisable(self):
        evt = DeviceLifecycleEvent(event_kind="detach", device_id="dev_01")
        payload = json.dumps(evt.to_dict())
        assert "detach" in payload

    def test_missing_optional_fields_default_to_none(self):
        evt = DeviceLifecycleEvent.from_dict({"device_id": "dev_01"})
        assert evt.trace_id is None
        assert evt.session_id is None
        assert evt.health_score is None

    def test_health_score_round_trip(self):
        evt = DeviceLifecycleEvent(device_id="d1", health_score=0.75)
        restored = DeviceLifecycleEvent.from_dict(evt.to_dict())
        assert restored.health_score == pytest.approx(0.75)


# ===========================================================================
# C. build_device_lifecycle_event
# ===========================================================================


class TestBuildDeviceLifecycleEvent:
    """build_device_lifecycle_event populates all identity fields."""

    def test_basic_attach(self):
        evt = build_device_lifecycle_event(
            "android_01",
            DeviceLifecycleEventKind.attach,
            reason="test_reason",
        )
        assert evt.device_id == "android_01"
        assert evt.event_kind == "attach"
        assert evt.reason == "test_reason"

    def test_all_identity_fields(self):
        evt = build_device_lifecycle_event(
            "dev_xyz",
            "reconnect",
            trace_id="t1",
            session_id="s1",
            mesh_session_id="m1",
            formation_id="f1",
            prior_state="disconnected",
            new_state="attached",
            readiness="ready",
            health_score=0.9,
            reason="reconnect_success",
        )
        assert evt.trace_id == "t1"
        assert evt.session_id == "s1"
        assert evt.mesh_session_id == "m1"
        assert evt.formation_id == "f1"
        assert evt.prior_state == "disconnected"
        assert evt.new_state == "attached"
        assert evt.readiness == "ready"
        assert evt.health_score == pytest.approx(0.9)

    def test_string_event_kind(self):
        evt = build_device_lifecycle_event("dev_01", "degraded")
        assert evt.event_kind == "degraded"

    def test_event_has_event_id(self):
        evt = build_device_lifecycle_event("dev_01", "lost")
        assert evt.event_id is not None
        assert len(evt.event_id) > 0

    def test_event_has_timestamp(self):
        evt = build_device_lifecycle_event("dev_01", "attach")
        assert evt.timestamp > 0.0


# ===========================================================================
# D. MeshSessionTransitionKind enum
# ===========================================================================


class TestMeshSessionTransitionKindEnum:
    """MeshSessionTransitionKind has all required values."""

    def test_create(self):
        assert MeshSessionTransitionKind.create == "create"

    def test_activate(self):
        assert MeshSessionTransitionKind.activate == "activate"

    def test_suspend(self):
        assert MeshSessionTransitionKind.suspend == "suspend"

    def test_restore(self):
        assert MeshSessionTransitionKind.restore == "restore"

    def test_terminate(self):
        assert MeshSessionTransitionKind.terminate == "terminate"

    def test_participant_joined(self):
        assert MeshSessionTransitionKind.participant_joined == "participant_joined"

    def test_participant_left(self):
        assert MeshSessionTransitionKind.participant_left == "participant_left"

    def test_is_str_enum(self):
        assert isinstance(MeshSessionTransitionKind.activate, str)

    def test_required_lifecycle_values_present(self):
        values = {e.value for e in MeshSessionTransitionKind}
        for required in ("create", "activate", "suspend", "restore", "terminate"):
            assert required in values


# ===========================================================================
# E. MeshSessionTransitionEvent round-trip
# ===========================================================================


class TestMeshSessionTransitionEventRoundTrip:
    """MeshSessionTransitionEvent round-trips through to_dict / from_dict."""

    def test_basic_round_trip(self):
        evt = MeshSessionTransitionEvent(
            transition_kind="activate",
            session_id="sess_001",
            trace_id="trace_abc",
            prior_status="pending",
            new_status="active",
            reason="all_participants_ready",
        )
        d = evt.to_dict()
        restored = MeshSessionTransitionEvent.from_dict(d)
        assert restored.transition_kind == "activate"
        assert restored.session_id == "sess_001"
        assert restored.trace_id == "trace_abc"
        assert restored.prior_status == "pending"
        assert restored.new_status == "active"
        assert restored.reason == "all_participants_ready"

    def test_to_dict_is_json_serialisable(self):
        evt = MeshSessionTransitionEvent(transition_kind="suspend", session_id="s1")
        payload = json.dumps(evt.to_dict())
        assert "suspend" in payload

    def test_participant_count_round_trip(self):
        evt = MeshSessionTransitionEvent(
            session_id="s1", transition_kind="participant_joined", participant_count=3
        )
        restored = MeshSessionTransitionEvent.from_dict(evt.to_dict())
        assert restored.participant_count == 3


# ===========================================================================
# F. build_mesh_session_transition_event
# ===========================================================================


class TestBuildMeshSessionTransitionEvent:
    """build_mesh_session_transition_event populates prior/new status."""

    def test_basic_activate(self):
        evt = build_mesh_session_transition_event(
            "sess_001",
            MeshSessionTransitionKind.activate,
            prior_status="pending",
            new_status="active",
            reason="participant_ready",
        )
        assert evt.session_id == "sess_001"
        assert evt.transition_kind == "activate"
        assert evt.prior_status == "pending"
        assert evt.new_status == "active"
        assert evt.reason == "participant_ready"

    def test_restore_with_count(self):
        evt = build_mesh_session_transition_event(
            "sess_002",
            "restore",
            prior_status="suspended",
            new_status="active",
            restore_count=2,
        )
        assert evt.restore_count == 2

    def test_participant_fields(self):
        evt = build_mesh_session_transition_event(
            "sess_003",
            "participant_joined",
            participant_device_id="phone_01",
            participant_count=2,
        )
        assert evt.participant_device_id == "phone_01"
        assert evt.participant_count == 2

    def test_event_has_event_id_and_timestamp(self):
        evt = build_mesh_session_transition_event("sess_004", "create")
        assert evt.event_id is not None
        assert evt.timestamp > 0.0


# ===========================================================================
# G. DispatchDecisionEventKind enum
# ===========================================================================


class TestDispatchDecisionEventKindEnum:
    """DispatchDecisionEventKind has all required values."""

    def test_plan_selected(self):
        assert DispatchDecisionEventKind.plan_selected == "plan_selected"

    def test_target_routed(self):
        assert DispatchDecisionEventKind.target_routed == "target_routed"

    def test_fallback_triggered(self):
        assert DispatchDecisionEventKind.fallback_triggered == "fallback_triggered"

    def test_plan_blocked(self):
        assert DispatchDecisionEventKind.plan_blocked == "plan_blocked"

    def test_orchestration_complete(self):
        assert DispatchDecisionEventKind.orchestration_complete == "orchestration_complete"

    def test_is_str_enum(self):
        assert isinstance(DispatchDecisionEventKind.plan_selected, str)


# ===========================================================================
# H. DispatchDecisionEvent round-trip
# ===========================================================================


class TestDispatchDecisionEventRoundTrip:
    """DispatchDecisionEvent round-trips through to_dict / from_dict."""

    def test_basic_round_trip(self):
        evt = DispatchDecisionEvent(
            event_kind="plan_selected",
            dispatch_id="disp_abc",
            mode="remote_handoff",
            executor_target_type="android_device",
            target_device_id="phone_01",
            decision_reason="mesh_participant_available",
            success=True,
        )
        d = evt.to_dict()
        restored = DispatchDecisionEvent.from_dict(d)
        assert restored.event_kind == "plan_selected"
        assert restored.dispatch_id == "disp_abc"
        assert restored.mode == "remote_handoff"
        assert restored.executor_target_type == "android_device"
        assert restored.target_device_id == "phone_01"
        assert restored.decision_reason == "mesh_participant_available"
        assert restored.success is True

    def test_to_dict_is_json_serialisable(self):
        evt = DispatchDecisionEvent(mode="local")
        payload = json.dumps(evt.to_dict())
        assert "local" in payload

    def test_fallback_fields(self):
        evt = DispatchDecisionEvent(
            mode="fallback_local",
            prior_mode="remote_handoff",
            event_kind="fallback_triggered",
        )
        d = evt.to_dict()
        assert d["prior_mode"] == "remote_handoff"
        assert d["event_kind"] == "fallback_triggered"

    def test_boolean_fields_default_false(self):
        evt = DispatchDecisionEvent.from_dict({"mode": "local"})
        assert evt.has_mesh_session is False
        assert evt.has_handoff_envelope is False
        assert evt.has_continuity_context is False
        assert evt.success is False


# ===========================================================================
# I. build_dispatch_decision_event
# ===========================================================================


class TestBuildDispatchDecisionEvent:
    """build_dispatch_decision_event captures mode and decision_reason."""

    def test_local_mode(self):
        evt = build_dispatch_decision_event(
            "local",
            decision_reason="no_mesh_participant_available",
        )
        assert evt.mode == "local"
        assert evt.decision_reason == "no_mesh_participant_available"

    def test_remote_handoff_mode(self):
        evt = build_dispatch_decision_event(
            "remote_handoff",
            dispatch_id="disp_001",
            executor_target_type="android_device",
            target_device_id="phone_01",
            has_handoff_envelope=True,
            decision_reason="eligible_remote_target_selected",
            success=True,
        )
        assert evt.mode == "remote_handoff"
        assert evt.executor_target_type == "android_device"
        assert evt.has_handoff_envelope is True
        assert evt.success is True

    def test_staged_mesh_mode(self):
        evt = build_dispatch_decision_event(
            "staged_mesh",
            has_mesh_session=True,
            decision_reason="mesh_session_active",
        )
        assert evt.mode == "staged_mesh"
        assert evt.has_mesh_session is True

    def test_fallback_local_with_prior_mode(self):
        evt = build_dispatch_decision_event(
            "fallback_local",
            event_kind=DispatchDecisionEventKind.fallback_triggered,
            prior_mode="remote_handoff",
            decision_reason="remote_target_unavailable",
        )
        assert evt.mode == "fallback_local"
        assert evt.prior_mode == "remote_handoff"
        assert evt.event_kind == "fallback_triggered"

    def test_has_continuity_context(self):
        evt = build_dispatch_decision_event(
            "local",
            has_continuity_context=True,
        )
        assert evt.has_continuity_context is True

    def test_event_has_event_id_and_timestamp(self):
        evt = build_dispatch_decision_event("local")
        assert evt.event_id is not None
        assert evt.timestamp > 0.0


# ===========================================================================
# J. RecoveryDecisionKind enum
# ===========================================================================


class TestRecoveryDecisionKindEnum:
    """RecoveryDecisionKind has all required values."""

    def test_resumable_reassociation(self):
        assert RecoveryDecisionKind.resumable_reassociation == "resumable_reassociation"

    def test_recovery_fallback(self):
        assert RecoveryDecisionKind.recovery_fallback == "recovery_fallback"

    def test_terminal_loss(self):
        assert RecoveryDecisionKind.terminal_loss == "terminal_loss"

    def test_unknown(self):
        assert RecoveryDecisionKind.unknown == "unknown"

    def test_is_str_enum(self):
        assert isinstance(RecoveryDecisionKind.terminal_loss, str)

    def test_all_required_values_present(self):
        values = {e.value for e in RecoveryDecisionKind}
        for required in ("resumable_reassociation", "recovery_fallback", "terminal_loss"):
            assert required in values


# ===========================================================================
# K. RecoveryDecisionEvent round-trip
# ===========================================================================


class TestRecoveryDecisionEventRoundTrip:
    """RecoveryDecisionEvent round-trips through to_dict / from_dict."""

    def test_basic_round_trip(self):
        evt = RecoveryDecisionEvent(
            decision_kind="resumable_reassociation",
            continuity_id="cont_001",
            prior_dispatch_id="disp_abc",
            prior_session_id="sess_001",
            prior_mesh_session_id="mesh_xyz",
            interruption_class="recoverable",
            interruption_reason="device_disconnect",
            is_resumable=True,
            resume_attempt_count=1,
            reason="reconnect_successful",
        )
        d = evt.to_dict()
        restored = RecoveryDecisionEvent.from_dict(d)
        assert restored.decision_kind == "resumable_reassociation"
        assert restored.continuity_id == "cont_001"
        assert restored.prior_dispatch_id == "disp_abc"
        assert restored.prior_session_id == "sess_001"
        assert restored.prior_mesh_session_id == "mesh_xyz"
        assert restored.interruption_class == "recoverable"
        assert restored.interruption_reason == "device_disconnect"
        assert restored.is_resumable is True
        assert restored.resume_attempt_count == 1

    def test_to_dict_is_json_serialisable(self):
        evt = RecoveryDecisionEvent(decision_kind="terminal_loss")
        payload = json.dumps(evt.to_dict())
        assert "terminal_loss" in payload


# ===========================================================================
# L. build_recovery_decision_event — is_resumable correctness
# ===========================================================================


class TestBuildRecoveryDecisionEvent:
    """build_recovery_decision_event sets is_resumable correctly."""

    def test_resumable_reassociation(self):
        evt = build_recovery_decision_event(
            RecoveryDecisionKind.resumable_reassociation,
            is_resumable=True,
            reason="device_reconnected",
        )
        assert evt.decision_kind == "resumable_reassociation"
        assert evt.is_resumable is True

    def test_terminal_loss_is_not_resumable(self):
        evt = build_recovery_decision_event(
            RecoveryDecisionKind.terminal_loss,
            is_resumable=False,
            interruption_class="terminal",
            reason="unrecoverable_session_loss",
        )
        assert evt.decision_kind == "terminal_loss"
        assert evt.is_resumable is False

    def test_recovery_fallback(self):
        evt = build_recovery_decision_event(
            "recovery_fallback",
            is_resumable=True,
            resume_attempt_count=2,
        )
        assert evt.decision_kind == "recovery_fallback"
        assert evt.resume_attempt_count == 2

    def test_prior_identity_fields(self):
        evt = build_recovery_decision_event(
            "resumable_reassociation",
            continuity_id="cont_001",
            prior_dispatch_id="d1",
            prior_session_id="s1",
            prior_mesh_session_id="m1",
            prior_task_id="t1",
        )
        assert evt.continuity_id == "cont_001"
        assert evt.prior_dispatch_id == "d1"
        assert evt.prior_session_id == "s1"
        assert evt.prior_mesh_session_id == "m1"
        assert evt.prior_task_id == "t1"


# ===========================================================================
# M–P. RuntimeObservabilitySink stores events
# ===========================================================================


class TestRuntimeObservabilitySinkStoresEvents:
    """RuntimeObservabilitySink stores all event types."""

    def setup_method(self):
        self.sink = RuntimeObservabilitySink(max_events=64)

    def test_stores_device_lifecycle_event(self):
        evt = build_device_lifecycle_event("dev_01", "attach")
        self.sink.record_device_lifecycle_event(evt)
        events = self.sink.list_device_lifecycle_events()
        assert len(events) == 1
        assert events[0]["event_kind"] == "attach"
        assert events[0]["device_id"] == "dev_01"

    def test_stores_mesh_session_transition_event(self):
        evt = build_mesh_session_transition_event("sess_001", "activate")
        self.sink.record_mesh_session_transition_event(evt)
        events = self.sink.list_mesh_session_transition_events()
        assert len(events) == 1
        assert events[0]["transition_kind"] == "activate"

    def test_stores_dispatch_decision_event(self):
        evt = build_dispatch_decision_event("local", decision_reason="no_target")
        self.sink.record_dispatch_decision_event(evt)
        events = self.sink.list_dispatch_decision_events()
        assert len(events) == 1
        assert events[0]["mode"] == "local"

    def test_stores_recovery_decision_event(self):
        evt = build_recovery_decision_event("terminal_loss", is_resumable=False)
        self.sink.record_recovery_decision_event(evt)
        events = self.sink.list_recovery_decision_events()
        assert len(events) == 1
        assert events[0]["decision_kind"] == "terminal_loss"


# ===========================================================================
# Q. RuntimeObservabilitySink is bounded
# ===========================================================================


class TestRuntimeObservabilitySinkBounded:
    """RuntimeObservabilitySink respects ring-buffer maxlen."""

    def test_bounded_device_events(self):
        sink = RuntimeObservabilitySink(max_events=4)
        for i in range(10):
            sink.record_device_lifecycle_event(
                build_device_lifecycle_event(f"dev_{i}", "attach")
            )
        events = sink.list_device_lifecycle_events()
        assert len(events) == 4
        # Most recent 4 should be dev_6..dev_9
        device_ids = [e["device_id"] for e in events]
        assert "dev_9" in device_ids

    def test_bounded_dispatch_events(self):
        sink = RuntimeObservabilitySink(max_events=3)
        for i in range(5):
            sink.record_dispatch_decision_event(
                build_dispatch_decision_event("local", decision_reason=f"reason_{i}")
            )
        events = sink.list_dispatch_decision_events()
        assert len(events) == 3


# ===========================================================================
# R. RuntimeObservabilitySink counters
# ===========================================================================


class TestRuntimeObservabilitySinkCounters:
    """RuntimeObservabilitySink.counters() returns correct total counts."""

    def test_counters_increment(self):
        sink = RuntimeObservabilitySink(max_events=4)
        for i in range(3):
            sink.record_device_lifecycle_event(
                build_device_lifecycle_event(f"dev_{i}", "attach")
            )
        for i in range(2):
            sink.record_mesh_session_transition_event(
                build_mesh_session_transition_event(f"sess_{i}", "activate")
            )
        sink.record_dispatch_decision_event(build_dispatch_decision_event("local"))
        counters = sink.counters()
        assert counters["device_lifecycle"] == 3
        assert counters["mesh_session_transition"] == 2
        assert counters["dispatch_decision"] == 1
        assert counters["recovery_decision"] == 0

    def test_counters_exceed_maxlen(self):
        # Counters should continue incrementing even when ring-buffer is full.
        sink = RuntimeObservabilitySink(max_events=2)
        for i in range(5):
            sink.record_device_lifecycle_event(
                build_device_lifecycle_event(f"dev_{i}", "attach")
            )
        counters = sink.counters()
        assert counters["device_lifecycle"] == 5
        assert len(sink.list_device_lifecycle_events()) == 2


# ===========================================================================
# S. RuntimeObservabilitySink.snapshot()
# ===========================================================================


class TestRuntimeObservabilitySinkSnapshot:
    """RuntimeObservabilitySink.snapshot() returns ObservabilitySnapshot."""

    def test_snapshot_is_observability_snapshot(self):
        sink = RuntimeObservabilitySink(max_events=16)
        sink.record_device_lifecycle_event(build_device_lifecycle_event("dev_01", "attach"))
        snap = sink.snapshot()
        assert isinstance(snap, ObservabilitySnapshot)

    def test_snapshot_has_all_event_types(self):
        sink = RuntimeObservabilitySink(max_events=16)
        sink.record_device_lifecycle_event(build_device_lifecycle_event("d1", "attach"))
        sink.record_mesh_session_transition_event(
            build_mesh_session_transition_event("s1", "create")
        )
        sink.record_dispatch_decision_event(build_dispatch_decision_event("local"))
        sink.record_recovery_decision_event(
            build_recovery_decision_event("terminal_loss")
        )
        snap = sink.snapshot()
        assert len(snap.device_lifecycle_events) == 1
        assert len(snap.mesh_session_transition_events) == 1
        assert len(snap.dispatch_decision_events) == 1
        assert len(snap.recovery_decision_events) == 1

    def test_snapshot_counters(self):
        sink = RuntimeObservabilitySink(max_events=4)
        for _ in range(3):
            sink.record_dispatch_decision_event(build_dispatch_decision_event("local"))
        snap = sink.snapshot()
        assert snap.total_dispatch_events_emitted == 3


# ===========================================================================
# T. ObservabilitySnapshot round-trip
# ===========================================================================


class TestObservabilitySnapshotRoundTrip:
    """ObservabilitySnapshot round-trips through to_dict / to_json."""

    def test_to_dict_is_json_serialisable(self):
        snap = ObservabilitySnapshot()
        payload = json.dumps(snap.to_dict())
        assert "snapshot_id" in payload

    def test_to_json_contains_snapshot_id(self):
        snap = ObservabilitySnapshot()
        j = snap.to_json()
        d = json.loads(j)
        assert "snapshot_id" in d

    def test_snapshot_with_events(self):
        snap = ObservabilitySnapshot(
            device_lifecycle_events=[{"event_kind": "attach"}],
            total_device_events_emitted=1,
        )
        d = snap.to_dict()
        assert d["total_device_events_emitted"] == 1
        assert d["device_lifecycle_events"][0]["event_kind"] == "attach"


# ===========================================================================
# U–X. emit_* helpers
# ===========================================================================


class TestEmitHelpers:
    """emit_* helpers return events and record them in the global sink."""

    def setup_method(self):
        reset_observability_sink()

    def test_emit_device_lifecycle_event_returns_event(self):
        evt = emit_device_lifecycle_event("dev_01", "attach", reason="test")
        assert isinstance(evt, DeviceLifecycleEvent)
        assert evt.device_id == "dev_01"
        assert evt.event_kind == "attach"

    def test_emit_device_lifecycle_event_records_in_sink(self):
        emit_device_lifecycle_event("dev_02", "detach")
        events = get_observability_sink().list_device_lifecycle_events()
        assert any(e["device_id"] == "dev_02" for e in events)

    def test_emit_mesh_session_transition_event_returns_event(self):
        evt = emit_mesh_session_transition_event(
            "sess_001", "activate", prior_status="pending", new_status="active"
        )
        assert isinstance(evt, MeshSessionTransitionEvent)
        assert evt.session_id == "sess_001"
        assert evt.transition_kind == "activate"

    def test_emit_mesh_session_transition_event_records_in_sink(self):
        emit_mesh_session_transition_event("sess_002", "suspend")
        events = get_observability_sink().list_mesh_session_transition_events()
        assert any(e["session_id"] == "sess_002" for e in events)

    def test_emit_dispatch_decision_event_returns_event(self):
        evt = emit_dispatch_decision_event(
            "remote_handoff",
            decision_reason="eligible_target_found",
            executor_target_type="android_device",
        )
        assert isinstance(evt, DispatchDecisionEvent)
        assert evt.mode == "remote_handoff"

    def test_emit_dispatch_decision_event_records_in_sink(self):
        emit_dispatch_decision_event("local", decision_reason="no_target")
        events = get_observability_sink().list_dispatch_decision_events()
        assert any(e["mode"] == "local" for e in events)

    def test_emit_recovery_decision_event_returns_event(self):
        evt = emit_recovery_decision_event(
            "resumable_reassociation",
            is_resumable=True,
            reason="device_reconnected",
        )
        assert isinstance(evt, RecoveryDecisionEvent)
        assert evt.decision_kind == "resumable_reassociation"
        assert evt.is_resumable is True

    def test_emit_recovery_decision_event_records_in_sink(self):
        emit_recovery_decision_event("terminal_loss", is_resumable=False)
        events = get_observability_sink().list_recovery_decision_events()
        assert any(e["decision_kind"] == "terminal_loss" for e in events)


# ===========================================================================
# Y. build_observability_snapshot
# ===========================================================================


class TestBuildObservabilitySnapshot:
    """build_observability_snapshot returns a populated snapshot."""

    def setup_method(self):
        reset_observability_sink()

    def test_returns_observability_snapshot(self):
        snap = build_observability_snapshot()
        assert isinstance(snap, ObservabilitySnapshot)

    def test_snapshot_reflects_emitted_events(self):
        emit_device_lifecycle_event("dev_01", "attach")
        emit_dispatch_decision_event("local")
        snap = build_observability_snapshot()
        assert snap.total_device_events_emitted >= 1
        assert snap.total_dispatch_events_emitted >= 1

    def test_snapshot_is_json_serialisable(self):
        emit_mesh_session_transition_event("sess_001", "create")
        snap = build_observability_snapshot()
        payload = json.dumps(snap.to_dict())
        assert "mesh_session_transition_events" in payload


# ===========================================================================
# Z. Sentinel constants — contracts.runtime_observability
# ===========================================================================


class TestContractsSentinels:
    """Sentinel constants are importable from contracts.runtime_observability."""

    def test_is_authority_sentinel(self):
        assert RUNTIME_OBSERVABILITY_IS_AUTHORITY
        assert "PR-G" in RUNTIME_OBSERVABILITY_IS_AUTHORITY

    def test_device_lifecycle_policy_sentinel(self):
        assert DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY
        assert "PR-G" in DEVICE_LIFECYCLE_EVENTS_ARE_STRUCTURED_POLICY

    def test_mesh_session_policy_sentinel(self):
        assert MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY
        assert "PR-G" in MESH_SESSION_TRANSITIONS_ARE_OBSERVABLE_POLICY

    def test_dispatch_policy_sentinel(self):
        assert DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY
        assert "PR-G" in DISPATCH_DECISIONS_ARE_EXPLAINABLE_POLICY

    def test_recovery_policy_sentinel(self):
        assert RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY
        assert "PR-G" in RECOVERY_DECISIONS_ARE_TRACEABLE_POLICY

    def test_pr_g_sentinel(self):
        assert RUNTIME_OBSERVABILITY_PR_G_SENTINEL
        assert "PR-G" in RUNTIME_OBSERVABILITY_PR_G_SENTINEL


# ===========================================================================
# AA. Sentinel constants — core.runtime.runtime_observability_sink
# ===========================================================================


class TestSinkSentinels:
    """Sentinel constants are importable from core.runtime.runtime_observability_sink."""

    def test_sink_is_authority_sentinel(self):
        assert RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY
        assert "PR-G" in RUNTIME_OBSERVABILITY_SINK_IS_AUTHORITY

    def test_sink_emits_policy_sentinel(self):
        assert SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY
        assert "PR-G" in SINK_EMITS_ARE_PRODUCTION_OBSERVABLE_POLICY

    def test_sink_bounded_policy_sentinel(self):
        assert SINK_IS_BOUNDED_POLICY
        assert "PR-G" in SINK_IS_BOUNDED_POLICY

    def test_sink_pr_g_sentinel(self):
        assert RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL
        assert "PR-G" in RUNTIME_OBSERVABILITY_SINK_PR_G_SENTINEL

    def test_sink_max_events_constant(self):
        assert SINK_MAX_EVENTS_PER_KIND > 0


# ===========================================================================
# AB. emit_* helpers are gracefully non-raising
# ===========================================================================


class TestEmitHelpersGraceful:
    """emit_* helpers never raise even with pathological inputs."""

    def setup_method(self):
        reset_observability_sink()

    def test_emit_device_lifecycle_event_no_raise_with_none_fields(self):
        # Should not raise even if optional fields are None.
        result = emit_device_lifecycle_event("dev_01", "attach")
        assert result is not None  # basic case should succeed

    def test_emit_dispatch_decision_event_no_raise_with_empty_mode(self):
        result = emit_dispatch_decision_event("")
        # Empty mode is unusual but should not raise.
        assert result is not None

    def test_emit_recovery_decision_event_no_raise_with_string_kind(self):
        result = emit_recovery_decision_event("resumable_reassociation")
        assert result is not None


# ===========================================================================
# AC. reset_observability_sink()
# ===========================================================================


class TestResetObservabilitySink:
    """reset_observability_sink() clears the singleton."""

    def test_reset_clears_singleton(self):
        sink1 = get_observability_sink()
        sink1.record_device_lifecycle_event(build_device_lifecycle_event("d1", "attach"))
        assert len(sink1.list_device_lifecycle_events()) == 1

        reset_observability_sink()
        sink2 = get_observability_sink()
        # New singleton should be empty.
        assert len(sink2.list_device_lifecycle_events()) == 0

    def test_reset_creates_new_singleton(self):
        sink1 = get_observability_sink()
        reset_observability_sink()
        sink2 = get_observability_sink()
        assert sink1 is not sink2


# ===========================================================================
# AD. DeviceLifecycleEvent.to_json() round-trip
# ===========================================================================


class TestDeviceLifecycleEventToJson:
    """DeviceLifecycleEvent.to_json() round-trips correctly."""

    def test_to_json_is_valid_json(self):
        evt = build_device_lifecycle_event(
            "dev_01", "attach", reason="test", trace_id="t1"
        )
        j = evt.to_json()
        d = json.loads(j)
        assert d["device_id"] == "dev_01"
        assert d["event_kind"] == "attach"
        assert d["reason"] == "test"
        assert d["trace_id"] == "t1"


# ===========================================================================
# AE. terminal_loss — is_resumable=False
# ===========================================================================


class TestTerminalLossIsNotResumable:
    """RecoveryDecisionEvent with terminal_loss has is_resumable=False."""

    def test_terminal_loss_is_not_resumable(self):
        evt = build_recovery_decision_event(
            RecoveryDecisionKind.terminal_loss,
            is_resumable=False,
            interruption_class="terminal",
            reason="unrecoverable_state",
        )
        assert evt.decision_kind == "terminal_loss"
        assert evt.is_resumable is False

    def test_terminal_loss_to_dict_is_resumable_false(self):
        evt = build_recovery_decision_event("terminal_loss", is_resumable=False)
        d = evt.to_dict()
        assert d["is_resumable"] is False


# ===========================================================================
# AF. resumable_reassociation — is_resumable=True
# ===========================================================================


class TestResumableReassociationIsResumable:
    """RecoveryDecisionEvent with resumable_reassociation has is_resumable=True."""

    def test_resumable_reassociation_is_resumable(self):
        evt = build_recovery_decision_event(
            RecoveryDecisionKind.resumable_reassociation,
            is_resumable=True,
            continuity_id="cont_001",
            prior_dispatch_id="disp_abc",
            reason="device_reconnected_successfully",
        )
        assert evt.decision_kind == "resumable_reassociation"
        assert evt.is_resumable is True
        assert evt.continuity_id == "cont_001"

    def test_resumable_to_dict_is_resumable_true(self):
        evt = build_recovery_decision_event("resumable_reassociation", is_resumable=True)
        d = evt.to_dict()
        assert d["is_resumable"] is True
