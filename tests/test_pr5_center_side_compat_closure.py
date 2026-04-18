#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_center_side_compat_closure.py
=============================================

PR-5 (Cross-Repo Compatibility Retirement Prep — Center-side Compatibility
Closure): validation test suite.

Coverage areas
--------------
A.  Module importable; authority and PR-5 sentinel are non-empty strings
    with expected tokens.
B.  All four policy sentinels are non-empty strings with expected keywords.
C.  CompatGapDomain enum members present and correct.
D.  CompatClosureStatus enum has OPEN, FENCED, RETIRED, TOMBSTONED members.
E.  CompatFenceKind enum members present.
F.  FenceVerdict enum members present.
G.  get_compat_gap_catalog() returns a non-empty list of CompatGapRecord.
H.  Every gap record has a non-empty gap_id, module_path, surface_name,
    canonical_replacement, and retirement_condition.
I.  Every fenced gap has a fence_kind that is not ``none``.
J.  No gap has OPEN status with a non-none fence_kind
    (open gaps must declare fence_kind=none explicitly, but per policy
    we expect all catalog entries to be FENCED or better after PR-5).
K.  The catalog contains all seven expected gap IDs:
    COMPAT-001, COMPAT-002, COMPAT-003, COMPAT-004, COMPAT-005, COMPAT-006,
    PROTO-007.
L.  No two records share the same gap_id (uniqueness).
M.  get_gaps_by_status(FENCED) returns only FENCED records.
N.  get_gaps_by_status(OPEN) returns only OPEN records.
O.  get_open_gaps() returns the same result as get_gaps_by_status(OPEN).
P.  get_fenced_gaps() returns the same result as get_gaps_by_status(FENCED).
Q.  check_compat_fence() with compat_path_invoked=False returns
    CANONICAL_PREFERRED for a known gap_id.
R.  check_compat_fence() with compat_path_invoked=True returns
    COMPAT_ALLOWED_FENCED for a FENCED gap.
S.  check_compat_fence() with an unknown gap_id returns UNKNOWN verdict.
T.  check_compat_fence() with strict=True raises RuntimeError for an
    unfenced (OPEN) gap (constructed in test, not from production catalog).
U.  assert_canonical_path_preferred() returns CANONICAL_PREFERRED when
    canonical_active=True.
V.  assert_canonical_path_preferred() returns COMPAT_ALLOWED_FENCED when
    canonical_active=False on a FENCED gap.
W.  build_compat_closure_snapshot() returns a CompatClosureSnapshot.
X.  Snapshot counts are internally consistent
    (total == open + fenced + retired + tombstoned).
Y.  Snapshot policy_sentinels list contains four sentinel strings.
Z.  CompatClosureSnapshot.to_dict() includes expected top-level keys.
AA. CompatGapRecord.to_dict() includes all required keys.
AB. is_cross_repo_convergence_ready() returns True when no OPEN gaps exist.
AC. CompatGapRecord fields for COMPAT-006 reference DeprecationWarning fence.
AD. CompatGapRecord for PROTO-007 references env_var_gate fence and
    GALAXY_ENABLE_LEGACY_PROTOCOLS.
AE. All CRITICAL, HIGH or MEDIUM severity gaps are FENCED, RETIRED, or TOMBSTONED.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.center_side_compat_closure import (
    CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY,
    CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY,
    CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL,
    COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY,
    CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY,
    LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY,
    CompatClosureSnapshot,
    CompatClosureStatus,
    CompatFenceKind,
    CompatFenceResult,
    CompatGapDomain,
    CompatGapRecord,
    FenceVerdict,
    assert_canonical_path_preferred,
    build_compat_closure_snapshot,
    check_compat_fence,
    get_compat_gap_catalog,
    get_fenced_gaps,
    get_gaps_by_status,
    get_open_gaps,
    is_cross_repo_convergence_ready,
)

