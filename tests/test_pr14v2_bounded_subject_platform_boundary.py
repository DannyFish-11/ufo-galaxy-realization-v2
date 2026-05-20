#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr14v2_bounded_subject_platform_boundary.py
==========================================================
PR-14V2: Bounded Subject Platform Boundary — regression tests.

Locks the following invariants:

 1.  Module is importable; authority and PR-14V2 sentinel are non-empty
     strings containing expected keywords.
 2.  QUASI_PLATFORM_STATE_DEFINITION contains required vocabulary.
 3.  All five policy sentinels are non-empty and contain expected keywords.
 4.  PlatformBoundaryAxis enum contains all five expected axis values.
 5.  BoundaryAxisDescriptor dataclass — to_dict() produces all required keys.
 6.  PlatformBoundarySnapshot dataclass — to_dict() produces all required keys.
 7.  PLATFORM_BOUNDARY_AXIS_REGISTRY has exactly five entries, one per axis.
 8.  Every axis descriptor has non-empty code_evidence.
 9.  Every axis descriptor has android_v2_consistent=True.
10.  Every axis descriptor has no_parallel_authority=True.
11.  build_platform_boundary_snapshot() — returns intact snapshot with zero
     violations when all five axes are structurally sound.
12.  build_platform_boundary_snapshot() — snapshot carries all five axes.
13.  assert_quasi_platform_state_intact() — does not raise when snapshot is
     intact.
14.  QuasiPlatformStateBoundaryViolation is raised only when an axis is
     misconfigured (android_v2_consistent=False or no_parallel_authority=False).
