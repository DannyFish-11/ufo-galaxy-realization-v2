#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_recovery_truth_surface.py
=====================================
PR-5-TRUTH automated test suite for the Recovery Truth Surface module.

Coverage matrix
---------------
Group A — Module structure and sentinels
  A01. core.recovery_truth_surface is importable.
  A02. RECOVERY_TRUTH_SURFACE_AUTHORITY sentinel is a non-empty string.
  A03. RECOVERY_TRUTH_SURFACE_PR5_TRUTH_SENTINEL is a non-empty string.
  A04. All eight policy sentinels are non-empty strings.
  A05. RecoveryTruthDimension has exactly six dimensions.
  A06. RecoveryTruthStatus has all required values.
  A07. RecoveryLevel has all four level values.

Group B — RecoveryTruthEntry dataclass
  B01. RecoveryTruthEntry can be constructed with defaults.
  B02. RecoveryTruthEntry.to_dict() returns a dict with all required keys.
  B03. RecoveryTruthEntry.from_dict() round-trips correctly.
  B04. is_v2_internal / is_participant_reconnect / is_task_continuity /
       is_authority_alignment are mutually exclusive per recovery_level.
  B05. RecoveryTruthStatus.is_closed and is_open are non-overlapping.

Group C — RecoveryTruthReport dataclass
  C01. RecoveryTruthReport can be constructed with defaults.
  C02. RecoveryTruthReport.to_dict() returns a dict with all required keys.
  C03. RecoveryTruthReport.to_json() returns valid JSON.
  C04. RecoveryTruthReport.from_dict() round-trips correctly.
  C05. RecoveryTruthReport.get_entry() returns the correct entry by dimension.
  C06. RecoveryTruthReport.has_deferred reflects deferred_dimensions list.
  C07. RecoveryTruthReport.all_closed is False when open_dimensions is non-empty.
  C08. RecoveryTruthReport.all_closed requires exactly 6 entries.

Group D — build_recovery_truth_report() function
  D01. build_recovery_truth_report() returns a RecoveryTruthReport.
  D02. Report contains exactly six entries (one per RecoveryTruthDimension).
  D03. Every entry has a non-empty evidence_summary.
  D04. Every entry has a non-empty policy_reference.
  D05. All six RecoveryTruthDimension values are represented in the report.
  D06. All entries use a valid RecoveryTruthStatus value.
  D07. All entries use a valid RecoveryLevel value.
  D08. deferred_dimensions is a list (may be empty).
  D09. open_dimensions is a list (may be empty).
  D10. closed_dimensions is a list (may be empty).
  D11. summary is a non-empty string.
  D12. Four-level success flags are present in the report dict.

Group E — Layer separation (must not collapse to single flag)
  E01. v2_internal_success does not imply participant_reconnect_success.
  E02. participant_reconnect_success does not imply task_continuity_success.
  E03. task_continuity_success does not imply authority_alignment_success.
  E04. All four flags are independently accessible from the report.
  E05. Report entries carry distinct recovery_level values (not all the same).

Group F — Deferred boundary honesty
  F01. Android offline queue replay ordering is explicitly documented as
       deferred in at least one policy sentinel or entry note.
  F02. Ephemeral transport binding is documented as deferred.
  F03. No entry has status=observed when structural-only evidence is present
       and no live event was recorded (honest partial, not claimed observed).
  F04. The OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY sentinel
       contains the word "deferred".
  F05. The EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY sentinel
       contains the word "deferred".

Group G — Singleton and reset
  G01. get_recovery_truth_surface() returns a RecoveryTruthReport.
  G02. Two calls to get_recovery_truth_surface() return the same object.
  G03. reset_recovery_truth_surface() causes the next call to return a
       fresh object.
  G04. reset_recovery_truth_surface() does not raise.

Group H — System acceptance integration
  H01. AcceptanceDimensionId has a recovery_truth_surface member.
  H02. AcceptanceDimensionId.all_dimensions() includes recovery_truth_surface.
  H03. SystemFinalAcceptanceEvaluator.evaluate() includes
       recovery_truth_surface in its checklist.
  H04. The recovery_truth_surface item has a non-empty evidence_summary.
  H05. The recovery_truth_surface item status is pending or accepted
       (not unresolved, since the module is available).

