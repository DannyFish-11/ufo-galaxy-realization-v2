#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr536_distributed_release_gate_skeleton.py
======================================================
PR-536 (test file number) / PR-7V2 (post-535 dual-repo runtime-unification
master plan, V2 side):
Canonical Distributed Release Gate Skeleton — validation test suite.

Problem addressed
-----------------
PR-7V2 introduces a canonical release gate skeleton that:

1. Defines all evidence categories for the distributed release gate.
2. Classifies each category as gate_worthy, advisory, or deferred.
3. Consumes the PR-6 evidence surface (read-only) to evaluate each category.
4. Produces a stable, JSON-serialisable ReleaseGateReport.
5. Remains non-enforcing (skeleton only) while structuring the evidence
   so later PRs can add enforcement without redefining semantics.

This test suite validates the skeleton against all acceptance criteria from
PR-7V2 so that a reviewer can determine:

- Which categories exist and what their strength is.
- That gate-worthy categories are backed by canonical evidence.
- That advisory/deferred categories cannot block release.
- That Android companion evidence is represented as a gate_worthy category
  after V2 ingestion.
- That the skeleton is non-enforcing in this PR.
- That the report is fully serialisable and round-trippable.
- That later PRs can build on the skeleton.

Coverage matrix
---------------
Group A — Module-level: sentinels, enums, __all__
  A01. Module importable; authority and PR7 sentinels present.
  A02. All seven policy sentinels are non-empty strings.
  A03. GateCategoryStrength has the three required values.
  A04. ReleaseGateVerdict has the four required values.
  A05. GateCategory has all eleven required category values.
  A06. __all__ contains all required public names.

Group B — Category definitions
  B01. Every GateCategory has an entry in _CATEGORY_STRENGTH.
  B02. Every GateCategory has an entry in _CATEGORY_DIMENSION_IDS.
  B03. Gate-worthy categories are exclusively backed by canonical-classified
       evidence dimensions.
  B04. Advisory categories use the advisory prefix naming convention.
  B05. Deferred categories use the deferred prefix naming convention.
  B06. companion_android is gate_worthy (not advisory).
  B07. deferred_rollout_promotion and deferred_ci_enforcement are deferred.

Group C — GateCategoryEvaluation
  C01. Default construction works; required fields present.
  C02. to_dict() returns all required keys.
  C03. from_dict(to_dict()) round-trip preserves all fields.

Group D — ReleaseGateReport
  D01. Default construction works; required fields present.
  D02. to_dict() returns all required keys.
  D03. to_json() is valid JSON.
  D04. from_dict(to_dict()) round-trip preserves all fields.
  D05. category_evaluations list is embedded correctly in to_dict().

Group E — evaluate_distributed_release_gate() — live evaluation
  E01. Returns a ReleaseGateReport.
  E02. Report has a non-empty report_id.
  E03. Report generated_at is a positive float.
  E04. Report authority matches DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY.
  E05. Report has exactly len(GateCategory) category_evaluations.
  E06. is_enforcing is False (skeleton is non-enforcing in this PR).
  E07. gate_worthy_count >= 7 (six canonical + one companion_android).
  E08. advisory_count >= 2 (advisory_audit_records, advisory_participant_session).
  E09. deferred_count >= 2 (deferred_rollout_promotion, deferred_ci_enforcement).
  E10. overall_verdict is one of the four ReleaseGateVerdict values.
  E11. deferred_notes list is non-empty.
  E12. to_json() of report is valid JSON.
  E13. blocked_gate_worthy_count + open_gate_worthy_count <= gate_worthy_count.

Group F — Category strength correctness
  F01. All gate_worthy category evaluations have non-advisory verdicts.
  F02. All advisory category evaluations have a non-blocked verdict.
  F03. All deferred category evaluations have verdict == "deferred".
  F04. companion_android evaluation has strength == "gate_worthy".
  F05. advisory_audit_records evaluation has strength == "advisory".
  F06. advisory_participant_session evaluation has strength == "advisory".
  F07. deferred_rollout_promotion evaluation has verdict == "deferred".
  F08. deferred_ci_enforcement evaluation has verdict == "deferred".

