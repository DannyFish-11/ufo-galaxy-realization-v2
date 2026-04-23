#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_compat_fallback_authority_hardening.py
======================================================

PR-9: Harden canonical truth authority boundaries and restrict compat
fallback influence — focused test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-9 sentinel non-empty strings.
B.  All four policy sentinels are non-empty strings with expected keywords.
C.  CompatInfluenceRole enum has observer, bounded_assist, degraded_fallback,
    unbound_influence values.
D.  CompatInfluenceBoundingStatus enum has EXPLICITLY_BOUNDED, SCOPE_LIMITED,
    UNBOUNDED, RETIRED values.
E.  CompatInfluenceVerdict enum has CANONICAL_AUTHORITY, BOUNDED_ASSIST_ACTIVE,
    DEGRADED_FALLBACK_ACTIVE, UNBOUND_INFLUENCE_DETECTED, UNKNOWN values.
F.  get_influence_registry() returns a non-empty list of CompatInfluenceRecord.
G.  Every influence record has non-empty influence_id, decision_site,
    canonical_path, compat_path, bounding_evidence, and reviewer_note.
H.  No two records share the same influence_id (uniqueness).
I.  Every record has a valid influence_role and bounding_status value.
J.  All expected INFL-001 through INFL-008 IDs are present in the registry.
K.  No record has bounding_status UNBOUNDED (hardening_complete invariant).
L.  CompatInfluenceRecord.to_dict() contains all required keys.
M.  check_canonical_authority_at_decision_site() with canonical_is_active=True
    and compat_path_invoked=False returns CANONICAL_AUTHORITY verdict.
N.  check_canonical_authority_at_decision_site() with compat_path_invoked=True
    and a degraded_fallback record returns DEGRADED_FALLBACK_ACTIVE verdict.
O.  check_canonical_authority_at_decision_site() with compat_path_invoked=True
    and a bounded_assist record returns BOUNDED_ASSIST_ACTIVE verdict.
P.  check_canonical_authority_at_decision_site() with unknown influence_id
    returns UNKNOWN verdict.
Q.  check_canonical_authority_at_decision_site() with strict=True raises
    RuntimeError when bounding_status is UNBOUNDED (constructed in test).
R.  assert_canonical_is_decision_authority() returns CANONICAL_AUTHORITY when
    canonical path is confirmed active.
S.  CompatInfluenceCheckResult.to_dict() contains required keys.
T.  build_authority_hardening_snapshot() returns AuthorityHardeningSnapshot.
U.  Snapshot counts are internally consistent
    (total == explicitly_bounded + scope_limited + unbounded + retired).
V.  Snapshot has hardening_complete == True (no unbounded or scope_limited).
W.  Snapshot policy_sentinels list contains four sentinel strings.
X.  AuthorityHardeningSnapshot.to_dict() contains expected top-level keys.
Y.  All INFL records that are degraded_fallback have EXPLICITLY_BOUNDED status.
Z.  get_influence_record() returns the correct record for a known ID.
AA. get_influence_record() returns None for an unknown ID.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest


# ===========================================================================
# A. Module importable; authority and PR-9 sentinel present
# ===========================================================================


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.compat_fallback_authority_guard  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.compat_fallback_authority_guard import (
            COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY,
        )
        assert isinstance(COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY, str)
        assert len(COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY) > 0
        assert "PR-9" in COMPAT_FALLBACK_AUTHORITY_GUARD_IS_AUTHORITY

    def test_pr9_sentinel_is_non_empty_string(self):
        from core.compat_fallback_authority_guard import (
            COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL,
        )
        assert isinstance(COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL, str)
        assert "PR9" in COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL
        assert "authority-hardening" in COMPAT_FALLBACK_AUTHORITY_GUARD_PR9_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_canonical_authority_policy_contains_expected_keyword(self):
        from core.compat_fallback_authority_guard import (
            CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY,
        )
        assert isinstance(CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY, str)
        assert "canonical" in CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY.lower()
        assert "primary" in CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY.lower()

    def test_compat_observe_assist_policy_present(self):
        from core.compat_fallback_authority_guard import (
            COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY,
        )
        assert isinstance(
            COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY,
            str,
        )
        assert len(COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY) > 0

    def test_unbound_influence_violation_policy_present(self):
        from core.compat_fallback_authority_guard import (
            UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY,
        )
        assert isinstance(UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY, str)
        assert "violation" in UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY.lower()

    def test_fallback_must_not_silently_become_canonical_policy_present(self):
        from core.compat_fallback_authority_guard import (
            FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY,
        )
        assert isinstance(FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY, str)
        assert "fallback" in FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY.lower()
        assert "canonical" in FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY.lower()


