#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_runtime_invariant_enforcement.py
================================================
PR-8 (Cross-Repo Runtime Validation, Invariant Enforcement, and Acceptance
Closure): acceptance-oriented test suite.

Coverage areas
--------------
A.  Module importable; authority and PR-8 sentinel are non-empty strings
    with expected tokens.
B.  All five policy sentinels are non-empty strings with expected keywords.
C.  InvariantDomain enum has all expected members.
D.  InvariantSeverity enum has CRITICAL, HIGH, MEDIUM, LOW.
E.  InvariantStatus enum has ENFORCED, PARTIALLY_ENFORCED, DOCUMENTED_ONLY,
    REGRESSION_RISK.
F.  ValidationGateVerdict enum has pass_, warn, fail.
G.  get_invariant_registry() returns a non-empty list of RuntimeInvariantRecord.
H.  Every RuntimeInvariantRecord has non-empty invariant_id, description,
    enforcement_mechanism, prior_pr_reference.
I.  No two invariants share the same invariant_id (uniqueness).
J.  get_cross_repo_assumption_registry() returns a non-empty list of
    CrossRepoAssumptionRecord.
K.  Every CrossRepoAssumptionRecord has non-empty assumption_id, v2_surface,
    android_surface, description, validation_mechanism.
L.  No two assumptions share the same assumption_id (uniqueness).
M.  The registry contains all ten expected invariant IDs: INV-001–INV-010.
N.  The assumption registry contains all six expected assumption IDs:
    ASSUME-001–ASSUME-006.
O.  get_invariants_by_domain() returns only matching-domain records and
    the result is non-empty for at least one domain.
P.  get_invariants_by_severity() returns only matching-severity records
    and the result is non-empty for HIGH severity.
Q.  get_violated_invariants() returns only REGRESSION_RISK records (empty
    in clean state, consistent with is_enforcement_posture_acceptable).
R.  get_unvalidated_assumptions() returns only unvalidated records (empty
    in clean state consistent with is_enforcement_posture_acceptable).
S.  check_invariant("INV-001") returns the INV-001 record without raising.
T.  check_invariant("INV-999") returns None for unknown ID (non-strict).
U.  check_invariant("INV-999", strict=True) raises ValueError.
V.  check_cross_repo_assumption("ASSUME-001") returns the ASSUME-001 record.
W.  check_cross_repo_assumption("ASSUME-999") returns None for unknown ID.
X.  check_cross_repo_assumption("ASSUME-999", strict=True) raises ValueError.
Y.  run_invariant_gate() returns a ValidationGateResult with correct gate_id
    and non-None verdict for every InvariantDomain.
Z.  run_cross_repo_validation_gate() returns a ValidationGateResult with
    gate_id == 'aggregate_cross_repo_validation'.
AA. run_all_enforcement_gates() returns a list with length equal to
    len(InvariantDomain) + 1 (one per domain plus the aggregate gate).
AB. build_enforcement_snapshot() returns an InvariantEnforcementSnapshot.
AC. Snapshot counts are internally consistent (total == enforced +
    partially_enforced + documented_only + regression_risk).
AD. Snapshot assumption counts are internally consistent
    (total == validated + unvalidated).
AE. Snapshot policy_sentinels list contains five sentinel strings.
AF. InvariantEnforcementSnapshot.to_dict() includes all expected top-level keys.
AG. RuntimeInvariantRecord.to_dict() includes all required keys.
AH. CrossRepoAssumptionRecord.to_dict() includes all required keys.
AI. ValidationGateResult.to_dict() includes all required keys.
AJ. is_enforcement_posture_acceptable() returns True when no REGRESSION_RISK
    invariants and no unvalidated assumptions exist in the clean registry.
AK. Snapshot enforcement_posture_acceptable agrees with
    is_enforcement_posture_acceptable().
AL. Every DOCUMENTED_ONLY invariant has non-empty enforcement_mechanism
    (prescribing future enforcement, not completely absent).
AM. All invariants with acceptance_test_gap have a non-empty gap description.
AN. All assumptions that are validated have non-empty validation_evidence.
AO. run_all_enforcement_gates() — each result contains 'gate_id' and
    'verdict' keys in its to_dict() output.