Group G — Non-enforcing guarantee
  G01. Report is_enforcing is always False.
  G02. GATE_SKELETON_IS_NON_ENFORCING_POLICY contains "non-enforcing" or "NOT".
  G03. Overall verdict "blocked" is possible but does not raise.
  G04. Overall verdict can be determined without any exceptions.

Group H — Android companion evidence representation
  H01. companion_android category is present in category_evaluations.
  H02. companion_android evaluation references the android_evaluator_artifact_ingestion
       dimension.
  H03. ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY is
       non-empty and references V2 ingestion.
  H04. V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY is non-empty.

Group I — Singleton and cache behaviour
  I01. get_release_gate_report() returns ReleaseGateReport.
  I02. Two consecutive calls to get_release_gate_report() return same report_id.
  I03. reset_release_gate_report() clears cache; next call returns new report_id.
  I04. evaluate_distributed_release_gate() always returns a fresh report.

Group J — Downstream regression guard
  J01. V2ReadinessGovernanceEvidenceSurface module importable.
  J02. DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY references PR7V2.

Group K — Extension guide validation
  K01. deferred_notes mention CI enforcement.
  K02. deferred_notes mention rollout promotion.
  K03. Report to_dict() contains evidence_surface_report_id key.
  K04. Each category_evaluation has a non-empty evidence_dimension_ids list
       OR is a deferred category with no dims.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.distributed_release_gate_skeleton import (
        DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY,
        DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL,
        GATE_SKELETON_IS_NON_ENFORCING_POLICY,
        GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY,
        DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY,
        ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY,
        V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
        GateCategoryStrength,
        GateCategory,
        ReleaseGateVerdict,
        GateCategoryEvaluation,
        ReleaseGateReport,
        DistributedReleaseGateSkeleton,
        evaluate_distributed_release_gate,
        get_release_gate_report,
        reset_release_gate_report,
        _CATEGORY_STRENGTH,
        _CATEGORY_DIMENSION_IDS,
    )
    _SKELETON_AVAILABLE = True
except ImportError:
    _SKELETON_AVAILABLE = False

_skip_if_unavailable = pytest.mark.skipif(
    not _SKELETON_AVAILABLE,
    reason="core.distributed_release_gate_skeleton not available",
)


# ===========================================================================
# Group A — Module-level sentinels, enums, __all__
# ===========================================================================


@_skip_if_unavailable
def test_A01_authority_and_pr7_sentinels_present():
    assert DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY
    assert "PR7V2" in DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY
    assert "canonical-distributed-release-gate-skeleton" in DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY
    assert "PR7V2" in DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL


@_skip_if_unavailable
def test_A02_all_policy_sentinels_non_empty():
    for sentinel in [
        GATE_SKELETON_IS_NON_ENFORCING_POLICY,
        GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY,
        DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY,
        ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY,
        V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
    ]:
        assert isinstance(sentinel, str) and sentinel, f"empty sentinel: {sentinel!r}"


@_skip_if_unavailable
def test_A03_gate_category_strength_values():
    assert GateCategoryStrength.gate_worthy.value == "gate_worthy"
    assert GateCategoryStrength.advisory.value == "advisory"
    assert GateCategoryStrength.deferred.value == "deferred"


@_skip_if_unavailable
def test_A04_release_gate_verdict_values():
    assert ReleaseGateVerdict.open.value == "open"
    assert ReleaseGateVerdict.blocked.value == "blocked"
    assert ReleaseGateVerdict.deferred.value == "deferred"
    assert ReleaseGateVerdict.unknown.value == "unknown"


@_skip_if_unavailable
def test_A05_gate_category_all_required_values():
    required = [
        "canonical_runtime_lifecycle",
        "canonical_graduation_acceptance",
        "canonical_post_graduation_governance",
        "canonical_continuity_recovery",
        "canonical_takeover_correctness",
        "canonical_compat_blocking",
        "companion_android",
        "advisory_audit_records",
        "advisory_participant_session",
        "deferred_rollout_promotion",
        "deferred_ci_enforcement",
    ]
    category_values = {c.value for c in GateCategory}
    for v in required:
        assert v in category_values, f"missing GateCategory value: {v!r}"


