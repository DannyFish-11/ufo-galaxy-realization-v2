#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_cross_repo_contract_finalization.py
===================================================
PR-7 (Cross-Repo Compatibility Retirement and Contract Finalization):
validation test suite.

Coverage areas
--------------
A.  Module importable; authority and PR-7 sentinel are non-empty strings
    with expected tokens.
B.  All five policy sentinels are non-empty strings with expected keywords.
C.  ContractBoundaryKind enum has all expected members.
D.  FinalizationStatus enum has STABLE, HARDENING, AMBIGUOUS, LEGACY_ONLY.
E.  DriftVectorKind enum has all expected members.
F.  FinalizationGateVerdict enum has pass_, warn, fail.
G.  get_contract_boundary_catalog() returns a non-empty list of
    ContractBoundaryRecord instances.
H.  Every ContractBoundaryRecord has non-empty boundary_id, center_authority,
    android_counterpart, description, addressing_strategy.
I.  No two boundaries share the same boundary_id (uniqueness).
J.  get_drift_vector_catalog() returns a non-empty list of DriftVectorRecord.
K.  Every DriftVectorRecord has non-empty vector_id, v2_surface,
    android_surface, description, addressing_strategy.
L.  No two drift vectors share the same vector_id (uniqueness).
M.  The catalog contains all eight expected boundary IDs:
    CONTRACT-001 through CONTRACT-008.
N.  The drift vector catalog contains all six expected vector IDs:
    DRIFT-001 through DRIFT-006.
O.  get_boundaries_by_status(STABLE) returns only STABLE records.
P.  get_boundaries_by_status(LEGACY_ONLY) returns only LEGACY_ONLY records.
Q.  get_ambiguous_boundaries() returns only AMBIGUOUS records.
R.  get_drift_vectors_by_kind(enum_vocabulary) returns only enum_vocabulary
    records, and the result is non-empty.
S.  run_contract_boundary_gate() returns a FinalizationGateResult with
    correct gate_id and non-None verdict.
T.  run_contract_boundary_gate() for a kind with no AMBIGUOUS boundaries
    returns pass_ or warn verdict (not fail).
U.  run_drift_vector_gate() returns a FinalizationGateResult with
    gate_id == 'aggregate_drift_vector'.
V.  run_all_finalization_gates() returns a list with length equal to
    len(ContractBoundaryKind) + 1 (one per kind plus the drift vector gate).
W.  build_finalization_snapshot() returns a ContractFinalizationSnapshot.
X.  Snapshot boundary counts are internally consistent
    (total == stable + hardening + ambiguous + legacy_only).
Y.  Snapshot drift vector counts are internally consistent
    (total == addressed + unaddressed).
Z.  Snapshot policy_sentinels list contains five sentinel strings.
AA. ContractFinalizationSnapshot.to_dict() includes expected top-level keys.
AB. ContractBoundaryRecord.to_dict() includes all required keys.
AC. DriftVectorRecord.to_dict() includes all required keys.
AD. FinalizationGateResult.to_dict() includes all required keys.
AE. is_contract_finalization_complete() returns True when no AMBIGUOUS
    boundaries and no HIGH-severity unaddressed drift vectors exist.
AF. The snapshot finalization_complete field agrees with
    is_contract_finalization_complete().
AG. All LEGACY_ONLY boundaries have a non-empty retirement_condition.
AH. All addressed drift vectors have a non-empty addressing_evidence.
AI. No boundary has FinalizationStatus.AMBIGUOUS in the catalog
    (post-PR-7 the catalog should not contain AMBIGUOUS entries).
AJ. Snapshot gate_results list is non-empty and each entry contains
    'gate_id' and 'verdict' keys.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.cross_repo_contract_finalization import (
    ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY,
    CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY,
    CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY,
    CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL,
    DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY,
    FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY,
    RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY,
    ContractBoundaryKind,
    ContractBoundaryRecord,
    ContractFinalizationSnapshot,
    DriftVectorKind,
    DriftVectorRecord,
    FinalizationGateResult,
    FinalizationGateVerdict,
    FinalizationStatus,
    build_finalization_snapshot,
    get_ambiguous_boundaries,
    get_boundaries_by_status,
    get_contract_boundary_catalog,
    get_drift_vector_catalog,
    get_drift_vectors_by_kind,
    is_contract_finalization_complete,
    run_all_finalization_gates,
    run_contract_boundary_gate,
    run_drift_vector_gate,
)