AP. No invariant has InvariantStatus.REGRESSION_RISK (clean-state assertion).
AQ. Snapshot gate_results list is non-empty.
AR. INV-001 has domain == task_lifecycle and severity == HIGH.
AS. INV-004 has a non-empty violation_log_prefix containing 'INV-004'.
AT. ASSUME-001 has validated == True and non-empty validation_evidence.
AU. INV-009 has status == ENFORCED (OutwardRuntimeTruth is fully enforced).
AV. INV-010 has status == ENFORCED (source posture contract is frozen/enforced).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from core.runtime_invariant_enforcement import (
    ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY,
    CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY,
    CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY,
    HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY,
    INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY,
    RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY,
    RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL,
    CrossRepoAssumptionRecord,
    InvariantDomain,
    InvariantEnforcementSnapshot,
    InvariantSeverity,
    InvariantStatus,
    RuntimeInvariantRecord,
    ValidationGateResult,
    ValidationGateVerdict,
    build_enforcement_snapshot,
    check_cross_repo_assumption,
    check_invariant,
    get_cross_repo_assumption_registry,
    get_invariant_registry,
    get_invariants_by_domain,
    get_invariants_by_severity,
    get_unvalidated_assumptions,
    get_violated_invariants,
    is_enforcement_posture_acceptable,
    run_all_enforcement_gates,
    run_cross_repo_validation_gate,
    run_invariant_gate,
)


# ---------------------------------------------------------------------------
# A. Module importable; authority and sentinel non-empty
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty() -> None:
    assert isinstance(RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY, str)
    assert len(RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY) > 0


def test_authority_sentinel_has_expected_tokens() -> None:
    assert RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY.startswith(
        "RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY::"
    )
    assert "core.runtime_invariant_enforcement" in RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY
    assert "PR-8" in RUNTIME_INVARIANT_ENFORCEMENT_IS_AUTHORITY


def test_pr8_sentinel_non_empty() -> None:
    assert isinstance(RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL, str)
    assert len(RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL) > 0


def test_pr8_sentinel_has_expected_tokens() -> None:
    assert RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL.startswith(
        "RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL::"
    )
    assert "PR8" in RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL
    assert "runtime-invariant-enforcement-v1" in RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL
    assert "core.runtime_invariant_enforcement" in RUNTIME_INVARIANT_ENFORCEMENT_PR8_SENTINEL


# ---------------------------------------------------------------------------
# B. Policy sentinels
# ---------------------------------------------------------------------------


def test_policy_sentinels_are_non_empty_strings() -> None:
    for sentinel in [
        HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY,
        CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY,
        CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY,
        ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY,
        INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY,
    ]:
        assert isinstance(sentinel, str)
        assert len(sentinel) > 10, f"Policy sentinel too short: {sentinel!r}"


def test_policy_sentinels_have_policy_prefix() -> None:
    for sentinel in [
        HIGH_VALUE_INVARIANTS_MUST_BE_MACHINE_CHECKABLE_POLICY,
        CROSS_REPO_ASSUMPTIONS_MUST_BE_VALIDATED_AT_BOUNDARY_POLICY,
        CANONICAL_STATE_MUST_NOT_SILENTLY_DEGRADE_POLICY,
        ACCEPTANCE_COVERAGE_MUST_PROTECT_CANONICAL_MODEL_POLICY,
        INVARIANT_VIOLATIONS_MUST_BE_OBSERVABLE_POLICY,
    ]:
        assert sentinel.startswith("POLICY::"), (
            f"Sentinel does not start with 'POLICY::': {sentinel!r}"
        )


# ---------------------------------------------------------------------------
# C. InvariantDomain enum completeness
# ---------------------------------------------------------------------------


def test_invariant_domain_members() -> None:
    expected = {
        "task_lifecycle",
        "session_transport",
        "readiness_participation",
        "source_of_truth",
        "projection_truth",
        "capability_routing",
        "cross_repo_contract",
        "acceptance_coverage",
    }
    actual = {m.value for m in InvariantDomain}
    assert expected == actual


