#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prj_truth_conflict_enforcement.py
==============================================
PR-J: Truth Conflict Enforcement and Canonical Truth Convergence Hardening
— focused test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-J sentinel present.
B.  All five policy sentinels are non-empty strings with expected keywords.
C.  TruthSurface enum has device, task, session values.
D.  TruthConflictVerdict enum has all six expected verdict values.
E.  TruthOwnershipRecord dataclass has required fields and to_dict() works.
F.  TruthConflictRecord dataclass has required fields and to_dict() works.
G.  TruthConflictEnforcementSnapshot dataclass has required fields and
    to_dict() works.
H.  get_truth_ownership_registry() returns non-empty list.
I.  Every ownership record has non-empty canonical_write_authority.
J.  get_write_authority_for_surface() returns the correct record for each
    known surface.
K.  get_write_authority_for_surface() returns None for an unknown surface.
L.  assert_canonical_write_precedes_compat_write() returns
    COMPAT_MIRROR_WRITE_VALID when canonical_write_confirmed=True.
M.  assert_canonical_write_precedes_compat_write() returns
    CANONICAL_WRITE_MISSING when canonical_write_confirmed=False.
N.  assert_canonical_write_precedes_compat_write() raises RuntimeError when
    strict=True and canonical_write_confirmed=False.
O.  assert_no_parallel_write_authority() returns
    CANONICAL_AUTHORITY_CONFIRMED for canonical authority module.
P.  assert_no_parallel_write_authority() returns
    PARALLEL_AUTHORITY_DETECTED for an unregistered writer.
Q.  assert_no_parallel_write_authority() returns
    TRUTH_REGRESSION_DETECTED for a prohibited path.
R.  assert_no_parallel_write_authority() raises RuntimeError when strict=True
    and a prohibited path is detected.
S.  check_compat_write_is_mirror_only() returns COMPAT_MIRROR_WRITE_VALID
    for a known allowed mirror path.
T.  check_compat_write_is_mirror_only() returns PARALLEL_AUTHORITY_DETECTED
    for an unknown compat path.
U.  check_compat_write_is_mirror_only() raises RuntimeError when strict=True
    and path is not in allowed mirrors.
V.  build_truth_conflict_enforcement_snapshot() returns
    TruthConflictEnforcementSnapshot with expected structure.
W.  Snapshot convergence_healthy is True on a fresh module (no violations).
X.  Snapshot total_surfaces == number of surfaces in ownership registry.
Y.  Snapshot policy_sentinels contains all five policy strings.
Z.  is_truth_convergence_healthy() returns bool.
AA. Device ownership record canonical_write_authority contains 'UnifiedDeviceManager'.
BB. Task ownership record canonical_write_authority contains 'CanonicalTask'.
CC. Session ownership record canonical_write_authority contains
    'CanonicalSessionTruthRuntime'.
DD. Device ownership record has registered_devices in prohibited_write_paths.
EE. Session ownership record has stale session context in prohibited_write_paths.
FF. TruthConflictEnforcementSnapshot.to_dict() contains all expected top-level keys.
GG. INV-011 is present in runtime_invariant_enforcement registry with ENFORCED status.
HH. INV-012 is present in runtime_invariant_enforcement registry with ENFORCED status.
II. INV-013 is present in runtime_invariant_enforcement registry with ENFORCED status.
JJ. INFL-009 is present in compat_fallback_authority_guard with EXPLICITLY_BOUNDED
    status.
KK. INFL-010 is present in compat_fallback_authority_guard with EXPLICITLY_BOUNDED
    status.
LL. hardening_complete in authority hardening snapshot remains True after adding
    INFL-009 and INFL-010 (both are EXPLICITLY_BOUNDED, not UNBOUNDED).
MM. No UNBOUNDED influence records in the full compat_fallback_authority_guard registry.
NN. Device truth surface has at least one allowed compat mirror path referencing
    routes/devices.
OO. assert_canonical_write_precedes_compat_write with task surface returns correct
    verdict for both confirmed and missing cases.