# ===========================================================================
# C. CompatInfluenceRole enum
# ===========================================================================


class TestCompatInfluenceRole:
    def test_observer_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceRole
        assert CompatInfluenceRole.observer.value == "observer"

    def test_bounded_assist_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceRole
        assert CompatInfluenceRole.bounded_assist.value == "bounded_assist"

    def test_degraded_fallback_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceRole
        assert CompatInfluenceRole.degraded_fallback.value == "degraded_fallback"

    def test_unbound_influence_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceRole
        assert CompatInfluenceRole.unbound_influence.value == "unbound_influence"

    def test_all_four_roles_present(self):
        from core.compat_fallback_authority_guard import CompatInfluenceRole
        expected = {"observer", "bounded_assist", "degraded_fallback", "unbound_influence"}
        actual = {r.value for r in CompatInfluenceRole}
        assert expected == actual


# ===========================================================================
# D. CompatInfluenceBoundingStatus enum
# ===========================================================================


class TestCompatInfluenceBoundingStatus:
    def test_explicitly_bounded_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceBoundingStatus
        assert CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED.value == "explicitly_bounded"

    def test_scope_limited_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceBoundingStatus
        assert CompatInfluenceBoundingStatus.SCOPE_LIMITED.value == "scope_limited"

    def test_unbounded_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceBoundingStatus
        assert CompatInfluenceBoundingStatus.UNBOUNDED.value == "unbounded"

    def test_retired_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceBoundingStatus
        assert CompatInfluenceBoundingStatus.RETIRED.value == "retired"

    def test_all_four_statuses_present(self):
        from core.compat_fallback_authority_guard import CompatInfluenceBoundingStatus
        expected = {"explicitly_bounded", "scope_limited", "unbounded", "retired"}
        actual = {s.value for s in CompatInfluenceBoundingStatus}
        assert expected == actual


# ===========================================================================
# E. CompatInfluenceVerdict enum
# ===========================================================================