# ---------------------------------------------------------------------------
# D. InvariantSeverity enum completeness
# ---------------------------------------------------------------------------


def test_invariant_severity_members() -> None:
    expected = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    actual = {m.value for m in InvariantSeverity}
    assert expected == actual


# ---------------------------------------------------------------------------
# E. InvariantStatus enum completeness
# ---------------------------------------------------------------------------


def test_invariant_status_members() -> None:
    expected = {"enforced", "partially_enforced", "documented_only", "regression_risk"}
    actual = {m.value for m in InvariantStatus}
    assert expected == actual


# ---------------------------------------------------------------------------
# F. ValidationGateVerdict enum completeness
# ---------------------------------------------------------------------------


def test_validation_gate_verdict_members() -> None:
    assert ValidationGateVerdict.pass_.value == "pass"
    assert ValidationGateVerdict.warn.value == "warn"
    assert ValidationGateVerdict.fail.value == "fail"
    assert len(list(ValidationGateVerdict)) == 3


# ---------------------------------------------------------------------------
# G. get_invariant_registry() — non-empty list of RuntimeInvariantRecord
# ---------------------------------------------------------------------------


def test_invariant_registry_non_empty() -> None:
    registry = get_invariant_registry()
    assert isinstance(registry, list)
    assert len(registry) > 0


def test_invariant_registry_all_records_are_correct_type() -> None:
    for record in get_invariant_registry():
        assert isinstance(record, RuntimeInvariantRecord)


# ---------------------------------------------------------------------------
# H. Every RuntimeInvariantRecord has required non-empty fields
# ---------------------------------------------------------------------------


def test_every_invariant_has_required_non_empty_fields() -> None:
    for record in get_invariant_registry():
        assert record.invariant_id, f"invariant_id empty for {record}"
        assert record.description, f"description empty for {record.invariant_id}"
        assert record.enforcement_mechanism, (
            f"enforcement_mechanism empty for {record.invariant_id}"
        )
        assert record.prior_pr_reference, (
            f"prior_pr_reference empty for {record.invariant_id}"
        )
        assert isinstance(record.domain, InvariantDomain)
        assert isinstance(record.severity, InvariantSeverity)
        assert isinstance(record.status, InvariantStatus)


# ---------------------------------------------------------------------------
# I. Invariant ID uniqueness
# ---------------------------------------------------------------------------


def test_invariant_ids_are_unique() -> None:
    ids = [r.invariant_id for r in get_invariant_registry()]
    assert len(ids) == len(set(ids)), "Duplicate invariant_id values found"


# ---------------------------------------------------------------------------
# J. get_cross_repo_assumption_registry() — non-empty list
# ---------------------------------------------------------------------------


def test_cross_repo_assumption_registry_non_empty() -> None:
    registry = get_cross_repo_assumption_registry()
    assert isinstance(registry, list)
    assert len(registry) > 0


def test_cross_repo_assumption_registry_all_records_are_correct_type() -> None:
    for record in get_cross_repo_assumption_registry():
        assert isinstance(record, CrossRepoAssumptionRecord)


# ---------------------------------------------------------------------------
# K. Every CrossRepoAssumptionRecord has required non-empty fields
# ---------------------------------------------------------------------------


def test_every_assumption_has_required_non_empty_fields() -> None:
    for record in get_cross_repo_assumption_registry():
        assert record.assumption_id, f"assumption_id empty for {record}"
        assert record.v2_surface, f"v2_surface empty for {record.assumption_id}"
        assert record.android_surface, f"android_surface empty for {record.assumption_id}"
        assert record.description, f"description empty for {record.assumption_id}"
        assert record.validation_mechanism, (
            f"validation_mechanism empty for {record.assumption_id}"
        )
        assert isinstance(record.domain, InvariantDomain)


# ---------------------------------------------------------------------------
# L. Assumption ID uniqueness
# ---------------------------------------------------------------------------


def test_assumption_ids_are_unique() -> None:
    ids = [r.assumption_id for r in get_cross_repo_assumption_registry()]
    assert len(ids) == len(set(ids)), "Duplicate assumption_id values found"


# ---------------------------------------------------------------------------
# M. Registry contains all ten expected invariant IDs
# ---------------------------------------------------------------------------


