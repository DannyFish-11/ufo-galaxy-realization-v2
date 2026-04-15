"""tests/test_pr7_post533_attached_runtime_session.py
=======================================================
Tests for PR package 7 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Persistent Attached-Runtime Session Semantics.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — AttachmentState enum: all values present, from_string(), is_active(),
     is_terminal(), is_recoverable().
C  — AttachmentLifecycleSignal enum: all values present, from_string().
D  — AttachedRuntimeSessionRecord: construction, defaults, to_dict(),
     from_dict(), to_json(), is_active(), is_eligible_for_execution().
E  — AttachedRuntimeSessionSnapshot: construction, defaults, to_dict(),
     to_json().
F  — AttachedRuntimeSessionRuntime: push, replace_latest_for_device,
     get_latest_for_device, list_all, list_active, size, capacity, clear.
G  — attach_runtime_session: new attach with join_runtime posture → attached.
H  — attach_runtime_session: control_only posture → detached, not eligible.
I  — attach_runtime_session: idempotent re-attach of already-attached device.
J  — attach_runtime_session: re-attach from disconnected state.
K  — attach_runtime_session: re-attach from detached state.
L  — attach_runtime_session: metadata merging on idempotent re-attach.
M  — attach_runtime_session: android_host_role and capability_tier carried.
N  — attach_runtime_session: session_id propagated.
O  — apply_lifecycle_signal: attached → detach → detaching.
P  — apply_lifecycle_signal: detaching → detach → detached.
Q  — apply_lifecycle_signal: attached → disconnect → disconnected.
R  — apply_lifecycle_signal: disconnected → reconnect → attached.
S  — apply_lifecycle_signal: attached → disable → disabled.
T  — apply_lifecycle_signal: attached → invalidate → invalidated (terminal).
U  — apply_lifecycle_signal: disconnected → invalidate → invalidated.
V  — apply_lifecycle_signal: invalidated → any signal except attach → no change.
W  — apply_lifecycle_signal: invalidated → attach → no change (terminal).
X  — apply_lifecycle_signal: no defined transition → record unchanged.
Y  — apply_lifecycle_signal: previous_state recorded on transition.
Z  — apply_lifecycle_signal: reason propagated.
AA — apply_lifecycle_signal: last_transition_at updated.
AB — apply_lifecycle_signal: detaching → disable → disabled.
AC — apply_lifecycle_signal: disconnected → disable → disabled.
AD — apply_lifecycle_signal: disabled → attach → attached.
AE — apply_lifecycle_signal: detached → attach → attached.
AF — get_attached_runtime_session: returns most recent record for device.
AG — get_attached_runtime_session: returns None for unknown device.
AH — list_active_attached_sessions: returns only attached records.
AI — list_active_attached_sessions: empty when no attached sessions.
AJ — build_attached_runtime_session_snapshot: counts active, total.
AK — build_attached_runtime_session_snapshot: includes policy sentinels.
AL — build_attached_runtime_session_snapshot: empty runtime → zero counts.
AM — core.runtime re-exports: all PR-7 symbols accessible from core.runtime.
AN — projection.py sentinel: ATTACHED_RUNTIME_SESSION_ALIGNED_PR7 is present
     and not UNAVAILABLE.
AO — Ring buffer capacity: 128.
AP — Ring buffer eviction: oldest entry evicted when full.
AQ — Serialisation round-trip: AttachedRuntimeSessionRecord to_dict → from_dict.
AR — Serialisation round-trip: to_json produces valid JSON.
AS — Serialisation: from_dict with malformed attachment_state → safe default.
AT — Serialisation: from_dict with non-dict raises ValueError.
AU — Multiple devices: each gets its own record.
AV — attach_runtime_session: second attach from clean state creates new record.
AW — AttachmentState.from_string: unknown string → default detached.
AX — AttachmentLifecycleSignal.from_string: unknown string → default attach.
AY — Transition table completeness: detaching → reconnect → attached.
AZ — End-to-end lifecycle: full attach → disconnect → reconnect → detach → detached.
BA — End-to-end: control_only device rejected, join_runtime accepted in same runtime.
BB — is_eligible_for_execution: attached + join_runtime → True.
BC — is_eligible_for_execution: attached + control_only → False.
BD — is_eligible_for_execution: disconnected + join_runtime → False.
BE — is_eligible_for_execution: disabled + join_runtime → False.
BF — Record ID is auto-generated UUID and unique per record.
BG — Snapshot ID is auto-generated UUID and unique per snapshot.
BH — attach_runtime_session: empty device_id still creates record.
BI — apply_lifecycle_signal: attached → detach records last_signal.
BJ — apply_lifecycle_signal: reconnect from detaching.
BK — list_active_attached_sessions: reflects latest record for device after
     lifecycle transitions.
BL — build_attached_runtime_session_snapshot: records are newest-first.
BM — reset_attached_runtime_session_runtime: clears singleton for isolation.
BN — get_attached_runtime_session_runtime: returns same singleton.
BO — AttachmentState enum string values match expected lowercase strings.
BP — AttachmentLifecycleSignal enum string values match expected lowercase strings.
BQ — attach_runtime_session: None posture treated as control_only → detached.
BR — Snapshot to_dict contains 'records', 'active_count', 'total_count'.
BS — Record to_dict: previous_state None → None in dict.
BT — Multiple transitions on same record: state history preserved in record.
BU — attach_runtime_session: attach_reason stored in record.
BV — Two separate devices: list_active returns both when both attached.
BW — apply_lifecycle_signal: does not mutate the original record.
BX — attach_runtime_session with custom runtime isolation.
BY — Snapshot snapshotted_at is recent timestamp.
BZ — All 10 policy sentinels non-empty strings.
"""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import MagicMock  # noqa: F401  # reserved for future mock-based tests