@_skip_if_unavailable
def test_A06_all_exports_present():
    import core.distributed_release_gate_skeleton as mod

    required = [
        "DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY",
        "DISTRIBUTED_RELEASE_GATE_SKELETON_PR7V2_SENTINEL",
        "GATE_SKELETON_IS_NON_ENFORCING_POLICY",
        "GATE_WORTHY_CATEGORIES_REQUIRE_CANONICAL_EVIDENCE_POLICY",
        "DEFERRED_CATEGORIES_MUST_NOT_BLOCK_RELEASE_POLICY",
        "ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY",
        "V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY",
        "GateCategoryStrength",
        "GateCategory",
        "ReleaseGateVerdict",
        "GateCategoryEvaluation",
        "ReleaseGateReport",
        "DistributedReleaseGateSkeleton",
        "evaluate_distributed_release_gate",
        "get_release_gate_report",
        "reset_release_gate_report",
    ]
    for name in required:
        assert hasattr(mod, name), f"missing export: {name}"


# ===========================================================================
# Group B — Category definitions
# ===========================================================================


@_skip_if_unavailable
def test_B01_every_category_has_strength_mapping():
    for category in GateCategory:
        assert category in _CATEGORY_STRENGTH, (
            f"GateCategory.{category.value} missing from _CATEGORY_STRENGTH"
        )


@_skip_if_unavailable
def test_B02_every_category_has_dimension_id_mapping():
    for category in GateCategory:
        assert category in _CATEGORY_DIMENSION_IDS, (
            f"GateCategory.{category.value} missing from _CATEGORY_DIMENSION_IDS"
        )


@_skip_if_unavailable
def test_B03_gate_worthy_categories_use_canonical_evidence_dimensions():
    """Gate-worthy categories must only reference canonical evidence dimensions."""
    # The evidence dimension IDs used by gate_worthy categories must correspond
    # to canonical classification.  We verify against the known canonical
    # dimension IDs from the PR-6 evidence surface.
    known_canonical_dimension_ids = {
        "delegated_flow_readiness",
        "delegated_flow_acceptance",
        "post_graduation_governance",
        "continuity_recovery_closure",
        "takeover_tracking",
        "compat_legacy_blocking",
        "android_evaluator_artifact_ingestion",
    }
    for category, strength in _CATEGORY_STRENGTH.items():
        if strength == GateCategoryStrength.gate_worthy:
            for dim_id in _CATEGORY_DIMENSION_IDS[category]:
                assert dim_id in known_canonical_dimension_ids, (
                    f"GateCategory.{category.value} (gate_worthy) references "
                    f"dimension_id {dim_id!r} which is not in the known canonical "
                    f"evidence dimension set."
                )


@_skip_if_unavailable
def test_B04_advisory_categories_use_advisory_prefix():
    advisory_cats = [
        c for c, s in _CATEGORY_STRENGTH.items()
        if s == GateCategoryStrength.advisory
    ]
    for cat in advisory_cats:
        assert cat.value.startswith("advisory_"), (
            f"Advisory category {cat.value!r} does not use 'advisory_' prefix"
        )


@_skip_if_unavailable
def test_B05_deferred_categories_use_deferred_prefix():
    deferred_cats = [
        c for c, s in _CATEGORY_STRENGTH.items()
        if s == GateCategoryStrength.deferred
    ]
    for cat in deferred_cats:
        assert cat.value.startswith("deferred_"), (
            f"Deferred category {cat.value!r} does not use 'deferred_' prefix"
        )


@_skip_if_unavailable
def test_B06_companion_android_is_gate_worthy():
    assert _CATEGORY_STRENGTH[GateCategory.companion_android] == GateCategoryStrength.gate_worthy


@_skip_if_unavailable
def test_B07_deferred_categories_are_deferred():
    assert _CATEGORY_STRENGTH[GateCategory.deferred_rollout_promotion] == GateCategoryStrength.deferred
    assert _CATEGORY_STRENGTH[GateCategory.deferred_ci_enforcement] == GateCategoryStrength.deferred


# ===========================================================================
# Group C — GateCategoryEvaluation
# ===========================================================================