def test_invariant_registry_contains_all_expected_ids() -> None:
    expected_ids = {
        "INV-001", "INV-002", "INV-003", "INV-004", "INV-005",
        "INV-006", "INV-007", "INV-008", "INV-009", "INV-010",
    }
    actual_ids = {r.invariant_id for r in get_invariant_registry()}
    missing = expected_ids - actual_ids
    assert not missing, f"Missing expected invariant IDs: {missing}"


# ---------------------------------------------------------------------------
# N. Assumption registry contains all six expected assumption IDs
# ---------------------------------------------------------------------------


def test_assumption_registry_contains_all_expected_ids() -> None:
    expected_ids = {
        "ASSUME-001", "ASSUME-002", "ASSUME-003",
        "ASSUME-004", "ASSUME-005", "ASSUME-006",
    }
    actual_ids = {r.assumption_id for r in get_cross_repo_assumption_registry()}
    missing = expected_ids - actual_ids
    assert not missing, f"Missing expected assumption IDs: {missing}"


# ---------------------------------------------------------------------------
# O. get_invariants_by_domain() — returns only matching domain records
# ---------------------------------------------------------------------------


def test_get_invariants_by_domain_returns_only_matching() -> None:
    for domain in InvariantDomain:
        results = get_invariants_by_domain(domain)
        assert isinstance(results, list)
        for r in results:
            assert r.domain == domain, (
                f"Domain mismatch: expected {domain}, got {r.domain} for {r.invariant_id}"
            )


def test_get_invariants_by_domain_non_empty_for_task_lifecycle() -> None:
    results = get_invariants_by_domain(InvariantDomain.task_lifecycle)
    assert len(results) > 0, "Expected non-empty list for task_lifecycle domain"


# ---------------------------------------------------------------------------
# P. get_invariants_by_severity() — returns only matching severity records
# ---------------------------------------------------------------------------


def test_get_invariants_by_severity_returns_only_matching() -> None:
    for severity in InvariantSeverity:
        results = get_invariants_by_severity(severity)
        for r in results:
            assert r.severity == severity


def test_get_invariants_by_severity_high_non_empty() -> None:
    results = get_invariants_by_severity(InvariantSeverity.HIGH)
    assert len(results) > 0, "Expected non-empty list for HIGH severity"


# ---------------------------------------------------------------------------
# Q. get_violated_invariants() — returns only REGRESSION_RISK records
# ---------------------------------------------------------------------------


def test_get_violated_invariants_returns_only_regression_risk() -> None:
    for record in get_violated_invariants():
        assert record.status == InvariantStatus.REGRESSION_RISK


def test_get_violated_invariants_empty_in_clean_state() -> None:
    # In the clean registry there should be no REGRESSION_RISK invariants
    violated = get_violated_invariants()
    assert violated == [], (
        f"Expected no REGRESSION_RISK invariants in clean state, found: "
        f"{[r.invariant_id for r in violated]}"
    )


# ---------------------------------------------------------------------------
# R. get_unvalidated_assumptions() — returns only unvalidated records
# ---------------------------------------------------------------------------


def test_get_unvalidated_assumptions_returns_only_unvalidated() -> None:
    for record in get_unvalidated_assumptions():
        assert not record.validated


def test_get_unvalidated_assumptions_empty_in_clean_state() -> None:
    # In the clean registry all assumptions should be validated
    unvalidated = get_unvalidated_assumptions()
    assert unvalidated == [], (
        f"Expected no unvalidated assumptions in clean state, found: "
        f"{[a.assumption_id for a in unvalidated]}"
    )


# ---------------------------------------------------------------------------
# S. check_invariant() — known ID returns record
# ---------------------------------------------------------------------------


def test_check_invariant_known_id_returns_record() -> None:
    record = check_invariant("INV-001")
    assert record is not None
    assert isinstance(record, RuntimeInvariantRecord)
    assert record.invariant_id == "INV-001"


def test_check_invariant_all_known_ids_return_records() -> None:
    for inv_record in get_invariant_registry():
        result = check_invariant(inv_record.invariant_id)
        assert result is not None
        assert result.invariant_id == inv_record.invariant_id


