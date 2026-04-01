#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_admissibility_chain.py
===================================
PR-5: Admissibility & Policy Convergence — chain integration tests.

Covers the unified admissibility + policy convergence layer
(``core.admissibility_policy_convergence``) and validates that the three-layer
chain is correctly wired end-to-end.

Test classes
------------
1. TestPolicyConvergenceSentinels
       Authority sentinels and contract version are importable and stable.

2. TestPolicyConvergenceOutputModel
       PolicyConvergenceOutput serialises correctly.
       Default fields are correct.
       to_dict() contains all standardised PR-5 fields.

3. TestEvaluatePolicyConvergenceEligible
       A registered+ready+routable device with all checks passing produces:
         eligibility=True, capability_fit=True, policy_score>0, route_preference set.

4. TestEvaluatePolicyConvergenceIneligible
       An unregistered device produces eligibility=False, policy_score=0.0.
       A not-routable device produces eligibility=False.

5. TestPolicyScoreRange
       policy_score is always in [0.0, 1.0].
       Eligible device has score > 0.
       Ineligible device has score == 0.0.

6. TestRoutePreferenceField
       route_preference reflects the effective_path from readiness.
       direct_ws path produces route_preference="direct_ws".
       No transport produces route_preference="none".

7. TestLiveRouteTruthInOutput
       transport_present, transport_usable, device_routable, effective_path
       from readiness Layer 1 are propagated to PolicyConvergenceOutput.

8. TestParticipationEnrichDoesNotOverride
       Participation enrichment in sources but does NOT override transport fields.

9. TestEmptyDeviceId
       Empty device_id produces eligibility=False with empty-device-id reason.

10. TestLayerDegradation
       When individual layers are unavailable, output degrades gracefully.