# ---------------------------------------------------------------------------
# A. Module importable; authority and sentinel non-empty
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty() -> None:
    assert isinstance(CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY, str)
    assert len(CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY) > 0


def test_authority_sentinel_has_expected_tokens() -> None:
    assert CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY.startswith(
        "CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY::"
    )
    assert "core.cross_repo_contract_finalization" in CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY
    assert "PR-7" in CROSS_REPO_CONTRACT_FINALIZATION_IS_AUTHORITY


def test_pr7_sentinel_non_empty() -> None:
    assert isinstance(CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL, str)
    assert len(CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL) > 0


def test_pr7_sentinel_has_expected_tokens() -> None:
    assert CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL.startswith(
        "CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL::"
    )
    assert "PR7" in CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL
    assert "cross-repo-contract-finalization-v1" in CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL
    assert "core.cross_repo_contract_finalization" in CROSS_REPO_CONTRACT_FINALIZATION_PR7_SENTINEL


# ---------------------------------------------------------------------------
# B. Policy sentinels
# ---------------------------------------------------------------------------


def test_policy_sentinels_are_non_empty_strings() -> None:
    for sentinel in [
        CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY,
        RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY,
        ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY,
        DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY,
        FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY,
    ]:
        assert isinstance(sentinel, str)
        assert len(sentinel) > 10, f"Policy sentinel too short: {sentinel!r}"


def test_policy_sentinels_have_policy_prefix() -> None:
    for sentinel in [
        CONTRACT_BOUNDARIES_MUST_BE_EXPLICIT_POLICY,
        RESIDUAL_COMPAT_PATHS_MUST_BE_FENCED_OR_RETIRED_POLICY,
        ANDROID_CONTRACT_EXPECTATIONS_MUST_BE_CENTER_AUTHORITATIVE_POLICY,
        DRIFT_VECTORS_MUST_BE_CATALOGUED_AND_ADDRESSED_POLICY,
        FINALIZATION_PASS_MUST_SHRINK_AMBIGUITY_POLICY,
    ]:
        assert sentinel.startswith("POLICY::"), (
            f"Sentinel does not start with 'POLICY::': {sentinel!r}"
        )


# ---------------------------------------------------------------------------
# C. ContractBoundaryKind enum completeness
# ---------------------------------------------------------------------------


def test_contract_boundary_kind_members() -> None:
    expected = {
        "task_dispatch_ingress",
        "readiness_participation",
        "session_transport",
        "projection_consumption",
        "capability_descriptor",
        "result_surface",
        "rest_api",
        "websocket_protocol",
        "aggregate",
    }
    actual = {m.value for m in ContractBoundaryKind}
    assert expected == actual


# ---------------------------------------------------------------------------
# D. FinalizationStatus enum completeness
# ---------------------------------------------------------------------------


def test_finalization_status_members() -> None:
    expected = {"stable", "hardening", "ambiguous", "legacy_only"}
    actual = {m.value for m in FinalizationStatus}
    assert expected == actual


# ---------------------------------------------------------------------------
# E. DriftVectorKind enum completeness
# ---------------------------------------------------------------------------


def test_drift_vector_kind_members() -> None:
    expected = {
        "enum_vocabulary",
        "field_naming",
        "lifecycle_semantics",
        "authority_ambiguity",
        "contract_gap",
        "transitional_expansion",
    }
    actual = {m.value for m in DriftVectorKind}
    assert expected == actual


# ---------------------------------------------------------------------------
# F. FinalizationGateVerdict enum completeness
# ---------------------------------------------------------------------------


def test_finalization_gate_verdict_members() -> None:
    assert FinalizationGateVerdict.pass_.value == "pass"
    assert FinalizationGateVerdict.warn.value == "warn"
    assert FinalizationGateVerdict.fail.value == "fail"
    assert len(list(FinalizationGateVerdict)) == 3