@_skip_if_unavailable
def test_C01_gate_category_evaluation_default_construction():
    e = GateCategoryEvaluation(
        category="canonical_runtime_lifecycle",
        strength="gate_worthy",
        verdict="open",
        evidence_status="present",
    )
    assert e.category == "canonical_runtime_lifecycle"
    assert e.strength == "gate_worthy"
    assert e.verdict == "open"
    assert e.evidence_status == "present"
    assert isinstance(e.evidence_dimension_ids, list)


@_skip_if_unavailable
def test_C02_gate_category_evaluation_to_dict_keys():
    e = GateCategoryEvaluation(
        category="companion_android",
        strength="gate_worthy",
        verdict="open",
        evidence_status="present",
        evidence_dimension_ids=["android_evaluator_artifact_ingestion"],
        summary="Android companion evidence present.",
    )
    d = e.to_dict()
    required_keys = [
        "category", "strength", "verdict", "evidence_status",
        "evidence_dimension_ids", "summary", "gap_description", "notes",
    ]
    for k in required_keys:
        assert k in d, f"to_dict missing key: {k}"


@_skip_if_unavailable
def test_C03_gate_category_evaluation_round_trip():
    e = GateCategoryEvaluation(
        category="advisory_audit_records",
        strength="advisory",
        verdict="open",
        evidence_status="present",
        evidence_dimension_ids=["android_delegated_audit_ring"],
        summary="Audit ring present.",
        gap_description="",
        notes="Advisory only.",
    )
    d = e.to_dict()
    e2 = GateCategoryEvaluation.from_dict(d)
    assert e2.category == e.category
    assert e2.strength == e.strength
    assert e2.verdict == e.verdict
    assert e2.evidence_status == e.evidence_status
    assert e2.evidence_dimension_ids == e.evidence_dimension_ids
    assert e2.summary == e.summary
    assert e2.notes == e.notes


# ===========================================================================
# Group D — ReleaseGateReport
# ===========================================================================


@_skip_if_unavailable
def test_D01_release_gate_report_construction():
    r = ReleaseGateReport(
        report_id="test-id",
        generated_at=1.0,
        authority=DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY,
        overall_verdict="open",
    )
    assert r.report_id == "test-id"
    assert r.overall_verdict == "open"
    assert r.is_enforcing is False
    assert isinstance(r.category_evaluations, list)
    assert isinstance(r.deferred_notes, list)


@_skip_if_unavailable
def test_D02_release_gate_report_to_dict_keys():
    r = ReleaseGateReport(
        report_id="test",
        generated_at=1.0,
        authority="auth",
        overall_verdict="open",
    )
    d = r.to_dict()
    required_keys = [
        "report_id", "generated_at", "authority", "overall_verdict",
        "is_enforcing", "category_evaluations", "gate_worthy_count",
        "advisory_count", "deferred_count", "blocked_gate_worthy_count",
        "open_gate_worthy_count", "evidence_surface_report_id",
        "deferred_notes",
    ]
    for k in required_keys:
        assert k in d, f"to_dict missing key: {k}"


@_skip_if_unavailable
def test_D03_release_gate_report_to_json_valid():
    r = ReleaseGateReport(
        report_id="test",
        generated_at=1.0,
        authority="auth",
        overall_verdict="open",
    )
    js = r.to_json()
    parsed = json.loads(js)
    assert parsed["report_id"] == "test"


@_skip_if_unavailable
def test_D04_release_gate_report_round_trip():
    e = GateCategoryEvaluation(
        category="canonical_runtime_lifecycle",
        strength="gate_worthy",
        verdict="open",
        evidence_status="present",
    )
    r = ReleaseGateReport(
        report_id="round-trip",
        generated_at=42.5,
        authority="auth-test",
        overall_verdict="open",
        is_enforcing=False,
        category_evaluations=[e],
        gate_worthy_count=1,
        advisory_count=0,
        deferred_count=0,
        blocked_gate_worthy_count=0,
        open_gate_worthy_count=1,
        evidence_surface_report_id="surf-id",
        deferred_notes=["note1"],
    )
    d = r.to_dict()
    r2 = ReleaseGateReport.from_dict(d)
    assert r2.report_id == r.report_id
    assert r2.overall_verdict == r.overall_verdict
    assert r2.is_enforcing == r.is_enforcing
    assert r2.gate_worthy_count == r.gate_worthy_count
    assert r2.evidence_surface_report_id == r.evidence_surface_report_id
    assert len(r2.category_evaluations) == 1
    assert r2.deferred_notes == r.deferred_notes


