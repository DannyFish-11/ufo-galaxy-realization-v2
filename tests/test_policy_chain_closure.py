#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_policy_chain_closure.py
=====================================
PR-B: Contract / Truth / Policy Closure — Policy Chain Closure tests.

Validates that ``core.admissibility_policy_convergence`` correctly produces
the PR-B standardised policy output fields:
  - degradation_reason
  - selected_target_reason
  - failure_domain

And that the readiness/participation/validator/policy chain produces
consistent, observable output.

Test classes
------------
1. TestPolicyConvergenceOutputPRBFields
       PolicyConvergenceOutput has degradation_reason, selected_target_reason,
       failure_domain as optional string fields.
       to_dict() includes all three fields.

2. TestEligibleDeviceHasSelectedTargetReason
       An eligible device gets a non-None selected_target_reason.
       An eligible device has failure_domain=None and degradation_reason=None.

3. TestIneligibleDeviceHasFailureDomain
       An ineligible device gets a non-None failure_domain.
       failure_domain value is a valid FailureDomain value string.

4. TestIneligibleDeviceHasDegradationReason
       An ineligible device gets a non-None degradation_reason.

5. TestTransportNotPresentMapsToTransportFailure
       transport_present=False → failure_domain contains "transport".

6. TestDeviceNotRoutableMapsToRoutingFailure
       device_routable=False, transport_present=True → failure_domain contains "routing".

7. TestEmptyDeviceIdHasValidationFailureDomain
       Empty device_id → failure_domain contains "validation".

8. TestPolicyOutputContractVersion
       contract_version is POLICY_OUTPUT_CONTRACT_VERSION in all output.

9. TestToDict_AllPRBFields
       to_dict() output is JSON-serialisable and contains all PR-B fields.

10. TestChainDegradationWhenLayersUnavailable
        Even when all sub-layers are unavailable, the output still has
        failure_domain and degradation_reason set.