# ---------------------------------------------------------------------------
# A. Authority and sentinel
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty() -> None:
    assert isinstance(CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY, str)
    assert CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY
    assert "IS_AUTHORITY" in CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY
    assert "core.center_side_compat_closure" in CENTER_SIDE_COMPAT_CLOSURE_IS_AUTHORITY


def test_pr5_sentinel_non_empty() -> None:
    assert isinstance(CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL, str)
    assert CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL
    assert "PR5" in CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL
    assert "center-side-compat-closure-v1" in CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL
    assert "core.center_side_compat_closure" in CENTER_SIDE_COMPAT_CLOSURE_PR5_SENTINEL


# ---------------------------------------------------------------------------
# B. Policy sentinels
# ---------------------------------------------------------------------------


def test_policy_sentinels_non_empty() -> None:
    for sentinel in [
        COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY,
        LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY,
        CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY,
        CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY,
    ]:
        assert isinstance(sentinel, str)
        assert sentinel


def test_compat_seams_policy_keyword() -> None:
    assert "COMPAT_SEAMS" in COMPAT_SEAMS_MUST_NOT_SILENTLY_SUPERSEDE_CANONICAL_POLICY


def test_legacy_fence_policy_keyword() -> None:
    assert "LEGACY_PATH_FENCE" in LEGACY_PATH_FENCE_MUST_BE_EXPLICIT_POLICY


def test_cross_repo_readiness_policy_keyword() -> None:
    assert "CROSS_REPO_READINESS" in CROSS_REPO_READINESS_REQUIRES_COMPAT_CLOSURE_POLICY


def test_canonical_preference_policy_keyword() -> None:
    assert (
        "CANONICAL_PATH_PREFERENCE" in CANONICAL_PATH_PREFERENCE_MUST_BE_ENFORCED_POLICY
    )


# ---------------------------------------------------------------------------
# C. CompatGapDomain enum
# ---------------------------------------------------------------------------


def test_compat_gap_domain_members() -> None:
    expected = {
        "websocket_path",
        "rest_endpoint",
        "registry_facade",
        "coordinator_substrate",
        "runtime_role",
        "projection_contract",
    }
    actual = {m.value for m in CompatGapDomain}
    assert expected == actual


# ---------------------------------------------------------------------------
# D. CompatClosureStatus enum
# ---------------------------------------------------------------------------


def test_compat_closure_status_members() -> None:
    expected = {"open", "fenced", "retired", "tombstoned"}
    actual = {m.value for m in CompatClosureStatus}
    assert expected == actual


# ---------------------------------------------------------------------------
# E. CompatFenceKind enum
# ---------------------------------------------------------------------------


def test_compat_fence_kind_members() -> None:
    expected = {
        "env_var_gate",
        "deprecation_warning",
        "sentinel_guard",
        "redirect_logging",
        "hard_error",
        "none",
    }
    actual = {m.value for m in CompatFenceKind}
    assert expected == actual


# ---------------------------------------------------------------------------
# F. FenceVerdict enum
# ---------------------------------------------------------------------------


def test_fence_verdict_members() -> None:
    expected = {
        "canonical_preferred",
        "compat_allowed_fenced",
        "compat_open_unfenced",
        "unknown",
    }
    actual = {m.value for m in FenceVerdict}
    assert expected == actual


# ---------------------------------------------------------------------------
# G. Catalog non-empty
# ---------------------------------------------------------------------------


def test_catalog_non_empty() -> None:
    catalog = get_compat_gap_catalog()
    assert isinstance(catalog, list)
    assert len(catalog) > 0
    for rec in catalog:
        assert isinstance(rec, CompatGapRecord)


# ---------------------------------------------------------------------------
# H. Every record has required non-empty fields
# ---------------------------------------------------------------------------


def test_every_record_has_required_fields() -> None:
    for rec in get_compat_gap_catalog():
        assert rec.gap_id, f"gap_id empty for record: {rec}"
        assert rec.module_path, f"module_path empty for {rec.gap_id}"
        assert rec.surface_name, f"surface_name empty for {rec.gap_id}"
        assert rec.canonical_replacement, f"canonical_replacement empty for {rec.gap_id}"
        assert rec.retirement_condition, f"retirement_condition empty for {rec.gap_id}"
        assert isinstance(rec.domain, CompatGapDomain)
        assert isinstance(rec.status, CompatClosureStatus)
        assert isinstance(rec.fence_kind, CompatFenceKind)