# ---------------------------------------------------------------------------
# G. get_contract_boundary_catalog() — non-empty list of ContractBoundaryRecord
# ---------------------------------------------------------------------------


def test_contract_boundary_catalog_non_empty() -> None:
    catalog = get_contract_boundary_catalog()
    assert isinstance(catalog, list)
    assert len(catalog) > 0


def test_contract_boundary_catalog_all_records_are_correct_type() -> None:
    for record in get_contract_boundary_catalog():
        assert isinstance(record, ContractBoundaryRecord)


# ---------------------------------------------------------------------------
# H. Every ContractBoundaryRecord has required non-empty fields
# ---------------------------------------------------------------------------


def test_every_boundary_has_required_non_empty_fields() -> None:
    for record in get_contract_boundary_catalog():
        assert record.boundary_id, f"boundary_id empty for {record}"
        assert record.center_authority, f"center_authority empty for {record.boundary_id}"
        assert record.android_counterpart, f"android_counterpart empty for {record.boundary_id}"
        assert record.description, f"description empty for {record.boundary_id}"
        assert record.addressing_strategy, f"addressing_strategy empty for {record.boundary_id}"
        assert isinstance(record.kind, ContractBoundaryKind)
        assert isinstance(record.status, FinalizationStatus)


# ---------------------------------------------------------------------------
# I. Boundary ID uniqueness
# ---------------------------------------------------------------------------


def test_boundary_ids_are_unique() -> None:
    ids = [r.boundary_id for r in get_contract_boundary_catalog()]
    assert len(ids) == len(set(ids)), "Duplicate boundary_id values found"


# ---------------------------------------------------------------------------
# J. get_drift_vector_catalog() — non-empty list
# ---------------------------------------------------------------------------


def test_drift_vector_catalog_non_empty() -> None:
    catalog = get_drift_vector_catalog()
    assert isinstance(catalog, list)
    assert len(catalog) > 0


def test_drift_vector_catalog_all_records_are_correct_type() -> None:
    for record in get_drift_vector_catalog():
        assert isinstance(record, DriftVectorRecord)


# ---------------------------------------------------------------------------
# K. Every DriftVectorRecord has required non-empty fields
# ---------------------------------------------------------------------------


def test_every_drift_vector_has_required_non_empty_fields() -> None:
    for record in get_drift_vector_catalog():
        assert record.vector_id, f"vector_id empty for {record}"
        assert record.v2_surface, f"v2_surface empty for {record.vector_id}"
        assert record.android_surface, f"android_surface empty for {record.vector_id}"
        assert record.description, f"description empty for {record.vector_id}"
        assert record.addressing_strategy, f"addressing_strategy empty for {record.vector_id}"
        assert isinstance(record.kind, DriftVectorKind)
        assert record.severity in {"HIGH", "MEDIUM", "LOW"}


# ---------------------------------------------------------------------------
# L. Drift vector ID uniqueness
# ---------------------------------------------------------------------------


def test_drift_vector_ids_are_unique() -> None:
    ids = [v.vector_id for v in get_drift_vector_catalog()]
    assert len(ids) == len(set(ids)), "Duplicate vector_id values found"


# ---------------------------------------------------------------------------
# M. Expected boundary IDs present
# ---------------------------------------------------------------------------


def test_expected_boundary_ids_present() -> None:
    expected_ids = {
        "CONTRACT-001",
        "CONTRACT-002",
        "CONTRACT-003",
        "CONTRACT-004",
        "CONTRACT-005",
        "CONTRACT-006",
        "CONTRACT-007",
        "CONTRACT-008",
    }
    actual_ids = {r.boundary_id for r in get_contract_boundary_catalog()}
    for expected in expected_ids:
        assert expected in actual_ids, f"Missing boundary_id: {expected}"


# ---------------------------------------------------------------------------
# N. Expected drift vector IDs present
# ---------------------------------------------------------------------------


def test_expected_drift_vector_ids_present() -> None:
    expected_ids = {
        "DRIFT-001",
        "DRIFT-002",
        "DRIFT-003",
        "DRIFT-004",
        "DRIFT-005",
        "DRIFT-006",
    }
    actual_ids = {v.vector_id for v in get_drift_vector_catalog()}
    for expected in expected_ids:
        assert expected in actual_ids, f"Missing vector_id: {expected}"


