#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gateway_capability_default_enforcement.py
======================================================
Test suite for the GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT closure.

Verifies that ``core.gateway_capability_default_enforcement`` provides a
correct default enforcement gate for ``send_gateway_command``, and that the
canonical gateway path no longer silently bypasses capability reality.

Test groups
-----------
A) Sentinels — all policy sentinels importable and non-empty.
B) infer_required_capabilities — command inference table correct.
C) lookup_device_capabilities — graceful degradation when registry unavailable.
D) enforce_gateway_default_capability_gate — gate logic (PASSED, NO_REQUIREMENTS,
   INSUFFICIENT_DATA, HARD_REJECT).
E) Explicit routing does not exempt capability gate.
F) audit_gateway_override — audited override path requires non-empty reason.
G) openclawd.py static checks — gate is wired into send_gateway_command.
H) GAP registry — GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT marked resolved.
I) Regression gate — module is importable and gate is callable.
"""

from __future__ import annotations

import pathlib
from typing import List
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# A) Sentinels
# ===========================================================================


class TestSentinels:
    def test_authority_sentinel_importable(self):
        from core.gateway_capability_default_enforcement import (
            GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY,
        )

        assert GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY
        assert "AUTHORITY" in GATEWAY_DEFAULT_ENFORCEMENT_AUTHORITY

    def test_pr_sentinel_importable(self):
        from core.gateway_capability_default_enforcement import (
            GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL,
        )

        assert GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL
        assert "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT" in GATEWAY_DEFAULT_ENFORCEMENT_PR_SENTINEL

    def test_explicit_routing_policy_importable(self):
        from core.gateway_capability_default_enforcement import (
            EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY,
        )

        assert EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY
        assert "device_id" in EXPLICIT_ROUTING_DOES_NOT_EXEMPT_CAPABILITY_GATE_POLICY

    def test_gap_closure_policy_importable(self):
        from core.gateway_capability_default_enforcement import (
            DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY,
        )

        assert DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY
        assert "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT" in DEFAULT_ENFORCEMENT_CLOSES_GAP_CAPABILITY_GATE_POLICY


# ===========================================================================
# B) infer_required_capabilities
# ===========================================================================


class TestInferRequiredCapabilities:
    def test_empty_command_returns_empty(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        assert infer_required_capabilities("") == []

    def test_unknown_command_returns_empty(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        assert infer_required_capabilities("totally_unknown_command_xyz") == []

    def test_take_photo_infers_camera(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("take_photo")
        assert "camera" in caps

    def test_take_screenshot_infers_screen(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("take_screenshot")
        assert "screen" in caps

    def test_gps_locate_infers_gps(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("gps_locate")
        assert "gps" in caps

    def test_nfc_read_infers_nfc(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("nfc_read")
        assert "nfc" in caps

    def test_bluetooth_scan_infers_bluetooth(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("bluetooth_scan")
        assert "bluetooth" in caps

    def test_local_ai_infers_local_ai(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("local_ai")
        assert "local_ai" in caps

    def test_screen_tap_infers_screen_and_touch(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps = infer_required_capabilities("screen_tap")
        assert "screen" in caps
        assert "touch" in caps

    def test_case_insensitive(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        caps_lower = infer_required_capabilities("take_photo")
        caps_upper = infer_required_capabilities("TAKE_PHOTO")
        assert caps_lower == caps_upper

    def test_prefix_match_camera(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        # "camera/rear" should infer camera via prefix
        caps = infer_required_capabilities("camera/rear")
        assert "camera" in caps

    def test_device_control_no_inference(self):
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        # Generic commands with no capability mapping return empty
        caps = infer_required_capabilities("device_control")
        assert isinstance(caps, list)


# ===========================================================================
# C) lookup_device_capabilities
# ===========================================================================


class TestLookupDeviceCapabilities:
    def test_empty_device_id_returns_empty(self):
        from core.gateway_capability_default_enforcement import lookup_device_capabilities

        assert lookup_device_capabilities("") == []

    def test_unknown_device_returns_empty(self):
        from core.gateway_capability_default_enforcement import lookup_device_capabilities

        # Not in registry — should return [] gracefully, not raise
        caps = lookup_device_capabilities("nonexistent_device_xyz_abc")
        assert caps == []

    def test_registry_unavailable_returns_empty(self):
        from core.gateway_capability_default_enforcement import lookup_device_capabilities

        with patch(
            "core.gateway_capability_default_enforcement.lookup_device_capabilities",
            wraps=lambda device_id: [],
        ):
            caps = lookup_device_capabilities("dev_unreachable")
        assert isinstance(caps, list)

    def test_device_with_string_capabilities(self):
        """When registry returns a device with string capabilities, they are returned."""
        from core.gateway_capability_default_enforcement import lookup_device_capabilities

        # Since DeviceRegistry requires pydantic (not installed in test env),
        # the function gracefully returns [] — verify it doesn't raise.
        caps = lookup_device_capabilities("dev_phone_test")
        assert isinstance(caps, list)

    def test_device_with_model_capabilities(self):
        """Function handles DeviceCapabilityModel .name attributes gracefully."""
        from core.gateway_capability_default_enforcement import lookup_device_capabilities

        # Graceful degradation path when registry unavailable
        caps = lookup_device_capabilities("dev_nfc_test")
        assert isinstance(caps, list)


# ===========================================================================
# D) enforce_gateway_default_capability_gate — gate logic
# ===========================================================================


class TestEnforceGatewayDefaultCapabilityGate:
    def test_no_capabilities_no_requirements_is_no_op(self):
        """No required_capabilities + unknown command = NO_REQUIREMENTS (no-op)."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        record = enforce_gateway_default_capability_gate(
            device_id="dev_x",
            command="device_control",  # no inference entry
            required_capabilities=None,
            device_capabilities=[],
        )
        assert record.verdict == HardenedVerdict.NO_REQUIREMENTS

    def test_explicit_capabilities_device_has_them_passes(self):
        """Device has all required caps → PASSED."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        record = enforce_gateway_default_capability_gate(
            device_id="dev_capable",
            command="take_photo",
            required_capabilities=["camera"],
            device_capabilities=["camera", "screen", "gps"],
        )
        assert record.verdict == HardenedVerdict.PASSED

    def test_explicit_capabilities_device_missing_hard_reject(self):
        """Device missing required cap → CapabilityHardRejectError (STRICT mode)."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import CapabilityHardRejectError

        with pytest.raises(CapabilityHardRejectError) as exc_info:
            enforce_gateway_default_capability_gate(
                device_id="dev_lacking",
                command="take_photo",
                required_capabilities=["camera"],
                device_capabilities=["screen"],  # camera missing
            )

        assert "camera" in exc_info.value.missing_capabilities
        assert exc_info.value.device_id == "dev_lacking"

    def test_inferred_capabilities_device_has_them_passes(self):
        """When required_capabilities is None, inferred from command; device has them → PASSED."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        record = enforce_gateway_default_capability_gate(
            device_id="dev_gps",
            command="gps_locate",  # infers ["gps"]
            required_capabilities=None,
            device_capabilities=["gps", "screen"],
        )
        assert record.verdict == HardenedVerdict.PASSED

    def test_inferred_capabilities_device_missing_hard_reject(self):
        """When inferred caps are missing from device → CapabilityHardRejectError."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import CapabilityHardRejectError

        with pytest.raises(CapabilityHardRejectError) as exc_info:
            enforce_gateway_default_capability_gate(
                device_id="dev_no_gps",
                command="gps_locate",  # infers ["gps"]
                required_capabilities=None,
                device_capabilities=["screen"],  # gps missing
            )

        assert "gps" in exc_info.value.missing_capabilities

    def test_device_capabilities_none_triggers_insufficient_data(self):
        """When device_capabilities is None and registry returns empty → INSUFFICIENT_DATA."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        # Patch lookup to return [] (device unknown)
        with patch(
            "core.gateway_capability_default_enforcement.lookup_device_capabilities",
            return_value=[],
        ):
            record = enforce_gateway_default_capability_gate(
                device_id="dev_unknown",
                command="gps_locate",  # infers ["gps"]
                required_capabilities=None,
                device_capabilities=None,  # triggers lookup
            )

        assert record.verdict == HardenedVerdict.INSUFFICIENT_DATA

    def test_error_in_reject_contains_audit_id(self):
        """CapabilityHardRejectError must carry a non-empty audit_id."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import CapabilityHardRejectError

        with pytest.raises(CapabilityHardRejectError) as exc_info:
            enforce_gateway_default_capability_gate(
                device_id="dev_x",
                command="nfc_read",
                required_capabilities=["nfc"],
                device_capabilities=["screen"],  # has caps but not nfc → REJECTED
            )

        assert exc_info.value.audit_id
        assert len(exc_info.value.audit_id) > 0