# ---------------------------------------------------------------------------
# I. Fenced gaps have a non-none fence_kind
# ---------------------------------------------------------------------------


def test_fenced_gaps_have_non_none_fence_kind() -> None:
    for rec in get_compat_gap_catalog():
        if rec.status == CompatClosureStatus.FENCED:
            assert rec.fence_kind != CompatFenceKind.none, (
                f"{rec.gap_id}: FENCED status requires a non-none fence_kind"
            )


# ---------------------------------------------------------------------------
# J. (Relaxed) Open gaps must declare fence_kind=none
# ---------------------------------------------------------------------------


def test_open_gaps_have_none_fence_kind() -> None:
    for rec in get_open_gaps():
        assert rec.fence_kind == CompatFenceKind.none, (
            f"{rec.gap_id}: OPEN gap must have fence_kind=none (no fence in place)"
        )


# ---------------------------------------------------------------------------
# K. All seven expected gap IDs present
# ---------------------------------------------------------------------------


def test_expected_gap_ids_present() -> None:
    expected_ids = {
        "COMPAT-001",
        "COMPAT-002",
        "COMPAT-003",
        "COMPAT-004",
        "COMPAT-005",
        "COMPAT-006",
        "PROTO-007",
    }
    catalog_ids = {rec.gap_id for rec in get_compat_gap_catalog()}
    for gap_id in expected_ids:
        assert gap_id in catalog_ids, f"Expected gap ID {gap_id!r} not found in catalog"


# ---------------------------------------------------------------------------
# L. Uniqueness of gap_id
# ---------------------------------------------------------------------------


def test_gap_ids_are_unique() -> None:
    ids = [rec.gap_id for rec in get_compat_gap_catalog()]
    assert len(ids) == len(set(ids)), "Duplicate gap_id found in catalog"


# ---------------------------------------------------------------------------
# M–P. Filter functions
# ---------------------------------------------------------------------------


def test_get_gaps_by_status_fenced_returns_only_fenced() -> None:
    for rec in get_gaps_by_status(CompatClosureStatus.FENCED):
        assert rec.status == CompatClosureStatus.FENCED


def test_get_gaps_by_status_open_returns_only_open() -> None:
    for rec in get_gaps_by_status(CompatClosureStatus.OPEN):
        assert rec.status == CompatClosureStatus.OPEN


def test_get_open_gaps_same_as_filter() -> None:
    assert get_open_gaps() == get_gaps_by_status(CompatClosureStatus.OPEN)


def test_get_fenced_gaps_same_as_filter() -> None:
    assert get_fenced_gaps() == get_gaps_by_status(CompatClosureStatus.FENCED)


# ---------------------------------------------------------------------------
# Q. check_compat_fence with compat_path_invoked=False → CANONICAL_PREFERRED
# ---------------------------------------------------------------------------


def test_check_fence_canonical_preferred() -> None:
    result = check_compat_fence("COMPAT-006", compat_path_invoked=False)
    assert isinstance(result, CompatFenceResult)
    assert result.verdict == FenceVerdict.CANONICAL_PREFERRED
    assert result.gap_id == "COMPAT-006"
    assert result.canonical_path


# ---------------------------------------------------------------------------
# R. check_compat_fence on FENCED gap with compat invoked → COMPAT_ALLOWED_FENCED
# ---------------------------------------------------------------------------


def test_check_fence_fenced_gap_compat_invoked() -> None:
    # All catalog records are FENCED, so use COMPAT-001
    result = check_compat_fence("COMPAT-001", compat_path_invoked=True)
    assert isinstance(result, CompatFenceResult)
    assert result.verdict == FenceVerdict.COMPAT_ALLOWED_FENCED
    assert result.gap_id == "COMPAT-001"
    assert result.message


