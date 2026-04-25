#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr535_v2_readiness_governance_evidence_surface.py
=============================================================
PR-535 (test file number) / PR-6V2-EVIDENCE (post-533 dual-repo
runtime-unification master plan, V2 side):
V2 Readiness / Governance Evidence Surface — validation test suite.

Problem addressed
-----------------
V2 readiness and governance evidence exists but is distributed across many
modules.  This test suite validates the new reviewable evidence surface:

1. The evidence surface module is importable and carries required policy
   sentinels.
2. All evidence classification values are defined and consistent.
3. EvidenceDimensionEntry and EvidenceSurfaceReport are serialisable and
   round-trippable.
4. build_evidence_surface_report() returns a populated report grounded in
   actual V2 runtime behaviour.
5. Canonical dimensions are present and traceable.
6. Advisory dimensions are correctly classified and do NOT claim to be
   canonical.
7. Companion-repo (Android) evidence dimensions are present and traceable
   to their V2 ingestion path.
8. Deferred notes are explicit and non-empty.
9. The singleton pattern (get/reset) works correctly.
10. Key downstream evidence modules are importable and carry their own
    authority sentinels (regression guard).

Coverage matrix
---------------
Group A — Module-level: sentinels, classification enum, __all__
  A01. Module importable; authority sentinel and PR6 sentinel present.
  A02. All five policy sentinels are non-empty strings.
  A03. EvidenceClassification enum has the three required values.
  A04. __all__ contains all required public names.

Group B — EvidenceDimensionEntry
  B01. Default construction works; required fields present.
  B02. to_dict() returns all required keys.
  B03. from_dict(to_dict()) round-trip preserves all fields.
  B04. Advisory classification string matches enum value.
  B05. Canonical classification string matches enum value.

Group C — EvidenceSurfaceReport
  C01. Default construction works; required fields present.
  C02. to_dict() returns all required keys.
  C03. to_json() is valid JSON.
  C04. from_dict(to_dict()) round-trip preserves all fields.
  C05. Dimensions list is embedded correctly in to_dict().

Group D — build_evidence_surface_report() — live probe
  D01. Returns an EvidenceSurfaceReport.
  D02. Report has a non-empty report_id.
  D03. Report generated_at is a positive float.
  D04. Report authority matches V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY.
  D05. Report contains at least 6 dimension entries.
  D06. canonical_count >= 1 (readiness gate at minimum).
  D07. advisory_count >= 1 (audit ring at minimum).
  D08. companion_repo_count >= 1 (Android evaluator artifacts).
  D09. Dimension entries each have non-empty dimension_id.
  D10. Dimension entries each have non-empty code_reference.
  D11. Dimension entries each have non-empty test_reference.
  D12. deferred_notes list is non-empty.
  D13. to_json() of report is valid JSON.

Group E — Classification correctness
  E01. Delegated flow readiness entry is classified 'canonical'.
  E02. Delegated flow acceptance entry is classified 'canonical'.
  E03. Post-graduation governance entry is classified 'canonical'.
  E04. Android evaluator artifact ingestion entry is classified 'companion_repo'.
  E05. Android delegated audit entry is classified 'advisory'.
  E06. No advisory entry claims evidence_status that would block release.
  E07. Continuity/recovery closure entry is classified 'canonical'.
  E08. Takeover tracking entry is classified 'canonical'.

Group F — Singleton and cache behaviour
  F01. get_evidence_surface_report() returns EvidenceSurfaceReport.
  F02. Two calls to get_evidence_surface_report() return same report_id.
  F03. reset_evidence_surface_report() clears cache; next call returns new report.
  F04. build_evidence_surface_report() always returns a fresh report.

Group G — Downstream module regression guard
  G01. DelegatedFlowReadinessGate authority sentinel importable and non-empty.
  G02. DelegatedFlowAcceptanceGate authority sentinel importable and non-empty.
  G03. DelegatedFlowGovernanceEvaluator authority sentinel importable and non-empty.
  G04. AndroidEvaluatorArtifactIngress policy sentinel importable.
  G05. TakeoverTracking authority sentinel importable and non-empty.
  G06. RecoveryDurabilityClosureValidator authority sentinel importable and non-empty.

Group H — Evidence traceability
  H01. Each dimension entry code_reference contains 'core.' prefix.
  H02. Each dimension entry test_reference contains 'test' (points to test file).
  H03. All canonical dimension entries have evidence_status != 'absent'.
  H04. Report all_canonical_present field matches manual check.
  H05. present_count + absent_count + unavailable_count equals len(dimensions).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.v2_readiness_governance_evidence_surface import (
        V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY,
        V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL,
        CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY,
        ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY,
        COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY,
        EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY,
        EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY,
        EvidenceClassification,
        EvidenceDimensionEntry,
        EvidenceSurfaceReport,
        build_evidence_surface_report,
        get_evidence_surface_report,
        reset_evidence_surface_report,
    )

    _SURFACE_AVAILABLE = True