class TestCompatInfluenceVerdict:
    def test_canonical_authority_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        assert CompatInfluenceVerdict.CANONICAL_AUTHORITY.value == "canonical_authority"

    def test_bounded_assist_active_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        assert CompatInfluenceVerdict.BOUNDED_ASSIST_ACTIVE.value == "bounded_assist_active"

    def test_degraded_fallback_active_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        assert CompatInfluenceVerdict.DEGRADED_FALLBACK_ACTIVE.value == "degraded_fallback_active"

    def test_unbound_influence_detected_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        assert CompatInfluenceVerdict.UNBOUND_INFLUENCE_DETECTED.value == "unbound_influence_detected"

    def test_unknown_value(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        assert CompatInfluenceVerdict.UNKNOWN.value == "unknown"

    def test_all_five_verdicts_present(self):
        from core.compat_fallback_authority_guard import CompatInfluenceVerdict
        expected = {
            "canonical_authority",
            "bounded_assist_active",
            "degraded_fallback_active",
            "unbound_influence_detected",
            "unknown",
        }
        actual = {v.value for v in CompatInfluenceVerdict}
        assert expected == actual


# ===========================================================================
# F. get_influence_registry() — non-empty list of CompatInfluenceRecord
# ===========================================================================


class TestInfluenceRegistry:
    def test_get_influence_registry_returns_nonempty_list(self):
        from core.compat_fallback_authority_guard import (
            get_influence_registry,
            CompatInfluenceRecord,
        )
        registry = get_influence_registry()
        assert isinstance(registry, list)
        assert len(registry) > 0
        assert all(isinstance(r, CompatInfluenceRecord) for r in registry)

    def test_get_influence_registry_returns_copy(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        r1 = get_influence_registry()
        r2 = get_influence_registry()
        assert r1 is not r2  # new list each time


# ===========================================================================
# G. Every record has required non-empty fields
# ===========================================================================


class TestInfluenceRecordFields:
    def test_all_records_have_non_empty_required_fields(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        for record in get_influence_registry():
            assert record.influence_id, f"Empty influence_id in {record}"
            assert record.decision_site, f"Empty decision_site in {record.influence_id}"
            assert record.canonical_path, f"Empty canonical_path in {record.influence_id}"
            assert record.compat_path, f"Empty compat_path in {record.influence_id}"
            assert record.bounding_evidence, (
                f"Empty bounding_evidence in {record.influence_id}"
            )
            assert record.reviewer_note, f"Empty reviewer_note in {record.influence_id}"


# ===========================================================================
# H. Unique influence IDs
# ===========================================================================


class TestInfluenceRegistryUniqueness:
    def test_all_influence_ids_are_unique(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        ids = [r.influence_id for r in get_influence_registry()]
        assert len(ids) == len(set(ids)), "Duplicate influence_id found in registry"


# ===========================================================================
# I. Valid role and bounding_status on every record
# ===========================================================================


class TestInfluenceRecordEnumValues:
    def test_all_records_have_valid_influence_role(self):
        from core.compat_fallback_authority_guard import (
            get_influence_registry,
            CompatInfluenceRole,
        )
        valid_roles = set(CompatInfluenceRole)
        for record in get_influence_registry():
            assert record.influence_role in valid_roles, (
                f"{record.influence_id} has invalid influence_role={record.influence_role!r}"
            )

    def test_all_records_have_valid_bounding_status(self):
        from core.compat_fallback_authority_guard import (
            get_influence_registry,
            CompatInfluenceBoundingStatus,
        )
        valid_statuses = set(CompatInfluenceBoundingStatus)
        for record in get_influence_registry():
            assert record.bounding_status in valid_statuses, (
                f"{record.influence_id} has invalid bounding_status={record.bounding_status!r}"
            )


# ===========================================================================
# J. Expected INFL-001 through INFL-008 IDs present
# ===========================================================================


class TestExpectedInfluenceIds:
    def test_all_expected_influence_ids_present(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        ids = {r.influence_id for r in get_influence_registry()}
        expected = {
            "INFL-001",
            "INFL-002",
            "INFL-003",
            "INFL-004",
            "INFL-005",
            "INFL-006",
            "INFL-007",
            "INFL-008",
        }
        for eid in expected:
            assert eid in ids, f"Expected influence_id {eid!r} not found in registry"


# ===========================================================================
# K. No record has bounding_status UNBOUNDED
# ===========================================================================


class TestNoUnboundedInfluence:
    def test_no_unbounded_influence_points_in_registry(self):
        from core.compat_fallback_authority_guard import (
            get_influence_registry,
            CompatInfluenceBoundingStatus,
        )
        unbounded = [
            r for r in get_influence_registry()
            if r.bounding_status == CompatInfluenceBoundingStatus.UNBOUNDED
        ]
        assert unbounded == [], (
            f"POLICY VIOLATION: unbounded influence points found: "
            + ", ".join(r.influence_id for r in unbounded)
        )


# ===========================================================================
# L. CompatInfluenceRecord.to_dict() required keys
# ===========================================================================


class TestInfluenceRecordToDict:
    def test_to_dict_contains_required_keys(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        required_keys = {
            "influence_id",
            "decision_site",
            "canonical_path",
            "compat_path",
            "influence_role",
            "bounding_status",
            "bounding_evidence",
            "reviewer_note",
            "pr_addressed",
        }
        for record in get_influence_registry():
            d = record.to_dict()
            for key in required_keys:
                assert key in d, (
                    f"to_dict() for {record.influence_id} missing key {key!r}"
                )

    def test_to_dict_role_and_status_are_strings(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        for record in get_influence_registry():
            d = record.to_dict()
            assert isinstance(d["influence_role"], str)
            assert isinstance(d["bounding_status"], str)


# ===========================================================================
# M. CANONICAL_AUTHORITY verdict when no compat invoked
# ===========================================================================


class TestCheckCanonicalAuthorityClean:
    def test_canonical_authority_verdict_when_no_compat_invoked(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
            CompatInfluenceVerdict,
        )
        result = check_canonical_authority_at_decision_site(
            "INFL-001",
            canonical_is_active=True,
            compat_path_invoked=False,
        )
        assert result.verdict == CompatInfluenceVerdict.CANONICAL_AUTHORITY

    def test_canonical_authority_result_has_correct_paths(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
            get_influence_record,
        )
        record = get_influence_record("INFL-003")
        result = check_canonical_authority_at_decision_site(
            "INFL-003",
            canonical_is_active=True,
            compat_path_invoked=False,
        )
        assert result.canonical_path == record.canonical_path
        assert result.compat_path == record.compat_path


# ===========================================================================
# N. DEGRADED_FALLBACK_ACTIVE verdict for degraded_fallback record
# ===========================================================================


class TestCheckDegradedFallbackActive:
    def test_degraded_fallback_verdict_when_fallback_invoked(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
            CompatInfluenceVerdict,
        )
        # INFL-001 has influence_role=degraded_fallback
        result = check_canonical_authority_at_decision_site(
            "INFL-001",
            canonical_is_active=False,
            compat_path_invoked=True,
        )
        assert result.verdict == CompatInfluenceVerdict.DEGRADED_FALLBACK_ACTIVE

    def test_degraded_fallback_message_mentions_canonical_path(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
        )
        result = check_canonical_authority_at_decision_site(
            "INFL-004",
            canonical_is_active=False,
            compat_path_invoked=True,
        )
        assert result.message  # non-empty message


# ===========================================================================
# O. BOUNDED_ASSIST_ACTIVE verdict for bounded_assist record
# ===========================================================================


class TestCheckBoundedAssistActive:
    def test_bounded_assist_verdict_when_compat_invoked(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
            CompatInfluenceVerdict,
        )
        # INFL-002 has influence_role=bounded_assist
        result = check_canonical_authority_at_decision_site(
            "INFL-002",
            canonical_is_active=True,
            compat_path_invoked=True,
        )
        assert result.verdict == CompatInfluenceVerdict.BOUNDED_ASSIST_ACTIVE


# ===========================================================================
# P. UNKNOWN verdict for unknown influence_id
# ===========================================================================


class TestCheckUnknownInfluenceId:
    def test_unknown_verdict_for_unregistered_id(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
            CompatInfluenceVerdict,
        )
        result = check_canonical_authority_at_decision_site(
            "INFL-UNKNOWN-99999",
            canonical_is_active=True,
            compat_path_invoked=True,
        )
        assert result.verdict == CompatInfluenceVerdict.UNKNOWN
        assert result.canonical_path == "<unknown>"
        assert result.compat_path == "<unknown>"


# ===========================================================================
# Q. strict=True raises RuntimeError for UNBOUNDED influence
# ===========================================================================


class TestStrictModeRaisesForUnbounded:
    def test_strict_raises_runtime_error_for_unbounded_influence(self):
        """Construct an ad-hoc unbounded record via module-level patching."""
        from core.compat_fallback_authority_guard import (
            CompatInfluenceRecord,
            CompatInfluenceRole,
            CompatInfluenceBoundingStatus,
        )
        # Build a fake unbounded record and inject it temporarily.
        fake_record = CompatInfluenceRecord(
            influence_id="INFL-TEST-UNBOUNDED",
            decision_site="test decision site",
            canonical_path="canonical.module.Path",
            compat_path="compat.module.Path",
            influence_role=CompatInfluenceRole.unbound_influence,
            bounding_status=CompatInfluenceBoundingStatus.UNBOUNDED,
            bounding_evidence="",
            reviewer_note="test record",
        )
        import core.compat_fallback_authority_guard as _mod
        original = list(_mod._INFLUENCE_REGISTRY)
        _mod._INFLUENCE_REGISTRY.append(fake_record)
        try:
            with pytest.raises(RuntimeError):
                _mod.check_canonical_authority_at_decision_site(
                    "INFL-TEST-UNBOUNDED",
                    canonical_is_active=False,
                    compat_path_invoked=True,
                    strict=True,
                )
        finally:
            _mod._INFLUENCE_REGISTRY[:] = original


# ===========================================================================
# R. assert_canonical_is_decision_authority returns CANONICAL_AUTHORITY
# ===========================================================================


class TestAssertCanonicalIsDecisionAuthority:
    def test_returns_canonical_authority_verdict(self):
        from core.compat_fallback_authority_guard import (
            assert_canonical_is_decision_authority,
            CompatInfluenceVerdict,
        )
        result = assert_canonical_is_decision_authority("INFL-006")
        assert result.verdict == CompatInfluenceVerdict.CANONICAL_AUTHORITY

    def test_accepts_context_string(self):
        from core.compat_fallback_authority_guard import (
            assert_canonical_is_decision_authority,
            CompatInfluenceVerdict,
        )
        result = assert_canonical_is_decision_authority(
            "INFL-007", context="test_pr9_suite"
        )
        assert result.verdict == CompatInfluenceVerdict.CANONICAL_AUTHORITY


# ===========================================================================
# S. CompatInfluenceCheckResult.to_dict() required keys
# ===========================================================================


class TestCompatInfluenceCheckResultToDict:
    def test_to_dict_contains_required_keys(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
        )
        result = check_canonical_authority_at_decision_site(
            "INFL-005",
            canonical_is_active=True,
            compat_path_invoked=False,
        )
        d = result.to_dict()
        required_keys = {
            "influence_id",
            "verdict",
            "canonical_path",
            "compat_path",
            "message",
            "timestamp",
        }
        for key in required_keys:
            assert key in d, f"to_dict() missing key {key!r}"

    def test_verdict_in_to_dict_is_string(self):
        from core.compat_fallback_authority_guard import (
            check_canonical_authority_at_decision_site,
        )
        result = check_canonical_authority_at_decision_site(
            "INFL-008",
            canonical_is_active=True,
            compat_path_invoked=False,
        )
        assert isinstance(result.to_dict()["verdict"], str)


# ===========================================================================
# T. build_authority_hardening_snapshot() returns AuthorityHardeningSnapshot
# ===========================================================================


class TestBuildAuthorityHardeningSnapshot:
    def test_returns_correct_type(self):
        from core.compat_fallback_authority_guard import (
            build_authority_hardening_snapshot,
            AuthorityHardeningSnapshot,
        )
        snapshot = build_authority_hardening_snapshot()
        assert isinstance(snapshot, AuthorityHardeningSnapshot)

    def test_snapshot_has_positive_total(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snapshot = build_authority_hardening_snapshot()
        assert snapshot.total_influence_points > 0


# ===========================================================================
# U. Snapshot counts internally consistent
# ===========================================================================


class TestSnapshotCountsConsistent:
    def test_total_equals_sum_of_status_counts(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        expected_total = (
            snap.explicitly_bounded_count
            + snap.scope_limited_count
            + snap.unbounded_count
            + snap.retired_count
        )
        assert snap.total_influence_points == expected_total


# ===========================================================================
# V. hardening_complete == True
# ===========================================================================


class TestHardeningComplete:
    def test_hardening_complete_is_true(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        assert snap.hardening_complete is True, (
            f"hardening_complete is False: "
            f"unbounded={snap.unbounded_count}, scope_limited={snap.scope_limited_count}"
        )

    def test_unbound_violation_count_is_zero(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        assert snap.unbound_violation_count == 0


# ===========================================================================
# W. Snapshot policy_sentinels has four entries
# ===========================================================================


class TestSnapshotPolicySentinels:
    def test_policy_sentinels_has_four_entries(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        assert len(snap.policy_sentinels) == 4

    def test_all_policy_sentinels_are_non_empty_strings(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        for sentinel in snap.policy_sentinels:
            assert isinstance(sentinel, str) and len(sentinel) > 0


# ===========================================================================
# X. AuthorityHardeningSnapshot.to_dict() expected top-level keys
# ===========================================================================


class TestSnapshotToDict:
    def test_to_dict_contains_expected_keys(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        d = snap.to_dict()
        expected_keys = {
            "total_influence_points",
            "by_bounding_status",
            "unbound_violation_count",
            "hardening_complete",
            "generated_at",
            "policy_sentinels",
            "influence_summaries",
        }
        for key in expected_keys:
            assert key in d, f"to_dict() missing key {key!r}"

    def test_by_bounding_status_has_four_keys(self):
        from core.compat_fallback_authority_guard import build_authority_hardening_snapshot
        snap = build_authority_hardening_snapshot()
        by_status = snap.to_dict()["by_bounding_status"]
        expected = {"explicitly_bounded", "scope_limited", "unbounded", "retired"}
        assert set(by_status.keys()) == expected


# ===========================================================================
# Y. All degraded_fallback records are EXPLICITLY_BOUNDED
# ===========================================================================


class TestDegradedFallbacksMustBeExplicitlyBounded:
    def test_all_degraded_fallback_records_are_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            get_influence_registry,
            CompatInfluenceRole,
            CompatInfluenceBoundingStatus,
        )
        fallbacks = [
            r for r in get_influence_registry()
            if r.influence_role == CompatInfluenceRole.degraded_fallback
        ]
        assert fallbacks, "No degraded_fallback records found — registry may be empty"
        not_bounded = [
            r for r in fallbacks
            if r.bounding_status != CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED
        ]
        assert not_bounded == [], (
            "degraded_fallback records without EXPLICITLY_BOUNDED status: "
            + ", ".join(r.influence_id for r in not_bounded)
        )


# ===========================================================================
# Z. get_influence_record() lookup helpers
# ===========================================================================


class TestGetInfluenceRecord:
    def test_returns_correct_record_for_known_id(self):
        from core.compat_fallback_authority_guard import get_influence_record
        record = get_influence_record("INFL-001")
        assert record is not None
        assert record.influence_id == "INFL-001"

    def test_returns_none_for_unknown_id(self):
        from core.compat_fallback_authority_guard import get_influence_record
        assert get_influence_record("INFL-DOES-NOT-EXIST") is None

    def test_all_expected_ids_resolvable(self):
        from core.compat_fallback_authority_guard import get_influence_record
        for i in range(1, 9):
            influence_id = f"INFL-00{i}"
            record = get_influence_record(influence_id)
            assert record is not None, f"get_influence_record({influence_id!r}) returned None"


# ===========================================================================
# AA. Additional integration guard: reviewer_note references canonical path
# ===========================================================================


class TestReviewerNoteQuality:
    def test_reviewer_notes_reference_canonical_path_or_signal(self):
        """Each reviewer_note should contain at least one actionable keyword."""
        from core.compat_fallback_authority_guard import get_influence_registry
        actionable_keywords = {"canonical", "reviewer", "check", "confirm", "path"}
        for record in get_influence_registry():
            lower_note = record.reviewer_note.lower()
            has_keyword = any(kw in lower_note for kw in actionable_keywords)
            assert has_keyword, (
                f"reviewer_note for {record.influence_id!r} lacks actionable keyword. "
                f"Note: {record.reviewer_note!r}"
            )