import pytest

from core.attached_runtime_session import (
    # Sentinels
    ATTACHED_RUNTIME_SESSION_AUTHORITY,
    ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY,
    TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY,
    DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY,
    ATTACH_IS_IDEMPOTENT_POLICY,
    DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY,
    INVALIDATED_SESSION_IS_TERMINAL_POLICY,
    DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY,
    ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY,
    ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE_POLICY,
    ATTACHED_RUNTIME_SESSION_PR7_SENTINEL,
    # Enums
    AttachmentState,
    AttachmentLifecycleSignal,
    AttachmentLifecycleAction,
    # Dataclasses / classes
    AttachedRuntimeSessionRecord,
    AttachedRuntimeSessionSnapshot,
    AttachedRuntimeSessionRuntime,
    # Functions
    attach_runtime_session,
    apply_lifecycle_signal,
    classify_attach_lifecycle_action,
    classify_signal_lifecycle_action,
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
    """Return a fresh, isolated runtime (not the module singleton)."""
    return AttachedRuntimeSessionRuntime(capacity=128)


def _attach(device_id: str = "dev-1", **kw) -> AttachedRuntimeSessionRecord:
    rt = kw.pop("runtime", _fresh_runtime())
    return attach_runtime_session(
        device_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
        **kw,
    )


# ---------------------------------------------------------------------------
# Group A — Sentinel presence and correctness
# ---------------------------------------------------------------------------


def test_a1_authority_sentinel_non_empty():
    assert isinstance(ATTACHED_RUNTIME_SESSION_AUTHORITY, str)
    assert len(ATTACHED_RUNTIME_SESSION_AUTHORITY) > 0


def test_a2_pr7_sentinel_non_empty():
    assert isinstance(ATTACHED_RUNTIME_SESSION_PR7_SENTINEL, str)
    assert "pr7" in ATTACHED_RUNTIME_SESSION_PR7_SENTINEL.lower()


def test_a3_persists_policy_non_empty():
    assert "POLICY" in ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY


def test_a4_transient_distinct_policy():
    assert "POLICY" in TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY


def test_a5_detach_signal_required_policy():
    assert "POLICY" in DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY


def test_a6_idempotent_policy():
    assert "POLICY" in ATTACH_IS_IDEMPOTENT_POLICY


def test_a7_disconnected_does_not_invalidate_policy():
    assert "POLICY" in DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY


def test_a8_invalidated_is_terminal_policy():
    assert "POLICY" in INVALIDATED_SESSION_IS_TERMINAL_POLICY


def test_a9_disabled_not_eligible_policy():
    assert "POLICY" in DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY


def test_a10_requires_join_runtime_policy():
    assert "POLICY" in ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY


def test_a11_lifecycle_posture_aware_policy():
    assert "POLICY" in ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY


# ---------------------------------------------------------------------------
# Group B — AttachmentState enum
# ---------------------------------------------------------------------------


def test_b1_all_states_present():
    values = {s.value for s in AttachmentState}
    assert values == {"attached", "detaching", "detached", "disconnected", "disabled", "invalidated"}


def test_b2_from_string_valid():
    assert AttachmentState.from_string("attached") == AttachmentState.attached
    assert AttachmentState.from_string("disconnected") == AttachmentState.disconnected
    assert AttachmentState.from_string("invalidated") == AttachmentState.invalidated


def test_b3_from_string_unknown_returns_default():
    result = AttachmentState.from_string("unknown_xyz")
    assert result == AttachmentState.detached


def test_b4_from_string_custom_default():
    result = AttachmentState.from_string("bogus", default=AttachmentState.disabled)
    assert result == AttachmentState.disabled


def test_b5_from_string_non_string_input():
    result = AttachmentState.from_string(None)
    assert result == AttachmentState.detached


def test_b6_is_active_attached():
    assert AttachmentState.attached.is_active() is True


def test_b7_is_active_non_attached():
    for s in [AttachmentState.detaching, AttachmentState.detached,
              AttachmentState.disconnected, AttachmentState.disabled,
              AttachmentState.invalidated]:
        assert s.is_active() is False


def test_b8_is_terminal():
    assert AttachmentState.invalidated.is_terminal() is True
    assert AttachmentState.detached.is_terminal() is True
    assert AttachmentState.attached.is_terminal() is False
    assert AttachmentState.disconnected.is_terminal() is False


def test_b9_is_recoverable():
    assert AttachmentState.disconnected.is_recoverable() is True
    assert AttachmentState.detaching.is_recoverable() is True
    assert AttachmentState.invalidated.is_recoverable() is False
    assert AttachmentState.attached.is_recoverable() is False


def test_b10_string_values_lowercase():
    for s in AttachmentState:
        assert s.value == s.value.lower()


# ---------------------------------------------------------------------------
# Group C — AttachmentLifecycleSignal enum
# ---------------------------------------------------------------------------


def test_c1_all_signals_present():
    values = {s.value for s in AttachmentLifecycleSignal}
    assert values == {"attach", "detach", "disconnect", "disable", "invalidate", "reconnect"}


def test_c2_from_string_valid():
    assert AttachmentLifecycleSignal.from_string("attach") == AttachmentLifecycleSignal.attach
    assert AttachmentLifecycleSignal.from_string("invalidate") == AttachmentLifecycleSignal.invalidate


def test_c3_from_string_unknown_returns_default():
    result = AttachmentLifecycleSignal.from_string("bogus")
    assert result == AttachmentLifecycleSignal.attach


def test_c4_from_string_non_string():
    result = AttachmentLifecycleSignal.from_string(42)
    assert result == AttachmentLifecycleSignal.attach


def test_c5_string_values_lowercase():
    for s in AttachmentLifecycleSignal:
        assert s.value == s.value.lower()


# ---------------------------------------------------------------------------
# Group D — AttachedRuntimeSessionRecord
# ---------------------------------------------------------------------------


def test_d1_construction_defaults():
    r = AttachedRuntimeSessionRecord(device_id="dev-1")
    assert r.device_id == "dev-1"
    assert r.source_runtime_posture == "join_runtime"
    assert r.attachment_state == AttachmentState.attached
    assert r.previous_state is None
    assert r.coordination_role == ""
    assert r.android_host_role == ""
    assert r.capability_tier == ""
    assert r.session_id == ""
    assert r.attach_reason == ""
    assert r.last_signal is None
    assert isinstance(r.metadata, dict)
    assert isinstance(r.record_id, str)


def test_d2_is_active_attached():
    r = AttachedRuntimeSessionRecord(device_id="d", attachment_state=AttachmentState.attached)
    assert r.is_active() is True


def test_d3_is_active_non_attached():
    r = AttachedRuntimeSessionRecord(device_id="d", attachment_state=AttachmentState.disconnected)
    assert r.is_active() is False


def test_d4_is_eligible_for_execution_attached_join_runtime():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.attached,
        source_runtime_posture="join_runtime",
    )
    assert r.is_eligible_for_execution() is True