"""

from __future__ import annotations

import sys
import os
import unittest
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
    device_id="dev1",
    registered=True,
    online=True,
    connected=True,
    routable=True,
    effective_path="direct_ws",
    transport_present=True,
    transport_usable=True,
    device_routable=True,
):
    routability = MagicMock()
    routability.transport_present = transport_present
    routability.transport_usable = transport_usable
    routability.device_routable = device_routable
    routability.effective_routable = device_routable
    routability.effective_path = effective_path
    routability.preferred_path = effective_path

    rs = MagicMock()
    rs.registered = registered
    rs.online = online
    rs.connected = connected
    rs.routable = routable
    rs.routability = routability
    rs.to_dict = lambda: {"device_id": device_id, "registered": registered}
    return rs


def _make_participation(orchestration_eligible=True):
    ps = MagicMock()
    ps.orchestration_eligible = orchestration_eligible
    ps.to_dict = lambda: {"orchestration_eligible": orchestration_eligible}
    return ps


def _make_validation(valid=True, capability_match=True, reasons=None):
    vr = MagicMock()
    vr.valid = valid
    vr.capability_match = capability_match
    vr.reasons = reasons or []
    vr.to_dict = lambda: {
        "valid": valid,
        "capability_match": capability_match,
        "reasons": reasons or [],
    }
    return vr


# ---------------------------------------------------------------------------
# 1. TestPolicyConvergenceSentinels
# ---------------------------------------------------------------------------


class TestPolicyConvergenceSentinels(unittest.TestCase):
    def test_authority_sentinel_is_string(self):
        self.assertIsInstance(ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY, str)
        self.assertTrue(len(ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY) > 0)

    def test_authority_sentinel_value(self):
        self.assertEqual(
            ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY,
            "ADMISSIBILITY_POLICY_CONVERGENCE_V1",
        )

    def test_layer_position_above_layer3(self):
        self.assertEqual(POLICY_CONVERGENCE_LAYER_POSITION, 4)

    def test_contract_version_is_string(self):
        self.assertIsInstance(POLICY_OUTPUT_CONTRACT_VERSION, str)

    def test_contract_version_value(self):
        self.assertEqual(POLICY_OUTPUT_CONTRACT_VERSION, "POLICY_CONTRACT_V1")

    def test_sentinels_in_exports(self):
        from core.admissibility_policy_convergence import __all__ as exports
        self.assertIn("ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY", exports)
        self.assertIn("POLICY_OUTPUT_CONTRACT_VERSION", exports)
        self.assertIn("PolicyConvergenceOutput", exports)
        self.assertIn("evaluate_policy_convergence", exports)


# ---------------------------------------------------------------------------
# 2. TestPolicyConvergenceOutputModel
# ---------------------------------------------------------------------------


class TestPolicyConvergenceOutputModel(unittest.TestCase):
    def test_default_fields(self):
        out = PolicyConvergenceOutput(device_id="dev1")
        self.assertFalse(out.eligibility)
        self.assertFalse(out.capability_fit)
        self.assertEqual(out.policy_score, 0.0)
        self.assertEqual(out.route_preference, "none")
        self.assertFalse(out.transport_present)
        self.assertFalse(out.transport_usable)
        self.assertFalse(out.device_routable)
        self.assertEqual(out.effective_path, "none")

    def test_contract_version_in_default(self):
        out = PolicyConvergenceOutput(device_id="dev1")
        self.assertEqual(out.contract_version, POLICY_OUTPUT_CONTRACT_VERSION)

    def test_to_dict_contains_all_pr5_fields(self):
        out = PolicyConvergenceOutput(device_id="dev1")
        d = out.to_dict()
        for key in (
            "device_id", "eligibility", "capability_fit", "policy_score",
            "route_preference", "transport_present", "transport_usable",
            "device_routable", "effective_path", "reasons", "sources",
            "contract_version",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_serialises_values_correctly(self):
        out = PolicyConvergenceOutput(
            device_id="dev1",
            eligibility=True,
            capability_fit=True,
            policy_score=0.8,
            route_preference="direct_ws",
            transport_present=True,
            transport_usable=True,
            device_routable=True,
            effective_path="direct_ws",
        )
        d = out.to_dict()
        self.assertTrue(d["eligibility"])
        self.assertTrue(d["capability_fit"])
        self.assertAlmostEqual(d["policy_score"], 0.8)
        self.assertEqual(d["route_preference"], "direct_ws")
        self.assertTrue(d["transport_present"])
        self.assertTrue(d["transport_usable"])
        self.assertTrue(d["device_routable"])
        self.assertEqual(d["effective_path"], "direct_ws")


# ---------------------------------------------------------------------------
# 3. TestEvaluatePolicyConvergenceEligible
# ---------------------------------------------------------------------------


class TestEvaluatePolicyConvergenceEligible(unittest.TestCase):
    def _mock_all_layers(self):
        rs = _make_readiness()
        ps = _make_participation()
        vr = _make_validation()
        return rs, ps, vr

    def test_eligible_device_produces_eligibility_true(self):
        rs, ps, vr = self._mock_all_layers()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=ps), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertTrue(out.eligibility)

    def test_eligible_device_has_positive_policy_score(self):
        rs, ps, vr = self._mock_all_layers()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=ps), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertGreater(out.policy_score, 0.0)

    def test_eligible_device_route_preference_is_direct_ws(self):
        rs, ps, vr = self._mock_all_layers()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=ps), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.route_preference, "direct_ws")

    def test_eligible_device_capability_fit_true(self):
        rs, ps, vr = self._mock_all_layers()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=ps), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertTrue(out.capability_fit)


# ---------------------------------------------------------------------------
# 4. TestEvaluatePolicyConvergenceIneligible
# ---------------------------------------------------------------------------


class TestEvaluatePolicyConvergenceIneligible(unittest.TestCase):
    def test_not_valid_device_produces_eligibility_false(self):
        rs = _make_readiness(registered=False)
        vr = _make_validation(valid=False, capability_match=False, reasons=["not-registered"])
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertFalse(out.eligibility)

    def test_ineligible_device_has_zero_policy_score(self):
        rs = _make_readiness(registered=False)
        vr = _make_validation(valid=False)
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.policy_score, 0.0)


# ---------------------------------------------------------------------------
# 5. TestPolicyScoreRange
# ---------------------------------------------------------------------------


class TestPolicyScoreRange(unittest.TestCase):
    def _eval(self, eligible=True):
        rs = _make_readiness()
        vr = _make_validation(valid=eligible)
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            return evaluate_policy_convergence("dev1")

    def test_score_in_range_for_eligible(self):
        out = self._eval(eligible=True)
        self.assertGreaterEqual(out.policy_score, 0.0)
        self.assertLessEqual(out.policy_score, 1.0)

    def test_score_zero_for_ineligible(self):
        out = self._eval(eligible=False)
        self.assertEqual(out.policy_score, 0.0)

    def test_score_positive_for_eligible(self):
        out = self._eval(eligible=True)
        self.assertGreater(out.policy_score, 0.0)


# ---------------------------------------------------------------------------
# 6. TestRoutePreferenceField
# ---------------------------------------------------------------------------


class TestRoutePreferenceField(unittest.TestCase):
    def test_direct_ws_route_preference(self):
        rs = _make_readiness(effective_path="direct_ws")
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.route_preference, "direct_ws")

    def test_relay_route_preference(self):
        rs = _make_readiness(effective_path="relay")
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.route_preference, "relay")

    def test_no_transport_route_preference_none(self):
        rs = _make_readiness(effective_path="none", transport_present=False,
                              transport_usable=False, device_routable=False)
        vr = _make_validation(valid=False)
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.route_preference, "none")


# ---------------------------------------------------------------------------
# 7. TestLiveRouteTruthInOutput
# ---------------------------------------------------------------------------


class TestLiveRouteTruthInOutput(unittest.TestCase):
    def test_transport_present_propagated(self):
        rs = _make_readiness(transport_present=True)
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertTrue(out.transport_present)

    def test_transport_usable_propagated(self):
        rs = _make_readiness(transport_usable=True)
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertTrue(out.transport_usable)

    def test_device_routable_propagated(self):
        rs = _make_readiness(device_routable=True)
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertTrue(out.device_routable)

    def test_effective_path_propagated(self):
        rs = _make_readiness(effective_path="ucm")
        vr = _make_validation()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.effective_path, "ucm")


# ---------------------------------------------------------------------------
# 8. TestParticipationEnrichDoesNotOverride
# ---------------------------------------------------------------------------


class TestParticipationEnrichDoesNotOverride(unittest.TestCase):
    def test_participation_in_sources_but_not_overriding_transport(self):
        rs = _make_readiness(transport_present=False, transport_usable=False,
                              device_routable=False, effective_path="none")
        ps = _make_participation(orchestration_eligible=True)
        vr = _make_validation(valid=False)
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=ps), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        # participation present in sources
        self.assertIn("participation", out.sources)
        # transport fields still come from readiness (not participation)
        self.assertFalse(out.transport_present)
        self.assertFalse(out.transport_usable)
        self.assertFalse(out.device_routable)


# ---------------------------------------------------------------------------
# 9. TestEmptyDeviceId
# ---------------------------------------------------------------------------


class TestEmptyDeviceId(unittest.TestCase):
    def test_empty_string_device_id(self):
        out = evaluate_policy_convergence("")
        self.assertFalse(out.eligibility)
        self.assertIn("empty-device-id", out.reasons)

    def test_whitespace_device_id(self):
        out = evaluate_policy_convergence("   ")
        self.assertFalse(out.eligibility)
        self.assertIn("empty-device-id", out.reasons)

    def test_empty_device_id_score_zero(self):
        out = evaluate_policy_convergence("")
        self.assertEqual(out.policy_score, 0.0)


# ---------------------------------------------------------------------------
# 10. TestLayerDegradation
# ---------------------------------------------------------------------------


class TestLayerDegradation(unittest.TestCase):
    def test_readiness_unavailable_degrades_gracefully(self):
        vr = _make_validation(valid=False)
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=None), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=vr):
            out = evaluate_policy_convergence("dev1")
        self.assertFalse(out.eligibility)
        self.assertIn("readiness-unavailable", out.reasons)

    def test_validation_unavailable_degrades_gracefully(self):
        rs = _make_readiness()
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=rs), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=None):
            out = evaluate_policy_convergence("dev1")
        self.assertFalse(out.eligibility)
        self.assertIn("validation-unavailable", out.reasons)

    def test_all_layers_unavailable_returns_ineligible(self):
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=None), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=None):
            out = evaluate_policy_convergence("dev1")
        self.assertFalse(out.eligibility)
        self.assertEqual(out.policy_score, 0.0)

    def test_output_always_has_contract_version(self):
        with patch("core.admissibility_policy_convergence._get_readiness", return_value=None), \
             patch("core.admissibility_policy_convergence._get_participation", return_value=None), \
             patch("core.admissibility_policy_convergence._get_validation", return_value=None):
            out = evaluate_policy_convergence("dev1")
        self.assertEqual(out.contract_version, POLICY_OUTPUT_CONTRACT_VERSION)


if __name__ == "__main__":
    unittest.main()