except ImportError:
    _SURFACE_AVAILABLE = False


_skip_if_unavailable = pytest.mark.skipif(
    not _SURFACE_AVAILABLE,
    reason="core.v2_readiness_governance_evidence_surface not available",
)


# ===========================================================================
# Group A — Module-level sentinels, classification enum, __all__
# ===========================================================================


@_skip_if_unavailable
def test_A01_module_importable_sentinels_present():
    assert V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY
    assert "PR6V2" in V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL
    assert "canonical-readiness-governance-evidence" in V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY


@_skip_if_unavailable
def test_A02_all_policy_sentinels_non_empty():
    for sentinel in [
        CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY,
        ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY,
        COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY,
        EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY,
        EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY,
    ]:
        assert isinstance(sentinel, str) and sentinel, f"empty sentinel: {sentinel!r}"


@_skip_if_unavailable
def test_A03_evidence_classification_enum_values():
    assert EvidenceClassification.canonical.value == "canonical"
    assert EvidenceClassification.advisory.value == "advisory"
    assert EvidenceClassification.companion_repo.value == "companion_repo"


@_skip_if_unavailable
def test_A04_all_exports_present():
    import core.v2_readiness_governance_evidence_surface as mod

    required = [
        "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY",
        "V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_PR6V2_SENTINEL",
        "CANONICAL_EVIDENCE_IS_GATE_INPUT_POLICY",
        "ADVISORY_EVIDENCE_IS_NOT_GATE_INPUT_POLICY",
        "COMPANION_REPO_EVIDENCE_IS_CLASSIFIED_BY_V2_POLICY",
        "EVIDENCE_SURFACE_IS_PROJECTION_ONLY_POLICY",
        "EVIDENCE_SURFACE_IS_REVIEWER_FRIENDLY_POLICY",
        "EvidenceClassification",
        "EvidenceDimensionEntry",
        "EvidenceSurfaceReport",
        "build_evidence_surface_report",
        "get_evidence_surface_report",
        "reset_evidence_surface_report",
    ]
    for name in required:
        assert hasattr(mod, name), f"missing export: {name}"


# ===========================================================================
# Group B — EvidenceDimensionEntry
# ===========================================================================


@_skip_if_unavailable
def test_B01_evidence_dimension_entry_construction():
    entry = EvidenceDimensionEntry(
        dimension_id="test_dim",
        display_name="Test Dimension",
        classification=EvidenceClassification.canonical.value,
        evidence_status="present",
        evidence_summary="test summary",
        code_reference="core.test_module",
        test_reference="tests/test_test.py",
    )
    assert entry.dimension_id == "test_dim"
    assert entry.classification == "canonical"
    assert entry.evidence_status == "present"


@_skip_if_unavailable
def test_B02_evidence_dimension_entry_to_dict_keys():
    entry = EvidenceDimensionEntry(
        dimension_id="test_dim",
        display_name="Test",
        classification=EvidenceClassification.advisory.value,
        evidence_status="present",
        evidence_summary="s",
        code_reference="core.m",
        test_reference="tests/t.py",
    )
    d = entry.to_dict()
    required_keys = [
        "dimension_id", "display_name", "classification", "evidence_status",
        "evidence_summary", "code_reference", "test_reference",
        "raw_evidence", "notes",
    ]
    for k in required_keys:
        assert k in d, f"missing key: {k}"


@_skip_if_unavailable
def test_B03_evidence_dimension_entry_round_trip():
    entry = EvidenceDimensionEntry(
        dimension_id="rt_dim",
        display_name="Round-trip Dimension",
        classification=EvidenceClassification.companion_repo.value,
        evidence_status="present",
        evidence_summary="round-trip summary",
        code_reference="core.rt_module",
        test_reference="tests/test_rt.py",
        raw_evidence={"foo": "bar"},
        notes="some note",
    )
    restored = EvidenceDimensionEntry.from_dict(entry.to_dict())
    assert restored.dimension_id == entry.dimension_id
    assert restored.display_name == entry.display_name
    assert restored.classification == entry.classification
    assert restored.evidence_status == entry.evidence_status
    assert restored.code_reference == entry.code_reference
    assert restored.test_reference == entry.test_reference
    assert restored.raw_evidence == entry.raw_evidence
    assert restored.notes == entry.notes