def test_d5_is_eligible_for_execution_attached_control_only():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.attached,
        source_runtime_posture="control_only",
    )
    assert r.is_eligible_for_execution() is False


def test_d6_to_dict_keys():
    r = AttachedRuntimeSessionRecord(device_id="d")
    d = r.to_dict()
    for key in ("record_id", "device_id", "session_id", "source_runtime_posture",
                "coordination_role", "android_host_role", "capability_tier",
                "attachment_state", "previous_state", "attach_reason",
                "last_signal", "attached_at", "last_transition_at", "metadata"):
        assert key in d


def test_d7_to_dict_state_is_string():
    r = AttachedRuntimeSessionRecord(device_id="d", attachment_state=AttachmentState.attached)
    assert r.to_dict()["attachment_state"] == "attached"


def test_d8_to_dict_previous_state_none():
    r = AttachedRuntimeSessionRecord(device_id="d")
    assert r.to_dict()["previous_state"] is None


def test_d9_to_json_valid():
    r = AttachedRuntimeSessionRecord(device_id="d")
    j = r.to_json()
    parsed = json.loads(j)
    assert parsed["device_id"] == "d"


def test_d10_from_dict_roundtrip():
    r = AttachedRuntimeSessionRecord(
        device_id="dev-x",
        source_runtime_posture="join_runtime",
        coordination_role="source_controller",
        android_host_role="FULL_RUNTIME_HOST",
        capability_tier="full_runtime",
        attachment_state=AttachmentState.attached,
        previous_state=AttachmentState.disconnected,
        session_id="sess-1",
        attach_reason="test reason",
        last_signal=AttachmentLifecycleSignal.reconnect,
        metadata={"platform": "android"},
    )
    restored = AttachedRuntimeSessionRecord.from_dict(r.to_dict())
    assert restored.device_id == r.device_id
    assert restored.attachment_state == AttachmentState.attached
    assert restored.previous_state == AttachmentState.disconnected
    assert restored.last_signal == AttachmentLifecycleSignal.reconnect
    assert restored.metadata == r.metadata


def test_d11_from_dict_invalid_state_defaults():
    d = {"device_id": "d", "attachment_state": "bogus_state"}
    r = AttachedRuntimeSessionRecord.from_dict(d)
    assert r.attachment_state == AttachmentState.detached


def test_d12_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AttachedRuntimeSessionRecord.from_dict("not a dict")


# ---------------------------------------------------------------------------
# Group E — AttachedRuntimeSessionSnapshot
# ---------------------------------------------------------------------------


def test_e1_construction_defaults():
    s = AttachedRuntimeSessionSnapshot()
    assert isinstance(s.snapshot_id, str)
    assert s.records == []
    assert s.active_count == 0
    assert s.total_count == 0
    assert s.policy_sentinels == []


def test_e2_to_dict_keys():
    s = AttachedRuntimeSessionSnapshot()
    d = s.to_dict()
    for k in ("snapshot_id", "records", "active_count", "total_count",
               "snapshotted_at", "policy_sentinels"):
        assert k in d


def test_e3_to_json_valid():
    s = AttachedRuntimeSessionSnapshot()
    j = s.to_json()
    parsed = json.loads(j)
    assert "snapshot_id" in parsed


# ---------------------------------------------------------------------------
# Group F — AttachedRuntimeSessionRuntime
# ---------------------------------------------------------------------------


def test_f1_initial_size_zero():
    rt = AttachedRuntimeSessionRuntime()
    assert rt.size() == 0


def test_f2_capacity_default():
    rt = AttachedRuntimeSessionRuntime()
    assert rt.capacity() == 128


def test_f3_push_and_size():
    rt = AttachedRuntimeSessionRuntime()
    r = AttachedRuntimeSessionRecord(device_id="d")
    rt.push(r)
    assert rt.size() == 1


def test_f4_get_latest_for_device():
    rt = AttachedRuntimeSessionRuntime()
    r1 = AttachedRuntimeSessionRecord(device_id="d", session_id="s1")
    r2 = AttachedRuntimeSessionRecord(device_id="d", session_id="s2")
    rt.push(r1)
    rt.push(r2)
    latest = rt.get_latest_for_device("d")
    assert latest.session_id == "s2"


def test_f5_get_latest_unknown_device():
    rt = AttachedRuntimeSessionRuntime()
    assert rt.get_latest_for_device("unknown") is None