# ---------------------------------------------------------------------------
# O. get_boundaries_by_status(STABLE) returns only STABLE records
# ---------------------------------------------------------------------------


def test_boundaries_by_status_stable_returns_only_stable() -> None:
    stable = get_boundaries_by_status(FinalizationStatus.STABLE)
    for r in stable:
        assert r.status == FinalizationStatus.STABLE


# ---------------------------------------------------------------------------
# P. get_boundaries_by_status(LEGACY_ONLY) returns only LEGACY_ONLY records
# ---------------------------------------------------------------------------


def test_boundaries_by_status_legacy_only_returns_only_legacy_only() -> None:
    legacy = get_boundaries_by_status(FinalizationStatus.LEGACY_ONLY)
    for r in legacy:
        assert r.status == FinalizationStatus.LEGACY_ONLY


# ---------------------------------------------------------------------------
# Q. get_ambiguous_boundaries() returns only AMBIGUOUS records
# ---------------------------------------------------------------------------


def test_get_ambiguous_boundaries_returns_only_ambiguous() -> None:
    ambiguous = get_ambiguous_boundaries()
    for r in ambiguous:
        assert r.status == FinalizationStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# R. get_drift_vectors_by_kind(enum_vocabulary) — non-empty, correct kind
# ---------------------------------------------------------------------------


def test_drift_vectors_by_kind_enum_vocabulary() -> None:
    results = get_drift_vectors_by_kind(DriftVectorKind.enum_vocabulary)
    assert len(results) > 0, "Expected at least one enum_vocabulary drift vector"
    for v in results:
        assert v.kind == DriftVectorKind.enum_vocabulary


# ---------------------------------------------------------------------------
# S. run_contract_boundary_gate() — returns FinalizationGateResult with
#    correct gate_id and non-None verdict
# ---------------------------------------------------------------------------


def test_run_contract_boundary_gate_returns_gate_result() -> None:
    result = run_contract_boundary_gate(ContractBoundaryKind.task_dispatch_ingress)
    assert isinstance(result, FinalizationGateResult)
    assert result.gate_id == "contract_boundary_task_dispatch_ingress"
    assert isinstance(result.verdict, FinalizationGateVerdict)


def test_run_contract_boundary_gate_has_all_fields() -> None:
    result = run_contract_boundary_gate(ContractBoundaryKind.session_transport)
    assert isinstance(result.ambiguous_count, int)
    assert isinstance(result.legacy_only_count, int)
    assert isinstance(result.unaddressed_drift_count, int)
    assert isinstance(result.details, str)
    assert isinstance(result.issues, list)


# ---------------------------------------------------------------------------
# T. run_contract_boundary_gate() with no AMBIGUOUS boundaries — not fail
# ---------------------------------------------------------------------------


def test_run_contract_boundary_gate_no_ambiguous_not_fail() -> None:
    # Find a kind that has no AMBIGUOUS boundaries in the catalog
    for kind in ContractBoundaryKind:
        ambiguous_for_kind = [
            r for r in get_contract_boundary_catalog()
            if r.kind == kind and r.status == FinalizationStatus.AMBIGUOUS
        ]
        if not ambiguous_for_kind:
            result = run_contract_boundary_gate(kind)
            # Without ambiguous boundaries, gate should be pass_ or warn, not fail
            # (unless there are unaddressed drift vectors matching this kind)
            if result.unaddressed_drift_count == 0:
                assert result.verdict != FinalizationGateVerdict.fail, (
                    f"Expected non-fail verdict for kind={kind.value} "
                    f"with no AMBIGUOUS boundaries and no unaddressed drift"
                )
            break


# ---------------------------------------------------------------------------
# U. run_drift_vector_gate() — gate_id == 'aggregate_drift_vector'
# ---------------------------------------------------------------------------


def test_run_drift_vector_gate_returns_correct_gate_id() -> None:
    result = run_drift_vector_gate()
    assert isinstance(result, FinalizationGateResult)
    assert result.gate_id == "aggregate_drift_vector"
    assert result.kind == ContractBoundaryKind.aggregate


