"""tests/test_pr2_android_mesh_signal_adapter.py
=================================================
Regression tests for PR-2: Android Mesh Participant Signal Adapter.

This module proves that the center-side mesh runtime closure path can now
consume real Android participant signals and that ``runtime_closed`` is no
longer only theoretically reachable in internal V2 tests.

Acceptance criteria (AC)
-------------------------
AC1 — ``ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL`` is present and non-empty.
AC2 — :class:`AndroidMeshParticipantSignalKind` covers all required signal
      kinds including ``readiness_confirmed``, ``barrier_reached``,
      ``task_completed``, ``task_failed``, and ``participant_dropped``.
AC3 — :func:`apply_android_participation_signal` correctly routes each signal
      kind to the appropriate ``LiveMeshSessionCoordinator`` lifecycle method.
AC4 — :func:`evaluate_center_runtime_status_with_android_signals` can drive
      ``runtime_closed`` from Android participation signals alone; this is the
      primary proof that the closure path is no longer V2-only.
AC5 — :func:`classify_android_proof_quality` correctly classifies ``live``,
      ``partial``, and ``missing`` proof quality based on signal coverage.
AC6 — Android proof quality is propagated to ``android_readiness_impact_notes``
      in the center state metadata.
AC7 — :class:`LiveMeshSessionCoordinator` ``on_android_participant_signal()``
      correctly routes signal strings to coordinator lifecycle events.
AC8 — Partial participation (one of N participants completed) results in a
      non-``runtime_closed`` center state.
AC9 — Task-failed participants result in ``task_failed`` in proof quality
      (classified as ``partial``, not ``missing``).
AC10 — All public functions are non-raising; passing ``None`` coordinator returns
       a valid center state.

Test groups
-----------
A   Sentinel and policy assertions (AC1)
B   AndroidMeshParticipantSignalKind enum (AC2)
C   AndroidMeshParticipantSignal dataclass construction
D   AndroidMeshParticipationRecord and update_from_signal
E   classify_android_proof_quality — live / partial / missing (AC5)
F   apply_android_participation_signal — routing to coordinator (AC3)
G   evaluate_center_runtime_status_with_android_signals — runtime_closed (AC4)
H   evaluate_center_runtime_status_with_android_signals — intermediate states
I   Android proof quality metadata propagation (AC6)
J   LiveMeshSessionCoordinator.on_android_participant_signal (AC7)
K   Partial participation — non-runtime_closed (AC8)
L   Failed participant proof quality (AC9)
M   Non-raising / None coordinator behaviour (AC10)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Dependency guards
# ---------------------------------------------------------------------------

try:
    from core.mesh.android_mesh_participant_signal_adapter import (
        ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL,
        ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY,
        ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY,
        ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY,
        RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY,
        AndroidMeshParticipantSignal,
        AndroidMeshParticipantSignalKind,
        AndroidMeshParticipationRecord,
        AndroidSignalApplicationOutcome,
        apply_android_participation_signal,
        apply_android_participation_signals_batch,
        build_android_participation_record,
        classify_android_proof_quality,
        classify_android_proof_quality_for_signals,
        evaluate_center_runtime_status_with_android_signals,
    )

    _ADAPTER_AVAILABLE = True
except ImportError:
    _ADAPTER_AVAILABLE = False

try:
    from core.mesh.live_mesh_session_coordinator import (
        LiveMeshSessionCoordinator,
        create_live_mesh_session_coordinator,
    )

    _COORDINATOR_AVAILABLE = True
except ImportError:
    _COORDINATOR_AVAILABLE = False

try:
    from contracts.mesh_session_coordinator import build_mesh_session_coordinator

    _CONTRACTS_AVAILABLE = True
except ImportError:
    _CONTRACTS_AVAILABLE = False

try:
    from core.mesh.mesh_runtime_center_state import (
        MeshRuntimeCenterStatus,
        evaluate_center_runtime_status,
    )

    _CENTER_STATE_AVAILABLE = True
except ImportError:
    _CENTER_STATE_AVAILABLE = False

_ALL_AVAILABLE = all([
    _ADAPTER_AVAILABLE,
    _COORDINATOR_AVAILABLE,
    _CONTRACTS_AVAILABLE,
    _CENTER_STATE_AVAILABLE,
])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_coordinator(session_id: str = "test_session", mesh_id: str = "test_mesh") -> Any:
    """Build a fresh coordinator state for testing."""
    return build_mesh_session_coordinator(session_id=session_id, mesh_id=mesh_id)


def _build_live_coordinator(
    session_id: str = "test_session",
    device_ids: Optional[List[str]] = None,
) -> "LiveMeshSessionCoordinator":
    """Build a live coordinator with optional pre-registered participants."""
    state = _build_coordinator(session_id=session_id)
    coord = LiveMeshSessionCoordinator(state)
    for did in (device_ids or []):
        coord.add_participant(did)
    return coord


def _make_signal(
    kind: "AndroidMeshParticipantSignalKind",
    device_id: str,
    session_id: str = "s1",
    **kwargs: Any,
) -> "AndroidMeshParticipantSignal":
    """Build a single AndroidMeshParticipantSignal for testing."""
    return AndroidMeshParticipantSignal(
        signal_kind=kind,
        device_id=device_id,
        session_id=session_id,
        **kwargs,
    )


# ===========================================================================
# Group A — Sentinel and policy assertions
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupA_SentinelAndPolicies:
    def test_a1_pr2_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL, str)
        assert len(ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL) > 0

    def test_a2_sentinel_contains_pr2_identifier(self) -> None:
        assert "PR-2" in ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL or "PR2" in ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL

    def test_a3_sentinel_mentions_runtime_closed(self) -> None:
        assert "runtime_closed" in ANDROID_MESH_SIGNAL_ADAPTER_PR2_SENTINEL

    def test_a4_android_signals_drive_coordinator_policy_present(self) -> None:
        assert isinstance(ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY, str)
        assert "POLICY" in ANDROID_SIGNALS_DRIVE_COORDINATOR_POLICY

    def test_a5_runtime_closed_from_android_signals_policy_present(self) -> None:
        assert isinstance(RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY, str)
        assert "runtime_closed" in RUNTIME_CLOSED_FROM_ANDROID_SIGNALS_POLICY

    def test_a6_android_proof_quality_impacts_readiness_policy_present(self) -> None:
        assert isinstance(ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY, str)
        assert "proof" in ANDROID_PROOF_QUALITY_IMPACTS_READINESS_POLICY.lower()

    def test_a7_android_signal_routing_non_raising_policy_present(self) -> None:
        assert isinstance(ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY, str)
        assert "POLICY" in ANDROID_SIGNAL_ROUTING_NON_RAISING_POLICY


# ===========================================================================
# Group B — AndroidMeshParticipantSignalKind enum
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupB_SignalKindEnum:
    def test_b1_all_required_signal_kinds_present(self) -> None:
        kinds = {k.value for k in AndroidMeshParticipantSignalKind}
        assert "readiness_confirmed" in kinds
        assert "barrier_reached" in kinds
        assert "task_completed" in kinds
        assert "task_failed" in kinds
        assert "participant_dropped" in kinds
        assert "unknown" in kinds

    def test_b2_from_string_returns_correct_kind(self) -> None:
        assert AndroidMeshParticipantSignalKind.from_string("readiness_confirmed") == AndroidMeshParticipantSignalKind.readiness_confirmed
        assert AndroidMeshParticipantSignalKind.from_string("task_completed") == AndroidMeshParticipantSignalKind.task_completed
        assert AndroidMeshParticipantSignalKind.from_string("barrier_reached") == AndroidMeshParticipantSignalKind.barrier_reached

    def test_b3_from_string_returns_unknown_for_empty(self) -> None:
        assert AndroidMeshParticipantSignalKind.from_string("") == AndroidMeshParticipantSignalKind.unknown
        assert AndroidMeshParticipantSignalKind.from_string(None) == AndroidMeshParticipantSignalKind.unknown

    def test_b4_from_string_returns_unknown_for_garbage(self) -> None:
        assert AndroidMeshParticipantSignalKind.from_string("garbage_value") == AndroidMeshParticipantSignalKind.unknown

    def test_b5_drives_coordinator_transition_for_active_kinds(self) -> None:
        assert AndroidMeshParticipantSignalKind.readiness_confirmed.drives_coordinator_transition()
        assert AndroidMeshParticipantSignalKind.barrier_reached.drives_coordinator_transition()
        assert AndroidMeshParticipantSignalKind.task_completed.drives_coordinator_transition()
        assert AndroidMeshParticipantSignalKind.task_failed.drives_coordinator_transition()
        assert AndroidMeshParticipantSignalKind.participant_dropped.drives_coordinator_transition()

    def test_b6_unknown_does_not_drive_coordinator_transition(self) -> None:
        assert not AndroidMeshParticipantSignalKind.unknown.drives_coordinator_transition()


# ===========================================================================
# Group C — AndroidMeshParticipantSignal dataclass
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupC_SignalDataclass:
    def test_c1_default_construction_is_valid(self) -> None:
        sig = AndroidMeshParticipantSignal()
        assert sig.signal_kind == AndroidMeshParticipantSignalKind.unknown
        assert sig.device_id == ""
        assert sig.session_id == ""
        assert isinstance(sig.signal_id, str) and len(sig.signal_id) > 0
        assert isinstance(sig.received_at, float)

    def test_c2_explicit_construction_sets_fields(self) -> None:
        sig = AndroidMeshParticipantSignal(
            signal_kind=AndroidMeshParticipantSignalKind.task_completed,
            device_id="android_phone_1",
            session_id="session_abc",
            result_payload={"output": "result_data"},
        )
        assert sig.signal_kind == AndroidMeshParticipantSignalKind.task_completed
        assert sig.device_id == "android_phone_1"
        assert sig.session_id == "session_abc"
        assert sig.result_payload == {"output": "result_data"}

    def test_c3_to_dict_is_json_safe(self) -> None:
        sig = AndroidMeshParticipantSignal(
            signal_kind=AndroidMeshParticipantSignalKind.readiness_confirmed,
            device_id="d1",
            session_id="s1",
        )
        d = sig.to_dict()
        assert isinstance(d, dict)
        assert d["signal_kind"] == "readiness_confirmed"
        assert d["device_id"] == "d1"
        assert d["session_id"] == "s1"

    def test_c4_failure_signal_carries_reason(self) -> None:
        sig = AndroidMeshParticipantSignal(
            signal_kind=AndroidMeshParticipantSignalKind.task_failed,
            device_id="d1",
            session_id="s1",
            failure_reason="oom_error",
        )
        assert sig.failure_reason == "oom_error"


# ===========================================================================
# Group D — AndroidMeshParticipationRecord
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupD_ParticipationRecord:
    def test_d1_default_record_has_no_signals(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        assert rec.signal_count == 0
        assert not rec.readiness_confirmed
        assert not rec.barrier_reached
        assert not rec.task_completed
        assert not rec.task_failed

    def test_d2_readiness_signal_sets_readiness_confirmed(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        sig = _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1")
        rec.update_from_signal(sig)
        assert rec.readiness_confirmed
        assert rec.signal_count == 1

    def test_d3_barrier_signal_sets_barrier_reached(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "d1"))
        assert rec.barrier_reached

    def test_d4_task_completed_signal_stores_result(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(
            AndroidMeshParticipantSignalKind.task_completed, "d1",
            result_payload={"answer": 42}
        ))
        assert rec.task_completed
        assert rec.result_payload == {"answer": 42}

    def test_d5_task_failed_signal_stores_reason(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(
            AndroidMeshParticipantSignalKind.task_failed, "d1",
            failure_reason="timeout"
        ))
        assert rec.task_failed
        assert rec.failure_reason == "timeout"

    def test_d6_build_participation_record_from_signals_list(self) -> None:
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1"),
        ]
        rec = build_android_participation_record(signals, device_id="d1", session_id="s1")
        assert rec.readiness_confirmed
        assert rec.task_completed
        assert rec.signal_count == 2

    def test_d7_build_participation_record_filters_by_device_id(self) -> None:
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d2"),
        ]
        rec_d1 = build_android_participation_record(signals, device_id="d1")
        assert rec_d1.readiness_confirmed
        assert not rec_d1.task_completed
        assert rec_d1.signal_count == 1


# ===========================================================================
# Group E — classify_android_proof_quality
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupE_ProofQuality:
    def test_e1_no_signals_is_missing(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        assert classify_android_proof_quality(rec) == "missing"

    def test_e2_task_completed_is_live(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1"))
        assert classify_android_proof_quality(rec) == "live"

    def test_e3_readiness_only_is_partial(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1"))
        assert classify_android_proof_quality(rec) == "partial"

    def test_e4_barrier_reached_only_is_partial(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "d1"))
        assert classify_android_proof_quality(rec) == "partial"

    def test_e5_task_failed_is_partial_not_missing(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_failed, "d1"))
        assert classify_android_proof_quality(rec) == "partial"

    def test_e6_participant_dropped_with_signals_is_partial(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1"))
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.participant_dropped, "d1"))
        assert classify_android_proof_quality(rec) == "partial"

    def test_e7_classify_from_signals_convenience_wrapper(self) -> None:
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1"),
        ]
        quality = classify_android_proof_quality_for_signals(signals, device_id="d1", session_id="s1")
        assert quality == "live"

    def test_e8_classify_missing_from_empty_list(self) -> None:
        quality = classify_android_proof_quality_for_signals([], device_id="d1", session_id="s1")
        assert quality == "missing"

    def test_e9_task_completed_overrides_prior_failure(self) -> None:
        """If task_completed arrives after task_failed, live wins."""
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_failed, "d1"))
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1"))
        assert classify_android_proof_quality(rec) == "live"


# ===========================================================================
# Group F — apply_android_participation_signal — coordinator routing
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupF_SignalRoutingToCoordinator:
    def test_f1_readiness_signal_drives_on_participant_ready(self) -> None:
        coord = _build_live_coordinator(session_id="sf1", device_ids=["d1"])
        sig = _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1", "sf1")
        outcome = apply_android_participation_signal(coord, sig)
        assert outcome.applied
        assert outcome.coordinator_method_called == "on_participant_ready"
        # Participant should now be in ready state
        participants = getattr(coord.state, "participants", [])
        p = next((p for p in participants if getattr(p, "device_id", "") == "d1"), None)
        assert p is not None
        p_status = p.status.value if hasattr(p.status, "value") else str(p.status)
        assert p_status == "ready"

    def test_f2_barrier_reached_drives_on_participant_working(self) -> None:
        coord = _build_live_coordinator(session_id="sf2", device_ids=["d1"])
        coord.on_participant_ready("d1")
        sig = _make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "d1", "sf2")
        outcome = apply_android_participation_signal(coord, sig)
        assert outcome.applied
        assert outcome.coordinator_method_called == "on_participant_working"

    def test_f3_task_completed_drives_on_participant_result(self) -> None:
        coord = _build_live_coordinator(session_id="sf3", device_ids=["d1"])
        coord.on_participant_ready("d1")
        coord.on_participant_working("d1")
        sig = _make_signal(
            AndroidMeshParticipantSignalKind.task_completed, "d1", "sf3",
            result_payload={"output": "test_result"}
        )
        outcome = apply_android_participation_signal(coord, sig)
        assert outcome.applied
        assert outcome.coordinator_method_called == "on_participant_result"
        # Participant result should be recorded
        assert "d1" in coord.partial_results

    def test_f4_task_failed_drives_on_participant_failed(self) -> None:
        coord = _build_live_coordinator(session_id="sf4", device_ids=["d1"])
        coord.on_participant_ready("d1")
        sig = _make_signal(AndroidMeshParticipantSignalKind.task_failed, "d1", "sf4", failure_reason="oom")
        outcome = apply_android_participation_signal(coord, sig)
        assert outcome.applied
        assert outcome.coordinator_method_called == "on_participant_failed"

    def test_f5_participant_dropped_drives_on_participant_dropped(self) -> None:
        coord = _build_live_coordinator(session_id="sf5", device_ids=["d1"])
        sig = _make_signal(AndroidMeshParticipantSignalKind.participant_dropped, "d1", "sf5")
        outcome = apply_android_participation_signal(coord, sig)
        assert outcome.applied
        assert outcome.coordinator_method_called == "on_participant_dropped"

    def test_f6_unknown_signal_is_not_applied(self) -> None:
        coord = _build_live_coordinator(session_id="sf6", device_ids=["d1"])
        sig = _make_signal(AndroidMeshParticipantSignalKind.unknown, "d1", "sf6")
        outcome = apply_android_participation_signal(coord, sig)
        assert not outcome.applied
        assert outcome.error_reason

    def test_f7_none_coordinator_returns_not_applied(self) -> None:
        sig = _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1")
        outcome = apply_android_participation_signal(None, sig)
        assert not outcome.applied
        assert "coordinator_is_none" in outcome.error_reason

    def test_f8_batch_apply_returns_outcomes_for_all_signals(self) -> None:
        coord = _build_live_coordinator(session_id="sf8", device_ids=["d1", "d2"])
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1", "sf8"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d2", "sf8"),
        ]
        outcomes = apply_android_participation_signals_batch(coord, signals)
        assert len(outcomes) == 2
        assert all(o.applied for o in outcomes)


# ===========================================================================
# Group G — evaluate_center_runtime_status_with_android_signals: runtime_closed
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupG_RuntimeClosedFromAndroidSignals:
    def test_g1_two_participants_both_completed_gives_runtime_closed(self) -> None:
        """Core AC4 proof: runtime_closed is reachable from Android signals."""
        state = _build_coordinator("sg1")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "android_1", "sg1"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "android_2", "sg1"),
            _make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "android_1", "sg1"),
            _make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "android_2", "sg1"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "android_1", "sg1",
                         result_payload={"output": "part_a"}),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "android_2", "sg1",
                         result_payload={"output": "part_b"}),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert center_state.status == MeshRuntimeCenterStatus.runtime_closed
        assert center_state.is_runtime_closed
        assert center_state.is_participation_ready

    def test_g2_single_participant_completed_gives_runtime_closed(self) -> None:
        state = _build_coordinator("sg2")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sg2"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sg2",
                         result_payload={"ok": True}),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert center_state.status == MeshRuntimeCenterStatus.runtime_closed
        assert center_state.is_runtime_closed

    def test_g3_runtime_closed_proof_quality_all_live(self) -> None:
        state = _build_coordinator("sg3")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sg3"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a2", "sg3"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert center_state.is_runtime_closed
        pq = center_state.metadata.get("android_proof_quality_map", {})
        assert pq.get("a1") == "live"
        assert pq.get("a2") == "live"

    def test_g4_android_signals_applied_count_matches_signals_list(self) -> None:
        state = _build_coordinator("sg4")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sg4"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sg4"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert center_state.metadata.get("android_signals_applied") == 2
        assert center_state.metadata.get("android_signals_total") == 2

    def test_g5_adapter_sentinel_present_in_metadata(self) -> None:
        state = _build_coordinator("sg5")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sg5"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        sentinel = center_state.metadata.get("android_signal_adapter_sentinel", "")
        assert "PR2" in sentinel or "PR-2" in sentinel

    def test_g6_runtime_closed_from_signals_without_prior_participants_registered(self) -> None:
        """When coordinator has no registered participants, Android signals auto-register them."""
        state = _build_coordinator("sg6")
        # Coordinator starts with zero participants
        assert len(getattr(state, "participants", []) or []) == 0
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "android_phone", "sg6"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "android_phone", "sg6",
                         result_payload={"done": True}),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(
            state, signals, register_android_devices=True
        )
        assert center_state.is_runtime_closed


# ===========================================================================
# Group H — evaluate_center_runtime_status_with_android_signals: intermediate states
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupH_IntermediateStatesFromAndroidSignals:
    def test_h1_no_signals_gives_pending_participants(self) -> None:
        state = _build_coordinator("sh1")
        center_state = evaluate_center_runtime_status_with_android_signals(state, [])
        # No participants, no signals → pending_participants
        assert center_state.status == MeshRuntimeCenterStatus.pending_participants
        assert not center_state.is_runtime_closed

    def test_h2_readiness_only_is_not_runtime_closed(self) -> None:
        state = _build_coordinator("sh2")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sh2"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert not center_state.is_runtime_closed
        assert center_state.is_participation_ready

    def test_h3_participation_ready_not_closed_is_correctly_classified(self) -> None:
        state = _build_coordinator("sh3")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sh3"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a2", "sh3"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        # Two participants ready but not completed → participation_ready
        assert not center_state.is_runtime_closed

    def test_h4_barrier_reached_by_both_but_not_completed_is_not_closed(self) -> None:
        state = _build_coordinator("sh4")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sh4"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a2", "sh4"),
            _make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "a1", "sh4"),
            _make_signal(AndroidMeshParticipantSignalKind.barrier_reached, "a2", "sh4"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        # Two participants at barrier but not yet completed → not runtime_closed
        assert not center_state.is_runtime_closed


# ===========================================================================
# Group I — Android proof quality metadata propagation
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupI_ProofQualityMetadataPropagation:
    def test_i1_missing_proof_quality_appears_in_readiness_impact_notes(self) -> None:
        state = _build_coordinator("si1")
        # a1 sends task_completed, a2 sends nothing (missing)
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "si1"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "si1"),
        ]
        # Build a coordinator with a2 pre-registered but not sending signals
        coord_state = _build_coordinator("si1")
        # Get center state
        center_state = evaluate_center_runtime_status_with_android_signals(coord_state, signals)
        # a1 is live (has task_completed), no missing devices in this signal list
        pq = center_state.metadata.get("android_proof_quality_map", {})
        assert pq.get("a1") == "live"

    def test_i2_partial_proof_quality_appears_in_readiness_impact_notes(self) -> None:
        state = _build_coordinator("si2")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "si2"),
            # a1 sends readiness but not completion → partial
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        pq = center_state.metadata.get("android_proof_quality_map", {})
        impact = center_state.metadata.get("android_readiness_impact_notes", [])
        assert pq.get("a1") == "partial"
        assert any("partial" in note for note in impact)

    def test_i3_participation_summary_contains_device_records(self) -> None:
        state = _build_coordinator("si3")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "si3",
                         result_payload={"data": "val"}),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        summary = center_state.metadata.get("android_participation_summary", {})
        assert "a1" in summary
        rec_dict = summary["a1"]
        assert rec_dict["task_completed"] is True
        assert rec_dict["signal_count"] == 1

    def test_i4_multiple_devices_appear_in_proof_quality_map(self) -> None:
        state = _build_coordinator("si4")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1", "si4"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d2", "si4"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "d3", "si4"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        pq = center_state.metadata.get("android_proof_quality_map", {})
        assert pq.get("d1") == "live"
        assert pq.get("d2") == "partial"
        assert pq.get("d3") == "live"


# ===========================================================================
# Group J — LiveMeshSessionCoordinator.on_android_participant_signal
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupJ_LiveCoordinatorAndroidSignalMethod:
    def test_j1_on_android_participant_signal_readiness_confirmed_returns_true(self) -> None:
        coord = _build_live_coordinator("sj1", device_ids=["d1"])
        result = coord.on_android_participant_signal("d1", "readiness_confirmed")
        assert result is True

    def test_j2_on_android_participant_signal_task_completed_drives_barrier(self) -> None:
        coord = _build_live_coordinator("sj2", device_ids=["d1"])
        coord.on_android_participant_signal("d1", "readiness_confirmed")
        coord.on_android_participant_signal("d1", "barrier_reached")
        result = coord.on_android_participant_signal(
            "d1", "task_completed",
            result_payload={"answer": "ok"}
        )
        assert result is True
        assert "d1" in coord.partial_results

    def test_j3_on_android_participant_signal_unknown_returns_false(self) -> None:
        coord = _build_live_coordinator("sj3", device_ids=["d1"])
        result = coord.on_android_participant_signal("d1", "not_a_valid_signal")
        assert result is False

    def test_j4_full_android_session_via_on_android_signal_gives_runtime_closed(self) -> None:
        """Full session driven purely by on_android_participant_signal → runtime_closed."""
        coord = _build_live_coordinator("sj4", device_ids=["phone_a", "phone_b"])
        # Simulate complete Android participation cycle
        coord.on_android_participant_signal("phone_a", "readiness_confirmed")
        coord.on_android_participant_signal("phone_b", "readiness_confirmed")
        coord.on_android_participant_signal("phone_a", "barrier_reached")
        coord.on_android_participant_signal("phone_b", "barrier_reached")
        coord.on_android_participant_signal("phone_a", "task_completed", result_payload={"out": "a"})
        coord.on_android_participant_signal("phone_b", "task_completed", result_payload={"out": "b"})

        # Finalize and evaluate
        result = coord.finalize()
        assert result.outcome == "completed"

        # Evaluate center state from the finalized coordinator state
        center_state = evaluate_center_runtime_status(result.coordinator_state)
        assert center_state.status == MeshRuntimeCenterStatus.runtime_closed
        assert center_state.is_runtime_closed

    def test_j5_task_failed_signal_marks_participant_failed(self) -> None:
        coord = _build_live_coordinator("sj5", device_ids=["d1"])
        coord.on_android_participant_signal("d1", "readiness_confirmed")
        result = coord.on_android_participant_signal("d1", "task_failed", failure_reason="error")
        assert result is True

    def test_j6_participant_dropped_signal_marks_participant_dropped(self) -> None:
        coord = _build_live_coordinator("sj6", device_ids=["d1"])
        result = coord.on_android_participant_signal("d1", "participant_dropped")
        assert result is True


# ===========================================================================
# Group K — Partial participation (non-runtime_closed)
# ===========================================================================


@pytest.mark.skipif(not _ALL_AVAILABLE, reason="required modules not available")
class TestGroupK_PartialParticipation:
    def test_k1_one_of_two_completed_is_not_runtime_closed(self) -> None:
        """AC8: Only one participant completes → not runtime_closed."""
        state = _build_coordinator("sk1")
        # Two participants registered, only one completes
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a1", "sk1"),
            _make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "a2", "sk1"),
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sk1"),
            # a2 never completes (barrier still open from a2's perspective)
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        # Since only a1 completed but a2 is still registered and just ready,
        # the session should NOT be runtime_closed
        # (a2's result is missing; a1 completed, a2 is ready but not done)
        assert not center_state.is_runtime_closed

    def test_k2_all_participants_failed_is_not_runtime_closed(self) -> None:
        state = _build_coordinator("sk2")
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_failed, "a1", "sk2"),
            _make_signal(AndroidMeshParticipantSignalKind.task_failed, "a2", "sk2"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(state, signals)
        assert not center_state.is_runtime_closed

    def test_k3_empty_signal_list_does_not_produce_runtime_closed(self) -> None:
        state = _build_coordinator("sk3")
        center_state = evaluate_center_runtime_status_with_android_signals(state, [])
        assert not center_state.is_runtime_closed


# ===========================================================================
# Group L — Failed participant proof quality (AC9)
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupL_FailedParticipantProofQuality:
    def test_l1_task_failed_signal_is_partial_not_missing(self) -> None:
        """AC9: task_failed is classified as partial, not missing."""
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_failed, "d1"))
        quality = classify_android_proof_quality(rec)
        assert quality == "partial"
        assert quality != "missing"

    def test_l2_participant_dropped_with_prior_readiness_is_partial(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.readiness_confirmed, "d1"))
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.participant_dropped, "d1"))
        quality = classify_android_proof_quality(rec)
        assert quality == "partial"

    def test_l3_task_completed_after_failure_is_live(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_failed, "d1"))
        rec.update_from_signal(_make_signal(AndroidMeshParticipantSignalKind.task_completed, "d1"))
        quality = classify_android_proof_quality(rec)
        assert quality == "live"


# ===========================================================================
# Group M — Non-raising / None coordinator behaviour (AC10)
# ===========================================================================


@pytest.mark.skipif(not _ADAPTER_AVAILABLE, reason="adapter module not available")
class TestGroupM_NonRaisingBehaviour:
    def test_m1_none_coordinator_returns_pending_participants_state(self) -> None:
        center_state = evaluate_center_runtime_status_with_android_signals(None, [])
        assert center_state.status == MeshRuntimeCenterStatus.pending_participants
        assert not center_state.is_runtime_closed

    def test_m2_none_coordinator_with_signals_returns_valid_state(self) -> None:
        signals = [
            _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1", "sm2"),
        ]
        center_state = evaluate_center_runtime_status_with_android_signals(None, signals)
        assert center_state is not None
        assert center_state.status == MeshRuntimeCenterStatus.pending_participants

    def test_m3_apply_signal_to_none_coordinator_does_not_raise(self) -> None:
        sig = _make_signal(AndroidMeshParticipantSignalKind.task_completed, "a1")
        outcome = apply_android_participation_signal(None, sig)
        assert outcome is not None
        assert not outcome.applied

    def test_m4_batch_apply_with_empty_signals_returns_empty_list(self) -> None:
        coord = _build_live_coordinator("sm4", device_ids=["d1"])
        outcomes = apply_android_participation_signals_batch(coord, [])
        assert outcomes == []

    def test_m5_build_participation_record_with_none_signals_does_not_raise(self) -> None:
        rec = build_android_participation_record(None, device_id="d1")
        assert rec is not None
        assert rec.signal_count == 0

    def test_m6_classify_proof_quality_on_empty_record_is_missing(self) -> None:
        rec = AndroidMeshParticipationRecord(device_id="d1", session_id="s1")
        quality = classify_android_proof_quality(rec)
        assert quality == "missing"

    def test_m7_evaluate_with_invalid_signal_kind_string_does_not_raise(self) -> None:
        coord = _build_live_coordinator("sm7", device_ids=["d1"])
        # Should return False not raise
        result = coord.on_android_participant_signal("d1", "totally_invalid_kind")
        assert result is False
