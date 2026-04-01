#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr6_admissibility_chain.py
========================================
Dedicated admissibility-chain tests (PR-6 follow-up, carried into PR-7).

Covers the three-layer chain:
  Layer 1 — Readiness   (core.device_readiness)
  Layer 2 — Participation  (core.device_participation)
  Layer 3 — Target Validation  (core.target_device_validator)

Test classes
------------
1. TestAdmissibilityChainSentinels
       Authority sentinels and layer constants are importable and stable.

2. TestCanonicalReasonConstants
       Canonical failure reason strings match their known values; callers can
       rely on them for pattern-matching without parsing free-form text.

3. TestReadinessLayer
       Layer-1 gate: readiness check returns correct registered/ready flags
       and canonical reasons for unregistered / not-ready devices.

4. TestParticipationLayer
       Layer-2 gate: participation builds on readiness; a device that is not
       Layer-1 ready is not participation-eligible; reason vocabulary uses
       REASON_NOT_ELIGIBLE.

5. TestTargetValidationLayer
       Layer-3 gate: target validation is the conjunction of Layer 1+2 + caps.
       Capability mismatch produces REASON_CAPABILITY_MISMATCH.
       Valid device with all checks passing produces valid=True.

6. TestChainSequencing
       Higher-layer checks must not bypass lower-layer authority.
       A Layer-2 not-eligible reason must propagate to the Layer-3 result.
       Layer-3 must not use shadow/legacy readiness strings.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# 1. TestAdmissibilityChainSentinels
# ---------------------------------------------------------------------------


class TestAdmissibilityChainSentinels(unittest.TestCase):
    """Sentinels and layer constants are importable and have expected values."""

    def test_chain_authority_importable(self):
        from core.admissibility_chain import ADMISSIBILITY_CHAIN_AUTHORITY
        self.assertIsNotNone(ADMISSIBILITY_CHAIN_AUTHORITY)

    def test_chain_authority_non_empty(self):
        from core.admissibility_chain import ADMISSIBILITY_CHAIN_AUTHORITY
        self.assertTrue(len(ADMISSIBILITY_CHAIN_AUTHORITY) > 0)

    def test_layer_readiness_is_1(self):
        from core.admissibility_chain import ADMISSIBILITY_LAYER_READINESS
        self.assertEqual(ADMISSIBILITY_LAYER_READINESS, 1)

    def test_layer_participation_is_2(self):
        from core.admissibility_chain import ADMISSIBILITY_LAYER_PARTICIPATION
        self.assertEqual(ADMISSIBILITY_LAYER_PARTICIPATION, 2)

    def test_layer_target_validation_is_3(self):
        from core.admissibility_chain import ADMISSIBILITY_LAYER_TARGET_VALIDATION
        self.assertEqual(ADMISSIBILITY_LAYER_TARGET_VALIDATION, 3)

    def test_layers_are_strictly_ordered(self):
        from core.admissibility_chain import (
            ADMISSIBILITY_LAYER_READINESS,
            ADMISSIBILITY_LAYER_PARTICIPATION,
            ADMISSIBILITY_LAYER_TARGET_VALIDATION,
        )
        self.assertLess(ADMISSIBILITY_LAYER_READINESS, ADMISSIBILITY_LAYER_PARTICIPATION)
        self.assertLess(ADMISSIBILITY_LAYER_PARTICIPATION, ADMISSIBILITY_LAYER_TARGET_VALIDATION)

    def test_target_validator_chain_position_matches_layer(self):
        """TargetDeviceValidator declares itself at the correct layer."""
        from core.admissibility_chain import ADMISSIBILITY_LAYER_TARGET_VALIDATION
        from core.target_device_validator import TARGET_DEVICE_VALIDATOR_CHAIN_POSITION
        self.assertEqual(
            TARGET_DEVICE_VALIDATOR_CHAIN_POSITION,
            ADMISSIBILITY_LAYER_TARGET_VALIDATION,
        )


# ---------------------------------------------------------------------------
# 2. TestCanonicalReasonConstants
# ---------------------------------------------------------------------------


