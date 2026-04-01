"""
tests/test_target_device_validator.py
======================================
Focused tests for ``core.target_device_validator`` — the canonical
target-device validation layer (PR-5 device validator).

Coverage:
  - Authority sentinel is importable and non-empty.
  - TargetDeviceValidationResult model serialises correctly via to_dict().
  - Registered and ready device validates successfully (valid=True).
  - Missing / unknown device returns valid=False with clear reasons.
  - Capability requirement mismatch returns valid=False.
  - Missing capability subsystem degrades gracefully without crashing.
  - Orchestration-required validation uses participation readiness when available.
  - Orchestration-required validation degrades when participation unavailable.
  - Empty device_id handled gracefully.
  - validate_target_device never raises regardless of subsystem state.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.target_device_validator import (
    TargetDeviceValidationResult,
    validate_target_device,
    TARGET_DEVICE_VALIDATOR_AUTHORITY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness_summary(
    device_id: str,
    registered: bool = True,
    online: bool = True,
    connected: bool = True,
    routable: bool = True,
) -> MagicMock:
    """Return a mock DeviceReadinessSummary."""
    rs = MagicMock()
    rs.device_id = device_id
    rs.registered = registered
    rs.online = online
    rs.connected = connected
    rs.routable = routable
    rs.to_dict.return_value = {
        "device_id": device_id,
        "registered": registered,
        "online": online,
        "connected": connected,
        "routable": routable,
    }
    return rs


def _make_participation_summary(
    device_id: str,
    orchestration_eligible: bool = True,
) -> MagicMock:
    """Return a mock ParticipationSummary."""
    ps = MagicMock()
    ps.device_id = device_id
    ps.orchestration_eligible = orchestration_eligible
    ps.to_dict.return_value = {
        "device_id": device_id,
        "orchestration_eligible": orchestration_eligible,
    }
    return ps


def _make_udm_device(device_id: str, capabilities: list) -> MagicMock:
    """Return a minimal mock UDM device."""
    d = MagicMock()
    d.device_id = device_id
    d.capabilities = capabilities
    return d


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------


class TestAuthoritySentinel(unittest.TestCase):
    def test_sentinel_importable(self):
        self.assertIsInstance(TARGET_DEVICE_VALIDATOR_AUTHORITY, str)

    def test_sentinel_non_empty(self):
        self.assertTrue(TARGET_DEVICE_VALIDATOR_AUTHORITY)

    def test_sentinel_contains_v2(self):
        self.assertIn("V2", TARGET_DEVICE_VALIDATOR_AUTHORITY)

    def test_chain_position_is_3(self):
        from core.target_device_validator import TARGET_DEVICE_VALIDATOR_CHAIN_POSITION
        self.assertEqual(TARGET_DEVICE_VALIDATOR_CHAIN_POSITION, 3)


# ---------------------------------------------------------------------------
# TargetDeviceValidationResult model
# ---------------------------------------------------------------------------


class TestTargetDeviceValidationResultModel(unittest.TestCase):
    def test_default_values(self):
        r = TargetDeviceValidationResult(device_id="d1")
        self.assertEqual(r.device_id, "d1")
        self.assertFalse(r.valid)
        self.assertFalse(r.registered)
        self.assertFalse(r.ready)
        self.assertFalse(r.capability_match)
        self.assertFalse(r.orchestration_eligible)
        self.assertEqual(r.reasons, [])
        self.assertEqual(r.sources, {})

    def test_to_dict_keys(self):
        r = TargetDeviceValidationResult(device_id="d1")
        d = r.to_dict()
        for key in (
            "device_id", "valid", "registered", "ready",
            "capability_match", "orchestration_eligible",
            "reasons", "sources",
        ):
            self.assertIn(key, d)

    def test_to_dict_reflects_field_values(self):
        r = TargetDeviceValidationResult(
            device_id="dev-x",
            valid=True,
            registered=True,
            ready=True,
            capability_match=True,
            orchestration_eligible=True,
            reasons=["ok"],
            sources={"src": "test"},
        )
        d = r.to_dict()
        self.assertEqual(d["device_id"], "dev-x")
        self.assertTrue(d["valid"])
        self.assertEqual(d["reasons"], ["ok"])
        self.assertEqual(d["sources"], {"src": "test"})

    def test_to_dict_copies_mutable_fields(self):
        """Mutations to the dict must not affect the original result."""
        r = TargetDeviceValidationResult(device_id="d1", reasons=["a"])
        d = r.to_dict()
        d["reasons"].append("b")
        self.assertEqual(r.reasons, ["a"])


# ---------------------------------------------------------------------------
# Registered and ready device validates successfully
# ---------------------------------------------------------------------------


class TestRegisteredReadyDevice(unittest.TestCase):
    def _valid_readiness(self, device_id: str) -> MagicMock:
        return _make_readiness_summary(device_id)

    def test_valid_device_returns_valid_true(self):
        rs = self._valid_readiness("dev-001")
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": rs.to_dict()}, [])):
            result = validate_target_device("dev-001")
        self.assertTrue(result.valid)
        self.assertTrue(result.registered)
        self.assertTrue(result.ready)
        self.assertTrue(result.capability_match)
        self.assertTrue(result.orchestration_eligible)

    def test_valid_device_no_reasons_for_failure(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("dev-001")
        # No device-not-* reasons expected
        failure_reasons = [r for r in result.reasons if r.startswith("device-not-")]
        self.assertEqual(failure_reasons, [])

    def test_returns_device_id_correctly(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("my-device-123")
        self.assertEqual(result.device_id, "my-device-123")


# ---------------------------------------------------------------------------
# Missing / unknown device returns invalid with clear reasons
# ---------------------------------------------------------------------------


class TestMissingDevice(unittest.TestCase):
    def test_unregistered_device_returns_valid_false(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, [])):
            result = validate_target_device("ghost-device")
        self.assertFalse(result.valid)
        self.assertFalse(result.registered)

    def test_unregistered_device_has_not_registered_reason(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, [])):
            result = validate_target_device("ghost-device")
        self.assertIn("not-registered", result.reasons)

    def test_registered_but_not_ready_returns_valid_false(self):
        # registered=True, ready=False
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, False, {}, [])):
            result = validate_target_device("offline-device")
        self.assertFalse(result.valid)
        self.assertTrue(result.registered)
        self.assertFalse(result.ready)

    def test_registered_but_not_ready_has_not_ready_reason(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, False, {}, [])):
            result = validate_target_device("offline-device")
        self.assertIn("not-ready", result.reasons)

    def test_readiness_module_unavailable_returns_valid_false(self):
        """When readiness module is unavailable, result is not valid."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, ["readiness-module-unavailable"])):
            result = validate_target_device("dev-x")
        self.assertFalse(result.valid)
        self.assertIn("readiness-module-unavailable", result.reasons)