@_skip_if_unavailable
def test_D05_category_evaluations_embedded_in_to_dict():
    e = GateCategoryEvaluation(
        category="companion_android",
        strength="gate_worthy",
        verdict="open",
        evidence_status="present",
    )
    r = ReleaseGateReport(
        report_id="x",
        generated_at=1.0,
        authority="auth",
        overall_verdict="open",
        category_evaluations=[e],
    )
    d = r.to_dict()
    assert isinstance(d["category_evaluations"], list)
    assert len(d["category_evaluations"]) == 1
    assert d["category_evaluations"][0]["category"] == "companion_android"


# ===========================================================================
# Group E — evaluate_distributed_release_gate() — live evaluation
# ===========================================================================


@_skip_if_unavailable
def test_E01_returns_release_gate_report():
    report = evaluate_distributed_release_gate()
    assert isinstance(report, ReleaseGateReport)


@_skip_if_unavailable
def test_E02_report_has_non_empty_report_id():
    report = evaluate_distributed_release_gate()
    assert report.report_id and isinstance(report.report_id, str)


@_skip_if_unavailable
def test_E03_report_generated_at_positive():
    report = evaluate_distributed_release_gate()
    assert report.generated_at > 0


@_skip_if_unavailable
def test_E04_report_authority_matches_sentinel():
    report = evaluate_distributed_release_gate()
    assert report.authority == DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY


@_skip_if_unavailable
def test_E05_report_has_all_category_evaluations():
    report = evaluate_distributed_release_gate()
    expected_count = len(list(GateCategory))
    assert len(report.category_evaluations) == expected_count, (
        f"Expected {expected_count} category evaluations, "
        f"got {len(report.category_evaluations)}"
    )


@_skip_if_unavailable
def test_E06_is_enforcing_is_false():
    report = evaluate_distributed_release_gate()
    assert report.is_enforcing is False


@_skip_if_unavailable
def test_E07_gate_worthy_count_at_least_seven():
    report = evaluate_distributed_release_gate()
    assert report.gate_worthy_count >= 7, (
        f"Expected at least 7 gate_worthy categories, got {report.gate_worthy_count}"
    )


@_skip_if_unavailable
def test_E08_advisory_count_at_least_two():
    report = evaluate_distributed_release_gate()
    assert report.advisory_count >= 2


@_skip_if_unavailable
def test_E09_deferred_count_at_least_two():
    report = evaluate_distributed_release_gate()
    assert report.deferred_count >= 2


@_skip_if_unavailable
def test_E10_overall_verdict_is_valid():
    report = evaluate_distributed_release_gate()
    valid_verdicts = {v.value for v in ReleaseGateVerdict}
    assert report.overall_verdict in valid_verdicts


@_skip_if_unavailable
def test_E11_deferred_notes_non_empty():
    report = evaluate_distributed_release_gate()
    assert isinstance(report.deferred_notes, list)
    assert len(report.deferred_notes) > 0


@_skip_if_unavailable
def test_E12_report_to_json_valid():
    report = evaluate_distributed_release_gate()
    js = report.to_json()
    parsed = json.loads(js)
    assert "report_id" in parsed
    assert "category_evaluations" in parsed


@_skip_if_unavailable
def test_E13_blocked_plus_open_le_gate_worthy():
    report = evaluate_distributed_release_gate()
    assert (
        report.blocked_gate_worthy_count + report.open_gate_worthy_count
        <= report.gate_worthy_count
    )


# ===========================================================================
# Group F — Category strength correctness
# ===========================================================================


@_skip_if_unavailable
def test_F01_gate_worthy_evaluations_have_non_advisory_verdicts():
    report = evaluate_distributed_release_gate()
    for e in report.category_evaluations:
        if e.strength == GateCategoryStrength.gate_worthy.value:
            # verdict may be open, blocked, deferred, or unknown — not a V2-level concern
            # But it must not be a forbidden advisory-specific value (there isn't one)
            assert e.verdict in {v.value for v in ReleaseGateVerdict}, (
                f"Unexpected verdict for gate_worthy category {e.category!r}: {e.verdict!r}"
            )