class TestCanonicalReasonConstants(unittest.TestCase):
    """Canonical reason strings are stable and match their expected values."""

    def test_reason_not_registered(self):
        from core.admissibility_chain import REASON_NOT_REGISTERED
        self.assertEqual(REASON_NOT_REGISTERED, "not-registered")

    def test_reason_not_ready(self):
        from core.admissibility_chain import REASON_NOT_READY
        self.assertEqual(REASON_NOT_READY, "not-ready")

    def test_reason_not_eligible(self):
        from core.admissibility_chain import REASON_NOT_ELIGIBLE
        self.assertEqual(REASON_NOT_ELIGIBLE, "not-eligible")

    def test_reason_capability_mismatch(self):
        from core.admissibility_chain import REASON_CAPABILITY_MISMATCH
        self.assertEqual(REASON_CAPABILITY_MISMATCH, "capability-mismatch")

    def test_reason_no_route(self):
        from core.admissibility_chain import REASON_NO_ROUTE
        self.assertEqual(REASON_NO_ROUTE, "no-route")

    def test_reason_readiness_unavailable(self):
        from core.admissibility_chain import REASON_READINESS_UNAVAILABLE
        self.assertEqual(REASON_READINESS_UNAVAILABLE, "readiness-unavailable")

    def test_reason_participation_unavailable(self):
        from core.admissibility_chain import REASON_PARTICIPATION_UNAVAILABLE
        self.assertEqual(REASON_PARTICIPATION_UNAVAILABLE, "participation-unavailable")

    def test_legacy_reason_not_in_canonical_vocabulary(self):
        """'orchestration-not-eligible' must NOT appear in canonical constants."""
        import core.admissibility_chain as chain_mod
        constants = {
            k: v for k, v in vars(chain_mod).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        for name, value in constants.items():
            self.assertNotEqual(
                value, "orchestration-not-eligible",
                msg=(
                    f"{name}={value!r} uses legacy wording; "
                    "canonical reason is 'not-eligible'"
                ),
            )


# ---------------------------------------------------------------------------
# 3. TestReadinessLayer
# ---------------------------------------------------------------------------


class TestReadinessLayer(unittest.TestCase):
    """Layer-1: device_readiness gate produces correct flags and reasons."""

    def _make_readiness_summary(
        self, registered=True, online=True, connected=True, routable=True
    ):
        rs = MagicMock()
        rs.registered = registered
        rs.online = online
        rs.connected = connected
        rs.routable = routable
        rs.to_dict.return_value = {
            "registered": registered,
            "online": online,
            "connected": connected,
            "routable": routable,
        }
        return rs

    def test_registered_ready_device_passes_layer1(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {"readiness": {}}, []),
        ):
            result = validate_target_device("dev-ready")
        self.assertTrue(result.registered)
        self.assertTrue(result.ready)

    def test_unregistered_device_fails_layer1(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(False, False, {}, ["not-registered"]),
        ):
            result = validate_target_device("dev-unknown")
        self.assertFalse(result.valid)
        self.assertFalse(result.registered)
        self.assertIn("not-registered", result.reasons)

    def test_registered_but_not_ready_fails_layer1(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, False, {"readiness": {}}, ["not-ready"]),
        ):
            result = validate_target_device("dev-offline")
        self.assertFalse(result.valid)
        self.assertTrue(result.registered)
        self.assertFalse(result.ready)
        self.assertIn("not-ready", result.reasons)

    def test_readiness_unavailable_degrades_gracefully(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(False, False, {}, ["readiness-module-unavailable"]),
        ):
            result = validate_target_device("dev-x")
        self.assertFalse(result.valid)
        self.assertIsNotNone(result)  # must not raise


# ---------------------------------------------------------------------------
# 4. TestParticipationLayer
# ---------------------------------------------------------------------------


class TestParticipationLayer(unittest.TestCase):
    """Layer-2: participation gate builds on Layer-1 and uses canonical reasons."""

    def test_not_eligible_reason_uses_canonical_string(self):
        """When a device is not orchestration-eligible the reason must be
        canonical 'not-eligible', not legacy 'orchestration-not-eligible'."""
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["not-eligible"]),
            ):
                result = validate_target_device(
                    "dev-not-elig", require_orchestration_eligible=True
                )
        self.assertFalse(result.valid)
        self.assertFalse(result.orchestration_eligible)
        self.assertIn("not-eligible", result.reasons)

    def test_participation_unavailable_reason_propagates(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(
                    False, {},
                    ["orchestration-check-unavailable:import-error"],
                ),
            ):
                result = validate_target_device(
                    "dev-x", require_orchestration_eligible=True
                )
        self.assertFalse(result.valid)
        self.assertTrue(
            any(
                r.startswith("orchestration-check-unavailable:")
                or r.startswith("orchestration-check-error:")
                for r in result.reasons
            )
        )

    def test_not_required_orchestration_defaults_eligible(self):
        """When orchestration is not required, orchestration_eligible is True."""
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            result = validate_target_device("dev-ok", require_orchestration_eligible=False)
        self.assertTrue(result.orchestration_eligible)

    def test_participation_authority_sentinel(self):
        from core.device_participation import DEVICE_PARTICIPATION_AUTHORITY
        self.assertTrue(len(DEVICE_PARTICIPATION_AUTHORITY) > 0)
        self.assertIn("V2", DEVICE_PARTICIPATION_AUTHORITY)

    def test_participation_builds_on_readiness_flag(self):
        """PARTICIPATION_BUILDS_ON_READINESS must be True — Layer 2 consumes Layer 1."""
        from core.device_participation import PARTICIPATION_BUILDS_ON_READINESS
        self.assertTrue(PARTICIPATION_BUILDS_ON_READINESS)


