"""tests/test_pr7_post533_attached_runtime_session.py
=======================================================
Tests for PR package 7 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Attached-Runtime Session Semantics.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — AttachmentState enum: all values present, from_string(), is_active(),
     is_terminal(), allows_reconnect().
C  — AttachmentLifecycleSignal enum: all values present, from_string().
D  — AttachedRuntimeSessionRecord: construction, defaults, to_dict(),
     from_dict(), to_json(), round-trip.
E  — AttachedRuntimeSessionSnapshot: construction, defaults, to_dict(),
     to_json().
F  — State-machine: attach signal from various states.
G  — State-machine: detach signal.
H  — State-machine: disconnect signal.
I  — State-machine: disable signal.
J  — State-machine: invalidate signal (permanent terminal).
K  — State-machine: reconnect signal from disconnected restores attached.
L  — State-machine: reconnect has no effect from terminal non-disconnected.
M  — AttachedRuntimeSessionRuntime: attach creates record.
N  — AttachedRuntimeSessionRuntime: attach is idempotent for active session.
O  — AttachedRuntimeSessionRuntime: re-attach after detached creates new session.
P  — AttachedRuntimeSessionRuntime: invalidated session blocks re-attach.
Q  — AttachedRuntimeSessionRuntime: apply_signal returns None for unknown device.
R  — AttachedRuntimeSessionRuntime: get() returns None for unknown device.
S  — AttachedRuntimeSessionRuntime: list_active() excludes terminal records.
T  — AttachedRuntimeSessionRuntime: list_all() includes all records.
U  — AttachedRuntimeSessionRuntime: ring-buffer eviction at capacity.
V  — AttachedRuntimeSessionRuntime: reset() clears all records.
W  — attach_runtime_session() module-level function (default runtime).
X  — apply_lifecycle_signal() module-level function (default runtime).
Y  — get_attached_runtime_session() module-level function (default runtime).
Z  — list_active_attached_sessions() module-level function.
AA — build_attached_runtime_session_snapshot() returns correct counts.
AB — build_attached_runtime_session_snapshot() serialises records.
AC — core.runtime re-exports: all PR-7 symbols accessible from core.runtime.
AD — projection.py sentinel: ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 is present
     and not UNAVAILABLE.
AE — End-to-end: Android join_runtime device attaches, then disconnects,
     then reconnects.
AF — End-to-end: control_only device attaches, detaches, re-attaches.
AG — End-to-end: observer_only device attaches; policy sentinel asserts
     non-promotability.
AH — End-to-end: device is disabled; reconnect has no effect.
AI — End-to-end: device is invalidated; all subsequent signals are no-ops.
AJ — Metadata: metadata is merged on idempotent re-attach.
AK — Metadata: metadata is merged on apply_signal.
AL — Thread safety: concurrent attaches for distinct devices.
AM — Serialisation round-trip: AttachedRuntimeSessionRecord to_dict →
     from_dict preserves all fields.
AN — Serialisation round-trip: AttachedRuntimeSessionRecord to_json produces
     valid JSON.
AO — Serialisation round-trip: AttachedRuntimeSessionSnapshot to_json produces
     valid JSON.
AP — Policy sentinels are non-empty strings.
AQ — AttachmentState values cover the full lifecycle vocabulary.
AR — Multiple devices: each gets its own session record.
AS — Session IDs are unique across records.
AT — attached_at is set at creation time; last_signal_at updates on signal.
AU — Snapshot authority and alignment_sentinel are set to module constants.
"""