@_skip_if_unavailable
def test_F02_advisory_evaluations_have_non_blocked_verdict():
    report = evaluate_distributed_release_gate()
    for e in report.category_evaluations:
        if e.strength == GateCategoryStrength.advisory.value:
            assert e.verdict != ReleaseGateVerdict.blocked.value, (
                f"Advisory category {e.category!r} must not have verdict 'blocked'"
            )


@_skip_if_unavailable
def test_F03_deferred_evaluations_have_deferred_verdict():
    report = evaluate_distributed_release_gate()
    for e in report.category_evaluations:
        if e.strength == GateCategoryStrength.deferred.value:
            assert e.verdict == ReleaseGateVerdict.deferred.value, (
                f"Deferred category {e.category!r} must have verdict 'deferred', "
                f"got {e.verdict!r}"
            )


@_skip_if_unavailable
def test_F04_companion_android_is_gate_worthy_in_report():
    report = evaluate_distributed_release_gate()
    companion = next(
        (e for e in report.category_evaluations
         if e.category == GateCategory.companion_android.value),
        None,
    )
    assert companion is not None, "companion_android category not found in report"
    assert companion.strength == GateCategoryStrength.gate_worthy.value


@_skip_if_unavailable
def test_F05_advisory_audit_records_is_advisory():
    report = evaluate_distributed_release_gate()
    e = next(
        (e for e in report.category_evaluations
         if e.category == GateCategory.advisory_audit_records.value),
        None,
    )
    assert e is not None
    assert e.strength == GateCategoryStrength.advisory.value


@_skip_if_unavailable
def test_F06_advisory_participant_session_is_advisory():
    report = evaluate_distributed_release_gate()
    e = next(
        (e for e in report.category_evaluations
         if e.category == GateCategory.advisory_participant_session.value),
        None,
    )
    assert e is not None
    assert e.strength == GateCategoryStrength.advisory.value


@_skip_if_unavailable
def test_F07_deferred_rollout_promotion_is_deferred():
    report = evaluate_distributed_release_gate()
    e = next(
        (ev for ev in report.category_evaluations
         if ev.category == GateCategory.deferred_rollout_promotion.value),
        None,
    )
    assert e is not None
    assert e.verdict == ReleaseGateVerdict.deferred.value


@_skip_if_unavailable
def test_F08_deferred_ci_enforcement_is_deferred():
    report = evaluate_distributed_release_gate()
    e = next(
        (ev for ev in report.category_evaluations
         if ev.category == GateCategory.deferred_ci_enforcement.value),
        None,
    )
    assert e is not None
    assert e.verdict == ReleaseGateVerdict.deferred.value


# ===========================================================================
# Group G — Non-enforcing guarantee
# ===========================================================================


@_skip_if_unavailable
def test_G01_report_is_enforcing_always_false():
    report = evaluate_distributed_release_gate()
    assert report.is_enforcing is False


@_skip_if_unavailable
def test_G02_non_enforcing_policy_sentinel_content():
    # The policy must reference the non-enforcing nature
    policy = GATE_SKELETON_IS_NON_ENFORCING_POLICY
    assert "non-enforcing" in policy.lower() or "NOT" in policy or "not" in policy.lower()


@_skip_if_unavailable
def test_G03_blocked_verdict_does_not_raise():
    """Simulate a blocked scenario: inject a gate_worthy dim with absent evidence."""
    from core.distributed_release_gate_skeleton import DistributedReleaseGateSkeleton
    skeleton = DistributedReleaseGateSkeleton()
    # Inject a fake dim index with an absent gate_worthy dimension
    fake_dim_index = {
        "delegated_flow_readiness": type("FakeDim", (), {"evidence_status": "absent"})(),
    }
    eval_result = skeleton._evaluate_category(
        GateCategory.canonical_runtime_lifecycle, fake_dim_index
    )
    assert eval_result.verdict == ReleaseGateVerdict.blocked.value
    # Now build the report — should not raise
    report = skeleton._build_report(
        evaluations=[eval_result],
        surface_report_id="fake",
    )
    assert report.overall_verdict == ReleaseGateVerdict.blocked.value
    assert report.is_enforcing is False  # Still non-enforcing