# ---------------------------------------------------------------------------
# T. check_invariant() — unknown ID returns None (non-strict)
# ---------------------------------------------------------------------------


def test_check_invariant_unknown_id_returns_none() -> None:
    result = check_invariant("INV-999")
    assert result is None


# ---------------------------------------------------------------------------
# U. check_invariant() — unknown ID raises ValueError in strict mode
# ---------------------------------------------------------------------------


def test_check_invariant_strict_raises_for_unknown_id() -> None:
    with pytest.raises(ValueError, match="INV-999"):
        check_invariant("INV-999", strict=True)


# ---------------------------------------------------------------------------
# V. check_cross_repo_assumption() — known ID returns record
# ---------------------------------------------------------------------------


def test_check_cross_repo_assumption_known_id_returns_record() -> None:
    record = check_cross_repo_assumption("ASSUME-001")
    assert record is not None
    assert isinstance(record, CrossRepoAssumptionRecord)
    assert record.assumption_id == "ASSUME-001"


# ---------------------------------------------------------------------------
# W. check_cross_repo_assumption() — unknown ID returns None
# ---------------------------------------------------------------------------


def test_check_cross_repo_assumption_unknown_id_returns_none() -> None:
    result = check_cross_repo_assumption("ASSUME-999")
    assert result is None


# ---------------------------------------------------------------------------
# X. check_cross_repo_assumption() — unknown ID raises ValueError in strict mode
# ---------------------------------------------------------------------------


def test_check_cross_repo_assumption_strict_raises_for_unknown() -> None:
    with pytest.raises(ValueError, match="ASSUME-999"):
        check_cross_repo_assumption("ASSUME-999", strict=True)


# ---------------------------------------------------------------------------
# Y. run_invariant_gate() — returns ValidationGateResult for each domain
# ---------------------------------------------------------------------------


def test_run_invariant_gate_returns_correct_type_for_all_domains() -> None:
    for domain in InvariantDomain:
        result = run_invariant_gate(domain)
        assert isinstance(result, ValidationGateResult)
        assert result.domain == domain
        assert result.verdict is not None
        assert isinstance(result.verdict, ValidationGateVerdict)


def test_run_invariant_gate_gate_id_matches_domain() -> None:
    for domain in InvariantDomain:
        result = run_invariant_gate(domain)
        assert f"invariant_domain_{domain.value}" == result.gate_id


# ---------------------------------------------------------------------------
# Z. run_cross_repo_validation_gate() — expected gate_id
# ---------------------------------------------------------------------------


def test_run_cross_repo_validation_gate_returns_correct_gate_id() -> None:
    result = run_cross_repo_validation_gate()
    assert isinstance(result, ValidationGateResult)
    assert result.gate_id == "aggregate_cross_repo_validation"


def test_run_cross_repo_validation_gate_verdict_non_none() -> None:
    result = run_cross_repo_validation_gate()
    assert result.verdict is not None
    assert isinstance(result.verdict, ValidationGateVerdict)


# ---------------------------------------------------------------------------
# AA. run_all_enforcement_gates() — list length
# ---------------------------------------------------------------------------


def test_run_all_enforcement_gates_length() -> None:
    results = run_all_enforcement_gates()
    expected_len = len(list(InvariantDomain)) + 1
    assert len(results) == expected_len, (
        f"Expected {expected_len} gate results, got {len(results)}"
    )


def test_run_all_enforcement_gates_all_correct_type() -> None:
    for result in run_all_enforcement_gates():
        assert isinstance(result, ValidationGateResult)


# ---------------------------------------------------------------------------
# AB. build_enforcement_snapshot() — returns InvariantEnforcementSnapshot
# ---------------------------------------------------------------------------


def test_build_enforcement_snapshot_returns_correct_type() -> None:
    snapshot = build_enforcement_snapshot()
    assert isinstance(snapshot, InvariantEnforcementSnapshot)


# ---------------------------------------------------------------------------
# AC. Snapshot invariant counts are internally consistent
# ---------------------------------------------------------------------------