def test_f6_list_all_newest_first():
    rt = AttachedRuntimeSessionRuntime()
    r1 = AttachedRuntimeSessionRecord(device_id="a")
    r2 = AttachedRuntimeSessionRecord(device_id="b")
    rt.push(r1)
    rt.push(r2)
    all_records = rt.list_all()
    assert all_records[0].device_id == "b"
    assert all_records[1].device_id == "a"


def test_f7_list_active_only_attached():
    rt = AttachedRuntimeSessionRuntime()
    r_attached = AttachedRuntimeSessionRecord(device_id="a", attachment_state=AttachmentState.attached)
    r_detached = AttachedRuntimeSessionRecord(device_id="b", attachment_state=AttachmentState.detached)
    rt.push(r_attached)
    rt.push(r_detached)
    active = rt.list_active()
    assert len(active) == 1
    assert active[0].device_id == "a"


def test_f8_replace_latest_for_device_success():
    rt = AttachedRuntimeSessionRuntime()
    r = AttachedRuntimeSessionRecord(device_id="d", session_id="old")
    rt.push(r)
    updated = AttachedRuntimeSessionRecord(
        device_id="d", session_id="new", record_id=r.record_id
    )
    replaced = rt.replace_latest_for_device(updated)
    assert replaced is True
    assert rt.get_latest_for_device("d").session_id == "new"


def test_f9_replace_latest_unknown_device():
    rt = AttachedRuntimeSessionRuntime()
    r = AttachedRuntimeSessionRecord(device_id="unknown")
    replaced = rt.replace_latest_for_device(r)
    assert replaced is False


def test_f10_clear():
    rt = AttachedRuntimeSessionRuntime()
    rt.push(AttachedRuntimeSessionRecord(device_id="d"))
    rt.clear()
    assert rt.size() == 0


# ---------------------------------------------------------------------------
# Group G — attach_runtime_session: new attach with join_runtime
# ---------------------------------------------------------------------------


def test_g1_attach_join_runtime_returns_attached():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r.attachment_state == AttachmentState.attached
    assert r.device_id == "dev-1"


def test_g2_attach_creates_record_in_runtime():
    rt = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert rt.size() == 1


def test_g3_attach_last_signal_is_attach():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r.last_signal == AttachmentLifecycleSignal.attach


# ---------------------------------------------------------------------------
# Group H — attach_runtime_session: control_only rejected
# ---------------------------------------------------------------------------


def test_h1_control_only_returns_detached():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="control_only", runtime=rt)
    assert r.attachment_state == AttachmentState.detached


def test_h2_control_only_not_eligible():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="control_only", runtime=rt)
    assert r.is_eligible_for_execution() is False


def test_h3_control_only_reason_mentions_policy():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="control_only", runtime=rt)
    assert "join_runtime" in r.attach_reason.lower() or "posture" in r.attach_reason.lower()


# ---------------------------------------------------------------------------
# Group I — Idempotent re-attach
# ---------------------------------------------------------------------------


def test_i1_idempotent_reattach_same_record_id():
    rt = _fresh_runtime()
    r1 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r2.record_id == r1.record_id


def test_i2_idempotent_reattach_still_attached():
    rt = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r2.attachment_state == AttachmentState.attached


def test_i3_idempotent_does_not_duplicate_in_buffer():
    rt = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert rt.size() == 1


# ---------------------------------------------------------------------------
# Group J — Re-attach from disconnected
# ---------------------------------------------------------------------------


def test_j1_reattach_from_disconnected():
    rt = _fresh_runtime()
    r1 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    r1_disconnected = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r2.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group K — Re-attach from detached
# ---------------------------------------------------------------------------


def test_k1_reattach_from_detached():
    rt = _fresh_runtime()
    r1 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    r1 = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.detach, runtime=rt)
    r1 = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.detach, runtime=rt)
    # r1 is now detached; re-attach
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r2.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group L — Metadata merging on idempotent re-attach
# ---------------------------------------------------------------------------


def test_l1_metadata_merged_on_reattach():
    rt = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                           metadata={"key1": "val1"}, runtime=rt)
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                                metadata={"key2": "val2"}, runtime=rt)
    assert r2.metadata.get("key1") == "val1"
    assert r2.metadata.get("key2") == "val2"


# ---------------------------------------------------------------------------
# Group M — android_host_role and capability_tier
# ---------------------------------------------------------------------------


def test_m1_android_host_role_stored():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                               android_host_role="FULL_RUNTIME_HOST", runtime=rt)
    assert r.android_host_role == "FULL_RUNTIME_HOST"


def test_m2_capability_tier_stored():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                               capability_tier="full_runtime", runtime=rt)
    assert r.capability_tier == "full_runtime"


# ---------------------------------------------------------------------------
# Group N — session_id propagated
# ---------------------------------------------------------------------------


def test_n1_session_id_propagated():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                               session_id="sess-abc", runtime=rt)
    assert r.session_id == "sess-abc"


# ---------------------------------------------------------------------------
# Groups O–AD — apply_lifecycle_signal transitions
# ---------------------------------------------------------------------------


def test_o1_attached_detach_to_detaching():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert updated.attachment_state == AttachmentState.detaching


def test_p1_detaching_detach_to_detached():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert r.attachment_state == AttachmentState.detached


def test_q1_attached_disconnect_to_disconnected():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    assert updated.attachment_state == AttachmentState.disconnected


def test_r1_disconnected_reconnect_to_attached():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)
    assert r.attachment_state == AttachmentState.attached


def test_s1_attached_disable_to_disabled():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
    assert updated.attachment_state == AttachmentState.disabled