# ---------------------------------------------------------------------------
# Capability requirement mismatch returns invalid
# ---------------------------------------------------------------------------


class TestCapabilityMismatch(unittest.TestCase):
    def test_missing_capability_returns_valid_false(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(False, {"device_capabilities": ["screen", "touch"],
                                      "required": ["camera"]},
                              ["missing-capabilities:camera"]),
            ):
                result = validate_target_device(
                    "dev-cap", required_capabilities=["camera"]
                )
        self.assertFalse(result.valid)
        self.assertFalse(result.capability_match)

    def test_missing_capability_reason_lists_missing_cap(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(False, {}, ["missing-capabilities:camera,gps"]),
            ):
                result = validate_target_device(
                    "dev-cap", required_capabilities=["camera", "gps"]
                )
        missing_reason = next(
            (r for r in result.reasons if r.startswith("missing-capabilities")), None
        )
        self.assertIsNotNone(missing_reason)

    def test_matching_capabilities_returns_valid_true(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(True, {"device_capabilities": ["screen", "touch", "camera"],
                                     "required": ["camera"]}, []),
            ):
                result = validate_target_device(
                    "dev-cap", required_capabilities=["camera"]
                )
        self.assertTrue(result.valid)
        self.assertTrue(result.capability_match)

    def test_no_required_capabilities_skips_check(self):
        """When required_capabilities is None, capability check passes trivially."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("dev-x", required_capabilities=None)
        self.assertTrue(result.capability_match)
        self.assertTrue(result.valid)

    def test_empty_required_capabilities_passes(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("dev-x", required_capabilities=[])
        self.assertTrue(result.capability_match)
        self.assertTrue(result.valid)


# ---------------------------------------------------------------------------
# Missing capability subsystem degrades gracefully without crashing
# ---------------------------------------------------------------------------


class TestCapabilitySubsystemDegradation(unittest.TestCase):
    def test_udm_import_error_does_not_crash(self):
        """ImportError from UDM must not raise; capability_match degrades to True."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(True, {}, ["capability-check-degraded:udm-import-error"]),
            ):
                result = validate_target_device(
                    "dev-x", required_capabilities=["camera"]
                )
        self.assertIsNotNone(result)

    def test_udm_runtime_error_records_reason_no_crash(self):
        """RuntimeError from UDM check records reason but does not crash."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(True, {}, ["capability-check-degraded:RuntimeError boom"]),
            ):
                result = validate_target_device(
                    "dev-x", required_capabilities=["camera"]
                )
        self.assertIsNotNone(result)
        # Should contain a degraded reason
        degraded_reason = next(
            (r for r in result.reasons if r.startswith("capability-check-degraded:")), None
        )
        self.assertIsNotNone(degraded_reason)

    def test_udm_returns_none_skips_cap_check(self):
        """When UDM returns None, capability check is skipped with a reason."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_capabilities",
                return_value=(True, {}, ["capability-check-skipped:udm-returned-none"]),
            ):
                result = validate_target_device(
                    "dev-x", required_capabilities=["camera"]
                )
        self.assertIsNotNone(result)
        # Should have a skip reason but not crash
        skip_reason = next(
            (r for r in result.reasons if r.startswith("capability-check-skipped:")), None
        )
        self.assertIsNotNone(skip_reason)