def test_snapshot_invariant_counts_consistent() -> None:
    snapshot = build_enforcement_snapshot()
    total = (
        snapshot.enforced_count
        + snapshot.partially_enforced_count
        + snapshot.documented_only_count
        + snapshot.regression_risk_count
    )
    assert snapshot.total_invariants == total, (
        f"Snapshot invariant count inconsistency: total={snapshot.total_invariants}, "
        f"sum={total}"
    )


# ---------------------------------------------------------------------------
# AD. Snapshot assumption counts are internally consistent
# ---------------------------------------------------------------------------


def test_snapshot_assumption_counts_consistent() -> None:
    snapshot = build_enforcement_snapshot()
    total = snapshot.validated_assumption_count + snapshot.unvalidated_assumption_count
    assert snapshot.total_assumptions == total, (
        f"Snapshot assumption count inconsistency: total={snapshot.total_assumptions}, "
        f"sum={total}"
    )


# ---------------------------------------------------------------------------
# AE. Snapshot policy_sentinels list contains five sentinel strings
# ---------------------------------------------------------------------------


def test_snapshot_policy_sentinels_count() -> None:
    snapshot = build_enforcement_snapshot()
    assert len(snapshot.policy_sentinels) == 5


def test_snapshot_policy_sentinels_all_strings() -> None:
    snapshot = build_enforcement_snapshot()
    for s in snapshot.policy_sentinels:
        assert isinstance(s, str)
        assert s.startswith("POLICY::")


# ---------------------------------------------------------------------------
# AF. InvariantEnforcementSnapshot.to_dict() — expected top-level keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_expected_keys() -> None:
    snapshot = build_enforcement_snapshot()
    d = snapshot.to_dict()
    expected_keys = {
        "total_invariants",
        "by_status",
        "cross_repo_assumptions",
        "enforcement_posture_acceptable",
        "generated_at",
        "policy_sentinels",
        "gate_results",
        "invariant_summaries",
        "assumption_summaries",
    }
    assert expected_keys == set(d.keys()), (
        f"Snapshot dict keys mismatch: {set(d.keys()) ^ expected_keys}"
    )


def test_snapshot_to_dict_by_status_keys() -> None:
    snapshot = build_enforcement_snapshot()
    by_status = snapshot.to_dict()["by_status"]
    assert set(by_status.keys()) == {
        "enforced", "partially_enforced", "documented_only", "regression_risk"
    }


def test_snapshot_to_dict_cross_repo_assumptions_keys() -> None:
    snapshot = build_enforcement_snapshot()
    cross = snapshot.to_dict()["cross_repo_assumptions"]
    assert set(cross.keys()) == {"total", "validated", "unvalidated"}


# ---------------------------------------------------------------------------
# AG. RuntimeInvariantRecord.to_dict() — required keys
# ---------------------------------------------------------------------------


def test_invariant_record_to_dict_has_required_keys() -> None:
    required_keys = {
        "invariant_id", "domain", "severity", "status",
        "description", "enforcement_mechanism", "prior_pr_reference",
        "violation_log_prefix", "regression_risk_detail",
        "acceptance_test_gap", "notes",
    }
    for record in get_invariant_registry():
        d = record.to_dict()
        missing = required_keys - set(d.keys())
        assert not missing, (
            f"Missing keys in {record.invariant_id}.to_dict(): {missing}"
        )


# ---------------------------------------------------------------------------
# AH. CrossRepoAssumptionRecord.to_dict() — required keys
# ---------------------------------------------------------------------------


def test_assumption_record_to_dict_has_required_keys() -> None:
    required_keys = {
        "assumption_id", "domain", "v2_surface", "android_surface",
        "description", "validation_mechanism", "validated",
        "validation_evidence", "drift_consequence", "notes",
    }
    for record in get_cross_repo_assumption_registry():
        d = record.to_dict()
        missing = required_keys - set(d.keys())
        assert not missing, (
            f"Missing keys in {record.assumption_id}.to_dict(): {missing}"
        )


# ---------------------------------------------------------------------------
# AI. ValidationGateResult.to_dict() — required keys
# ---------------------------------------------------------------------------