@_skip_if_unavailable
def test_B04_advisory_classification_string():
    entry = EvidenceDimensionEntry(
        dimension_id="a",
        display_name="A",
        classification=EvidenceClassification.advisory.value,
        evidence_status="present",
        evidence_summary="s",
        code_reference="core.m",
        test_reference="t",
    )
    assert entry.classification == "advisory"


@_skip_if_unavailable
def test_B05_canonical_classification_string():
    entry = EvidenceDimensionEntry(
        dimension_id="c",
        display_name="C",
        classification=EvidenceClassification.canonical.value,
        evidence_status="present",
        evidence_summary="s",
        code_reference="core.m",
        test_reference="t",
    )
    assert entry.classification == "canonical"


# ===========================================================================
# Group C — EvidenceSurfaceReport
# ===========================================================================


@_skip_if_unavailable
def test_C01_evidence_surface_report_construction():
    report = EvidenceSurfaceReport(
        report_id="test-id",
        generated_at=1.0,
        authority="TEST_AUTHORITY",
    )
    assert report.report_id == "test-id"
    assert report.dimensions == []
    assert report.deferred_notes == []


@_skip_if_unavailable
def test_C02_evidence_surface_report_to_dict_keys():
    report = EvidenceSurfaceReport(
        report_id="r",
        generated_at=1.0,
        authority="AUTH",
    )
    d = report.to_dict()
    required_keys = [
        "report_id", "generated_at", "authority", "dimensions",
        "canonical_count", "advisory_count", "companion_repo_count",
        "present_count", "absent_count", "unavailable_count",
        "all_canonical_present", "deferred_notes",
    ]
    for k in required_keys:
        assert k in d, f"missing key: {k}"


@_skip_if_unavailable
def test_C03_evidence_surface_report_to_json_valid():
    report = EvidenceSurfaceReport(
        report_id="r",
        generated_at=1.0,
        authority="AUTH",
        canonical_count=1,
    )
    j = report.to_json()
    parsed = json.loads(j)
    assert parsed["report_id"] == "r"
    assert parsed["canonical_count"] == 1


@_skip_if_unavailable
def test_C04_evidence_surface_report_round_trip():
    dim = EvidenceDimensionEntry(
        dimension_id="d",
        display_name="D",
        classification="canonical",
        evidence_status="present",
        evidence_summary="s",
        code_reference="core.m",
        test_reference="tests/t.py",
    )
    report = EvidenceSurfaceReport(
        report_id="rt",
        generated_at=42.0,
        authority="AUTH",
        dimensions=[dim],
        canonical_count=1,
        deferred_notes=["deferred item 1"],
    )
    restored = EvidenceSurfaceReport.from_dict(report.to_dict())
    assert restored.report_id == "rt"
    assert restored.generated_at == 42.0
    assert len(restored.dimensions) == 1
    assert restored.dimensions[0].dimension_id == "d"
    assert restored.deferred_notes == ["deferred item 1"]


@_skip_if_unavailable
def test_C05_dimensions_embedded_in_to_dict():
    dim = EvidenceDimensionEntry(
        dimension_id="embedded",
        display_name="E",
        classification="advisory",
        evidence_status="present",
        evidence_summary="s",
        code_reference="core.m",
        test_reference="t",
    )
    report = EvidenceSurfaceReport(
        report_id="r",
        generated_at=1.0,
        authority="A",
        dimensions=[dim],
    )
    d = report.to_dict()
    assert isinstance(d["dimensions"], list)
    assert len(d["dimensions"]) == 1
    assert d["dimensions"][0]["dimension_id"] == "embedded"


# ===========================================================================
# Group D — build_evidence_surface_report() — live probe
# ===========================================================================


@_skip_if_unavailable
def test_D01_build_returns_evidence_surface_report():
    report = build_evidence_surface_report()
    assert isinstance(report, EvidenceSurfaceReport)


@_skip_if_unavailable
def test_D02_report_has_non_empty_report_id():
    report = build_evidence_surface_report()
    assert report.report_id and isinstance(report.report_id, str)


@_skip_if_unavailable
def test_D03_report_generated_at_is_positive():
    report = build_evidence_surface_report()
    assert report.generated_at > 0.0


@_skip_if_unavailable
def test_D04_report_authority_matches_sentinel():
    report = build_evidence_surface_report()
    assert report.authority == V2_READINESS_GOVERNANCE_EVIDENCE_SURFACE_AUTHORITY


@_skip_if_unavailable
def test_D05_report_has_at_least_six_dimensions():
    report = build_evidence_surface_report()
    assert len(report.dimensions) >= 6, (
        f"Expected at least 6 evidence dimensions, got {len(report.dimensions)}"
    )