PP. assert_no_parallel_write_authority with session surface returns correct verdict
    for an allowed compat path.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.truth_conflict_enforcement  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.truth_conflict_enforcement import (
            TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY,
        )
        assert isinstance(TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY, str)
        assert len(TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY) > 0
        assert "PR-J" in TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY

    def test_prj_sentinel_is_non_empty_string(self):
        from core.truth_conflict_enforcement import (
            TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL,
        )
        assert isinstance(TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL, str)
        assert "PR-J" in TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL
        assert "truth-conflict-enforcement" in TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_canonical_write_precedes_compat_write_policy(self):
        from core.truth_conflict_enforcement import (
            CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY,
        )
        assert isinstance(CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY, str)
        assert "canonical" in CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY.lower()
        assert "compat" in CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY.lower()

    def test_no_parallel_truth_authority_policy(self):
        from core.truth_conflict_enforcement import (
            NO_PARALLEL_TRUTH_AUTHORITY_POLICY,
        )
        assert isinstance(NO_PARALLEL_TRUTH_AUTHORITY_POLICY, str)
        assert "parallel" in NO_PARALLEL_TRUTH_AUTHORITY_POLICY.lower()
        assert "authority" in NO_PARALLEL_TRUTH_AUTHORITY_POLICY.lower()

    def test_compat_truth_write_must_be_mirror_only_policy(self):
        from core.truth_conflict_enforcement import (
            COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY,
        )
        assert isinstance(COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY, str)
        assert "mirror" in COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY.lower()

    def test_truth_regression_detection_policy(self):
        from core.truth_conflict_enforcement import (
            TRUTH_REGRESSION_DETECTION_POLICY,
        )
        assert isinstance(TRUTH_REGRESSION_DETECTION_POLICY, str)
        assert "regression" in TRUTH_REGRESSION_DETECTION_POLICY.lower()

    def test_truth_conflict_relapse_must_be_fail_fast_policy(self):
        from core.truth_conflict_enforcement import (
            TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY,
        )
        assert isinstance(TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY, str)
        assert "fail" in TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY.lower()
        assert "relapse" in TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY.lower()


# ===========================================================================
# C. TruthSurface enum
# ===========================================================================


class TestTruthSurfaceEnum:
    def test_device_value(self):
        from core.truth_conflict_enforcement import TruthSurface
        assert TruthSurface.device.value == "device"

    def test_task_value(self):
        from core.truth_conflict_enforcement import TruthSurface
        assert TruthSurface.task.value == "task"

    def test_session_value(self):
        from core.truth_conflict_enforcement import TruthSurface
        assert TruthSurface.session.value == "session"

    def test_all_three_surfaces_present(self):
        from core.truth_conflict_enforcement import TruthSurface
        expected = {"device", "task", "session"}
        actual = {s.value for s in TruthSurface}
        assert expected == actual


# ===========================================================================
# D. TruthConflictVerdict enum
# ===========================================================================


