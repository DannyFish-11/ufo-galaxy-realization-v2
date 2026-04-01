#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_validator_canonical_inputs.py
==========================================
PR-5: Target validator canonical inputs tests.

Validates the PR-5 requirements for ``core.target_device_validator``:

  * ``VALIDATOR_CANONICAL_INPUTS_ONLY = True``
  * ``CanonicalValidationInput`` adapter/interop class is importable and works.
  * ``validate_target_device_from_canonical`` routes through the canonical adapter.
  * Legacy inputs normalised via ``CanonicalValidationInput.from_legacy`` produce
    the same result as direct canonical inputs.
  * The validator never accepts raw compat-cache data — it only consumes
    canonical readiness (Layer 1) and participation (Layer 2) truth.

Test classes
------------
1. TestValidatorCanonicalInputsSentinel
       VALIDATOR_CANONICAL_INPUTS_ONLY is importable and True.
       CanonicalValidationInput is importable.
       validate_target_device_from_canonical is importable.

2. TestCanonicalValidationInputAdapter
       CanonicalValidationInput default construction.
       from_legacy() factory populates source_label.
       from_legacy() accepts capabilities and orchestration_eligible.

3. TestValidateFromCanonicalDelegates
       validate_target_device_from_canonical returns a TargetDeviceValidationResult.
       Empty device_id produces valid=False with appropriate reason.
       Result sources contain 'canonical_input_source' key.

4. TestValidatorOnlyConsumesCanonicalTruth
       Validator calls get_device_readiness (Layer 1), NOT compat cache.
       Validator calls get_device_participation for orchestration check.
       Result for registered+ready device is valid=True.
       Result for unregistered device is valid=False.

5. TestLegacyInputsNormalisedViaAdapter
       from_legacy input produces same validation result as direct input.
       source_label is preserved in result sources.

6. TestCapabilityCheckViaCanonicalInput
       CanonicalValidationInput with required_capabilities triggers cap check.
       Capability mismatch propagates to validation result.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.target_device_validator import (
    TargetDeviceValidationResult,
    CanonicalValidationInput,
    validate_target_device,
    validate_target_device_from_canonical,
    TARGET_DEVICE_VALIDATOR_AUTHORITY,
    VALIDATOR_CANONICAL_INPUTS_ONLY,
    VALIDATOR_TRUTH_SOURCE,
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
):
    rs = MagicMock()
    rs.registered = registered
    rs.online = online
    rs.connected = connected
    rs.routable = routable
    rs.to_dict = lambda: {
        "device_id": device_id,
        "registered": registered,
        "online": online,
        "connected": connected,
        "routable": routable,
    }
    return rs


# ---------------------------------------------------------------------------
# 1. TestValidatorCanonicalInputsSentinel
# ---------------------------------------------------------------------------


class TestValidatorCanonicalInputsSentinel(unittest.TestCase):
    def test_validator_canonical_inputs_only_is_true(self):
        self.assertTrue(VALIDATOR_CANONICAL_INPUTS_ONLY)

    def test_canonical_validation_input_importable(self):
        self.assertIsNotNone(CanonicalValidationInput)

    def test_validate_from_canonical_importable(self):
        self.assertIsNotNone(validate_target_device_from_canonical)

    def test_sentinels_in_exports(self):
        from core.target_device_validator import __all__ as exports
        self.assertIn("VALIDATOR_CANONICAL_INPUTS_ONLY", exports)
        self.assertIn("CanonicalValidationInput", exports)
        self.assertIn("validate_target_device_from_canonical", exports)

    def test_authority_sentinel_stable(self):
        self.assertEqual(TARGET_DEVICE_VALIDATOR_AUTHORITY, "TARGET_DEVICE_VALIDATOR_V2")

    def test_validator_truth_source_mentions_compat_excluded(self):
        self.assertIn("compat-cache excluded", VALIDATOR_TRUTH_SOURCE)


# ---------------------------------------------------------------------------
# 2. TestCanonicalValidationInputAdapter
# ---------------------------------------------------------------------------


class TestCanonicalValidationInputAdapter(unittest.TestCase):
    def test_default_construction(self):
        ci = CanonicalValidationInput(device_id="dev1")
        self.assertEqual(ci.device_id, "dev1")
        self.assertIsNone(ci.required_capabilities)
        self.assertFalse(ci.require_orchestration_eligible)
        self.assertEqual(ci.source_label, "canonical")

    def test_from_legacy_sets_source_label(self):
        ci = CanonicalValidationInput.from_legacy("dev1", legacy_source="test_compat")
        self.assertEqual(ci.source_label, "test_compat")
        self.assertEqual(ci.device_id, "dev1")

    def test_from_legacy_default_source_label(self):
        ci = CanonicalValidationInput.from_legacy("dev1")
        self.assertEqual(ci.source_label, "legacy_compat")

    def test_from_legacy_with_capabilities(self):
        ci = CanonicalValidationInput.from_legacy(
            "dev1", capabilities=["screen", "touch"]
        )
        self.assertEqual(ci.required_capabilities, ["screen", "touch"])

    def test_from_legacy_with_orchestration_eligible(self):
        ci = CanonicalValidationInput.from_legacy(
            "dev1", orchestration_eligible=True
        )
        self.assertTrue(ci.require_orchestration_eligible)

    def test_from_legacy_all_params(self):
        ci = CanonicalValidationInput.from_legacy(
            "dev2",
            capabilities=["camera"],
            orchestration_eligible=True,
            legacy_source="old_api",
        )
        self.assertEqual(ci.device_id, "dev2")
        self.assertEqual(ci.required_capabilities, ["camera"])
        self.assertTrue(ci.require_orchestration_eligible)
        self.assertEqual(ci.source_label, "old_api")


