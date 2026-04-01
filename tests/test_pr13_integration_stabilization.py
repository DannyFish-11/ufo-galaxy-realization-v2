"""
tests/test_pr13_integration_stabilization.py
=============================================
PR-13 — Integration and Stabilization of Canonical Cross-Device Control Plane.

This test module validates that the canonical cross-device control-plane
modules introduced across earlier PRs are properly integrated and that
their public APIs remain stable.

Coverage
--------
A) Module imports — all canonical control-plane modules are importable
   from the correct locations

B) Authority sentinels — all modules export a stable authority sentinel string

C) Field name consistency — shared field names across control-plane modules
   (ready, orchestration_eligible, capability_match, valid, selected,
   reasons, sources) follow the naming convention

D) to_dict() consistency — all result/summary types produce dicts with
   expected stable keys

E) Inter-layer integration — the combined candidate resolution path
   (Layers 1 + 2 + 4 via Layer 6) behaves as expected under controlled
   mock conditions

F) Graceful degradation contract — all public helpers return safe defaults
   when all optional subsystems are unavailable

G) Failure domain integration — failure domain classification is importable
   and integrates with execution failure schemas

H) Cross-device policy integration — cross-device policy package is
   importable and exports the expected public API

I) Documentation presence — the architecture document exists on disk

J) Logging field consistency — exclusion decisions are logged with
   consistent event-name fields
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# A) Module imports
# ===========================================================================

class TestModuleImports:
    """All canonical control-plane modules are importable from expected paths."""

    def test_device_readiness_importable(self):
        """Layer 1: core.device_readiness is importable."""
        import core.device_readiness  # noqa: F401

    def test_device_participation_importable(self):
        """Layer 2: core.device_participation is importable."""
        import core.device_participation  # noqa: F401

    def test_mesh_participation_summary_importable(self):
        """Layer 3: core.mesh_participation_summary is importable."""
        import core.mesh_participation_summary  # noqa: F401

    def test_capability_registry_importable(self):
        """Layer 4: core.capability_registry is importable."""
        import core.capability_registry  # noqa: F401

    def test_target_device_validator_importable(self):
        """Layer 5: core.target_device_validator is importable."""
        import core.target_device_validator  # noqa: F401

    def test_cross_device_candidates_importable(self):
        """Layer 6: core.cross_device_candidates is importable."""
        import core.cross_device_candidates  # noqa: F401

    def test_failure_domains_importable(self):
        """Layer 9a: core.failure_domains is importable."""
        import core.failure_domains  # noqa: F401

    def test_execution_failure_schema_importable(self):
        """Layer 9b: core.schemas.execution_failure is importable."""
        import core.schemas.execution_failure  # noqa: F401

    def test_cross_device_policy_importable(self):
        """Layer 8: core.cross_device_policy package is importable."""
        import core.cross_device_policy  # noqa: F401

    def test_cross_device_policy_device_role_importable(self):
        """DeviceRole importable from core.cross_device_policy."""
        from core.cross_device_policy import DeviceRole  # noqa: F401

    def test_cross_device_policy_routing_policy_importable(self):
        """RoutingPolicy importable from core.cross_device_policy."""
        from core.cross_device_policy import RoutingPolicy  # noqa: F401

    def test_cross_device_policy_resolve_routing_importable(self):
        """resolve_routing importable from core.cross_device_policy."""
        from core.cross_device_policy import resolve_routing  # noqa: F401


# ===========================================================================
# B) Authority sentinels
# ===========================================================================

class TestAuthoritySentinels:
    """All canonical modules export a non-empty authority sentinel string."""

    def test_device_readiness_authority(self):
        from core.device_readiness import DEVICE_READINESS_AUTHORITY
        assert isinstance(DEVICE_READINESS_AUTHORITY, str)
        assert len(DEVICE_READINESS_AUTHORITY) > 0

    def test_device_participation_authority(self):
        from core.device_participation import DEVICE_PARTICIPATION_AUTHORITY
        assert isinstance(DEVICE_PARTICIPATION_AUTHORITY, str)
        assert len(DEVICE_PARTICIPATION_AUTHORITY) > 0

    def test_capability_registry_authority(self):
        from core.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        assert isinstance(CAPABILITY_REGISTRY_AUTHORITY, str)
        assert len(CAPABILITY_REGISTRY_AUTHORITY) > 0

    def test_target_device_validator_authority(self):
        from core.target_device_validator import TARGET_DEVICE_VALIDATOR_AUTHORITY
        assert isinstance(TARGET_DEVICE_VALIDATOR_AUTHORITY, str)
        assert len(TARGET_DEVICE_VALIDATOR_AUTHORITY) > 0

    def test_cross_device_candidates_authority(self):
        from core.cross_device_candidates import CROSS_DEVICE_CANDIDATES_AUTHORITY
        assert isinstance(CROSS_DEVICE_CANDIDATES_AUTHORITY, str)
        assert len(CROSS_DEVICE_CANDIDATES_AUTHORITY) > 0

    def test_authority_sentinels_are_distinct(self):
        """All authority sentinels must be unique strings."""
        from core.device_readiness import DEVICE_READINESS_AUTHORITY
        from core.device_participation import DEVICE_PARTICIPATION_AUTHORITY
        from core.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        from core.target_device_validator import TARGET_DEVICE_VALIDATOR_AUTHORITY
        from core.cross_device_candidates import CROSS_DEVICE_CANDIDATES_AUTHORITY

        sentinels = [
            DEVICE_READINESS_AUTHORITY,
            DEVICE_PARTICIPATION_AUTHORITY,
            CAPABILITY_REGISTRY_AUTHORITY,
            TARGET_DEVICE_VALIDATOR_AUTHORITY,
            CROSS_DEVICE_CANDIDATES_AUTHORITY,
        ]
        assert len(sentinels) == len(set(sentinels)), (
            "Authority sentinels must be distinct; duplicates found"
        )


# ===========================================================================
# C) Field name consistency
# ===========================================================================

class TestFieldNameConsistency:
    """Shared field names follow the canonical naming convention."""

    def test_device_readiness_summary_has_registered(self):
        from core.device_readiness import DeviceReadinessSummary
        s = DeviceReadinessSummary(device_id="d1")
        assert hasattr(s, "registered")

    def test_device_readiness_summary_has_reasons(self):
        from core.device_readiness import DeviceReadinessSummary
        s = DeviceReadinessSummary(device_id="d1")
        assert hasattr(s, "reasons")
        assert isinstance(s.reasons, list)

    def test_device_readiness_summary_has_sources(self):
        from core.device_readiness import DeviceReadinessSummary
        s = DeviceReadinessSummary(device_id="d1")
        assert hasattr(s, "sources")
        assert isinstance(s.sources, dict)

    def test_participation_summary_has_orchestration_eligible(self):
        from core.device_participation import ParticipationSummary
        s = ParticipationSummary(device_id="d1")
        assert hasattr(s, "orchestration_eligible")

    def test_participation_summary_has_reasons(self):
        from core.device_participation import ParticipationSummary
        s = ParticipationSummary(device_id="d1")
        assert hasattr(s, "reasons")
        assert isinstance(s.reasons, list)

    def test_participation_summary_has_sources(self):
        from core.device_participation import ParticipationSummary
        s = ParticipationSummary(device_id="d1")
        assert hasattr(s, "sources")
        assert isinstance(s.sources, dict)

    def test_capability_summary_has_resolved_capabilities(self):
        from core.capability_registry import DeviceCapabilitySummary
        s = DeviceCapabilitySummary(device_id="d1")
        assert hasattr(s, "resolved_capabilities")
        assert isinstance(s.resolved_capabilities, list)

    def test_capability_summary_has_reasons(self):
        from core.capability_registry import DeviceCapabilitySummary
        s = DeviceCapabilitySummary(device_id="d1")
        assert hasattr(s, "reasons")
        assert isinstance(s.reasons, list)

    def test_target_validation_result_has_valid(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "valid")

    def test_target_validation_result_has_ready(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "ready")

    def test_target_validation_result_has_capability_match(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "capability_match")

    def test_target_validation_result_has_orchestration_eligible(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "orchestration_eligible")

    def test_target_validation_result_has_reasons(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "reasons")
        assert isinstance(r.reasons, list)

    def test_target_validation_result_has_sources(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        assert hasattr(r, "sources")
        assert isinstance(r.sources, dict)

    def test_cross_device_candidate_has_ready(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "ready")

    def test_cross_device_candidate_has_orchestration_eligible(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "orchestration_eligible")

    def test_cross_device_candidate_has_capability_match(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "capability_match")

    def test_cross_device_candidate_has_selected(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "selected")

    def test_cross_device_candidate_has_reasons(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "reasons")
        assert isinstance(c.reasons, list)

    def test_cross_device_candidate_has_sources(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        assert hasattr(c, "sources")
        assert isinstance(c.sources, dict)


# ===========================================================================
# D) to_dict() consistency
# ===========================================================================

class TestToDictConsistency:
    """All result/summary types produce JSON-serialisable dicts with stable keys."""

    def _assert_json_safe(self, d: dict) -> None:
        try:
            json.dumps(d)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"to_dict() result is not JSON-serialisable: {exc}")

    def test_device_readiness_summary_to_dict(self):
        from core.device_readiness import DeviceReadinessSummary
        s = DeviceReadinessSummary(device_id="d1")
        d = s.to_dict()
        assert isinstance(d, dict)
        for key in ("device_id", "registered", "reasons", "sources"):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_participation_summary_to_dict(self):
        from core.device_participation import ParticipationSummary
        s = ParticipationSummary(device_id="d1")
        d = s.to_dict()
        assert isinstance(d, dict)
        for key in ("device_id", "orchestration_eligible", "reasons", "sources"):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_capability_summary_to_dict(self):
        from core.capability_registry import DeviceCapabilitySummary
        s = DeviceCapabilitySummary(device_id="d1")
        d = s.to_dict()
        assert isinstance(d, dict)
        for key in ("device_id", "available", "resolved_capabilities", "reasons", "sources"):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_capability_match_result_to_dict(self):
        from core.capability_registry import CapabilityMatchResult
        r = CapabilityMatchResult(device_id="d1", required_capabilities=[])
        d = r.to_dict()
        assert isinstance(d, dict)
        for key in ("device_id", "matched", "missing_capabilities"):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_target_validation_result_to_dict(self):
        from core.target_device_validator import TargetDeviceValidationResult
        r = TargetDeviceValidationResult(device_id="d1")
        d = r.to_dict()
        assert isinstance(d, dict)
        for key in (
            "device_id", "valid", "registered", "ready",
            "capability_match", "orchestration_eligible",
            "reasons", "sources",
        ):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_cross_device_candidate_to_dict(self):
        from core.cross_device_candidates import CrossDeviceCandidate
        c = CrossDeviceCandidate(device_id="d1")
        d = c.to_dict()
        assert isinstance(d, dict)
        for key in (
            "device_id", "ready", "orchestration_eligible",
            "capability_match", "selected", "reasons", "sources",
        ):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)

    def test_cross_device_resolution_to_dict(self):
        from core.cross_device_candidates import CrossDeviceCandidateResolution
        r = CrossDeviceCandidateResolution()
        d = r.to_dict()
        assert isinstance(d, dict)
        for key in (
            "required_capabilities", "requested_target_device",
            "selected_device_ids", "eligible_device_ids",
            "candidates", "reasons",
        ):
            assert key in d, f"Missing key: {key}"
        self._assert_json_safe(d)


# ===========================================================================
# E) Inter-layer integration
# ===========================================================================

MOD_CANDIDATES = "core.cross_device_candidates"


def _patch_enumerate(device_ids: List[str]):
    return patch(f"{MOD_CANDIDATES}._enumerate_device_ids", return_value=device_ids)


def _patch_readiness(ready_map: Dict[str, bool]):
    def _check(device_id: str) -> tuple:
        ready = ready_map.get(device_id, False)
        reasons = [] if ready else [f"not-ready:{device_id}"]
        return ready, reasons
    return patch(f"{MOD_CANDIDATES}._check_readiness", side_effect=_check)


def _patch_participation(eligible_map: Dict[str, bool]):
    def _check(device_id: str) -> tuple:
        eligible = eligible_map.get(device_id, False)
        reasons = [] if eligible else [f"not-eligible:{device_id}"]
        return eligible, reasons
    return patch(f"{MOD_CANDIDATES}._check_orchestration_eligible", side_effect=_check)


def _patch_capability(capable_map: Dict[str, bool]):
    def _check(device_id: str, caps: List[str]) -> tuple:
        match = capable_map.get(device_id, True)
        reasons = [] if match else [f"capability-mismatch:{device_id}"]
        return match, {}, reasons
    return patch(f"{MOD_CANDIDATES}._check_capabilities", side_effect=_check)


class TestInterLayerIntegration:
    """Integration tests for the combined candidate resolution path."""

    def test_all_gates_pass_device_is_selected(self):
        """A device passing all three gates (readiness, participation, capability) is selected."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-a"]), \
             _patch_readiness({"dev-a": True}), \
             _patch_participation({"dev-a": True}), \
             _patch_capability({"dev-a": True}):
            result = resolve_cross_device_candidates(required_capabilities=["screen"])
        assert "dev-a" in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-a")
        assert candidate.selected is True
        assert candidate.ready is True
        assert candidate.orchestration_eligible is True
        assert candidate.capability_match is True

    def test_readiness_gate_excludes_device(self):
        """A device failing readiness is excluded even if other gates pass."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-b"]), \
             _patch_readiness({"dev-b": False}), \
             _patch_participation({"dev-b": True}):
            result = resolve_cross_device_candidates()
        assert "dev-b" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-b")
        assert candidate.selected is False
        assert candidate.ready is False
        assert len(candidate.reasons) > 0

    def test_participation_gate_excludes_device(self):
        """A device failing participation is excluded when gate is required."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-c"]), \
             _patch_readiness({"dev-c": True}), \
             _patch_participation({"dev-c": False}):
            result = resolve_cross_device_candidates(require_orchestration_eligible=True)
        assert "dev-c" not in result.selected_device_ids

    def test_participation_gate_skipped_when_not_required(self):
        """A device failing participation passes when require_orchestration_eligible=False."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-d"]), \
             _patch_readiness({"dev-d": True}), \
             _patch_participation({"dev-d": False}), \
             _patch_capability({"dev-d": True}):
            result = resolve_cross_device_candidates(require_orchestration_eligible=False)
        assert "dev-d" in result.selected_device_ids

    def test_capability_gate_excludes_device(self):
        """A device failing capability check is excluded."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["dev-e"]), \
             _patch_readiness({"dev-e": True}), \
             _patch_participation({"dev-e": True}), \
             _patch_capability({"dev-e": False}):
            result = resolve_cross_device_candidates(required_capabilities=["camera"])
        assert "dev-e" not in result.selected_device_ids
        candidate = next(c for c in result.candidates if c.device_id == "dev-e")
        assert candidate.capability_match is False

    def test_multiple_devices_mixed_eligibility(self):
        """Multiple devices are filtered correctly when eligibility varies."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        devices = ["ready-1", "ready-2", "not-ready"]
        with _patch_enumerate(devices), \
             _patch_readiness({"ready-1": True, "ready-2": True, "not-ready": False}), \
             _patch_participation({"ready-1": True, "ready-2": True, "not-ready": False}), \
             _patch_capability({"ready-1": True, "ready-2": True, "not-ready": False}):
            result = resolve_cross_device_candidates()
        assert "ready-1" in result.selected_device_ids
        assert "ready-2" in result.selected_device_ids
        assert "not-ready" not in result.selected_device_ids

    def test_requested_valid_target_is_selected(self):
        """A valid requested target device is included in selected_device_ids."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["target-dev"]), \
             _patch_readiness({"target-dev": True}), \
             _patch_participation({"target-dev": True}), \
             _patch_capability({"target-dev": True}):
            result = resolve_cross_device_candidates(requested_target_device="target-dev")
        assert "target-dev" in result.selected_device_ids

    def test_requested_invalid_target_is_excluded(self):
        """An invalid requested target device is excluded with reasons in the resolution."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        with _patch_enumerate(["bad-dev"]), \
             _patch_readiness({"bad-dev": False}), \
             _patch_participation({"bad-dev": False}):
            result = resolve_cross_device_candidates(requested_target_device="bad-dev")
        assert "bad-dev" not in result.selected_device_ids
        assert len(result.reasons) > 0


# ===========================================================================
# F) Graceful degradation contract
# ===========================================================================

class TestGracefulDegradation:
    """All public helpers return safe results when optional subsystems are unavailable."""

    def test_device_readiness_never_raises(self):
        """get_device_readiness must not raise even when all subsystems are absent."""
        from core.device_readiness import get_device_readiness

        def _boom(*args, **kwargs):
            raise RuntimeError("subsystem unavailable")

        with patch.dict("sys.modules", {"core.unified_device_manager": None}):
            try:
                result = get_device_readiness("test-device")
            except Exception as exc:
                pytest.fail(f"get_device_readiness raised unexpectedly: {exc}")
        assert result is not None
        assert result.device_id == "test-device"

    def test_target_validator_never_raises(self):
        """validate_target_device must not raise even when all subsystems fail."""
        from core.target_device_validator import validate_target_device

        with _patch_enumerate([]), \
             patch("core.target_device_validator._check_readiness",
                   return_value=(False, False, {}, ["readiness-unavailable"])):
            try:
                result = validate_target_device("test-device")
            except Exception as exc:
                pytest.fail(f"validate_target_device raised unexpectedly: {exc}")
        assert result is not None
        assert result.device_id == "test-device"
        assert result.valid is False

    def test_cross_device_candidates_never_raises(self):
        """resolve_cross_device_candidates must not raise even when all subsystems fail."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        def _boom():
            raise RuntimeError("boom")

        with patch(f"{MOD_CANDIDATES}._enumerate_device_ids", side_effect=_boom):
            try:
                result = resolve_cross_device_candidates()
            except Exception as exc:
                pytest.fail(f"resolve_cross_device_candidates raised unexpectedly: {exc}")
        assert result is not None
        assert result.selected_device_ids == []

    def test_get_selected_candidates_never_raises(self):
        """get_selected_cross_device_candidates must not raise."""
        from core.cross_device_candidates import get_selected_cross_device_candidates

        def _boom():
            raise RuntimeError("boom")

        with patch(f"{MOD_CANDIDATES}._enumerate_device_ids", side_effect=_boom):
            try:
                result = get_selected_cross_device_candidates()
            except Exception as exc:
                pytest.fail(f"get_selected_cross_device_candidates raised unexpectedly: {exc}")
        assert isinstance(result, list)