15.  get_platform_boundary_axes() returns a list of all five axes.
16.  get_system_definition() returns the QUASI_PLATFORM_STATE_DEFINITION string.
17.  Snapshot to_json() is valid JSON containing all required top-level keys.
18.  Snapshot axis_count equals five.
19.  CANONICAL_CENTER axis code_evidence references center_authority_boundary.
20.  BOUNDED_SUBJECT axis code_evidence references distributed_subject_contract_v1.
21.  PARTICIPANT_GOVERNANCE axis code_evidence references operator_action_governance.
22.  OBSERVABILITY_EVIDENCE axis code_evidence references cross_subject_observability_contract.
23.  OUTWARD_CONSUMPTION axis code_evidence references final_acceptance_surface_boundary.
24.  No axis has an axis value that duplicates another axis value.
25.  CANONICAL_CENTER policy sentinel references "canonical center".
26.  BOUNDED_SUBJECT policy sentinel references "global truth finalization".
27.  PARTICIPANT_GOVERNANCE policy sentinel references "participant lifecycle".
28.  OBSERVABILITY_EVIDENCE policy sentinel references "parallel" and "authority".
29.  OUTWARD_CONSUMPTION policy sentinel references "consumption".
30.  Authority sentinel references "quasi-platform state" concepts.
"""

from __future__ import annotations

import json
import pytest

from core.bounded_subject_platform_boundary import (
    BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY,
    BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL,
    BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY,
    CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY,
    OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY,
    OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY,
    PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY,
    PLATFORM_BOUNDARY_AXIS_REGISTRY,
    QUASI_PLATFORM_STATE_DEFINITION,
    BoundaryAxisDescriptor,
    PlatformBoundaryAxis,
    PlatformBoundarySnapshot,
    QuasiPlatformStateBoundaryViolation,
    assert_quasi_platform_state_intact,
    build_platform_boundary_snapshot,
    get_platform_boundary_axes,
    get_system_definition,
)


# ===========================================================================
# 1–3: Authority and policy sentinels
# ===========================================================================

def test_authority_sentinel_is_non_empty_and_contains_keywords() -> None:
    assert BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY
    assert "AUTHORITY" in BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY
    assert "bounded" in BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY.lower()


def test_pr14v2_sentinel_is_non_empty_and_contains_pr14v2() -> None:
    assert BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL
    assert "14v2" in BOUNDED_SUBJECT_PLATFORM_BOUNDARY_PR14V2_SENTINEL.lower()


def test_quasi_platform_state_definition_contains_required_vocabulary() -> None:
    d = QUASI_PLATFORM_STATE_DEFINITION
    assert d
    assert "canonical" in d.lower()
    assert "bounded" in d.lower()
    assert "authority" in d.lower()


def test_all_five_policy_sentinels_are_non_empty() -> None:
    sentinels = [
        CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY,
        BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY,
        PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY,
        OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY,
        OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY,
    ]
    for s in sentinels:
        assert s, f"sentinel is empty: {s!r}"


# ===========================================================================
# 4: PlatformBoundaryAxis enum
# ===========================================================================

def test_platform_boundary_axis_has_all_five_values() -> None:
    values = {a.value for a in PlatformBoundaryAxis}
    assert "canonical_center" in values
    assert "bounded_subject" in values
    assert "participant_governance" in values
    assert "observability_evidence" in values
    assert "outward_consumption" in values
    assert len(values) == 5


# ===========================================================================
# 5: BoundaryAxisDescriptor
# ===========================================================================

def test_boundary_axis_descriptor_to_dict_has_all_required_keys() -> None:
    axes = get_platform_boundary_axes()
    assert axes
    d = axes[0].to_dict()
    required_keys = {
        "axis",
        "description",
        "policy_sentinel",
        "code_evidence",
        "android_v2_consistent",
        "no_parallel_authority",
        "notes",
    }
    assert required_keys <= set(d.keys())


# ===========================================================================
# 6: PlatformBoundarySnapshot
# ===========================================================================

def test_platform_boundary_snapshot_to_dict_has_all_required_keys() -> None:
    snap = build_platform_boundary_snapshot()
    d = snap.to_dict()
    required_keys = {
        "snapshot_id",
        "timestamp",
        "system_definition",
        "authority_sentinel",
        "pr14v2_sentinel",
        "axes",
        "quasi_platform_state_intact",
        "violations",
        "axis_count",
    }
    assert required_keys <= set(d.keys())


# ===========================================================================
# 7: Registry has exactly five axes
# ===========================================================================

def test_platform_boundary_axis_registry_has_exactly_five_entries() -> None:
    assert len(PLATFORM_BOUNDARY_AXIS_REGISTRY) == 5


def test_registry_covers_all_five_axis_values() -> None:
    axis_values = {a.axis for a in PLATFORM_BOUNDARY_AXIS_REGISTRY}
    expected = set(PlatformBoundaryAxis)
    assert axis_values == expected


# ===========================================================================
# 8–10: Per-axis invariants
# ===========================================================================

def test_every_axis_has_non_empty_code_evidence() -> None:
    for axis in PLATFORM_BOUNDARY_AXIS_REGISTRY:
        assert axis.code_evidence, (
            f"axis={axis.axis.value} has empty code_evidence"
        )


def test_every_axis_is_android_v2_consistent() -> None:
    for axis in PLATFORM_BOUNDARY_AXIS_REGISTRY:
        assert axis.android_v2_consistent is True, (
            f"axis={axis.axis.value} has android_v2_consistent=False"
        )


def test_every_axis_has_no_parallel_authority() -> None:
    for axis in PLATFORM_BOUNDARY_AXIS_REGISTRY:
        assert axis.no_parallel_authority is True, (
            f"axis={axis.axis.value} has no_parallel_authority=False"
        )


# ===========================================================================
# 11–13: build_platform_boundary_snapshot / assert_quasi_platform_state_intact
# ===========================================================================

def test_build_platform_boundary_snapshot_returns_intact() -> None:
    snap = build_platform_boundary_snapshot()
    assert snap.quasi_platform_state_intact is True
    assert snap.violations == []


def test_build_platform_boundary_snapshot_has_five_axes() -> None:
    snap = build_platform_boundary_snapshot()
    assert len(snap.axes) == 5


def test_assert_quasi_platform_state_intact_does_not_raise() -> None:
    # Should not raise — all axes are intact in the registry
    assert_quasi_platform_state_intact()


# ===========================================================================
# 14: QuasiPlatformStateBoundaryViolation is raised on misconfigured axis
# ===========================================================================

def test_violation_raised_when_android_v2_inconsistent() -> None:
    from core.bounded_subject_platform_boundary import (
        _evaluate_quasi_platform_state,
    )
    bad_axis = BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.CANONICAL_CENTER,
        description="test",
        policy_sentinel="test policy",
        code_evidence=("some.module",),
        android_v2_consistent=False,  # bad
        no_parallel_authority=True,
    )
    intact, violations = _evaluate_quasi_platform_state([bad_axis])
    assert not intact
    assert violations


def test_violation_raised_when_parallel_authority_introduced() -> None:
    from core.bounded_subject_platform_boundary import (
        _evaluate_quasi_platform_state,
    )
    bad_axis = BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.BOUNDED_SUBJECT,
        description="test",
        policy_sentinel="test policy",
        code_evidence=("some.module",),
        android_v2_consistent=True,
        no_parallel_authority=False,  # bad
    )
    intact, violations = _evaluate_quasi_platform_state([bad_axis])
    assert not intact
    assert violations


def test_quasi_platform_state_boundary_violation_carries_snapshot() -> None:
    from core.bounded_subject_platform_boundary import (
        _evaluate_quasi_platform_state,
    )
    bad_axis = BoundaryAxisDescriptor(
        axis=PlatformBoundaryAxis.OUTWARD_CONSUMPTION,
        description="test",
        policy_sentinel="test policy",
        code_evidence=("some.module",),
        android_v2_consistent=False,
        no_parallel_authority=True,
    )
    intact, violations = _evaluate_quasi_platform_state([bad_axis])
    snap = PlatformBoundarySnapshot(
        axes=[bad_axis],
        quasi_platform_state_intact=intact,
        violations=violations,
    )
    exc = QuasiPlatformStateBoundaryViolation("test violation", snapshot=snap)
    assert exc.snapshot is not None
    assert not exc.snapshot.quasi_platform_state_intact


# ===========================================================================
# 15–16: Helper functions
# ===========================================================================

def test_get_platform_boundary_axes_returns_five_axes() -> None:
    axes = get_platform_boundary_axes()
    assert len(axes) == 5
    assert all(isinstance(a, BoundaryAxisDescriptor) for a in axes)


def test_get_system_definition_matches_sentinel() -> None:
    defn = get_system_definition()
    assert defn == QUASI_PLATFORM_STATE_DEFINITION


# ===========================================================================
# 17–18: Serialisation
# ===========================================================================

def test_snapshot_to_json_is_valid_json_with_required_keys() -> None:
    snap = build_platform_boundary_snapshot()
    raw = snap.to_json()
    data = json.loads(raw)
    required_keys = {
        "snapshot_id",
        "timestamp",
        "axes",
        "quasi_platform_state_intact",
        "violations",
        "axis_count",
    }
    assert required_keys <= set(data.keys())


def test_snapshot_axis_count_equals_five() -> None:
    snap = build_platform_boundary_snapshot()
    d = snap.to_dict()
    assert d["axis_count"] == 5


# ===========================================================================
# 19–23: Per-axis code evidence references
# ===========================================================================

def _axis_by(axis_type: PlatformBoundaryAxis) -> BoundaryAxisDescriptor:
    for a in PLATFORM_BOUNDARY_AXIS_REGISTRY:
        if a.axis == axis_type:
            return a
    raise KeyError(axis_type)


def test_canonical_center_axis_references_center_authority_boundary() -> None:
    axis = _axis_by(PlatformBoundaryAxis.CANONICAL_CENTER)
    evidence_str = " ".join(axis.code_evidence)
    assert "center_authority_boundary" in evidence_str


def test_bounded_subject_axis_references_distributed_subject_contract() -> None:
    axis = _axis_by(PlatformBoundaryAxis.BOUNDED_SUBJECT)
    evidence_str = " ".join(axis.code_evidence)
    assert "distributed_subject_contract_v1" in evidence_str


def test_participant_governance_axis_references_operator_action_governance() -> None:
    axis = _axis_by(PlatformBoundaryAxis.PARTICIPANT_GOVERNANCE)
    evidence_str = " ".join(axis.code_evidence)
    assert "operator_action_governance" in evidence_str


def test_observability_axis_references_cross_subject_observability_contract() -> None:
    axis = _axis_by(PlatformBoundaryAxis.OBSERVABILITY_EVIDENCE)
    evidence_str = " ".join(axis.code_evidence)
    assert "cross_subject_observability_contract" in evidence_str


def test_outward_consumption_axis_references_final_acceptance_surface_boundary() -> None:
    axis = _axis_by(PlatformBoundaryAxis.OUTWARD_CONSUMPTION)
    evidence_str = " ".join(axis.code_evidence)
    assert "final_acceptance_surface_boundary" in evidence_str


# ===========================================================================
# 24: No duplicate axis values
# ===========================================================================

def test_no_duplicate_axis_values_in_registry() -> None:
    seen = set()
    for a in PLATFORM_BOUNDARY_AXIS_REGISTRY:
        assert a.axis not in seen, (
            f"Duplicate axis value in registry: {a.axis.value}"
        )
        seen.add(a.axis)


# ===========================================================================
# 25–29: Policy sentinel vocabulary
# ===========================================================================

def test_canonical_center_policy_references_canonical_center() -> None:
    p = CANONICAL_CENTER_BOUNDARY_IS_SOLE_AUTHORITY_POLICY
    assert "canonical" in p.lower()
    assert "center" in p.lower()


def test_bounded_subject_policy_references_global_truth_finalization() -> None:
    p = BOUNDED_SUBJECT_HAS_NO_GLOBAL_TRUTH_FINALIZATION_POLICY
    assert "global" in p.lower()
    assert "truth" in p.lower()


def test_participant_governance_policy_references_participant_lifecycle() -> None:
    p = PARTICIPANT_GOVERNANCE_IS_CENTER_ONLY_POLICY
    assert "participant" in p.lower()
    assert "lifecycle" in p.lower()


def test_observability_policy_references_parallel_and_authority() -> None:
    p = OBSERVABILITY_BOUNDARY_IS_NOT_PARALLEL_AUTHORITY_POLICY
    assert "parallel" in p.lower()
    assert "authority" in p.lower()


def test_outward_consumption_policy_references_consumption() -> None:
    p = OUTWARD_CONSUMPTION_BOUNDARY_IS_CONSUMPTION_ONLY_POLICY
    assert "consumption" in p.lower()


# ===========================================================================
# 30: Authority sentinel references quasi-platform state concepts
# ===========================================================================

def test_authority_sentinel_references_canonical_governance_concepts() -> None:
    s = BOUNDED_SUBJECT_PLATFORM_BOUNDARY_AUTHORITY
    assert "canonical" in s.lower()
    assert "bounded" in s.lower()