def test_gate_result_to_dict_has_required_keys() -> None:
    required_keys = {
        "gate_id", "domain", "verdict", "regression_risk_count",
        "documented_only_count", "unvalidated_assumption_count",
        "details", "issues", "checked_at",
    }
    for result in run_all_enforcement_gates():
        d = result.to_dict()
        missing = required_keys - set(d.keys())
        assert not missing, (
            f"Missing keys in gate {result.gate_id}.to_dict(): {missing}"
        )


# ---------------------------------------------------------------------------
# AJ. is_enforcement_posture_acceptable() — True in clean state
# ---------------------------------------------------------------------------


def test_is_enforcement_posture_acceptable_true_in_clean_state() -> None:
    assert is_enforcement_posture_acceptable() is True


# ---------------------------------------------------------------------------
# AK. Snapshot enforcement_posture_acceptable agrees with function
# ---------------------------------------------------------------------------


def test_snapshot_posture_agrees_with_function() -> None:
    snapshot = build_enforcement_snapshot()
    assert snapshot.enforcement_posture_acceptable == is_enforcement_posture_acceptable()


# ---------------------------------------------------------------------------
# AL. Every DOCUMENTED_ONLY invariant has non-empty enforcement_mechanism
# ---------------------------------------------------------------------------


def test_documented_only_invariants_have_non_empty_enforcement_mechanism() -> None:
    for record in get_invariant_registry():
        if record.status == InvariantStatus.DOCUMENTED_ONLY:
            assert record.enforcement_mechanism, (
                f"DOCUMENTED_ONLY invariant {record.invariant_id} must have "
                "a non-empty enforcement_mechanism prescribing future enforcement."
            )


# ---------------------------------------------------------------------------
# AM. All invariants with acceptance_test_gap have non-empty gap description
# ---------------------------------------------------------------------------


def test_invariants_with_acceptance_test_gap_have_non_empty_description() -> None:
    for record in get_invariant_registry():
        # acceptance_test_gap is either empty or has a meaningful description
        if record.acceptance_test_gap:
            assert len(record.acceptance_test_gap) > 10, (
                f"acceptance_test_gap for {record.invariant_id} is too short: "
                f"{record.acceptance_test_gap!r}"
            )


# ---------------------------------------------------------------------------
# AN. All validated assumptions have non-empty validation_evidence
# ---------------------------------------------------------------------------


def test_validated_assumptions_have_non_empty_evidence() -> None:
    for record in get_cross_repo_assumption_registry():
        if record.validated:
            assert record.validation_evidence, (
                f"Validated assumption {record.assumption_id} must have "
                "non-empty validation_evidence."
            )


# ---------------------------------------------------------------------------
# AO. run_all_enforcement_gates() — each result to_dict has gate_id + verdict
# ---------------------------------------------------------------------------


def test_all_gate_results_to_dict_have_gate_id_and_verdict() -> None:
    for result in run_all_enforcement_gates():
        d = result.to_dict()
        assert "gate_id" in d, f"gate_id missing from gate result dict for {result.gate_id}"
        assert "verdict" in d, f"verdict missing from gate result dict for {result.gate_id}"


# ---------------------------------------------------------------------------
# AP. No invariant has InvariantStatus.REGRESSION_RISK (clean-state assertion)
# ---------------------------------------------------------------------------


def test_no_regression_risk_invariants_in_clean_state() -> None:
    regression = [
        r.invariant_id for r in get_invariant_registry()
        if r.status == InvariantStatus.REGRESSION_RISK
    ]
    assert regression == [], (
        f"REGRESSION_RISK invariants found in registry: {regression}"
    )


# ---------------------------------------------------------------------------
# AQ. Snapshot gate_results list is non-empty
# ---------------------------------------------------------------------------


def test_snapshot_gate_results_non_empty() -> None:
    snapshot = build_enforcement_snapshot()
    assert len(snapshot.gate_results) > 0


# ---------------------------------------------------------------------------
# AR. INV-001 has domain == task_lifecycle and severity == HIGH
# ---------------------------------------------------------------------------


def test_inv001_domain_and_severity() -> None:
    record = check_invariant("INV-001")
    assert record is not None
    assert record.domain == InvariantDomain.task_lifecycle
    assert record.severity == InvariantSeverity.HIGH


# ---------------------------------------------------------------------------
# AS. INV-004 has a non-empty violation_log_prefix containing 'INV-004'
# ---------------------------------------------------------------------------


def test_inv004_violation_log_prefix() -> None:
    record = check_invariant("INV-004")
    assert record is not None
    assert record.violation_log_prefix, "INV-004 must have a non-empty violation_log_prefix"
    assert "INV-004" in record.violation_log_prefix


# ---------------------------------------------------------------------------
# AT. ASSUME-001 has validated == True and non-empty validation_evidence
# ---------------------------------------------------------------------------


def test_assume001_validated_and_has_evidence() -> None:
    record = check_cross_repo_assumption("ASSUME-001")
    assert record is not None
    assert record.validated is True
    assert record.validation_evidence, "ASSUME-001 must have non-empty validation_evidence"


# ---------------------------------------------------------------------------
# AU. INV-009 has status == ENFORCED
# ---------------------------------------------------------------------------


def test_inv009_is_enforced() -> None:
    record = check_invariant("INV-009")
    assert record is not None
    assert record.status == InvariantStatus.ENFORCED, (
        f"INV-009 expected ENFORCED, got {record.status}"
    )


# ---------------------------------------------------------------------------
# AV. INV-010 has status == ENFORCED
# ---------------------------------------------------------------------------


def test_inv010_is_enforced() -> None:
    record = check_invariant("INV-010")
    assert record is not None
    assert record.status == InvariantStatus.ENFORCED, (
        f"INV-010 expected ENFORCED, got {record.status}"
    )


# ---------------------------------------------------------------------------
# Additional acceptance-oriented checks
# ---------------------------------------------------------------------------


def test_all_invariant_violation_log_prefixes_follow_convention() -> None:
    """INV-XXX violation_log_prefix must start with INVARIANT_VIOLATION:: if set."""
    for record in get_invariant_registry():
        if record.violation_log_prefix:
            assert record.violation_log_prefix.startswith("INVARIANT_VIOLATION::"), (
                f"{record.invariant_id} violation_log_prefix does not start with "
                f"'INVARIANT_VIOLATION::': {record.violation_log_prefix!r}"
            )


def test_all_cross_repo_assumptions_have_drift_consequence() -> None:
    """Every cross-repo assumption should document the consequence of violation."""
    for record in get_cross_repo_assumption_registry():
        assert record.drift_consequence, (
            f"CrossRepoAssumptionRecord {record.assumption_id} missing drift_consequence"
        )


def test_snapshot_invariant_summaries_length_matches_registry() -> None:
    """Snapshot invariant_summaries should contain one entry per invariant."""
    snapshot = build_enforcement_snapshot()
    registry = get_invariant_registry()
    assert len(snapshot.invariant_summaries) == len(registry)


def test_snapshot_assumption_summaries_length_matches_registry() -> None:
    """Snapshot assumption_summaries should contain one entry per assumption."""
    snapshot = build_enforcement_snapshot()
    registry = get_cross_repo_assumption_registry()
    assert len(snapshot.assumption_summaries) == len(registry)


def test_cross_repo_validation_gate_pass_in_clean_state() -> None:
    """In the clean registry, the aggregate cross-repo validation gate must pass."""
    result = run_cross_repo_validation_gate()
    assert result.verdict in (
        ValidationGateVerdict.pass_,
        ValidationGateVerdict.warn,
    ), (
        f"Cross-repo validation gate should be pass or warn in clean state, "
        f"got: {result.verdict}"
    )


def test_invariant_gate_no_fail_verdicts_in_clean_state() -> None:
    """In the clean registry no domain gate should return a fail verdict."""
    for domain in InvariantDomain:
        result = run_invariant_gate(domain)
        assert result.verdict != ValidationGateVerdict.fail, (
            f"Domain gate {domain.value} returned fail verdict in clean state: "
            f"{result.details}"
        )


def test_enforcement_snapshot_generated_at_is_recent() -> None:
    """Snapshot generated_at should be a recent Unix timestamp (within last 60s)."""
    snapshot = build_enforcement_snapshot()
    now = time.time()
    assert snapshot.generated_at <= now
    assert snapshot.generated_at > now - 60, (
        "Snapshot generated_at is unexpectedly old"
    )
