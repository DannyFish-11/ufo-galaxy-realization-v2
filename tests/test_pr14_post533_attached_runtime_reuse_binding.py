"""tests/test_pr14_post533_attached_runtime_reuse_binding.py
=============================================================
Tests for PR package 14 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Persistent Attached-Runtime Reuse Binding.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — ReuseEligibilityStatus enum: all values, from_string(), defaults.
C  — ReuseInvalidationReason enum: all values, from_string(),
     is_lifecycle_invalidation().
D  — AttachedRuntimeReuseBindingIdentity: construction, defaults, to_dict(),
     to_json(), from_dict().
E  — AttachedRuntimeReuseBindingRecord: construction, defaults, to_dict(),
     to_json(), is_eligible(), is_invalidated(), has_dispatch_binding().
F  — AttachedRuntimeReuseBindingSnapshot: construction, defaults, to_dict(),
     to_json().
G  — AttachedRuntimeReuseBindingRuntime: push, list_all, list_eligible,
     get_latest_for_session, get_latest_for_device, clear, size, capacity.
H  — establish_reuse_binding: valid inputs → eligible record.
I  — establish_reuse_binding: empty session_id → ineligible (missing_session).
J  — establish_reuse_binding: empty device_id → ineligible (missing_device).
K  — establish_reuse_binding: non-join_runtime posture → ineligible (bad_posture).
L  — establish_reuse_binding: trace_id auto-generated when absent.
M  — establish_reuse_binding: reuse_binding_id override honoured.
N  — establish_reuse_binding: posture defaults to join_runtime.
O  — establish_reuse_binding: coordination_role forwarded.
P  — establish_reuse_binding: android_host_role forwarded.
Q  — establish_reuse_binding: capability_tier forwarded.
R  — establish_reuse_binding: persisted to runtime ring-buffer.
S  — establish_reuse_binding: custom runtime isolation.
T  — establish_reuse_binding: metadata stored in record.
U  — evaluate_reuse_eligibility: eligible record → eligible.
V  — evaluate_reuse_eligibility: ineligible record → ineligible (fast-path).
W  — evaluate_reuse_eligibility: live attached session attached + join_runtime → eligible.
X  — evaluate_reuse_eligibility: live session detached → ineligible.
Y  — evaluate_reuse_eligibility: live session non-join_runtime posture → ineligible.
Z  — evaluate_reuse_eligibility: None attached_session → uses record status.
AA — invalidate_reuse_binding: detach signal → ineligible, reason=detach.
AB — invalidate_reuse_binding: disconnect signal → ineligible, reason=disconnect.
AC — invalidate_reuse_binding: disable signal → ineligible, reason=disable.
AD — invalidate_reuse_binding: invalidate signal → ineligible, reason=invalidate.
AE — invalidate_reuse_binding: unknown signal → safe-defaults to detach reason.
AF — invalidate_reuse_binding: identity fields preserved.
AG — invalidate_reuse_binding: invalidated_at is set.
AH — invalidate_reuse_binding: persisted to runtime ring-buffer.
AI — invalidate_reuse_binding: original record not mutated.
AJ — register_dispatch_binding_id: dispatch_binding_id updated.
AK — register_dispatch_binding_id: identity fields preserved.
AL — register_dispatch_binding_id: eligibility status preserved.
AM — register_dispatch_binding_id: persisted to runtime ring-buffer.
AN — register_dispatch_binding_id: original record not mutated.
AO — record_reuse_binding: persists externally constructed record.
AP — get_reuse_binding: returns most recent for session_id.
AQ — get_reuse_binding: returns None for unknown session_id.
AR — get_reuse_binding_by_device: returns most recent for device_id.
AS — get_reuse_binding_by_device: returns None for unknown device_id.
AT — list_eligible_reuse_bindings: returns only eligible records.
AU — list_eligible_reuse_bindings: empty when all ineligible.
AV — build_reuse_binding_snapshot: counts eligible / ineligible correctly.
AW — build_reuse_binding_snapshot: empty runtime → zero counts.
AX — build_reuse_binding_snapshot: records are newest-first.
AY — core.runtime re-exports: all PR-14 symbols accessible from core.runtime.
AZ — projection.py sentinel: ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14
     is present and not UNAVAILABLE.
BA — Ring buffer capacity: 128.
BB — Ring buffer eviction: oldest entry evicted when full.
BC — Serialisation round-trip: to_dict produces expected keys.
BD — Serialisation round-trip: to_json produces valid JSON.
BE — AttachedRuntimeReuseBindingIdentity.from_dict: non-dict raises ValueError.
BF — All 10 policy sentinels are non-empty strings.
BG — ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL contains 'package=14'.
BH — Multiple sessions: each gets its own binding record.
BI — get_reuse_binding_runtime returns same singleton.
BJ — reset_reuse_binding_runtime clears singleton for isolation.
BK — reuse_binding_id auto-generated UUID when not provided.
BL — establish then invalidate: evaluate_reuse_eligibility returns ineligible.
BM — Snapshot to_json is valid JSON.
BN — Two sessions: list_eligible returns both when both eligible.
BO — Ineligible record: is_eligible() returns False.
BP — Eligible record: is_eligible() returns True.
BQ — invalidate then re-establish: new binding is eligible.
BR — dispatch_binding_id empty at establishment; updated by register_dispatch_binding_id.
BS — end-to-end: establish → register_dispatch_binding_id × 2 → snapshot shows latest.
BT — evaluate_reuse_eligibility: live session state is string 'attached' → eligible.
BU — evaluate_reuse_eligibility: live session state is string 'detached' → ineligible.
BV — ReuseInvalidationReason.from_string: unknown string → none.
BW — ReuseInvalidationReason.is_lifecycle_invalidation: only lifecycle signals True.
BX — ReuseEligibilityStatus.from_string: unknown string → ineligible.
BY — AttachedRuntimeReuseBindingRecord.has_dispatch_binding: True after register.
BZ — establish_reuse_binding: control_only posture in empty string normalises properly.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from core.attached_runtime_reuse_binding import (
    ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY,
    ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL,
    REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY,
    REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY,
    REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY,
    REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY,
    REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY,
    REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY,
    AttachedRuntimeReuseBindingIdentity,
    AttachedRuntimeReuseBindingRecord,
    AttachedRuntimeReuseBindingRuntime,
    AttachedRuntimeReuseBindingSnapshot,
    ReuseEligibilityStatus,
    ReuseInvalidationReason,
    build_reuse_binding_snapshot,
    establish_reuse_binding,
    evaluate_reuse_eligibility,
    get_reuse_binding,
    get_reuse_binding_by_device,
    get_reuse_binding_runtime,
    invalidate_reuse_binding,
    list_eligible_reuse_bindings,
    record_reuse_binding,
    register_dispatch_binding_id,
    reset_reuse_binding_runtime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_rt() -> AttachedRuntimeReuseBindingRuntime:
    """Return a fresh isolated ring-buffer (not the singleton)."""
    return AttachedRuntimeReuseBindingRuntime()


def _eligible_binding(
    session_id: str = "sess-1",
    device_id: str = "dev-1",
    posture: str = "join_runtime",
    coordination_role: str = "joined_runtime_participant",
    android_host_role: str = "FULL_RUNTIME_HOST",
    capability_tier: str = "full_runtime",
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
) -> AttachedRuntimeReuseBindingRecord:
    rt = runtime if runtime is not None else _fresh_rt()
    return establish_reuse_binding(
        session_id=session_id,
        device_id=device_id,
        source_runtime_posture=posture,
        coordination_role=coordination_role,
        android_host_role=android_host_role,
        capability_tier=capability_tier,
        runtime=rt,
    )


@dataclass
class _StubAttachedSession:
    """Minimal stub mimicking PR-7 AttachedRuntimeSessionRecord."""

    session_id: str = "sess-1"
    device_id: str = "dev-1"
    source_runtime_posture: str = "join_runtime"
    coordination_role: str = "joined_runtime_participant"
    android_host_role: str = "FULL_RUNTIME_HOST"
    capability_tier: str = "full_runtime"
    attachment_state: Any = field(default=None)

    def __post_init__(self):
        if self.attachment_state is None:
            self.attachment_state = _AttachState("attached")


@dataclass
class _AttachState:
    value: str = "attached"

    def __eq__(self, other):
        if isinstance(other, str):
            return self.value == other
        return NotImplemented

    def __hash__(self):
        return hash(self.value)


# ---------------------------------------------------------------------------
# Group A — Authority / policy sentinel presence
# ---------------------------------------------------------------------------


class TestGroupA_Sentinels:
    def test_A01_authority_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY
        assert isinstance(ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY, str)

    def test_A02_authority_mentions_canonical_authority(self):
        assert "canonical authority" in ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY.lower()

    def test_A03_pr14_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL
        assert isinstance(ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL, str)

    def test_A04_pr14_sentinel_contains_package14(self):
        assert "package=14" in ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL

    def test_A05_reuse_requires_session_policy_non_empty(self):
        assert REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY

    def test_A06_reuse_requires_posture_policy_non_empty(self):
        assert REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY

    def test_A07_reuse_requires_device_policy_non_empty(self):
        assert REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY

    def test_A08_eligibility_requires_active_session_policy_non_empty(self):
        assert REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY

    def test_A09_invalidated_on_detach_policy_non_empty(self):
        assert REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY

    def test_A10_invalidated_on_disconnect_policy_non_empty(self):
        assert REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY

    def test_A11_invalidated_on_disable_policy_non_empty(self):
        assert REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY

    def test_A12_dispatch_binding_id_latest_policy_non_empty(self):
        assert REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY

    def test_A13_stable_targeting_surface_policy_non_empty(self):
        assert REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY


# ---------------------------------------------------------------------------
# Group B — ReuseEligibilityStatus enum
# ---------------------------------------------------------------------------


class TestGroupB_ReuseEligibilityStatus:
    def test_B01_eligible_value(self):
        assert ReuseEligibilityStatus.eligible.value == "eligible"

    def test_B02_ineligible_value(self):
        assert ReuseEligibilityStatus.ineligible.value == "ineligible"

    def test_B03_from_string_eligible(self):
        assert ReuseEligibilityStatus.from_string("eligible") == ReuseEligibilityStatus.eligible

    def test_B04_from_string_ineligible(self):
        assert ReuseEligibilityStatus.from_string("ineligible") == ReuseEligibilityStatus.ineligible

    def test_B05_from_string_unknown_defaults_ineligible(self):
        assert ReuseEligibilityStatus.from_string("unknown") == ReuseEligibilityStatus.ineligible

    def test_B06_from_string_none_defaults_ineligible(self):
        assert ReuseEligibilityStatus.from_string(None) == ReuseEligibilityStatus.ineligible

    def test_B07_from_string_custom_default(self):
        result = ReuseEligibilityStatus.from_string("bad", default=ReuseEligibilityStatus.eligible)
        assert result == ReuseEligibilityStatus.eligible

    def test_B08_from_string_case_insensitive(self):
        assert ReuseEligibilityStatus.from_string("ELIGIBLE") == ReuseEligibilityStatus.eligible

    def test_B09_string_enum_is_str(self):
        assert isinstance(ReuseEligibilityStatus.eligible, str)


# ---------------------------------------------------------------------------
# Group C — ReuseInvalidationReason enum
# ---------------------------------------------------------------------------


class TestGroupC_ReuseInvalidationReason:
    def test_C01_detach_value(self):
        assert ReuseInvalidationReason.detach.value == "detach"

    def test_C02_disconnect_value(self):
        assert ReuseInvalidationReason.disconnect.value == "disconnect"

    def test_C03_disable_value(self):
        assert ReuseInvalidationReason.disable.value == "disable"

    def test_C04_invalidate_value(self):
        assert ReuseInvalidationReason.invalidate.value == "invalidate"

    def test_C05_bad_posture_value(self):
        assert ReuseInvalidationReason.bad_posture.value == "bad_posture"

    def test_C06_missing_session_value(self):
        assert ReuseInvalidationReason.missing_session.value == "missing_session"

    def test_C07_missing_device_value(self):
        assert ReuseInvalidationReason.missing_device.value == "missing_device"

    def test_C08_none_value(self):
        assert ReuseInvalidationReason.none.value == "none"

    def test_C09_from_string_detach(self):
        assert ReuseInvalidationReason.from_string("detach") == ReuseInvalidationReason.detach

    def test_C10_from_string_disconnect(self):
        assert ReuseInvalidationReason.from_string("disconnect") == ReuseInvalidationReason.disconnect

    def test_C11_from_string_unknown_defaults_none(self):
        assert ReuseInvalidationReason.from_string("unknown") == ReuseInvalidationReason.none

    def test_C12_from_string_none_input_defaults_none(self):
        assert ReuseInvalidationReason.from_string(None) == ReuseInvalidationReason.none

    def test_C13_is_lifecycle_invalidation_detach(self):
        assert ReuseInvalidationReason.detach.is_lifecycle_invalidation() is True

    def test_C14_is_lifecycle_invalidation_disconnect(self):
        assert ReuseInvalidationReason.disconnect.is_lifecycle_invalidation() is True

    def test_C15_is_lifecycle_invalidation_disable(self):
        assert ReuseInvalidationReason.disable.is_lifecycle_invalidation() is True

    def test_C16_is_lifecycle_invalidation_invalidate(self):
        assert ReuseInvalidationReason.invalidate.is_lifecycle_invalidation() is True

    def test_C17_is_lifecycle_invalidation_bad_posture_false(self):
        assert ReuseInvalidationReason.bad_posture.is_lifecycle_invalidation() is False

    def test_C18_is_lifecycle_invalidation_missing_session_false(self):
        assert ReuseInvalidationReason.missing_session.is_lifecycle_invalidation() is False

    def test_C19_is_lifecycle_invalidation_none_false(self):
        assert ReuseInvalidationReason.none.is_lifecycle_invalidation() is False

    def test_C20_from_string_case_insensitive(self):
        assert ReuseInvalidationReason.from_string("DETACH") == ReuseInvalidationReason.detach


# ---------------------------------------------------------------------------
# Group D — AttachedRuntimeReuseBindingIdentity
# ---------------------------------------------------------------------------


class TestGroupD_Identity:
    def test_D01_construction_minimal(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        assert ident.session_id == "s"
        assert ident.device_id == "d"
        assert ident.reuse_binding_id
        assert ident.trace_id

    def test_D02_auto_generated_ids_are_uuids(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        uuid.UUID(ident.reuse_binding_id)  # raises if not valid UUID
        uuid.UUID(ident.trace_id)

    def test_D03_override_reuse_binding_id(self):
        ident = AttachedRuntimeReuseBindingIdentity(
            session_id="s", device_id="d", reuse_binding_id="my-id"
        )
        assert ident.reuse_binding_id == "my-id"

    def test_D04_override_trace_id(self):
        ident = AttachedRuntimeReuseBindingIdentity(
            session_id="s", device_id="d", trace_id="my-trace"
        )
        assert ident.trace_id == "my-trace"

    def test_D05_to_dict_keys(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        d = ident.to_dict()
        assert set(d.keys()) == {"reuse_binding_id", "session_id", "device_id", "trace_id"}

    def test_D06_to_json_valid_json(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        parsed = json.loads(ident.to_json())
        assert parsed["session_id"] == "s"

    def test_D07_from_dict_roundtrip(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        ident2 = AttachedRuntimeReuseBindingIdentity.from_dict(ident.to_dict())
        assert ident2.session_id == ident.session_id
        assert ident2.device_id == ident.device_id
        assert ident2.reuse_binding_id == ident.reuse_binding_id
        assert ident2.trace_id == ident.trace_id

    def test_D08_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            AttachedRuntimeReuseBindingIdentity.from_dict("not-a-dict")

    def test_D09_from_dict_missing_fields_safe_defaults(self):
        ident = AttachedRuntimeReuseBindingIdentity.from_dict({})
        assert isinstance(ident.session_id, str)
        assert isinstance(ident.reuse_binding_id, str)


# ---------------------------------------------------------------------------
# Group E — AttachedRuntimeReuseBindingRecord
# ---------------------------------------------------------------------------


class TestGroupE_Record:
    def test_E01_defaults(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(identity=ident)
        assert rec.reuse_eligibility_status == ReuseEligibilityStatus.ineligible
        assert rec.invalidation_reason == ReuseInvalidationReason.none
        assert rec.dispatch_binding_id == ""

    def test_E02_is_eligible_true(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(
            identity=ident,
            reuse_eligibility_status=ReuseEligibilityStatus.eligible,
        )
        assert rec.is_eligible() is True

    def test_E03_is_eligible_false(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(
            identity=ident,
            reuse_eligibility_status=ReuseEligibilityStatus.ineligible,
        )
        assert rec.is_eligible() is False

    def test_E04_is_invalidated(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(
            identity=ident,
            reuse_eligibility_status=ReuseEligibilityStatus.ineligible,
        )
        assert rec.is_invalidated() is True

    def test_E05_has_dispatch_binding_false_by_default(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(identity=ident)
        assert rec.has_dispatch_binding() is False

    def test_E06_has_dispatch_binding_true(self):
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s", device_id="d")
        rec = AttachedRuntimeReuseBindingRecord(
            identity=ident, dispatch_binding_id="dbid-1"
        )
        assert rec.has_dispatch_binding() is True

    def test_E07_to_dict_contains_expected_keys(self):
        rec = _eligible_binding()
        d = rec.to_dict()
        assert "identity" in d
        assert "reuse_eligibility_status" in d
        assert "invalidation_reason" in d
        assert "dispatch_binding_id" in d
        assert "established_at" in d

    def test_E08_to_json_valid(self):
        rec = _eligible_binding()
        parsed = json.loads(rec.to_json())
        assert "identity" in parsed

    def test_E09_established_at_is_float(self):
        rec = _eligible_binding()
        assert isinstance(rec.established_at, float)

    def test_E10_invalidated_at_none_initially(self):
        rec = _eligible_binding()
        assert rec.invalidated_at is None


# ---------------------------------------------------------------------------
# Group F — AttachedRuntimeReuseBindingSnapshot
# ---------------------------------------------------------------------------


class TestGroupF_Snapshot:
    def test_F01_defaults(self):
        snap = AttachedRuntimeReuseBindingSnapshot()
        assert snap.records == []
        assert snap.eligible_count == 0
        assert snap.ineligible_count == 0

    def test_F02_to_dict_keys(self):
        snap = AttachedRuntimeReuseBindingSnapshot()
        d = snap.to_dict()
        assert "records" in d
        assert "eligible_count" in d
        assert "ineligible_count" in d
        assert "snapshot_at" in d

    def test_F03_to_json_valid(self):
        snap = AttachedRuntimeReuseBindingSnapshot()
        json.loads(snap.to_json())


# ---------------------------------------------------------------------------
# Group G — AttachedRuntimeReuseBindingRuntime ring buffer
# ---------------------------------------------------------------------------


class TestGroupG_Runtime:
    def test_G01_initial_size_zero(self):
        rt = _fresh_rt()
        assert rt.size() == 0

    def test_G02_capacity_128(self):
        rt = _fresh_rt()
        assert rt.capacity == 128

    def test_G03_push_increases_size(self):
        rt = _fresh_rt()
        rec = _eligible_binding(runtime=rt)
        assert rt.size() == 1

    def test_G04_list_all_newest_first(self):
        rt = _fresh_rt()
        r1 = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        r2 = establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        all_recs = rt.list_all()
        assert all_recs[0].identity.session_id == "s2"
        assert all_recs[1].identity.session_id == "s1"

    def test_G05_list_eligible_filters_ineligible(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="", device_id="d2", runtime=rt)  # ineligible
        eligible = rt.list_eligible()
        assert len(eligible) == 1
        assert eligible[0].identity.session_id == "s1"

    def test_G06_get_latest_for_session(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        r = rt.get_latest_for_session("s1")
        assert r is not None

    def test_G07_get_latest_for_session_none_unknown(self):
        rt = _fresh_rt()
        assert rt.get_latest_for_session("nonexistent") is None

    def test_G08_get_latest_for_device(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="dev-x", runtime=rt)
        r = rt.get_latest_for_device("dev-x")
        assert r is not None
        assert r.identity.device_id == "dev-x"

    def test_G09_get_latest_for_device_none_unknown(self):
        rt = _fresh_rt()
        assert rt.get_latest_for_device("nonexistent") is None

    def test_G10_clear_empties_buffer(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        rt.clear()
        assert rt.size() == 0


# ---------------------------------------------------------------------------
# Group H — establish_reuse_binding: valid inputs
# ---------------------------------------------------------------------------


class TestGroupH_EstablishValid:
    def test_H01_returns_eligible_record(self):
        rec = _eligible_binding()
        assert rec.is_eligible()

    def test_H02_session_id_stored(self):
        rec = _eligible_binding(session_id="my-session")
        assert rec.identity.session_id == "my-session"

    def test_H03_device_id_stored(self):
        rec = _eligible_binding(device_id="my-device")
        assert rec.identity.device_id == "my-device"

    def test_H04_posture_stored(self):
        rec = _eligible_binding(posture="join_runtime")
        assert rec.source_runtime_posture == "join_runtime"

    def test_H05_is_session_anchored_true(self):
        rec = _eligible_binding()
        assert rec.is_session_anchored is True

    def test_H06_is_device_bound_true(self):
        rec = _eligible_binding()
        assert rec.is_device_bound is True

    def test_H07_invalidation_reason_none(self):
        rec = _eligible_binding()
        assert rec.invalidation_reason == ReuseInvalidationReason.none

    def test_H08_dispatch_binding_id_empty_initially(self):
        rec = _eligible_binding()
        assert rec.dispatch_binding_id == ""


# ---------------------------------------------------------------------------
# Group I — establish_reuse_binding: missing session_id
# ---------------------------------------------------------------------------


class TestGroupI_MissingSession:
    def test_I01_empty_session_id_ineligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="", device_id="d1", runtime=rt)
        assert rec.is_invalidated()
        assert rec.invalidation_reason == ReuseInvalidationReason.missing_session

    def test_I02_persisted_to_runtime(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="", device_id="d1", runtime=rt)
        assert rt.size() == 1


# ---------------------------------------------------------------------------
# Group J — establish_reuse_binding: missing device_id
# ---------------------------------------------------------------------------


class TestGroupJ_MissingDevice:
    def test_J01_empty_device_id_ineligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="", runtime=rt)
        assert rec.is_invalidated()
        assert rec.invalidation_reason == ReuseInvalidationReason.missing_device

    def test_J02_persisted_to_runtime(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="", runtime=rt)
        assert rt.size() == 1


# ---------------------------------------------------------------------------
# Group K — establish_reuse_binding: bad posture
# ---------------------------------------------------------------------------


class TestGroupK_BadPosture:
    def test_K01_control_only_ineligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            source_runtime_posture="control_only",
            runtime=rt,
        )
        assert rec.is_invalidated()
        assert rec.invalidation_reason == ReuseInvalidationReason.bad_posture

    def test_K02_arbitrary_posture_ineligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            source_runtime_posture="observer_only",
            runtime=rt,
        )
        assert rec.is_invalidated()
        assert rec.invalidation_reason == ReuseInvalidationReason.bad_posture


# ---------------------------------------------------------------------------
# Group L-T — establish_reuse_binding: parameter forwarding
# ---------------------------------------------------------------------------


class TestGroupLT_EstablishParams:
    def test_L01_trace_id_auto_generated(self):
        rec = _eligible_binding()
        uuid.UUID(rec.identity.trace_id)

    def test_M01_reuse_binding_id_override(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            reuse_binding_id="fixed-id",
            runtime=rt,
        )
        assert rec.identity.reuse_binding_id == "fixed-id"

    def test_N01_posture_defaults_to_join_runtime(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        assert rec.source_runtime_posture == "join_runtime"

    def test_O01_coordination_role_forwarded(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            coordination_role="source_controller",
            runtime=rt,
        )
        assert rec.coordination_role == "source_controller"

    def test_P01_android_host_role_forwarded(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            android_host_role="PARTIAL_RUNTIME_HOST",
            runtime=rt,
        )
        assert rec.android_host_role == "PARTIAL_RUNTIME_HOST"

    def test_Q01_capability_tier_forwarded(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            capability_tier="partial_runtime",
            runtime=rt,
        )
        assert rec.capability_tier == "partial_runtime"

    def test_R01_persisted_to_runtime(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        assert rt.size() == 1

    def test_S01_custom_runtime_isolation(self):
        rt1 = _fresh_rt()
        rt2 = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt1)
        assert rt1.size() == 1
        assert rt2.size() == 0

    def test_T01_metadata_stored(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            metadata={"key": "value"},
            runtime=rt,
        )
        assert rec.metadata == {"key": "value"}


# ---------------------------------------------------------------------------
# Group U-Z — evaluate_reuse_eligibility
# ---------------------------------------------------------------------------


class TestGroupUZ_EvaluateEligibility:
    def test_U01_eligible_record_no_session_returns_eligible(self):
        rec = _eligible_binding()
        assert evaluate_reuse_eligibility(rec) == ReuseEligibilityStatus.eligible

    def test_V01_ineligible_record_fast_path(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="", device_id="d1", runtime=rt)
        assert evaluate_reuse_eligibility(rec) == ReuseEligibilityStatus.ineligible

    def test_W01_live_session_attached_join_runtime_eligible(self):
        rec = _eligible_binding()
        session = _StubAttachedSession(attachment_state=_AttachState("attached"))
        result = evaluate_reuse_eligibility(rec, attached_session=session)
        assert result == ReuseEligibilityStatus.eligible

    def test_X01_live_session_detached_ineligible(self):
        rec = _eligible_binding()
        session = _StubAttachedSession(attachment_state=_AttachState("detached"))
        result = evaluate_reuse_eligibility(rec, attached_session=session)
        assert result == ReuseEligibilityStatus.ineligible

    def test_Y01_live_session_wrong_posture_ineligible(self):
        rec = _eligible_binding()
        session = _StubAttachedSession(
            attachment_state=_AttachState("attached"),
            source_runtime_posture="control_only",
        )
        result = evaluate_reuse_eligibility(rec, attached_session=session)
        assert result == ReuseEligibilityStatus.ineligible

    def test_Z01_none_session_uses_record_status(self):
        rec = _eligible_binding()
        result = evaluate_reuse_eligibility(rec, attached_session=None)
        assert result == ReuseEligibilityStatus.eligible


# ---------------------------------------------------------------------------
# Group AA-AH — invalidate_reuse_binding
# ---------------------------------------------------------------------------


class TestGroupAA_Invalidate:
    def test_AA01_detach_signal(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert inv.reuse_eligibility_status == ReuseEligibilityStatus.ineligible
        assert inv.invalidation_reason == ReuseInvalidationReason.detach

    def test_AB01_disconnect_signal(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="disconnect", runtime=rt)
        assert inv.invalidation_reason == ReuseInvalidationReason.disconnect

    def test_AC01_disable_signal(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="disable", runtime=rt)
        assert inv.invalidation_reason == ReuseInvalidationReason.disable

    def test_AD01_invalidate_signal(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="invalidate", runtime=rt)
        assert inv.invalidation_reason == ReuseInvalidationReason.invalidate

    def test_AE01_unknown_signal_safe_default(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="foobar", runtime=rt)
        assert inv.reuse_eligibility_status == ReuseEligibilityStatus.ineligible
        assert inv.invalidation_reason == ReuseInvalidationReason.detach  # safe default

    def test_AF01_identity_preserved(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert inv.identity.session_id == rec.identity.session_id
        assert inv.identity.device_id == rec.identity.device_id
        assert inv.identity.reuse_binding_id == rec.identity.reuse_binding_id

    def test_AG01_invalidated_at_set(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert inv.invalidated_at is not None
        assert inv.invalidated_at >= rec.established_at

    def test_AH01_persisted_to_runtime(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        size_before = rt.size()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert rt.size() == size_before + 1

    def test_AI01_original_record_not_mutated(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        original_status = rec.reuse_eligibility_status
        inv = invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert rec.reuse_eligibility_status == original_status
        assert inv is not rec


# ---------------------------------------------------------------------------
# Group AJ-AN — register_dispatch_binding_id
# ---------------------------------------------------------------------------


class TestGroupAJ_RegisterDispatch:
    def test_AJ01_dispatch_binding_id_updated(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        updated = register_dispatch_binding_id(rec, "dispatch-001", runtime=rt)
        assert updated.dispatch_binding_id == "dispatch-001"

    def test_AK01_identity_preserved(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        updated = register_dispatch_binding_id(rec, "dispatch-001", runtime=rt)
        assert updated.identity.session_id == rec.identity.session_id
        assert updated.identity.reuse_binding_id == rec.identity.reuse_binding_id

    def test_AL01_eligibility_status_preserved(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        updated = register_dispatch_binding_id(rec, "dispatch-001", runtime=rt)
        assert updated.reuse_eligibility_status == rec.reuse_eligibility_status

    def test_AM01_persisted_to_runtime(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        size_before = rt.size()
        register_dispatch_binding_id(rec, "dispatch-001", runtime=rt)
        assert rt.size() == size_before + 1

    def test_AN01_original_not_mutated(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        updated = register_dispatch_binding_id(rec, "dispatch-001", runtime=rt)
        assert rec.dispatch_binding_id == ""
        assert updated is not rec


# ---------------------------------------------------------------------------
# Group AO — record_reuse_binding
# ---------------------------------------------------------------------------


class TestGroupAO_RecordReuse:
    def test_AO01_persists_external_record(self):
        rt = _fresh_rt()
        ident = AttachedRuntimeReuseBindingIdentity(session_id="s1", device_id="d1")
        rec = AttachedRuntimeReuseBindingRecord(
            identity=ident,
            reuse_eligibility_status=ReuseEligibilityStatus.eligible,
        )
        record_reuse_binding(rec, runtime=rt)
        assert rt.size() == 1
        assert rt.get_latest_for_session("s1") is rec


# ---------------------------------------------------------------------------
# Group AP-AS — get_reuse_binding / get_reuse_binding_by_device
# ---------------------------------------------------------------------------


class TestGroupAP_GetReuse:
    def test_AP01_get_reuse_binding_returns_latest_for_session(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        r = get_reuse_binding("s1", runtime=rt)
        assert r is not None
        assert r.identity.session_id == "s1"

    def test_AQ01_get_reuse_binding_none_unknown(self):
        rt = _fresh_rt()
        assert get_reuse_binding("nonexistent", runtime=rt) is None

    def test_AR01_get_reuse_binding_by_device_returns_latest(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="dev-x", runtime=rt)
        r = get_reuse_binding_by_device("dev-x", runtime=rt)
        assert r is not None
        assert r.identity.device_id == "dev-x"

    def test_AS01_get_reuse_binding_by_device_none_unknown(self):
        rt = _fresh_rt()
        assert get_reuse_binding_by_device("nonexistent", runtime=rt) is None


# ---------------------------------------------------------------------------
# Group AT-AU — list_eligible_reuse_bindings
# ---------------------------------------------------------------------------


class TestGroupAT_ListEligible:
    def test_AT01_returns_only_eligible(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="", device_id="d2", runtime=rt)
        eligible = list_eligible_reuse_bindings(runtime=rt)
        assert len(eligible) == 1
        assert eligible[0].identity.session_id == "s1"

    def test_AU01_empty_when_all_ineligible(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="", device_id="d1", runtime=rt)
        assert list_eligible_reuse_bindings(runtime=rt) == []


# ---------------------------------------------------------------------------
# Group AV-AX — build_reuse_binding_snapshot
# ---------------------------------------------------------------------------


class TestGroupAV_Snapshot:
    def test_AV01_counts_correctly(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        establish_reuse_binding(session_id="", device_id="d3", runtime=rt)
        snap = build_reuse_binding_snapshot(runtime=rt)
        assert snap.eligible_count == 2
        assert snap.ineligible_count == 1

    def test_AW01_empty_runtime_zero_counts(self):
        rt = _fresh_rt()
        snap = build_reuse_binding_snapshot(runtime=rt)
        assert snap.eligible_count == 0
        assert snap.ineligible_count == 0
        assert snap.records == []

    def test_AX01_records_newest_first(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        snap = build_reuse_binding_snapshot(runtime=rt)
        assert snap.records[0].identity.session_id == "s2"


# ---------------------------------------------------------------------------
# Group AY — core.runtime re-exports
# ---------------------------------------------------------------------------


class TestGroupAY_RuntimeReExports:
    def test_AY01_all_pr14_symbols_from_core_runtime(self):
        pytest.importorskip("pydantic")
        import core.runtime as cr
        symbols = [
            "ATTACHED_RUNTIME_REUSE_BINDING_AUTHORITY",
            "REUSE_BINDING_REQUIRES_ATTACHED_SESSION_POLICY",
            "REUSE_BINDING_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
            "REUSE_BINDING_REQUIRES_TARGET_DEVICE_ID_POLICY",
            "REUSE_ELIGIBILITY_REQUIRES_ACTIVE_SESSION_POLICY",
            "REUSE_BINDING_INVALIDATED_ON_DETACH_POLICY",
            "REUSE_BINDING_INVALIDATED_ON_DISCONNECT_POLICY",
            "REUSE_BINDING_INVALIDATED_ON_DISABLE_POLICY",
            "REUSE_BINDING_DISPATCH_BINDING_ID_IS_LATEST_POLICY",
            "REUSE_BINDING_IS_STABLE_TARGETING_SURFACE_POLICY",
            "ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL",
            "ReuseEligibilityStatus",
            "ReuseInvalidationReason",
            "AttachedRuntimeReuseBindingIdentity",
            "AttachedRuntimeReuseBindingRecord",
            "AttachedRuntimeReuseBindingSnapshot",
            "AttachedRuntimeReuseBindingRuntime",
            "establish_reuse_binding",
            "evaluate_reuse_eligibility",
            "invalidate_reuse_binding",
            "register_dispatch_binding_id",
            "record_reuse_binding",
            "get_reuse_binding",
            "get_reuse_binding_by_device",
            "list_eligible_reuse_bindings",
            "build_reuse_binding_snapshot",
            "get_reuse_binding_runtime",
            "reset_reuse_binding_runtime",
        ]
        for sym in symbols:
            assert hasattr(cr, sym), f"core.runtime missing PR-14 symbol: {sym}"


# ---------------------------------------------------------------------------
# Group AZ — projection.py sentinel
# ---------------------------------------------------------------------------


class TestGroupAZ_ProjectionSentinel:
    def test_AZ01_sentinel_present_and_not_unavailable(self):
        pytest.importorskip("fastapi")
        from core.routes.projection import ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14
        assert ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14
        assert "UNAVAILABLE" not in ATTACHED_RUNTIME_REUSE_BINDING_ALIGNED_PR14


# ---------------------------------------------------------------------------
# Group BA-BB — ring buffer capacity and eviction
# ---------------------------------------------------------------------------


class TestGroupBA_BufferCapacity:
    def test_BA01_capacity_is_128(self):
        rt = _fresh_rt()
        assert rt.capacity == 128

    def test_BB01_evicts_oldest_when_full(self):
        rt = AttachedRuntimeReuseBindingRuntime(capacity=3)
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        establish_reuse_binding(session_id="s3", device_id="d3", runtime=rt)
        establish_reuse_binding(session_id="s4", device_id="d4", runtime=rt)  # evicts s1
        assert rt.size() == 3
        assert rt.get_latest_for_session("s1") is None
        assert rt.get_latest_for_session("s4") is not None


# ---------------------------------------------------------------------------
# Group BC-BD — Serialisation
# ---------------------------------------------------------------------------


class TestGroupBC_Serialisation:
    def test_BC01_to_dict_keys(self):
        rec = _eligible_binding()
        d = rec.to_dict()
        expected_keys = {
            "identity", "reuse_eligibility_status", "invalidation_reason",
            "source_runtime_posture", "coordination_role", "android_host_role",
            "capability_tier", "dispatch_binding_id", "is_session_anchored",
            "is_device_bound", "established_at", "invalidated_at", "metadata",
        }
        assert expected_keys == set(d.keys())

    def test_BD01_to_json_valid_json(self):
        rec = _eligible_binding()
        parsed = json.loads(rec.to_json())
        assert parsed["reuse_eligibility_status"] == "eligible"


# ---------------------------------------------------------------------------
# Group BE-BG — misc
# ---------------------------------------------------------------------------


class TestGroupBE_Misc:
    def test_BE01_identity_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            AttachedRuntimeReuseBindingIdentity.from_dict("not-a-dict")

    def test_BF01_all_10_policy_sentinels_non_empty(self):
        from core.attached_runtime_reuse_binding import _ALL_POLICY_SENTINELS
        assert len(_ALL_POLICY_SENTINELS) == 10
        for s in _ALL_POLICY_SENTINELS:
            assert isinstance(s, str)
            assert s

    def test_BG01_pr14_sentinel_contains_package14(self):
        assert "package=14" in ATTACHED_RUNTIME_REUSE_BINDING_PR14_SENTINEL


# ---------------------------------------------------------------------------
# Group BH-BJ — singleton management
# ---------------------------------------------------------------------------


class TestGroupBH_Singleton:
    def test_BH01_multiple_sessions_each_has_own_record(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        r1 = rt.get_latest_for_session("s1")
        r2 = rt.get_latest_for_session("s2")
        assert r1 is not None
        assert r2 is not None
        assert r1.identity.session_id != r2.identity.session_id

    def test_BI01_get_reuse_binding_runtime_same_singleton(self):
        rt1 = get_reuse_binding_runtime()
        rt2 = get_reuse_binding_runtime()
        assert rt1 is rt2

    def test_BJ01_reset_clears_singleton(self):
        reset_reuse_binding_runtime()
        rt1 = get_reuse_binding_runtime()
        reset_reuse_binding_runtime()
        rt2 = get_reuse_binding_runtime()
        assert rt1 is not rt2


# ---------------------------------------------------------------------------
# Group BK-BZ — additional coverage
# ---------------------------------------------------------------------------


class TestGroupBK_Additional:
    def test_BK01_reuse_binding_id_auto_uuid(self):
        rec = _eligible_binding()
        uuid.UUID(rec.identity.reuse_binding_id)

    def test_BL01_establish_invalidate_evaluate_ineligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        inv = invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        assert evaluate_reuse_eligibility(inv) == ReuseEligibilityStatus.ineligible

    def test_BM01_snapshot_to_json_valid(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        snap = build_reuse_binding_snapshot(runtime=rt)
        json.loads(snap.to_json())

    def test_BN01_two_sessions_both_eligible_in_list(self):
        rt = _fresh_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        eligible = list_eligible_reuse_bindings(runtime=rt)
        assert len(eligible) == 2

    def test_BO01_ineligible_record_is_eligible_false(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="", device_id="d1", runtime=rt)
        assert rec.is_eligible() is False

    def test_BP01_eligible_record_is_eligible_true(self):
        rec = _eligible_binding()
        assert rec.is_eligible() is True

    def test_BQ01_invalidate_then_reestablish_is_eligible(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        new_rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        assert new_rec.is_eligible()

    def test_BR01_dispatch_binding_id_lifecycle(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        assert rec.dispatch_binding_id == ""
        updated = register_dispatch_binding_id(rec, "dbid-1", runtime=rt)
        assert updated.dispatch_binding_id == "dbid-1"

    def test_BS01_end_to_end_multiple_dispatches(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        r2 = register_dispatch_binding_id(rec, "dbid-1", runtime=rt)
        r3 = register_dispatch_binding_id(r2, "dbid-2", runtime=rt)
        latest = get_reuse_binding("s1", runtime=rt)
        assert latest is not None
        assert latest.dispatch_binding_id == "dbid-2"

    def test_BT01_evaluate_string_attached_state_eligible(self):
        """evaluate_reuse_eligibility should handle plain-string attachment_state."""
        rec = _eligible_binding()

        class _StrSession:
            attachment_state = "attached"
            source_runtime_posture = "join_runtime"

        assert evaluate_reuse_eligibility(rec, attached_session=_StrSession()) == ReuseEligibilityStatus.eligible

    def test_BU01_evaluate_string_detached_state_ineligible(self):
        rec = _eligible_binding()

        class _StrSession:
            attachment_state = "detached"
            source_runtime_posture = "join_runtime"

        assert evaluate_reuse_eligibility(rec, attached_session=_StrSession()) == ReuseEligibilityStatus.ineligible

    def test_BV01_invalidation_reason_from_string_unknown_none(self):
        assert ReuseInvalidationReason.from_string("zzz") == ReuseInvalidationReason.none

    def test_BW01_is_lifecycle_invalidation_only_for_lifecycle_signals(self):
        lifecycle = {ReuseInvalidationReason.detach, ReuseInvalidationReason.disconnect,
                     ReuseInvalidationReason.disable, ReuseInvalidationReason.invalidate}
        for r in ReuseInvalidationReason:
            if r in lifecycle:
                assert r.is_lifecycle_invalidation() is True
            else:
                assert r.is_lifecycle_invalidation() is False

    def test_BX01_eligibility_from_string_unknown_ineligible(self):
        assert ReuseEligibilityStatus.from_string("zzz") == ReuseEligibilityStatus.ineligible

    def test_BY01_has_dispatch_binding_true_after_register(self):
        rt = _fresh_rt()
        rec = establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        updated = register_dispatch_binding_id(rec, "dbid-xyz", runtime=rt)
        assert updated.has_dispatch_binding() is True

    def test_BZ01_empty_posture_normalises_to_join_runtime(self):
        """An empty string posture should default to join_runtime (eligible)."""
        rt = _fresh_rt()
        rec = establish_reuse_binding(
            session_id="s1", device_id="d1",
            source_runtime_posture="",  # empty → defaults to join_runtime
            runtime=rt,
        )
        assert rec.is_eligible()
        assert rec.source_runtime_posture == "join_runtime"
