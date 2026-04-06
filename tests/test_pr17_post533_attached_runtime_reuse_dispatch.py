"""tests/test_pr17_post533_attached_runtime_reuse_dispatch.py
=============================================================
Tests for PR package 17 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Dispatch Consumption of Attached-Runtime Reuse
Bindings.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — ReuseDispatchResolutionKind enum: all values, from_string(), defaults.
C  — ReuseDispatchResolution: construction, defaults, accessor methods,
     to_dict().
D  — resolve_reuse_dispatch_surface: no_binding when no record exists.
E  — resolve_reuse_dispatch_surface: session_id primary lookup.
F  — resolve_reuse_dispatch_surface: device_id fallback when session_id empty.
G  — resolve_reuse_dispatch_surface: device_id fallback when session lookup misses.
H  — resolve_reuse_dispatch_surface: eligible binding → reused.
I  — resolve_reuse_dispatch_surface: ineligible binding → rejected.
J  — resolve_reuse_dispatch_surface: live attached_session attached + join_runtime → reused.
K  — resolve_reuse_dispatch_surface: live attached_session detached → rejected.
L  — resolve_reuse_dispatch_surface: live attached_session wrong posture → rejected.
M  — resolve_reuse_dispatch_surface: reject_reason reflects invalidation_reason.
N  — resolve_reuse_dispatch_surface: metadata forwarded to resolution.
O  — write_back_dispatch_binding_id: updates dispatch_binding_id on reuse binding.
P  — write_back_dispatch_binding_id: identity fields preserved.
Q  — write_back_dispatch_binding_id: no_binding resolution returned unchanged.
R  — write_back_dispatch_binding_id: empty dispatch_binding_id → unchanged.
S  — write_back_dispatch_binding_id: returns new resolution (original not mutated).
T  — dispatch_with_reuse_binding: eligible binding → reused, no new binding created.
U  — dispatch_with_reuse_binding: no_binding → creates new dispatch binding.
V  — dispatch_with_reuse_binding: new_binding resolution carries dispatch binding.
W  — dispatch_with_reuse_binding: rejected binding → rejected, no new binding.
X  — dispatch_with_reuse_binding: write-back registered after new dispatch binding.
Y  — Integration: same session multi-dispatch reuse (required outcome 1).
Z  — Integration: invalidated binding rejected (required outcome 2).
AA — Integration: detach → no reuse (required outcome 3).
AB — Integration: disconnect → no reuse (required outcome 3).
AC — Integration: re-establish after reattach (required outcome 4).
AD — core.runtime re-exports: all PR-17 symbols accessible from core.runtime.
AE — projection.py sentinel: ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17
     is present and not UNAVAILABLE.
AF — All 10 policy sentinels are non-empty strings.
AG — ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL contains 'package=17'.
AH — dispatch_with_reuse_binding: no_binding + resolve_dispatch_binding creates
     bound record.
AI — resolve_reuse_dispatch_surface: reused resolution has reuse_binding set.
AJ — resolve_reuse_dispatch_surface: rejected resolution has reuse_binding set.
AK — resolve_reuse_dispatch_surface: no_binding resolution has reuse_binding=None.
AL — dispatch_with_reuse_binding: reused → dispatch_binding is None in resolution.
AM — dispatch_with_reuse_binding: new_binding → dispatch_binding is not None.
AN — ReuseDispatchResolution.to_dict: all expected keys present.
AO — ReuseDispatchResolution: resolution_id is a UUID string.
AP — ReuseDispatchResolution: resolved_at is a float.
AQ — Integration: disable → no reuse.
AR — Integration: invalidate signal → no reuse.
AS — dispatch_with_reuse_binding: metadata forwarded to resolution.
AT — resolve_reuse_dispatch_surface: empty session_id and device_id → no_binding.
AU — write_back_dispatch_binding_id: reuse binding carries updated dispatch_binding_id.
AV — dispatch_with_reuse_binding: reused → resolution_id preserved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from core.attached_runtime_reuse_dispatch import (
    ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY,
    ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL,
    REUSE_DISPATCH_LOOKUP_PRECEDES_DISPATCH_POLICY,
    REUSE_DISPATCH_ELIGIBILITY_GATE_IS_MANDATORY_POLICY,
    REUSE_DISPATCH_ELIGIBLE_SURFACE_IS_REUSED_POLICY,
    REUSE_DISPATCH_INELIGIBLE_BINDING_IS_REJECTED_POLICY,
    REUSE_DISPATCH_NO_BINDING_ALLOWS_NEW_DISPATCH_POLICY,
    REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY_POLICY,
    REUSE_DISPATCH_INVALIDATION_HARD_STOP_POLICY,
    REUSE_DISPATCH_SESSION_LOOKUP_PRECEDES_DEVICE_LOOKUP_POLICY,
    REUSE_DISPATCH_LIVE_SESSION_CROSS_CHECK_IS_OPTIONAL_POLICY,
    REUSE_DISPATCH_RESOLUTION_IS_IMMUTABLE_POLICY,
    REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION_POLICY,
    ReuseDispatchResolutionKind,
    ReuseDispatchResolution,
    resolve_reuse_dispatch_surface,
    write_back_dispatch_binding_id,
    dispatch_with_reuse_binding,
)
from core.attached_runtime_reuse_binding import (
    AttachedRuntimeReuseBindingRuntime,
    establish_reuse_binding,
    invalidate_reuse_binding,
    get_reuse_binding,
    ReuseEligibilityStatus,
)
from core.android_runtime_dispatch_binding import (
    AndroidRuntimeDispatchBindingRuntime,
)

# ---------------------------------------------------------------------------
# Minimal stub helpers
# ---------------------------------------------------------------------------


@dataclass
class _AttachState:
    value: str = "attached"


@dataclass
class _StubSession:
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
class _StubContractIdentity:
    contract_id: str = "contract-1"
    session_id: str = "sess-1"
    trace_id: str = "trace-abc"


@dataclass
class _StubContract:
    identity: _StubContractIdentity = field(default_factory=_StubContractIdentity)


@dataclass
class _StubTrackerIdentity:
    tracker_id: str = "tracker-1"


@dataclass
class _StubTracker:
    identity: _StubTrackerIdentity = field(default_factory=_StubTrackerIdentity)


def _fresh_reuse_rt() -> AttachedRuntimeReuseBindingRuntime:
    return AttachedRuntimeReuseBindingRuntime()


def _fresh_dispatch_rt() -> AndroidRuntimeDispatchBindingRuntime:
    return AndroidRuntimeDispatchBindingRuntime()


def _make_eligible_binding(
    session_id: str = "sess-1",
    device_id: str = "dev-1",
    runtime: Optional[AttachedRuntimeReuseBindingRuntime] = None,
):
    rt = runtime if runtime is not None else _fresh_reuse_rt()
    return establish_reuse_binding(
        session_id=session_id,
        device_id=device_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
    )


# ---------------------------------------------------------------------------
# A — Authority / policy sentinel presence and correctness
# ---------------------------------------------------------------------------


class TestGroupA_Sentinels:
    def test_A01_authority_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY
        assert isinstance(ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY, str)

    def test_A02_authority_mentions_pr17(self):
        assert "PR17" in ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY or "17" in ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY

    def test_A03_pr17_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL
        assert isinstance(ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL, str)

    def test_A04_pr17_sentinel_contains_package17(self):
        assert "package=17" in ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL

    def test_A05_all_10_policy_sentinels_non_empty(self):
        for sentinel in (
            REUSE_DISPATCH_LOOKUP_PRECEDES_DISPATCH_POLICY,
            REUSE_DISPATCH_ELIGIBILITY_GATE_IS_MANDATORY_POLICY,
            REUSE_DISPATCH_ELIGIBLE_SURFACE_IS_REUSED_POLICY,
            REUSE_DISPATCH_INELIGIBLE_BINDING_IS_REJECTED_POLICY,
            REUSE_DISPATCH_NO_BINDING_ALLOWS_NEW_DISPATCH_POLICY,
            REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY_POLICY,
            REUSE_DISPATCH_INVALIDATION_HARD_STOP_POLICY,
            REUSE_DISPATCH_SESSION_LOOKUP_PRECEDES_DEVICE_LOOKUP_POLICY,
            REUSE_DISPATCH_LIVE_SESSION_CROSS_CHECK_IS_OPTIONAL_POLICY,
            REUSE_DISPATCH_RESOLUTION_IS_IMMUTABLE_POLICY,
        ):
            assert sentinel, f"Policy sentinel is empty: {sentinel!r}"
            assert isinstance(sentinel, str)

    def test_A06_detach_policy_non_empty(self):
        assert REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION_POLICY
        assert isinstance(REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION_POLICY, str)


# ---------------------------------------------------------------------------
# B — ReuseDispatchResolutionKind enum
# ---------------------------------------------------------------------------


class TestGroupB_ReuseDispatchResolutionKind:
    def test_B01_reused_value(self):
        assert ReuseDispatchResolutionKind.reused.value == "reused"

    def test_B02_new_binding_value(self):
        assert ReuseDispatchResolutionKind.new_binding.value == "new_binding"

    def test_B03_rejected_value(self):
        assert ReuseDispatchResolutionKind.rejected.value == "rejected"

    def test_B04_no_binding_value(self):
        assert ReuseDispatchResolutionKind.no_binding.value == "no_binding"

    def test_B05_from_string_reused(self):
        assert ReuseDispatchResolutionKind.from_string("reused") == ReuseDispatchResolutionKind.reused

    def test_B06_from_string_new_binding(self):
        assert ReuseDispatchResolutionKind.from_string("new_binding") == ReuseDispatchResolutionKind.new_binding

    def test_B07_from_string_rejected(self):
        assert ReuseDispatchResolutionKind.from_string("rejected") == ReuseDispatchResolutionKind.rejected

    def test_B08_from_string_no_binding(self):
        assert ReuseDispatchResolutionKind.from_string("no_binding") == ReuseDispatchResolutionKind.no_binding

    def test_B09_from_string_unknown_defaults_no_binding(self):
        assert ReuseDispatchResolutionKind.from_string("unknown_xyz") == ReuseDispatchResolutionKind.no_binding

    def test_B10_from_string_case_insensitive(self):
        assert ReuseDispatchResolutionKind.from_string("REUSED") == ReuseDispatchResolutionKind.reused

    def test_B11_string_enum_is_str(self):
        assert isinstance(ReuseDispatchResolutionKind.reused, str)

    def test_B12_all_four_kinds_exist(self):
        kinds = {k.value for k in ReuseDispatchResolutionKind}
        assert kinds == {"reused", "new_binding", "rejected", "no_binding"}


# ---------------------------------------------------------------------------
# C — ReuseDispatchResolution dataclass
# ---------------------------------------------------------------------------


class TestGroupC_ReuseDispatchResolution:
    def test_C01_construction_minimal(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert r.resolution_kind == ReuseDispatchResolutionKind.no_binding
        assert r.session_id == "s"
        assert r.device_id == "d"

    def test_C02_reuse_binding_defaults_none(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert r.reuse_binding is None

    def test_C03_dispatch_binding_defaults_none(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert r.dispatch_binding is None

    def test_C04_reject_reason_defaults_empty(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert r.reject_reason == ""

    def test_AO_resolution_id_is_uuid_string(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert isinstance(r.resolution_id, str)
        # Should be parsable as UUID
        uuid.UUID(r.resolution_id)

    def test_AP_resolved_at_is_float(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert isinstance(r.resolved_at, float)
        assert r.resolved_at > 0

    def test_C05_is_reusable_true_for_reused(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="s",
            device_id="d",
        )
        assert r.is_reusable() is True
        assert r.is_rejected() is False
        assert r.has_no_binding() is False
        assert r.is_new_binding() is False

    def test_C06_is_rejected_true_for_rejected(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.rejected,
            session_id="s",
            device_id="d",
        )
        assert r.is_rejected() is True
        assert r.is_reusable() is False

    def test_C07_has_no_binding_true_for_no_binding(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        assert r.has_no_binding() is True

    def test_C08_is_new_binding_true_for_new_binding(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.new_binding,
            session_id="s",
            device_id="d",
        )
        assert r.is_new_binding() is True

    def test_AN_to_dict_has_expected_keys(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        d = r.to_dict()
        for key in (
            "resolution_kind",
            "session_id",
            "device_id",
            "reuse_binding_id",
            "dispatch_binding_id",
            "reject_reason",
            "resolved_at",
            "resolution_id",
            "metadata",
        ):
            assert key in d, f"Missing key: {key}"

    def test_C09_to_dict_no_binding_id_is_empty_string(self):
        r = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="s",
            device_id="d",
        )
        d = r.to_dict()
        assert d["reuse_binding_id"] == ""
        assert d["dispatch_binding_id"] == ""


# ---------------------------------------------------------------------------
# D — resolve_reuse_dispatch_surface: no_binding when no record exists
# ---------------------------------------------------------------------------


class TestGroupD_NoBinding:
    def test_D01_no_record_for_session_returns_no_binding(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("unknown-sess", "unknown-dev", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def test_AT_empty_session_and_device_returns_no_binding(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("", "", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def test_AK_no_binding_has_reuse_binding_none(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("x", "y", reuse_runtime=rt)
        assert result.reuse_binding is None

    def test_D02_no_binding_reject_reason_empty(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("x", "y", reuse_runtime=rt)
        assert result.reject_reason == ""

    def test_D03_no_binding_session_id_preserved(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("sess-xyz", "dev-abc", reuse_runtime=rt)
        assert result.session_id == "sess-xyz"
        assert result.device_id == "dev-abc"


# ---------------------------------------------------------------------------
# E — resolve_reuse_dispatch_surface: session_id primary lookup
# ---------------------------------------------------------------------------


class TestGroupE_SessionLookup:
    def test_E01_session_lookup_finds_eligible_binding(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-A", device_id="dev-A", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-A", "dev-A", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_E02_session_lookup_ignores_device_id_when_session_matches(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-B", device_id="dev-B", runtime=rt)
        # Pass wrong device_id; should still resolve by session_id
        result = resolve_reuse_dispatch_surface("sess-B", "wrong-device", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused


# ---------------------------------------------------------------------------
# F — resolve_reuse_dispatch_surface: device_id fallback when session_id empty
# ---------------------------------------------------------------------------


class TestGroupF_DeviceFallback:
    def test_F01_device_fallback_when_session_empty(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-F", device_id="dev-F", runtime=rt)
        result = resolve_reuse_dispatch_surface("", "dev-F", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_F02_device_fallback_returns_no_binding_on_miss(self):
        rt = _fresh_reuse_rt()
        result = resolve_reuse_dispatch_surface("", "dev-miss", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding


# ---------------------------------------------------------------------------
# G — resolve_reuse_dispatch_surface: device_id fallback when session lookup misses
# ---------------------------------------------------------------------------


class TestGroupG_SessionMissDeviceFallback:
    def test_G01_session_miss_falls_back_to_device(self):
        rt = _fresh_reuse_rt()
        # Binding stored with a different session_id but same device_id
        _make_eligible_binding(session_id="sess-G1", device_id="dev-G", runtime=rt)
        # Lookup with different session, same device → fallback to device
        result = resolve_reuse_dispatch_surface("sess-G2", "dev-G", reuse_runtime=rt)
        # Session lookup misses, device fallback succeeds
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused


# ---------------------------------------------------------------------------
# H — resolve_reuse_dispatch_surface: eligible binding → reused
# ---------------------------------------------------------------------------


class TestGroupH_EligibleReused:
    def test_H01_eligible_binding_returns_reused(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-H", device_id="dev-H", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-H", "dev-H", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_AI_reused_resolution_has_reuse_binding_set(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-H2", device_id="dev-H2", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-H2", "dev-H2", reuse_runtime=rt)
        assert result.reuse_binding is not None

    def test_H02_reused_reject_reason_empty(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-H3", device_id="dev-H3", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-H3", "dev-H3", reuse_runtime=rt)
        assert result.reject_reason == ""


# ---------------------------------------------------------------------------
# I — resolve_reuse_dispatch_surface: ineligible binding → rejected
# ---------------------------------------------------------------------------


class TestGroupI_IneligibleRejected:
    def test_I01_invalidated_binding_returns_rejected(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-I", device_id="dev-I", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="detach", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-I", "dev-I", reuse_runtime=rt)
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_AJ_rejected_has_reuse_binding_set(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-I2", device_id="dev-I2", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="disconnect", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-I2", "dev-I2", reuse_runtime=rt)
        assert result.reuse_binding is not None
        assert result.reuse_binding.is_invalidated()

    def test_M_reject_reason_reflects_invalidation_reason(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-M", device_id="dev-M", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="disconnect", runtime=rt)
        result = resolve_reuse_dispatch_surface("sess-M", "dev-M", reuse_runtime=rt)
        assert result.reject_reason == "disconnect"


# ---------------------------------------------------------------------------
# J/K/L — resolve_reuse_dispatch_surface: live attached_session cross-check
# ---------------------------------------------------------------------------


class TestGroupJKL_LiveSessionCrossCheck:
    def test_J01_attached_join_runtime_session_eligible(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-J", device_id="dev-J", runtime=rt)
        live_session = _StubSession(
            session_id="sess-J",
            device_id="dev-J",
            attachment_state=_AttachState("attached"),
            source_runtime_posture="join_runtime",
        )
        result = resolve_reuse_dispatch_surface(
            "sess-J", "dev-J", attached_session=live_session, reuse_runtime=rt
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_K01_detached_session_returns_rejected(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-K", device_id="dev-K", runtime=rt)
        live_session = _StubSession(
            session_id="sess-K",
            device_id="dev-K",
            attachment_state=_AttachState("detached"),
            source_runtime_posture="join_runtime",
        )
        result = resolve_reuse_dispatch_surface(
            "sess-K", "dev-K", attached_session=live_session, reuse_runtime=rt
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_L01_wrong_posture_returns_rejected(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-L", device_id="dev-L", runtime=rt)
        live_session = _StubSession(
            session_id="sess-L",
            device_id="dev-L",
            attachment_state=_AttachState("attached"),
            source_runtime_posture="control_only",
        )
        result = resolve_reuse_dispatch_surface(
            "sess-L", "dev-L", attached_session=live_session, reuse_runtime=rt
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected


# ---------------------------------------------------------------------------
# N — resolve_reuse_dispatch_surface: metadata forwarded
# ---------------------------------------------------------------------------


class TestGroupN_Metadata:
    def test_N01_metadata_forwarded_to_resolution(self):
        rt = _fresh_reuse_rt()
        meta = {"caller": "test", "tag": "42"}
        result = resolve_reuse_dispatch_surface("x", "y", reuse_runtime=rt, metadata=meta)
        assert result.metadata == meta

    def test_AS_dispatch_with_reuse_binding_metadata_forwarded(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        meta = {"caller": "dispatch_test"}
        result = dispatch_with_reuse_binding(
            "x", "y",
            _StubSession(session_id="x", device_id="y"),
            _StubContract(),
            _StubTracker(),
            reuse_runtime=rt,
            dispatch_runtime=drt,
            metadata=meta,
        )
        assert result.metadata == meta


# ---------------------------------------------------------------------------
# O/P/Q/R/S — write_back_dispatch_binding_id
# ---------------------------------------------------------------------------


class TestGroupOPQRS_WriteBack:
    def test_O01_updates_dispatch_binding_id_on_reuse_binding(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-O", device_id="dev-O", runtime=rt)
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="sess-O",
            device_id="dev-O",
            reuse_binding=binding,
        )
        updated = write_back_dispatch_binding_id(resolution, "bind-999", reuse_runtime=rt)
        assert updated.reuse_binding is not None
        assert updated.reuse_binding.dispatch_binding_id == "bind-999"

    def test_AU_updated_reuse_binding_carries_dispatch_binding_id(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-AU", device_id="dev-AU", runtime=rt)
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="sess-AU",
            device_id="dev-AU",
            reuse_binding=binding,
        )
        updated = write_back_dispatch_binding_id(resolution, "bind-AU", reuse_runtime=rt)
        # Verify via get_reuse_binding that the ring-buffer reflects the update
        latest = get_reuse_binding("sess-AU", runtime=rt)
        assert latest is not None
        assert latest.dispatch_binding_id == "bind-AU"

    def test_P01_identity_fields_preserved_after_write_back(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-P", device_id="dev-P", runtime=rt)
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="sess-P",
            device_id="dev-P",
            reuse_binding=binding,
        )
        updated = write_back_dispatch_binding_id(resolution, "bind-X", reuse_runtime=rt)
        assert updated.reuse_binding.identity.session_id == "sess-P"
        assert updated.reuse_binding.identity.device_id == "dev-P"
        assert updated.reuse_binding.identity.reuse_binding_id == binding.identity.reuse_binding_id

    def test_Q01_no_binding_resolution_returned_unchanged(self):
        rt = _fresh_reuse_rt()
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.no_binding,
            session_id="sess-Q",
            device_id="dev-Q",
            reuse_binding=None,
        )
        updated = write_back_dispatch_binding_id(resolution, "bind-X", reuse_runtime=rt)
        assert updated is resolution

    def test_R01_empty_dispatch_binding_id_returns_unchanged(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-R", device_id="dev-R", runtime=rt)
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="sess-R",
            device_id="dev-R",
            reuse_binding=binding,
        )
        updated = write_back_dispatch_binding_id(resolution, "", reuse_runtime=rt)
        assert updated is resolution

    def test_S01_returns_new_resolution_original_not_mutated(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-S", device_id="dev-S", runtime=rt)
        original_dispatch_id = binding.dispatch_binding_id
        resolution = ReuseDispatchResolution(
            resolution_kind=ReuseDispatchResolutionKind.reused,
            session_id="sess-S",
            device_id="dev-S",
            reuse_binding=binding,
        )
        updated = write_back_dispatch_binding_id(resolution, "bind-new", reuse_runtime=rt)
        assert updated is not resolution
        # Original resolution's reuse_binding unchanged
        assert resolution.reuse_binding.dispatch_binding_id == original_dispatch_id


# ---------------------------------------------------------------------------
# T/U/V/W/X — dispatch_with_reuse_binding
# ---------------------------------------------------------------------------


class TestGroupTUVWX_DispatchWithReuseBinding:
    def test_T01_eligible_binding_returns_reused(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        _make_eligible_binding(session_id="sess-T", device_id="dev-T", runtime=rt)
        session = _StubSession(session_id="sess-T", device_id="dev-T")
        result = dispatch_with_reuse_binding(
            "sess-T", "dev-T",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_AL_reused_dispatch_binding_is_none(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        _make_eligible_binding(session_id="sess-AL", device_id="dev-AL", runtime=rt)
        session = _StubSession(session_id="sess-AL", device_id="dev-AL")
        result = dispatch_with_reuse_binding(
            "sess-AL", "dev-AL",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.dispatch_binding is None

    def test_U01_no_binding_creates_new_dispatch_binding(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-U", device_id="dev-U")
        result = dispatch_with_reuse_binding(
            "sess-U", "dev-U",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.new_binding

    def test_V01_new_binding_resolution_carries_dispatch_binding(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-V", device_id="dev-V")
        result = dispatch_with_reuse_binding(
            "sess-V", "dev-V",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.dispatch_binding is not None

    def test_AM_new_binding_dispatch_binding_not_none(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-AM", device_id="dev-AM")
        result = dispatch_with_reuse_binding(
            "sess-AM", "dev-AM",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.is_new_binding()
        assert result.dispatch_binding is not None

    def test_W01_rejected_binding_returns_rejected_no_new_binding(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        binding = _make_eligible_binding(session_id="sess-W", device_id="dev-W", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="detach", runtime=rt)
        session = _StubSession(session_id="sess-W", device_id="dev-W")
        result = dispatch_with_reuse_binding(
            "sess-W", "dev-W",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert result.dispatch_binding is None

    def test_X01_new_binding_write_back_registered(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-X", device_id="dev-X")
        result = dispatch_with_reuse_binding(
            "sess-X", "dev-X",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        # The dispatch binding's binding_id should be written back to the reuse binding
        if result.reuse_binding is not None:
            assert result.reuse_binding.dispatch_binding_id != ""
            if result.dispatch_binding is not None:
                assert result.reuse_binding.dispatch_binding_id == result.dispatch_binding.identity.binding_id

    def test_AH_new_binding_dispatch_record_is_non_rejected(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-AH", device_id="dev-AH")
        result = dispatch_with_reuse_binding(
            "sess-AH", "dev-AH",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.new_binding
        assert result.dispatch_binding is not None

    def test_AV_reused_resolution_id_preserved(self):
        """dispatch_with_reuse_binding reused path preserves resolution_id."""
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        _make_eligible_binding(session_id="sess-AV", device_id="dev-AV", runtime=rt)
        session = _StubSession(session_id="sess-AV", device_id="dev-AV")
        result = dispatch_with_reuse_binding(
            "sess-AV", "dev-AV",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert isinstance(result.resolution_id, str)
        uuid.UUID(result.resolution_id)


# ---------------------------------------------------------------------------
# Y — Integration: same session multi-dispatch reuse (required outcome 1)
# ---------------------------------------------------------------------------


class TestGroupY_SameSessionMultiDispatchReuse:
    def test_Y01_first_dispatch_no_binding_creates_new(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        session = _StubSession(session_id="sess-Y", device_id="dev-Y")
        r1 = dispatch_with_reuse_binding(
            "sess-Y", "dev-Y",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert r1.resolution_kind == ReuseDispatchResolutionKind.new_binding

    def test_Y02_second_dispatch_reuses_surface(self):
        """After establishing a reuse binding, subsequent resolve returns reused."""
        rt = _fresh_reuse_rt()
        # Establish an eligible reuse binding to simulate a prior dispatch that
        # set up the surface.
        _make_eligible_binding(session_id="sess-Y2", device_id="dev-Y2", runtime=rt)
        # Second dispatch: should find and reuse the binding
        r2 = resolve_reuse_dispatch_surface("sess-Y2", "dev-Y2", reuse_runtime=rt)
        assert r2.resolution_kind == ReuseDispatchResolutionKind.reused
        assert r2.is_reusable()

    def test_Y03_multiple_dispatches_all_reuse(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-Y3", device_id="dev-Y3", runtime=rt)
        for _ in range(5):
            r = resolve_reuse_dispatch_surface("sess-Y3", "dev-Y3", reuse_runtime=rt)
            assert r.resolution_kind == ReuseDispatchResolutionKind.reused


# ---------------------------------------------------------------------------
# Z — Integration: invalidated binding rejection (required outcome 2)
# ---------------------------------------------------------------------------


class TestGroupZ_InvalidatedBindingRejection:
    def test_Z01_invalidated_binding_is_rejected(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-Z", device_id="dev-Z", runtime=rt)
        assert resolve_reuse_dispatch_surface("sess-Z", "dev-Z", reuse_runtime=rt).resolution_kind == ReuseDispatchResolutionKind.reused
        # Invalidate
        invalidate_reuse_binding(binding, lifecycle_signal="invalidate", runtime=rt)
        r = resolve_reuse_dispatch_surface("sess-Z", "dev-Z", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_Z02_dispatch_after_invalidation_is_rejected(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        binding = _make_eligible_binding(session_id="sess-Z2", device_id="dev-Z2", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="detach", runtime=rt)
        session = _StubSession(session_id="sess-Z2", device_id="dev-Z2")
        r = dispatch_with_reuse_binding(
            "sess-Z2", "dev-Z2",
            session, _StubContract(), _StubTracker(),
            reuse_runtime=rt, dispatch_runtime=drt,
        )
        assert r.is_rejected()


# ---------------------------------------------------------------------------
# AA/AB — Integration: detach/disconnect → no reuse (required outcome 3)
# ---------------------------------------------------------------------------


class TestGroupAAB_DetachDisconnectNoReuse:
    def test_AA01_detach_lifecycle_signal_prevents_reuse(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-AA", device_id="dev-AA", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="detach", runtime=rt)
        r = resolve_reuse_dispatch_surface("sess-AA", "dev-AA", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert r.reject_reason == "detach"

    def test_AB01_disconnect_lifecycle_signal_prevents_reuse(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-AB", device_id="dev-AB", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="disconnect", runtime=rt)
        r = resolve_reuse_dispatch_surface("sess-AB", "dev-AB", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert r.reject_reason == "disconnect"

    def test_AQ01_disable_lifecycle_signal_prevents_reuse(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-AQ", device_id="dev-AQ", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="disable", runtime=rt)
        r = resolve_reuse_dispatch_surface("sess-AQ", "dev-AQ", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert r.reject_reason == "disable"

    def test_AR01_invalidate_lifecycle_signal_prevents_reuse(self):
        rt = _fresh_reuse_rt()
        binding = _make_eligible_binding(session_id="sess-AR", device_id="dev-AR", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="invalidate", runtime=rt)
        r = resolve_reuse_dispatch_surface("sess-AR", "dev-AR", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert r.reject_reason == "invalidate"

    def test_AA02_live_session_detached_cross_check_rejected(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-AA2", device_id="dev-AA2", runtime=rt)
        live_session = _StubSession(
            session_id="sess-AA2",
            device_id="dev-AA2",
            attachment_state=_AttachState("detached"),
            source_runtime_posture="join_runtime",
        )
        r = resolve_reuse_dispatch_surface(
            "sess-AA2", "dev-AA2",
            attached_session=live_session,
            reuse_runtime=rt,
        )
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_AB02_live_session_disconnected_cross_check_rejected(self):
        rt = _fresh_reuse_rt()
        _make_eligible_binding(session_id="sess-AB2", device_id="dev-AB2", runtime=rt)
        live_session = _StubSession(
            session_id="sess-AB2",
            device_id="dev-AB2",
            attachment_state=_AttachState("disconnected"),
            source_runtime_posture="join_runtime",
        )
        r = resolve_reuse_dispatch_surface(
            "sess-AB2", "dev-AB2",
            attached_session=live_session,
            reuse_runtime=rt,
        )
        assert r.resolution_kind == ReuseDispatchResolutionKind.rejected


# ---------------------------------------------------------------------------
# AC — Integration: re-establish after reattach (required outcome 4)
# ---------------------------------------------------------------------------


class TestGroupAC_ReestablishAfterReattach:
    def test_AC01_after_invalidation_new_binding_eligible(self):
        rt = _fresh_reuse_rt()
        # Establish and then invalidate
        binding = _make_eligible_binding(session_id="sess-AC", device_id="dev-AC", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="detach", runtime=rt)
        r_rejected = resolve_reuse_dispatch_surface("sess-AC", "dev-AC", reuse_runtime=rt)
        assert r_rejected.resolution_kind == ReuseDispatchResolutionKind.rejected

        # Re-attach: establish a new reuse binding for same session
        establish_reuse_binding(
            session_id="sess-AC", device_id="dev-AC",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        r_reused = resolve_reuse_dispatch_surface("sess-AC", "dev-AC", reuse_runtime=rt)
        assert r_reused.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_AC02_new_session_after_reattach_is_reusable(self):
        rt = _fresh_reuse_rt()
        # Original session invalidated
        binding = _make_eligible_binding(session_id="sess-AC-old", device_id="dev-AC2", runtime=rt)
        invalidate_reuse_binding(binding, lifecycle_signal="disconnect", runtime=rt)

        # New session (reattach with new session_id)
        establish_reuse_binding(
            session_id="sess-AC-new", device_id="dev-AC2",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        r = resolve_reuse_dispatch_surface("sess-AC-new", "dev-AC2", reuse_runtime=rt)
        assert r.resolution_kind == ReuseDispatchResolutionKind.reused

    def test_AC03_full_lifecycle_reattach_dispatch_flow(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()

        # First attach + dispatch
        establish_reuse_binding(
            session_id="sess-lifecycle", device_id="dev-lifecycle",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        r1 = resolve_reuse_dispatch_surface("sess-lifecycle", "dev-lifecycle", reuse_runtime=rt)
        assert r1.is_reusable()

        # Detach
        invalidate_reuse_binding(r1.reuse_binding, lifecycle_signal="detach", runtime=rt)
        r2 = resolve_reuse_dispatch_surface("sess-lifecycle", "dev-lifecycle", reuse_runtime=rt)
        assert r2.is_rejected()

        # Reattach with new session
        establish_reuse_binding(
            session_id="sess-lifecycle-v2", device_id="dev-lifecycle",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        r3 = resolve_reuse_dispatch_surface("sess-lifecycle-v2", "dev-lifecycle", reuse_runtime=rt)
        assert r3.is_reusable()


# ---------------------------------------------------------------------------
# AD — core.runtime re-exports
# ---------------------------------------------------------------------------


class TestGroupAD_CoreRuntimeReExports:
    def test_AD01_all_pr17_symbols_accessible_from_core_runtime(self):
        from core.runtime import (  # noqa: PLC0415
            ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY,
            ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL,
            REUSE_DISPATCH_LOOKUP_PRECEDES_DISPATCH_POLICY,
            REUSE_DISPATCH_ELIGIBILITY_GATE_IS_MANDATORY_POLICY,
            REUSE_DISPATCH_ELIGIBLE_SURFACE_IS_REUSED_POLICY,
            REUSE_DISPATCH_INELIGIBLE_BINDING_IS_REJECTED_POLICY,
            REUSE_DISPATCH_NO_BINDING_ALLOWS_NEW_DISPATCH_POLICY,
            REUSE_DISPATCH_WRITE_BACK_IS_MANDATORY_POLICY,
            REUSE_DISPATCH_INVALIDATION_HARD_STOP_POLICY,
            REUSE_DISPATCH_SESSION_LOOKUP_PRECEDES_DEVICE_LOOKUP_POLICY,
            REUSE_DISPATCH_LIVE_SESSION_CROSS_CHECK_IS_OPTIONAL_POLICY,
            REUSE_DISPATCH_RESOLUTION_IS_IMMUTABLE_POLICY,
            REUSE_DISPATCH_DETACH_TRIGGERS_INELIGIBLE_RESOLUTION_POLICY,
            ReuseDispatchResolutionKind,
            ReuseDispatchResolution,
            resolve_reuse_dispatch_surface,
            write_back_dispatch_binding_id,
            dispatch_with_reuse_binding,
        )
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL
        assert ReuseDispatchResolutionKind.reused.value == "reused"


# ---------------------------------------------------------------------------
# AE — projection.py sentinel
# ---------------------------------------------------------------------------


class TestGroupAE_ProjectionSentinel:
    def test_AE01_projection_sentinel_present_and_not_unavailable(self):
        from core.routes.projection import (  # noqa: PLC0415
            ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17,
        )
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17
        assert "UNAVAILABLE" not in ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17
        assert "PR17" in ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17