def test_run_drift_vector_gate_has_valid_verdict() -> None:
    result = run_drift_vector_gate()
    assert isinstance(result.verdict, FinalizationGateVerdict)


# ---------------------------------------------------------------------------
# V. run_all_finalization_gates() — correct count
# ---------------------------------------------------------------------------


def test_run_all_finalization_gates_returns_correct_count() -> None:
    results = run_all_finalization_gates()
    # One per ContractBoundaryKind (excluding 'aggregate' sentinel) + 1 drift vector gate
    non_aggregate_kinds = [k for k in ContractBoundaryKind if k is not ContractBoundaryKind.aggregate]
    expected_count = len(non_aggregate_kinds) + 1
    assert len(results) == expected_count


def test_run_all_finalization_gates_all_are_gate_results() -> None:
    for result in run_all_finalization_gates():
        assert isinstance(result, FinalizationGateResult)


# ---------------------------------------------------------------------------
# W. build_finalization_snapshot() — returns ContractFinalizationSnapshot
# ---------------------------------------------------------------------------


def test_build_finalization_snapshot_returns_snapshot() -> None:
    snapshot = build_finalization_snapshot()
    assert isinstance(snapshot, ContractFinalizationSnapshot)


# ---------------------------------------------------------------------------
# X. Snapshot boundary counts are internally consistent
# ---------------------------------------------------------------------------


def test_snapshot_boundary_counts_consistent() -> None:
    snapshot = build_finalization_snapshot()
    assert (
        snapshot.total_boundaries
        == snapshot.stable_count
        + snapshot.hardening_count
        + snapshot.ambiguous_count
        + snapshot.legacy_only_count
    )


# ---------------------------------------------------------------------------
# Y. Snapshot drift vector counts are internally consistent
# ---------------------------------------------------------------------------


def test_snapshot_drift_vector_counts_consistent() -> None:
    snapshot = build_finalization_snapshot()
    assert (
        snapshot.total_drift_vectors
        == snapshot.addressed_drift_count + snapshot.unaddressed_drift_count
    )


# ---------------------------------------------------------------------------
# Z. Snapshot policy_sentinels contains five strings
# ---------------------------------------------------------------------------


def test_snapshot_policy_sentinels_count() -> None:
    snapshot = build_finalization_snapshot()
    assert len(snapshot.policy_sentinels) == 5
    for sentinel in snapshot.policy_sentinels:
        assert isinstance(sentinel, str)
        assert len(sentinel) > 0


# ---------------------------------------------------------------------------
# AA. ContractFinalizationSnapshot.to_dict() — expected top-level keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_has_expected_keys() -> None:
    snapshot = build_finalization_snapshot()
    d = snapshot.to_dict()
    expected_keys = {
        "total_boundaries",
        "by_status",
        "drift_vectors",
        "finalization_complete",
        "generated_at",
        "policy_sentinels",
        "gate_results",
        "boundary_summaries",
        "drift_vector_summaries",
    }
    for key in expected_keys:
        assert key in d, f"Missing key in snapshot.to_dict(): {key!r}"


def test_snapshot_to_dict_by_status_sub_keys() -> None:
    d = build_finalization_snapshot().to_dict()
    by_status = d["by_status"]
    for key in ("stable", "hardening", "ambiguous", "legacy_only"):
        assert key in by_status, f"Missing by_status key: {key!r}"


def test_snapshot_to_dict_drift_vectors_sub_keys() -> None:
    d = build_finalization_snapshot().to_dict()
    drift = d["drift_vectors"]
    for key in ("total", "addressed", "unaddressed", "high_severity_unaddressed"):
        assert key in drift, f"Missing drift_vectors key: {key!r}"


# ---------------------------------------------------------------------------
# AB. ContractBoundaryRecord.to_dict() — all required keys
# ---------------------------------------------------------------------------