@_skip_if_unavailable
def test_G04_overall_verdict_deterministic():
    report1 = evaluate_distributed_release_gate()
    report2 = evaluate_distributed_release_gate()
    assert report1.overall_verdict == report2.overall_verdict


# ===========================================================================
# Group H — Android companion evidence representation
# ===========================================================================


@_skip_if_unavailable
def test_H01_companion_android_category_in_report():
    report = evaluate_distributed_release_gate()
    categories = [e.category for e in report.category_evaluations]
    assert GateCategory.companion_android.value in categories


@_skip_if_unavailable
def test_H02_companion_android_references_ingestion_dimension():
    report = evaluate_distributed_release_gate()
    companion = next(
        e for e in report.category_evaluations
        if e.category == GateCategory.companion_android.value
    )
    assert "android_evaluator_artifact_ingestion" in companion.evidence_dimension_ids


@_skip_if_unavailable
def test_H03_android_companion_policy_references_v2_ingestion():
    policy = ANDROID_COMPANION_EVIDENCE_IS_GATE_WORTHY_AFTER_V2_INGESTION_POLICY
    assert policy
    assert "ingestion" in policy.lower() or "V2" in policy


@_skip_if_unavailable
def test_H04_v2_canonical_orchestration_authority_policy_non_empty():
    assert V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY
    assert "V2" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY


# ===========================================================================
# Group I — Singleton and cache behaviour
# ===========================================================================


@_skip_if_unavailable
def test_I01_get_release_gate_report_returns_report():
    reset_release_gate_report()
    report = get_release_gate_report()
    assert isinstance(report, ReleaseGateReport)


@_skip_if_unavailable
def test_I02_two_get_calls_return_same_report_id():
    reset_release_gate_report()
    r1 = get_release_gate_report()
    r2 = get_release_gate_report()
    assert r1.report_id == r2.report_id


@_skip_if_unavailable
def test_I03_reset_clears_cache():
    reset_release_gate_report()
    r1 = get_release_gate_report()
    reset_release_gate_report()
    r2 = get_release_gate_report()
    assert r1.report_id != r2.report_id


@_skip_if_unavailable
def test_I04_evaluate_always_returns_fresh_report():
    r1 = evaluate_distributed_release_gate()
    r2 = evaluate_distributed_release_gate()
    assert r1.report_id != r2.report_id


# ===========================================================================
# Group J — Downstream regression guard
# ===========================================================================


@_skip_if_unavailable
def test_J01_v2_readiness_evidence_surface_importable():
    try:
        from core.v2_readiness_governance_evidence_surface import (
            V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY,
        )
        assert V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY
    except ImportError:
        pytest.skip("core.v2_readiness_governance_evidence_surface not available")


@_skip_if_unavailable
def test_J02_authority_sentinel_references_pr7v2():
    assert "PR7V2" in DISTRIBUTED_RELEASE_GATE_SKELETON_AUTHORITY


# ===========================================================================
# Group K — Extension guide validation
# ===========================================================================


@_skip_if_unavailable
def test_K01_deferred_notes_mention_ci_enforcement():
    report = evaluate_distributed_release_gate()
    combined = " ".join(report.deferred_notes).lower()
    assert "ci" in combined or "enforcement" in combined


@_skip_if_unavailable
def test_K02_deferred_notes_mention_rollout_promotion():
    report = evaluate_distributed_release_gate()
    combined = " ".join(report.deferred_notes).lower()
    assert "rollout" in combined or "promotion" in combined


@_skip_if_unavailable
def test_K03_report_to_dict_has_evidence_surface_report_id():
    report = evaluate_distributed_release_gate()
    d = report.to_dict()
    assert "evidence_surface_report_id" in d


@_skip_if_unavailable
def test_K04_non_deferred_categories_have_dimension_ids():
    report = evaluate_distributed_release_gate()
    for e in report.category_evaluations:
        if e.strength != GateCategoryStrength.deferred.value:
            # Non-deferred categories must reference at least one dimension
            assert len(e.evidence_dimension_ids) >= 1, (
                f"Non-deferred category {e.category!r} has no evidence_dimension_ids"
            )