# ---------------------------------------------------------------------------
# S. check_compat_fence with unknown gap_id → UNKNOWN
# ---------------------------------------------------------------------------


def test_check_fence_unknown_gap_id() -> None:
    result = check_compat_fence("COMPAT-NONEXISTENT-9999")
    assert result.verdict == FenceVerdict.UNKNOWN
    assert result.gap_id == "COMPAT-NONEXISTENT-9999"


# ---------------------------------------------------------------------------
# T. check_compat_fence with strict=True on OPEN gap raises RuntimeError
# ---------------------------------------------------------------------------


def test_check_fence_strict_raises_for_open_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a synthetic OPEN record into the catalog temporarily."""
    import core.center_side_compat_closure as _mod

    synthetic = CompatGapRecord(
        gap_id="COMPAT-TEST-OPEN",
        severity="LOW",
        domain=CompatGapDomain.rest_endpoint,
        module_path="core.routes.test_open",
        surface_name="Test open gap",
        status=CompatClosureStatus.OPEN,
        fence_kind=CompatFenceKind.none,
        canonical_replacement="core.routes.canonical",
        retirement_condition="Test only.",
    )
    original = list(_mod._COMPAT_GAP_CATALOG)
    monkeypatch.setattr(_mod, "_COMPAT_GAP_CATALOG", original + [synthetic])

    with pytest.raises(RuntimeError):
        check_compat_fence("COMPAT-TEST-OPEN", compat_path_invoked=True, strict=True)


# ---------------------------------------------------------------------------
# U. assert_canonical_path_preferred → CANONICAL_PREFERRED
# ---------------------------------------------------------------------------


def test_assert_canonical_preferred_when_canonical_active() -> None:
    result = assert_canonical_path_preferred("PROTO-007", canonical_active=True)
    assert result.verdict == FenceVerdict.CANONICAL_PREFERRED


# ---------------------------------------------------------------------------
# V. assert_canonical_path_preferred when compat invoked → COMPAT_ALLOWED_FENCED
# ---------------------------------------------------------------------------


def test_assert_canonical_preferred_when_compat_invoked() -> None:
    result = assert_canonical_path_preferred(
        "PROTO-007", canonical_active=False, context="test_context"
    )
    assert result.verdict == FenceVerdict.COMPAT_ALLOWED_FENCED


# ---------------------------------------------------------------------------
# W. build_compat_closure_snapshot returns CompatClosureSnapshot
# ---------------------------------------------------------------------------


def test_build_snapshot_returns_correct_type() -> None:
    snapshot = build_compat_closure_snapshot()
    assert isinstance(snapshot, CompatClosureSnapshot)
    assert snapshot.total_gaps > 0


# ---------------------------------------------------------------------------
# X. Snapshot counts are internally consistent
# ---------------------------------------------------------------------------


def test_snapshot_counts_consistent() -> None:
    snapshot = build_compat_closure_snapshot()
    total_from_statuses = (
        snapshot.open_count
        + snapshot.fenced_count
        + snapshot.retired_count
        + snapshot.tombstoned_count
    )
    assert snapshot.total_gaps == total_from_statuses, (
        f"Snapshot total_gaps={snapshot.total_gaps} != "
        f"sum of status counts={total_from_statuses}"
    )


# ---------------------------------------------------------------------------
# Y. Snapshot policy_sentinels contains four sentinel strings
# ---------------------------------------------------------------------------


def test_snapshot_policy_sentinels() -> None:
    snapshot = build_compat_closure_snapshot()
    assert isinstance(snapshot.policy_sentinels, list)
    assert len(snapshot.policy_sentinels) == 4
    for s in snapshot.policy_sentinels:
        assert isinstance(s, str)
        assert s


# ---------------------------------------------------------------------------
# Z. CompatClosureSnapshot.to_dict() includes expected keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_keys() -> None:
    d = build_compat_closure_snapshot().to_dict()
    expected_keys = {
        "total_gaps",
        "by_status",
        "high_or_medium_open_count",
        "cross_repo_ready",
        "generated_at",
        "policy_sentinels",
        "gap_summaries",
    }
    assert expected_keys.issubset(d.keys()), (
        f"Missing keys: {expected_keys - d.keys()}"
    )
    assert isinstance(d["by_status"], dict)
    assert "open" in d["by_status"]
    assert "fenced" in d["by_status"]


# ---------------------------------------------------------------------------
# AA. CompatGapRecord.to_dict() includes all required keys
# ---------------------------------------------------------------------------


def test_gap_record_to_dict_keys() -> None:
    required_keys = {
        "gap_id",
        "severity",
        "domain",
        "module_path",
        "surface_name",
        "status",
        "fence_kind",
        "canonical_replacement",
        "retirement_condition",
        "fence_evidence",
        "cross_repo_impact",
        "notes",
    }
    for rec in get_compat_gap_catalog():
        d = rec.to_dict()
        assert required_keys.issubset(d.keys()), (
            f"{rec.gap_id} to_dict() missing keys: {required_keys - d.keys()}"
        )


# ---------------------------------------------------------------------------
# AB. is_cross_repo_convergence_ready when no OPEN gaps
# ---------------------------------------------------------------------------


def test_cross_repo_convergence_ready_when_no_open_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.center_side_compat_closure as _mod

    # All records fenced — should be ready
    fenced_only = [
        r for r in _mod._COMPAT_GAP_CATALOG
        if r.status == CompatClosureStatus.FENCED
    ]
    monkeypatch.setattr(_mod, "_COMPAT_GAP_CATALOG", fenced_only)
    assert is_cross_repo_convergence_ready() is True


def test_cross_repo_convergence_not_ready_when_open_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.center_side_compat_closure as _mod

    synthetic_open = CompatGapRecord(
        gap_id="COMPAT-OPEN-TEST",
        severity="MEDIUM",
        domain=CompatGapDomain.rest_endpoint,
        module_path="core.routes.test",
        surface_name="test open",
        status=CompatClosureStatus.OPEN,
        fence_kind=CompatFenceKind.none,
        canonical_replacement="core.routes.canonical",
        retirement_condition="Test only.",
    )
    monkeypatch.setattr(
        _mod, "_COMPAT_GAP_CATALOG", list(_mod._COMPAT_GAP_CATALOG) + [synthetic_open]
    )
    assert is_cross_repo_convergence_ready() is False


# ---------------------------------------------------------------------------
# AC. COMPAT-006 references DeprecationWarning fence
# ---------------------------------------------------------------------------


def test_compat_006_deprecation_warning_fence() -> None:
    rec = next(r for r in get_compat_gap_catalog() if r.gap_id == "COMPAT-006")
    assert rec.fence_kind == CompatFenceKind.deprecation_warning
    assert "DeprecationWarning" in rec.fence_evidence


# ---------------------------------------------------------------------------
# AD. PROTO-007 references env_var_gate and GALAXY_ENABLE_LEGACY_PROTOCOLS
# ---------------------------------------------------------------------------


def test_proto_007_env_var_gate_fence() -> None:
    rec = next(r for r in get_compat_gap_catalog() if r.gap_id == "PROTO-007")
    assert rec.fence_kind == CompatFenceKind.env_var_gate
    assert "GALAXY_ENABLE_LEGACY_PROTOCOLS" in rec.fence_evidence
    assert rec.domain == CompatGapDomain.websocket_path


# ---------------------------------------------------------------------------
# AE. All CRITICAL, HIGH or MEDIUM severity gaps are FENCED, RETIRED, or TOMBSTONED
# ---------------------------------------------------------------------------


def test_critical_high_medium_gaps_not_open() -> None:
    for rec in get_compat_gap_catalog():
        if rec.severity in ("CRITICAL", "HIGH", "MEDIUM"):
            assert rec.status != CompatClosureStatus.OPEN, (
                f"{rec.gap_id} has severity={rec.severity} but status=OPEN. "
                "CRITICAL/HIGH/MEDIUM gaps must be at least FENCED."
            )