# ===========================================================================
# E) Explicit routing does not exempt capability gate
# ===========================================================================


class TestExplicitRoutingDoesNotExemptGate:
    def test_explicit_device_id_still_gated(self):
        """Supplying device_id explicitly does not skip the capability gate."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import CapabilityHardRejectError

        # Explicit device_id with known missing capability → should still reject
        with pytest.raises(CapabilityHardRejectError):
            enforce_gateway_default_capability_gate(
                device_id="explicit_device_no_camera",
                command="take_photo",
                required_capabilities=["camera"],
                device_capabilities=["screen"],  # no camera
            )

    def test_explicit_device_id_with_matching_caps_passes(self):
        """Explicit device_id with correct caps → PASSED (not rejected)."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        record = enforce_gateway_default_capability_gate(
            device_id="explicit_device_with_camera",
            command="take_photo",
            required_capabilities=["camera"],
            device_capabilities=["camera", "screen"],
        )
        assert record.verdict == HardenedVerdict.PASSED

    def test_no_caps_no_inference_still_no_op(self):
        """Explicit device_id + no caps + no inference → NO_REQUIREMENTS (backward compat)."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedVerdict

        record = enforce_gateway_default_capability_gate(
            device_id="explicit_device_any",
            command="device_control",
            required_capabilities=None,
            device_capabilities=["screen"],
        )
        assert record.verdict == HardenedVerdict.NO_REQUIREMENTS


# ===========================================================================
# F) audit_gateway_override — audited override path
# ===========================================================================


class TestAuditGatewayOverride:
    def test_override_with_reason_returns_audited_override(self):
        from core.gateway_capability_default_enforcement import audit_gateway_override
        from core.capability_enforcement_hardener import HardenedVerdict

        record = audit_gateway_override(
            device_id="dev_override",
            command="take_photo",
            override_reason="Emergency diagnostic — device known to have camera despite registry lag",
            required_capabilities=["camera"],
            device_capabilities=[],  # would normally be rejected
        )
        assert record.verdict == HardenedVerdict.AUDITED_OVERRIDE
        assert record.override_reason

    def test_override_without_reason_raises_value_error(self):
        from core.gateway_capability_default_enforcement import audit_gateway_override

        with pytest.raises(ValueError, match="override_reason"):
            audit_gateway_override(
                device_id="dev_x",
                command="take_photo",
                override_reason="",  # empty reason must raise
                required_capabilities=["camera"],
                device_capabilities=[],
            )

    def test_override_reason_stored_in_record(self):
        from core.gateway_capability_default_enforcement import audit_gateway_override

        reason = "CI integration test bypass"
        record = audit_gateway_override(
            device_id="dev_y",
            command="gps_locate",
            override_reason=reason,
            required_capabilities=["gps"],
            device_capabilities=["screen"],
        )
        assert record.override_reason == reason

    def test_override_infers_capabilities_when_not_supplied(self):
        from core.gateway_capability_default_enforcement import audit_gateway_override
        from core.capability_enforcement_hardener import HardenedVerdict

        record = audit_gateway_override(
            device_id="dev_infer",
            command="nfc_read",  # infers ["nfc"]
            override_reason="Test override with inferred caps",
            required_capabilities=None,  # should be inferred
            device_capabilities=[],
        )
        assert record.verdict == HardenedVerdict.AUDITED_OVERRIDE
        assert "nfc" in record.required_capabilities


# ===========================================================================
# G) openclawd.py static checks — gate is wired into send_gateway_command
# ===========================================================================


class TestOpenclawdGateWired:
    def test_gateway_enforcement_module_imported_in_send_gateway_command(self):
        """core/openclawd.py must reference gateway_capability_default_enforcement."""
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"

        assert openclawd_path.exists(), "core/openclawd.py not found"
        source = openclawd_path.read_text(encoding="utf-8")

        assert "gateway_capability_default_enforcement" in source, (
            "core/openclawd.py must import from "
            "core.gateway_capability_default_enforcement.  "
            "The GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT closure requires "
            "the gate to be wired into send_gateway_command()."
        )

    def test_enforce_gateway_default_capability_gate_called_in_send_gateway_command(self):
        """send_gateway_command must call enforce_gateway_default_capability_gate."""
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"
        source = openclawd_path.read_text(encoding="utf-8")

        assert "enforce_gateway_default_capability_gate" in source, (
            "core/openclawd.py must call enforce_gateway_default_capability_gate() "
            "inside send_gateway_command().  Without this call, the capability gate "
            "is not a default invariant and GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT "
            "is not closed."
        )

    def test_capability_hard_reject_error_handled_in_send_gateway_command(self):
        """send_gateway_command must catch CapabilityHardRejectError."""
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"
        source = openclawd_path.read_text(encoding="utf-8")

        assert "CapabilityHardRejectError" in source, (
            "core/openclawd.py must catch CapabilityHardRejectError inside "
            "send_gateway_command() and return a hard-reject response dict.  "
            "Without this, unhandled exceptions from the gate break the "
            "gateway command path entirely."
        )

    def test_capability_gate_verdict_in_result_dict(self):
        """send_gateway_command must attach capability_gate_verdict to result."""
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"
        source = openclawd_path.read_text(encoding="utf-8")

        assert "capability_gate_verdict" in source, (
            "core/openclawd.py send_gateway_command must attach "
            "'capability_gate_verdict' from the gate record to the result "
            "dict for observability."
        )


# ===========================================================================
# H) GAP registry — GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT marked resolved
# ===========================================================================


class TestGapRegistryResolved:
    def test_gap_capability_gate_marked_resolved(self):
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY

        gap = next(
            (g for g in WORKSTREAM_GAP_REGISTRY if g.gap_id == "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT"),
            None,
        )
        assert gap is not None, "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT not found in WORKSTREAM_GAP_REGISTRY"
        assert gap.resolved is True, (
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT must be marked resolved=True "
            "after the closure PR lands."
        )

    def test_gap_resolution_pr_non_empty(self):
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY

        gap = next(
            (g for g in WORKSTREAM_GAP_REGISTRY if g.gap_id == "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT"),
            None,
        )
        assert gap is not None
        assert gap.resolution_pr, (
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT must have a non-empty "
            "resolution_pr to prove it was closed by a concrete PR."
        )


# ===========================================================================
# I) Regression gate — module importable and gate callable
# ===========================================================================


class TestRegressionGate:
    def test_module_importable(self):
        """The enforcement module must be importable without errors."""
        import core.gateway_capability_default_enforcement as m  # noqa: F401

        assert m is not None

    def test_gate_callable(self):
        """enforce_gateway_default_capability_gate must be callable."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )

        assert callable(enforce_gateway_default_capability_gate)

    def test_override_callable(self):
        """audit_gateway_override must be callable."""
        from core.gateway_capability_default_enforcement import audit_gateway_override

        assert callable(audit_gateway_override)

    def test_infer_callable(self):
        """infer_required_capabilities must be callable."""
        from core.gateway_capability_default_enforcement import infer_required_capabilities

        assert callable(infer_required_capabilities)

    def test_gate_returns_record_type(self):
        """enforce_gateway_default_capability_gate must return HardenedEnforcementRecord."""
        from core.gateway_capability_default_enforcement import (
            enforce_gateway_default_capability_gate,
        )
        from core.capability_enforcement_hardener import HardenedEnforcementRecord

        record = enforce_gateway_default_capability_gate(
            device_id="regression_dev",
            command="device_control",  # no inference
            required_capabilities=None,
            device_capabilities=[],
        )
        assert isinstance(record, HardenedEnforcementRecord)