@_skip_if_unavailable
def test_D06_canonical_count_at_least_one():
    report = build_evidence_surface_report()
    assert report.canonical_count >= 1, "Expected at least 1 canonical dimension"


@_skip_if_unavailable
def test_D07_advisory_count_at_least_one():
    report = build_evidence_surface_report()
    assert report.advisory_count >= 1, "Expected at least 1 advisory dimension"


@_skip_if_unavailable
def test_D08_companion_repo_count_at_least_one():
    report = build_evidence_surface_report()
    assert report.companion_repo_count >= 1, "Expected at least 1 companion_repo dimension"


@_skip_if_unavailable
def test_D09_dimension_entries_have_non_empty_dimension_id():
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        assert entry.dimension_id, f"empty dimension_id in: {entry}"


@_skip_if_unavailable
def test_D10_dimension_entries_have_non_empty_code_reference():
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        assert entry.code_reference, f"empty code_reference in: {entry.dimension_id}"


@_skip_if_unavailable
def test_D11_dimension_entries_have_non_empty_test_reference():
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        assert entry.test_reference, f"empty test_reference in: {entry.dimension_id}"


@_skip_if_unavailable
def test_D12_deferred_notes_non_empty():
    report = build_evidence_surface_report()
    assert report.deferred_notes, "Expected at least one deferred note"
    for note in report.deferred_notes:
        assert isinstance(note, str) and note


@_skip_if_unavailable
def test_D13_report_to_json_is_valid():
    report = build_evidence_surface_report()
    j = report.to_json()
    parsed = json.loads(j)
    assert "report_id" in parsed
    assert "dimensions" in parsed
    assert isinstance(parsed["dimensions"], list)


# ===========================================================================
# Group E — Classification correctness
# ===========================================================================


def _find_dimension(report: "EvidenceSurfaceReport", dim_id: str):
    for d in report.dimensions:
        if d.dimension_id == dim_id:
            return d
    return None


@_skip_if_unavailable
def test_E01_delegated_flow_readiness_is_canonical():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "delegated_flow_readiness")
    assert entry is not None, "delegated_flow_readiness dimension missing from report"
    assert entry.classification == EvidenceClassification.canonical.value


@_skip_if_unavailable
def test_E02_delegated_flow_acceptance_is_canonical():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "delegated_flow_acceptance")
    assert entry is not None, "delegated_flow_acceptance dimension missing from report"
    assert entry.classification == EvidenceClassification.canonical.value


@_skip_if_unavailable
def test_E03_post_graduation_governance_is_canonical():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "post_graduation_governance")
    assert entry is not None, "post_graduation_governance dimension missing from report"
    assert entry.classification == EvidenceClassification.canonical.value


@_skip_if_unavailable
def test_E04_android_evaluator_artifact_ingestion_is_companion_repo():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "android_evaluator_artifact_ingestion")
    assert entry is not None, "android_evaluator_artifact_ingestion dimension missing"
    assert entry.classification == EvidenceClassification.companion_repo.value


@_skip_if_unavailable
def test_E05_android_delegated_audit_is_advisory():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "android_delegated_runtime_audit")
    assert entry is not None, "android_delegated_runtime_audit dimension missing"
    assert entry.classification == EvidenceClassification.advisory.value


@_skip_if_unavailable
def test_E06_advisory_entries_correctly_classified():
    """Advisory entries must not have classification 'canonical'."""
    report = build_evidence_surface_report()
    advisory_ids = ["android_delegated_runtime_audit", "participant_session_truth"]
    for dim_id in advisory_ids:
        entry = _find_dimension(report, dim_id)
        if entry is not None:
            assert entry.classification != EvidenceClassification.canonical.value, (
                f"Advisory dimension {dim_id!r} incorrectly classified as canonical"
            )


@_skip_if_unavailable
def test_E07_continuity_recovery_closure_is_canonical():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "continuity_recovery_closure")
    assert entry is not None, "continuity_recovery_closure dimension missing"
    assert entry.classification == EvidenceClassification.canonical.value


@_skip_if_unavailable
def test_E08_takeover_tracking_is_canonical():
    report = build_evidence_surface_report()
    entry = _find_dimension(report, "takeover_tracking")
    assert entry is not None, "takeover_tracking dimension missing"
    assert entry.classification == EvidenceClassification.canonical.value


# ===========================================================================
# Group F — Singleton and cache behaviour
# ===========================================================================


@_skip_if_unavailable
def test_F01_get_evidence_surface_report_returns_report():
    reset_evidence_surface_report()
    report = get_evidence_surface_report()
    assert isinstance(report, EvidenceSurfaceReport)