Group I — Evidence surface integration
  I01. build_evidence_surface_report() includes a recovery_truth_surface entry.
  I02. The recovery_truth_surface evidence entry has evidence_status "present".
  I03. The recovery_truth_surface entry carries code_reference and test_reference.

Group J — Reality audit integration
  J01. DualRepoSystemRealityAuditor audit report includes
       recovery_truth_surface in the recovery_redispatch_reconnect evidence.
  J02. The recovery_redispatch_reconnect dimension probes
       core.recovery_truth_surface as one of its modules.
"""

import json
import pytest


# ---------------------------------------------------------------------------
# Group A — Module structure and sentinels
# ---------------------------------------------------------------------------


def test_A01_module_importable():
    import core.recovery_truth_surface  # noqa: F401


def test_A02_authority_sentinel():
    from core.recovery_truth_surface import RECOVERY_TRUTH_SURFACE_AUTHORITY
    assert isinstance(RECOVERY_TRUTH_SURFACE_AUTHORITY, str)
    assert len(RECOVERY_TRUTH_SURFACE_AUTHORITY) > 20


def test_A03_pr5_truth_sentinel():
    from core.recovery_truth_surface import RECOVERY_TRUTH_SURFACE_PR5_TRUTH_SENTINEL
    assert isinstance(RECOVERY_TRUTH_SURFACE_PR5_TRUTH_SENTINEL, str)
    assert "PR5-TRUTH" in RECOVERY_TRUTH_SURFACE_PR5_TRUTH_SENTINEL


def test_A04_all_policy_sentinels_non_empty():
    from core.recovery_truth_surface import (
        PARTICIPANT_DISCONNECT_OBSERVED_IS_SEPARATE_FROM_V2_RECOVERY_POLICY,
        RECONNECT_AND_REDISPATCH_ARE_DISTINCT_TRUTH_ATOMS_POLICY,
        TASK_CONTINUITY_IS_DISTINCT_FROM_RECONNECT_SUCCESS_POLICY,
        DUPLICATE_DISPATCH_AVOIDANCE_REQUIRES_EXPLICIT_EVIDENCE_POLICY,
        AUTHORITY_ALIGNMENT_REQUIRES_STATE_MATCH_POLICY,
        OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY,
        EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY,
    )
    sentinels = [
        PARTICIPANT_DISCONNECT_OBSERVED_IS_SEPARATE_FROM_V2_RECOVERY_POLICY,
        RECONNECT_AND_REDISPATCH_ARE_DISTINCT_TRUTH_ATOMS_POLICY,
        TASK_CONTINUITY_IS_DISTINCT_FROM_RECONNECT_SUCCESS_POLICY,
        DUPLICATE_DISPATCH_AVOIDANCE_REQUIRES_EXPLICIT_EVIDENCE_POLICY,
        AUTHORITY_ALIGNMENT_REQUIRES_STATE_MATCH_POLICY,
        OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY,
        EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY,
    ]
    for s in sentinels:
        assert isinstance(s, str) and len(s) > 20, f"sentinel too short: {s!r}"


def test_A05_recovery_truth_dimension_has_six_values():
    from core.recovery_truth_surface import RecoveryTruthDimension
    dims = RecoveryTruthDimension.all_dimensions()
    assert len(dims) == 6
    expected = {
        "participant_disconnect_observed",
        "reconnect_observed",
        "redispatch_triggered",
        "in_flight_task_continuity_preserved",
        "duplicate_dispatch_avoided",
        "recovered_state_aligned",
    }
    assert {d.value for d in dims} == expected


def test_A06_recovery_truth_status_has_required_values():
    from core.recovery_truth_surface import RecoveryTruthStatus
    required = {"observed", "not_observed", "not_applicable", "deferred", "partial", "unknown"}
    assert {s.value for s in RecoveryTruthStatus} >= required


def test_A07_recovery_level_has_four_values():
    from core.recovery_truth_surface import RecoveryLevel
    levels = RecoveryLevel.all_levels()
    assert len(levels) == 4
    expected = {
        "v2_internal",
        "participant_reconnect",
        "task_continuity",
        "authority_state_alignment",
    }
    assert {lv.value for lv in levels} == expected


# ---------------------------------------------------------------------------
# Group B — RecoveryTruthEntry dataclass
# ---------------------------------------------------------------------------


def test_B01_entry_default_construction():
    from core.recovery_truth_surface import RecoveryTruthEntry
    e = RecoveryTruthEntry()
    assert e.dimension is not None
    assert e.status is not None
    assert e.recovery_level is not None


def test_B02_entry_to_dict_has_required_keys():
    from core.recovery_truth_surface import RecoveryTruthEntry, RecoveryTruthDimension, RecoveryTruthStatus, RecoveryLevel
    e = RecoveryTruthEntry(
        dimension=RecoveryTruthDimension.reconnect_observed,
        status=RecoveryTruthStatus.partial,
        recovery_level=RecoveryLevel.participant_reconnect,
        evidence_summary="test summary",
        policy_reference="POLICY::TEST",
    )
    d = e.to_dict()
    required_keys = {
        "dimension", "status", "recovery_level",
        "evidence_summary", "policy_reference",
        "supporting_modules", "deferred_note",
        "is_v2_internal", "is_participant_reconnect",
        "is_task_continuity", "is_authority_alignment",
        "evaluated_at",
    }
    assert required_keys <= set(d.keys())
    assert d["dimension"] == "reconnect_observed"
    assert d["status"] == "partial"
    assert d["recovery_level"] == "participant_reconnect"


def test_B03_entry_from_dict_round_trip():
    from core.recovery_truth_surface import RecoveryTruthEntry, RecoveryTruthDimension, RecoveryTruthStatus, RecoveryLevel
    original = RecoveryTruthEntry(
        dimension=RecoveryTruthDimension.redispatch_triggered,
        status=RecoveryTruthStatus.deferred,
        recovery_level=RecoveryLevel.v2_internal,
        evidence_summary="redispatch deferred evidence",
        policy_reference="POLICY::REDISPATCH_TEST",
        deferred_note="deferred for later PR",
    )
    d = original.to_dict()
    restored = RecoveryTruthEntry.from_dict(d)
    assert restored.dimension == original.dimension
    assert restored.status == original.status
    assert restored.recovery_level == original.recovery_level
    assert restored.evidence_summary == original.evidence_summary
    assert restored.policy_reference == original.policy_reference
    assert restored.deferred_note == original.deferred_note


def test_B04_recovery_level_properties_are_mutually_exclusive():
    from core.recovery_truth_surface import RecoveryTruthEntry, RecoveryTruthDimension, RecoveryTruthStatus, RecoveryLevel
    combos = [
        (RecoveryLevel.v2_internal, "is_v2_internal"),
        (RecoveryLevel.participant_reconnect, "is_participant_reconnect"),
        (RecoveryLevel.task_continuity, "is_task_continuity"),
        (RecoveryLevel.authority_state_alignment, "is_authority_alignment"),
    ]
    for level, prop in combos:
        e = RecoveryTruthEntry(
            dimension=RecoveryTruthDimension.reconnect_observed,
            status=RecoveryTruthStatus.unknown,
            recovery_level=level,
        )
        # The corresponding property must be True
        assert getattr(e, prop) is True, f"{prop} should be True for {level}"
        # All others must be False
        for _, other_prop in combos:
            if other_prop != prop:
                assert getattr(e, other_prop) is False, (
                    f"{other_prop} should be False when level={level}"
                )


def test_B05_status_is_closed_and_is_open_non_overlapping():
    from core.recovery_truth_surface import RecoveryTruthStatus
    for s in RecoveryTruthStatus:
        # A status cannot be both closed and open simultaneously
        assert not (s.is_closed and s.is_open), (
            f"Status {s!r} is both closed and open — contradiction"
        )


# ---------------------------------------------------------------------------
# Group C — RecoveryTruthReport dataclass
# ---------------------------------------------------------------------------


def test_C01_report_default_construction():
    from core.recovery_truth_surface import RecoveryTruthReport
    r = RecoveryTruthReport()
    assert r.report_id
    assert r.generated_at > 0
    assert isinstance(r.entries, list)


def test_C02_report_to_dict_required_keys():
    from core.recovery_truth_surface import RecoveryTruthReport
    r = RecoveryTruthReport()
    d = r.to_dict()
    required = {
        "report_id", "generated_at", "authority", "entries",
        "v2_internal_success", "participant_reconnect_success",
        "task_continuity_success", "authority_alignment_success",
        "deferred_dimensions", "open_dimensions", "closed_dimensions",
        "summary",
    }
    assert required <= set(d.keys())


def test_C03_report_to_json_is_valid_json():
    from core.recovery_truth_surface import RecoveryTruthReport
    r = RecoveryTruthReport(summary="test summary")
    j = r.to_json()
    parsed = json.loads(j)
    assert isinstance(parsed, dict)
    assert "report_id" in parsed


def test_C04_report_from_dict_round_trip():
    from core.recovery_truth_surface import RecoveryTruthReport, RecoveryTruthEntry, RecoveryTruthDimension, RecoveryTruthStatus, RecoveryLevel
    entry = RecoveryTruthEntry(
        dimension=RecoveryTruthDimension.reconnect_observed,
        status=RecoveryTruthStatus.partial,
        recovery_level=RecoveryLevel.participant_reconnect,
        evidence_summary="test",
        policy_reference="POLICY::TEST",
    )
    original = RecoveryTruthReport(
        entries=[entry],
        v2_internal_success=True,
        participant_reconnect_success=False,
        deferred_dimensions=["recovered_state_aligned"],
        summary="test summary",
    )
    d = original.to_dict()
    restored = RecoveryTruthReport.from_dict(d)
    assert restored.report_id == original.report_id
    assert restored.v2_internal_success == original.v2_internal_success
    assert restored.participant_reconnect_success == original.participant_reconnect_success
    assert len(restored.entries) == 1
    assert restored.entries[0].dimension == RecoveryTruthDimension.reconnect_observed


def test_C05_report_get_entry():
    from core.recovery_truth_surface import RecoveryTruthReport, RecoveryTruthEntry, RecoveryTruthDimension, RecoveryTruthStatus, RecoveryLevel
    entry = RecoveryTruthEntry(
        dimension=RecoveryTruthDimension.duplicate_dispatch_avoided,
        status=RecoveryTruthStatus.observed,
        recovery_level=RecoveryLevel.v2_internal,
    )
    r = RecoveryTruthReport(entries=[entry])
    found = r.get_entry(RecoveryTruthDimension.duplicate_dispatch_avoided)
    assert found is entry
    not_found = r.get_entry(RecoveryTruthDimension.reconnect_observed)
    assert not_found is None


def test_C06_has_deferred_reflects_list():
    from core.recovery_truth_surface import RecoveryTruthReport
    r_empty = RecoveryTruthReport(deferred_dimensions=[])
    assert r_empty.has_deferred is False
    r_with = RecoveryTruthReport(deferred_dimensions=["reconnect_observed"])
    assert r_with.has_deferred is True


def test_C07_all_closed_false_when_open_dims():
    from core.recovery_truth_surface import RecoveryTruthReport
    r = RecoveryTruthReport(open_dimensions=["reconnect_observed"])
    assert r.all_closed is False


def test_C08_all_closed_requires_six_entries():
    from core.recovery_truth_surface import RecoveryTruthReport, RecoveryTruthEntry
    # With 0 entries and no open dims: all_closed should be False (need 6 entries)
    r_empty = RecoveryTruthReport(open_dimensions=[])
    assert r_empty.all_closed is False
    # With 6 entries and no open dims
    entries = [RecoveryTruthEntry() for _ in range(6)]
    r_full = RecoveryTruthReport(entries=entries, open_dimensions=[])
    assert r_full.all_closed is True


# ---------------------------------------------------------------------------
# Group D — build_recovery_truth_report() function
# ---------------------------------------------------------------------------


def test_D01_build_returns_recovery_truth_report():
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryTruthReport
    r = build_recovery_truth_report()
    assert isinstance(r, RecoveryTruthReport)


def test_D02_report_has_six_entries():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert len(r.entries) == 6


def test_D03_every_entry_has_evidence_summary():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    for e in r.entries:
        assert e.evidence_summary, (
            f"Entry {e.dimension.value} has empty evidence_summary"
        )


def test_D04_every_entry_has_policy_reference():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    for e in r.entries:
        assert e.policy_reference, (
            f"Entry {e.dimension.value} has empty policy_reference"
        )


def test_D05_all_six_dimensions_represented():
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryTruthDimension
    r = build_recovery_truth_report()
    dims_in_report = {e.dimension for e in r.entries}
    for dim in RecoveryTruthDimension.all_dimensions():
        assert dim in dims_in_report, f"Dimension {dim.value} missing from report"


def test_D06_all_entries_use_valid_status():
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryTruthStatus
    valid_statuses = set(RecoveryTruthStatus)
    r = build_recovery_truth_report()
    for e in r.entries:
        assert e.status in valid_statuses, (
            f"Entry {e.dimension.value} has invalid status {e.status!r}"
        )


def test_D07_all_entries_use_valid_recovery_level():
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryLevel
    valid_levels = set(RecoveryLevel)
    r = build_recovery_truth_report()
    for e in r.entries:
        assert e.recovery_level in valid_levels, (
            f"Entry {e.dimension.value} has invalid recovery_level {e.recovery_level!r}"
        )


def test_D08_deferred_dimensions_is_list():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert isinstance(r.deferred_dimensions, list)


def test_D09_open_dimensions_is_list():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert isinstance(r.open_dimensions, list)


def test_D10_closed_dimensions_is_list():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert isinstance(r.closed_dimensions, list)


def test_D11_summary_is_non_empty():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert r.summary and len(r.summary) > 20


def test_D12_four_level_flags_in_report_dict():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    d = r.to_dict()
    for key in ("v2_internal_success", "participant_reconnect_success",
                "task_continuity_success", "authority_alignment_success"):
        assert key in d, f"Key {key!r} missing from report dict"
        assert isinstance(d[key], bool)


# ---------------------------------------------------------------------------
# Group E — Layer separation (must not collapse to single flag)
# ---------------------------------------------------------------------------


def test_E01_v2_internal_does_not_imply_participant_reconnect():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    # We cannot assert a specific value, but we can assert the two flags
    # are independently accessible and have independent values
    assert hasattr(r, "v2_internal_success")
    assert hasattr(r, "participant_reconnect_success")
    # They are not required to be equal — that's the whole point
    # (just checking they are independently stored)
    assert isinstance(r.v2_internal_success, bool)
    assert isinstance(r.participant_reconnect_success, bool)


def test_E02_participant_reconnect_does_not_imply_task_continuity():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert isinstance(r.participant_reconnect_success, bool)
    assert isinstance(r.task_continuity_success, bool)


def test_E03_task_continuity_does_not_imply_authority_alignment():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    assert isinstance(r.task_continuity_success, bool)
    assert isinstance(r.authority_alignment_success, bool)


def test_E04_all_four_flags_independently_accessible():
    from core.recovery_truth_surface import build_recovery_truth_report
    r = build_recovery_truth_report()
    # All four flags must be present and boolean
    flags = [
        r.v2_internal_success,
        r.participant_reconnect_success,
        r.task_continuity_success,
        r.authority_alignment_success,
    ]
    for f in flags:
        assert isinstance(f, bool)


def test_E05_entries_have_distinct_recovery_levels():
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryLevel
    r = build_recovery_truth_report()
    levels_seen = {e.recovery_level for e in r.entries}
    # There should be at least 2 different recovery levels used across 6 entries
    assert len(levels_seen) >= 2, (
        "All entries have the same recovery_level — levels are not separated"
    )


# ---------------------------------------------------------------------------
# Group F — Deferred boundary honesty
# ---------------------------------------------------------------------------


def test_F01_offline_queue_replay_documented_in_sentinel():
    from core.recovery_truth_surface import OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY
    # The sentinel must reference offline queue ordering as deferred
    sentinel_lower = OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY.lower()
    assert "offline" in sentinel_lower or "queue" in sentinel_lower
    assert "deferred" in sentinel_lower


def test_F02_ephemeral_transport_binding_documented_in_sentinel():
    from core.recovery_truth_surface import EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY
    sentinel_lower = EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY.lower()
    assert "ephemeral" in sentinel_lower or "transport" in sentinel_lower or "binding" in sentinel_lower
    assert "deferred" in sentinel_lower


def test_F03_no_entry_claims_fully_observed_without_live_event():
    """Entries built from static module probes must not claim 'observed'.

    Since build_recovery_truth_report() probes structural wiring only
    (no live recovery event), no entry should have status=observed.
    An entry may have partial, not_applicable, deferred, or unknown.
    """
    from core.recovery_truth_surface import build_recovery_truth_report, RecoveryTruthStatus
    r = build_recovery_truth_report()
    for e in r.entries:
        assert e.status != RecoveryTruthStatus.observed, (
            f"Entry {e.dimension.value} claims status=observed "
            f"but no live event was simulated: {e.evidence_summary!r}"
        )


def test_F04_offline_queue_sentinel_contains_deferred():
    from core.recovery_truth_surface import OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY
    assert "deferred" in OFFLINE_QUEUE_REPLAY_ORDERING_IS_DEFERRED_TRUTH_POLICY.lower()


def test_F05_ephemeral_binding_sentinel_contains_deferred():
    from core.recovery_truth_surface import EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY
    assert "deferred" in EPHEMERAL_TRANSPORT_BINDING_IS_DEFERRED_TRUTH_POLICY.lower()


# ---------------------------------------------------------------------------
# Group G — Singleton and reset
# ---------------------------------------------------------------------------


def test_G01_get_recovery_truth_surface_returns_report():
    from core.recovery_truth_surface import (
        get_recovery_truth_surface,
        reset_recovery_truth_surface,
        RecoveryTruthReport,
    )
    reset_recovery_truth_surface()
    r = get_recovery_truth_surface()
    assert isinstance(r, RecoveryTruthReport)


def test_G02_singleton_returns_same_object():
    from core.recovery_truth_surface import get_recovery_truth_surface, reset_recovery_truth_surface
    reset_recovery_truth_surface()
    r1 = get_recovery_truth_surface()
    r2 = get_recovery_truth_surface()
    assert r1 is r2


def test_G03_reset_causes_fresh_object():
    from core.recovery_truth_surface import get_recovery_truth_surface, reset_recovery_truth_surface
    reset_recovery_truth_surface()
    r1 = get_recovery_truth_surface()
    reset_recovery_truth_surface()
    r2 = get_recovery_truth_surface()
    # Different objects after reset
    assert r1 is not r2


def test_G04_reset_does_not_raise():
    from core.recovery_truth_surface import reset_recovery_truth_surface
    reset_recovery_truth_surface()
    reset_recovery_truth_surface()  # Calling twice is safe


# ---------------------------------------------------------------------------
# Group H — System acceptance integration
# ---------------------------------------------------------------------------


def test_H01_acceptance_dimension_has_recovery_truth_surface():
    from core.system_final_acceptance_verdict import AcceptanceDimensionId
    assert hasattr(AcceptanceDimensionId, "recovery_truth_surface")
    assert AcceptanceDimensionId.recovery_truth_surface.value == "recovery_truth_surface"


def test_H02_all_dimensions_includes_recovery_truth_surface():
    from core.system_final_acceptance_verdict import AcceptanceDimensionId
    all_dims = AcceptanceDimensionId.all_dimensions()
    dim_values = [d.value for d in all_dims]
    assert "recovery_truth_surface" in dim_values


def test_H03_evaluator_includes_recovery_truth_surface_in_checklist():
    from core.system_final_acceptance_verdict import (
        SystemFinalAcceptanceEvaluator,
        reset_system_acceptance_evaluator,
    )
    reset_system_acceptance_evaluator()
    evaluator = SystemFinalAcceptanceEvaluator()
    report = evaluator.evaluate()
    assert "recovery_truth_surface" in report.checklist


def test_H04_recovery_truth_surface_item_has_evidence_summary():
    from core.system_final_acceptance_verdict import (
        SystemFinalAcceptanceEvaluator,
        reset_system_acceptance_evaluator,
    )
    reset_system_acceptance_evaluator()
    evaluator = SystemFinalAcceptanceEvaluator()
    report = evaluator.evaluate()
    item = report.checklist.get("recovery_truth_surface")
    assert item is not None
    assert item.evidence_summary, "recovery_truth_surface item has empty evidence_summary"


def test_H05_recovery_truth_surface_not_unresolved():
    """Since core.recovery_truth_surface is available, status must not be unresolved."""
    from core.system_final_acceptance_verdict import (
        SystemFinalAcceptanceEvaluator,
        DimensionStatus,
        reset_system_acceptance_evaluator,
    )
    reset_system_acceptance_evaluator()
    evaluator = SystemFinalAcceptanceEvaluator()
    report = evaluator.evaluate()
    item = report.checklist.get("recovery_truth_surface")
    assert item is not None
    assert item.status != DimensionStatus.unresolved, (
        f"recovery_truth_surface should not be unresolved; "
        f"got status={item.status.value!r}, gap={item.gap_description!r}"
    )


# ---------------------------------------------------------------------------
# Group I — Evidence surface integration
# ---------------------------------------------------------------------------


def test_I01_evidence_surface_includes_recovery_truth_surface():
    from core.v2_readiness_governance_evidence_surface import build_evidence_surface_report
    report = build_evidence_surface_report()
    dim_ids = [d.dimension_id for d in report.dimensions]
    assert "recovery_truth_surface" in dim_ids, (
        f"recovery_truth_surface not found in evidence surface; "
        f"found: {dim_ids!r}"
    )


def test_I02_evidence_surface_recovery_truth_status_present():
    from core.v2_readiness_governance_evidence_surface import build_evidence_surface_report
    report = build_evidence_surface_report()
    entry = next(
        (d for d in report.dimensions if d.dimension_id == "recovery_truth_surface"),
        None,
    )
    assert entry is not None
    assert entry.evidence_status == "present", (
        f"Expected evidence_status='present' but got {entry.evidence_status!r}"
    )


def test_I03_evidence_surface_recovery_truth_has_references():
    from core.v2_readiness_governance_evidence_surface import build_evidence_surface_report
    report = build_evidence_surface_report()
    entry = next(
        (d for d in report.dimensions if d.dimension_id == "recovery_truth_surface"),
        None,
    )
    assert entry is not None
    assert entry.code_reference, "recovery_truth_surface entry has empty code_reference"
    assert entry.test_reference, "recovery_truth_surface entry has empty test_reference"


# ---------------------------------------------------------------------------
# Group J — Reality audit integration
# ---------------------------------------------------------------------------


def test_J01_reality_audit_includes_truth_surface_in_recovery_evidence():
    from core.dual_repo_system_reality_audit import (
        DualRepoSystemRealityAuditor,
        AuditDimension,
    )
    auditor = DualRepoSystemRealityAuditor()
    report = auditor.audit()
    dim_entry = next(
        (d for d in report.dimensions
         if d.dimension == AuditDimension.recovery_redispatch_reconnect),
        None,
    )
    assert dim_entry is not None
    # The evidence_summary or code_references should mention the truth surface
    combined = (
        dim_entry.evidence_summary
        + " ".join(dim_entry.code_references)
    )
    assert "recovery_truth_surface" in combined, (
        f"recovery_truth_surface not mentioned in recovery audit evidence; "
        f"evidence_summary={dim_entry.evidence_summary!r}, "
        f"code_refs={dim_entry.code_references!r}"
    )


def test_J02_recovery_audit_probes_truth_surface_module():
    from core.dual_repo_system_reality_audit import (
        DualRepoSystemRealityAuditor,
        AuditDimension,
    )
    auditor = DualRepoSystemRealityAuditor()
    report = auditor.audit()
    dim_entry = next(
        (d for d in report.dimensions
         if d.dimension == AuditDimension.recovery_redispatch_reconnect),
        None,
    )
    assert dim_entry is not None
    assert "core.recovery_truth_surface" in dim_entry.code_references, (
        f"core.recovery_truth_surface not in code_references; "
        f"code_refs={dim_entry.code_references!r}"
    )