def test_boundary_record_to_dict_has_required_keys() -> None:
    record = get_contract_boundary_catalog()[0]
    d = record.to_dict()
    required = {
        "boundary_id",
        "kind",
        "status",
        "center_authority",
        "android_counterpart",
        "description",
        "addressing_strategy",
        "retirement_condition",
        "invariant",
        "drift_risk",
        "notes",
    }
    for key in required:
        assert key in d, f"Missing key in ContractBoundaryRecord.to_dict(): {key!r}"


# ---------------------------------------------------------------------------
# AC. DriftVectorRecord.to_dict() — all required keys
# ---------------------------------------------------------------------------


def test_drift_vector_record_to_dict_has_required_keys() -> None:
    record = get_drift_vector_catalog()[0]
    d = record.to_dict()
    required = {
        "vector_id",
        "kind",
        "severity",
        "v2_surface",
        "android_surface",
        "description",
        "addressing_strategy",
        "addressed",
        "addressing_evidence",
        "notes",
    }
    for key in required:
        assert key in d, f"Missing key in DriftVectorRecord.to_dict(): {key!r}"


# ---------------------------------------------------------------------------
# AD. FinalizationGateResult.to_dict() — all required keys
# ---------------------------------------------------------------------------


def test_finalization_gate_result_to_dict_has_required_keys() -> None:
    result = run_contract_boundary_gate(ContractBoundaryKind.rest_api)
    d = result.to_dict()
    required = {
        "gate_id",
        "kind",
        "verdict",
        "ambiguous_count",
        "legacy_only_count",
        "unaddressed_drift_count",
        "details",
        "issues",
        "checked_at",
    }
    for key in required:
        assert key in d, f"Missing key in FinalizationGateResult.to_dict(): {key!r}"


# ---------------------------------------------------------------------------
# AE. is_contract_finalization_complete() — True when no blocking issues
# ---------------------------------------------------------------------------


def test_is_contract_finalization_complete_returns_bool() -> None:
    result = is_contract_finalization_complete()
    assert isinstance(result, bool)


def test_is_contract_finalization_complete_logic() -> None:
    # The result must agree with the computed conditions
    ambiguous = get_ambiguous_boundaries()
    high_unaddressed = [
        v for v in get_drift_vector_catalog()
        if not v.addressed and v.severity == "HIGH"
    ]
    expected = len(ambiguous) == 0 and len(high_unaddressed) == 0
    assert is_contract_finalization_complete() == expected


# ---------------------------------------------------------------------------
# AF. Snapshot finalization_complete agrees with is_contract_finalization_complete()
# ---------------------------------------------------------------------------


def test_snapshot_finalization_complete_agrees_with_gate() -> None:
    snapshot = build_finalization_snapshot()
    assert snapshot.finalization_complete == is_contract_finalization_complete()


# ---------------------------------------------------------------------------
# AG. All LEGACY_ONLY boundaries have a non-empty retirement_condition
# ---------------------------------------------------------------------------


def test_legacy_only_boundaries_have_retirement_condition() -> None:
    for record in get_boundaries_by_status(FinalizationStatus.LEGACY_ONLY):
        assert record.retirement_condition, (
            f"LEGACY_ONLY boundary {record.boundary_id} has empty retirement_condition"
        )


# ---------------------------------------------------------------------------
# AH. All addressed drift vectors have non-empty addressing_evidence
# ---------------------------------------------------------------------------


def test_addressed_drift_vectors_have_evidence() -> None:
    for vector in get_drift_vector_catalog():
        if vector.addressed:
            assert vector.addressing_evidence, (
                f"Addressed drift vector {vector.vector_id} has empty addressing_evidence"
            )


# ---------------------------------------------------------------------------
# AI. No AMBIGUOUS boundaries in the catalog (post-PR-7)
# ---------------------------------------------------------------------------


def test_no_ambiguous_boundaries_in_catalog() -> None:
    """After PR-7 finalization, the catalog must not contain AMBIGUOUS entries."""
    ambiguous = get_ambiguous_boundaries()
    assert len(ambiguous) == 0, (
        f"Found AMBIGUOUS boundaries in catalog after PR-7: "
        f"{[r.boundary_id for r in ambiguous]}"
    )


# ---------------------------------------------------------------------------
# AJ. Snapshot gate_results non-empty; each entry has 'gate_id' and 'verdict'
# ---------------------------------------------------------------------------