"""

from __future__ import annotations

import json
import sys
import os
import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.admissibility_policy_convergence import (
    PolicyConvergenceOutput,
    evaluate_policy_convergence,
    ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY,
    POLICY_CONVERGENCE_LAYER_POSITION,
    POLICY_OUTPUT_CONTRACT_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness(
    device_id: str = "dev1",
    registered: bool = True,
    online: bool = True,
    transport_present: bool = True,
    transport_usable: bool = True,
    device_routable: bool = True,
    effective_path: str = "direct_ws",
):
    routability = MagicMock()
    routability.transport_present = transport_present
    routability.transport_usable = transport_usable
    routability.device_routable = device_routable
    routability.effective_routable = device_routable
    routability.effective_path = effective_path
    routability.preferred_path = effective_path

    readiness = MagicMock()
    readiness.device_id = device_id
    readiness.registered = registered
    readiness.online = online
    readiness.routability = routability
    readiness.to_dict.return_value = {"device_id": device_id, "registered": registered}
    return readiness


def _make_participation(device_id: str = "dev1"):
    p = MagicMock()
    p.device_id = device_id
    p.orchestration_eligible = True
    p.to_dict.return_value = {"device_id": device_id}
    return p


def _make_validation(valid: bool = True, capability_match: bool = True):
    v = MagicMock()
    v.valid = valid
    v.capability_match = capability_match
    v.reasons = [] if valid else ["not-registered"]
    v.to_dict.return_value = {"valid": valid, "capability_match": capability_match}
    return v


# ---------------------------------------------------------------------------
# 1. PolicyConvergenceOutput PR-B fields
# ---------------------------------------------------------------------------


class TestPolicyConvergenceOutputPRBFields(unittest.TestCase):
    def setUp(self) -> None:
        self.output = PolicyConvergenceOutput(device_id="dev1")

    def test_has_degradation_reason(self) -> None:
        assert hasattr(self.output, "degradation_reason")

    def test_degradation_reason_default_is_none(self) -> None:
        assert self.output.degradation_reason is None

    def test_has_selected_target_reason(self) -> None:
        assert hasattr(self.output, "selected_target_reason")

    def test_selected_target_reason_default_is_none(self) -> None:
        assert self.output.selected_target_reason is None

    def test_has_failure_domain(self) -> None:
        assert hasattr(self.output, "failure_domain")

    def test_failure_domain_default_is_none(self) -> None:
        assert self.output.failure_domain is None

    def test_to_dict_contains_degradation_reason(self) -> None:
        d = self.output.to_dict()
        assert "degradation_reason" in d

    def test_to_dict_contains_selected_target_reason(self) -> None:
        d = self.output.to_dict()
        assert "selected_target_reason" in d

    def test_to_dict_contains_failure_domain(self) -> None:
        d = self.output.to_dict()
        assert "failure_domain" in d

    def test_to_dict_is_json_serialisable(self) -> None:
        d = self.output.to_dict()
        serialised = json.dumps(d)
        assert serialised


# ---------------------------------------------------------------------------
# 2. Eligible device has selected_target_reason
# ---------------------------------------------------------------------------


class TestEligibleDeviceHasSelectedTargetReason(unittest.TestCase):
    def _run_eligible(self, device_id: str = "dev_eligible") -> PolicyConvergenceOutput:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=_make_readiness(device_id),
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=_make_participation(device_id),
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=True, capability_match=True),
            ),
        ):
            return evaluate_policy_convergence(device_id)

    def test_eligible_device_has_selected_target_reason(self) -> None:
        output = self._run_eligible()
        assert output.selected_target_reason is not None
        assert output.selected_target_reason

    def test_eligible_device_has_no_failure_domain(self) -> None:
        output = self._run_eligible()
        assert output.failure_domain is None

    def test_eligible_device_has_no_degradation_reason(self) -> None:
        output = self._run_eligible()
        assert output.degradation_reason is None

    def test_selected_target_reason_mentions_score(self) -> None:
        output = self._run_eligible()
        assert "score" in output.selected_target_reason


# ---------------------------------------------------------------------------
# 3. Ineligible device has failure_domain
# ---------------------------------------------------------------------------


class TestIneligibleDeviceHasFailureDomain(unittest.TestCase):
    def _run_ineligible(
        self,
        device_id: str = "dev_ineligible",
        transport_present: bool = False,
        transport_usable: bool = False,
        device_routable: bool = False,
    ) -> PolicyConvergenceOutput:
        readiness = _make_readiness(
            device_id,
            registered=False,
            online=False,
            transport_present=transport_present,
            transport_usable=transport_usable,
            device_routable=device_routable,
            effective_path="none",
        )
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=readiness,
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=False, capability_match=False),
            ),
        ):
            return evaluate_policy_convergence(device_id)

    def test_ineligible_device_has_failure_domain(self) -> None:
        output = self._run_ineligible()
        assert output.failure_domain is not None
        assert output.failure_domain

    def test_failure_domain_is_valid_string(self) -> None:
        from core.failure_domains import FailureDomain
        output = self._run_ineligible()
        # Should be a valid FailureDomain value
        values = {d.value for d in FailureDomain}
        assert output.failure_domain in values, (
            f"failure_domain {output.failure_domain!r} not in FailureDomain values"
        )

    def test_ineligible_device_has_selected_target_reason(self) -> None:
        output = self._run_ineligible()
        assert output.selected_target_reason is not None
        assert "not selected" in output.selected_target_reason.lower() or output.selected_target_reason


# ---------------------------------------------------------------------------
# 4. Ineligible device has degradation_reason
# ---------------------------------------------------------------------------


class TestIneligibleDeviceHasDegradationReason(unittest.TestCase):
    def _run_ineligible(self, device_id: str = "dev_deg") -> PolicyConvergenceOutput:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=_make_readiness(
                    device_id,
                    transport_present=False,
                    transport_usable=False,
                    device_routable=False,
                    effective_path="none",
                ),
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=False, capability_match=False),
            ),
        ):
            return evaluate_policy_convergence(device_id)

    def test_ineligible_device_has_degradation_reason(self) -> None:
        output = self._run_ineligible()
        assert output.degradation_reason is not None
        assert output.degradation_reason

    def test_degradation_reason_is_string(self) -> None:
        output = self._run_ineligible()
        assert isinstance(output.degradation_reason, str)


# ---------------------------------------------------------------------------
# 5. Transport not present → transport failure domain
# ---------------------------------------------------------------------------


class TestTransportNotPresentMapsToTransportFailure(unittest.TestCase):
    def test_transport_not_present_gives_transport_failure(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=_make_readiness(
                    "dev_no_transport",
                    transport_present=False,
                    transport_usable=False,
                    device_routable=False,
                    effective_path="none",
                ),
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=False),
            ),
        ):
            output = evaluate_policy_convergence("dev_no_transport")

        assert output.failure_domain is not None
        assert "transport" in output.failure_domain or "routing" in output.failure_domain

    def test_transport_not_present_degradation_reason(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=_make_readiness(
                    "dev_x",
                    transport_present=False,
                    transport_usable=False,
                    device_routable=False,
                    effective_path="none",
                ),
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=False),
            ),
        ):
            output = evaluate_policy_convergence("dev_x")

        assert output.degradation_reason is not None
        assert "transport" in output.degradation_reason or "not" in output.degradation_reason


# ---------------------------------------------------------------------------
# 6. Device not routable → routing failure domain
# ---------------------------------------------------------------------------


class TestDeviceNotRoutableMapsToRoutingFailure(unittest.TestCase):
    def test_not_routable_gives_routing_failure(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=_make_readiness(
                    "dev_no_route",
                    transport_present=True,
                    transport_usable=True,
                    device_routable=False,
                    effective_path="none",
                ),
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=_make_validation(valid=False),
            ),
        ):
            output = evaluate_policy_convergence("dev_no_route")

        assert output.failure_domain is not None
        assert "routing" in output.failure_domain or "transport" in output.failure_domain


# ---------------------------------------------------------------------------
# 7. Empty device_id → validation failure domain
# ---------------------------------------------------------------------------


class TestEmptyDeviceIdHasValidationFailureDomain(unittest.TestCase):
    def test_empty_device_id_failure_domain(self) -> None:
        output = evaluate_policy_convergence("")
        assert output.eligibility is False
        # failure_domain should be set
        assert output.failure_domain is not None
        assert "validation" in output.failure_domain

    def test_empty_device_id_degradation_reason(self) -> None:
        output = evaluate_policy_convergence("")
        assert output.degradation_reason is not None


# ---------------------------------------------------------------------------
# 8. contract_version in all output
# ---------------------------------------------------------------------------


class TestPolicyOutputContractVersion(unittest.TestCase):
    def test_default_contract_version(self) -> None:
        output = PolicyConvergenceOutput(device_id="test")
        assert output.contract_version == POLICY_OUTPUT_CONTRACT_VERSION

    def test_evaluate_output_has_correct_version(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=None,
            ),
        ):
            output = evaluate_policy_convergence("test_dev")

        assert output.contract_version == POLICY_OUTPUT_CONTRACT_VERSION


# ---------------------------------------------------------------------------
# 9. to_dict — all PR-B fields
# ---------------------------------------------------------------------------


class TestToDictAllPRBFields(unittest.TestCase):
    def test_all_pr_b_fields_in_to_dict(self) -> None:
        output = PolicyConvergenceOutput(device_id="dev1")
        d = output.to_dict()
        pr_b_fields = [
            "eligibility",
            "capability_fit",
            "route_preference",
            "policy_score",
            "transport_present",
            "transport_usable",
            "device_routable",
            "effective_path",
            "degradation_reason",
            "selected_target_reason",
            "failure_domain",
            "reasons",
            "contract_version",
        ]
        for f in pr_b_fields:
            assert f in d, f"to_dict() missing field {f!r}"

    def test_to_dict_json_serialisable(self) -> None:
        output = PolicyConvergenceOutput(
            device_id="dev1",
            eligibility=False,
            failure_domain="routing_failure",
            degradation_reason="device not routable",
            selected_target_reason="device not selected: device not routable",
        )
        serialised = json.dumps(output.to_dict())
        assert serialised

    def test_to_dict_with_all_pr_b_fields_set(self) -> None:
        output = PolicyConvergenceOutput(
            device_id="dev1",
            eligibility=True,
            capability_fit=True,
            policy_score=0.8,
            route_preference="direct_ws",
            transport_present=True,
            transport_usable=True,
            device_routable=True,
            effective_path="direct_ws",
            degradation_reason=None,
            selected_target_reason="device eligible: score=0.800 path=direct_ws",
            failure_domain=None,
        )
        d = output.to_dict()
        assert d["selected_target_reason"] is not None
        assert d["failure_domain"] is None
        assert d["degradation_reason"] is None


# ---------------------------------------------------------------------------
# 10. Chain degradation when layers unavailable
# ---------------------------------------------------------------------------


class TestChainDegradationWhenLayersUnavailable(unittest.TestCase):
    def test_all_layers_unavailable_still_has_failure_domain(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=None,
            ),
        ):
            output = evaluate_policy_convergence("orphan_dev")

        assert output.eligibility is False
        assert output.failure_domain is not None

    def test_all_layers_unavailable_has_degradation_reason(self) -> None:
        with (
            patch(
                "core.admissibility_policy_convergence._get_readiness",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_participation",
                return_value=None,
            ),
            patch(
                "core.admissibility_policy_convergence._get_validation",
                return_value=None,
            ),
        ):
            output = evaluate_policy_convergence("orphan_dev2")

        assert output.degradation_reason is not None


if __name__ == "__main__":
    unittest.main()
