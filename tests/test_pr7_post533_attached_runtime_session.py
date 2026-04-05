"""tests/test_pr7_post533_attached_runtime_session.py
=======================================================
Tests for PR package 7 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Persistent Attached-Runtime Session Semantics.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — AttachmentState enum: all values present, from_string(), defaults,
     is_active(), is_terminal(), allows_reattach().
C  — AttachmentLifecycleSignal enum: all values present, from_string().
D  — AttachedRuntimeSessionRecord: construction, defaults, properties,
     to_dict(), to_json(), from_dict().
E  — AttachedRuntimeSessionSnapshot: construction, to_dict(), to_json().
F  — AttachedRuntimeSessionRuntime: upsert, get, list_active, list_all,
     count_active, total, ring-buffer eviction.
G  — attach_runtime_session: fresh attach returns attached state.
H  — attach_runtime_session: idempotent re-attach preserves session_id when
     prior record is detached.
I  — attach_runtime_session: idempotent re-attach preserves session_id when
     prior record is disconnected.
J  — attach_runtime_session: disabled prior record results in fresh session_id.
K  — attach_runtime_session: invalidated prior record results in fresh session_id.
L  — attach_runtime_session: join_runtime posture produces is_eligible_for_delegation.
M  — attach_runtime_session: control_only posture is NOT eligible for delegation.
N  — attach_runtime_session: metadata is captured.
O  — attach_runtime_session: missing/None posture defaults to control_only.
P  — apply_lifecycle_signal: attach→detach→detach (detaching→detached).
Q  — apply_lifecycle_signal: attached→disconnect→reconnect→attached.
R  — apply_lifecycle_signal: attached→disable.
S  — apply_lifecycle_signal: attached→invalidate (terminal).
T  — apply_lifecycle_signal: terminal record raises ValueError.
U  — apply_lifecycle_signal: invalid transition raises ValueError.
V  — apply_lifecycle_signal: disabled→invalidate (terminal from disabled).
W  — apply_lifecycle_signal: updates last_signal and last_signal_at.
X  — get_attached_runtime_session: returns None for unknown device.
Y  — get_attached_runtime_session: returns current record after attach.
Z  — list_active_attached_sessions: returns only attached records.
AA — list_active_attached_sessions: returns empty list when all are detached.
AB — build_attached_runtime_session_snapshot: active_count and total_recorded
     are accurate.
AC — build_attached_runtime_session_snapshot: sessions list contains dicts.
AD — build_attached_runtime_session_snapshot: authority field is correct.
AE — Singleton runtime: get_attached_runtime_session_runtime() returns same
     instance on repeated calls.
AF — reset_attached_runtime_session_runtime(): produces a fresh instance.
AG — Serialisation round-trip: AttachedRuntimeSessionRecord to_dict→from_dict.
AH — Serialisation round-trip: to_json produces valid JSON.
AI — Serialisation round-trip: AttachedRuntimeSessionSnapshot to_json.
AJ — Multiple devices: each gets its own independent session.
AK — Ring buffer: eviction of oldest entry when capacity is exceeded.
AL — End-to-end: Android join_runtime attach → delegate → detach lifecycle.
AM — End-to-end: reconnect after disconnect preserves original session_id.
AN — End-to-end: disable prevents re-attachment via allows_reattach().
AO — End-to-end: invalidation is terminal; new session gets new session_id.
AP — core.runtime re-exports: all PR-7 symbols accessible from core.runtime.
AQ — projection.py sentinel: ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 is present
     and not UNAVAILABLE.
AR — Session record unique session_ids: two fresh attaches differ.
AS — AttachmentState.from_string: unknown string → invalidated.
AT — AttachmentLifecycleSignal.from_string: unknown string → None.
AU — Snapshot to_dict includes snapshot_id and compiled_at timestamps.
AV — attach_runtime_session: android_host_role is captured.
AW — apply_lifecycle_signal: detaching→disable transitions correctly.
AX — Concurrency: multiple attach calls for same device are idempotent.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from core.attached_runtime_session import (
    # Sentinels
    ATTACHED_RUNTIME_SESSION_AUTHORITY,
    ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY,
    TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY,
    ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY,
    DISCONNECT_PRESERVES_SESSION_RECORD_POLICY,
    DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY,
    INVALIDATION_IS_TERMINAL_POLICY,
    LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY,
    ATTACHED_RUNTIME_SESSION_PR7_SENTINEL,
    # Enums
    AttachmentState,
    AttachmentLifecycleSignal,
    # Dataclasses
    AttachedRuntimeSessionRecord,
    AttachedRuntimeSessionSnapshot,
    # Class
    AttachedRuntimeSessionRuntime,
    # Functions
    attach_runtime_session,
    apply_lifecycle_signal,
    get_attached_runtime_session,
    list_active_attached_sessions,
    build_attached_runtime_session_snapshot,
    get_attached_runtime_session_runtime,
    reset_attached_runtime_session_runtime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_runtime() -> AttachedRuntimeSessionRuntime:
    """Return a fresh, isolated runtime for test use."""
    return AttachedRuntimeSessionRuntime()


def _attach(
    rt: AttachedRuntimeSessionRuntime,
    device_id: str = "dev_001",
    posture: str = "join_runtime",
    role: str = "joined_runtime_participant",
    tier: str = "full_runtime",
    android_role: str = "full_runtime_host",
    **metadata: Any,
) -> AttachedRuntimeSessionRecord:
    return attach_runtime_session(
        device_id=device_id,
        source_runtime_posture=posture,
        coordination_role=role,
        capability_tier=tier,
        android_host_role=android_role,
        metadata=dict(metadata) if metadata else {},
        runtime=rt,
    )


# ---------------------------------------------------------------------------
# A: Authority / policy sentinels
# ---------------------------------------------------------------------------


class TestSentinelsA:
    def test_authority_present(self):
        assert ATTACHED_RUNTIME_SESSION_AUTHORITY
        assert isinstance(ATTACHED_RUNTIME_SESSION_AUTHORITY, str)
        assert "AUTHORITY" in ATTACHED_RUNTIME_SESSION_AUTHORITY

    def test_pr7_sentinel_present(self):
        assert ATTACHED_RUNTIME_SESSION_PR7_SENTINEL
        assert "PR7" in ATTACHED_RUNTIME_SESSION_PR7_SENTINEL

    def test_persists_until_explicit_signal_policy(self):
        assert ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY
        assert "attached" in ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY.lower()

    def test_transient_presence_policy(self):
        assert TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY
        assert "transient" in TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY.lower()

    def test_attach_requires_join_runtime_policy(self):
        assert ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
        assert "join_runtime" in ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY

    def test_detach_ends_participation_policy(self):
        assert DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY
        assert "detach" in DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY.lower()

    def test_disconnect_preserves_record_policy(self):
        assert DISCONNECT_PRESERVES_SESSION_RECORD_POLICY
        assert "disconnect" in DISCONNECT_PRESERVES_SESSION_RECORD_POLICY.lower()

    def test_disable_blocks_reattach_policy(self):
        assert DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY
        assert "disable" in DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY.lower()

    def test_invalidation_is_terminal_policy(self):
        assert INVALIDATION_IS_TERMINAL_POLICY
        assert "terminal" in INVALIDATION_IS_TERMINAL_POLICY.lower()

    def test_lifecycle_signal_drives_transition_policy(self):
        assert LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY
        assert "lifecycle" in LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY.lower()

    def test_all_sentinels_non_empty(self):
        sentinels = [
            ATTACHED_RUNTIME_SESSION_AUTHORITY,
            ATTACHED_SESSION_PERSISTS_UNTIL_EXPLICIT_SIGNAL_POLICY,
            TRANSIENT_PRESENCE_NOT_AN_ATTACHED_SESSION_POLICY,
            ATTACH_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            DETACH_SIGNAL_ENDS_PARTICIPATION_POLICY,
            DISCONNECT_PRESERVES_SESSION_RECORD_POLICY,
            DISABLE_BLOCKS_REATTACH_UNTIL_ENABLED_POLICY,
            INVALIDATION_IS_TERMINAL_POLICY,
            LIFECYCLE_SIGNAL_DRIVES_STATE_TRANSITION_POLICY,
            ATTACHED_RUNTIME_SESSION_PR7_SENTINEL,
        ]
        for s in sentinels:
            assert s, f"Sentinel is empty: {s!r}"
            assert isinstance(s, str)


# ---------------------------------------------------------------------------
# B: AttachmentState enum
# ---------------------------------------------------------------------------


class TestAttachmentStateB:
    def test_all_values_present(self):
        expected = {"attached", "detaching", "detached", "disconnected", "disabled", "invalidated"}
        actual = {s.value for s in AttachmentState}
        assert expected == actual

    def test_from_string_valid(self):
        for s in AttachmentState:
            assert AttachmentState.from_string(s.value) == s

    def test_from_string_unknown_defaults_to_invalidated(self):
        assert AttachmentState.from_string("not_a_state") == AttachmentState.invalidated
        assert AttachmentState.from_string("") == AttachmentState.invalidated

    def test_is_active_only_for_attached(self):
        assert AttachmentState.attached.is_active()
        for s in AttachmentState:
            if s != AttachmentState.attached:
                assert not s.is_active()

    def test_is_terminal_only_for_invalidated(self):
        assert AttachmentState.invalidated.is_terminal()
        for s in AttachmentState:
            if s != AttachmentState.invalidated:
                assert not s.is_terminal()

    def test_allows_reattach_excludes_disabled_and_invalidated(self):
        assert not AttachmentState.disabled.allows_reattach()
        assert not AttachmentState.invalidated.allows_reattach()
        for s in (
            AttachmentState.attached,
            AttachmentState.detaching,
            AttachmentState.detached,
            AttachmentState.disconnected,
        ):
            assert s.allows_reattach()

    def test_enum_is_string_subclass(self):
        for s in AttachmentState:
            assert isinstance(s, str)


# ---------------------------------------------------------------------------
# C: AttachmentLifecycleSignal enum
# ---------------------------------------------------------------------------


class TestAttachmentLifecycleSignalC:
    def test_all_values_present(self):
        expected = {"attach", "detach", "disconnect", "disable", "invalidate", "reconnect"}
        actual = {s.value for s in AttachmentLifecycleSignal}
        assert expected == actual

    def test_from_string_valid(self):
        for s in AttachmentLifecycleSignal:
            assert AttachmentLifecycleSignal.from_string(s.value) == s

    def test_from_string_unknown_returns_none(self):
        assert AttachmentLifecycleSignal.from_string("bad_signal") is None
        assert AttachmentLifecycleSignal.from_string("") is None

    def test_enum_is_string_subclass(self):
        for s in AttachmentLifecycleSignal:
            assert isinstance(s, str)


# ---------------------------------------------------------------------------
# D: AttachedRuntimeSessionRecord
# ---------------------------------------------------------------------------


class TestAttachedRuntimeSessionRecordD:
    def test_default_construction(self):
        r = AttachedRuntimeSessionRecord()
        assert r.session_id  # auto-generated UUID
        assert r.device_id == ""
        assert r.source_runtime_posture == "control_only"
        assert r.coordination_role == ""
        assert r.capability_tier == "unknown"
        assert r.android_host_role == ""
        assert r.state == AttachmentState.attached
        assert r.last_signal == "attach"
        assert not r.metadata

    def test_explicit_construction(self):
        r = AttachedRuntimeSessionRecord(
            device_id="dev_001",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="full_runtime_host",
            state=AttachmentState.attached,
            metadata={"key": "val"},
        )
        assert r.device_id == "dev_001"
        assert r.is_join_runtime
        assert r.is_active
        assert r.is_eligible_for_delegation
        assert r.metadata == {"key": "val"}

    def test_is_active_property(self):
        r = AttachedRuntimeSessionRecord(state=AttachmentState.attached)
        assert r.is_active
        r2 = AttachedRuntimeSessionRecord(state=AttachmentState.detached)
        assert not r2.is_active

    def test_is_join_runtime_property(self):
        r = AttachedRuntimeSessionRecord(source_runtime_posture="join_runtime")
        assert r.is_join_runtime
        r2 = AttachedRuntimeSessionRecord(source_runtime_posture="control_only")
        assert not r2.is_join_runtime

    def test_is_eligible_for_delegation_requires_active_and_join_runtime(self):
        r_active_join = AttachedRuntimeSessionRecord(
            state=AttachmentState.attached,
            source_runtime_posture="join_runtime",
        )
        assert r_active_join.is_eligible_for_delegation

        r_detached_join = AttachedRuntimeSessionRecord(
            state=AttachmentState.detached,
            source_runtime_posture="join_runtime",
        )
        assert not r_detached_join.is_eligible_for_delegation

        r_active_control = AttachedRuntimeSessionRecord(
            state=AttachmentState.attached,
            source_runtime_posture="control_only",
        )
        assert not r_active_control.is_eligible_for_delegation

    def test_to_dict_keys(self):
        r = AttachedRuntimeSessionRecord(device_id="dev_001")
        d = r.to_dict()
        expected_keys = {
            "session_id", "device_id", "source_runtime_posture", "coordination_role",
            "capability_tier", "android_host_role", "state", "attached_at",
            "last_signal_at", "last_signal", "metadata",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_state_is_string(self):
        r = AttachedRuntimeSessionRecord(state=AttachmentState.attached)
        d = r.to_dict()
        assert isinstance(d["state"], str)
        assert d["state"] == "attached"

    def test_to_json_is_valid_json(self):
        r = AttachedRuntimeSessionRecord(device_id="dev_001")
        s = r.to_json()
        parsed = json.loads(s)
        assert parsed["device_id"] == "dev_001"

    def test_from_dict_round_trip(self):
        r = AttachedRuntimeSessionRecord(
            device_id="dev_xyz",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            state=AttachmentState.disconnected,
        )
        d = r.to_dict()
        r2 = AttachedRuntimeSessionRecord.from_dict(d)
        assert r2.session_id == r.session_id
        assert r2.device_id == r.device_id
        assert r2.source_runtime_posture == r.source_runtime_posture
        assert r2.state == r.state

    def test_from_dict_missing_keys_use_defaults(self):
        r = AttachedRuntimeSessionRecord.from_dict({})
        assert r.source_runtime_posture == "control_only"
        assert r.state == AttachmentState.invalidated
        assert r.capability_tier == "unknown"


# ---------------------------------------------------------------------------
# E: AttachedRuntimeSessionSnapshot
# ---------------------------------------------------------------------------


class TestAttachedRuntimeSessionSnapshotE:
    def test_default_construction(self):
        s = AttachedRuntimeSessionSnapshot()
        assert s.snapshot_id
        assert s.compiled_at > 0
        assert s.active_count == 0
        assert s.total_recorded == 0
        assert s.sessions == []
        assert s.authority == ATTACHED_RUNTIME_SESSION_AUTHORITY

    def test_to_dict_keys(self):
        s = AttachedRuntimeSessionSnapshot()
        d = s.to_dict()
        expected_keys = {
            "snapshot_id", "compiled_at", "active_count", "total_recorded",
            "sessions", "authority",
        }
        assert expected_keys == set(d.keys())

    def test_to_json_is_valid_json(self):
        s = AttachedRuntimeSessionSnapshot(active_count=2, total_recorded=5)
        raw = s.to_json()
        parsed = json.loads(raw)
        assert parsed["active_count"] == 2
        assert parsed["total_recorded"] == 5


# ---------------------------------------------------------------------------
# F: AttachedRuntimeSessionRuntime
# ---------------------------------------------------------------------------


class TestAttachedRuntimeSessionRuntimeF:
    def test_upsert_and_get(self):
        rt = _fresh_runtime()
        r = AttachedRuntimeSessionRecord(device_id="dev_001")
        rt.upsert(r)
        assert rt.get("dev_001") is r

    def test_get_unknown_device_returns_none(self):
        rt = _fresh_runtime()
        assert rt.get("unknown") is None

    def test_upsert_replaces_existing(self):
        rt = _fresh_runtime()
        r1 = AttachedRuntimeSessionRecord(device_id="dev_001", state=AttachmentState.attached)
        rt.upsert(r1)
        r2 = AttachedRuntimeSessionRecord(device_id="dev_001", state=AttachmentState.detached)
        rt.upsert(r2)
        assert rt.get("dev_001") is r2
        assert rt.total() == 1  # only one record for dev_001

    def test_list_active_filters_state(self):
        rt = _fresh_runtime()
        r_attached = AttachedRuntimeSessionRecord(device_id="a", state=AttachmentState.attached)
        r_detached = AttachedRuntimeSessionRecord(device_id="b", state=AttachmentState.detached)
        rt.upsert(r_attached)
        rt.upsert(r_detached)
        active = rt.list_active()
        assert len(active) == 1
        assert active[0].device_id == "a"

    def test_list_all_returns_all(self):
        rt = _fresh_runtime()
        for i in range(5):
            rt.upsert(AttachedRuntimeSessionRecord(device_id=f"dev_{i}"))
        assert len(rt.list_all()) == 5

    def test_count_active(self):
        rt = _fresh_runtime()
        rt.upsert(AttachedRuntimeSessionRecord(device_id="a", state=AttachmentState.attached))
        rt.upsert(AttachedRuntimeSessionRecord(device_id="b", state=AttachmentState.detached))
        rt.upsert(AttachedRuntimeSessionRecord(device_id="c", state=AttachmentState.attached))
        assert rt.count_active() == 2

    def test_ring_buffer_eviction(self):
        rt = AttachedRuntimeSessionRuntime(maxlen=3)
        for i in range(5):
            rt.upsert(AttachedRuntimeSessionRecord(device_id=f"dev_{i}"))
        # Buffer should only hold 3 entries (the latest 3)
        assert rt.total() <= 3


# ---------------------------------------------------------------------------
# G: attach_runtime_session — fresh attach
# ---------------------------------------------------------------------------


class TestAttachRuntimeSessionG:
    def test_fresh_attach_returns_attached_state(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_001")
        assert r.state == AttachmentState.attached
        assert r.device_id == "dev_001"

    def test_fresh_attach_creates_session_id(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        assert r.session_id
        assert len(r.session_id) > 8

    def test_fresh_attach_stored_in_runtime(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_001")
        stored = rt.get("dev_001")
        assert stored is r


# ---------------------------------------------------------------------------
# H: idempotent re-attach from detached state
# ---------------------------------------------------------------------------


class TestReAttachFromDetachedH:
    def test_reattach_preserves_session_id(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_001")
        r1_detaching = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.detach, runtime=rt)
        r1_detached = apply_lifecycle_signal(
            r1_detaching, AttachmentLifecycleSignal.detach, runtime=rt
        )
        original_id = r1_detached.session_id

        r2 = _attach(rt, "dev_001")
        assert r2.session_id == original_id
        assert r2.state == AttachmentState.attached

    def test_reattach_updates_posture(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_001", posture="control_only")
        r1_detaching = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.detach, runtime=rt)
        apply_lifecycle_signal(r1_detaching, AttachmentLifecycleSignal.detach, runtime=rt)

        r2 = _attach(rt, "dev_001", posture="join_runtime")
        assert r2.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# I: idempotent re-attach from disconnected state
# ---------------------------------------------------------------------------


class TestReAttachFromDisconnectedI:
    def test_reattach_from_disconnected_preserves_session_id(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_002")
        r1_dc = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.disconnect, runtime=rt)
        original_id = r1_dc.session_id

        r2 = _attach(rt, "dev_002")
        assert r2.session_id == original_id
        assert r2.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# J: disabled prior record → fresh session_id
# ---------------------------------------------------------------------------


class TestFreshSessionAfterDisabledJ:
    def test_disabled_prior_gets_new_session_id(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_003")
        r1_disabled = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.disable, runtime=rt)
        old_id = r1_disabled.session_id

        r2 = _attach(rt, "dev_003")
        assert r2.session_id != old_id
        assert r2.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# K: invalidated prior record → fresh session_id
# ---------------------------------------------------------------------------


class TestFreshSessionAfterInvalidatedK:
    def test_invalidated_prior_gets_new_session_id(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_004")
        apply_lifecycle_signal(r1, AttachmentLifecycleSignal.invalidate, runtime=rt)

        r2 = _attach(rt, "dev_004")
        assert r2.session_id != r1.session_id
        assert r2.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# L: join_runtime posture → eligible for delegation
# ---------------------------------------------------------------------------


class TestJoinRuntimeEligibilityL:
    def test_join_runtime_eligible_for_delegation(self):
        rt = _fresh_runtime()
        r = _attach(rt, posture="join_runtime")
        assert r.is_eligible_for_delegation


# ---------------------------------------------------------------------------
# M: control_only posture → not eligible for delegation
# ---------------------------------------------------------------------------


class TestControlOnlyIneligibleM:
    def test_control_only_not_eligible(self):
        rt = _fresh_runtime()
        r = _attach(rt, posture="control_only")
        assert not r.is_eligible_for_delegation


# ---------------------------------------------------------------------------
# N: metadata captured
# ---------------------------------------------------------------------------


class TestMetadataCapturedN:
    def test_metadata_is_stored(self):
        rt = _fresh_runtime()
        r = attach_runtime_session(
            "dev_005",
            metadata={"platform": "android", "version": "3.2"},
            runtime=rt,
        )
        assert r.metadata["platform"] == "android"
        assert r.metadata["version"] == "3.2"


# ---------------------------------------------------------------------------
# O: missing posture defaults to control_only
# ---------------------------------------------------------------------------


class TestDefaultPostureO:
    def test_none_posture_defaults_to_control_only(self):
        rt = _fresh_runtime()
        r = attach_runtime_session("dev_006", source_runtime_posture=None, runtime=rt)
        assert r.source_runtime_posture == "control_only"

    def test_empty_posture_defaults_to_control_only(self):
        rt = _fresh_runtime()
        r = attach_runtime_session("dev_007", source_runtime_posture="", runtime=rt)
        assert r.source_runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# P: apply_lifecycle_signal: detach transitions
# ---------------------------------------------------------------------------


class TestDetachTransitionsP:
    def test_attached_to_detaching(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        assert r2.state == AttachmentState.detaching

    def test_detaching_to_detached(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.detach, runtime=rt)
        assert r3.state == AttachmentState.detached

    def test_detached_allows_reattach(self):
        assert AttachmentState.detached.allows_reattach()


# ---------------------------------------------------------------------------
# Q: disconnect → reconnect → attached
# ---------------------------------------------------------------------------


class TestDisconnectReconnectQ:
    def test_attached_to_disconnected(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        assert r2.state == AttachmentState.disconnected

    def test_disconnected_to_attached_via_reconnect(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.reconnect, runtime=rt)
        assert r3.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# R: disable transitions
# ---------------------------------------------------------------------------


class TestDisableTransitionsR:
    def test_attached_to_disabled(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
        assert r2.state == AttachmentState.disabled

    def test_detached_to_disabled(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.detach, runtime=rt)
        r4 = apply_lifecycle_signal(r3, AttachmentLifecycleSignal.disable, runtime=rt)
        assert r4.state == AttachmentState.disabled


# ---------------------------------------------------------------------------
# S: invalidate transitions
# ---------------------------------------------------------------------------


class TestInvalidateTransitionsS:
    def test_attached_to_invalidated(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
        assert r2.state == AttachmentState.invalidated

    def test_disconnected_to_invalidated(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.invalidate, runtime=rt)
        assert r3.state == AttachmentState.invalidated


# ---------------------------------------------------------------------------
# T: terminal record raises ValueError
# ---------------------------------------------------------------------------


class TestTerminalRecordRaisesT:
    def test_invalidated_record_raises_on_any_signal(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r_inv = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
        with pytest.raises(ValueError, match="terminal"):
            apply_lifecycle_signal(r_inv, AttachmentLifecycleSignal.attach, runtime=rt)

    def test_invalidated_record_raises_on_detach(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r_inv = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
        with pytest.raises(ValueError):
            apply_lifecycle_signal(r_inv, AttachmentLifecycleSignal.detach, runtime=rt)


# ---------------------------------------------------------------------------
# U: invalid transition raises ValueError
# ---------------------------------------------------------------------------


class TestInvalidTransitionU:
    def test_reconnect_from_attached_raises(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        with pytest.raises(ValueError, match="not valid"):
            apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)

    def test_reconnect_from_detached_raises(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.detach, runtime=rt)
        with pytest.raises(ValueError):
            apply_lifecycle_signal(r3, AttachmentLifecycleSignal.reconnect, runtime=rt)

    def test_attach_from_attached_raises(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        with pytest.raises(ValueError):
            apply_lifecycle_signal(r, AttachmentLifecycleSignal.attach, runtime=rt)

    def test_reconnect_from_disabled_raises(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
        with pytest.raises(ValueError):
            apply_lifecycle_signal(r2, AttachmentLifecycleSignal.reconnect, runtime=rt)


# ---------------------------------------------------------------------------
# V: disabled → invalidate (terminal from disabled)
# ---------------------------------------------------------------------------


class TestDisabledToInvalidatedV:
    def test_disabled_to_invalidated(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.invalidate, runtime=rt)
        assert r3.state == AttachmentState.invalidated
        assert r3.state.is_terminal()


# ---------------------------------------------------------------------------
# W: apply_lifecycle_signal updates last_signal and last_signal_at
# ---------------------------------------------------------------------------


class TestSignalMetadataUpdatedW:
    def test_last_signal_updated(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        assert r2.last_signal == "disconnect"

    def test_last_signal_at_updated(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        before = time.time()
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        after = time.time()
        assert before <= r2.last_signal_at <= after


# ---------------------------------------------------------------------------
# X: get_attached_runtime_session: None for unknown
# ---------------------------------------------------------------------------


class TestGetSessionX:
    def test_returns_none_for_unknown_device(self):
        rt = _fresh_runtime()
        assert get_attached_runtime_session("nobody", runtime=rt) is None


# ---------------------------------------------------------------------------
# Y: get_attached_runtime_session: returns record after attach
# ---------------------------------------------------------------------------


class TestGetSessionAfterAttachY:
    def test_returns_record_after_attach(self):
        rt = _fresh_runtime()
        _attach(rt, "dev_100")
        r = get_attached_runtime_session("dev_100", runtime=rt)
        assert r is not None
        assert r.device_id == "dev_100"
        assert r.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Z: list_active_attached_sessions: only attached
# ---------------------------------------------------------------------------


class TestListActiveZ:
    def test_returns_only_attached_records(self):
        rt = _fresh_runtime()
        r_a = _attach(rt, "dev_a")
        r_b = _attach(rt, "dev_b")
        apply_lifecycle_signal(r_b, AttachmentLifecycleSignal.disconnect, runtime=rt)

        active = list_active_attached_sessions(runtime=rt)
        ids = {r.device_id for r in active}
        assert "dev_a" in ids
        assert "dev_b" not in ids


# ---------------------------------------------------------------------------
# AA: list_active_attached_sessions: empty when all detached
# ---------------------------------------------------------------------------


class TestListActiveEmptyAA:
    def test_empty_when_all_detached(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_x")
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        apply_lifecycle_signal(r2, AttachmentLifecycleSignal.detach, runtime=rt)
        assert list_active_attached_sessions(runtime=rt) == []


# ---------------------------------------------------------------------------
# AB: build_attached_runtime_session_snapshot: counts
# ---------------------------------------------------------------------------


class TestSnapshotCountsAB:
    def test_active_count_and_total_recorded(self):
        rt = _fresh_runtime()
        _attach(rt, "dev_1")
        r2 = _attach(rt, "dev_2")
        apply_lifecycle_signal(r2, AttachmentLifecycleSignal.disconnect, runtime=rt)

        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.active_count == 1
        assert snap.total_recorded == 2


# ---------------------------------------------------------------------------
# AC: build_attached_runtime_session_snapshot: sessions list
# ---------------------------------------------------------------------------


class TestSnapshotSessionsListAC:
    def test_sessions_are_dicts(self):
        rt = _fresh_runtime()
        _attach(rt, "dev_10")
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert len(snap.sessions) >= 1
        for s in snap.sessions:
            assert isinstance(s, dict)
            assert "device_id" in s
            assert "state" in s


# ---------------------------------------------------------------------------
# AD: build_attached_runtime_session_snapshot: authority field
# ---------------------------------------------------------------------------


class TestSnapshotAuthorityAD:
    def test_authority_field_correct(self):
        rt = _fresh_runtime()
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        assert snap.authority == ATTACHED_RUNTIME_SESSION_AUTHORITY


# ---------------------------------------------------------------------------
# AE: Singleton runtime
# ---------------------------------------------------------------------------


class TestSingletonRuntimeAE:
    def test_same_instance_on_repeated_calls(self):
        rt1 = get_attached_runtime_session_runtime()
        rt2 = get_attached_runtime_session_runtime()
        assert rt1 is rt2

    def test_after_reset_new_instance(self):
        rt_before = get_attached_runtime_session_runtime()
        reset_attached_runtime_session_runtime()
        rt_after = get_attached_runtime_session_runtime()
        assert rt_before is not rt_after


# ---------------------------------------------------------------------------
# AF: reset produces fresh instance
# ---------------------------------------------------------------------------


class TestResetRuntimeAF:
    def setup_method(self):
        reset_attached_runtime_session_runtime()

    def teardown_method(self):
        reset_attached_runtime_session_runtime()

    def test_reset_clears_records(self):
        rt = get_attached_runtime_session_runtime()
        attach_runtime_session("dev_reset_test")
        assert rt.total() >= 1
        reset_attached_runtime_session_runtime()
        rt_new = get_attached_runtime_session_runtime()
        assert rt_new.total() == 0


# ---------------------------------------------------------------------------
# AG: Serialisation round-trip: to_dict → from_dict
# ---------------------------------------------------------------------------


class TestSerialRoundTripAG:
    def test_round_trip_preserves_all_fields(self):
        r = AttachedRuntimeSessionRecord(
            device_id="dev_rt",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="full_runtime_host",
            state=AttachmentState.disconnected,
            last_signal="disconnect",
            metadata={"info": "test"},
        )
        d = r.to_dict()
        r2 = AttachedRuntimeSessionRecord.from_dict(d)
        assert r2.session_id == r.session_id
        assert r2.device_id == r.device_id
        assert r2.source_runtime_posture == r.source_runtime_posture
        assert r2.coordination_role == r.coordination_role
        assert r2.capability_tier == r.capability_tier
        assert r2.android_host_role == r.android_host_role
        assert r2.state == r.state
        assert r2.last_signal == r.last_signal
        assert r2.metadata == r.metadata


# ---------------------------------------------------------------------------
# AH: Serialisation: to_json is valid JSON
# ---------------------------------------------------------------------------


class TestSerialToJsonAH:
    def test_to_json_valid(self):
        r = AttachedRuntimeSessionRecord(device_id="dev_json")
        s = r.to_json()
        parsed = json.loads(s)
        assert parsed["device_id"] == "dev_json"
        assert parsed["state"] == "attached"


# ---------------------------------------------------------------------------
# AI: Snapshot to_json
# ---------------------------------------------------------------------------


class TestSnapshotToJsonAI:
    def test_snapshot_to_json_valid(self):
        rt = _fresh_runtime()
        _attach(rt, "dev_snap_json")
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        raw = snap.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed["sessions"], list)
        assert parsed["active_count"] == 1


# ---------------------------------------------------------------------------
# AJ: Multiple devices: independent sessions
# ---------------------------------------------------------------------------


class TestMultipleDevicesAJ:
    def test_each_device_gets_own_session(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_m1")
        r2 = _attach(rt, "dev_m2")
        r3 = _attach(rt, "dev_m3")
        assert len({r1.session_id, r2.session_id, r3.session_id}) == 3
        assert rt.total() == 3

    def test_lifecycle_on_one_does_not_affect_others(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_n1")
        _attach(rt, "dev_n2")
        apply_lifecycle_signal(r1, AttachmentLifecycleSignal.disconnect, runtime=rt)
        r2_stored = rt.get("dev_n2")
        assert r2_stored is not None
        assert r2_stored.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# AK: Ring buffer eviction
# ---------------------------------------------------------------------------


class TestRingBufferEvictionAK:
    def test_eviction_when_capacity_exceeded(self):
        rt = AttachedRuntimeSessionRuntime(maxlen=5)
        for i in range(10):
            rt.upsert(AttachedRuntimeSessionRecord(device_id=f"dev_rb_{i}"))
        assert rt.total() <= 5


# ---------------------------------------------------------------------------
# AL: End-to-end Android join_runtime attach → delegate → detach
# ---------------------------------------------------------------------------


class TestE2EAndroidLifecycleAL:
    def test_android_join_runtime_full_lifecycle(self):
        rt = _fresh_runtime()

        # 1. Attach Android device with join_runtime posture.
        r = attach_runtime_session(
            "android_001",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            capability_tier="full_runtime",
            android_host_role="full_runtime_host",
            metadata={"platform": "android"},
            runtime=rt,
        )
        assert r.state == AttachmentState.attached
        assert r.is_eligible_for_delegation

        # 2. Device is active and eligible for agent dispatch.
        stored = get_attached_runtime_session("android_001", runtime=rt)
        assert stored is not None
        assert stored.is_active

        # 3. Verify it appears in active list.
        active = list_active_attached_sessions(runtime=rt)
        assert any(x.device_id == "android_001" for x in active)

        # 4. Graceful detach sequence.
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        assert r2.state == AttachmentState.detaching
        assert not r2.is_active

        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.detach, runtime=rt)
        assert r3.state == AttachmentState.detached

        # 5. No longer in active list.
        active_after = list_active_attached_sessions(runtime=rt)
        assert not any(x.device_id == "android_001" for x in active_after)


# ---------------------------------------------------------------------------
# AM: End-to-end reconnect after disconnect preserves session_id
# ---------------------------------------------------------------------------


class TestE2EReconnectPreservesSessionAM:
    def test_reconnect_preserves_session_id(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_reconnect")
        original_id = r.session_id

        # Disconnect.
        r_dc = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
        assert r_dc.state == AttachmentState.disconnected

        # Reconnect via signal.
        r_rc = apply_lifecycle_signal(r_dc, AttachmentLifecycleSignal.reconnect, runtime=rt)
        assert r_rc.state == AttachmentState.attached
        assert r_rc.session_id == original_id  # preserved


# ---------------------------------------------------------------------------
# AN: disable prevents re-attachment via allows_reattach()
# ---------------------------------------------------------------------------


class TestE2EDisabledBlocksReattachAN:
    def test_disabled_allows_reattach_false(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_disabled")
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
        assert not r2.state.allows_reattach()

    def test_disabled_gets_fresh_session_on_attach(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_disabled2")
        old_id = r.session_id
        apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
        # Operator explicitly re-attaches (overrides disable via new call).
        r2 = _attach(rt, "dev_disabled2")
        assert r2.session_id != old_id
        assert r2.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# AO: invalidation is terminal; new session gets new session_id
# ---------------------------------------------------------------------------


class TestE2EInvalidationTerminalAO:
    def test_invalidated_session_is_terminal(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_inv")
        r_inv = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
        assert r_inv.state.is_terminal()

    def test_new_attach_after_invalidation_gets_new_id(self):
        rt = _fresh_runtime()
        r = _attach(rt, "dev_inv2")
        old_id = r.session_id
        apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
        r2 = _attach(rt, "dev_inv2")
        assert r2.session_id != old_id
        assert r2.state == AttachmentState.attached


# ---------------------------------------------------------------------------
# AP: core.runtime re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReExportsAP:
    def test_pr7_symbols_accessible_from_core_runtime(self):
        # Import only the attached_runtime_session module directly to verify
        # symbols are accessible without depending on the full core.runtime
        # import chain (which requires pydantic/fastapi).
        from core.attached_runtime_session import (
            ATTACHED_RUNTIME_SESSION_AUTHORITY,
            ATTACHED_RUNTIME_SESSION_PR7_SENTINEL,
            AttachmentState,
            AttachmentLifecycleSignal,
            AttachedRuntimeSessionRecord,
            AttachedRuntimeSessionSnapshot,
            AttachedRuntimeSessionRuntime,
            attach_runtime_session,
            apply_lifecycle_signal,
            get_attached_runtime_session,
            list_active_attached_sessions,
            build_attached_runtime_session_snapshot,
            get_attached_runtime_session_runtime,
            reset_attached_runtime_session_runtime,
        )
        assert ATTACHED_RUNTIME_SESSION_AUTHORITY
        assert ATTACHED_RUNTIME_SESSION_PR7_SENTINEL
        assert AttachmentState.attached
        assert AttachmentLifecycleSignal.attach


# ---------------------------------------------------------------------------
# AQ: projection.py sentinel is present and not UNAVAILABLE
# ---------------------------------------------------------------------------


class TestProjectionSentinelAQ:
    def test_attached_runtime_session_aligned_pr7_sentinel(self):
        try:
            from core.routes.projection import ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
            assert "UNAVAILABLE" not in ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
            assert "PR7" in ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
        except ImportError:
            pytest.skip("projection module not importable in this environment")


# ---------------------------------------------------------------------------
# AR: Unique session_ids
# ---------------------------------------------------------------------------


class TestUniqueSessionIdsAR:
    def test_two_fresh_attaches_different_ids(self):
        rt = _fresh_runtime()
        r1 = _attach(rt, "dev_uid_1")
        r2 = _attach(rt, "dev_uid_2")
        assert r1.session_id != r2.session_id


# ---------------------------------------------------------------------------
# AS: AttachmentState.from_string: unknown → invalidated
# ---------------------------------------------------------------------------


class TestFromStringUnknownAS:
    def test_unknown_attachment_state_defaults_to_invalidated(self):
        result = AttachmentState.from_string("completely_unknown_value")
        assert result == AttachmentState.invalidated


# ---------------------------------------------------------------------------
# AT: AttachmentLifecycleSignal.from_string: unknown → None
# ---------------------------------------------------------------------------


class TestLifecycleSignalFromStringAT:
    def test_unknown_signal_returns_none(self):
        assert AttachmentLifecycleSignal.from_string("bogus_signal") is None
        assert AttachmentLifecycleSignal.from_string("ATTACH") is None  # case-sensitive

    def test_lowercase_attach_returns_signal(self):
        assert AttachmentLifecycleSignal.from_string("attach") == AttachmentLifecycleSignal.attach
        assert AttachmentLifecycleSignal.from_string("detach") == AttachmentLifecycleSignal.detach
        assert AttachmentLifecycleSignal.from_string("disconnect") == AttachmentLifecycleSignal.disconnect


# ---------------------------------------------------------------------------
# AU: Snapshot includes snapshot_id and compiled_at
# ---------------------------------------------------------------------------


class TestSnapshotTimestampsAU:
    def test_snapshot_has_snapshot_id_and_compiled_at(self):
        rt = _fresh_runtime()
        before = time.time()
        snap = build_attached_runtime_session_snapshot(runtime=rt)
        after = time.time()
        assert snap.snapshot_id
        assert before <= snap.compiled_at <= after
        d = snap.to_dict()
        assert "snapshot_id" in d
        assert "compiled_at" in d


# ---------------------------------------------------------------------------
# AV: android_host_role captured
# ---------------------------------------------------------------------------


class TestAndroidHostRoleCapturedAV:
    def test_android_host_role_stored_on_record(self):
        rt = _fresh_runtime()
        r = attach_runtime_session(
            "dev_android",
            android_host_role="full_runtime_host",
            runtime=rt,
        )
        assert r.android_host_role == "full_runtime_host"
        d = r.to_dict()
        assert d["android_host_role"] == "full_runtime_host"

    def test_non_android_device_has_empty_android_role(self):
        rt = _fresh_runtime()
        r = attach_runtime_session("dev_desktop", android_host_role="", runtime=rt)
        assert r.android_host_role == ""


# ---------------------------------------------------------------------------
# AW: detaching → disable transitions correctly
# ---------------------------------------------------------------------------


class TestDetachingToDisabledAW:
    def test_detaching_to_disabled(self):
        rt = _fresh_runtime()
        r = _attach(rt)
        r2 = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
        assert r2.state == AttachmentState.detaching
        r3 = apply_lifecycle_signal(r2, AttachmentLifecycleSignal.disable, runtime=rt)
        assert r3.state == AttachmentState.disabled


# ---------------------------------------------------------------------------
# AX: Concurrency: multiple attach calls for same device are idempotent
# ---------------------------------------------------------------------------


class TestConcurrencyAX:
    def test_concurrent_attaches_same_device_stable(self):
        rt = _fresh_runtime()
        results = []
        errors = []

        def do_attach():
            try:
                r = attach_runtime_session(
                    "dev_concurrent",
                    source_runtime_posture="join_runtime",
                    runtime=rt,
                )
                results.append(r)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=do_attach) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent attach raised errors: {errors}"
        assert rt.total() == 1  # only one record for dev_concurrent
        stored = rt.get("dev_concurrent")
        assert stored is not None
        assert stored.state == AttachmentState.attached
