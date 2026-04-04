"""tests/test_post533_pr6_canonical_capability_scheduling_basis.py
====================================================================
Tests for PR package 6 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Device Capability & Scheduling Basis.

Post-533 dual-repo unification track — this is the MAIN-repo side of PR
package 6.

Coverage:
  1. CapabilityTier enum: values, from_string(), safe default for unknowns.
  2. RuntimeCapabilityProfile construction, to_dict(), from_dict() round-trip.
  3. build_runtime_capability_profile() from dict and object inputs.
  4. build_runtime_capability_profile() graceful degradation on broken inputs.
  5. build_scheduling_basis_inputs() normalization of posture, role, tier.
  6. evaluate_execution_surface_eligibility(): observer_only gate.
  7. evaluate_execution_surface_eligibility(): control_only posture gate.
  8. evaluate_execution_surface_eligibility(): capability-requirement gate.
  9. evaluate_execution_surface_eligibility(): eligible (all gates pass).
  10. ExecutionSurfaceEligibility.to_dict() serialization.
  11. runtime_capability_profile_from_scheduling_inputs() round-trip.
  12. Policy sentinels are present.
  13. core.runtime re-exports all PR package 6 symbols.
  14. core.routes.projection has CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6.
  15. Backwards-compatibility: existing fields unaffected; defaults are safe.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _device_dict(**kw: Any) -> dict:
    """Build a standard device registration dict."""
    return {
        "device_id": kw.get("device_id", "dev_001"),
        "name": kw.get("name", "Test Device"),
        "source_runtime_posture": kw.get("source_runtime_posture", "join_runtime"),
        "is_runtime_host": kw.get("is_runtime_host", True),
        "online": kw.get("online", True),
        "capabilities": kw.get("capabilities", ["screen", "camera"]),
        "coordination_role": kw.get("coordination_role", "source_controller"),
    }


def _device_dict_control_only(**kw: Any) -> dict:
    d = _device_dict(**kw)
    d["source_runtime_posture"] = "control_only"
    d["is_runtime_host"] = False
    return d


def _mock_device(
    device_id: str = "dev_mock_001",
    source_runtime_posture: str = "join_runtime",
    is_runtime_host: bool = True,
    online: bool = True,
    capabilities: list | None = None,
    coordination_role: str = "",
    runtime_enabled: bool = True,
    supports_remote_handoff: bool = True,
) -> MagicMock:
    """Mock a RegisteredRuntimeDevice-shaped object."""
    m = MagicMock()
    m.device_id = device_id
    m.source_runtime_posture = source_runtime_posture
    m.is_runtime_host = is_runtime_host
    m.online = online
    m.coordination_role = coordination_role
    m.status = "online" if online else "offline"
    autonomy = MagicMock()
    autonomy.runtime_enabled = runtime_enabled
    autonomy.supports_remote_handoff = supports_remote_handoff
    m.autonomy = autonomy
    caps = MagicMock()
    caps.capabilities = capabilities if capabilities is not None else ["screen", "camera"]
    m.capabilities = caps
    return m


# ---------------------------------------------------------------------------
# 1. CapabilityTier enum
# ---------------------------------------------------------------------------


class TestCapabilityTierEnum:
    """CapabilityTier enum values and from_string() behavior."""

    def test_full_runtime_value(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.full_runtime.value == "full_runtime"

    def test_partial_runtime_value(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.partial_runtime.value == "partial_runtime"

    def test_command_only_value(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.command_only.value == "command_only"

    def test_unknown_value(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.unknown.value == "unknown"

    def test_from_string_full_runtime(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string("full_runtime") == CapabilityTier.full_runtime

    def test_from_string_partial_runtime(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string("partial_runtime") == CapabilityTier.partial_runtime

    def test_from_string_command_only(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string("command_only") == CapabilityTier.command_only

    def test_from_string_unknown_default(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string("garbage_value") == CapabilityTier.unknown

    def test_from_string_none_default(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string(None) == CapabilityTier.unknown  # type: ignore[arg-type]

    def test_from_string_empty_default(self):
        from core.canonical_capability_scheduling_basis import CapabilityTier
        assert CapabilityTier.from_string("") == CapabilityTier.unknown


# ---------------------------------------------------------------------------
# 2. RuntimeCapabilityProfile construction and serialization
# ---------------------------------------------------------------------------


class TestRuntimeCapabilityProfile:
    """RuntimeCapabilityProfile dataclass and serialization."""

    def test_default_construction(self):
        from core.canonical_capability_scheduling_basis import (
            RuntimeCapabilityProfile,
            CapabilityTier,
        )
        p = RuntimeCapabilityProfile(device_id="d1")
        assert p.device_id == "d1"
        assert p.capability_tier == CapabilityTier.unknown
        assert p.source_runtime_posture == "control_only"
        assert p.coordination_role == ""
        assert p.is_runtime_host is False
        assert p.host_present is False
        assert p.declared_capabilities == []
        assert p.resolved_capabilities == []
        assert p.profile_id.startswith("rcap_")

    def test_to_dict_has_all_keys(self):
        from core.canonical_capability_scheduling_basis import (
            RuntimeCapabilityProfile,
            CapabilityTier,
        )
        p = RuntimeCapabilityProfile(
            device_id="d1",
            capability_tier=CapabilityTier.full_runtime,
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            is_runtime_host=True,
            host_present=True,
            declared_capabilities=["screen", "camera"],
            resolved_capabilities=["screen", "camera", "touch"],
        )
        d = p.to_dict()
        assert d["device_id"] == "d1"
        assert d["capability_tier"] == "full_runtime"
        assert d["source_runtime_posture"] == "join_runtime"
        assert d["coordination_role"] == "source_controller"
        assert d["is_runtime_host"] is True
        assert d["host_present"] is True
        assert "screen" in d["declared_capabilities"]
        assert "touch" in d["resolved_capabilities"]

    def test_to_json_round_trip(self):
        from core.canonical_capability_scheduling_basis import (
            RuntimeCapabilityProfile,
            CapabilityTier,
        )
        p = RuntimeCapabilityProfile(
            device_id="d2",
            capability_tier=CapabilityTier.partial_runtime,
            declared_capabilities=["screen"],
        )
        raw = p.to_json()
        data = json.loads(raw)
        assert data["device_id"] == "d2"
        assert data["capability_tier"] == "partial_runtime"

    def test_from_dict_round_trip(self):
        from core.canonical_capability_scheduling_basis import (
            RuntimeCapabilityProfile,
            CapabilityTier,
        )
        p = RuntimeCapabilityProfile(
            device_id="d3",
            capability_tier=CapabilityTier.command_only,
            source_runtime_posture="control_only",
            is_runtime_host=False,
            host_present=False,
            declared_capabilities=["screen"],
        )
        restored = RuntimeCapabilityProfile.from_dict(p.to_dict())
        assert restored.device_id == "d3"
        assert restored.capability_tier == CapabilityTier.command_only
        assert restored.source_runtime_posture == "control_only"
        assert restored.is_runtime_host is False

    def test_from_dict_missing_fields_use_defaults(self):
        from core.canonical_capability_scheduling_basis import (
            RuntimeCapabilityProfile,
            CapabilityTier,
        )
        restored = RuntimeCapabilityProfile.from_dict({"device_id": "d4"})
        assert restored.device_id == "d4"
        assert restored.capability_tier == CapabilityTier.unknown
        assert restored.source_runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# 3. build_runtime_capability_profile() from dict input
# ---------------------------------------------------------------------------


class TestBuildRuntimeCapabilityProfileDict:
    """build_runtime_capability_profile() with dict-shaped inputs."""

    def test_join_runtime_online_yields_full_runtime_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        d = _device_dict(source_runtime_posture="join_runtime", online=True)
        p = build_runtime_capability_profile(d)
        assert p.capability_tier == CapabilityTier.full_runtime
        assert p.source_runtime_posture == "join_runtime"
        assert p.host_present is True

    def test_join_runtime_offline_yields_partial_runtime_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        d = _device_dict(source_runtime_posture="join_runtime", online=False)
        p = build_runtime_capability_profile(d)
        assert p.capability_tier == CapabilityTier.partial_runtime
        assert p.host_present is False

    def test_control_only_with_caps_yields_command_only_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        d = _device_dict_control_only(capabilities=["screen", "touch"], online=True)
        p = build_runtime_capability_profile(d)
        assert p.capability_tier == CapabilityTier.command_only
        assert p.source_runtime_posture == "control_only"

    def test_no_posture_field_defaults_to_control_only(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = {"device_id": "d_noposture", "capabilities": []}
        p = build_runtime_capability_profile(d)
        assert p.source_runtime_posture == "control_only"

    def test_empty_dict_yields_safe_defaults(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        p = build_runtime_capability_profile({})
        assert p.capability_tier == CapabilityTier.unknown
        assert p.source_runtime_posture == "control_only"

    def test_coordination_role_preserved(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = _device_dict(coordination_role="joined_runtime_participant")
        p = build_runtime_capability_profile(d)
        assert p.coordination_role == "joined_runtime_participant"

    def test_unknown_coordination_role_yields_empty(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = _device_dict(coordination_role="something_weird")
        p = build_runtime_capability_profile(d)
        assert p.coordination_role == ""

    def test_autonomy_dict_sets_is_runtime_host(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = {
            "device_id": "d_autonomy",
            "source_runtime_posture": "control_only",
            "autonomy": {"runtime_enabled": True, "supports_remote_handoff": True},
            "online": True,
        }
        p = build_runtime_capability_profile(d)
        assert p.is_runtime_host is True

    def test_status_online_string_sets_host_present(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = {
            "device_id": "d_status",
            "source_runtime_posture": "join_runtime",
            "status": "online",
            "capabilities": [],
        }
        p = build_runtime_capability_profile(d)
        assert p.host_present is True

    def test_declared_capabilities_preserved(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        d = _device_dict(capabilities=["screen", "touch", "camera"])
        p = build_runtime_capability_profile(d)
        assert set(p.declared_capabilities) == {"screen", "touch", "camera"}


# ---------------------------------------------------------------------------
# 4. build_runtime_capability_profile() from object input
# ---------------------------------------------------------------------------


class TestBuildRuntimeCapabilityProfileObject:
    """build_runtime_capability_profile() with object-shaped inputs."""

    def test_mock_join_runtime_online_full_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        m = _mock_device(source_runtime_posture="join_runtime", online=True)
        p = build_runtime_capability_profile(m)
        assert p.capability_tier == CapabilityTier.full_runtime
        assert p.source_runtime_posture == "join_runtime"
        assert p.host_present is True

    def test_mock_control_only_online_command_only(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        m = _mock_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            online=True,
            runtime_enabled=False,
            supports_remote_handoff=False,
            capabilities=["screen"],
        )
        p = build_runtime_capability_profile(m)
        assert p.capability_tier == CapabilityTier.command_only
        assert p.source_runtime_posture == "control_only"

    def test_mock_no_capabilities_unknown_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        m = _mock_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            online=False,
            runtime_enabled=False,
            supports_remote_handoff=False,
            capabilities=[],
        )
        p = build_runtime_capability_profile(m)
        assert p.capability_tier == CapabilityTier.unknown

    def test_mock_autonomy_sets_is_runtime_host(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        m = _mock_device(
            source_runtime_posture="control_only",
            is_runtime_host=False,
            runtime_enabled=True,
            supports_remote_handoff=False,
        )
        p = build_runtime_capability_profile(m)
        assert p.is_runtime_host is True

    def test_broken_object_returns_safe_defaults(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
            CapabilityTier,
        )
        class Broken:
            @property
            def source_runtime_posture(self):
                raise RuntimeError("boom")
        p = build_runtime_capability_profile(Broken())
        assert p.capability_tier == CapabilityTier.unknown
        assert p.source_runtime_posture == "control_only"

    def test_capabilities_as_list_attribute(self):
        from core.canonical_capability_scheduling_basis import (
            build_runtime_capability_profile,
        )
        m = MagicMock()
        m.device_id = "d_listcap"
        m.source_runtime_posture = "join_runtime"
        m.is_runtime_host = True
        m.online = True
        m.status = "online"
        m.coordination_role = ""
        m.autonomy = None
        m.capabilities = ["screen", "touch"]
        p = build_runtime_capability_profile(m)
        assert "screen" in p.declared_capabilities
        assert "touch" in p.declared_capabilities


# ---------------------------------------------------------------------------
# 5. build_scheduling_basis_inputs() normalization
# ---------------------------------------------------------------------------


class TestBuildSchedulingBasisInputs:
    """build_scheduling_basis_inputs() normalization behavior."""

    def test_join_runtime_host_present_yields_full_runtime_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d1",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        assert inputs.source_runtime_posture == "join_runtime"
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_join_runtime_no_host_partial_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d2",
            source_runtime_posture="join_runtime",
            host_present=False,
        )
        assert inputs.capability_tier == CapabilityTier.partial_runtime

    def test_unknown_posture_defaults_control_only(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d3",
            source_runtime_posture="something_weird",
        )
        assert inputs.source_runtime_posture == "control_only"

    def test_observer_only_role_preserved(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d4",
            coordination_role="observer_only",
        )
        assert inputs.coordination_role == "observer_only"

    def test_unknown_role_returns_empty(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d5",
            coordination_role="alien_role",
        )
        assert inputs.coordination_role == ""

    def test_explicit_tier_override_respected(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d6",
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.full_runtime,
        )
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_required_capabilities_stored(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d7",
            required_capabilities=["screen", "camera"],
        )
        assert "screen" in inputs.required_capabilities
        assert "camera" in inputs.required_capabilities

    def test_to_dict_serializable(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="d8",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        d = inputs.to_dict()
        assert d["device_id"] == "d8"
        assert d["source_runtime_posture"] == "join_runtime"
        assert d["host_present"] is True


# ---------------------------------------------------------------------------
# 6. evaluate_execution_surface_eligibility(): observer_only gate
# ---------------------------------------------------------------------------


class TestEvaluateEligibilityObserverOnly:
    """observer_only coordination role always ineligible."""

    def test_observer_only_ineligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="obs_1",
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert "observer_only" in result.blocking_reason

    def test_observer_only_ineligible_even_with_full_tier(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="obs_2",
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            capability_tier=CapabilityTier.full_runtime,
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False

    def test_observer_only_policy_applied(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="obs_3",
            coordination_role="observer_only",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.policy_applied == OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY


# ---------------------------------------------------------------------------
# 7. evaluate_execution_surface_eligibility(): control_only posture gate
# ---------------------------------------------------------------------------


class TestEvaluateEligibilityControlOnly:
    """control_only posture blocks local execution."""

    def test_control_only_ineligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="ctrl_1",
            source_runtime_posture="control_only",
            coordination_role="source_controller",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert "control_only" in result.blocking_reason

    def test_control_only_ineligible_regardless_of_capabilities(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="ctrl_2",
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.full_runtime,
            declared_capabilities=["screen", "camera"],
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False

    def test_control_only_posture_policy_applied(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="ctrl_3",
            source_runtime_posture="control_only",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.policy_applied == POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY


# ---------------------------------------------------------------------------
# 8. evaluate_execution_surface_eligibility(): capability gate
# ---------------------------------------------------------------------------


class TestEvaluateEligibilityCapabilities:
    """Capability requirement gate."""

    def test_missing_required_capability_ineligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="cap_1",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            host_present=True,
            declared_capabilities=["screen"],
        )
        result = evaluate_execution_surface_eligibility(
            inputs, required_capabilities=["screen", "camera"]
        )
        assert result.eligible is False
        assert "camera" in result.missing_capabilities
        assert result.capabilities_met is False

    def test_all_required_capabilities_met_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="cap_2",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            host_present=True,
            declared_capabilities=["screen", "camera", "touch"],
        )
        result = evaluate_execution_surface_eligibility(
            inputs, required_capabilities=["screen", "camera"]
        )
        assert result.eligible is True
        assert result.capabilities_met is True
        assert result.missing_capabilities == []

    def test_empty_required_capabilities_no_gate(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="cap_3",
            source_runtime_posture="join_runtime",
            host_present=True,
            declared_capabilities=[],
        )
        result = evaluate_execution_surface_eligibility(inputs, required_capabilities=[])
        assert result.eligible is True

    def test_capability_check_case_insensitive(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="cap_4",
            source_runtime_posture="join_runtime",
            host_present=True,
            declared_capabilities=["Screen", "Camera"],
        )
        result = evaluate_execution_surface_eligibility(
            inputs, required_capabilities=["screen", "camera"]
        )
        assert result.eligible is True


# ---------------------------------------------------------------------------
# 9. evaluate_execution_surface_eligibility(): eligible (all gates pass)
# ---------------------------------------------------------------------------


class TestEvaluateEligibilityEligible:
    """All gates pass → eligible result."""

    def test_join_runtime_participant_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="elig_1",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            host_present=True,
            declared_capabilities=["screen"],
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.blocking_reason == ""

    def test_source_controller_join_runtime_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="elig_2",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            host_present=True,
            declared_capabilities=["screen", "camera"],
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True

    def test_target_only_executor_join_runtime_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="elig_3",
            source_runtime_posture="join_runtime",
            coordination_role="target_only_executor",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True

    def test_no_coordination_role_join_runtime_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="elig_4",
            source_runtime_posture="join_runtime",
            coordination_role="",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True


# ---------------------------------------------------------------------------
# 10. ExecutionSurfaceEligibility.to_dict() serialization
# ---------------------------------------------------------------------------


class TestExecutionSurfaceEligibilityToDict:
    """ExecutionSurfaceEligibility.to_dict() serialization."""

    def test_to_dict_eligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="serial_1",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        d = result.to_dict()
        assert d["device_id"] == "serial_1"
        assert d["eligible"] is True
        assert "evaluation_id" in d
        assert "capability_tier" in d
        assert "blocking_reason" in d
        assert "policy_applied" in d
        assert "capabilities_met" in d
        assert "missing_capabilities" in d

    def test_to_dict_ineligible(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="serial_2",
            source_runtime_posture="control_only",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        d = result.to_dict()
        assert d["eligible"] is False
        assert d["blocking_reason"] != ""

    def test_evaluation_id_unique(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="serial_3",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        r1 = evaluate_execution_surface_eligibility(inputs)
        r2 = evaluate_execution_surface_eligibility(inputs)
        assert r1.evaluation_id != r2.evaluation_id

    def test_json_serializable(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="serial_json",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        # Should not raise
        encoded = json.dumps(result.to_dict())
        decoded = json.loads(encoded)
        assert decoded["device_id"] == "serial_json"


# ---------------------------------------------------------------------------
# 11. runtime_capability_profile_from_scheduling_inputs() round-trip
# ---------------------------------------------------------------------------


class TestRuntimeCapabilityProfileFromSchedulingInputs:
    """runtime_capability_profile_from_scheduling_inputs() round-trip."""

    def test_profile_matches_inputs(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            runtime_capability_profile_from_scheduling_inputs,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="rt_1",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            host_present=True,
            declared_capabilities=["screen", "touch"],
            is_runtime_host=True,
        )
        profile = runtime_capability_profile_from_scheduling_inputs(inputs)
        assert profile.device_id == "rt_1"
        assert profile.source_runtime_posture == "join_runtime"
        assert profile.coordination_role == "joined_runtime_participant"
        assert profile.capability_tier == CapabilityTier.full_runtime
        assert profile.is_runtime_host is True
        assert "screen" in profile.declared_capabilities

    def test_profile_to_dict_round_trip(self):
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            runtime_capability_profile_from_scheduling_inputs,
            RuntimeCapabilityProfile,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="rt_2",
            source_runtime_posture="join_runtime",
            host_present=True,
        )
        profile = runtime_capability_profile_from_scheduling_inputs(inputs)
        restored = RuntimeCapabilityProfile.from_dict(profile.to_dict())
        assert restored.device_id == "rt_2"
        assert restored.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# 12. Policy sentinels are present
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    """All policy sentinels are present and non-empty strings."""

    @pytest.mark.parametrize("sentinel_name", [
        "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
        "CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY",
        "POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY",
        "COORDINATION_ROLE_GATES_ORCHESTRATION_PARTICIPATION_POLICY",
        "HOST_PRESENCE_REQUIRED_FOR_FULL_RUNTIME_POLICY",
        "OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY",
        "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
    ])
    def test_sentinel_is_nonempty_string(self, sentinel_name: str):
        import importlib
        mod = importlib.import_module("core.canonical_capability_scheduling_basis")
        val = getattr(mod, sentinel_name)
        assert isinstance(val, str)
        assert len(val) > 20, f"{sentinel_name} looks too short"


# ---------------------------------------------------------------------------
# 13. core.runtime re-exports all PR package 6 symbols
# ---------------------------------------------------------------------------


class TestCoreRuntimeReexports:
    """core.runtime must re-export all canonical capability/scheduling symbols."""

    @pytest.mark.parametrize("symbol", [
        "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
        "CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY",
        "POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY",
        "COORDINATION_ROLE_GATES_ORCHESTRATION_PARTICIPATION_POLICY",
        "HOST_PRESENCE_REQUIRED_FOR_FULL_RUNTIME_POLICY",
        "OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY",
        "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
        "CapabilityTier",
        "RuntimeCapabilityProfile",
        "SchedulingBasisInputs",
        "ExecutionSurfaceEligibility",
        "build_runtime_capability_profile",
        "build_scheduling_basis_inputs",
        "evaluate_execution_surface_eligibility",
        "runtime_capability_profile_from_scheduling_inputs",
    ])
    def test_symbol_accessible_via_core_runtime(self, symbol: str):
        import core.runtime as rt
        assert hasattr(rt, symbol), f"core.runtime missing symbol: {symbol}"


# ---------------------------------------------------------------------------
# 14. core.routes.projection has PR6 sentinel
# ---------------------------------------------------------------------------


class TestProjectionRoutesSentinel:
    """core.routes.projection must expose CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6."""

    def test_sentinel_present(self):
        from core.routes.projection import CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
        assert isinstance(CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6, str)
        assert len(CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6) > 10

    def test_sentinel_is_v1_when_module_available(self):
        from core.routes.projection import CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
        # When the module is importable (always true in this test suite),
        # the sentinel should contain "V1" indicating the live path was taken.
        assert "V1" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6


# ---------------------------------------------------------------------------
# 15. Backwards-compatibility: existing fields unaffected; defaults are safe
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    """Ensure new module does not break existing contracts."""

    def test_source_execution_eligibility_unaffected(self):
        """core.source_execution_eligibility still works independently."""
        from core.source_execution_eligibility import (
            check_source_execution_eligibility,
            SourceExecutionEligibility,
        )
        result = check_source_execution_eligibility("join_runtime")
        assert isinstance(result, SourceExecutionEligibility)
        assert result.eligible is True

    def test_android_runtime_host_unaffected(self):
        """core.android_runtime_host still works independently."""
        from core.android_runtime_host import (
            classify_android_runtime_host,
            AndroidRuntimeHostRole,
        )
        d = {"device_id": "bc_ph", "source_runtime_posture": "join_runtime", "online": True}
        role = classify_android_runtime_host(d)
        assert role == AndroidRuntimeHostRole.FULL_RUNTIME_HOST

    def test_capability_tier_unknown_safe_for_scheduling(self):
        """unknown tier does not crash evaluation."""
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            CapabilityTier,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="bc_unk",
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.unknown,
            host_present=False,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        # Should not raise; eligible because join_runtime and no observer/cap gate
        assert isinstance(result.eligible, bool)

    def test_none_posture_yields_control_only(self):
        """None posture safely degrades to control_only."""
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="bc_none",
            source_runtime_posture=None,  # type: ignore[arg-type]
        )
        assert inputs.source_runtime_posture == "control_only"

    def test_multi_device_coordination_authority_unaffected(self):
        """core.multi_device_coordination_authority still works."""
        from core.multi_device_coordination_authority import (
            derive_coordination_role,
            CoordinationRole,
        )
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            formation_role="source_device",
        )
        assert role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT

    def test_required_caps_override_in_evaluate(self):
        """required_capabilities kwarg overrides inputs.required_capabilities."""
        from core.canonical_capability_scheduling_basis import (
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
        )
        inputs = build_scheduling_basis_inputs(
            device_id="bc_cap_override",
            source_runtime_posture="join_runtime",
            host_present=True,
            declared_capabilities=["screen"],
            required_capabilities=["screen"],  # would pass from inputs alone
        )
        # Override with harder requirement
        result = evaluate_execution_surface_eligibility(
            inputs, required_capabilities=["screen", "camera"]
        )
        assert result.eligible is False
        assert "camera" in result.missing_capabilities