# ---------------------------------------------------------------------------
# Orchestration-required validation
# ---------------------------------------------------------------------------


class TestOrchestrationRequiredValidation(unittest.TestCase):
    def test_orchestration_eligible_passes_when_required(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(True, {"participation": {"orchestration_eligible": True}}, []),
            ):
                result = validate_target_device(
                    "dev-orch", require_orchestration_eligible=True
                )
        self.assertTrue(result.valid)
        self.assertTrue(result.orchestration_eligible)

    def test_orchestration_not_eligible_returns_invalid(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["not-eligible"]),
            ):
                result = validate_target_device(
                    "dev-orch", require_orchestration_eligible=True
                )
        self.assertFalse(result.valid)
        self.assertFalse(result.orchestration_eligible)
        self.assertIn("not-eligible", result.reasons)

    def test_orchestration_not_required_defaults_eligible(self):
        """When not required, orchestration_eligible is True by default."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("dev-x", require_orchestration_eligible=False)
        self.assertTrue(result.orchestration_eligible)

    def test_orchestration_module_unavailable_degrades_gracefully(self):
        """ImportError from device_participation must not crash."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["orchestration-check-unavailable:import-error"]),
            ):
                result = validate_target_device(
                    "dev-x", require_orchestration_eligible=True
                )
        self.assertIsNotNone(result)
        # Should not raise and should note degradation
        orch_reason = next(
            (r for r in result.reasons
             if r.startswith("orchestration-check-unavailable:")
             or r.startswith("orchestration-check-error:")),
            None,
        )
        self.assertIsNotNone(orch_reason)

    def test_orchestration_participation_error_degrades_gracefully(self):
        """RuntimeError from participation check must not crash."""
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            with patch(
                "core.target_device_validator._check_orchestration",
                return_value=(False, {}, ["orchestration-check-error:RuntimeError boom"]),
            ):
                result = validate_target_device(
                    "dev-x", require_orchestration_eligible=True
                )
        self.assertIsNotNone(result)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):
    def test_empty_device_id_returns_invalid(self):
        result = validate_target_device("")
        self.assertFalse(result.valid)
        self.assertIn("empty-device-id", result.reasons)

    def test_whitespace_device_id_returns_invalid(self):
        result = validate_target_device("   ")
        self.assertFalse(result.valid)
        self.assertIn("empty-device-id", result.reasons)

    def test_validate_never_raises_on_full_subsystem_failure(self):
        """validate_target_device must never raise even if all subsystems fail."""
        with patch(
            "core.target_device_validator._check_readiness",
            return_value=(False, False, {}, ["readiness-unexpected-error:total failure"]),
        ):
            try:
                result = validate_target_device("dev-x")
                self.assertFalse(result.valid)
            except Exception:
                self.fail("validate_target_device raised unexpectedly")

    def test_result_device_id_preserved(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, [])):
            result = validate_target_device("specific-id-xyz")
        self.assertEqual(result.device_id, "specific-id-xyz")

    def test_sources_populated_from_readiness(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {"readiness": {"ok": True}}, [])):
            result = validate_target_device("dev-x")
        self.assertIn("readiness", result.sources)

    def test_to_dict_round_trip(self):
        with patch("core.target_device_validator._check_readiness",
                   return_value=(True, True, {}, [])):
            result = validate_target_device("dev-x")
        d = result.to_dict()
        self.assertEqual(d["device_id"], "dev-x")
        self.assertIsInstance(d["reasons"], list)
        self.assertIsInstance(d["sources"], dict)


# ---------------------------------------------------------------------------
# Integration: validate via real device_readiness module (smoke test)
# ---------------------------------------------------------------------------


class TestIntegrationWithDeviceReadiness(unittest.TestCase):
    """Smoke tests that exercise the real device_readiness integration path."""

    def test_unknown_device_via_readiness_module(self):
        """Real readiness module call for an unknown device should return not registered."""
        # No subsystems available in test environment → registered=False
        result = validate_target_device("nonexistent-device-abc123")
        self.assertFalse(result.registered)
        self.assertFalse(result.valid)

    def test_result_is_always_returned(self):
        """validate_target_device always returns a TargetDeviceValidationResult."""
        result = validate_target_device("any-device")
        self.assertIsInstance(result, TargetDeviceValidationResult)


if __name__ == "__main__":
    unittest.main()