# ---------------------------------------------------------------------------
# 5. TestTargetValidationLayer
# ---------------------------------------------------------------------------


class TestTargetValidationLayer(unittest.TestCase):
    """Layer-3: target validation is the conjunction of Layer 1+2 + capabilities."""

    def test_valid_device_with_all_checks_passes(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(True, {}, []),
            ):
                result = validate_target_device(
                    "dev-valid",
                    required_capabilities=["screen"],
                    require_orchestration_eligible=False,
                )
        self.assertTrue(result.valid)
        self.assertTrue(result.registered)
        self.assertTrue(result.ready)
        self.assertTrue(result.capability_match)

    def test_capability_mismatch_fails_layer3(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(False, {}, ["capability-mismatch:missing=camera"]),
            ):
                result = validate_target_device(
                    "dev-nocam", required_capabilities=["camera"]
                )
        self.assertFalse(result.valid)
        self.assertFalse(result.capability_match)
        self.assertTrue(
            any(r.startswith("capability-mismatch") for r in result.reasons)
        )

    def test_result_device_id_is_preserved(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            result = validate_target_device("dev-id-check")
        self.assertEqual(result.device_id, "dev-id-check")

    def test_target_validator_authority_sentinel(self):
        from core.target_device_validator import TARGET_DEVICE_VALIDATOR_AUTHORITY
        self.assertIn("V2", TARGET_DEVICE_VALIDATOR_AUTHORITY)

    def test_to_dict_includes_all_layers(self):
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {"readiness": {"registered": True}}, []),
        ):
            result = validate_target_device("dev-dict")
        d = result.to_dict()
        for key in ("device_id", "valid", "registered", "ready",
                    "capability_match", "orchestration_eligible", "reasons", "sources"):
            self.assertIn(key, d, msg=f"to_dict() missing key: {key}")


# ---------------------------------------------------------------------------
# 6. TestChainSequencing
# ---------------------------------------------------------------------------


class TestChainSequencing(unittest.TestCase):
    """Higher layers must not bypass lower-layer authority or reason vocabulary."""

    def test_layer2_not_eligible_propagates_to_layer3_result(self):
        """A Layer-2 'not-eligible' reason must appear in the Layer-3 result."""
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["not-eligible"]),
            ):
                result = validate_target_device(
                    "dev-seq", require_orchestration_eligible=True
                )
        self.assertIn("not-eligible", result.reasons)
        self.assertFalse(result.orchestration_eligible)

    def test_layer1_not_ready_produces_invalid_verdict(self):
        """A not-ready device must produce valid=False with 'not-ready' in reasons
        regardless of what higher-layer checks return."""
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, False, {}, ["not-ready"]),
        ):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(True, {}, []),
            ):
                result = validate_target_device(
                    "dev-notready", require_orchestration_eligible=True
                )

        # Overall verdict must be False because Layer 1 failed
        self.assertFalse(result.valid)
        self.assertFalse(result.ready)
        self.assertIn("not-ready", result.reasons)

    def test_legacy_reason_string_not_produced_by_layer3(self):
        """Layer-3 must not produce the legacy 'orchestration-not-eligible' reason."""
        from core.target_device_validator import validate_target_device
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(True, True, {}, []),
        ):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["not-eligible"]),
            ):
                result = validate_target_device(
                    "dev-legacy-check", require_orchestration_eligible=True
                )
        self.assertNotIn("orchestration-not-eligible", result.reasons)

    def test_admissibility_chain_authority_matches_module(self):
        """Chain authority sentinel is stable and identifies the canonical module."""
        from core.admissibility_chain import ADMISSIBILITY_CHAIN_AUTHORITY
        self.assertTrue(ADMISSIBILITY_CHAIN_AUTHORITY.startswith("ADMISSIBILITY_CHAIN"))

    def test_dispatch_spine_sentinels_importable(self):
        """PR-7 dispatch spine sentinels are importable from the canonical module."""
        from core.cross_device_execution_chain import (
            COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY,
            TASK_ENVELOPE_CANONICAL_CONTRACT,
        )
        self.assertIn("COMMAND_ROUTER_DISPATCH_SPINE", COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY)
        self.assertIn("TASK_ENVELOPE_CANONICAL_CONTRACT", TASK_ENVELOPE_CANONICAL_CONTRACT)

    def test_dispatch_spine_authority_also_on_command_router(self):
        """The dispatch spine sentinel is also declared on CommandRouter."""
        from core.command_router import COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY
        self.assertIn("COMMAND_ROUTER_DISPATCH_SPINE", COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY)


if __name__ == "__main__":
    unittest.main()