def test_snapshot_gate_results_non_empty() -> None:
    snapshot = build_finalization_snapshot()
    assert len(snapshot.gate_results) > 0


def test_snapshot_gate_results_have_required_keys() -> None:
    snapshot = build_finalization_snapshot()
    for gate_result in snapshot.gate_results:
        assert "gate_id" in gate_result, "Missing 'gate_id' in gate_result"
        assert "verdict" in gate_result, "Missing 'verdict' in gate_result"


# ---------------------------------------------------------------------------
# Additional: specific boundary attributes
# ---------------------------------------------------------------------------


def test_contract001_is_task_dispatch_ingress_stable() -> None:
    """CONTRACT-001 must be STABLE task_dispatch_ingress."""
    boundaries = {r.boundary_id: r for r in get_contract_boundary_catalog()}
    record = boundaries["CONTRACT-001"]
    assert record.kind == ContractBoundaryKind.task_dispatch_ingress
    assert record.status == FinalizationStatus.STABLE


def test_contract007_is_legacy_only_rest_api() -> None:
    """CONTRACT-007 (REST compat aliases) must be LEGACY_ONLY rest_api."""
    boundaries = {r.boundary_id: r for r in get_contract_boundary_catalog()}
    record = boundaries["CONTRACT-007"]
    assert record.kind == ContractBoundaryKind.rest_api
    assert record.status == FinalizationStatus.LEGACY_ONLY


def test_contract008_is_legacy_only_websocket_protocol() -> None:
    """CONTRACT-008 (/ws/ufo3 legacy path) must be LEGACY_ONLY websocket_protocol."""
    boundaries = {r.boundary_id: r for r in get_contract_boundary_catalog()}
    record = boundaries["CONTRACT-008"]
    assert record.kind == ContractBoundaryKind.websocket_protocol
    assert record.status == FinalizationStatus.LEGACY_ONLY


def test_drift001_is_addressed() -> None:
    """DRIFT-001 (timeout/timed_out variant) must be addressed."""
    vectors = {v.vector_id: v for v in get_drift_vector_catalog()}
    v = vectors["DRIFT-001"]
    assert v.addressed is True
    assert v.kind == DriftVectorKind.enum_vocabulary


def test_drift_vectors_no_high_severity_unaddressed() -> None:
    """No HIGH-severity drift vector should remain unaddressed after PR-7."""
    high_unaddressed = [
        v for v in get_drift_vector_catalog()
        if v.severity == "HIGH" and not v.addressed
    ]
    assert len(high_unaddressed) == 0, (
        f"Found HIGH-severity unaddressed drift vectors: "
        f"{[v.vector_id for v in high_unaddressed]}"
    )


def test_boundary_counts_cover_all_kinds() -> None:
    """Each non-aggregate ContractBoundaryKind must have at least one boundary in the catalog."""
    catalog = get_contract_boundary_catalog()
    kinds_in_catalog = {r.kind for r in catalog}
    for kind in ContractBoundaryKind:
        if kind is ContractBoundaryKind.aggregate:
            continue  # aggregate is a sentinel kind used only for the drift gate
        assert kind in kinds_in_catalog, (
            f"No contract boundary record for kind: {kind.value}"
        )


def test_all_gate_ids_are_unique() -> None:
    """Gate IDs returned by run_all_finalization_gates() must be unique."""
    results = run_all_finalization_gates()
    gate_ids = [r.gate_id for r in results]
    assert len(gate_ids) == len(set(gate_ids)), "Duplicate gate IDs found"


def test_snapshot_boundary_summaries_count_matches_catalog() -> None:
    """Snapshot boundary_summaries count must match catalog length."""
    snapshot = build_finalization_snapshot()
    catalog = get_contract_boundary_catalog()
    assert len(snapshot.boundary_summaries) == len(catalog)


def test_snapshot_drift_vector_summaries_count_matches_catalog() -> None:
    """Snapshot drift_vector_summaries count must match drift vector catalog."""
    snapshot = build_finalization_snapshot()
    catalog = get_drift_vector_catalog()
    assert len(snapshot.drift_vector_summaries) == len(catalog)