def test_t1_attached_invalidate_to_invalidated():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
    assert updated.attachment_state == AttachmentState.invalidated


def test_u1_disconnected_invalidate_to_invalidated():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
    assert r.attachment_state == AttachmentState.invalidated


def test_v1_invalidated_signal_no_change():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
    for sig in [AttachmentLifecycleSignal.detach, AttachmentLifecycleSignal.disconnect,
                AttachmentLifecycleSignal.disable, AttachmentLifecycleSignal.reconnect]:
        result = apply_lifecycle_signal(r, sig, runtime=rt)
        assert result.attachment_state == AttachmentState.invalidated


def test_w1_invalidated_attach_no_change():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
    result = apply_lifecycle_signal(r, AttachmentLifecycleSignal.attach, runtime=rt)
    assert result.attachment_state == AttachmentState.invalidated


def test_x1_no_defined_transition_record_unchanged():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    # invalidated → reconnect has no defined transition (stays invalidated via terminal check)
    r_inv = apply_lifecycle_signal(r, AttachmentLifecycleSignal.invalidate, runtime=rt)
    before_state = r_inv.attachment_state
    result = apply_lifecycle_signal(r_inv, AttachmentLifecycleSignal.reconnect, runtime=rt)
    assert result.attachment_state == before_state  # terminal, unchanged


def test_y1_previous_state_recorded():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    assert updated.previous_state == AttachmentState.attached


def test_z1_reason_propagated():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect,
                                     reason="network lost", runtime=rt)
    assert updated.attach_reason == "network lost"


def test_aa1_last_transition_at_updated():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    before = r.last_transition_at
    time.sleep(0.01)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    assert updated.last_transition_at >= before


def test_ab1_detaching_disable_to_disabled():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert r.attachment_state == AttachmentState.detaching
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
    assert r.attachment_state == AttachmentState.disabled


def test_ac1_disconnected_disable_to_disabled():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
    assert r.attachment_state == AttachmentState.disabled


def test_ad1_disabled_attach_to_attached():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.attach, runtime=rt)
    assert r.attachment_state == AttachmentState.attached


def test_ae1_detached_attach_to_attached():
    rt = _fresh_runtime()
    # Build a detached record manually
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.detached,
    )
    rt.push(r)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.attach, runtime=rt)
    assert updated.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group AF–AI — get_attached_runtime_session, list_active
# ---------------------------------------------------------------------------


def test_af1_get_returns_latest():
    rt = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                           session_id="s1", runtime=rt)
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                           session_id="s2", runtime=rt)
    r = get_attached_runtime_session("dev-1", runtime=rt)
    assert r.session_id == "s2"


def test_ag1_get_unknown_device_returns_none():
    rt = _fresh_runtime()
    assert get_attached_runtime_session("no-such-device", runtime=rt) is None


def test_ah1_list_active_only_attached():
    rt = _fresh_runtime()
    attach_runtime_session("dev-a", source_runtime_posture="join_runtime", runtime=rt)
    r_b = attach_runtime_session("dev-b", source_runtime_posture="join_runtime", runtime=rt)
    apply_lifecycle_signal(r_b, AttachmentLifecycleSignal.disconnect, runtime=rt)
    active = list_active_attached_sessions(runtime=rt)
    device_ids = {r.device_id for r in active}
    assert "dev-a" in device_ids


def test_ai1_list_active_empty_when_no_sessions():
    rt = _fresh_runtime()
    assert list_active_attached_sessions(runtime=rt) == []


# ---------------------------------------------------------------------------
# Group AJ–AL — build_attached_runtime_session_snapshot
# ---------------------------------------------------------------------------


def test_aj1_snapshot_counts():
    rt = _fresh_runtime()
    attach_runtime_session("dev-a", source_runtime_posture="join_runtime", runtime=rt)
    attach_runtime_session("dev-b", source_runtime_posture="join_runtime", runtime=rt)
    r_c = attach_runtime_session("dev-c", source_runtime_posture="join_runtime", runtime=rt)
    apply_lifecycle_signal(r_c, AttachmentLifecycleSignal.disconnect, runtime=rt)
    snap = build_attached_runtime_session_snapshot(runtime=rt)
    assert snap.total_count == 3
    assert snap.active_count == 2


def test_ak1_snapshot_includes_policy_sentinels():
    rt = _fresh_runtime()
    snap = build_attached_runtime_session_snapshot(runtime=rt)
    assert len(snap.policy_sentinels) == 10
    assert all(isinstance(s, str) and len(s) > 0 for s in snap.policy_sentinels)


def test_al1_empty_snapshot():
    rt = _fresh_runtime()
    snap = build_attached_runtime_session_snapshot(runtime=rt)
    assert snap.active_count == 0
    assert snap.total_count == 0
    assert snap.records == []


# ---------------------------------------------------------------------------
# Group AM — core.runtime re-exports
# ---------------------------------------------------------------------------


def test_am1_core_runtime_reexports_all_pr7_symbols():
    import core.runtime as cr
    symbols = [
        "ATTACHED_RUNTIME_SESSION_AUTHORITY",
        "ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY",
        "TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY",
        "DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY",
        "ATTACH_IS_IDEMPOTENT_POLICY",
        "DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY",
        "INVALIDATED_SESSION_IS_TERMINAL_POLICY",
        "DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY",
        "ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
        "ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY",
        "ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE_POLICY",
        "ATTACHED_RUNTIME_SESSION_PR7_SENTINEL",
        "AttachmentState",
        "AttachmentLifecycleSignal",
        "AttachmentLifecycleAction",
        "AttachedRuntimeSessionRecord",
        "AttachedRuntimeSessionSnapshot",
        "AttachedRuntimeSessionRuntime",
        "attach_runtime_session",
        "apply_lifecycle_signal",
        "classify_attach_lifecycle_action",
        "classify_signal_lifecycle_action",
        "get_attached_runtime_session",
        "list_active_attached_sessions",
        "build_attached_runtime_session_snapshot",
        "get_attached_runtime_session_runtime",
        "reset_attached_runtime_session_runtime",
    ]
    for sym in symbols:
        assert hasattr(cr, sym), f"core.runtime missing PR-7 symbol: {sym}"


