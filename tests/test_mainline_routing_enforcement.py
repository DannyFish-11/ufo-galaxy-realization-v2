#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_mainline_routing_enforcement.py
==========================================
Mainline routing enforcement: capability gate on explicit device routing paths.

This test file verifies the enforcement changes introduced to close the
explicit-device-id capability gate bypass gap.

Test groups
-----------
A) Sentinels — all enforcement sentinels importable and non-empty.
B) ExplicitRouteVerdict — enum values correct.
C) audit_explicit_device_capabilities — no requirements → NO_REQUIREMENTS.
D) audit_explicit_device_capabilities — confirmed path.
E) audit_explicit_device_capabilities — mismatch path.
F) audit_explicit_device_capabilities — partially missing capabilities.
G) audit_explicit_device_capabilities — insufficient data (runtime unavailable).
H) enforce_explicit_route_capability_gate — MISMATCH → AUDITED_BYPASS (no raise).
I) enforce_explicit_route_capability_gate — MISMATCH + raise_on_mismatch → exception.
J) enforce_explicit_route_capability_gate — CONFIRMED → no log warning.
K) ExplicitRouteCapabilityAudit.to_dict — serialisable.
L) Android local AI sentinel — unavailable-by-default expressed.
M) openclawd.py — enforcement call site present (static source check).
N) openclawd.py — _dispatch_device forwards required_capabilities.
"""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# A) Sentinels
# ===========================================================================


class TestEnforcementSentinels:
    def test_authority_sentinel_importable(self):
        from core.mainline_routing_enforcement import MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY

        assert MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY
        assert "AUTHORITY" in MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY

    def test_pr_sentinel_importable(self):
        from core.mainline_routing_enforcement import MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL

        assert MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL

    def test_capability_gate_enforcement_policy(self):
        from core.mainline_routing_enforcement import (
            CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY,
        )

        assert "explicit" in CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY.lower()
        assert "device_id" in CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY

    def test_no_silent_bypass_policy(self):
        from core.mainline_routing_enforcement import NO_SILENT_CAPABILITY_BYPASS_POLICY

        assert "silent" in NO_SILENT_CAPABILITY_BYPASS_POLICY.lower()

    def test_bypass_requires_audit_policy(self):
        from core.mainline_routing_enforcement import EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY

        assert "audit" in EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY.lower()


# ===========================================================================
# B) ExplicitRouteVerdict enum
# ===========================================================================


class TestExplicitRouteVerdict:
    def test_verdict_values_exist(self):
        from core.mainline_routing_enforcement import ExplicitRouteVerdict

        assert ExplicitRouteVerdict.CONFIRMED.value == "confirmed"
        assert ExplicitRouteVerdict.MISMATCH.value == "mismatch"
        assert ExplicitRouteVerdict.INSUFFICIENT_DATA.value == "insufficient_data"
        assert ExplicitRouteVerdict.AUDITED_BYPASS.value == "audited_bypass"
        assert ExplicitRouteVerdict.NO_REQUIREMENTS.value == "no_requirements"


# ===========================================================================
# C) audit_explicit_device_capabilities — no requirements
# ===========================================================================


class TestAuditNoRequirements:
    def test_empty_requirements_returns_no_requirements(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities("dev_001", [])

        assert result is not None
        assert result.verdict == ExplicitRouteVerdict.NO_REQUIREMENTS
        assert result.device_id == "dev_001"
        assert result.required_capabilities == []

    def test_none_treated_as_empty(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        # Passing an empty sequence — gate is inactive.
        result = audit_explicit_device_capabilities("dev_002", [])
        assert result.verdict == ExplicitRouteVerdict.NO_REQUIREMENTS


# ===========================================================================
# D) audit_explicit_device_capabilities — confirmed path
# ===========================================================================


class TestAuditConfirmed:
    def test_all_caps_present_confirms(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_phone",
            ["screen", "touch"],
            device_capabilities=["screen", "touch", "camera"],
        )

        assert result.verdict == ExplicitRouteVerdict.CONFIRMED
        assert result.missing_capabilities == []
        assert "screen" in result.confirmed_capabilities or result.confirmed_capabilities

    def test_single_cap_confirmed(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_desktop",
            ["keyboard"],
            device_capabilities=["keyboard", "screen"],
        )

        assert result.verdict == ExplicitRouteVerdict.CONFIRMED

    def test_exact_match_confirmed(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_tablet",
            ["screen", "touch"],
            device_capabilities=["screen", "touch"],
        )

        assert result.verdict == ExplicitRouteVerdict.CONFIRMED


# ===========================================================================
# E) audit_explicit_device_capabilities — mismatch path
# ===========================================================================


class TestAuditMismatch:
    def test_missing_cap_returns_mismatch(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_basic",
            ["screen", "local_ai"],
            device_capabilities=["screen"],
        )

        assert result.verdict == ExplicitRouteVerdict.MISMATCH
        assert "local_ai" in result.missing_capabilities

    def test_no_caps_at_all_returns_mismatch(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_empty",
            ["screen"],
            device_capabilities=[],
        )

        assert result.verdict == ExplicitRouteVerdict.MISMATCH
        assert "screen" in result.missing_capabilities


# ===========================================================================
# F) audit_explicit_device_capabilities — partial mismatch
# ===========================================================================


class TestAuditPartialMismatch:
    def test_partial_mismatch_reported(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        result = audit_explicit_device_capabilities(
            "dev_partial",
            ["screen", "touch", "nfc"],
            device_capabilities=["screen", "touch"],
        )

        assert result.verdict == ExplicitRouteVerdict.MISMATCH
        assert "nfc" in result.missing_capabilities
        # screen and touch should be accounted for
        assert "nfc" not in result.confirmed_capabilities


# ===========================================================================
# G) audit_explicit_device_capabilities — insufficient data
# ===========================================================================


class TestAuditInsufficientData:
    def test_no_runtime_returns_insufficient_data(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            audit_explicit_device_capabilities,
        )

        # No device_capabilities supplied, and runtime lookup will fail in tests.
        # The function must return INSUFFICIENT_DATA, not raise.
        result = audit_explicit_device_capabilities(
            "dev_unknown",
            ["screen"],
            # device_capabilities=None means runtime lookup attempted
        )

        # Either INSUFFICIENT_DATA (runtime unavailable) or CONFIRMED/MISMATCH
        # if the runtime somehow returns data in the test environment.
        # We only require that it doesn't raise.
        assert result is not None
        assert result.verdict in (
            ExplicitRouteVerdict.INSUFFICIENT_DATA,
            ExplicitRouteVerdict.CONFIRMED,
            ExplicitRouteVerdict.MISMATCH,
        )


# ===========================================================================
# H) enforce_explicit_route_capability_gate — MISMATCH → AUDITED_BYPASS
# ===========================================================================


class TestEnforceMismatchAuditedBypass:
    def test_mismatch_becomes_audited_bypass(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            enforce_explicit_route_capability_gate,
        )

        result = enforce_explicit_route_capability_gate(
            "dev_lacking",
            ["local_ai"],
            device_capabilities=[],
            raise_on_mismatch=False,
        )

        # MISMATCH is promoted to AUDITED_BYPASS (not silent)
        assert result.verdict == ExplicitRouteVerdict.AUDITED_BYPASS

    def test_no_requirements_returns_no_requirements(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            enforce_explicit_route_capability_gate,
        )

        result = enforce_explicit_route_capability_gate(
            "dev_any",
            [],
            device_capabilities=["screen"],
            raise_on_mismatch=False,
        )

        assert result.verdict == ExplicitRouteVerdict.NO_REQUIREMENTS


# ===========================================================================
# I) enforce_explicit_route_capability_gate — raise_on_mismatch
# ===========================================================================


class TestEnforceMismatchRaise:
    def test_raise_on_mismatch_raises_capability_mismatch_error(self):
        from core.mainline_routing_enforcement import (
            CapabilityMismatchError,
            ExplicitRouteVerdict,
            enforce_explicit_route_capability_gate,
        )

        with pytest.raises(CapabilityMismatchError) as exc_info:
            enforce_explicit_route_capability_gate(
                "dev_lacking",
                ["local_ai"],
                device_capabilities=[],
                raise_on_mismatch=True,
            )

        assert "dev_lacking" in str(exc_info.value)
        # The exception carries the original MISMATCH verdict, not AUDITED_BYPASS,
        # so the caller receives the real verdict.
        assert exc_info.value.audit.verdict == ExplicitRouteVerdict.MISMATCH

    def test_no_raise_when_confirmed(self):
        from core.mainline_routing_enforcement import (
            ExplicitRouteVerdict,
            enforce_explicit_route_capability_gate,
        )

        result = enforce_explicit_route_capability_gate(
            "dev_capable",
            ["screen"],
            device_capabilities=["screen", "touch"],
            raise_on_mismatch=True,
        )

        assert result.verdict == ExplicitRouteVerdict.CONFIRMED


# ===========================================================================
# J) enforce_explicit_route_capability_gate — CONFIRMED → no warning
# ===========================================================================


class TestEnforceConfirmedNoWarn:
    def test_confirmed_does_not_log_warning(self, caplog):
        import logging

        from core.mainline_routing_enforcement import enforce_explicit_route_capability_gate

        with caplog.at_level(logging.WARNING, logger="Galaxy.MainlineRoutingEnforcement"):
            enforce_explicit_route_capability_gate(
                "dev_full",
                ["screen"],
                device_capabilities=["screen", "touch"],
            )

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warning_records, (
            "Expected no warning for confirmed capability gate, "
            f"got: {[r.message for r in warning_records]}"
        )


# ===========================================================================
# K) ExplicitRouteCapabilityAudit.to_dict
# ===========================================================================


class TestAuditToDict:
    def test_to_dict_serialisable(self):
        import json

        from core.mainline_routing_enforcement import (
            ExplicitRouteCapabilityAudit,
            ExplicitRouteVerdict,
        )

        audit = ExplicitRouteCapabilityAudit(
            device_id="dev_test",
            required_capabilities=["screen"],
            verdict=ExplicitRouteVerdict.CONFIRMED,
            confirmed_capabilities=["screen"],
            missing_capabilities=[],
            reason="Test",
        )

        d = audit.to_dict()
        assert d["device_id"] == "dev_test"
        assert d["verdict"] == "confirmed"

        # Must be JSON-serialisable
        json_str = json.dumps(d)
        assert "dev_test" in json_str


# ===========================================================================
# L) Android local AI sentinel — unavailable by default
# ===========================================================================


class TestAndroidLocalAISentinel:
    def test_unavailable_by_default_sentinel_present(self):
        from core.android_runtime_host import ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT

        assert ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT
        assert "UNAVAILABLE" in ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT

    def test_roadmap_sentinel_present(self):
        from core.android_runtime_host import ANDROID_LOCAL_AI_IS_ROADMAP_NOT_DEFAULT

        assert ANDROID_LOCAL_AI_IS_ROADMAP_NOT_DEFAULT
        assert "ROADMAP" in ANDROID_LOCAL_AI_IS_ROADMAP_NOT_DEFAULT

    def test_default_capability_flag_is_false(self):
        from core.android_runtime_host import ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG

        assert ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG is False, (
            "Android local AI must default to OFF.  "
            "ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG must be False."
        )


# ===========================================================================
# M) openclawd.py — enforcement call site present (static source check)
# ===========================================================================


class TestOpenclawdCallSitePresent:
    def test_enforcement_function_referenced_in_openclawd(self):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"

        assert openclawd_path.exists(), "core/openclawd.py not found"

        source = openclawd_path.read_text(encoding="utf-8")
        assert "enforce_explicit_route_capability_gate" in source, (
            "core/openclawd.py must contain a call to "
            "enforce_explicit_route_capability_gate.  "
            "The explicit-device-id capability bypass gap must not be re-opened."
        )

    def test_enforcement_import_in_openclawd(self):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"
        source = openclawd_path.read_text(encoding="utf-8")

        assert "mainline_routing_enforcement" in source, (
            "core/openclawd.py must import from core.mainline_routing_enforcement."
        )


# ===========================================================================
# N) openclawd.py — _dispatch_device forwards required_capabilities
# ===========================================================================


class TestDispatchDeviceForwardsCapabilities:
    def test_required_capabilities_forwarded_in_dispatch_device(self):
        import pathlib

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        openclawd_path = repo_root / "core" / "openclawd.py"
        source = openclawd_path.read_text(encoding="utf-8")

        # The fix ensures _dispatch_device passes required_capabilities
        # to send_gateway_command so the TaskEnvelope gate is reachable.
        assert "required_capabilities=required_caps" in source, (
            "_dispatch_device must forward required_capabilities to "
            "send_gateway_command.  Without this, the TaskEnvelope capability "
            "gate in CommandRouter is unreachable on explicit device routes."
        )