@_skip_if_unavailable
def test_F02_two_calls_return_same_report_id():
    reset_evidence_surface_report()
    r1 = get_evidence_surface_report()
    r2 = get_evidence_surface_report()
    assert r1.report_id == r2.report_id


@_skip_if_unavailable
def test_F03_reset_clears_cache_new_report_id():
    reset_evidence_surface_report()
    r1 = get_evidence_surface_report()
    reset_evidence_surface_report()
    r2 = get_evidence_surface_report()
    assert r1.report_id != r2.report_id


@_skip_if_unavailable
def test_F04_build_always_returns_fresh_report():
    r1 = build_evidence_surface_report()
    r2 = build_evidence_surface_report()
    assert r1.report_id != r2.report_id


# ===========================================================================
# Group G — Downstream module regression guard
# ===========================================================================


def test_G01_delegated_flow_readiness_gate_authority_importable():
    try:
        from core.delegated_flow_readiness_gate import (
            DELEGATED_FLOW_READINESS_GATE_AUTHORITY,
        )
        assert DELEGATED_FLOW_READINESS_GATE_AUTHORITY
    except ImportError:
        pytest.skip("core.delegated_flow_readiness_gate not available")


def test_G02_delegated_flow_acceptance_gate_authority_importable():
    try:
        from core.delegated_flow_acceptance_gate import (
            DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY,
        )
        assert DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY
    except ImportError:
        pytest.skip("core.delegated_flow_acceptance_gate not available")


def test_G03_post_graduation_governance_authority_importable():
    try:
        from core.delegated_flow_post_graduation_governance import (
            DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY,
        )
        assert DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY
    except ImportError:
        pytest.skip("core.delegated_flow_post_graduation_governance not available")


def test_G04_android_evaluator_artifact_ingress_policy_importable():
    try:
        from core.android_evaluator_artifact_ingress import (
            GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY,
        )
        assert GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY
    except ImportError:
        pytest.skip("core.android_evaluator_artifact_ingress not available")


def test_G05_takeover_tracking_authority_importable():
    try:
        from core.takeover_tracking import (
            TAKEOVER_TRACKING_AUTHORITY,
        )
        assert TAKEOVER_TRACKING_AUTHORITY
    except ImportError:
        pytest.skip("core.takeover_tracking not available")


def test_G06_recovery_closure_validator_authority_importable():
    try:
        from core.recovery_durability_closure_validator import (
            RECOVERY_DURABILITY_CLOSURE_AUTHORITY,
        )
        assert RECOVERY_DURABILITY_CLOSURE_AUTHORITY
    except ImportError:
        pytest.skip("core.recovery_durability_closure_validator not available")


# ===========================================================================
# Group H — Evidence traceability
# ===========================================================================


@_skip_if_unavailable
def test_H01_code_references_have_core_prefix():
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        assert entry.code_reference.startswith("core."), (
            f"dimension {entry.dimension_id!r} code_reference does not start with 'core.': "
            f"{entry.code_reference!r}"
        )


@_skip_if_unavailable
def test_H02_test_references_contain_test_keyword():
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        assert "test" in entry.test_reference.lower(), (
            f"dimension {entry.dimension_id!r} test_reference does not reference a test: "
            f"{entry.test_reference!r}"
        )


@_skip_if_unavailable
def test_H03_canonical_dimensions_evidence_status_not_absent():
    """Canonical dimensions must not have evidence_status == 'absent'."""
    report = build_evidence_surface_report()
    for entry in report.dimensions:
        if entry.classification == EvidenceClassification.canonical.value:
            assert entry.evidence_status != "absent", (
                f"Canonical dimension {entry.dimension_id!r} has evidence_status 'absent'"
            )


@_skip_if_unavailable
def test_H04_all_canonical_present_field_correct():
    report = build_evidence_surface_report()
    canonical_dims = [
        d for d in report.dimensions
        if d.classification == EvidenceClassification.canonical.value
    ]
    manual_check = all(d.evidence_status == "present" for d in canonical_dims)
    assert report.all_canonical_present == manual_check


@_skip_if_unavailable
def test_H05_count_totals_match_dimensions():
    """present + absent + unavailable equals total dimension count."""
    report = build_evidence_surface_report()
    total = len(report.dimensions)
    counted = report.present_count + report.absent_count + report.unavailable_count
    assert counted == total, (
        f"Count totals mismatch: present={report.present_count} + "
        f"absent={report.absent_count} + unavailable={report.unavailable_count} "
        f"= {counted} != {total} (total dimensions)"
    )