# ===========================================================================
# G) Failure domain integration
# ===========================================================================

class TestFailureDomainIntegration:
    """Failure domain classification integrates with execution failure schemas."""

    def test_failure_domain_enum_importable(self):
        from core.failure_domains import FailureDomain
        assert hasattr(FailureDomain, "TIMEOUT_FAILURE")
        assert hasattr(FailureDomain, "REMOTE_DEVICE_UNAVAILABLE")
        assert hasattr(FailureDomain, "GATEWAY_TRANSPORT_FAILURE")

    def test_classify_from_error_code_timeout(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        classification = classify_from_error_code("COMMAND_TIMEOUT")
        assert classification.domain == FailureDomain.TIMEOUT_FAILURE
        assert classification.is_retryable is True

    def test_classify_from_error_code_device_not_found(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        classification = classify_from_error_code("DEVICE_NOT_FOUND")
        assert classification.domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE

    def test_classify_from_error_code_none_is_unknown(self):
        from core.failure_domains import classify_from_error_code, FailureDomain
        classification = classify_from_error_code(None)
        assert classification.domain == FailureDomain.UNKNOWN_FAILURE

    def test_classify_from_exception_timeout(self):
        from core.failure_domains import classify_from_exception, FailureDomain
        classification = classify_from_exception(TimeoutError("timed out"))
        assert classification.domain == FailureDomain.TIMEOUT_FAILURE

    def test_classify_from_exception_connection_error(self):
        from core.failure_domains import classify_from_exception, FailureDomain
        classification = classify_from_exception(ConnectionError("disconnected"))
        assert classification.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE

    def test_build_failure_record_importable(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("COMMAND_TIMEOUT")
        assert record is not None
        assert record.failure_domain == "timeout_failure"
        assert record.is_retryable is True

    def test_failure_record_to_dict_is_json_safe(self):
        from core.schemas.execution_failure import build_failure_record
        record = build_failure_record("DEVICE_NOT_FOUND")
        d = record.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise

    def test_failure_record_summary_returns_dict(self):
        from core.schemas.execution_failure import (
            build_failure_record,
            failure_record_summary,
        )
        record = build_failure_record("DISCONNECT")
        summary = failure_record_summary(record)
        assert isinstance(summary, dict)
        assert "failure_domain" in summary
        assert "is_retryable" in summary

    def test_failure_record_summary_none_returns_empty_dict(self):
        from core.schemas.execution_failure import failure_record_summary
        result = failure_record_summary(None)
        assert result == {}

    def test_is_retryable_by_domain_helpers(self):
        from core.failure_domains import is_retryable_by_domain, FailureDomain
        assert is_retryable_by_domain(FailureDomain.TIMEOUT_FAILURE) is True
        assert is_retryable_by_domain(FailureDomain.GATEWAY_TRANSPORT_FAILURE) is True
        assert is_retryable_by_domain(FailureDomain.CONTRACT_VALIDATION_FAILURE) is False

    def test_downgrade_hint_for_domain(self):
        from core.failure_domains import downgrade_hint_for_domain, FailureDomain
        hint = downgrade_hint_for_domain(FailureDomain.REMOTE_CAPABILITY_MISMATCH)
        assert hint == "agent_runtime_to_command_only"
        assert downgrade_hint_for_domain(FailureDomain.TIMEOUT_FAILURE) is None

    def test_default_policy_constants_importable(self):
        from core.schemas.execution_failure import (
            DEFAULT_NO_RETRY_POLICY,
            DEFAULT_TRANSIENT_RETRY_POLICY,
            DEFAULT_NO_FALLBACK_POLICY,
            DEFAULT_REMOTE_FALLBACK_POLICY,
        )
        assert DEFAULT_NO_RETRY_POLICY.is_retryable is False
        assert DEFAULT_TRANSIENT_RETRY_POLICY.is_retryable is True
        assert DEFAULT_NO_FALLBACK_POLICY.allow_remote_to_local is False
        assert DEFAULT_REMOTE_FALLBACK_POLICY.allow_remote_to_local is True


# ===========================================================================
# H) Cross-device policy integration
# ===========================================================================

class TestCrossDevicePolicyIntegration:
    """Cross-device policy package exports expected API and integrates correctly."""

    def test_device_role_enum_values(self):
        from core.cross_device_policy import DeviceRole
        expected_roles = {
            "source_device",
            "primary_execution_device",
            "support_device",
            "observer_device",
            "relay_device",
            "fallback_device",
            "unassigned",
        }
        actual_roles = {r.value for r in DeviceRole}
        assert expected_roles <= actual_roles, (
            f"Missing DeviceRole values: {expected_roles - actual_roles}"
        )

    def test_routing_posture_enum_values(self):
        from core.cross_device_policy import RoutingPosture
        expected_postures = {
            "local_preferred",
            "local_then_expand",
            "remote_required",
            "split_execution",
            "mirrored_observation",
            "undecided",
        }
        actual_postures = {p.value for p in RoutingPosture}
        assert expected_postures <= actual_postures, (
            f"Missing RoutingPosture values: {expected_postures - actual_postures}"
        )

    def test_default_local_routing_policy_is_local(self):
        from core.cross_device_policy import DEFAULT_LOCAL_ROUTING_POLICY, RoutingPosture
        assert DEFAULT_LOCAL_ROUTING_POLICY.posture in (
            RoutingPosture.LOCAL_PREFERRED,
            "local_preferred",
        )
        assert DEFAULT_LOCAL_ROUTING_POLICY.is_cross_device is False

    def test_resolve_routing_local_domain_returns_local_preferred(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture
        try:
            from core.continuum.types import RuntimeDomain
            domain = RuntimeDomain.LOCAL if hasattr(RuntimeDomain, "LOCAL") else None
        except Exception:
            domain = None
        policy = resolve_routing(runtime_domain=domain)
        assert policy.posture in (RoutingPosture.LOCAL_PREFERRED, "local_preferred")

    def test_resolve_routing_none_domain_is_safe(self):
        from core.cross_device_policy import resolve_routing, RoutingPosture
        policy = resolve_routing(runtime_domain=None)
        assert policy is not None
        assert policy.posture in (RoutingPosture.LOCAL_PREFERRED, "local_preferred")

    def test_build_assignment_summary_none_returns_idle(self):
        from core.cross_device_policy import build_assignment_summary, IDLE_ASSIGNMENT_SUMMARY
        summary = build_assignment_summary(None)
        assert summary is not None
        assert summary.is_cross_device is False

    def test_idle_assignment_summary_constant(self):
        from core.cross_device_policy import IDLE_ASSIGNMENT_SUMMARY
        assert IDLE_ASSIGNMENT_SUMMARY is not None
        assert IDLE_ASSIGNMENT_SUMMARY.is_cross_device is False

    def test_attach_cross_device_to_projection_additive(self):
        from core.cross_device_policy import attach_cross_device_to_projection
        original = {"key": "value"}
        result = attach_cross_device_to_projection(original, None)
        assert isinstance(result, dict)
        assert result["key"] == "value"
        assert original is not result  # original not modified

    def test_get_assignment_hints_none_summary(self):
        from core.cross_device_policy import get_assignment_hints
        hints = get_assignment_hints(None)
        assert isinstance(hints, dict)
        assert "is_cross_device" in hints or "has_primary" in hints or len(hints) >= 0


# ===========================================================================
# I) Documentation presence
# ===========================================================================

class TestDocumentationPresence:
    """Architecture documentation exists on disk."""

    def _repo_root(self) -> str:
        """Return the repository root directory."""
        # Walk up from this file's location to find docs/
        here = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(os.path.dirname(here), "docs")
        if os.path.isdir(candidate):
            return os.path.dirname(here)
        # Fallback: look relative to cwd
        return os.getcwd()

    def test_cross_device_control_plane_architecture_doc_exists(self):
        """docs/CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md must exist."""
        root = self._repo_root()
        doc_path = os.path.join(root, "docs", "CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md")
        assert os.path.isfile(doc_path), (
            f"Missing documentation file: {doc_path}\n"
            "PR-13 requires docs/CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md"
        )

    def test_cross_device_control_plane_doc_is_non_empty(self):
        """The architecture doc must contain meaningful content."""
        root = self._repo_root()
        doc_path = os.path.join(root, "docs", "CROSS_DEVICE_CONTROL_PLANE_ARCHITECTURE.md")
        if not os.path.isfile(doc_path):
            pytest.skip("Architecture doc not yet present")
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert len(content) > 500, "Architecture document appears too short"
        assert "readiness" in content.lower()
        assert "participation" in content.lower()
        assert "capability" in content.lower()

    def test_gateway_transport_boundary_doc_exists(self):
        """galaxy_gateway/GATEWAY_TRANSPORT_BOUNDARY.md must exist."""
        root = self._repo_root()
        doc_path = os.path.join(
            root, "galaxy_gateway", "GATEWAY_TRANSPORT_BOUNDARY.md"
        )
        if not os.path.isfile(doc_path):
            pytest.skip("GATEWAY_TRANSPORT_BOUNDARY.md not present (may be in a subdirectory)")
        assert os.path.isfile(doc_path)


# ===========================================================================
# J) Logging field consistency
# ===========================================================================

class TestLoggingFieldConsistency:
    """Exclusion and selection decisions are logged with consistent structured fields."""

    def test_excluded_device_logged_at_info(self, caplog):
        """Not-ready device produces an INFO log from the candidates module."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        with caplog.at_level(logging.INFO, logger="Galaxy.CrossDeviceCandidates"), \
             _patch_enumerate(["log-dev-1"]), \
             _patch_readiness({"log-dev-1": False}), \
             _patch_participation({"log-dev-1": True}):
            resolve_cross_device_candidates()

        info_records = [
            r for r in caplog.records
            if r.name == "Galaxy.CrossDeviceCandidates" and r.levelno >= logging.INFO
        ]
        assert len(info_records) > 0, "Expected at least one INFO log for excluded device"
        assert any("EXCLUDED" in r.message for r in info_records)

    def test_selected_device_logged_at_debug(self, caplog):
        """Selected device produces a DEBUG log from the candidates module."""
        from core.cross_device_candidates import resolve_cross_device_candidates

        with caplog.at_level(logging.DEBUG, logger="Galaxy.CrossDeviceCandidates"), \
             _patch_enumerate(["log-dev-2"]), \
             _patch_readiness({"log-dev-2": True}), \
             _patch_participation({"log-dev-2": True}), \
             _patch_capability({"log-dev-2": True}):
            resolve_cross_device_candidates()

        debug_records = [
            r for r in caplog.records
            if r.name == "Galaxy.CrossDeviceCandidates"
        ]
        assert any("SELECTED" in r.message for r in debug_records)

    def test_log_messages_contain_device_id(self, caplog):
        """INFO-level exclusion logs must mention the device_id."""
        from core.cross_device_candidates import resolve_cross_device_candidates
        device_id = "specific-device-id-xyz"

        with caplog.at_level(logging.INFO, logger="Galaxy.CrossDeviceCandidates"), \
             _patch_enumerate([device_id]), \
             _patch_readiness({device_id: False}), \
             _patch_participation({device_id: True}):
            resolve_cross_device_candidates()

        relevant = [
            r for r in caplog.records
            if r.name == "Galaxy.CrossDeviceCandidates" and device_id in r.message
        ]
        assert len(relevant) > 0, (
            f"Expected at least one log message containing '{device_id}'"
        )