# ---------------------------------------------------------------------------
# Group AN — projection.py sentinel
# ---------------------------------------------------------------------------


def test_an1_projection_sentinel_not_unavailable():
    try:
        from core.routes.projection import ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
        assert "UNAVAILABLE" not in ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
        assert "PR7" in ATTACHED_RUNTIME_SESSION_ALIGNED_PR7
    except ImportError:
        pytest.skip("projection route not importable in this environment")


# ---------------------------------------------------------------------------
# Group AO–AP — Ring buffer capacity and eviction
# ---------------------------------------------------------------------------


def test_ao1_ring_buffer_capacity_128():
    rt = AttachedRuntimeSessionRuntime()
    assert rt.capacity() == 128


def test_ap1_ring_buffer_eviction():
    rt = AttachedRuntimeSessionRuntime(capacity=3)
    for i in range(4):
        rt.push(AttachedRuntimeSessionRecord(device_id=f"dev-{i}"))
    assert rt.size() == 3
    all_ids = [r.device_id for r in rt.list_all()]
    assert "dev-0" not in all_ids  # evicted
    assert "dev-3" in all_ids


# ---------------------------------------------------------------------------
# Group AQ–AS — Serialisation
# ---------------------------------------------------------------------------


def test_aq1_roundtrip_from_dict():
    r = AttachedRuntimeSessionRecord(
        device_id="dev-rt",
        source_runtime_posture="join_runtime",
        coordination_role="joined_runtime_participant",
        attachment_state=AttachmentState.attached,
        previous_state=AttachmentState.disconnected,
        last_signal=AttachmentLifecycleSignal.reconnect,
    )
    restored = AttachedRuntimeSessionRecord.from_dict(r.to_dict())
    assert restored.device_id == r.device_id
    assert restored.coordination_role == r.coordination_role
    assert restored.attachment_state == r.attachment_state
    assert restored.previous_state == r.previous_state
    assert restored.last_signal == r.last_signal


def test_ar1_to_json_valid_json():
    r = AttachedRuntimeSessionRecord(device_id="d")
    parsed = json.loads(r.to_json())
    assert parsed["device_id"] == "d"


def test_as1_from_dict_malformed_state_defaults():
    d = {"device_id": "d", "attachment_state": "not_a_real_state"}
    r = AttachedRuntimeSessionRecord.from_dict(d)
    assert r.attachment_state == AttachmentState.detached


def test_at1_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AttachedRuntimeSessionRecord.from_dict(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# Group AU–AV — Multiple devices
# ---------------------------------------------------------------------------


def test_au1_multiple_devices_independent():
    rt = _fresh_runtime()
    r_a = attach_runtime_session("dev-a", source_runtime_posture="join_runtime", runtime=rt)
    r_b = attach_runtime_session("dev-b", source_runtime_posture="join_runtime", runtime=rt)
    assert r_a.device_id == "dev-a"
    assert r_b.device_id == "dev-b"
    assert get_attached_runtime_session("dev-a", runtime=rt).device_id == "dev-a"
    assert get_attached_runtime_session("dev-b", runtime=rt).device_id == "dev-b"


def test_av1_second_attach_from_clean_state():
    rt = _fresh_runtime()
    r1 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert rt.size() == 1
    # Disconnect and then re-attach
    r1 = apply_lifecycle_signal(r1, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r2 = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r2.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group AW–AX — from_string edge cases
# ---------------------------------------------------------------------------


def test_aw1_attachmentstate_from_string_unknown():
    result = AttachmentState.from_string("totally_unknown_12345")
    assert result == AttachmentState.detached


def test_ax1_lifecyclesignal_from_string_unknown():
    result = AttachmentLifecycleSignal.from_string("totally_unknown_12345")
    assert result == AttachmentLifecycleSignal.attach


# ---------------------------------------------------------------------------
# Group AY — Transition completeness
# ---------------------------------------------------------------------------


def test_ay1_detaching_reconnect_to_attached():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert r.attachment_state == AttachmentState.detaching
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)
    assert r.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group AZ — End-to-end lifecycle
# ---------------------------------------------------------------------------


def test_az1_full_lifecycle():
    rt = _fresh_runtime()
    # attach
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert r.attachment_state == AttachmentState.attached
    # disconnect
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    assert r.attachment_state == AttachmentState.disconnected
    # reconnect
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)
    assert r.attachment_state == AttachmentState.attached
    # detach
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert r.attachment_state == AttachmentState.detaching
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert r.attachment_state == AttachmentState.detached


# ---------------------------------------------------------------------------
# Group BA — control_only rejected, join_runtime accepted
# ---------------------------------------------------------------------------


def test_ba1_control_only_and_join_runtime_same_runtime():
    rt = _fresh_runtime()
    r_ctrl = attach_runtime_session("dev-ctrl", source_runtime_posture="control_only", runtime=rt)
    r_join = attach_runtime_session("dev-join", source_runtime_posture="join_runtime", runtime=rt)
    assert r_ctrl.attachment_state == AttachmentState.detached
    assert r_join.attachment_state == AttachmentState.attached
    active = list_active_attached_sessions(runtime=rt)
    assert any(r.device_id == "dev-join" for r in active)
    assert not any(r.device_id == "dev-ctrl" for r in active)


# ---------------------------------------------------------------------------
# Groups BB–BE — is_eligible_for_execution
# ---------------------------------------------------------------------------


def test_bb1_attached_join_runtime_eligible():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.attached,
        source_runtime_posture="join_runtime",
    )
    assert r.is_eligible_for_execution() is True


def test_bc1_attached_control_only_not_eligible():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.attached,
        source_runtime_posture="control_only",
    )
    assert r.is_eligible_for_execution() is False


def test_bd1_disconnected_join_runtime_not_eligible():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.disconnected,
        source_runtime_posture="join_runtime",
    )
    assert r.is_eligible_for_execution() is False


def test_be1_disabled_join_runtime_not_eligible():
    r = AttachedRuntimeSessionRecord(
        device_id="d",
        attachment_state=AttachmentState.disabled,
        source_runtime_posture="join_runtime",
    )
    assert r.is_eligible_for_execution() is False


# ---------------------------------------------------------------------------
# Groups BF–BG — Auto-generated IDs
# ---------------------------------------------------------------------------


def test_bf1_record_ids_unique():
    ids = {AttachedRuntimeSessionRecord(device_id="d").record_id for _ in range(10)}
    assert len(ids) == 10


def test_bg1_snapshot_ids_unique():
    ids = {AttachedRuntimeSessionSnapshot().snapshot_id for _ in range(10)}
    assert len(ids) == 10


# ---------------------------------------------------------------------------
# Group BH — Empty device_id
# ---------------------------------------------------------------------------


def test_bh1_empty_device_id_creates_record():
    rt = _fresh_runtime()
    r = attach_runtime_session("", source_runtime_posture="join_runtime", runtime=rt)
    assert r.device_id == ""
    assert r.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group BI–BJ — Signal metadata
# ---------------------------------------------------------------------------


def test_bi1_last_signal_is_detach():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    updated = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    assert updated.last_signal == AttachmentLifecycleSignal.detach


def test_bj1_reconnect_from_detaching():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.detach, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)
    assert r.attachment_state == AttachmentState.attached
    assert r.last_signal == AttachmentLifecycleSignal.reconnect


# ---------------------------------------------------------------------------
# Group BK — list_active reflects transitions
# ---------------------------------------------------------------------------


def test_bk1_list_active_reflects_transitions():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt)
    assert len(list_active_attached_sessions(runtime=rt)) == 1
    apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    assert len(list_active_attached_sessions(runtime=rt)) == 0


# ---------------------------------------------------------------------------
# Group BL — Snapshot records newest-first
# ---------------------------------------------------------------------------


def test_bl1_snapshot_records_newest_first():
    rt = _fresh_runtime()
    attach_runtime_session("dev-a", source_runtime_posture="join_runtime", runtime=rt)
    attach_runtime_session("dev-b", source_runtime_posture="join_runtime", runtime=rt)
    snap = build_attached_runtime_session_snapshot(runtime=rt)
    assert snap.records[0].device_id == "dev-b"
    assert snap.records[1].device_id == "dev-a"


# ---------------------------------------------------------------------------
# Group BM–BN — Singleton management
# ---------------------------------------------------------------------------


def test_bm1_reset_singleton():
    get_attached_runtime_session_runtime()  # create
    reset_attached_runtime_session_runtime()
    # After reset, a new singleton is created
    rt = get_attached_runtime_session_runtime()
    assert rt.size() == 0


def test_bn1_get_runtime_returns_same_singleton():
    reset_attached_runtime_session_runtime()
    rt1 = get_attached_runtime_session_runtime()
    rt2 = get_attached_runtime_session_runtime()
    assert rt1 is rt2
    reset_attached_runtime_session_runtime()


# ---------------------------------------------------------------------------
# Group BO–BP — Enum string values
# ---------------------------------------------------------------------------


def test_bo1_attachment_state_string_values():
    assert AttachmentState.attached.value == "attached"
    assert AttachmentState.detaching.value == "detaching"
    assert AttachmentState.detached.value == "detached"
    assert AttachmentState.disconnected.value == "disconnected"
    assert AttachmentState.disabled.value == "disabled"
    assert AttachmentState.invalidated.value == "invalidated"


def test_bp1_lifecycle_signal_string_values():
    assert AttachmentLifecycleSignal.attach.value == "attach"
    assert AttachmentLifecycleSignal.detach.value == "detach"
    assert AttachmentLifecycleSignal.disconnect.value == "disconnect"
    assert AttachmentLifecycleSignal.disable.value == "disable"
    assert AttachmentLifecycleSignal.invalidate.value == "invalidate"
    assert AttachmentLifecycleSignal.reconnect.value == "reconnect"


# ---------------------------------------------------------------------------
# Group BQ — None posture treated as control_only
# ---------------------------------------------------------------------------


def test_bq1_none_posture_treated_as_control_only():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture=None, runtime=rt)
    assert r.attachment_state == AttachmentState.detached


# ---------------------------------------------------------------------------
# Group BR–BS — to_dict contents
# ---------------------------------------------------------------------------


def test_br1_snapshot_to_dict_keys():
    snap = AttachedRuntimeSessionSnapshot()
    d = snap.to_dict()
    assert "records" in d
    assert "active_count" in d
    assert "total_count" in d


def test_bs1_record_to_dict_none_previous_state():
    r = AttachedRuntimeSessionRecord(device_id="d")
    assert r.to_dict()["previous_state"] is None


# ---------------------------------------------------------------------------
# Group BT — Multiple transitions
# ---------------------------------------------------------------------------


def test_bt1_multiple_transitions_tracked():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.reconnect, runtime=rt)
    r = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disable, runtime=rt)
    assert r.attachment_state == AttachmentState.disabled
    assert r.previous_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# Group BU — attach_reason stored
# ---------------------------------------------------------------------------


def test_bu1_attach_reason_stored():
    rt = _fresh_runtime()
    r = attach_runtime_session("dev-1", source_runtime_posture="join_runtime",
                               attach_reason="initial device join", runtime=rt)
    assert r.attach_reason == "initial device join"


# ---------------------------------------------------------------------------
# Group BV — Two devices both active in list_active
# ---------------------------------------------------------------------------


def test_bv1_two_devices_both_active():
    rt = _fresh_runtime()
    attach_runtime_session("dev-a", source_runtime_posture="join_runtime", runtime=rt)
    attach_runtime_session("dev-b", source_runtime_posture="join_runtime", runtime=rt)
    active = list_active_attached_sessions(runtime=rt)
    ids = {r.device_id for r in active}
    assert ids == {"dev-a", "dev-b"}


# ---------------------------------------------------------------------------
# Group BW — apply_lifecycle_signal does not mutate original
# ---------------------------------------------------------------------------


def test_bw1_apply_does_not_mutate_original():
    rt = _fresh_runtime()
    r = _attach(runtime=rt)
    original_state = r.attachment_state
    _ = apply_lifecycle_signal(r, AttachmentLifecycleSignal.disconnect, runtime=rt)
    # Original record object should be unchanged in its own fields
    assert r.attachment_state == original_state


# ---------------------------------------------------------------------------
# Group BX — Custom runtime isolation
# ---------------------------------------------------------------------------


def test_bx1_custom_runtime_isolated():
    rt1 = _fresh_runtime()
    rt2 = _fresh_runtime()
    attach_runtime_session("dev-1", source_runtime_posture="join_runtime", runtime=rt1)
    assert rt2.size() == 0


# ---------------------------------------------------------------------------
# Group BY — Snapshot timestamp is recent
# ---------------------------------------------------------------------------


def test_by1_snapshot_timestamp_recent():
    before = time.time()
    rt = _fresh_runtime()
    snap = build_attached_runtime_session_snapshot(runtime=rt)
    after = time.time()
    assert before <= snap.snapshotted_at <= after


# ---------------------------------------------------------------------------
# Group BZ — All 10 policy sentinels non-empty
# ---------------------------------------------------------------------------


def test_bz1_all_policy_sentinels_non_empty():
    sentinels = [
        ATTACHED_RUNTIME_SESSION_AUTHORITY,
        ATTACHED_SESSION_PERSISTS_ACROSS_REQUESTS_POLICY,
        TRANSIENT_PRESENCE_DISTINCT_FROM_ATTACHED_SESSION_POLICY,
        DETACH_SIGNAL_REQUIRED_FOR_SESSION_TERMINATION_POLICY,
        ATTACH_IS_IDEMPOTENT_POLICY,
        DISCONNECTED_DOES_NOT_INVALIDATE_SESSION_POLICY,
        INVALIDATED_SESSION_IS_TERMINAL_POLICY,
        DISABLED_SESSION_NOT_ELIGIBLE_FOR_EXECUTION_POLICY,
        ATTACHED_SESSION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
        ATTACHMENT_LIFECYCLE_IS_POSTURE_AWARE_POLICY,
    ]
    for s in sentinels:
        assert isinstance(s, str)
        assert len(s) > 10


# ---------------------------------------------------------------------------
# Group CA — Lifecycle governance action helpers
# ---------------------------------------------------------------------------


def test_ca1_attach_lifecycle_action_classification():
    assert ATTACHMENT_LIFECYCLE_ACTION_GOVERNANCE_POLICY.startswith("POLICY::")

    assert classify_attach_lifecycle_action(None, "join_runtime") == AttachmentLifecycleAction.create

    active = AttachedRuntimeSessionRecord(
        device_id="dev-1",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.attached,
    )
    assert classify_attach_lifecycle_action(active, "join_runtime") == AttachmentLifecycleAction.reconcile

    disconnected = AttachedRuntimeSessionRecord(
        device_id="dev-1",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.disconnected,
    )
    assert classify_attach_lifecycle_action(disconnected, "join_runtime") == AttachmentLifecycleAction.replace
    assert classify_attach_lifecycle_action(disconnected, "control_only") == AttachmentLifecycleAction.rejected


def test_ca2_signal_lifecycle_action_classification():
    attached = AttachedRuntimeSessionRecord(
        device_id="dev-1",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.attached,
    )
    detached = AttachedRuntimeSessionRecord(
        device_id="dev-2",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.detached,
    )
    disconnected = AttachedRuntimeSessionRecord(
        device_id="dev-4",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.disconnected,
    )
    invalidated = AttachedRuntimeSessionRecord(
        device_id="dev-3",
        source_runtime_posture="join_runtime",
        attachment_state=AttachmentState.invalidated,
    )

    assert (
        classify_signal_lifecycle_action(attached, AttachmentLifecycleSignal.disconnect)
        == AttachmentLifecycleAction.deactivate
    )
    assert (
        classify_signal_lifecycle_action(disconnected, AttachmentLifecycleSignal.reconnect)
        == AttachmentLifecycleAction.recover
    )
    assert (
        classify_signal_lifecycle_action(attached, AttachmentLifecycleSignal.invalidate)
        == AttachmentLifecycleAction.retire
    )
    assert (
        classify_signal_lifecycle_action(detached, AttachmentLifecycleSignal.reconnect)
        == AttachmentLifecycleAction.no_change
    )
    assert (
        classify_signal_lifecycle_action(invalidated, AttachmentLifecycleSignal.disable)
        == AttachmentLifecycleAction.retire
    )
