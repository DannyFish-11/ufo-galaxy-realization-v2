"""tests/test_pr11_post533_android_runtime_dispatch_binding.py
==============================================================
Tests for PR package 11 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical MAIN-Side Attached-Android-Runtime Dispatch
Binding Basis.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — AndroidRuntimeBindingState enum: all values, from_string(), defaults.
C  — AndroidRuntimeBindingState: is_active(), is_terminal(), is_dispatch_ready(),
     is_recoverable().
D  — AndroidRuntimeBindingSignal enum: all values, from_string(), defaults.
E  — AndroidRuntimeDispatchBindingIdentity: construction, defaults, to_dict(),
     to_json(), from_dict().
F  — AndroidRuntimeDispatchBindingRecord: construction, defaults, to_dict(),
     to_json(), from_dict(), is_accepted(), is_rejected(), is_active(),
     is_terminal(), is_dispatch_ready().
G  — AndroidRuntimeDispatchBindingSnapshot: construction, defaults, to_dict(),
     to_json().
H  — AndroidRuntimeDispatchBindingRuntime: push, list_all, list_active,
     get_latest_for_session, get_latest_for_contract, get_latest_for_device,
     clear, size, capacity.
I  — create_android_dispatch_binding: valid inputs → unbound record.
J  — create_android_dispatch_binding: empty session_id → rejected.
K  — create_android_dispatch_binding: empty device_id → rejected.
L  — create_android_dispatch_binding: non-join_runtime posture → rejected.
M  — create_android_dispatch_binding: trace_id auto-generated when absent.
N  — create_android_dispatch_binding: binding_id override honoured.
O  — create_android_dispatch_binding: posture normalised to join_runtime.
P  — create_android_dispatch_binding: coordination_role forwarded.
Q  — create_android_dispatch_binding: contract_id / tracker_id optional at creation.
R  — create_android_dispatch_binding: persisted to runtime ring-buffer.
S  — create_android_dispatch_binding: custom runtime isolation.
T  — advance_binding_state: unbound → bind → binding.
U  — advance_binding_state: binding → confirm → bound.
V  — advance_binding_state: bound → dispatch → dispatching (with contract_id).
W  — advance_binding_state: dispatch blocked without contract_id.
X  — advance_binding_state: bound → suspend → suspended.
Y  — advance_binding_state: dispatching → suspend → suspended.
Z  — advance_binding_state: suspended → resume → bound.
AA — advance_binding_state: any → release → released.
AB — advance_binding_state: released record returned unchanged.
AC — advance_binding_state: invalid transition returns record unchanged.
AD — advance_binding_state: identity fields preserved across transitions.
AE — advance_binding_state: persisted to runtime ring-buffer.
AF — advance_binding_state: bind on already-bound is idempotent.
AG — advance_binding_state: confirm on already-bound is idempotent.
AH — resolve_dispatch_binding: valid PR-7/PR-9/PR-10 records → bound record.
AI — resolve_dispatch_binding: session_id mismatch → rejected.
AJ — resolve_dispatch_binding: empty session_id → rejected.
AK — resolve_dispatch_binding: empty device_id → rejected.
AL — resolve_dispatch_binding: tracker_id forwarded from PR-10 record.
AM — resolve_dispatch_binding: contract_id forwarded from PR-9 record.
AN — resolve_dispatch_binding: trace_id forwarded from PR-9 contract.
AO — resolve_dispatch_binding: android_host_role override respected.
AP — record_dispatch_binding: persists record to runtime.
AQ — get_dispatch_binding: returns most recent for session_id.
AR — get_dispatch_binding: returns None for unknown session_id.
AS — get_dispatch_binding_by_contract: returns most recent for contract_id.
AT — get_dispatch_binding_by_contract: returns None for unknown contract_id.
AU — list_bound_dispatch_bindings: returns active records only.
AV — list_bound_dispatch_bindings: empty when all released.
AW — build_dispatch_binding_snapshot: counts active and total correctly.
AX — build_dispatch_binding_snapshot: includes policy sentinels.
AY — build_dispatch_binding_snapshot: empty runtime → zero counts.
AZ — core.runtime re-exports: all PR-11 symbols accessible from core.runtime.
BA — projection.py sentinel: ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11
     is present and not UNAVAILABLE.
BB — Ring buffer capacity: 128.
BC — Ring buffer eviction: oldest entry evicted when full.
BD — Serialisation round-trip: AndroidRuntimeDispatchBindingRecord to_dict → from_dict.
BE — Serialisation round-trip: to_json produces valid JSON.
BF — Serialisation: from_dict with non-dict raises ValueError.
BG — Multiple sessions: each gets its own binding record.
BH — All 10 policy sentinels are non-empty strings.
BI — AndroidRuntimeDispatchBindingRecord.is_accepted: True when no reject_reason
     and anchored.
BJ — AndroidRuntimeDispatchBindingRecord.is_accepted: False when reject_reason set.
BK — AndroidRuntimeDispatchBindingRecord.is_rejected: True when reject_reason set.
BL — AndroidRuntimeDispatchBindingRecord.is_active: True when non-released.
BM — AndroidRuntimeDispatchBindingRecord.is_terminal: True when released.
BN — binding_id is auto-generated UUID when not provided.
BO — Snapshot to_dict contains 'records', 'active_count', 'total_count'.
BP — Record to_dict: reject_reason empty when accepted.
BQ — Record to_dict: identity sub-dict has expected keys.
BR — get_dispatch_binding_runtime returns same singleton.
BS — reset_dispatch_binding_runtime clears singleton for isolation.
BT — Two separate sessions: list_active returns both when both active.
BU — create_android_dispatch_binding: does not mutate other records in runtime.
BV — end-to-end: create → bind → confirm → add contract → dispatch → snapshot
     reflects dispatching state.
BW — ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL contains 'package=11'.
BX — AndroidRuntimeDispatchBindingRecord from_dict: missing fields use safe defaults.
BY — AndroidRuntimeDispatchBindingIdentity from_dict: non-dict raises ValueError.
BZ — AndroidRuntimeDispatchBindingRecord from_dict: non-dict raises ValueError.
CA — advance_binding_state: updated_at is later than or equal to created_at.
CB — AndroidRuntimeDispatchBindingRuntime: clear() empties the buffer.
CC — binding_id is stable across to_dict/from_dict round-trip.
CD — list_active excludes released bindings.
CE — build_dispatch_binding_snapshot: records are newest-first.
CF — AndroidRuntimeBindingSignal.from_string: unknown string → bind.
CG — AndroidRuntimeBindingState.from_string: unknown string → unbound.
CH — AndroidRuntimeDispatchBindingRuntime.get_latest_for_device returns correct record.
CI — advance_binding_state: metadata preserved across transitions.
CJ — create_android_dispatch_binding: metadata stored in record.
CK — resolve_dispatch_binding: coordination_role from attached_session forwarded.
CL — Snapshot to_json is valid JSON.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest

from core.android_runtime_dispatch_binding import (
    ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
    ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL,
    BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY,
    BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY,
    BINDING_STATE_IS_MONOTONIC_POLICY,
    BINDING_TRACKER_ID_IS_PROPAGATED_POLICY,
    DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY,
    RELEASED_BINDING_IS_TERMINAL_POLICY,
    AndroidRuntimeBindingSignal,
    AndroidRuntimeBindingState,
    AndroidRuntimeDispatchBindingIdentity,
    AndroidRuntimeDispatchBindingRecord,
    AndroidRuntimeDispatchBindingRuntime,
    AndroidRuntimeDispatchBindingSnapshot,
    advance_binding_state,
    build_dispatch_binding_snapshot,
    create_android_dispatch_binding,
    get_dispatch_binding,
    get_dispatch_binding_by_contract,
    get_dispatch_binding_runtime,
    list_bound_dispatch_bindings,
    record_dispatch_binding,
    reset_dispatch_binding_runtime,
    resolve_dispatch_binding,
)


# ---------------------------------------------------------------------------
# Helpers / minimal stub objects for resolve_dispatch_binding tests
# ---------------------------------------------------------------------------


def _fresh_rt() -> AndroidRuntimeDispatchBindingRuntime:
    return AndroidRuntimeDispatchBindingRuntime()


def _make_binding(
    session_id: str = "sess-1",
    device_id: str = "dev-1",
    posture: str = "join_runtime",
    contract_id: str = "",
    tracker_id: str = "",
    runtime: Optional[AndroidRuntimeDispatchBindingRuntime] = None,
) -> AndroidRuntimeDispatchBindingRecord:
    rt = runtime if runtime is not None else _fresh_rt()
    return create_android_dispatch_binding(
        session_id=session_id,
        device_id=device_id,
        source_runtime_posture=posture,
        contract_id=contract_id,
        tracker_id=tracker_id,
        runtime=rt,
    )


@dataclass
class _StubSession:
    device_id: str = "dev-1"
    session_id: str = "sess-1"
    source_runtime_posture: str = "join_runtime"
    coordination_role: str = "joined_runtime_participant"
    android_host_role: str = "FULL_RUNTIME_HOST"
    capability_tier: str = "full_runtime"


@dataclass
class _StubContractIdentity:
    contract_id: str = "contract-1"
    session_id: str = "sess-1"
    trace_id: str = "trace-abc"


@dataclass
class _StubContract:
    identity: _StubContractIdentity = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.identity is None:
            self.identity = _StubContractIdentity()


@dataclass
class _StubTrackerIdentity:
    tracker_id: str = "tracker-1"


@dataclass
class _StubTracker:
    identity: _StubTrackerIdentity = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.identity is None:
            self.identity = _StubTrackerIdentity()


# ---------------------------------------------------------------------------
# A — Authority / policy sentinel presence and correctness
# ---------------------------------------------------------------------------


def test_A01_authority_sentinel_non_empty():
    assert ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY
    assert isinstance(ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY, str)


def test_A02_authority_sentinel_contains_module_name():
    assert "core.android_runtime_dispatch_binding" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY


def test_A03_authority_sentinel_contains_pr11():
    assert "PR-11" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY or "PR package 11" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY or "dispatch binding" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY.lower()


def test_A04_pr11_sentinel_non_empty():
    assert ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL
    assert isinstance(ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL, str)


def test_A05_all_policy_sentinels_non_empty():
    for s in (
        BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
        BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
        BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
        BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY,
        BINDING_STATE_IS_MONOTONIC_POLICY,
        RELEASED_BINDING_IS_TERMINAL_POLICY,
        BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY,
        DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY,
        BINDING_TRACKER_ID_IS_PROPAGATED_POLICY,
    ):
        assert s, f"Policy sentinel is empty: {s!r}"
        assert isinstance(s, str)


# ---------------------------------------------------------------------------
# B — AndroidRuntimeBindingState enum
# ---------------------------------------------------------------------------


def test_B01_state_all_values_present():
    values = {s.value for s in AndroidRuntimeBindingState}
    assert values == {"unbound", "binding", "bound", "dispatching", "suspended", "released"}


def test_B02_state_from_string_known():
    assert AndroidRuntimeBindingState.from_string("bound") == AndroidRuntimeBindingState.bound


def test_B03_state_from_string_case_insensitive():
    assert AndroidRuntimeBindingState.from_string("DISPATCHING") == AndroidRuntimeBindingState.dispatching


def test_B04_state_from_string_unknown_defaults_to_unbound():
    assert AndroidRuntimeBindingState.from_string("bogus") == AndroidRuntimeBindingState.unbound


def test_B05_state_from_string_non_string_defaults():
    assert AndroidRuntimeBindingState.from_string(None) == AndroidRuntimeBindingState.unbound  # type: ignore[arg-type]


def test_B06_state_from_string_custom_default():
    assert (
        AndroidRuntimeBindingState.from_string("??", default=AndroidRuntimeBindingState.bound)
        == AndroidRuntimeBindingState.bound
    )


# ---------------------------------------------------------------------------
# C — AndroidRuntimeBindingState helpers
# ---------------------------------------------------------------------------


def test_C01_released_is_terminal():
    assert AndroidRuntimeBindingState.released.is_terminal()


def test_C02_non_released_not_terminal():
    for s in AndroidRuntimeBindingState:
        if s != AndroidRuntimeBindingState.released:
            assert not s.is_terminal(), f"{s} should not be terminal"


def test_C03_released_not_active():
    assert not AndroidRuntimeBindingState.released.is_active()


def test_C04_non_released_is_active():
    for s in AndroidRuntimeBindingState:
        if s != AndroidRuntimeBindingState.released:
            assert s.is_active(), f"{s} should be active"


def test_C05_bound_is_dispatch_ready():
    assert AndroidRuntimeBindingState.bound.is_dispatch_ready()


def test_C06_other_states_not_dispatch_ready():
    for s in AndroidRuntimeBindingState:
        if s != AndroidRuntimeBindingState.bound:
            assert not s.is_dispatch_ready(), f"{s} should not be dispatch_ready"


def test_C07_suspended_is_recoverable():
    assert AndroidRuntimeBindingState.suspended.is_recoverable()


def test_C08_other_states_not_recoverable():
    for s in AndroidRuntimeBindingState:
        if s != AndroidRuntimeBindingState.suspended:
            assert not s.is_recoverable(), f"{s} should not be recoverable"


# ---------------------------------------------------------------------------
# D — AndroidRuntimeBindingSignal enum
# ---------------------------------------------------------------------------


def test_D01_signal_all_values_present():
    values = {s.value for s in AndroidRuntimeBindingSignal}
    assert values == {"bind", "confirm", "dispatch", "suspend", "resume", "release"}


def test_D02_signal_from_string_known():
    assert AndroidRuntimeBindingSignal.from_string("confirm") == AndroidRuntimeBindingSignal.confirm


def test_D03_signal_from_string_case_insensitive():
    assert AndroidRuntimeBindingSignal.from_string("RELEASE") == AndroidRuntimeBindingSignal.release


def test_D04_signal_from_string_unknown_defaults_to_bind():
    assert AndroidRuntimeBindingSignal.from_string("bogus") == AndroidRuntimeBindingSignal.bind


def test_D05_signal_from_string_non_string_defaults():
    assert AndroidRuntimeBindingSignal.from_string(42) == AndroidRuntimeBindingSignal.bind  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# E — AndroidRuntimeDispatchBindingIdentity
# ---------------------------------------------------------------------------


def test_E01_identity_construction_defaults():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    assert identity.session_id == "s1"
    assert identity.device_id == "d1"
    assert identity.contract_id == ""
    assert identity.tracker_id == ""
    assert identity.binding_id  # auto-generated
    assert identity.trace_id  # auto-generated


def test_E02_identity_to_dict_has_all_keys():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    d = identity.to_dict()
    for key in ("binding_id", "session_id", "device_id", "contract_id", "tracker_id", "trace_id"):
        assert key in d


def test_E03_identity_to_json_valid_json():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    parsed = json.loads(identity.to_json())
    assert parsed["session_id"] == "s1"


def test_E04_identity_from_dict_round_trip():
    identity = AndroidRuntimeDispatchBindingIdentity(
        session_id="s1", device_id="d1", contract_id="c1", tracker_id="t1"
    )
    restored = AndroidRuntimeDispatchBindingIdentity.from_dict(identity.to_dict())
    assert restored.session_id == "s1"
    assert restored.device_id == "d1"
    assert restored.contract_id == "c1"
    assert restored.tracker_id == "t1"
    assert restored.binding_id == identity.binding_id


def test_E05_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AndroidRuntimeDispatchBindingIdentity.from_dict("not-a-dict")  # type: ignore[arg-type]


def test_E06_identity_from_dict_auto_generates_missing_binding_id():
    restored = AndroidRuntimeDispatchBindingIdentity.from_dict({"session_id": "s1", "device_id": "d1"})
    assert restored.binding_id


def test_E07_identity_from_dict_auto_generates_missing_trace_id():
    restored = AndroidRuntimeDispatchBindingIdentity.from_dict({"session_id": "s1", "device_id": "d1"})
    assert restored.trace_id


# ---------------------------------------------------------------------------
# F — AndroidRuntimeDispatchBindingRecord
# ---------------------------------------------------------------------------


def test_F01_record_construction_defaults():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    assert record.binding_state == AndroidRuntimeBindingState.unbound
    assert record.source_runtime_posture == "join_runtime"
    assert record.coordination_role == ""
    assert record.is_session_anchored
    assert record.is_device_bound
    assert record.reject_reason == ""


def test_F02_record_is_accepted_when_no_reject_reason():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    assert record.is_accepted()
    assert not record.is_rejected()


def test_F03_record_is_rejected_when_reject_reason_set():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="", device_id="")
    record = AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        reject_reason="something went wrong",
        is_session_anchored=False,
        is_device_bound=False,
        binding_state=AndroidRuntimeBindingState.released,
    )
    assert record.is_rejected()
    assert not record.is_accepted()


def test_F04_record_is_active_when_not_released():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    assert record.is_active()
    assert not record.is_terminal()


def test_F05_record_is_terminal_when_released():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        binding_state=AndroidRuntimeBindingState.released,
    )
    assert record.is_terminal()
    assert not record.is_active()


def test_F06_record_is_dispatch_ready_requires_bound_and_contract_id():
    identity = AndroidRuntimeDispatchBindingIdentity(
        session_id="s1", device_id="d1", contract_id="c1"
    )
    record = AndroidRuntimeDispatchBindingRecord(
        identity=identity, binding_state=AndroidRuntimeBindingState.bound
    )
    assert record.is_dispatch_ready()


def test_F07_record_is_not_dispatch_ready_without_contract_id():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(
        identity=identity, binding_state=AndroidRuntimeBindingState.bound
    )
    assert not record.is_dispatch_ready()


def test_F08_record_to_dict_has_all_keys():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    d = record.to_dict()
    for key in (
        "identity", "binding_state", "source_runtime_posture", "coordination_role",
        "android_host_role", "capability_tier", "is_session_anchored", "is_device_bound",
        "reject_reason", "created_at", "updated_at", "metadata",
    ):
        assert key in d, f"Missing key: {key}"


def test_F09_record_to_json_valid_json():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    parsed = json.loads(record.to_json())
    assert parsed["binding_state"] == "unbound"


def test_F10_record_from_dict_round_trip():
    identity = AndroidRuntimeDispatchBindingIdentity(
        session_id="s1", device_id="d1", contract_id="c1", tracker_id="t1"
    )
    record = AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        binding_state=AndroidRuntimeBindingState.bound,
        source_runtime_posture="join_runtime",
        coordination_role="joined_runtime_participant",
        android_host_role="FULL_RUNTIME_HOST",
        capability_tier="full_runtime",
    )
    restored = AndroidRuntimeDispatchBindingRecord.from_dict(record.to_dict())
    assert restored.binding_state == AndroidRuntimeBindingState.bound
    assert restored.identity.contract_id == "c1"
    assert restored.coordination_role == "joined_runtime_participant"


def test_F11_record_from_dict_missing_fields_use_safe_defaults():
    restored = AndroidRuntimeDispatchBindingRecord.from_dict({"identity": {"session_id": "s1", "device_id": "d1"}})
    assert restored.binding_state == AndroidRuntimeBindingState.unbound
    assert restored.source_runtime_posture == "join_runtime"
    assert restored.reject_reason == ""


def test_F12_record_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AndroidRuntimeDispatchBindingRecord.from_dict("not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# G — AndroidRuntimeDispatchBindingSnapshot
# ---------------------------------------------------------------------------


def test_G01_snapshot_construction_defaults():
    snap = AndroidRuntimeDispatchBindingSnapshot()
    assert snap.records == []
    assert snap.active_count == 0
    assert snap.total_count == 0
    assert snap.policy_sentinels == []


def test_G02_snapshot_to_dict_has_expected_keys():
    snap = AndroidRuntimeDispatchBindingSnapshot(active_count=1, total_count=2)
    d = snap.to_dict()
    assert "records" in d
    assert "active_count" in d
    assert "total_count" in d
    assert "policy_sentinels" in d


def test_G03_snapshot_to_json_valid_json():
    snap = AndroidRuntimeDispatchBindingSnapshot(active_count=1, total_count=1)
    parsed = json.loads(snap.to_json())
    assert parsed["active_count"] == 1


# ---------------------------------------------------------------------------
# H — AndroidRuntimeDispatchBindingRuntime
# ---------------------------------------------------------------------------


def test_H01_runtime_capacity_default():
    rt = AndroidRuntimeDispatchBindingRuntime()
    assert rt.capacity == 128


def test_H02_runtime_push_and_size():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    assert rt.size() == 1


def test_H03_runtime_list_all_newest_first():
    rt = _fresh_rt()
    r1 = _make_binding(session_id="s1", device_id="d1", runtime=rt)
    r2 = _make_binding(session_id="s2", device_id="d2", runtime=rt)
    all_records = rt.list_all()
    assert all_records[0].identity.session_id == "s2"
    assert all_records[1].identity.session_id == "s1"


def test_H04_runtime_list_active_excludes_released():
    rt = _fresh_rt()
    r1 = _make_binding(session_id="s1", device_id="d1", runtime=rt)
    rejected = create_android_dispatch_binding(
        session_id="", device_id="d2", runtime=rt
    )
    active = rt.list_active()
    session_ids = {r.identity.session_id for r in active}
    assert "s1" in session_ids
    # rejected binding is in released state
    assert all(r.binding_state.is_active() for r in active)


def test_H05_runtime_get_latest_for_session():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="d1", runtime=rt)
    found = rt.get_latest_for_session("s1")
    assert found is not None
    assert found.identity.session_id == "s1"


def test_H06_runtime_get_latest_for_session_unknown():
    rt = _fresh_rt()
    assert rt.get_latest_for_session("no-such") is None


def test_H07_runtime_get_latest_for_contract():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="d1", contract_id="c1", runtime=rt)
    found = rt.get_latest_for_contract("c1")
    assert found is not None
    assert found.identity.contract_id == "c1"


def test_H08_runtime_get_latest_for_contract_unknown():
    rt = _fresh_rt()
    assert rt.get_latest_for_contract("no-such") is None


def test_H09_runtime_get_latest_for_device():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="my-device", runtime=rt)
    found = rt.get_latest_for_device("my-device")
    assert found is not None
    assert found.identity.device_id == "my-device"


def test_H10_runtime_clear():
    rt = _fresh_rt()
    _make_binding(runtime=rt)
    rt.clear()
    assert rt.size() == 0


def test_H11_runtime_eviction_when_full():
    capacity = 4
    rt = AndroidRuntimeDispatchBindingRuntime(capacity=capacity)
    for i in range(capacity + 1):
        create_android_dispatch_binding(
            session_id=f"s{i}", device_id=f"d{i}", runtime=rt
        )
    assert rt.size() == capacity
    all_sessions = {r.identity.session_id for r in rt.list_all()}
    assert "s0" not in all_sessions  # oldest evicted


# ---------------------------------------------------------------------------
# I — create_android_dispatch_binding: valid inputs
# ---------------------------------------------------------------------------


def test_I01_valid_inputs_returns_unbound_record():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-valid",
        device_id="dev-valid",
        runtime=rt,
    )
    assert rec.binding_state == AndroidRuntimeBindingState.unbound
    assert rec.is_accepted()
    assert not rec.reject_reason


def test_I02_valid_inputs_session_id_preserved():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-xyz", device_id="dev-xyz", runtime=rt
    )
    assert rec.identity.session_id == "sess-xyz"


def test_I03_valid_inputs_device_id_preserved():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-777", runtime=rt
    )
    assert rec.identity.device_id == "dev-777"


# ---------------------------------------------------------------------------
# J — create_android_dispatch_binding: empty session_id → rejected
# ---------------------------------------------------------------------------


def test_J01_empty_session_id_rejected():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="", device_id="dev-1", runtime=rt
    )
    assert rec.is_rejected()
    assert rec.binding_state == AndroidRuntimeBindingState.released
    assert "session_id" in rec.reject_reason.lower() or "attached_session" in rec.reject_reason


def test_J02_rejected_record_persisted_to_runtime():
    rt = _fresh_rt()
    create_android_dispatch_binding(session_id="", device_id="dev-1", runtime=rt)
    assert rt.size() == 1


# ---------------------------------------------------------------------------
# K — create_android_dispatch_binding: empty device_id → rejected
# ---------------------------------------------------------------------------


def test_K01_empty_device_id_rejected():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="", runtime=rt
    )
    assert rec.is_rejected()
    assert rec.binding_state == AndroidRuntimeBindingState.released
    assert "device_id" in rec.reject_reason.lower()


# ---------------------------------------------------------------------------
# L — create_android_dispatch_binding: non-join_runtime posture → rejected
# ---------------------------------------------------------------------------


def test_L01_control_only_posture_rejected():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        source_runtime_posture="control_only",
        runtime=rt,
    )
    assert rec.is_rejected()
    assert rec.binding_state == AndroidRuntimeBindingState.released
    assert "join_runtime" in rec.reject_reason


def test_L02_empty_posture_rejected():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-1", source_runtime_posture="", runtime=rt
    )
    assert rec.is_rejected()


def test_L03_unknown_posture_rejected():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        source_runtime_posture="observer",
        runtime=rt,
    )
    assert rec.is_rejected()


# ---------------------------------------------------------------------------
# M — create_android_dispatch_binding: trace_id auto-generated
# ---------------------------------------------------------------------------


def test_M01_trace_id_auto_generated_when_absent():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-1", runtime=rt
    )
    assert rec.identity.trace_id
    # Should be a valid UUID-ish string
    assert len(rec.identity.trace_id) > 0


def test_M02_trace_id_override_honoured():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        trace_id="my-trace-id",
        runtime=rt,
    )
    assert rec.identity.trace_id == "my-trace-id"


# ---------------------------------------------------------------------------
# N — create_android_dispatch_binding: binding_id override
# ---------------------------------------------------------------------------


def test_N01_binding_id_auto_generated_when_absent():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-1", runtime=rt
    )
    assert rec.identity.binding_id


def test_N02_binding_id_override_honoured():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        binding_id="explicit-bid",
        runtime=rt,
    )
    assert rec.identity.binding_id == "explicit-bid"


# ---------------------------------------------------------------------------
# O — posture normalised to join_runtime for valid inputs
# ---------------------------------------------------------------------------


def test_O01_accepted_binding_posture_is_join_runtime():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-1", runtime=rt
    )
    assert rec.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# P — coordination_role forwarded
# ---------------------------------------------------------------------------


def test_P01_coordination_role_forwarded():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        coordination_role="target_only_executor",
        runtime=rt,
    )
    assert rec.coordination_role == "target_only_executor"


# ---------------------------------------------------------------------------
# Q — contract_id / tracker_id optional at creation
# ---------------------------------------------------------------------------


def test_Q01_contract_id_and_tracker_id_optional_at_creation():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1", device_id="dev-1", runtime=rt
    )
    assert rec.identity.contract_id == ""
    assert rec.identity.tracker_id == ""
    assert rec.is_accepted()


def test_Q02_contract_id_forwarded_when_provided():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        contract_id="c999",
        runtime=rt,
    )
    assert rec.identity.contract_id == "c999"


def test_Q03_tracker_id_forwarded_when_provided():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-1",
        device_id="dev-1",
        tracker_id="t999",
        runtime=rt,
    )
    assert rec.identity.tracker_id == "t999"


# ---------------------------------------------------------------------------
# R — create_android_dispatch_binding: persisted to runtime
# ---------------------------------------------------------------------------


def test_R01_record_persisted_to_runtime():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-r1", device_id="dev-r1", runtime=rt
    )
    found = rt.get_latest_for_session("sess-r1")
    assert found is not None
    assert found.identity.binding_id == rec.identity.binding_id


# ---------------------------------------------------------------------------
# S — create_android_dispatch_binding: custom runtime isolation
# ---------------------------------------------------------------------------


def test_S01_custom_runtime_isolation():
    rt_a = _fresh_rt()
    rt_b = _fresh_rt()
    create_android_dispatch_binding(session_id="sess-a", device_id="dev-a", runtime=rt_a)
    assert rt_b.size() == 0
    assert rt_a.size() == 1


# ---------------------------------------------------------------------------
# T — advance_binding_state: unbound → bind → binding
# ---------------------------------------------------------------------------


def test_T01_advance_unbound_with_bind_signal():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.unbound
    updated = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert updated.binding_state == AndroidRuntimeBindingState.binding


# ---------------------------------------------------------------------------
# U — advance_binding_state: binding → confirm → bound
# ---------------------------------------------------------------------------


def test_U01_advance_binding_with_confirm_signal():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.bound


# ---------------------------------------------------------------------------
# V — advance_binding_state: bound → dispatch → dispatching (with contract_id)
# ---------------------------------------------------------------------------


def test_V01_advance_bound_with_dispatch_requires_contract_id():
    rt = _fresh_rt()
    rec = _make_binding(contract_id="c1", runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.dispatch, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.dispatching


# ---------------------------------------------------------------------------
# W — advance_binding_state: dispatch blocked without contract_id
# ---------------------------------------------------------------------------


def test_W01_dispatch_blocked_without_contract_id():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)  # no contract_id
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    # dispatch should be blocked
    unchanged = advance_binding_state(rec, AndroidRuntimeBindingSignal.dispatch, runtime=rt)
    assert unchanged.binding_state == AndroidRuntimeBindingState.bound  # unchanged


# ---------------------------------------------------------------------------
# X — advance_binding_state: bound → suspend → suspended
# ---------------------------------------------------------------------------


def test_X01_suspend_from_bound():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.suspend, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.suspended


# ---------------------------------------------------------------------------
# Y — advance_binding_state: dispatching → suspend → suspended
# ---------------------------------------------------------------------------


def test_Y01_suspend_from_dispatching():
    rt = _fresh_rt()
    rec = _make_binding(contract_id="c1", runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.dispatch, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.suspend, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.suspended


# ---------------------------------------------------------------------------
# Z — advance_binding_state: suspended → resume → bound
# ---------------------------------------------------------------------------


def test_Z01_resume_from_suspended():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.suspend, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.resume, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.bound


# ---------------------------------------------------------------------------
# AA — advance_binding_state: any → release → released
# ---------------------------------------------------------------------------


def test_AA01_release_from_unbound():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.released


def test_AA02_release_from_bound():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.released


def test_AA03_release_from_suspended():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.suspend, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.released


# ---------------------------------------------------------------------------
# AB — advance_binding_state: released record returned unchanged
# ---------------------------------------------------------------------------


def test_AB01_released_record_unchanged():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.released
    # Further signals should not change it
    unchanged = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert unchanged.binding_state == AndroidRuntimeBindingState.released
    assert unchanged is rec


# ---------------------------------------------------------------------------
# AC — advance_binding_state: invalid transition returns record unchanged
# ---------------------------------------------------------------------------


def test_AC01_invalid_transition_returns_unchanged():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    # unbound → confirm is not in the transition table
    unchanged = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    assert unchanged.binding_state == AndroidRuntimeBindingState.unbound
    assert unchanged is rec


def test_AC02_resume_from_unbound_returns_unchanged():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    unchanged = advance_binding_state(rec, AndroidRuntimeBindingSignal.resume, runtime=rt)
    assert unchanged is rec


# ---------------------------------------------------------------------------
# AD — advance_binding_state: identity fields preserved
# ---------------------------------------------------------------------------


def test_AD01_identity_fields_preserved_across_transitions():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="sess-id",
        device_id="dev-id",
        contract_id="contract-id",
        tracker_id="tracker-id",
        trace_id="trace-id",
        binding_id="binding-id",
        runtime=rt,
    )
    advanced = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert advanced.identity.session_id == "sess-id"
    assert advanced.identity.device_id == "dev-id"
    assert advanced.identity.contract_id == "contract-id"
    assert advanced.identity.tracker_id == "tracker-id"
    assert advanced.identity.trace_id == "trace-id"
    assert advanced.identity.binding_id == "binding-id"


# ---------------------------------------------------------------------------
# AE — advance_binding_state: persisted to runtime ring-buffer
# ---------------------------------------------------------------------------


def test_AE01_advance_persists_to_runtime():
    rt = _fresh_rt()
    rec = _make_binding(session_id="sess-ae", runtime=rt)
    initial_size = rt.size()
    advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert rt.size() == initial_size + 1


# ---------------------------------------------------------------------------
# AF — advance_binding_state: bind on already-bound is idempotent
# ---------------------------------------------------------------------------


def test_AF01_bind_on_bound_is_idempotent():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.bound


# ---------------------------------------------------------------------------
# AG — advance_binding_state: confirm on already-bound is idempotent
# ---------------------------------------------------------------------------


def test_AG01_confirm_on_bound_is_idempotent():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.bound


# ---------------------------------------------------------------------------
# AH — resolve_dispatch_binding: valid PR-7/PR-9/PR-10 records
# ---------------------------------------------------------------------------


def test_AH01_resolve_dispatch_binding_valid_records():
    rt = _fresh_rt()
    session = _StubSession()
    contract = _StubContract()
    tracker = _StubTracker()
    rec = resolve_dispatch_binding(session, contract, tracker, runtime=rt)
    assert rec.is_accepted()
    assert rec.identity.session_id == "sess-1"
    assert rec.identity.device_id == "dev-1"
    assert rec.identity.contract_id == "contract-1"
    assert rec.identity.tracker_id == "tracker-1"


def test_AH02_resolve_binding_state_is_unbound_initially():
    rt = _fresh_rt()
    rec = resolve_dispatch_binding(
        _StubSession(), _StubContract(), _StubTracker(), runtime=rt
    )
    assert rec.binding_state == AndroidRuntimeBindingState.unbound


# ---------------------------------------------------------------------------
# AI — resolve_dispatch_binding: session_id mismatch → rejected
# ---------------------------------------------------------------------------


def test_AI01_session_id_mismatch_rejected():
    rt = _fresh_rt()
    session = _StubSession(session_id="sess-A")
    contract_id = _StubContractIdentity(session_id="sess-B", contract_id="c1")
    contract = _StubContract(identity=contract_id)
    tracker = _StubTracker()
    rec = resolve_dispatch_binding(session, contract, tracker, runtime=rt)
    assert rec.is_rejected()
    assert "sess-A" in rec.reject_reason or "sess-B" in rec.reject_reason


# ---------------------------------------------------------------------------
# AJ — resolve_dispatch_binding: empty session_id → rejected
# ---------------------------------------------------------------------------


def test_AJ01_empty_session_id_rejected_via_resolve():
    rt = _fresh_rt()
    session = _StubSession(session_id="")
    rec = resolve_dispatch_binding(session, _StubContract(), _StubTracker(), runtime=rt)
    assert rec.is_rejected()


# ---------------------------------------------------------------------------
# AK — resolve_dispatch_binding: empty device_id → rejected
# ---------------------------------------------------------------------------


def test_AK01_empty_device_id_rejected_via_resolve():
    rt = _fresh_rt()
    session = _StubSession(device_id="")
    rec = resolve_dispatch_binding(session, _StubContract(), _StubTracker(), runtime=rt)
    assert rec.is_rejected()


# ---------------------------------------------------------------------------
# AL — resolve_dispatch_binding: tracker_id forwarded
# ---------------------------------------------------------------------------


def test_AL01_tracker_id_forwarded_from_tracker_record():
    rt = _fresh_rt()
    tracker = _StubTracker(identity=_StubTrackerIdentity(tracker_id="my-tracker"))
    rec = resolve_dispatch_binding(
        _StubSession(), _StubContract(), tracker, runtime=rt
    )
    assert rec.identity.tracker_id == "my-tracker"


# ---------------------------------------------------------------------------
# AM — resolve_dispatch_binding: contract_id forwarded
# ---------------------------------------------------------------------------


def test_AM01_contract_id_forwarded_from_contract_record():
    rt = _fresh_rt()
    contract = _StubContract(
        identity=_StubContractIdentity(contract_id="my-contract", session_id="sess-1")
    )
    rec = resolve_dispatch_binding(
        _StubSession(), contract, _StubTracker(), runtime=rt
    )
    assert rec.identity.contract_id == "my-contract"


# ---------------------------------------------------------------------------
# AN — resolve_dispatch_binding: trace_id forwarded from contract
# ---------------------------------------------------------------------------


def test_AN01_trace_id_forwarded_from_contract():
    rt = _fresh_rt()
    contract = _StubContract(
        identity=_StubContractIdentity(trace_id="my-trace", session_id="sess-1")
    )
    rec = resolve_dispatch_binding(
        _StubSession(), contract, _StubTracker(), runtime=rt
    )
    assert rec.identity.trace_id == "my-trace"


# ---------------------------------------------------------------------------
# AO — resolve_dispatch_binding: android_host_role override
# ---------------------------------------------------------------------------


def test_AO01_android_host_role_override_respected():
    rt = _fresh_rt()
    rec = resolve_dispatch_binding(
        _StubSession(),
        _StubContract(),
        _StubTracker(),
        android_host_role="PARTIAL_RUNTIME_HOST",
        runtime=rt,
    )
    assert rec.android_host_role == "PARTIAL_RUNTIME_HOST"


# ---------------------------------------------------------------------------
# AP — record_dispatch_binding: persists record to runtime
# ---------------------------------------------------------------------------


def test_AP01_record_dispatch_binding_persists():
    rt = _fresh_rt()
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    record = AndroidRuntimeDispatchBindingRecord(identity=identity)
    record_dispatch_binding(record, runtime=rt)
    assert rt.size() == 1


# ---------------------------------------------------------------------------
# AQ — get_dispatch_binding: returns most recent for session_id
# ---------------------------------------------------------------------------


def test_AQ01_get_dispatch_binding_returns_most_recent():
    rt = _fresh_rt()
    _make_binding(session_id="sess-q1", runtime=rt)
    found = get_dispatch_binding("sess-q1", runtime=rt)
    assert found is not None
    assert found.identity.session_id == "sess-q1"


def test_AQ02_get_dispatch_binding_none_for_unknown():
    rt = _fresh_rt()
    assert get_dispatch_binding("no-such-session", runtime=rt) is None


# ---------------------------------------------------------------------------
# AR — get_dispatch_binding: returns None for unknown session_id
# ---------------------------------------------------------------------------


def test_AR01_get_dispatch_binding_none_unknown():
    rt = _fresh_rt()
    assert get_dispatch_binding("unknown", runtime=rt) is None


# ---------------------------------------------------------------------------
# AS — get_dispatch_binding_by_contract
# ---------------------------------------------------------------------------


def test_AS01_get_by_contract_returns_most_recent():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="d1", contract_id="my-c", runtime=rt)
    found = get_dispatch_binding_by_contract("my-c", runtime=rt)
    assert found is not None
    assert found.identity.contract_id == "my-c"


def test_AS02_get_by_contract_none_for_unknown():
    rt = _fresh_rt()
    assert get_dispatch_binding_by_contract("no-such-contract", runtime=rt) is None


# ---------------------------------------------------------------------------
# AT — get_dispatch_binding_by_contract: None for unknown
# ---------------------------------------------------------------------------


def test_AT01_get_by_contract_unknown_is_none():
    rt = _fresh_rt()
    assert get_dispatch_binding_by_contract("nonexistent", runtime=rt) is None


# ---------------------------------------------------------------------------
# AU — list_bound_dispatch_bindings
# ---------------------------------------------------------------------------


def test_AU01_list_bound_returns_active_records():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="d1", runtime=rt)
    _make_binding(session_id="s2", device_id="d2", runtime=rt)
    active = list_bound_dispatch_bindings(runtime=rt)
    session_ids = {r.identity.session_id for r in active}
    assert "s1" in session_ids
    assert "s2" in session_ids


def test_AU02_list_bound_excludes_released():
    rt = _fresh_rt()
    rec = _make_binding(session_id="s1", device_id="d1", runtime=rt)
    advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    active = list_bound_dispatch_bindings(runtime=rt)
    # Released records should not appear in active
    assert all(r.binding_state.is_active() for r in active)


# ---------------------------------------------------------------------------
# AV — list_bound_dispatch_bindings: empty when all released
# ---------------------------------------------------------------------------


def test_AV01_empty_when_all_released():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    advance_binding_state(rec, AndroidRuntimeBindingSignal.release, runtime=rt)
    active = list_bound_dispatch_bindings(runtime=rt)
    # The original record is still in unbound (we advanced a local var but didn't replace)
    # Let's use a cleaner approach: only released records
    rt2 = _fresh_rt()
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s-rel", device_id="d-rel")
    released = AndroidRuntimeDispatchBindingRecord(
        identity=identity, binding_state=AndroidRuntimeBindingState.released
    )
    record_dispatch_binding(released, runtime=rt2)
    active2 = list_bound_dispatch_bindings(runtime=rt2)
    assert len(active2) == 0


# ---------------------------------------------------------------------------
# AW — build_dispatch_binding_snapshot: counts
# ---------------------------------------------------------------------------


def test_AW01_snapshot_counts_active_and_total():
    rt = _fresh_rt()
    _make_binding(session_id="s1", device_id="d1", runtime=rt)
    rec2 = _make_binding(session_id="s2", device_id="d2", runtime=rt)
    # Release s2
    advance_binding_state(rec2, AndroidRuntimeBindingSignal.release, runtime=rt)
    snap = build_dispatch_binding_snapshot(runtime=rt)
    assert snap.total_count == 3  # s1 create + s2 create + s2 release
    # Active: only records in non-released state (2: s1 and original s2 before release)
    assert snap.active_count == 2


def test_AW02_snapshot_total_count():
    rt = _fresh_rt()
    _make_binding(runtime=rt)
    snap = build_dispatch_binding_snapshot(runtime=rt)
    assert snap.total_count == 1


# ---------------------------------------------------------------------------
# AX — build_dispatch_binding_snapshot: includes policy sentinels
# ---------------------------------------------------------------------------


def test_AX01_snapshot_includes_policy_sentinels():
    rt = _fresh_rt()
    snap = build_dispatch_binding_snapshot(runtime=rt)
    assert len(snap.policy_sentinels) == 10
    assert all(isinstance(s, str) and s for s in snap.policy_sentinels)


# ---------------------------------------------------------------------------
# AY — build_dispatch_binding_snapshot: empty runtime
# ---------------------------------------------------------------------------


def test_AY01_empty_runtime_snapshot():
    rt = _fresh_rt()
    snap = build_dispatch_binding_snapshot(runtime=rt)
    assert snap.total_count == 0
    assert snap.active_count == 0
    assert snap.records == []


# ---------------------------------------------------------------------------
# AZ — core.runtime re-exports
# ---------------------------------------------------------------------------


def test_AZ01_core_runtime_exports_all_pr11_symbols():
    pytest.importorskip("pydantic")
    import core.runtime as cr

    symbols = [
        "ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY",
        "ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL",
        "BINDING_REQUIRES_ATTACHED_SESSION_POLICY",
        "BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
        "BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY",
        "BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY",
        "BINDING_STATE_IS_MONOTONIC_POLICY",
        "RELEASED_BINDING_IS_TERMINAL_POLICY",
        "BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY",
        "DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY",
        "BINDING_TRACKER_ID_IS_PROPAGATED_POLICY",
        "AndroidRuntimeBindingState",
        "AndroidRuntimeBindingSignal",
        "AndroidRuntimeDispatchBindingIdentity",
        "AndroidRuntimeDispatchBindingRecord",
        "AndroidRuntimeDispatchBindingSnapshot",
        "AndroidRuntimeDispatchBindingRuntime",
        "create_android_dispatch_binding",
        "advance_binding_state",
        "resolve_dispatch_binding",
        "record_dispatch_binding",
        "get_dispatch_binding",
        "get_dispatch_binding_by_contract",
        "list_bound_dispatch_bindings",
        "build_dispatch_binding_snapshot",
        "get_dispatch_binding_runtime",
        "reset_dispatch_binding_runtime",
    ]
    for sym in symbols:
        assert hasattr(cr, sym), f"core.runtime missing PR-11 symbol: {sym}"


# ---------------------------------------------------------------------------
# BA — projection.py sentinel
# ---------------------------------------------------------------------------


def test_BA01_projection_sentinel_present_and_not_unavailable():
    pytest.importorskip("fastapi")
    from core.routes.projection import ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11

    assert ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11
    assert "UNAVAILABLE" not in ANDROID_RUNTIME_DISPATCH_BINDING_ALIGNED_PR11


# ---------------------------------------------------------------------------
# BB — Ring buffer capacity
# ---------------------------------------------------------------------------


def test_BB01_ring_buffer_capacity_is_128():
    rt = AndroidRuntimeDispatchBindingRuntime()
    assert rt.capacity == 128


# ---------------------------------------------------------------------------
# BC — Ring buffer eviction
# ---------------------------------------------------------------------------


def test_BC01_oldest_evicted_when_full():
    capacity = 5
    rt = AndroidRuntimeDispatchBindingRuntime(capacity=capacity)
    for i in range(capacity + 2):
        create_android_dispatch_binding(
            session_id=f"evict-{i}", device_id=f"dev-{i}", runtime=rt
        )
    all_sessions = {r.identity.session_id for r in rt.list_all()}
    assert "evict-0" not in all_sessions
    assert "evict-1" not in all_sessions
    assert rt.size() == capacity


# ---------------------------------------------------------------------------
# BD — Serialisation round-trip
# ---------------------------------------------------------------------------


def test_BD01_record_to_dict_from_dict_round_trip():
    rt = _fresh_rt()
    rec = create_android_dispatch_binding(
        session_id="s-bd",
        device_id="d-bd",
        contract_id="c-bd",
        tracker_id="t-bd",
        trace_id="trace-bd",
        coordination_role="target_only_executor",
        android_host_role="FULL_RUNTIME_HOST",
        capability_tier="full_runtime",
        runtime=rt,
    )
    restored = AndroidRuntimeDispatchBindingRecord.from_dict(rec.to_dict())
    assert restored.identity.session_id == "s-bd"
    assert restored.identity.contract_id == "c-bd"
    assert restored.identity.tracker_id == "t-bd"
    assert restored.coordination_role == "target_only_executor"
    assert restored.android_host_role == "FULL_RUNTIME_HOST"


# ---------------------------------------------------------------------------
# BE — Serialisation: to_json produces valid JSON
# ---------------------------------------------------------------------------


def test_BE01_to_json_produces_valid_json():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    parsed = json.loads(rec.to_json())
    assert parsed["binding_state"] == "unbound"
    assert "identity" in parsed


# ---------------------------------------------------------------------------
# BF — Serialisation: from_dict non-dict raises ValueError
# ---------------------------------------------------------------------------


def test_BF01_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AndroidRuntimeDispatchBindingRecord.from_dict([1, 2, 3])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BG — Multiple sessions: each gets its own binding record
# ---------------------------------------------------------------------------


def test_BG01_multiple_sessions_independent():
    rt = _fresh_rt()
    r1 = _make_binding(session_id="s-multi-1", device_id="d1", runtime=rt)
    r2 = _make_binding(session_id="s-multi-2", device_id="d2", runtime=rt)
    assert r1.identity.session_id != r2.identity.session_id
    found1 = rt.get_latest_for_session("s-multi-1")
    found2 = rt.get_latest_for_session("s-multi-2")
    assert found1 is not None and found2 is not None
    assert found1.identity.device_id == "d1"
    assert found2.identity.device_id == "d2"


# ---------------------------------------------------------------------------
# BH — All 10 policy sentinels non-empty
# ---------------------------------------------------------------------------


def test_BH01_all_10_sentinels_non_empty():
    sentinels = [
        ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
        BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
        BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
        BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
        BINDING_SESSION_ID_MUST_MATCH_CONTRACT_POLICY,
        BINDING_STATE_IS_MONOTONIC_POLICY,
        RELEASED_BINDING_IS_TERMINAL_POLICY,
        BINDING_CONTRACT_ID_IS_IMMUTABLE_POLICY,
        DISPATCH_BINDING_REQUIRES_CONTRACT_ID_POLICY,
        BINDING_TRACKER_ID_IS_PROPAGATED_POLICY,
    ]
    assert len(sentinels) == 10
    for s in sentinels:
        assert s and isinstance(s, str)


# ---------------------------------------------------------------------------
# BI-BM — is_accepted / is_rejected / is_active / is_terminal helpers
# ---------------------------------------------------------------------------


def test_BI01_is_accepted_true_when_no_reject_reason():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    rec = AndroidRuntimeDispatchBindingRecord(identity=identity)
    assert rec.is_accepted()


def test_BJ01_is_accepted_false_when_reject_reason_set():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="", device_id="")
    rec = AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        reject_reason="rejected",
        is_session_anchored=False,
        binding_state=AndroidRuntimeBindingState.released,
    )
    assert not rec.is_accepted()


def test_BK01_is_rejected_true_when_reject_reason():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="", device_id="")
    rec = AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        reject_reason="bad",
        binding_state=AndroidRuntimeBindingState.released,
    )
    assert rec.is_rejected()


def test_BL01_is_active_true_when_not_released():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    rec = AndroidRuntimeDispatchBindingRecord(identity=identity)
    assert rec.is_active()


def test_BM01_is_terminal_true_when_released():
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s1", device_id="d1")
    rec = AndroidRuntimeDispatchBindingRecord(
        identity=identity, binding_state=AndroidRuntimeBindingState.released
    )
    assert rec.is_terminal()


# ---------------------------------------------------------------------------
# BN — binding_id auto-generated
# ---------------------------------------------------------------------------


def test_BN01_binding_id_auto_generated():
    rt = _fresh_rt()
    r1 = _make_binding(session_id="s1", device_id="d1", runtime=rt)
    r2 = _make_binding(session_id="s2", device_id="d2", runtime=rt)
    # Different binding_ids auto-generated
    assert r1.identity.binding_id != r2.identity.binding_id


# ---------------------------------------------------------------------------
# BO — Snapshot to_dict keys
# ---------------------------------------------------------------------------


def test_BO01_snapshot_to_dict_has_expected_keys():
    snap = AndroidRuntimeDispatchBindingSnapshot(active_count=1, total_count=2)
    d = snap.to_dict()
    assert "records" in d
    assert "active_count" in d
    assert "total_count" in d
    assert "policy_sentinels" in d


# ---------------------------------------------------------------------------
# BP — Record to_dict: reject_reason empty when accepted
# ---------------------------------------------------------------------------


def test_BP01_reject_reason_empty_when_accepted():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    d = rec.to_dict()
    assert d["reject_reason"] == ""


# ---------------------------------------------------------------------------
# BQ — Record to_dict: identity sub-dict
# ---------------------------------------------------------------------------


def test_BQ01_identity_sub_dict_has_expected_keys():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    d = rec.to_dict()
    assert "identity" in d
    identity_d = d["identity"]
    for key in ("binding_id", "session_id", "device_id", "contract_id", "tracker_id", "trace_id"):
        assert key in identity_d, f"Missing identity key: {key}"


# ---------------------------------------------------------------------------
# BR / BS — Singleton accessor and reset
# ---------------------------------------------------------------------------


def test_BR01_get_dispatch_binding_runtime_returns_singleton():
    rt1 = get_dispatch_binding_runtime()
    rt2 = get_dispatch_binding_runtime()
    assert rt1 is rt2


def test_BS01_reset_clears_singleton():
    reset_dispatch_binding_runtime()
    rt = get_dispatch_binding_runtime()
    assert rt.size() == 0


# ---------------------------------------------------------------------------
# BT — Two separate sessions: list_active returns both
# ---------------------------------------------------------------------------


def test_BT01_two_sessions_both_returned_when_active():
    rt = _fresh_rt()
    create_android_dispatch_binding(session_id="sess-bt-1", device_id="d1", runtime=rt)
    create_android_dispatch_binding(session_id="sess-bt-2", device_id="d2", runtime=rt)
    active = rt.list_active()
    session_ids = {r.identity.session_id for r in active}
    assert "sess-bt-1" in session_ids
    assert "sess-bt-2" in session_ids


# ---------------------------------------------------------------------------
# BU — create does not mutate other records
# ---------------------------------------------------------------------------


def test_BU01_create_does_not_mutate_other_records():
    rt = _fresh_rt()
    r1 = _make_binding(session_id="sess-bu-1", device_id="d1", runtime=rt)
    _make_binding(session_id="sess-bu-2", device_id="d2", runtime=rt)
    # r1 should still be in its original state
    found = rt.get_latest_for_session("sess-bu-1")
    assert found.binding_state == AndroidRuntimeBindingState.unbound


# ---------------------------------------------------------------------------
# BV — end-to-end: create → bind → confirm → add contract → dispatch → snapshot
# ---------------------------------------------------------------------------


def test_BV01_end_to_end_dispatch_lifecycle():
    rt = _fresh_rt()

    # 1. Create binding with contract_id already set
    rec = create_android_dispatch_binding(
        session_id="e2e-sess",
        device_id="e2e-dev",
        contract_id="e2e-contract",
        tracker_id="e2e-tracker",
        runtime=rt,
    )
    assert rec.binding_state == AndroidRuntimeBindingState.unbound

    # 2. Bind
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.binding

    # 3. Confirm
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.confirm, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.bound

    # 4. Dispatch (contract_id already set, so this should succeed)
    rec = advance_binding_state(rec, AndroidRuntimeBindingSignal.dispatch, runtime=rt)
    assert rec.binding_state == AndroidRuntimeBindingState.dispatching

    # 5. Snapshot reflects dispatching state
    snap = build_dispatch_binding_snapshot(runtime=rt)
    dispatching = [r for r in snap.records if r.binding_state == AndroidRuntimeBindingState.dispatching]
    assert len(dispatching) >= 1
    assert any(r.identity.session_id == "e2e-sess" for r in dispatching)


# ---------------------------------------------------------------------------
# BW — PR11 sentinel contains 'package=11'
# ---------------------------------------------------------------------------


def test_BW01_pr11_sentinel_contains_package_11():
    assert "package=11" in ANDROID_RUNTIME_DISPATCH_BINDING_PR11_SENTINEL


# ---------------------------------------------------------------------------
# BX — from_dict missing fields use safe defaults
# ---------------------------------------------------------------------------


def test_BX01_from_dict_missing_fields_safe_defaults():
    rec = AndroidRuntimeDispatchBindingRecord.from_dict({})
    assert rec.binding_state == AndroidRuntimeBindingState.unbound
    assert rec.source_runtime_posture == "join_runtime"
    assert rec.reject_reason == ""
    assert rec.metadata == {}


# ---------------------------------------------------------------------------
# BY — AndroidRuntimeDispatchBindingIdentity from_dict: non-dict raises
# ---------------------------------------------------------------------------


def test_BY01_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AndroidRuntimeDispatchBindingIdentity.from_dict("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BZ — Record from_dict: non-dict raises
# ---------------------------------------------------------------------------


def test_BZ01_record_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        AndroidRuntimeDispatchBindingRecord.from_dict(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CA — advance_binding_state: updated_at >= created_at
# ---------------------------------------------------------------------------


def test_CA01_updated_at_is_later_than_or_equal_to_created_at():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    t_before = time.time()
    advanced = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert advanced.updated_at >= rec.created_at


# ---------------------------------------------------------------------------
# CB — Runtime clear()
# ---------------------------------------------------------------------------


def test_CB01_clear_empties_the_buffer():
    rt = _fresh_rt()
    _make_binding(runtime=rt)
    _make_binding(session_id="s2", device_id="d2", runtime=rt)
    rt.clear()
    assert rt.size() == 0
    assert rt.list_all() == []


# ---------------------------------------------------------------------------
# CC — binding_id stable across to_dict/from_dict
# ---------------------------------------------------------------------------


def test_CC01_binding_id_stable_across_round_trip():
    rt = _fresh_rt()
    rec = _make_binding(runtime=rt)
    bid = rec.identity.binding_id
    restored = AndroidRuntimeDispatchBindingRecord.from_dict(rec.to_dict())
    assert restored.identity.binding_id == bid


# ---------------------------------------------------------------------------
# CD — list_active excludes released
# ---------------------------------------------------------------------------


def test_CD01_list_active_excludes_released():
    rt = _fresh_rt()
    identity = AndroidRuntimeDispatchBindingIdentity(session_id="s-rel2", device_id="d-rel2")
    released = AndroidRuntimeDispatchBindingRecord(
        identity=identity, binding_state=AndroidRuntimeBindingState.released
    )
    rt.push(released)
    active = rt.list_active()
    assert not any(
        r.identity.session_id == "s-rel2" for r in active
    )


# ---------------------------------------------------------------------------
# CE — Snapshot records are newest-first
# ---------------------------------------------------------------------------


def test_CE01_snapshot_records_newest_first():
    rt = _fresh_rt()
    create_android_dispatch_binding(session_id="first", device_id="d1", runtime=rt)
    create_android_dispatch_binding(session_id="second", device_id="d2", runtime=rt)
    snap = build_dispatch_binding_snapshot(runtime=rt)
    assert snap.records[0].identity.session_id == "second"
    assert snap.records[1].identity.session_id == "first"


# ---------------------------------------------------------------------------
# CF — AndroidRuntimeBindingSignal.from_string: unknown → bind
# ---------------------------------------------------------------------------


def test_CF01_signal_from_string_unknown_defaults_to_bind():
    result = AndroidRuntimeBindingSignal.from_string("totally-unknown")
    assert result == AndroidRuntimeBindingSignal.bind


# ---------------------------------------------------------------------------
# CG — AndroidRuntimeBindingState.from_string: unknown → unbound
# ---------------------------------------------------------------------------


def test_CG01_state_from_string_unknown_defaults_to_unbound():
    result = AndroidRuntimeBindingState.from_string("totally-unknown")
    assert result == AndroidRuntimeBindingState.unbound


# ---------------------------------------------------------------------------
# CH — get_latest_for_device returns correct record
# ---------------------------------------------------------------------------


def test_CH01_get_latest_for_device_returns_correct_record():
    rt = _fresh_rt()
    create_android_dispatch_binding(session_id="s1", device_id="target-device", runtime=rt)
    create_android_dispatch_binding(session_id="s2", device_id="other-device", runtime=rt)
    found = rt.get_latest_for_device("target-device")
    assert found is not None
    assert found.identity.device_id == "target-device"


# ---------------------------------------------------------------------------
# CI — advance_binding_state: metadata preserved
# ---------------------------------------------------------------------------


def test_CI01_metadata_preserved_across_transitions():
    rt = _fresh_rt()
    meta = {"key": "value", "number": 42}
    rec = create_android_dispatch_binding(
        session_id="sess-meta",
        device_id="dev-meta",
        metadata=meta,
        runtime=rt,
    )
    advanced = advance_binding_state(rec, AndroidRuntimeBindingSignal.bind, runtime=rt)
    assert advanced.metadata == meta


# ---------------------------------------------------------------------------
# CJ — create_android_dispatch_binding: metadata stored
# ---------------------------------------------------------------------------


def test_CJ01_metadata_stored_in_record():
    rt = _fresh_rt()
    meta = {"foo": "bar"}
    rec = create_android_dispatch_binding(
        session_id="s1", device_id="d1", metadata=meta, runtime=rt
    )
    assert rec.metadata == {"foo": "bar"}


# ---------------------------------------------------------------------------
# CK — resolve_dispatch_binding: coordination_role from attached_session forwarded
# ---------------------------------------------------------------------------


def test_CK01_coordination_role_from_attached_session_forwarded():
    rt = _fresh_rt()
    session = _StubSession(coordination_role="source_controller")
    rec = resolve_dispatch_binding(
        session, _StubContract(), _StubTracker(), runtime=rt
    )
    assert rec.coordination_role == "source_controller"


# ---------------------------------------------------------------------------
# CL — Snapshot to_json is valid JSON
# ---------------------------------------------------------------------------


def test_CL01_snapshot_to_json_valid_json():
    rt = _fresh_rt()
    _make_binding(runtime=rt)
    snap = build_dispatch_binding_snapshot(runtime=rt)
    parsed = json.loads(snap.to_json())
    assert "records" in parsed
    assert "active_count" in parsed
