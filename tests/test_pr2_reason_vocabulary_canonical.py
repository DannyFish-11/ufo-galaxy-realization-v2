#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr2_reason_vocabulary_canonical.py
==============================================
PR-2 — Canonical Message Interop: Reason Vocabulary Tests.

Validates that:
 1.  REASON_NOT_REGISTERED importable from core.message_interop.
 2.  REASON_NOT_READY importable from core.message_interop.
 3.  REASON_NO_ROUTE importable from core.message_interop.
 4.  REASON_NOT_ELIGIBLE importable from core.message_interop.
 5.  REASON_CAPABILITY_MISMATCH importable from core.message_interop.
 6.  REASON_READINESS_UNAVAILABLE importable from core.message_interop.
 7.  REASON_PARTICIPATION_UNAVAILABLE importable from core.message_interop.
 8.  REASON_NOT_REGISTERED == 'not-registered'.
 9.  REASON_NOT_READY == 'not-ready'.
10.  REASON_NO_ROUTE == 'no-route'.
11.  REASON_NOT_ELIGIBLE == 'not-eligible'.
12.  REASON_CAPABILITY_MISMATCH == 'capability-mismatch'.
13.  REASON_READINESS_UNAVAILABLE == 'readiness-unavailable'.
14.  REASON_PARTICIPATION_UNAVAILABLE == 'participation-unavailable'.
15.  Reasons from core.message_interop are identical to those in admissibility_chain.
16.  target_device_validator uses 'not-registered' for unknown device.
17.  target_device_validator uses 'not-ready' for registered but unroutable device.
18.  target_device_validator uses 'capability-mismatch' for capability failure.
19.  target_device_validator uses 'not-eligible' for ineligible orchestration.
20.  device_participation uses 'not-registered' reason string.
21.  device_participation uses 'no-route' reason string.
22.  device_participation uses 'readiness-unavailable' reason string.
23.  No legacy 'orchestration-not-eligible' reason in target_device_validator source.
24.  All canonical reasons are non-empty hyphenated strings.
25.  REASON_* constants are re-exported in core.message_interop.__all__.
"""

from __future__ import annotations

import inspect
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestReasonVocabularyImports(unittest.TestCase):
    """Tests 1–7: Reason constants importable from message_interop."""

    def test_01_reason_not_registered_importable(self):
        from core.message_interop import REASON_NOT_REGISTERED
        self.assertIsNotNone(REASON_NOT_REGISTERED)

    def test_02_reason_not_ready_importable(self):
        from core.message_interop import REASON_NOT_READY
        self.assertIsNotNone(REASON_NOT_READY)

    def test_03_reason_no_route_importable(self):
        from core.message_interop import REASON_NO_ROUTE
        self.assertIsNotNone(REASON_NO_ROUTE)

    def test_04_reason_not_eligible_importable(self):
        from core.message_interop import REASON_NOT_ELIGIBLE
        self.assertIsNotNone(REASON_NOT_ELIGIBLE)

    def test_05_reason_capability_mismatch_importable(self):
        from core.message_interop import REASON_CAPABILITY_MISMATCH
        self.assertIsNotNone(REASON_CAPABILITY_MISMATCH)

    def test_06_reason_readiness_unavailable_importable(self):
        from core.message_interop import REASON_READINESS_UNAVAILABLE
        self.assertIsNotNone(REASON_READINESS_UNAVAILABLE)

    def test_07_reason_participation_unavailable_importable(self):
        from core.message_interop import REASON_PARTICIPATION_UNAVAILABLE
        self.assertIsNotNone(REASON_PARTICIPATION_UNAVAILABLE)


class TestReasonVocabularyValues(unittest.TestCase):
    """Tests 8–14: Canonical reason string values."""

    def test_08_not_registered_value(self):
        from core.message_interop import REASON_NOT_REGISTERED
        self.assertEqual(REASON_NOT_REGISTERED, "not-registered")

    def test_09_not_ready_value(self):
        from core.message_interop import REASON_NOT_READY
        self.assertEqual(REASON_NOT_READY, "not-ready")

    def test_10_no_route_value(self):
        from core.message_interop import REASON_NO_ROUTE
        self.assertEqual(REASON_NO_ROUTE, "no-route")

    def test_11_not_eligible_value(self):
        from core.message_interop import REASON_NOT_ELIGIBLE
        self.assertEqual(REASON_NOT_ELIGIBLE, "not-eligible")

    def test_12_capability_mismatch_value(self):
        from core.message_interop import REASON_CAPABILITY_MISMATCH
        self.assertEqual(REASON_CAPABILITY_MISMATCH, "capability-mismatch")

    def test_13_readiness_unavailable_value(self):
        from core.message_interop import REASON_READINESS_UNAVAILABLE
        self.assertEqual(REASON_READINESS_UNAVAILABLE, "readiness-unavailable")

    def test_14_participation_unavailable_value(self):
        from core.message_interop import REASON_PARTICIPATION_UNAVAILABLE
        self.assertEqual(REASON_PARTICIPATION_UNAVAILABLE, "participation-unavailable")


class TestReasonVocabularyConsistency(unittest.TestCase):
    """Tests 15, 23–25: Cross-module vocabulary consistency."""

    def test_15_reasons_identical_to_admissibility_chain(self):
        """message_interop reason values match admissibility_chain."""
        try:
            from core.admissibility_chain import (
                REASON_NOT_REGISTERED as AC_NR,
                REASON_NOT_READY as AC_NRY,
                REASON_NO_ROUTE as AC_NO,
                REASON_NOT_ELIGIBLE as AC_NE,
                REASON_CAPABILITY_MISMATCH as AC_CM,
                REASON_READINESS_UNAVAILABLE as AC_RU,
                REASON_PARTICIPATION_UNAVAILABLE as AC_PU,
            )
            from core.message_interop import (
                REASON_NOT_REGISTERED,
                REASON_NOT_READY,
                REASON_NO_ROUTE,
                REASON_NOT_ELIGIBLE,
                REASON_CAPABILITY_MISMATCH,
                REASON_READINESS_UNAVAILABLE,
                REASON_PARTICIPATION_UNAVAILABLE,
            )
            self.assertEqual(REASON_NOT_REGISTERED, AC_NR)
            self.assertEqual(REASON_NOT_READY, AC_NRY)
            self.assertEqual(REASON_NO_ROUTE, AC_NO)
            self.assertEqual(REASON_NOT_ELIGIBLE, AC_NE)
            self.assertEqual(REASON_CAPABILITY_MISMATCH, AC_CM)
            self.assertEqual(REASON_READINESS_UNAVAILABLE, AC_RU)
            self.assertEqual(REASON_PARTICIPATION_UNAVAILABLE, AC_PU)
        except ImportError:
            self.skipTest("admissibility_chain not available")

    def test_23_no_legacy_orchestration_not_eligible_in_validator(self):
        """target_device_validator must not produce 'orchestration-not-eligible'."""
        import core.target_device_validator as m
        src = inspect.getsource(m)
        self.assertNotIn("orchestration-not-eligible", src)

    def test_24_all_canonical_reasons_are_hyphenated_non_empty(self):
        from core.message_interop import (
            REASON_NOT_REGISTERED,
            REASON_NOT_READY,
            REASON_NO_ROUTE,
            REASON_NOT_ELIGIBLE,
            REASON_CAPABILITY_MISMATCH,
            REASON_READINESS_UNAVAILABLE,
            REASON_PARTICIPATION_UNAVAILABLE,
        )
        for r in [
            REASON_NOT_REGISTERED, REASON_NOT_READY, REASON_NO_ROUTE,
            REASON_NOT_ELIGIBLE, REASON_CAPABILITY_MISMATCH,
            REASON_READINESS_UNAVAILABLE, REASON_PARTICIPATION_UNAVAILABLE,
        ]:
            self.assertTrue(len(r) > 0, f"empty reason: {r!r}")
            # Canonical format uses hyphens (not underscores as primary separator)
            self.assertIn("-", r, f"reason not hyphenated: {r!r}")
            # Must be lowercase only (no uppercase)
            self.assertEqual(r, r.lower(), f"reason contains uppercase: {r!r}")
            # Must not contain spaces
            self.assertNotIn(" ", r, f"reason contains space: {r!r}")

    def test_25_reasons_in_all(self):
        import core.message_interop as m
        all_exports = m.__all__
        for name in [
            "REASON_NOT_REGISTERED", "REASON_NOT_READY", "REASON_NO_ROUTE",
            "REASON_NOT_ELIGIBLE", "REASON_CAPABILITY_MISMATCH",
            "REASON_READINESS_UNAVAILABLE", "REASON_PARTICIPATION_UNAVAILABLE",
        ]:
            self.assertIn(name, all_exports, f"{name} not in __all__")


class TestConsumerReasonUsage(unittest.TestCase):
    """Tests 16–22: Consumer modules emit canonical reason strings."""

    def _run_validator(self, device_id, readiness_kwargs=None, cap_kwargs=None, orch_kwargs=None):
        """Run validate_target_device with mocked subsystems."""
        from unittest.mock import patch, MagicMock
        from core.target_device_validator import validate_target_device

        mock_rs = MagicMock()
        for k, v in (readiness_kwargs or {}).items():
            setattr(mock_rs, k, v)
        mock_rs.to_dict = lambda: {}

        with patch("core.target_device_validator._check_readiness") as mock_readiness:
            with patch("core.target_device_validator._check_capabilities") as mock_caps:
                with patch("core.target_device_validator._check_orchestration") as mock_orch:
                    registered = readiness_kwargs.get("registered", False) if readiness_kwargs else False
                    ready = readiness_kwargs.get("ready", False) if readiness_kwargs else False
                    mock_readiness.return_value = (registered, ready, {}, [])

                    cap_ok = cap_kwargs.get("ok", True) if cap_kwargs else True
                    mock_caps.return_value = (cap_ok, {}, [] if cap_ok else ["capability-mismatch:missing=x"])

                    orch_ok = orch_kwargs.get("ok", True) if orch_kwargs else True
                    mock_orch.return_value = (orch_ok, {}, [] if orch_ok else ["not-eligible"])

                    return validate_target_device(
                        device_id,
                        required_capabilities=cap_kwargs.get("required", []) if cap_kwargs else [],
                        require_orchestration_eligible=bool(orch_kwargs) if orch_kwargs else False,
                    )

    def test_16_validator_not_registered_reason(self):
        result = self._run_validator("unknown_dev", readiness_kwargs={"registered": False, "ready": False})
        self.assertIn("not-registered", result.reasons)

    def test_17_validator_not_ready_reason(self):
        result = self._run_validator("known_dev", readiness_kwargs={"registered": True, "ready": False})
        self.assertIn("not-ready", result.reasons)

    def test_18_validator_capability_mismatch_reason(self):
        result = self._run_validator(
            "dev_cap",
            readiness_kwargs={"registered": True, "ready": True},
            cap_kwargs={"ok": False, "required": ["screen"]},
        )
        any_cap_mismatch = any("capability-mismatch" in r for r in result.reasons)
        self.assertTrue(any_cap_mismatch)

    def test_19_validator_not_eligible_reason(self):
        result = self._run_validator(
            "dev_orch",
            readiness_kwargs={"registered": True, "ready": True},
            orch_kwargs={"ok": False},
        )
        any_not_eligible = any("not-eligible" in r for r in result.reasons)
        self.assertTrue(any_not_eligible)

    def test_20_participation_not_registered_in_source(self):
        """device_participation source contains 'not-registered' reason string."""
        import core.device_participation as m
        src = inspect.getsource(m)
        self.assertIn('"not-registered"', src)

    def test_21_participation_no_route_in_source(self):
        """device_participation source contains 'no-route' reason string."""
        import core.device_participation as m
        src = inspect.getsource(m)
        self.assertIn('"no-route"', src)

    def test_22_participation_readiness_unavailable_in_source(self):
        """device_participation source contains 'readiness-unavailable'."""
        import core.device_participation as m
        src = inspect.getsource(m)
        self.assertIn('"readiness-unavailable"', src)


if __name__ == "__main__":
    unittest.main()