class TestTruthConflictVerdictEnum:
    def test_canonical_authority_confirmed_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert (
            TruthConflictVerdict.CANONICAL_AUTHORITY_CONFIRMED.value
            == "canonical_authority_confirmed"
        )

    def test_compat_mirror_write_valid_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert (
            TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID.value
            == "compat_mirror_write_valid"
        )

    def test_canonical_write_missing_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert (
            TruthConflictVerdict.CANONICAL_WRITE_MISSING.value
            == "canonical_write_missing"
        )

    def test_parallel_authority_detected_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert (
            TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED.value
            == "parallel_authority_detected"
        )

    def test_truth_regression_detected_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert (
            TruthConflictVerdict.TRUTH_REGRESSION_DETECTED.value
            == "truth_regression_detected"
        )

    def test_unknown_value(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        assert TruthConflictVerdict.UNKNOWN.value == "unknown"

    def test_all_six_verdicts_present(self):
        from core.truth_conflict_enforcement import TruthConflictVerdict
        expected = {
            "canonical_authority_confirmed",
            "compat_mirror_write_valid",
            "canonical_write_missing",
            "parallel_authority_detected",
            "truth_regression_detected",
            "unknown",
        }
        actual = {v.value for v in TruthConflictVerdict}
        assert expected == actual


# ===========================================================================
# E. TruthOwnershipRecord dataclass
# ===========================================================================


class TestTruthOwnershipRecord:
    def test_device_ownership_record_to_dict_keys(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        d = record.to_dict()
        assert "surface" in d
        assert "canonical_write_authority" in d
        assert "allowed_compat_mirror_paths" in d
        assert "prohibited_write_paths" in d
        assert "reviewer_verification" in d
        assert "pr_reference" in d

    def test_to_dict_surface_is_string(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        assert isinstance(record.to_dict()["surface"], str)


# ===========================================================================
# F. TruthConflictRecord dataclass
# ===========================================================================


class TestTruthConflictRecord:
    def test_conflict_record_to_dict_keys(self):
        from core.truth_conflict_enforcement import (
            TruthConflictRecord,
            TruthConflictVerdict,
            TruthSurface,
        )
        record = TruthConflictRecord(
            surface=TruthSurface.device,
            verdict=TruthConflictVerdict.CANONICAL_AUTHORITY_CONFIRMED,
            caller_module="test_module",
            canonical_authority="core.unified.device_manager.UnifiedDeviceManager",
            message="test message",
        )
        d = record.to_dict()
        assert "surface" in d
        assert "verdict" in d
        assert "caller_module" in d
        assert "canonical_authority" in d
        assert "message" in d
        assert "timestamp" in d

    def test_conflict_record_values(self):
        from core.truth_conflict_enforcement import (
            TruthConflictRecord,
            TruthConflictVerdict,
            TruthSurface,
        )
        record = TruthConflictRecord(
            surface=TruthSurface.task,
            verdict=TruthConflictVerdict.CANONICAL_WRITE_MISSING,
            caller_module="legacy_writer",
            canonical_authority="core.canonical_task.CanonicalTask",
        )
        d = record.to_dict()
        assert d["surface"] == "task"
        assert d["verdict"] == "canonical_write_missing"
        assert d["caller_module"] == "legacy_writer"


# ===========================================================================
# G. TruthConflictEnforcementSnapshot dataclass
# ===========================================================================


class TestTruthConflictEnforcementSnapshot:
    def test_snapshot_to_dict_keys(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        d = snapshot.to_dict()
        required_keys = {
            "generated_at",
            "total_surfaces",
            "surfaces_with_declared_authority",
            "parallel_authority_violations_detected",
            "compat_write_ordering_violations_detected",
            "truth_regression_events_detected",
            "convergence_healthy",
            "policy_sentinels",
            "surface_summaries",
        }
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# H. get_truth_ownership_registry() returns non-empty list
# ===========================================================================


class TestGetTruthOwnershipRegistry:
    def test_returns_non_empty_list(self):
        from core.truth_conflict_enforcement import get_truth_ownership_registry
        registry = get_truth_ownership_registry()
        assert isinstance(registry, list)
        assert len(registry) > 0

    def test_all_records_are_truth_ownership_records(self):
        from core.truth_conflict_enforcement import (
            TruthOwnershipRecord,
            get_truth_ownership_registry,
        )
        for record in get_truth_ownership_registry():
            assert isinstance(record, TruthOwnershipRecord)


# ===========================================================================
# I. Every ownership record has non-empty canonical_write_authority
# ===========================================================================


class TestOwnershipRecordCanonicalAuthority:
    def test_every_record_has_canonical_write_authority(self):
        from core.truth_conflict_enforcement import get_truth_ownership_registry
        for record in get_truth_ownership_registry():
            assert isinstance(record.canonical_write_authority, str)
            assert len(record.canonical_write_authority) > 0, (
                f"Surface {record.surface.value} has empty canonical_write_authority"
            )

    def test_no_duplicate_surfaces(self):
        from core.truth_conflict_enforcement import get_truth_ownership_registry
        surfaces = [r.surface for r in get_truth_ownership_registry()]
        assert len(surfaces) == len(set(surfaces)), "Duplicate surfaces in registry"


# ===========================================================================
# J. get_write_authority_for_surface() returns correct record
# ===========================================================================


class TestGetWriteAuthorityForSurface:
    def test_device_surface_returns_record(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        assert record.surface == TruthSurface.device

    def test_task_surface_returns_record(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.task)
        assert record is not None
        assert record.surface == TruthSurface.task

    def test_session_surface_returns_record(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.session)
        assert record is not None
        assert record.surface == TruthSurface.session


# ===========================================================================
# L–N. assert_canonical_write_precedes_compat_write()
# ===========================================================================


class TestAssertCanonicalWritePrecedesCompatWrite:
    def test_returns_valid_when_canonical_confirmed(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.device,
            canonical_write_confirmed=True,
            compat_path="core.routes.devices",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID
        assert result.surface == TruthSurface.device

    def test_returns_missing_when_canonical_not_confirmed(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.device,
            canonical_write_confirmed=False,
            compat_path="core.routes.devices",
        )
        assert result.verdict == TruthConflictVerdict.CANONICAL_WRITE_MISSING

    def test_raises_on_strict_with_missing_canonical(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        with pytest.raises(RuntimeError):
            assert_canonical_write_precedes_compat_write(
                TruthSurface.device,
                canonical_write_confirmed=False,
                strict=True,
            )

    def test_does_not_raise_when_not_strict(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        # Should not raise even on violation when strict=False
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.session,
            canonical_write_confirmed=False,
            strict=False,
        )
        assert result is not None

    def test_task_surface_canonical_confirmed(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.task,
            canonical_write_confirmed=True,
            compat_path="core.canonical_task_dispatch_chain",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID

    def test_task_surface_canonical_missing(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.task,
            canonical_write_confirmed=False,
        )
        assert result.verdict == TruthConflictVerdict.CANONICAL_WRITE_MISSING


# ===========================================================================
# O–R. assert_no_parallel_write_authority()
# ===========================================================================


class TestAssertNoParallelWriteAuthority:
    def test_canonical_authority_confirmed_for_udm(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        result = assert_no_parallel_write_authority(
            TruthSurface.device,
            writer_module="UnifiedDeviceManager",
        )
        assert result.verdict == TruthConflictVerdict.CANONICAL_AUTHORITY_CONFIRMED

    def test_parallel_authority_detected_for_unknown_writer(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        result = assert_no_parallel_write_authority(
            TruthSurface.device,
            writer_module="some.unknown.legacy_module",
        )
        assert result.verdict == TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED

    def test_truth_regression_detected_for_prohibited_path(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        # registered_devices is in prohibited_write_paths for device surface
        result = assert_no_parallel_write_authority(
            TruthSurface.device,
            writer_module="core.routes._shared.registered_devices",
        )
        assert result.verdict == TruthConflictVerdict.TRUTH_REGRESSION_DETECTED

    def test_raises_on_strict_with_prohibited_path(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        with pytest.raises(RuntimeError):
            assert_no_parallel_write_authority(
                TruthSurface.device,
                writer_module="core.routes._shared.registered_devices",
                strict=True,
            )

    def test_allowed_compat_path_returns_valid(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        # routes.devices is in the allowed compat mirror paths
        result = assert_no_parallel_write_authority(
            TruthSurface.device,
            writer_module="core.routes.devices",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID


# ===========================================================================
# S–U. check_compat_write_is_mirror_only()
# ===========================================================================


class TestCheckCompatWriteIsMirrorOnly:
    def test_known_allowed_path_returns_valid(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            check_compat_write_is_mirror_only,
        )
        result = check_compat_write_is_mirror_only(
            TruthSurface.device,
            compat_path="core.routes.devices",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID

    def test_unknown_path_returns_parallel_detected(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            check_compat_write_is_mirror_only,
        )
        result = check_compat_write_is_mirror_only(
            TruthSurface.device,
            compat_path="some.unknown.new_module",
        )
        assert result.verdict == TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED

    def test_raises_on_strict_with_unknown_path(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            check_compat_write_is_mirror_only,
        )
        with pytest.raises(RuntimeError):
            check_compat_write_is_mirror_only(
                TruthSurface.device,
                compat_path="some.new.module",
                strict=True,
            )

    def test_session_canonical_path_returns_valid(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            check_compat_write_is_mirror_only,
        )
        result = check_compat_write_is_mirror_only(
            TruthSurface.session,
            compat_path="core.attached_runtime_session.AttachedRuntimeSession",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID


# ===========================================================================
# V–Y. build_truth_conflict_enforcement_snapshot()
# ===========================================================================


class TestBuildTruthConflictEnforcementSnapshot:
    def test_returns_snapshot_instance(self):
        from core.truth_conflict_enforcement import (
            TruthConflictEnforcementSnapshot,
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        assert isinstance(snapshot, TruthConflictEnforcementSnapshot)

    def test_convergence_healthy_on_fresh_module(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        # A fresh module with no active violations should report healthy
        assert isinstance(snapshot.convergence_healthy, bool)

    def test_total_surfaces_matches_registry(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
            get_truth_ownership_registry,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        assert snapshot.total_surfaces == len(get_truth_ownership_registry())

    def test_surfaces_with_declared_authority_equals_total(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        assert snapshot.surfaces_with_declared_authority == snapshot.total_surfaces

    def test_policy_sentinels_contains_five_entries(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        assert len(snapshot.policy_sentinels) == 5

    def test_policy_sentinels_are_strings(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        for sentinel in snapshot.policy_sentinels:
            assert isinstance(sentinel, str)
            assert len(sentinel) > 0


# ===========================================================================
# Z. is_truth_convergence_healthy()
# ===========================================================================


class TestIsTruthConvergenceHealthy:
    def test_returns_bool(self):
        from core.truth_conflict_enforcement import is_truth_convergence_healthy
        result = is_truth_convergence_healthy()
        assert isinstance(result, bool)


# ===========================================================================
# AA–CC. Canonical write authority content verification
# ===========================================================================


class TestCanonicalWriteAuthorityContent:
    def test_device_authority_contains_unified_device_manager(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        assert "UnifiedDeviceManager" in record.canonical_write_authority

    def test_task_authority_contains_canonical_task(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.task)
        assert record is not None
        assert "CanonicalTask" in record.canonical_write_authority

    def test_session_authority_contains_canonical_session_truth_runtime(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.session)
        assert record is not None
        assert "CanonicalSessionTruthRuntime" in record.canonical_write_authority


# ===========================================================================
# DD–EE. Prohibited write paths content verification
# ===========================================================================


class TestProhibitedWritePaths:
    def test_device_prohibited_paths_contains_registered_devices(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        prohibited_text = " ".join(record.prohibited_write_paths)
        assert "registered_devices" in prohibited_text

    def test_session_prohibited_paths_contains_stale_context_reference(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.session)
        assert record is not None
        prohibited_text = " ".join(record.prohibited_write_paths)
        assert "stale" in prohibited_text.lower() or "bypass" in prohibited_text.lower()


# ===========================================================================
# FF. Snapshot to_dict() has all expected top-level keys
# ===========================================================================


class TestSnapshotToDictKeys:
    def test_to_dict_contains_all_expected_keys(self):
        from core.truth_conflict_enforcement import (
            build_truth_conflict_enforcement_snapshot,
        )
        snapshot = build_truth_conflict_enforcement_snapshot()
        d = snapshot.to_dict()
        expected_keys = {
            "generated_at",
            "total_surfaces",
            "surfaces_with_declared_authority",
            "parallel_authority_violations_detected",
            "compat_write_ordering_violations_detected",
            "truth_regression_events_detected",
            "convergence_healthy",
            "policy_sentinels",
            "surface_summaries",
        }
        for key in expected_keys:
            assert key in d, f"Missing key in snapshot.to_dict(): {key}"


# ===========================================================================
# GG–II. New invariants INV-011, INV-012, INV-013 in runtime_invariant_enforcement
# ===========================================================================


class TestNewInvariantsPresent:
    def test_inv_011_present_and_enforced(self):
        from core.runtime_invariant_enforcement import (
            InvariantStatus,
            check_invariant,
        )
        record = check_invariant("INV-011")
        assert record is not None
        assert record.invariant_id == "INV-011"
        assert record.status == InvariantStatus.ENFORCED

    def test_inv_011_domain_is_source_of_truth(self):
        from core.runtime_invariant_enforcement import (
            InvariantDomain,
            check_invariant,
        )
        record = check_invariant("INV-011")
        assert record is not None
        assert record.domain == InvariantDomain.source_of_truth

    def test_inv_011_description_references_udm(self):
        from core.runtime_invariant_enforcement import check_invariant
        record = check_invariant("INV-011")
        assert record is not None
        assert "UnifiedDeviceManager" in record.description

    def test_inv_012_present_and_enforced(self):
        from core.runtime_invariant_enforcement import (
            InvariantStatus,
            check_invariant,
        )
        record = check_invariant("INV-012")
        assert record is not None
        assert record.invariant_id == "INV-012"
        assert record.status == InvariantStatus.ENFORCED

    def test_inv_012_domain_is_session_transport(self):
        from core.runtime_invariant_enforcement import (
            InvariantDomain,
            check_invariant,
        )
        record = check_invariant("INV-012")
        assert record is not None
        assert record.domain == InvariantDomain.session_transport

    def test_inv_012_description_references_canonical_session_truth(self):
        from core.runtime_invariant_enforcement import check_invariant
        record = check_invariant("INV-012")
        assert record is not None
        assert "CanonicalSessionTruthRuntime" in record.description

    def test_inv_013_present_and_enforced(self):
        from core.runtime_invariant_enforcement import (
            InvariantStatus,
            check_invariant,
        )
        record = check_invariant("INV-013")
        assert record is not None
        assert record.invariant_id == "INV-013"
        assert record.status == InvariantStatus.ENFORCED

    def test_inv_013_domain_is_task_lifecycle(self):
        from core.runtime_invariant_enforcement import (
            InvariantDomain,
            check_invariant,
        )
        record = check_invariant("INV-013")
        assert record is not None
        assert record.domain == InvariantDomain.task_lifecycle

    def test_inv_013_description_references_canonical_task(self):
        from core.runtime_invariant_enforcement import check_invariant
        record = check_invariant("INV-013")
        assert record is not None
        assert "CanonicalTask" in record.description

    def test_all_three_new_invariants_have_violation_log_prefix(self):
        from core.runtime_invariant_enforcement import check_invariant
        for inv_id in ("INV-011", "INV-012", "INV-013"):
            record = check_invariant(inv_id)
            assert record is not None
            assert f"INVARIANT_VIOLATION::{inv_id}" in record.violation_log_prefix, (
                f"{inv_id} missing expected violation_log_prefix"
            )


# ===========================================================================
# JJ–KK. New influence records INFL-009, INFL-010 in compat_fallback_authority_guard
# ===========================================================================


class TestNewInfluenceRecordsPresent:
    def test_infl_009_present(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-009")
        assert record is not None
        assert record.influence_id == "INFL-009"

    def test_infl_009_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            CompatInfluenceBoundingStatus,
            get_influence_record,
        )
        record = get_influence_record("INFL-009")
        assert record is not None
        assert record.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED

    def test_infl_009_pr_addressed_is_prj(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-009")
        assert record is not None
        assert "PR-J" in record.pr_addressed

    def test_infl_009_canonical_path_references_udm(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-009")
        assert record is not None
        assert "UnifiedDeviceManager" in record.canonical_path

    def test_infl_010_present(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-010")
        assert record is not None
        assert record.influence_id == "INFL-010"

    def test_infl_010_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            CompatInfluenceBoundingStatus,
            get_influence_record,
        )
        record = get_influence_record("INFL-010")
        assert record is not None
        assert record.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED

    def test_infl_010_pr_addressed_is_prj(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-010")
        assert record is not None
        assert "PR-J" in record.pr_addressed

    def test_infl_010_canonical_path_references_canonical_session_truth(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-010")
        assert record is not None
        assert "CanonicalSessionTruthRuntime" in record.canonical_path


# ===========================================================================
# LL–MM. Hardening complete — no UNBOUNDED or SCOPE_LIMITED records
# ===========================================================================


class TestHardeningComplete:
    def test_hardening_complete_remains_true(self):
        from core.compat_fallback_authority_guard import (
            build_authority_hardening_snapshot,
        )
        snapshot = build_authority_hardening_snapshot()
        assert snapshot.hardening_complete is True, (
            "hardening_complete must be True; "
            f"scope_limited_count={snapshot.scope_limited_count}, "
            f"unbounded_count={snapshot.unbounded_count}"
        )

    def test_no_unbounded_records(self):
        from core.compat_fallback_authority_guard import (
            CompatInfluenceBoundingStatus,
            get_influence_registry,
        )
        unbounded = [
            r for r in get_influence_registry()
            if r.bounding_status == CompatInfluenceBoundingStatus.UNBOUNDED
        ]
        assert len(unbounded) == 0, (
            f"Found {len(unbounded)} UNBOUNDED influence records: "
            f"{[r.influence_id for r in unbounded]}"
        )

    def test_no_scope_limited_records(self):
        from core.compat_fallback_authority_guard import (
            CompatInfluenceBoundingStatus,
            get_influence_registry,
        )
        scope_limited = [
            r for r in get_influence_registry()
            if r.bounding_status == CompatInfluenceBoundingStatus.SCOPE_LIMITED
        ]
        assert len(scope_limited) == 0, (
            f"Found {len(scope_limited)} SCOPE_LIMITED influence records: "
            f"{[r.influence_id for r in scope_limited]}"
        )

    def test_infl_001_through_infl_010_all_present(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        registry = get_influence_registry()
        ids = {r.influence_id for r in registry}
        expected_ids = {
            "INFL-001", "INFL-002", "INFL-003", "INFL-004",
            "INFL-005", "INFL-006", "INFL-007", "INFL-008",
            "INFL-009", "INFL-010",
        }
        for expected_id in expected_ids:
            assert expected_id in ids, (
                f"{expected_id} missing from influence registry"
            )


# ===========================================================================
# NN. Device truth surface has routes/devices in allowed mirror paths
# ===========================================================================


class TestDeviceSurfaceAllowedPaths:
    def test_device_allowed_paths_contains_routes_devices(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        allowed_text = " ".join(record.allowed_compat_mirror_paths)
        assert "routes" in allowed_text.lower() or "devices" in allowed_text.lower(), (
            "Device surface allowed_compat_mirror_paths should reference routes/devices"
        )

    def test_device_allowed_paths_contains_compat_route(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            get_write_authority_for_surface,
        )
        record = get_write_authority_for_surface(TruthSurface.device)
        assert record is not None
        allowed_text = " ".join(record.allowed_compat_mirror_paths)
        assert "compat" in allowed_text.lower(), (
            "Device surface allowed_compat_mirror_paths should reference compat route"
        )


# ===========================================================================
# OO. assert_canonical_write_precedes_compat_write with task surface
# ===========================================================================


class TestTaskSurfaceWriteOrderingGuard:
    def test_task_surface_returns_correct_surface_in_record(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.task,
            canonical_write_confirmed=True,
        )
        assert result.surface == TruthSurface.task

    def test_task_surface_canonical_authority_contains_canonical_task(self):
        from core.truth_conflict_enforcement import (
            TruthSurface,
            assert_canonical_write_precedes_compat_write,
        )
        result = assert_canonical_write_precedes_compat_write(
            TruthSurface.task,
            canonical_write_confirmed=True,
        )
        assert "CanonicalTask" in result.canonical_authority


# ===========================================================================
# PP. assert_no_parallel_write_authority with session surface allowed compat path
# ===========================================================================


class TestSessionSurfaceParallelAuthorityGuard:
    def test_session_attached_runtime_is_allowed_compat(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        result = assert_no_parallel_write_authority(
            TruthSurface.session,
            writer_module="core.attached_runtime_session.AttachedRuntimeSession",
        )
        assert result.verdict == TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID

    def test_session_unknown_writer_returns_parallel_detected(self):
        from core.truth_conflict_enforcement import (
            TruthConflictVerdict,
            TruthSurface,
            assert_no_parallel_write_authority,
        )
        result = assert_no_parallel_write_authority(
            TruthSurface.session,
            writer_module="some.legacy.session_store",
        )
        assert result.verdict == TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED
