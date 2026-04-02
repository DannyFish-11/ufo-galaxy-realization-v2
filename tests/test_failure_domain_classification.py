#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_failure_domain_classification.py
=============================================
PR-B: Contract / Truth / Policy Closure — Failure Domain Classification tests.

Validates that ``core.failure_domains`` correctly provides the PR-B canonical
failure domain vocabulary and that classification helpers work correctly.

Test classes
------------
1. TestPRBFailureDomainMembers
       All seven PR-B canonical failure domains are present in FailureDomain.

2. TestPRBFailureDomainsSet
       PR_B_FAILURE_DOMAINS contains exactly the seven PR-B domains.

3. TestFailureDomainClosureAuthority
       FAILURE_DOMAIN_CLOSURE_AUTHORITY is importable and non-empty.

4. TestMapToPRBDomain
       PR-13 domains map to the correct PR-B equivalents.
       PR-B domains map to themselves (identity).

5. TestPRBDomainsInDomainDescriptions
       All seven PR-B domains have entries in DOMAIN_DESCRIPTIONS.

6. TestPRBRetryEligibility
       transport_failure and fabric_failure are retryable (transient).
       semantic_failure is retryable on alternate target.
       policy_failure and validation_failure and executor_failure are not retryable.

7. TestClassifyFromErrorCodePRB
       PR-B error codes (SEMANTIC_MISMATCH, POLICY_REJECTED, etc.) map correctly.

8. TestClassifyFromExceptionPreservesExisting
       classify_from_exception() still works for the original PR-13 cases.

9. TestAllDomainValuesUnique
       All FailureDomain values are unique strings.
"""

from __future__ import annotations

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.failure_domains import (
    FailureDomain,
    FailureClassification,
    classify_from_error_code,
    classify_from_exception,
    is_retryable_by_domain,
    downgrade_hint_for_domain,
    DOMAIN_DESCRIPTIONS,
    PR_B_FAILURE_DOMAINS,
    FAILURE_DOMAIN_CLOSURE_AUTHORITY,
    map_to_pr_b_domain,
)


# ---------------------------------------------------------------------------
# 1. PR-B failure domain members
# ---------------------------------------------------------------------------


class TestPRBFailureDomainMembers(unittest.TestCase):
    _REQUIRED_PR_B = [
        "SEMANTIC_FAILURE",
        "VALIDATION_FAILURE",
        "POLICY_FAILURE",
        "ROUTING_FAILURE",
        "FABRIC_FAILURE",
        "TRANSPORT_FAILURE",
        "EXECUTOR_FAILURE",
    ]

    def test_all_pr_b_members_present(self) -> None:
        for member_name in self._REQUIRED_PR_B:
            assert hasattr(FailureDomain, member_name), (
                f"FailureDomain.{member_name} is missing"
            )

    def test_pr_b_member_values_are_strings(self) -> None:
        for member_name in self._REQUIRED_PR_B:
            domain = getattr(FailureDomain, member_name)
            assert isinstance(domain.value, str)
            assert domain.value  # non-empty

    def test_semantic_failure_value(self) -> None:
        assert FailureDomain.SEMANTIC_FAILURE.value == "semantic_failure"

    def test_validation_failure_value(self) -> None:
        assert FailureDomain.VALIDATION_FAILURE.value == "validation_failure"

    def test_policy_failure_value(self) -> None:
        assert FailureDomain.POLICY_FAILURE.value == "policy_failure"

    def test_routing_failure_value(self) -> None:
        assert FailureDomain.ROUTING_FAILURE.value == "routing_failure"

    def test_fabric_failure_value(self) -> None:
        assert FailureDomain.FABRIC_FAILURE.value == "fabric_failure"

    def test_transport_failure_value(self) -> None:
        assert FailureDomain.TRANSPORT_FAILURE.value == "transport_failure"

    def test_executor_failure_value(self) -> None:
        assert FailureDomain.EXECUTOR_FAILURE.value == "executor_failure"


# ---------------------------------------------------------------------------
# 2. PR_B_FAILURE_DOMAINS set
# ---------------------------------------------------------------------------


class TestPRBFailureDomainsSet(unittest.TestCase):
    _EXPECTED = {
        FailureDomain.SEMANTIC_FAILURE,
        FailureDomain.VALIDATION_FAILURE,
        FailureDomain.POLICY_FAILURE,
        FailureDomain.ROUTING_FAILURE,
        FailureDomain.FABRIC_FAILURE,
        FailureDomain.TRANSPORT_FAILURE,
        FailureDomain.EXECUTOR_FAILURE,
    }

    def test_pr_b_domains_contains_all_expected(self) -> None:
        for domain in self._EXPECTED:
            assert domain in PR_B_FAILURE_DOMAINS, (
                f"{domain} not in PR_B_FAILURE_DOMAINS"
            )

    def test_pr_b_domains_has_exactly_seven(self) -> None:
        assert len(PR_B_FAILURE_DOMAINS) == 7

    def test_pr_b_domains_is_frozenset(self) -> None:
        assert isinstance(PR_B_FAILURE_DOMAINS, frozenset)


# ---------------------------------------------------------------------------
# 3. FAILURE_DOMAIN_CLOSURE_AUTHORITY
# ---------------------------------------------------------------------------


class TestFailureDomainClosureAuthority(unittest.TestCase):
    def test_authority_is_string(self) -> None:
        assert isinstance(FAILURE_DOMAIN_CLOSURE_AUTHORITY, str)
        assert FAILURE_DOMAIN_CLOSURE_AUTHORITY

    def test_authority_contains_version(self) -> None:
        assert "V1" in FAILURE_DOMAIN_CLOSURE_AUTHORITY


# ---------------------------------------------------------------------------
# 4. map_to_pr_b_domain
# ---------------------------------------------------------------------------


class TestMapToPRBDomain(unittest.TestCase):
    _PR13_TO_PR_B = {
        FailureDomain.LOCAL_RUNTIME_FAILURE: FailureDomain.EXECUTOR_FAILURE,
        FailureDomain.REMOTE_CAPABILITY_MISMATCH: FailureDomain.SEMANTIC_FAILURE,
        FailureDomain.REMOTE_DEVICE_UNAVAILABLE: FailureDomain.ROUTING_FAILURE,
        FailureDomain.GATEWAY_TRANSPORT_FAILURE: FailureDomain.TRANSPORT_FAILURE,
        FailureDomain.SUBSTRATE_DISPATCH_FAILURE: FailureDomain.ROUTING_FAILURE,
        FailureDomain.CONTRACT_VALIDATION_FAILURE: FailureDomain.VALIDATION_FAILURE,
        FailureDomain.TIMEOUT_FAILURE: FailureDomain.TRANSPORT_FAILURE,
    }

    def test_pr13_domains_map_to_correct_pr_b_equivalents(self) -> None:
        for pr13_domain, expected_pr_b in self._PR13_TO_PR_B.items():
            result = map_to_pr_b_domain(pr13_domain)
            assert result == expected_pr_b, (
                f"map_to_pr_b_domain({pr13_domain!r}) should return "
                f"{expected_pr_b!r}, got {result!r}"
            )

    def test_pr_b_domains_map_to_themselves(self) -> None:
        for domain in PR_B_FAILURE_DOMAINS:
            result = map_to_pr_b_domain(domain)
            assert result == domain, (
                f"PR-B domain {domain!r} should map to itself, got {result!r}"
            )

    def test_unknown_failure_maps_to_unknown(self) -> None:
        result = map_to_pr_b_domain(FailureDomain.UNKNOWN_FAILURE)
        assert result == FailureDomain.UNKNOWN_FAILURE


# ---------------------------------------------------------------------------
# 5. PR-B domains in DOMAIN_DESCRIPTIONS
# ---------------------------------------------------------------------------


class TestPRBDomainsInDomainDescriptions(unittest.TestCase):
    def test_all_pr_b_domains_have_descriptions(self) -> None:
        for domain in PR_B_FAILURE_DOMAINS:
            assert domain in DOMAIN_DESCRIPTIONS, (
                f"PR-B domain {domain!r} has no entry in DOMAIN_DESCRIPTIONS"
            )

    def test_pr_b_descriptions_are_non_empty(self) -> None:
        for domain in PR_B_FAILURE_DOMAINS:
            desc = DOMAIN_DESCRIPTIONS.get(domain, "")
            assert desc, (
                f"PR-B domain {domain!r} has empty description"
            )


# ---------------------------------------------------------------------------
# 6. PR-B retry eligibility
# ---------------------------------------------------------------------------


class TestPRBRetryEligibility(unittest.TestCase):
    def test_transport_failure_is_retryable(self) -> None:
        assert is_retryable_by_domain(FailureDomain.TRANSPORT_FAILURE)

    def test_fabric_failure_is_retryable(self) -> None:
        assert is_retryable_by_domain(FailureDomain.FABRIC_FAILURE)

    def test_semantic_failure_retryable_on_alternate_target(self) -> None:
        # Not retryable on same target
        assert not is_retryable_by_domain(
            FailureDomain.SEMANTIC_FAILURE, allow_alternate_target=False
        )
        # But retryable on alternate target
        assert is_retryable_by_domain(
            FailureDomain.SEMANTIC_FAILURE, allow_alternate_target=True
        )

    def test_routing_failure_retryable_on_alternate_target(self) -> None:
        assert not is_retryable_by_domain(
            FailureDomain.ROUTING_FAILURE, allow_alternate_target=False
        )
        assert is_retryable_by_domain(
            FailureDomain.ROUTING_FAILURE, allow_alternate_target=True
        )

    def test_policy_failure_not_retryable(self) -> None:
        assert not is_retryable_by_domain(FailureDomain.POLICY_FAILURE)
        assert not is_retryable_by_domain(
            FailureDomain.POLICY_FAILURE, allow_alternate_target=True
        )

    def test_validation_failure_not_retryable(self) -> None:
        assert not is_retryable_by_domain(FailureDomain.VALIDATION_FAILURE)

    def test_executor_failure_not_retryable(self) -> None:
        assert not is_retryable_by_domain(FailureDomain.EXECUTOR_FAILURE)


# ---------------------------------------------------------------------------
# 7. classify_from_error_code with PR-B codes
# ---------------------------------------------------------------------------


class TestClassifyFromErrorCodePRB(unittest.TestCase):
    _PR_B_CODE_MAP = {
        "SEMANTIC_MISMATCH": FailureDomain.SEMANTIC_FAILURE,
        "POLICY_REJECTED": FailureDomain.POLICY_FAILURE,
        "ROUTE_NOT_FOUND": FailureDomain.ROUTING_FAILURE,
        "FABRIC_ERROR": FailureDomain.FABRIC_FAILURE,
        "TRANSPORT_ERROR": FailureDomain.TRANSPORT_FAILURE,
        "EXECUTOR_FAILED": FailureDomain.EXECUTOR_FAILURE,
        "VALIDATION_ERROR": FailureDomain.VALIDATION_FAILURE,
    }

    def test_pr_b_error_codes_map_correctly(self) -> None:
        for code, expected_domain in self._PR_B_CODE_MAP.items():
            classification = classify_from_error_code(code)
            assert classification.domain == expected_domain, (
                f"classify_from_error_code({code!r}) should return "
                f"{expected_domain!r}, got {classification.domain!r}"
            )

    def test_returns_failure_classification(self) -> None:
        for code in self._PR_B_CODE_MAP:
            result = classify_from_error_code(code)
            assert isinstance(result, FailureClassification)


# ---------------------------------------------------------------------------
# 8. classify_from_exception — backward compatibility
# ---------------------------------------------------------------------------


class TestClassifyFromExceptionPreservesExisting(unittest.TestCase):
    def test_timeout_exception(self) -> None:
        exc = TimeoutError("operation timed out")
        classification = classify_from_exception(exc)
        assert classification.domain == FailureDomain.TIMEOUT_FAILURE

    def test_connection_exception(self) -> None:
        exc = ConnectionError("network connection failed")
        classification = classify_from_exception(exc)
        assert classification.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE

    def test_generic_exception_is_local_runtime(self) -> None:
        exc = RuntimeError("something went wrong")
        classification = classify_from_exception(exc)
        assert classification.domain == FailureDomain.LOCAL_RUNTIME_FAILURE

    def test_to_dict_contains_domain(self) -> None:
        exc = TimeoutError("test")
        result = classify_from_exception(exc).to_dict()
        assert "domain" in result
        assert result["domain"] == FailureDomain.TIMEOUT_FAILURE.value


# ---------------------------------------------------------------------------
# 9. All domain values unique
# ---------------------------------------------------------------------------


class TestAllDomainValuesUnique(unittest.TestCase):
    def test_all_values_are_unique(self) -> None:
        values = [d.value for d in FailureDomain]
        assert len(values) == len(set(values)), (
            "FailureDomain has duplicate values: "
            + str([v for v in values if values.count(v) > 1])
        )

    def test_pr_b_values_do_not_overlap_with_pr13_values(self) -> None:
        pr13_values = {
            FailureDomain.LOCAL_RUNTIME_FAILURE.value,
            FailureDomain.REMOTE_CAPABILITY_MISMATCH.value,
            FailureDomain.REMOTE_DEVICE_UNAVAILABLE.value,
            FailureDomain.GATEWAY_TRANSPORT_FAILURE.value,
            FailureDomain.SUBSTRATE_DISPATCH_FAILURE.value,
            FailureDomain.ORCHESTRATION_PARTIAL_FAILURE.value,
            FailureDomain.CONTRACT_VALIDATION_FAILURE.value,
            FailureDomain.TIMEOUT_FAILURE.value,
            FailureDomain.UNKNOWN_FAILURE.value,
        }
        pr_b_values = {d.value for d in PR_B_FAILURE_DOMAINS}
        overlap = pr13_values & pr_b_values
        assert not overlap, (
            f"PR-13 and PR-B domain values overlap: {overlap}"
        )


if __name__ == "__main__":
    unittest.main()