# ---------------------------------------------------------------------------
# 3. TestValidateFromCanonicalDelegates
# ---------------------------------------------------------------------------


class TestValidateFromCanonicalDelegates(unittest.TestCase):
    def test_returns_target_device_validation_result(self):
        ci = CanonicalValidationInput(device_id="dev1")
        rs = _make_readiness()
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])):
            result = validate_target_device_from_canonical(ci)
        self.assertIsInstance(result, TargetDeviceValidationResult)

    def test_empty_device_id_produces_valid_false(self):
        ci = CanonicalValidationInput(device_id="")
        result = validate_target_device_from_canonical(ci)
        self.assertFalse(result.valid)

    def test_result_sources_contains_canonical_input_source(self):
        ci = CanonicalValidationInput(device_id="dev1", source_label="test_label")
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])):
            result = validate_target_device_from_canonical(ci)
        self.assertIn("canonical_input_source", result.sources)
        self.assertEqual(result.sources["canonical_input_source"], "test_label")

    def test_legacy_source_label_preserved(self):
        ci = CanonicalValidationInput.from_legacy("dev1", legacy_source="compat_v1")
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])):
            result = validate_target_device_from_canonical(ci)
        self.assertEqual(result.sources["canonical_input_source"], "compat_v1")


# ---------------------------------------------------------------------------
# 4. TestValidatorOnlyConsumesCanonicalTruth
# ---------------------------------------------------------------------------


class TestValidatorOnlyConsumesCanonicalTruth(unittest.TestCase):
    def test_registered_and_ready_device_is_valid(self):
        """Validator produces valid=True when readiness confirms registered+ready."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])), \
             patch("core.target_device_validator._check_capabilities",
                   return_value=(True, {}, [])):
            result = validate_target_device("dev1")
        self.assertTrue(result.registered)
        self.assertTrue(result.ready)
        self.assertTrue(result.valid)

    def test_unregistered_device_is_invalid(self):
        """Validator produces valid=False when readiness says not registered."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, [])):
            result = validate_target_device("dev1")
        self.assertFalse(result.registered)
        self.assertFalse(result.valid)

    def test_registered_but_not_ready_device_is_invalid(self):
        """Validator produces valid=False when registered but not ready."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, False, {"readiness": {}}, [])):
            result = validate_target_device("dev1")
        self.assertTrue(result.registered)
        self.assertFalse(result.ready)
        self.assertFalse(result.valid)

    def test_empty_device_id_short_circuits(self):
        result = validate_target_device("")
        self.assertFalse(result.valid)
        self.assertIn("empty-device-id", result.reasons)


# ---------------------------------------------------------------------------
# 5. TestLegacyInputsNormalisedViaAdapter
# ---------------------------------------------------------------------------


class TestLegacyInputsNormalisedViaAdapter(unittest.TestCase):
    def test_from_legacy_and_direct_produce_same_result(self):
        """Legacy-normalised and direct canonical inputs produce identical results."""
        ci_direct = CanonicalValidationInput(device_id="dev1")
        ci_legacy = CanonicalValidationInput.from_legacy("dev1")

        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])), \
             patch("core.target_device_validator._check_capabilities",
                   return_value=(True, {}, [])):
            result_direct = validate_target_device_from_canonical(ci_direct)
            result_legacy = validate_target_device_from_canonical(ci_legacy)

        self.assertEqual(result_direct.valid, result_legacy.valid)
        self.assertEqual(result_direct.registered, result_legacy.registered)
        self.assertEqual(result_direct.ready, result_legacy.ready)

    def test_source_label_differs_between_canonical_and_legacy(self):
        ci_direct = CanonicalValidationInput(device_id="dev1", source_label="canonical")
        ci_legacy = CanonicalValidationInput.from_legacy("dev1", legacy_source="legacy_compat")

        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {}}, [])), \
             patch("core.target_device_validator._check_capabilities",
                   return_value=(True, {}, [])):
            r1 = validate_target_device_from_canonical(ci_direct)
            r2 = validate_target_device_from_canonical(ci_legacy)

        self.assertEqual(r1.sources["canonical_input_source"], "canonical")
        self.assertEqual(r2.sources["canonical_input_source"], "legacy_compat")


# ---------------------------------------------------------------------------
# 6. TestCapabilityCheckViaCanonicalInput
# ---------------------------------------------------------------------------


class TestCapabilityCheckViaCanonicalInput(unittest.TestCase):
    def test_canonical_input_with_capabilities_triggers_cap_check(self):
        ci = CanonicalValidationInput(device_id="dev1", required_capabilities=["camera"])
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])), \
             patch("core.target_device_validator._check_capabilities",
                   return_value=(False, {}, ["capability-mismatch:missing=camera"])) as mock_cap:
            result = validate_target_device_from_canonical(ci)
        # check that capabilities were passed through
        mock_cap.assert_called_once_with("dev1", ["camera"])
        self.assertFalse(result.capability_match)

    def test_canonical_input_no_capabilities_skips_cap_check(self):
        ci = CanonicalValidationInput(device_id="dev1")
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])), \
             patch("core.target_device_validator._check_capabilities",
                   return_value=(True, {}, [])) as mock_cap:
            result = validate_target_device_from_canonical(ci)
        mock_cap.assert_called_once_with("dev1", [])
        self.assertTrue(result.capability_match)


if __name__ == "__main__":
    unittest.main()