from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from core.attached_runtime_session import (
    # Sentinels
    ATTACHED_RUNTIME_SESSION_AUTHORITY,
    ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY,
    TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY,
    ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY,
    DETACH_CLOSES_SESSION_GRACEFULLY_POLICY,
    DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY,
    DISABLE_PREVENTS_REATTACH_POLICY,
    INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY,
    RECONNECT_RESTORES_ATTACHED_STATE_POLICY,
    OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY,
    ATTACHED_RUNTIME_SESSION_ALIGNED_PR7,
    # Enums
    AttachmentState,
    AttachmentLifecycleSignal,
    # Dataclasses
    AttachedRuntimeSessionRecord,
    AttachedRuntimeSessionSnapshot,
    # Runtime
    AttachedRuntimeSessionRuntime,
    # Functions
    attach_runtime_session,
    apply_lifecycle_signal,
    get_attached_runtime_session,
    list_active_attached_sessions,
    build_attached_runtime_session_snapshot,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_runtime(capacity: int = 128) -> AttachedRuntimeSessionRuntime:
    """Return a fresh, isolated AttachedRuntimeSessionRuntime for each test."""
    return AttachedRuntimeSessionRuntime(capacity=capacity)


def _device_id() -> str:
    return f"device-{uuid.uuid4().hex[:8]}"


# ===========================================================================
# A — Policy sentinels
# ===========================================================================

class TestPolicySentinels:
    def test_a_authority_sentinel_present(self):
        assert isinstance(ATTACHED_RUNTIME_SESSION_AUTHORITY, str)
        assert "AUTHORITY" in ATTACHED_RUNTIME_SESSION_AUTHORITY
        assert len(ATTACHED_RUNTIME_SESSION_AUTHORITY) > 20

    def test_a_persists_policy_present(self):
        assert isinstance(
            ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY, str
        )
        assert len(ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY) > 20

    def test_a_transient_policy_present(self):
        assert isinstance(TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY, str)
        assert len(TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY) > 20

    def test_a_idempotent_policy_present(self):
        assert isinstance(ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY, str)
        assert len(ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY) > 20

    def test_a_detach_policy_present(self):
        assert isinstance(DETACH_CLOSES_SESSION_GRACEFULLY_POLICY, str)
        assert len(DETACH_CLOSES_SESSION_GRACEFULLY_POLICY) > 20

    def test_a_disconnect_policy_present(self):
        assert isinstance(DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY, str)
        assert len(DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY) > 20

    def test_a_disable_policy_present(self):
        assert isinstance(DISABLE_PREVENTS_REATTACH_POLICY, str)
        assert len(DISABLE_PREVENTS_REATTACH_POLICY) > 20

    def test_a_invalidate_policy_present(self):
        assert isinstance(INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY, str)
        assert len(INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY) > 20

    def test_a_reconnect_policy_present(self):
        assert isinstance(RECONNECT_RESTORES_ATTACHED_STATE_POLICY, str)
        assert len(RECONNECT_RESTORES_ATTACHED_STATE_POLICY) > 20

    def test_a_observer_only_policy_present(self):
        assert isinstance(OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY, str)
        assert len(OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY) > 20

    def test_a_aligned_pr7_sentinel_present(self):
        assert isinstance(ATTACHED_RUNTIME_SESSION_ALIGNED_PR7, str)
        assert "PR7" in ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
        assert len(ATTACHED_RUNTIME_SESSION_ALIGNED_PR7) > 20


# ===========================================================================
# B — AttachmentState enum
# ===========================================================================

class TestAttachmentStateEnum:
    def test_b_all_values_present(self):
        values = {s.value for s in AttachmentState}
        assert values == {
            "attached",
            "detaching",
            "detached",
            "disconnected",
            "disabled",
            "invalidated",
        }

    def test_b_from_string_known(self):
        assert AttachmentState.from_string("attached") == AttachmentState.attached
        assert AttachmentState.from_string("detaching") == AttachmentState.detaching
        assert AttachmentState.from_string("detached") == AttachmentState.detached
        assert AttachmentState.from_string("disconnected") == AttachmentState.disconnected
        assert AttachmentState.from_string("disabled") == AttachmentState.disabled
        assert AttachmentState.from_string("invalidated") == AttachmentState.invalidated

    def test_b_from_string_unknown_defaults_attached(self):
        assert AttachmentState.from_string("bogus") == AttachmentState.attached

    def test_b_is_active_attached(self):
        assert AttachmentState.attached.is_active() is True

    def test_b_is_active_detaching(self):
        assert AttachmentState.detaching.is_active() is True

    def test_b_is_active_false_for_terminal_states(self):
        for state in (
            AttachmentState.detached,
            AttachmentState.disconnected,
            AttachmentState.disabled,
            AttachmentState.invalidated,
        ):
            assert state.is_active() is False, f"{state.value} should not be active"

    def test_b_is_terminal_for_terminal_states(self):
        for state in (
            AttachmentState.detached,
            AttachmentState.disconnected,
            AttachmentState.disabled,
            AttachmentState.invalidated,
        ):
            assert state.is_terminal() is True, f"{state.value} should be terminal"

    def test_b_is_terminal_false_for_active_states(self):
        for state in (AttachmentState.attached, AttachmentState.detaching):
            assert state.is_terminal() is False, f"{state.value} should not be terminal"

    def test_b_allows_reconnect_disconnected_only(self):
        assert AttachmentState.disconnected.allows_reconnect() is True
        for state in (
            AttachmentState.attached,
            AttachmentState.detaching,
            AttachmentState.detached,
            AttachmentState.disabled,
            AttachmentState.invalidated,
        ):
            assert state.allows_reconnect() is False


# ===========================================================================
# C — AttachmentLifecycleSignal enum
# ===========================================================================

class TestAttachmentLifecycleSignalEnum:
    def test_c_all_values_present(self):
        values = {s.value for s in AttachmentLifecycleSignal}
        assert values == {
            "attach",
            "detach",
            "disconnect",
            "disable",
            "invalidate",
            "reconnect",
        }

    def test_c_from_string_known(self):
        assert AttachmentLifecycleSignal.from_string("attach") == AttachmentLifecycleSignal.attach
        assert AttachmentLifecycleSignal.from_string("detach") == AttachmentLifecycleSignal.detach
        assert AttachmentLifecycleSignal.from_string("disconnect") == AttachmentLifecycleSignal.disconnect
        assert AttachmentLifecycleSignal.from_string("disable") == AttachmentLifecycleSignal.disable
        assert AttachmentLifecycleSignal.from_string("invalidate") == AttachmentLifecycleSignal.invalidate
        assert AttachmentLifecycleSignal.from_string("reconnect") == AttachmentLifecycleSignal.reconnect

    def test_c_from_string_unknown_defaults_attach(self):
        assert AttachmentLifecycleSignal.from_string("bogus") == AttachmentLifecycleSignal.attach


# ===========================================================================
# D — AttachedRuntimeSessionRecord
# ===========================================================================

class TestAttachedRuntimeSessionRecord:
    def test_d_construction_defaults(self):
        rec = AttachedRuntimeSessionRecord(device_id="dev-1")
        assert rec.device_id == "dev-1"
        assert rec.attachment_state == AttachmentState.attached
        assert rec.source_runtime_posture == "control_only"
        assert rec.coordination_role == ""
        assert rec.capability_tier == "unknown"
        assert rec.android_host_role == ""
        assert rec.last_signal is None
        assert isinstance(rec.session_id, str)
        assert len(rec.session_id) > 0
        assert isinstance(rec.metadata, dict)

    def test_d_construction_explicit_values(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-2",
            attachment_state=AttachmentState.disconnected,
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="FULL_RUNTIME_HOST",
            last_signal=AttachmentLifecycleSignal.disconnect,
            metadata={"foo": "bar"},
        )
        assert rec.attachment_state == AttachmentState.disconnected
        assert rec.source_runtime_posture == "join_runtime"
        assert rec.coordination_role == "joined_runtime_participant"
        assert rec.capability_tier == "full_runtime"
        assert rec.android_host_role == "FULL_RUNTIME_HOST"
        assert rec.last_signal == AttachmentLifecycleSignal.disconnect
        assert rec.metadata == {"foo": "bar"}

    def test_d_to_dict_contains_all_fields(self):
        rec = AttachedRuntimeSessionRecord(device_id="dev-3")
        d = rec.to_dict()
        assert "device_id" in d
        assert "session_id" in d
        assert "attachment_state" in d
        assert "source_runtime_posture" in d
        assert "coordination_role" in d
        assert "capability_tier" in d
        assert "android_host_role" in d
        assert "attached_at" in d
        assert "last_signal_at" in d
        assert "last_signal" in d
        assert "metadata" in d

    def test_d_to_dict_state_as_string(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-4", attachment_state=AttachmentState.detached
        )
        assert rec.to_dict()["attachment_state"] == "detached"

    def test_d_to_dict_last_signal_as_string(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-5", last_signal=AttachmentLifecycleSignal.reconnect
        )
        assert rec.to_dict()["last_signal"] == "reconnect"

    def test_d_to_dict_last_signal_none(self):
        rec = AttachedRuntimeSessionRecord(device_id="dev-6")
        assert rec.to_dict()["last_signal"] is None

    def test_d_to_json_valid(self):
        rec = AttachedRuntimeSessionRecord(device_id="dev-7")
        data = json.loads(rec.to_json())
        assert data["device_id"] == "dev-7"

    def test_d_from_dict_round_trip(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-8",
            attachment_state=AttachmentState.disconnected,
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="FULL_RUNTIME_HOST",
            last_signal=AttachmentLifecycleSignal.disconnect,
            metadata={"key": "val"},
        )
        restored = AttachedRuntimeSessionRecord.from_dict(rec.to_dict())
        assert restored.device_id == rec.device_id
        assert restored.attachment_state == rec.attachment_state
        assert restored.source_runtime_posture == rec.source_runtime_posture
        assert restored.coordination_role == rec.coordination_role
        assert restored.capability_tier == rec.capability_tier
        assert restored.android_host_role == rec.android_host_role
        assert restored.last_signal == rec.last_signal
        assert restored.metadata == rec.metadata

    def test_d_from_dict_missing_fields_defaults(self):
        rec = AttachedRuntimeSessionRecord.from_dict({"device_id": "dev-9"})
        assert rec.device_id == "dev-9"
        assert rec.attachment_state == AttachmentState.attached
        assert rec.source_runtime_posture == "control_only"

    def test_d_from_dict_no_last_signal(self):
        rec = AttachedRuntimeSessionRecord.from_dict(
            {"device_id": "dev-10", "last_signal": None}
        )
        assert rec.last_signal is None


# ===========================================================================
# E — AttachedRuntimeSessionSnapshot
# ===========================================================================

class TestAttachedRuntimeSessionSnapshot:
    def test_e_construction_defaults(self):
        snap = AttachedRuntimeSessionSnapshot()
        assert snap.records == []
        assert snap.active_count == 0
        assert snap.total_count == 0
        assert isinstance(snap.snapshot_id, str)
        assert snap.authority == ATTACHED_RUNTIME_SESSION_AUTHORITY
        assert snap.alignment_sentinel == ATTACHED_RUNTIME_SESSION_ALIGNED_PR7

    def test_e_to_dict_contains_all_fields(self):
        snap = AttachedRuntimeSessionSnapshot(
            records=[{"device_id": "dev-1"}],
            active_count=1,
            total_count=1,
        )
        d = snap.to_dict()
        assert d["active_count"] == 1
        assert d["total_count"] == 1
        assert d["records"] == [{"device_id": "dev-1"}]
        assert "snapshot_id" in d
        assert "snapshot_at" in d
        assert "authority" in d
        assert "alignment_sentinel" in d

    def test_e_to_json_valid(self):
        snap = AttachedRuntimeSessionSnapshot()
        data = json.loads(snap.to_json())
        assert "snapshot_id" in data


# ===========================================================================
# F — State-machine: attach signal
# ===========================================================================

class TestStateMachineAttach:
    def test_f_attach_from_new_yields_attached(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rec = rt.attach(dev)
        assert rec.attachment_state == AttachmentState.attached

    def test_f_attach_from_detached_yields_attached(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        rec = rt.attach(dev)
        assert rec.attachment_state == AttachmentState.attached

    def test_f_attach_from_disconnected_yields_attached(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        rec = rt.attach(dev)
        assert rec.attachment_state == AttachmentState.attached


# ===========================================================================
# G — State-machine: detach signal
# ===========================================================================

class TestStateMachineDetach:
    def test_g_detach_from_attached_yields_detached(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        assert rec.attachment_state == AttachmentState.detached

    def test_g_detach_marks_last_signal(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        assert rec.last_signal == AttachmentLifecycleSignal.detach

    def test_g_detach_from_invalidated_has_no_effect(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        # detach from invalidated should keep invalidated
        assert rec.attachment_state == AttachmentState.invalidated


# ===========================================================================
# H — State-machine: disconnect signal
# ===========================================================================

class TestStateMachineDisconnect:
    def test_h_disconnect_from_attached_yields_disconnected(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        assert rec.attachment_state == AttachmentState.disconnected

    def test_h_disconnect_marks_last_signal(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        assert rec.last_signal == AttachmentLifecycleSignal.disconnect

    def test_h_disconnect_from_invalidated_has_no_effect(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        assert rec.attachment_state == AttachmentState.invalidated


# ===========================================================================
# I — State-machine: disable signal
# ===========================================================================

class TestStateMachineDisable:
    def test_i_disable_from_attached_yields_disabled(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disable)
        assert rec.attachment_state == AttachmentState.disabled

    def test_i_disable_from_disconnected_yields_disabled(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disable)
        assert rec.attachment_state == AttachmentState.disabled

    def test_i_disable_from_invalidated_has_no_effect(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.disable)
        assert rec.attachment_state == AttachmentState.invalidated


# ===========================================================================
# J — State-machine: invalidate signal
# ===========================================================================

class TestStateMachineInvalidate:
    def test_j_invalidate_from_attached_yields_invalidated(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        assert rec.attachment_state == AttachmentState.invalidated

    def test_j_invalidate_from_disconnected_yields_invalidated(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        assert rec.attachment_state == AttachmentState.invalidated

    def test_j_invalidate_from_disabled_yields_invalidated(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disable)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        assert rec.attachment_state == AttachmentState.invalidated

    def test_j_invalidated_is_terminal(self):
        assert AttachmentState.invalidated.is_terminal() is True


# ===========================================================================
# K — State-machine: reconnect from disconnected
# ===========================================================================

class TestStateMachineReconnect:
    def test_k_reconnect_from_disconnected_yields_attached(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.reconnect)
        assert rec.attachment_state == AttachmentState.attached

    def test_k_reconnect_marks_last_signal(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.disconnect)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.reconnect)
        assert rec.last_signal == AttachmentLifecycleSignal.reconnect


# ===========================================================================
# L — State-machine: reconnect has no effect from non-disconnected terminals
# ===========================================================================

class TestStateMachineReconnectNoEffect:
    @pytest.mark.parametrize("terminal_signal, expected_state", [
        (AttachmentLifecycleSignal.detach, AttachmentState.detached),
        (AttachmentLifecycleSignal.disable, AttachmentState.disabled),
        (AttachmentLifecycleSignal.invalidate, AttachmentState.invalidated),
    ])
    def test_l_reconnect_no_effect_from_terminal(self, terminal_signal, expected_state):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, terminal_signal)
        rec = rt.apply_signal(dev, AttachmentLifecycleSignal.reconnect)
        assert rec.attachment_state == expected_state


# ===========================================================================
# M — Runtime: attach creates record
# ===========================================================================

class TestRuntimeAttach:
    def test_m_attach_creates_record(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rec = rt.attach(dev, source_runtime_posture="join_runtime")
        assert rec.device_id == dev
        assert rec.source_runtime_posture == "join_runtime"
        assert rec.attachment_state == AttachmentState.attached

    def test_m_attach_persists_in_index(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        assert rt.get(dev) is not None


# ===========================================================================
# N — Runtime: idempotent attach
# ===========================================================================

class TestRuntimeIdempotentAttach:
    def test_n_idempotent_returns_same_session_id(self):
        rt = _fresh_runtime()
        dev = _device_id()
        r1 = rt.attach(dev, source_runtime_posture="join_runtime")
        r2 = rt.attach(dev, source_runtime_posture="join_runtime")
        assert r1.session_id == r2.session_id

    def test_n_idempotent_refreshes_metadata(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev, metadata={"k": "v1"})
        rt.attach(dev, metadata={"k": "v2", "extra": 1})
        rec = rt.get(dev)
        assert rec.metadata.get("k") == "v2"
        assert rec.metadata.get("extra") == 1

    def test_n_idempotent_refreshes_posture(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev, source_runtime_posture="control_only")
        rt.attach(dev, source_runtime_posture="join_runtime")
        rec = rt.get(dev)
        assert rec.source_runtime_posture == "join_runtime"


# ===========================================================================
# O — Runtime: re-attach after detached creates new session
# ===========================================================================

class TestRuntimeReattachAfterDetach:
    def test_o_reattach_after_detach_gets_new_session_id(self):
        rt = _fresh_runtime()
        dev = _device_id()
        r1 = rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        r2 = rt.attach(dev)
        assert r2.session_id != r1.session_id

    def test_o_reattach_after_detach_is_active(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.detach)
        rec = rt.attach(dev)
        assert rec.attachment_state == AttachmentState.attached


# ===========================================================================
# P — Runtime: invalidated session blocks re-attach
# ===========================================================================

class TestRuntimeInvalidatedBlocksReattach:
    def test_p_invalidated_blocks_reattach(self):
        rt = _fresh_runtime()
        dev = _device_id()
        r1 = rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        r2 = rt.attach(dev)
        # Returns the existing invalidated record unchanged
        assert r2.attachment_state == AttachmentState.invalidated
        assert r2.session_id == r1.session_id


# ===========================================================================
# Q — Runtime: apply_signal returns None for unknown device
# ===========================================================================

class TestRuntimeApplySignalUnknown:
    def test_q_apply_signal_none_for_unknown(self):
        rt = _fresh_runtime()
        result = rt.apply_signal("nonexistent-device", AttachmentLifecycleSignal.detach)
        assert result is None


# ===========================================================================
# R — Runtime: get() returns None for unknown device
# ===========================================================================

class TestRuntimeGetUnknown:
    def test_r_get_none_for_unknown(self):
        rt = _fresh_runtime()
        assert rt.get("nonexistent") is None


# ===========================================================================
# S — Runtime: list_active() excludes terminal records
# ===========================================================================

class TestRuntimeListActive:
    def test_s_list_active_excludes_detached(self):
        rt = _fresh_runtime()
        dev1 = _device_id()
        dev2 = _device_id()
        rt.attach(dev1)
        rt.attach(dev2)
        rt.apply_signal(dev1, AttachmentLifecycleSignal.detach)
        active = rt.list_active()
        device_ids = {r.device_id for r in active}
        assert dev2 in device_ids
        assert dev1 not in device_ids

    def test_s_list_active_excludes_invalidated(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rt.attach(dev)
        rt.apply_signal(dev, AttachmentLifecycleSignal.invalidate)
        assert rt.list_active() == []


# ===========================================================================
# T — Runtime: list_all() includes all records
# ===========================================================================

class TestRuntimeListAll:
    def test_t_list_all_includes_terminal(self):
        rt = _fresh_runtime()
        dev1 = _device_id()
        dev2 = _device_id()
        rt.attach(dev1)
        rt.attach(dev2)
        rt.apply_signal(dev1, AttachmentLifecycleSignal.detach)
        all_recs = rt.list_all()
        assert len(all_recs) == 2


# ===========================================================================
# U — Runtime: ring-buffer eviction at capacity
# ===========================================================================

class TestRuntimeRingBufferEviction:
    def test_u_evicts_oldest_at_capacity(self):
        cap = 4
        rt = _fresh_runtime(capacity=cap)
        devices = [_device_id() for _ in range(cap + 1)]
        for dev in devices:
            rt.attach(dev)
        # The total stored count should not exceed capacity
        assert len(rt.list_all()) <= cap

    def test_u_newest_records_survive_eviction(self):
        cap = 3
        rt = _fresh_runtime(capacity=cap)
        devices = [_device_id() for _ in range(cap + 2)]
        for dev in devices:
            rt.attach(dev)
        surviving_ids = {r.device_id for r in rt.list_all()}
        # The last 'cap' devices should be present
        for dev in devices[-cap:]:
            assert dev in surviving_ids


# ===========================================================================
# V — Runtime: reset()
# ===========================================================================

class TestRuntimeReset:
    def test_v_reset_clears_all(self):
        rt = _fresh_runtime()
        for _ in range(5):
            rt.attach(_device_id())
        rt.reset()
        assert rt.list_all() == []
        assert rt.list_active() == []


# ===========================================================================
# W — attach_runtime_session() module-level function
# ===========================================================================

class TestModuleLevelAttach:
    def test_w_attach_runtime_session_with_custom_runtime(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rec = attach_runtime_session(
            dev,
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            runtime=rt,
        )
        assert rec.device_id == dev
        assert rec.source_runtime_posture == "join_runtime"
        assert rec.coordination_role == "joined_runtime_participant"
        assert rec.capability_tier == "full_runtime"


# ===========================================================================
# X — apply_lifecycle_signal() module-level function
# ===========================================================================

class TestModuleLevelApplySignal:
    def test_x_apply_lifecycle_signal_with_custom_runtime(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.detach, runtime=rt)
        assert rec.attachment_state == AttachmentState.detached

    def test_x_apply_lifecycle_signal_none_for_unknown(self):
        rt = _fresh_runtime()
        result = apply_lifecycle_signal(
            "unknown-dev", AttachmentLifecycleSignal.detach, runtime=rt
        )
        assert result is None


# ===========================================================================
# Y — get_attached_runtime_session() module-level function
# ===========================================================================

class TestModuleLevelGet:
    def test_y_get_returns_record(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        rec = get_attached_runtime_session(dev, runtime=rt)
        assert rec is not None
        assert rec.device_id == dev

    def test_y_get_returns_none_for_unknown(self):
        rt = _fresh_runtime()
        assert get_attached_runtime_session("unknown", runtime=rt) is None


# ===========================================================================
# Z — list_active_attached_sessions() module-level function
# ===========================================================================

class TestModuleLevelListActive:
    def test_z_list_active_returns_non_terminal(self):
        rt = _fresh_runtime()
        dev1 = _device_id()
        dev2 = _device_id()
        attach_runtime_session(dev1, runtime=rt)
        attach_runtime_session(dev2, runtime=rt)
        apply_lifecycle_signal(dev1, AttachmentLifecycleSignal.detach, runtime=rt)
        active = list_active_attached_sessions(runtime=rt)
        ids = {r.device_id for r in active}
        assert dev2 in ids
        assert dev1 not in ids


# ===========================================================================
# AA — build_attached_runtime_session_snapshot(): correct counts
# ===========================================================================

class TestSnapshotCounts:
    def test_aa_snapshot_active_count(self):
        rt = _fresh_runtime()
        dev1 = _device_id()
        dev2 = _device_id()
        dev3 = _device_id()
        attach_runtime_session(dev1, runtime=rt)
        attach_runtime_session(dev2, runtime=rt)
        attach_runtime_session(dev3, runtime=rt)
        apply_lifecycle_signal(dev3, AttachmentLifecycleSignal.disconnect, runtime=rt)
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.total_count == 3
        assert snap.active_count == 2

    def test_aa_snapshot_empty_runtime(self):
        rt = _fresh_runtime()
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.total_count == 0
        assert snap.active_count == 0


# ===========================================================================
# AB — build_attached_runtime_session_snapshot(): serialises records
# ===========================================================================

class TestSnapshotSerialisation:
    def test_ab_snapshot_records_are_dicts(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert isinstance(snap.records, list)
        assert len(snap.records) == 1
        assert isinstance(snap.records[0], dict)
        assert snap.records[0]["device_id"] == dev


# ===========================================================================
# AC — core.runtime re-exports
# ===========================================================================

class TestRuntimeReexports:
    def test_ac_sentinels_accessible_from_core_runtime(self):
        try:
            from core.runtime import (
                ATTACHED_RUNTIME_SESSION_AUTHORITY,
                ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY,
                TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY,
                ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY,
                DETACH_CLOSES_SESSION_GRACEFULLY_POLICY,
                DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY,
                DISABLE_PREVENTS_REATTACH_POLICY,
                INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY,
                RECONNECT_RESTORES_ATTACHED_STATE_POLICY,
                OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY,
                ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 as _pr7_sentinel,
            )
            assert ATTACHED_RUNTIME_SESSION_AUTHORITY
            assert _pr7_sentinel
            assert "PR7" in _pr7_sentinel
        except ImportError:
            pytest.skip("core.runtime requires additional dependencies not available in this environment")

    def test_ac_types_accessible_from_core_runtime(self):
        try:
            from core.runtime import (
                AttachmentState,
                AttachmentLifecycleSignal,
                AttachedRuntimeSessionRecord,
                AttachedRuntimeSessionSnapshot,
                AttachedRuntimeSessionRuntime,
            )
            assert AttachmentState.attached
            assert AttachmentLifecycleSignal.attach
        except ImportError:
            pytest.skip("core.runtime requires additional dependencies not available in this environment")

    def test_ac_functions_accessible_from_core_runtime(self):
        try:
            from core.runtime import (
                attach_runtime_session,
                apply_lifecycle_signal,
                get_attached_runtime_session,
                list_active_attached_sessions,
                build_attached_runtime_session_snapshot,
                AttachedRuntimeSessionRuntime,
            )
            rt = AttachedRuntimeSessionRuntime()
            dev = _device_id()
            rec = attach_runtime_session(dev, runtime=rt)
            assert rec.attachment_state == AttachmentState.attached
        except ImportError:
            pytest.skip("core.runtime requires additional dependencies not available in this environment")


# ===========================================================================
# AD — projection.py sentinel
# ===========================================================================

class TestProjectionSentinel:
    def test_ad_projection_sentinel_present_and_not_unavailable(self):
        try:
            from core.routes.projection import ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 as proj_sentinel

            assert isinstance(proj_sentinel, str)
            assert len(proj_sentinel) > 20
            assert "UNAVAILABLE" not in proj_sentinel
        except ImportError:
            pytest.skip("core.routes.projection requires fastapi")

    def test_ad_projection_sentinel_contains_pr7_marker(self):
        try:
            from core.routes.projection import ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 as proj_sentinel

            assert "PR7" in proj_sentinel
        except ImportError:
            pytest.skip("core.routes.projection requires fastapi")


# ===========================================================================
# AE — End-to-end: Android join_runtime attach → disconnect → reconnect
# ===========================================================================

class TestEndToEndAndroidReconnect:
    def test_ae_android_attach_disconnect_reconnect(self):
        rt = _fresh_runtime()
        dev = _device_id()

        # Attach
        rec = attach_runtime_session(
            dev,
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="FULL_RUNTIME_HOST",
            runtime=rt,
        )
        assert rec.attachment_state == AttachmentState.attached

        # Disconnect (transport loss)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.disconnect, runtime=rt)
        assert rec.attachment_state == AttachmentState.disconnected

        # Reconnect
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.reconnect, runtime=rt)
        assert rec.attachment_state == AttachmentState.attached
        # Metadata preserved across lifecycle
        assert rec.source_runtime_posture == "join_runtime"
        assert rec.capability_tier == "full_runtime"


# ===========================================================================
# AF — End-to-end: control_only device attaches, detaches, re-attaches
# ===========================================================================

class TestEndToEndControlOnlyReattach:
    def test_af_control_only_attach_detach_reattach(self):
        rt = _fresh_runtime()
        dev = _device_id()

        r1 = attach_runtime_session(
            dev, source_runtime_posture="control_only", runtime=rt
        )
        assert r1.attachment_state == AttachmentState.attached

        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.detach, runtime=rt)
        assert get_attached_runtime_session(dev, runtime=rt).attachment_state == AttachmentState.detached

        r2 = attach_runtime_session(
            dev, source_runtime_posture="control_only", runtime=rt
        )
        assert r2.attachment_state == AttachmentState.attached
        # New session after detach
        assert r2.session_id != r1.session_id


# ===========================================================================
# AG — End-to-end: observer_only policy sentinel
# ===========================================================================

class TestEndToEndObserverOnly:
    def test_ag_observer_only_sentinel_describes_non_promotability(self):
        """The observer_only policy sentinel asserts that role changes require
        a new attach() call, not lifecycle signals."""
        assert "lifecycle" in OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY.lower()

    def test_ag_observer_only_session_can_be_created(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rec = attach_runtime_session(
            dev,
            source_runtime_posture="control_only",
            coordination_role="observer_only",
            runtime=rt,
        )
        assert rec.coordination_role == "observer_only"
        assert rec.attachment_state == AttachmentState.attached


# ===========================================================================
# AH — End-to-end: disabled device; reconnect has no effect
# ===========================================================================

class TestEndToEndDisabledNoReconnect:
    def test_ah_disabled_reconnect_no_effect(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.disable, runtime=rt)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.reconnect, runtime=rt)
        assert rec.attachment_state == AttachmentState.disabled


# ===========================================================================
# AI — End-to-end: invalidated device; subsequent signals are no-ops
# ===========================================================================

class TestEndToEndInvalidatedNoOp:
    def test_ai_invalidated_detach_no_op(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.invalidate, runtime=rt)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.detach, runtime=rt)
        assert rec.attachment_state == AttachmentState.invalidated

    def test_ai_invalidated_reconnect_no_op(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.invalidate, runtime=rt)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.reconnect, runtime=rt)
        assert rec.attachment_state == AttachmentState.invalidated

    def test_ai_invalidated_disable_no_op(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.invalidate, runtime=rt)
        rec = apply_lifecycle_signal(dev, AttachmentLifecycleSignal.disable, runtime=rt)
        assert rec.attachment_state == AttachmentState.invalidated


# ===========================================================================
# AJ — Metadata merge on idempotent re-attach
# ===========================================================================

class TestMetadataMergeReattach:
    def test_aj_metadata_merged_on_idempotent_reattach(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, metadata={"a": 1}, runtime=rt)
        attach_runtime_session(dev, metadata={"b": 2}, runtime=rt)
        rec = get_attached_runtime_session(dev, runtime=rt)
        assert rec.metadata.get("a") == 1
        assert rec.metadata.get("b") == 2


# ===========================================================================
# AK — Metadata merge on apply_signal
# ===========================================================================

class TestMetadataMergeSignal:
    def test_ak_metadata_merged_on_signal(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, metadata={"orig": True}, runtime=rt)
        apply_lifecycle_signal(
            dev,
            AttachmentLifecycleSignal.disconnect,
            metadata={"disconnect_reason": "timeout"},
            runtime=rt,
        )
        rec = get_attached_runtime_session(dev, runtime=rt)
        assert rec.metadata.get("orig") is True
        assert rec.metadata.get("disconnect_reason") == "timeout"


# ===========================================================================
# AL — Thread safety: concurrent attaches for distinct devices
# ===========================================================================

class TestThreadSafety:
    def test_al_concurrent_attaches(self):
        rt = _fresh_runtime(capacity=128)
        devices = [_device_id() for _ in range(50)]

        def do_attach(dev: str) -> None:
            attach_runtime_session(dev, runtime=rt)
            apply_lifecycle_signal(dev, AttachmentLifecycleSignal.disconnect, runtime=rt)
            apply_lifecycle_signal(dev, AttachmentLifecycleSignal.reconnect, runtime=rt)

        with ThreadPoolExecutor(max_workers=10) as exc:
            list(exc.map(do_attach, devices))

        active = list_active_attached_sessions(runtime=rt)
        assert len(active) == 50


# ===========================================================================
# AM — Serialisation round-trip: to_dict → from_dict
# ===========================================================================

class TestSerialisationRoundTrip:
    def test_am_record_dict_round_trip(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-rt",
            attachment_state=AttachmentState.disconnected,
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="FULL_RUNTIME_HOST",
            last_signal=AttachmentLifecycleSignal.disconnect,
            metadata={"x": 42},
        )
        restored = AttachedRuntimeSessionRecord.from_dict(rec.to_dict())
        assert restored.device_id == rec.device_id
        assert restored.attachment_state == rec.attachment_state
        assert restored.source_runtime_posture == rec.source_runtime_posture
        assert restored.coordination_role == rec.coordination_role
        assert restored.capability_tier == rec.capability_tier
        assert restored.android_host_role == rec.android_host_role
        assert restored.last_signal == rec.last_signal
        assert restored.metadata == rec.metadata


# ===========================================================================
# AN — Serialisation round-trip: to_json produces valid JSON
# ===========================================================================

class TestSerialisationJson:
    def test_an_record_json_valid(self):
        rec = AttachedRuntimeSessionRecord(
            device_id="dev-json",
            last_signal=AttachmentLifecycleSignal.detach,
        )
        data = json.loads(rec.to_json())
        assert data["device_id"] == "dev-json"
        assert data["last_signal"] == "detach"

    def test_an_record_json_all_fields_serialisable(self):
        rec = AttachedRuntimeSessionRecord(device_id="dev-full")
        # Should not raise
        json.loads(rec.to_json())


# ===========================================================================
# AO — Serialisation round-trip: snapshot to_json produces valid JSON
# ===========================================================================

class TestSnapshotJson:
    def test_ao_snapshot_json_valid(self):
        rt = _fresh_runtime()
        dev = _device_id()
        attach_runtime_session(dev, runtime=rt)
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        data = json.loads(snap.to_json())
        assert data["total_count"] == 1
        assert data["active_count"] == 1
        assert isinstance(data["records"], list)


# ===========================================================================
# AP — Policy sentinels are non-empty strings
# ===========================================================================

class TestPolicySentinelStrings:
    @pytest.mark.parametrize("sentinel", [
        ATTACHED_RUNTIME_SESSION_AUTHORITY,
        ATTACHED_RUNTIME_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY,
        TRANSIENT_PRESENCE_IS_NOT_ATTACHED_SESSION_POLICY,
        ATTACH_SIGNAL_IS_IDEMPOTENT_POLICY,
        DETACH_CLOSES_SESSION_GRACEFULLY_POLICY,
        DISCONNECT_MARKS_SESSION_DISCONNECTED_POLICY,
        DISABLE_PREVENTS_REATTACH_POLICY,
        INVALIDATE_TERMINATES_SESSION_PERMANENTLY_POLICY,
        RECONNECT_RESTORES_ATTACHED_STATE_POLICY,
        OBSERVER_ONLY_SESSION_CANNOT_BE_PROMOTED_POLICY,
        ATTACHED_RUNTIME_SESSION_ALIGNED_PR7,
    ])
    def test_ap_sentinel_is_non_empty_string(self, sentinel):
        assert isinstance(sentinel, str)
        assert len(sentinel) > 10


# ===========================================================================
# AQ — AttachmentState covers full lifecycle vocabulary
# ===========================================================================

class TestAttachmentStateVocabulary:
    def test_aq_all_lifecycle_vocab_present(self):
        vocab = {"attached", "detaching", "detached", "disconnected", "disabled", "invalidated"}
        present = {s.value for s in AttachmentState}
        assert vocab == present


# ===========================================================================
# AR — Multiple devices get independent session records
# ===========================================================================

class TestMultipleDevices:
    def test_ar_multiple_devices_independent(self):
        rt = _fresh_runtime()
        devs = [_device_id() for _ in range(5)]
        for dev in devs:
            attach_runtime_session(dev, source_runtime_posture="join_runtime", runtime=rt)
        # Disconnect one
        apply_lifecycle_signal(devs[0], AttachmentLifecycleSignal.disconnect, runtime=rt)
        for dev in devs[1:]:
            rec = get_attached_runtime_session(dev, runtime=rt)
            assert rec.attachment_state == AttachmentState.attached


# ===========================================================================
# AS — Session IDs are unique across records
# ===========================================================================

class TestSessionIdUniqueness:
    def test_as_session_ids_are_unique(self):
        rt = _fresh_runtime()
        session_ids = set()
        for _ in range(20):
            dev = _device_id()
            rec = attach_runtime_session(dev, runtime=rt)
            assert rec.session_id not in session_ids
            session_ids.add(rec.session_id)


# ===========================================================================
# AT — attached_at and last_signal_at timing
# ===========================================================================

class TestTimestamps:
    def test_at_attached_at_set_on_creation(self):
        rt = _fresh_runtime()
        before = time.time()
        dev = _device_id()
        rec = attach_runtime_session(dev, runtime=rt)
        after = time.time()
        assert before <= rec.attached_at <= after

    def test_at_last_signal_at_updates_on_signal(self):
        rt = _fresh_runtime()
        dev = _device_id()
        rec = attach_runtime_session(dev, runtime=rt)
        t0 = rec.attached_at
        # Apply a signal and verify last_signal_at is >= attached_at
        apply_lifecycle_signal(dev, AttachmentLifecycleSignal.disconnect, runtime=rt)
        rec2 = get_attached_runtime_session(dev, runtime=rt)
        assert rec2.last_signal_at >= t0
        assert rec2.last_signal == AttachmentLifecycleSignal.disconnect


# ===========================================================================
# AU — Snapshot authority and alignment_sentinel
# ===========================================================================

class TestSnapshotSentinels:
    def test_au_snapshot_authority_matches_module_constant(self):
        rt = _fresh_runtime()
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.authority == ATTACHED_RUNTIME_SESSION_AUTHORITY

    def test_au_snapshot_alignment_sentinel_matches_module_constant(self):
        rt = _fresh_runtime()
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.alignment_sentinel == ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
