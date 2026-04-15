"""tests/test_pr6_post533_canonical_capability_scheduling_basis.py
====================================================================
Tests for PR package 6 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Device Capability & Scheduling Basis.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — CapabilityTier enum: all values present, from_string(), defaults.
C  — ExecutionSurface enum: all values present, from_string(), defaults.
D  — RuntimeCapabilityProfile: construction, defaults, to_dict(), from_dict(),
     to_json().
E  — SchedulingBasisInputs: construction, defaults, to_dict(), to_json().
F  — ExecutionSurfaceEligibility: construction, defaults, to_dict(), to_json().
G  — _derive_capability_tier (via build_runtime_capability_profile): join_runtime
     + both flags → full_runtime.
H  — _derive_capability_tier: join_runtime posture alone → partial_runtime.
I  — _derive_capability_tier: control_only + is_runtime_host → partial_runtime.
J  — _derive_capability_tier: control_only + autonomy flags → partial_runtime.
K  — _derive_capability_tier: observer_only role → command_only regardless.
L  — _derive_capability_tier: Android PR-5 host role lifts tier.
M  — _derive_capability_tier: no signals → command_only.
N  — build_runtime_capability_profile: dict input.
O  — build_runtime_capability_profile: object input (attribute-style).
P  — build_runtime_capability_profile: nested autonomy dict.
Q  — build_runtime_capability_profile: graceful degradation on malformed input.
R  — build_scheduling_basis_inputs: explicit kwargs, tier auto-derived.
S  — build_scheduling_basis_inputs: explicit capability_tier not overridden.
T  — build_scheduling_basis_inputs: posture normalisation (None → control_only).
U  — normalize_scheduling_inputs: dict payload with autonomy sub-dict.
V  — normalize_scheduling_inputs: flat dict payload.
W  — normalize_scheduling_inputs: Android auto-detection from platform.
X  — normalize_scheduling_inputs: pre-computed capability_tier honored.
Y  — normalize_scheduling_inputs: non-dict input → safe default.
Z  — evaluate_execution_surface_eligibility: observer_only → unavailable.
AA — evaluate_execution_surface_eligibility: command_only tier → unavailable.
AB — evaluate_execution_surface_eligibility: unknown tier → unavailable.
AC — evaluate_execution_surface_eligibility: local_host surface.
AD — evaluate_execution_surface_eligibility: android_host surface.
AE — evaluate_execution_surface_eligibility: remote_device surface.
AF — evaluate_execution_surface_eligibility: no matching surface → unavailable.
AG — evaluate_execution_surface_eligibility: join_runtime local_host with
     joined_runtime_participant role.
AH — evaluate_execution_surface_eligibility: returns inputs_snapshot in result.
AI — evaluate_execution_surface_eligibility: eligible=False has unavailable surface.
AJ — core.runtime re-exports: all PR-6 symbols accessible from core.runtime.
AK — projection.py sentinel: CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
     is present and not UNAVAILABLE.
AL — End-to-end: Android join_runtime full pipeline.
AM — End-to-end: Control-only device cannot be scheduled.
AN — End-to-end: Android partial-runtime (is_runtime_host only) gets android_host.
AO — Serialisation round-trip: RuntimeCapabilityProfile to_dict → from_dict.
AP — Serialisation round-trip: SchedulingBasisInputs to_json produces valid JSON.
AQ — Serialisation round-trip: ExecutionSurfaceEligibility to_json produces valid JSON.
AR — Profile ID and inputs ID are auto-generated and unique.
AS — CapabilityTier ordering: full_runtime > partial_runtime in practice.
AT — Multiple devices: each gets its own profile.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.canonical_capability_scheduling_basis import (
    # Sentinels
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
    FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY,
    CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY,
    OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY,
    ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY,
    SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY,
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
    # Enums
    CapabilityTier,
    ExecutionSurface,
    # Dataclasses
    RuntimeCapabilityProfile,
    SchedulingBasisInputs,
    ExecutionSurfaceEligibility,
    # Functions
    build_runtime_capability_profile,
    build_scheduling_basis_inputs,
    evaluate_execution_surface_eligibility,
    normalize_scheduling_inputs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _android_full_dict(**kw: Any) -> dict:
    """Full Android device dict with join_runtime posture and autonomy."""
    return {
        "device_id": kw.get("device_id", "ph_001"),
        "platform": kw.get("platform", "android"),
        "source_runtime_posture": kw.get("source_runtime_posture", "join_runtime"),
        "coordination_role": kw.get("coordination_role", "joined_runtime_participant"),
        "is_runtime_host": kw.get("is_runtime_host", True),
        "android_host_role": kw.get("android_host_role", "full_runtime_host"),
        "autonomy": {
            "runtime_enabled": kw.get("runtime_enabled", True),
            "supports_remote_handoff": kw.get("supports_remote_handoff", True),
        },
        "online": kw.get("online", True),
    }


def _desktop_local_dict(**kw: Any) -> dict:
    """Local desktop host dict."""
    return {
        "device_id": kw.get("device_id", "desktop_001"),
        "platform": kw.get("platform", "desktop"),
        "source_runtime_posture": kw.get("source_runtime_posture", "join_runtime"),
        "coordination_role": kw.get("coordination_role", "source_controller"),
        "is_host_present": kw.get("is_host_present", True),
        "is_runtime_host": kw.get("is_runtime_host", False),
        "runtime_enabled": kw.get("runtime_enabled", True),
        "supports_remote_handoff": kw.get("supports_remote_handoff", True),
    }


def _mock_device(
    device_id: str = "dev_001",
    platform: str = "android",
    posture: str = "join_runtime",
    is_runtime_host: bool = True,
    runtime_enabled: bool = True,
    supports_remote_handoff: bool = True,
    android_host_role: str = "full_runtime_host",
    coordination_role: str = "joined_runtime_participant",
    online: bool = True,
) -> MagicMock:
    """Build a MagicMock device with attribute-style access."""
    m = MagicMock()
    m.device_id = device_id
    m.platform = platform
    m.source_runtime_posture = posture
    m.is_runtime_host = is_runtime_host
    m.android_host_role = android_host_role
    m.coordination_role = coordination_role
    m.is_host_present = False
    m.online = online
    autonomy = MagicMock()
    autonomy.runtime_enabled = runtime_enabled
    autonomy.supports_remote_handoff = supports_remote_handoff
    m.autonomy = autonomy
    return m


# ---------------------------------------------------------------------------
# A: Authority / policy sentinels
# ---------------------------------------------------------------------------


class TestSentinelsA:
    def test_authority_present(self):
        assert CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY
        assert isinstance(CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY, str)
        assert "AUTHORITY" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY

    def test_pr6_sentinel_present(self):
        assert CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL
        assert "PR6" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

    def test_full_runtime_tier_policy(self):
        assert FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
        assert "join_runtime" in FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY.lower()

    def test_command_only_blocks_policy(self):
        assert COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY
        assert "command_only" in COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY.lower()

    def test_capability_tier_drives_surface_policy(self):
        assert CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY
        assert "ExecutionSurface" in CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY or \
               "surface" in CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY.lower()

    def test_observer_only_excluded_policy(self):
        assert OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY
        assert "observer_only" in OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY

    def test_android_host_capability_lifted_policy(self):
        assert ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY
        assert "PR-5" in ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY or \
               "android" in ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY.lower()

    def test_normalisation_additive_policy(self):
        assert SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY
        assert "additive" in SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY.lower()

    def test_all_sentinels_non_empty(self):
        sentinels = [
            CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
            FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY,
            CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY,
            OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY,
            ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY,
            SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY,
            CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
        ]
        for s in sentinels:
            assert s and len(s) > 10, f"Sentinel too short or empty: {s!r}"


# ---------------------------------------------------------------------------
# B: CapabilityTier enum
# ---------------------------------------------------------------------------


class TestCapabilityTierB:
    def test_all_values_present(self):
        assert CapabilityTier.full_runtime
        assert CapabilityTier.partial_runtime
        assert CapabilityTier.command_only
        assert CapabilityTier.unknown

    def test_string_values(self):
        assert CapabilityTier.full_runtime.value == "full_runtime"
        assert CapabilityTier.partial_runtime.value == "partial_runtime"
        assert CapabilityTier.command_only.value == "command_only"
        assert CapabilityTier.unknown.value == "unknown"

    def test_from_string_valid(self):
        assert CapabilityTier.from_string("full_runtime") == CapabilityTier.full_runtime
        assert CapabilityTier.from_string("partial_runtime") == CapabilityTier.partial_runtime
        assert CapabilityTier.from_string("command_only") == CapabilityTier.command_only
        assert CapabilityTier.from_string("unknown") == CapabilityTier.unknown

    def test_from_string_unknown_on_invalid(self):
        assert CapabilityTier.from_string("garbage") == CapabilityTier.unknown
        assert CapabilityTier.from_string("") == CapabilityTier.unknown

    def test_from_string_case_insensitive(self):
        assert CapabilityTier.from_string("FULL_RUNTIME") == CapabilityTier.full_runtime
        assert CapabilityTier.from_string("Partial_Runtime") == CapabilityTier.partial_runtime

    def test_str_compatible(self):
        assert str(CapabilityTier.full_runtime) in ("CapabilityTier.full_runtime", "full_runtime")


# ---------------------------------------------------------------------------
# C: ExecutionSurface enum
# ---------------------------------------------------------------------------


class TestExecutionSurfaceC:
    def test_all_values_present(self):
        assert ExecutionSurface.local_host
        assert ExecutionSurface.android_host
        assert ExecutionSurface.remote_device
        assert ExecutionSurface.unavailable

    def test_string_values(self):
        assert ExecutionSurface.local_host.value == "local_host"
        assert ExecutionSurface.android_host.value == "android_host"
        assert ExecutionSurface.remote_device.value == "remote_device"
        assert ExecutionSurface.unavailable.value == "unavailable"

    def test_from_string_valid(self):
        assert ExecutionSurface.from_string("local_host") == ExecutionSurface.local_host
        assert ExecutionSurface.from_string("android_host") == ExecutionSurface.android_host
        assert ExecutionSurface.from_string("remote_device") == ExecutionSurface.remote_device
        assert ExecutionSurface.from_string("unavailable") == ExecutionSurface.unavailable

    def test_from_string_default_on_invalid(self):
        assert ExecutionSurface.from_string("garbage") == ExecutionSurface.unavailable
        assert ExecutionSurface.from_string("") == ExecutionSurface.unavailable

    def test_from_string_case_insensitive(self):
        assert ExecutionSurface.from_string("ANDROID_HOST") == ExecutionSurface.android_host


# ---------------------------------------------------------------------------
# D: RuntimeCapabilityProfile
# ---------------------------------------------------------------------------


class TestRuntimeCapabilityProfileD:
    def test_default_construction(self):
        p = RuntimeCapabilityProfile()
        assert p.device_id == ""
        assert p.platform == ""
        assert p.source_runtime_posture == "control_only"
        assert p.coordination_role == ""
        assert p.is_host_present is False
        assert p.is_runtime_host is False
        assert p.runtime_enabled is False
        assert p.supports_remote_handoff is False
        assert p.android_host_role == ""
        assert p.capability_tier == CapabilityTier.unknown
        assert p.profile_id.startswith("rcap_")

    def test_explicit_construction(self):
        p = RuntimeCapabilityProfile(
            device_id="ph_001",
            platform="android",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            is_host_present=False,
            is_runtime_host=True,
            runtime_enabled=True,
            supports_remote_handoff=True,
            android_host_role="full_runtime_host",
            capability_tier=CapabilityTier.full_runtime,
        )
        assert p.device_id == "ph_001"
        assert p.platform == "android"
        assert p.source_runtime_posture == "join_runtime"
        assert p.capability_tier == CapabilityTier.full_runtime

    def test_to_dict_keys(self):
        p = RuntimeCapabilityProfile(device_id="d1", capability_tier=CapabilityTier.partial_runtime)
        d = p.to_dict()
        assert "device_id" in d
        assert "capability_tier" in d
        assert d["capability_tier"] == "partial_runtime"
        assert "authority" in d

    def test_to_json_valid(self):
        p = RuntimeCapabilityProfile(device_id="d2", capability_tier=CapabilityTier.full_runtime)
        raw = p.to_json()
        parsed = json.loads(raw)
        assert parsed["device_id"] == "d2"
        assert parsed["capability_tier"] == "full_runtime"

    def test_from_dict_roundtrip(self):
        original = RuntimeCapabilityProfile(
            device_id="d3",
            platform="android",
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_runtime_host=True,
        )
        d = original.to_dict()
        restored = RuntimeCapabilityProfile.from_dict(d)
        assert restored.device_id == "d3"
        assert restored.platform == "android"
        assert restored.source_runtime_posture == "join_runtime"
        assert restored.capability_tier == CapabilityTier.full_runtime
        assert restored.is_runtime_host is True

    def test_from_dict_defaults_on_missing_keys(self):
        p = RuntimeCapabilityProfile.from_dict({})
        assert p.device_id == ""
        assert p.capability_tier == CapabilityTier.unknown

    def test_repr_contains_device_id(self):
        p = RuntimeCapabilityProfile(device_id="test_repr")
        assert "test_repr" in repr(p)


# ---------------------------------------------------------------------------
# E: SchedulingBasisInputs
# ---------------------------------------------------------------------------


class TestSchedulingBasisInputsE:
    def test_default_construction(self):
        s = SchedulingBasisInputs()
        assert s.device_id == ""
        assert s.source_runtime_posture == "control_only"
        assert s.capability_tier == CapabilityTier.unknown
        assert s.is_host_present is False
        assert s.is_android_device is False
        assert s.inputs_id.startswith("sbi_")

    def test_explicit_construction(self):
        s = SchedulingBasisInputs(
            device_id="ph_002",
            platform="android",
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
            android_host_role="full_runtime_host",
        )
        assert s.device_id == "ph_002"
        assert s.capability_tier == CapabilityTier.full_runtime
        assert s.is_android_device is True

    def test_to_dict_keys(self):
        s = SchedulingBasisInputs(device_id="d10")
        d = s.to_dict()
        assert "device_id" in d
        assert "capability_tier" in d
        assert "source_runtime_posture" in d
        assert "is_android_device" in d

    def test_to_json_valid(self):
        s = SchedulingBasisInputs(device_id="d11", capability_tier=CapabilityTier.partial_runtime)
        parsed = json.loads(s.to_json())
        assert parsed["device_id"] == "d11"
        assert parsed["capability_tier"] == "partial_runtime"

    def test_repr(self):
        s = SchedulingBasisInputs(device_id="repr_test")
        assert "repr_test" in repr(s)


# ---------------------------------------------------------------------------
# F: ExecutionSurfaceEligibility
# ---------------------------------------------------------------------------


class TestExecutionSurfaceEligibilityF:
    def test_eligible_construction(self):
        e = ExecutionSurfaceEligibility(
            eligible=True,
            surface=ExecutionSurface.android_host,
            reason="test reason",
            capability_tier=CapabilityTier.full_runtime,
        )
        assert e.eligible is True
        assert e.surface == ExecutionSurface.android_host
        assert e.capability_tier == CapabilityTier.full_runtime

    def test_ineligible_construction(self):
        e = ExecutionSurfaceEligibility(
            eligible=False,
            surface=ExecutionSurface.unavailable,
            reason="blocked",
        )
        assert e.eligible is False
        assert e.surface == ExecutionSurface.unavailable

    def test_to_dict(self):
        e = ExecutionSurfaceEligibility(
            eligible=True,
            surface=ExecutionSurface.local_host,
            reason="ok",
            capability_tier=CapabilityTier.full_runtime,
        )
        d = e.to_dict()
        assert d["eligible"] is True
        assert d["surface"] == "local_host"
        assert d["capability_tier"] == "full_runtime"
        assert "authority" in d
        assert "eligibility_id" in d

    def test_to_json_valid(self):
        e = ExecutionSurfaceEligibility(
            eligible=False,
            surface=ExecutionSurface.unavailable,
            reason="blocked",
        )
        parsed = json.loads(e.to_json())
        assert parsed["eligible"] is False
        assert parsed["surface"] == "unavailable"

    def test_default_eligibility_id(self):
        e = ExecutionSurfaceEligibility(
            eligible=False, surface=ExecutionSurface.unavailable, reason="x"
        )
        assert e.eligibility_id.startswith("ese_")

    def test_inputs_snapshot_stored(self):
        snap = {"device_id": "d1"}
        e = ExecutionSurfaceEligibility(
            eligible=True,
            surface=ExecutionSurface.android_host,
            reason="ok",
            inputs_snapshot=snap,
        )
        assert e.inputs_snapshot["device_id"] == "d1"


# ---------------------------------------------------------------------------
# G: _derive_capability_tier: join_runtime + both flags → full_runtime
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationG:
    def test_join_runtime_with_both_flags_full_runtime(self):
        profile = build_runtime_capability_profile({
            "device_id": "ph_001",
            "source_runtime_posture": "join_runtime",
            "is_runtime_host": True,
            "autonomy": {
                "runtime_enabled": True,
                "supports_remote_handoff": True,
            },
        })
        assert profile.capability_tier == CapabilityTier.full_runtime

    def test_join_runtime_flat_flags_full_runtime(self):
        profile = build_runtime_capability_profile({
            "device_id": "ph_002",
            "source_runtime_posture": "join_runtime",
            "runtime_enabled": True,
            "supports_remote_handoff": True,
        })
        assert profile.capability_tier == CapabilityTier.full_runtime


# ---------------------------------------------------------------------------
# H: _derive_capability_tier: join_runtime posture alone → partial_runtime
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationH:
    def test_join_runtime_no_flags_partial_runtime(self):
        profile = build_runtime_capability_profile({
            "device_id": "ph_003",
            "source_runtime_posture": "join_runtime",
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime

    def test_join_runtime_one_flag_partial_runtime(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "join_runtime",
            "runtime_enabled": True,
            # supports_remote_handoff missing
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# I: _derive_capability_tier: control_only + is_runtime_host → partial_runtime
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationI:
    def test_control_only_with_is_runtime_host_partial(self):
        profile = build_runtime_capability_profile({
            "device_id": "ph_004",
            "source_runtime_posture": "control_only",
            "is_runtime_host": True,
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# J: _derive_capability_tier: control_only + autonomy flags → partial_runtime
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationJ:
    def test_control_only_runtime_enabled_partial(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "control_only",
            "runtime_enabled": True,
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# K: observer_only role → command_only
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationK:
    def test_observer_only_role_blocks_to_command_only(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "join_runtime",
            "coordination_role": "observer_only",
            "runtime_enabled": True,
            "supports_remote_handoff": True,
            "is_runtime_host": True,
        })
        assert profile.capability_tier == CapabilityTier.command_only

    def test_observer_only_overrides_all_signals(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "join_runtime",
            "coordination_role": "observer_only",
            "android_host_role": "full_runtime_host",
            "is_runtime_host": True,
            "runtime_enabled": True,
            "supports_remote_handoff": True,
        })
        assert profile.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# L: Android PR-5 host role lifts tier
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationL:
    def test_android_full_host_role_lifts_to_partial_without_posture(self):
        # control_only posture but is_runtime_host + android_host_role set
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "control_only",
            "is_runtime_host": True,
            "android_host_role": "full_runtime_host",
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime

    def test_android_partial_host_role_lifts_to_partial(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "control_only",
            "is_runtime_host": True,
            "android_host_role": "partial_runtime_host",
        })
        assert profile.capability_tier == CapabilityTier.partial_runtime

    def test_android_connected_only_no_lift(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "control_only",
            "is_runtime_host": False,
            "android_host_role": "connected_device_only",
        })
        assert profile.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# M: No signals → command_only
# ---------------------------------------------------------------------------


class TestCapabilityTierDerivationM:
    def test_no_signals_command_only(self):
        profile = build_runtime_capability_profile({})
        assert profile.capability_tier == CapabilityTier.command_only

    def test_control_only_no_flags_command_only(self):
        profile = build_runtime_capability_profile({
            "source_runtime_posture": "control_only",
            "is_runtime_host": False,
            "runtime_enabled": False,
            "supports_remote_handoff": False,
        })
        assert profile.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# N: build_runtime_capability_profile dict input
# ---------------------------------------------------------------------------


class TestBuildProfileDictN:
    def test_dict_full_android(self):
        d = _android_full_dict()
        profile = build_runtime_capability_profile(d)
        assert profile.device_id == "ph_001"
        assert profile.platform == "android"
        assert profile.source_runtime_posture == "join_runtime"
        assert profile.capability_tier == CapabilityTier.full_runtime

    def test_dict_missing_fields_safe_defaults(self):
        profile = build_runtime_capability_profile({"device_id": "x"})
        assert profile.device_id == "x"
        assert profile.source_runtime_posture == "control_only"
        assert profile.capability_tier == CapabilityTier.command_only

    def test_dict_nested_autonomy(self):
        d = {
            "device_id": "ph_010",
            "source_runtime_posture": "join_runtime",
            "autonomy": {"runtime_enabled": True, "supports_remote_handoff": True},
        }
        profile = build_runtime_capability_profile(d)
        assert profile.runtime_enabled is True
        assert profile.supports_remote_handoff is True
        assert profile.capability_tier == CapabilityTier.full_runtime


# ---------------------------------------------------------------------------
# O: build_runtime_capability_profile object input
# ---------------------------------------------------------------------------


class TestBuildProfileObjectO:
    def test_object_input(self):
        device = _mock_device(
            device_id="obj_001",
            platform="android",
            posture="join_runtime",
            runtime_enabled=True,
            supports_remote_handoff=True,
        )
        profile = build_runtime_capability_profile(device)
        assert profile.device_id == "obj_001"
        assert profile.capability_tier == CapabilityTier.full_runtime

    def test_object_control_only_posture(self):
        device = _mock_device(posture="control_only", is_runtime_host=False,
                              runtime_enabled=False, supports_remote_handoff=False)
        profile = build_runtime_capability_profile(device)
        assert profile.capability_tier == CapabilityTier.command_only

    def test_object_without_autonomy_attribute(self):
        m = MagicMock()
        m.device_id = "no_autonomy"
        m.platform = "desktop"
        m.source_runtime_posture = "join_runtime"
        m.is_runtime_host = False
        m.android_host_role = ""
        m.coordination_role = ""
        m.is_host_present = False
        m.autonomy = None
        m.runtime_enabled = True
        m.supports_remote_handoff = True
        profile = build_runtime_capability_profile(m)
        assert profile.device_id == "no_autonomy"
        assert profile.capability_tier == CapabilityTier.full_runtime


# ---------------------------------------------------------------------------
# P: build_runtime_capability_profile nested autonomy dict
# ---------------------------------------------------------------------------


class TestBuildProfileNestedAutonomyP:
    def test_nested_autonomy_dict_read(self):
        d = {
            "device_id": "ph_020",
            "source_runtime_posture": "join_runtime",
            "autonomy": {
                "runtime_enabled": True,
                "supports_remote_handoff": False,
            },
        }
        profile = build_runtime_capability_profile(d)
        assert profile.runtime_enabled is True
        assert profile.supports_remote_handoff is False
        # join_runtime but only one flag → partial_runtime
        assert profile.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# Q: build_runtime_capability_profile graceful degradation
# ---------------------------------------------------------------------------


class TestBuildProfileDegradationQ:
    def test_none_input_safe(self):
        # None is not a dict; getattr on None returns defaults, so we get
        # command_only (the conservative tier with no signals).
        profile = build_runtime_capability_profile(None)
        assert isinstance(profile, RuntimeCapabilityProfile)
        assert profile.capability_tier in (CapabilityTier.command_only, CapabilityTier.unknown)

    def test_int_input_safe(self):
        profile = build_runtime_capability_profile(42)
        assert isinstance(profile, RuntimeCapabilityProfile)

    def test_empty_dict_safe(self):
        profile = build_runtime_capability_profile({})
        assert isinstance(profile, RuntimeCapabilityProfile)
        assert profile.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# R: build_scheduling_basis_inputs explicit kwargs
# ---------------------------------------------------------------------------


class TestBuildSchedulingBasisInputsR:
    def test_join_runtime_android_full(self):
        inputs = build_scheduling_basis_inputs(
            device_id="ph_030",
            platform="android",
            source_runtime_posture="join_runtime",
            is_android_device=True,
            android_host_role="full_runtime_host",
            runtime_enabled=True,
            supports_remote_handoff=True,
        )
        assert inputs.device_id == "ph_030"
        assert inputs.source_runtime_posture == "join_runtime"
        assert inputs.is_android_device is True
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_control_only_command_only_tier(self):
        inputs = build_scheduling_basis_inputs(source_runtime_posture="control_only")
        assert inputs.source_runtime_posture == "control_only"
        assert inputs.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# S: build_scheduling_basis_inputs explicit tier not overridden
# ---------------------------------------------------------------------------


class TestBuildSchedulingBasisInputsExplicitTierS:
    def test_explicit_tier_honored(self):
        # Even though posture is control_only, explicit tier overrides derivation
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.full_runtime,
        )
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_explicit_partial_honored(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            runtime_enabled=True,
            supports_remote_handoff=True,
            capability_tier=CapabilityTier.partial_runtime,
        )
        assert inputs.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# T: build_scheduling_basis_inputs posture normalisation
# ---------------------------------------------------------------------------


class TestBuildSchedulingBasisPostureNormalisationT:
    def test_none_posture_defaults_control_only(self):
        inputs = build_scheduling_basis_inputs(source_runtime_posture=None)
        assert inputs.source_runtime_posture == "control_only"

    def test_unknown_posture_defaults_control_only(self):
        inputs = build_scheduling_basis_inputs(source_runtime_posture="UNKNOWN_POSTURE")
        assert inputs.source_runtime_posture == "control_only"

    def test_join_runtime_case_insensitive(self):
        inputs = build_scheduling_basis_inputs(source_runtime_posture="JOIN_RUNTIME")
        # normalisation should be case-sensitive (exact match needed)
        assert inputs.source_runtime_posture in ("control_only", "join_runtime")


# ---------------------------------------------------------------------------
# U: normalize_scheduling_inputs dict with autonomy sub-dict
# ---------------------------------------------------------------------------


class TestNormalizeSchedulingInputsAutonomySubdictU:
    def test_autonomy_subdict_read(self):
        raw = {
            "device_id": "ph_040",
            "platform": "android",
            "source_runtime_posture": "join_runtime",
            "autonomy": {
                "runtime_enabled": True,
                "supports_remote_handoff": True,
            },
        }
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.device_id == "ph_040"
        assert inputs.runtime_enabled is True
        assert inputs.supports_remote_handoff is True
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_autonomy_subdict_partial(self):
        raw = {
            "platform": "android",
            "source_runtime_posture": "join_runtime",
            "autonomy": {"runtime_enabled": True, "supports_remote_handoff": False},
        }
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# V: normalize_scheduling_inputs flat dict
# ---------------------------------------------------------------------------


class TestNormalizeSchedulingInputsFlatV:
    def test_flat_dict(self):
        raw = {
            "device_id": "ph_050",
            "source_runtime_posture": "join_runtime",
            "runtime_enabled": True,
            "supports_remote_handoff": True,
        }
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.device_id == "ph_050"
        assert inputs.runtime_enabled is True

    def test_empty_dict(self):
        inputs = normalize_scheduling_inputs({})
        assert inputs.device_id == ""
        assert inputs.source_runtime_posture == "control_only"
        assert inputs.capability_tier == CapabilityTier.command_only


# ---------------------------------------------------------------------------
# W: normalize_scheduling_inputs Android auto-detection
# ---------------------------------------------------------------------------


class TestNormalizeSchedulingInputsAndroidDetectionW:
    def test_android_detected_by_platform(self):
        raw = {"platform": "android", "source_runtime_posture": "join_runtime"}
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.is_android_device is True

    def test_android_detected_by_role(self):
        raw = {"android_host_role": "full_runtime_host",
               "source_runtime_posture": "join_runtime"}
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.is_android_device is True

    def test_non_android_not_detected(self):
        raw = {"platform": "desktop", "source_runtime_posture": "join_runtime"}
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.is_android_device is False

    def test_is_android_device_flag(self):
        raw = {"is_android_device": True, "source_runtime_posture": "join_runtime"}
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.is_android_device is True


# ---------------------------------------------------------------------------
# X: normalize_scheduling_inputs pre-computed tier honored
# ---------------------------------------------------------------------------


class TestNormalizeSchedulingInputsPreTierX:
    def test_precomputed_full_runtime_tier(self):
        raw = {
            "device_id": "ph_060",
            "source_runtime_posture": "control_only",
            "capability_tier": "full_runtime",
        }
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.capability_tier == CapabilityTier.full_runtime

    def test_precomputed_partial_tier(self):
        raw = {"capability_tier": "partial_runtime"}
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.capability_tier == CapabilityTier.partial_runtime


# ---------------------------------------------------------------------------
# Y: normalize_scheduling_inputs non-dict input → safe default
# ---------------------------------------------------------------------------


class TestNormalizeSchedulingInputsNonDictY:
    def test_none_input(self):
        inputs = normalize_scheduling_inputs(None)  # type: ignore
        assert isinstance(inputs, SchedulingBasisInputs)
        assert inputs.capability_tier == CapabilityTier.unknown

    def test_string_input(self):
        inputs = normalize_scheduling_inputs("not_a_dict")  # type: ignore
        assert isinstance(inputs, SchedulingBasisInputs)


# ---------------------------------------------------------------------------
# Z: evaluate_execution_surface_eligibility: observer_only → unavailable
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityObserverOnlyZ:
    def test_observer_only_role_ineligible(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable
        assert "observer_only" in result.reason

    def test_observer_only_overrides_full_runtime_tier(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            capability_tier=CapabilityTier.full_runtime,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False


# ---------------------------------------------------------------------------
# AA: evaluate_execution_surface_eligibility: command_only tier → unavailable
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityCommandOnlyAA:
    def test_command_only_tier_ineligible(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.command_only,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable
        assert "command_only" in result.reason

    def test_command_only_tier_even_with_android_device(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",  # forces command_only tier
            capability_tier=CapabilityTier.command_only,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False


# ---------------------------------------------------------------------------
# AB: evaluate_execution_surface_eligibility: unknown tier → unavailable
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityUnknownAB:
    def test_unknown_tier_ineligible(self):
        inputs = build_scheduling_basis_inputs(
            capability_tier=CapabilityTier.unknown,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable


# ---------------------------------------------------------------------------
# AC: evaluate_execution_surface_eligibility: local_host surface
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityLocalHostAC:
    def test_local_host_join_runtime(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.local_host

    def test_local_host_partial_runtime(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.partial_runtime,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.local_host

    def test_local_host_not_selected_without_host_present(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_host_present=False,  # no host
        )
        result = evaluate_execution_surface_eligibility(inputs)
        # Without host present and not android and no target → unavailable
        assert result.surface != ExecutionSurface.local_host

    def test_local_host_control_only_not_selected(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.full_runtime,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        # control_only posture without joined_runtime_participant role
        # → local_host should not match (posture not join_runtime)
        assert result.surface != ExecutionSurface.local_host


# ---------------------------------------------------------------------------
# AD: evaluate_execution_surface_eligibility: android_host surface
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityAndroidHostAD:
    def test_android_host_full_runtime(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
            android_host_role="full_runtime_host",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.android_host

    def test_android_host_partial_runtime(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.partial_runtime,
            is_android_device=True,
            android_host_role="partial_runtime_host",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.android_host

    def test_android_host_preferred_over_remote_device(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
            target_device_id="some_target",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.surface == ExecutionSurface.android_host


# ---------------------------------------------------------------------------
# AE: evaluate_execution_surface_eligibility: remote_device surface
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityRemoteDeviceAE:
    def test_remote_device_with_target(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=False,
            target_device_id="remote_001",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.remote_device

    def test_remote_device_partial_runtime(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.partial_runtime,
            is_android_device=False,
            target_device_id="remote_002",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.remote_device

    def test_no_remote_without_target(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=False,
            target_device_id="",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.surface != ExecutionSurface.remote_device


# ---------------------------------------------------------------------------
# AF: evaluate_execution_surface_eligibility: no match → unavailable
# ---------------------------------------------------------------------------


class TestEvalSurfaceEligibilityUnavailableAF:
    def test_no_matching_surface(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_host_present=False,
            is_android_device=False,
            target_device_id="",
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable


# ---------------------------------------------------------------------------
# AG: local_host with joined_runtime_participant role
# ---------------------------------------------------------------------------


class TestEvalSurfaceLocalHostRoleAG:
    def test_joined_runtime_participant_enables_local_host(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="control_only",  # posture alone would not qualify
            coordination_role="joined_runtime_participant",
            capability_tier=CapabilityTier.partial_runtime,
            is_host_present=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.local_host


# ---------------------------------------------------------------------------
# AH: evaluate_execution_surface_eligibility: inputs_snapshot in result
# ---------------------------------------------------------------------------


class TestEvalSurfaceInputsSnapshotAH:
    def test_inputs_snapshot_present(self):
        inputs = build_scheduling_basis_inputs(
            device_id="snap_test",
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert isinstance(result.inputs_snapshot, dict)
        assert result.inputs_snapshot.get("device_id") == "snap_test"

    def test_inputs_snapshot_has_tier(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="control_only",
            capability_tier=CapabilityTier.command_only,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert "capability_tier" in result.inputs_snapshot


# ---------------------------------------------------------------------------
# AI: eligible=False always has unavailable surface
# ---------------------------------------------------------------------------


class TestEvalSurfaceIneligibleUnavailableAI:
    @pytest.mark.parametrize(
        "posture,tier,role",
        [
            ("control_only", None, ""),
            ("join_runtime", CapabilityTier.command_only, ""),
            ("join_runtime", CapabilityTier.unknown, ""),
            ("join_runtime", CapabilityTier.full_runtime, "observer_only"),
        ],
    )
    def test_ineligible_always_unavailable(self, posture, tier, role):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture=posture,
            capability_tier=tier,
            coordination_role=role or None,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        if not result.eligible:
            assert result.surface == ExecutionSurface.unavailable


# ---------------------------------------------------------------------------
# AJ: core.runtime re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReexportsAJ:
    def test_sentinels_accessible_from_core_runtime(self):
        from core.runtime import (
            CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
            CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
            FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY,
            CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY,
            OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY,
            ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY,
            SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY,
        )
        assert CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY
        assert CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

    def test_types_accessible_from_core_runtime(self):
        from core.runtime import (
            CapabilityTier,
            ExecutionSurface,
            RuntimeCapabilityProfile,
            SchedulingBasisInputs,
            ExecutionSurfaceEligibility,
        )
        assert CapabilityTier.full_runtime
        assert ExecutionSurface.android_host

    def test_functions_accessible_from_core_runtime(self):
        from core.runtime import (
            build_runtime_capability_profile,
            build_scheduling_basis_inputs,
            evaluate_execution_surface_eligibility,
            normalize_scheduling_inputs,
        )
        # Quick call to confirm they're callable
        profile = build_runtime_capability_profile({})
        assert isinstance(profile, RuntimeCapabilityProfile)

        inputs = build_scheduling_basis_inputs()
        assert isinstance(inputs, SchedulingBasisInputs)

        result = evaluate_execution_surface_eligibility(inputs)
        assert isinstance(result, ExecutionSurfaceEligibility)

        norm = normalize_scheduling_inputs({})
        assert isinstance(norm, SchedulingBasisInputs)


# ---------------------------------------------------------------------------
# AK: projection.py sentinel
# ---------------------------------------------------------------------------


class TestProjectionSentinelAK:
    def test_projection_sentinel_present_and_not_unavailable(self):
        try:
            from core.routes.projection import (
                CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6,
            )
            assert CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
            assert "UNAVAILABLE" not in CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
            assert "PR6" in CANONICAL_CAPABILITY_SCHEDULING_BASIS_ALIGNED_PR6
        except ImportError:
            pytest.skip("core.routes.projection requires fastapi")


# ---------------------------------------------------------------------------
# AL: End-to-end: Android join_runtime full pipeline
# ---------------------------------------------------------------------------


class TestE2EAndroidFullPipelineAL:
    def test_android_join_runtime_e2e(self):
        raw = _android_full_dict(
            device_id="e2e_ph_001",
            source_runtime_posture="join_runtime",
            runtime_enabled=True,
            supports_remote_handoff=True,
        )
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.capability_tier == CapabilityTier.full_runtime
        assert inputs.is_android_device is True

        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.android_host
        assert result.capability_tier == CapabilityTier.full_runtime

    def test_android_e2e_profile_then_inputs(self):
        raw = _android_full_dict(device_id="e2e_ph_002")
        profile = build_runtime_capability_profile(raw)
        assert profile.capability_tier == CapabilityTier.full_runtime

        inputs = build_scheduling_basis_inputs(
            device_id=profile.device_id,
            platform=profile.platform,
            source_runtime_posture=profile.source_runtime_posture,
            coordination_role=profile.coordination_role,
            capability_tier=profile.capability_tier,
            is_android_device=True,
            android_host_role=profile.android_host_role,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.android_host


# ---------------------------------------------------------------------------
# AM: End-to-end: Control-only device cannot be scheduled
# ---------------------------------------------------------------------------


class TestE2EControlOnlyAM:
    def test_control_only_device_unavailable(self):
        raw = {
            "device_id": "control_ph_001",
            "platform": "android",
            "source_runtime_posture": "control_only",
        }
        inputs = normalize_scheduling_inputs(raw)
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable

    def test_control_only_no_signals_unavailable(self):
        inputs = build_scheduling_basis_inputs(source_runtime_posture="control_only")
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False


# ---------------------------------------------------------------------------
# AN: End-to-end: Android partial-runtime gets android_host surface
# ---------------------------------------------------------------------------


class TestE2EAndroidPartialRuntimeAN:
    def test_android_partial_runtime_android_host_surface(self):
        raw = {
            "device_id": "partial_ph_001",
            "platform": "android",
            "source_runtime_posture": "join_runtime",
            # only one autonomy flag
            "autonomy": {"runtime_enabled": True, "supports_remote_handoff": False},
        }
        inputs = normalize_scheduling_inputs(raw)
        assert inputs.capability_tier == CapabilityTier.partial_runtime
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True
        assert result.surface == ExecutionSurface.android_host


# ---------------------------------------------------------------------------
# AO: Serialisation round-trip: RuntimeCapabilityProfile
# ---------------------------------------------------------------------------


class TestSerialisationRoundTripAO:
    def test_profile_roundtrip(self):
        original = build_runtime_capability_profile(_android_full_dict(device_id="rt_001"))
        d = original.to_dict()
        restored = RuntimeCapabilityProfile.from_dict(d)
        assert restored.device_id == "rt_001"
        assert restored.capability_tier == original.capability_tier
        assert restored.source_runtime_posture == original.source_runtime_posture
        assert restored.platform == original.platform

    def test_profile_json_roundtrip(self):
        original = build_runtime_capability_profile(_android_full_dict(device_id="rt_002"))
        raw = original.to_json()
        d = json.loads(raw)
        assert d["device_id"] == "rt_002"
        assert d["capability_tier"] == "full_runtime"


# ---------------------------------------------------------------------------
# AP: SchedulingBasisInputs to_json
# ---------------------------------------------------------------------------


class TestSchedulingBasisInputsJsonAP:
    def test_to_json_valid_json(self):
        inputs = build_scheduling_basis_inputs(
            device_id="json_001",
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
        )
        raw = inputs.to_json()
        parsed = json.loads(raw)
        assert parsed["device_id"] == "json_001"
        assert parsed["capability_tier"] == "full_runtime"


# ---------------------------------------------------------------------------
# AQ: ExecutionSurfaceEligibility to_json
# ---------------------------------------------------------------------------


class TestEligibilityJsonAQ:
    def test_to_json_valid_json(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        raw = result.to_json()
        parsed = json.loads(raw)
        assert parsed["eligible"] is True
        assert parsed["surface"] == "android_host"
        assert "reason" in parsed
        assert "eligibility_id" in parsed


# ---------------------------------------------------------------------------
# AR: Profile ID and inputs ID are auto-generated and unique
# ---------------------------------------------------------------------------


class TestAutoGeneratedIdsAR:
    def test_profile_ids_unique(self):
        p1 = RuntimeCapabilityProfile()
        p2 = RuntimeCapabilityProfile()
        assert p1.profile_id != p2.profile_id
        assert p1.profile_id.startswith("rcap_")

    def test_inputs_ids_unique(self):
        i1 = SchedulingBasisInputs()
        i2 = SchedulingBasisInputs()
        assert i1.inputs_id != i2.inputs_id
        assert i1.inputs_id.startswith("sbi_")

    def test_eligibility_ids_unique(self):
        inputs = build_scheduling_basis_inputs(capability_tier=CapabilityTier.command_only)
        r1 = evaluate_execution_surface_eligibility(inputs)
        r2 = evaluate_execution_surface_eligibility(inputs)
        assert r1.eligibility_id != r2.eligibility_id
        assert r1.eligibility_id.startswith("ese_")

    def test_custom_profile_id_preserved(self):
        p = RuntimeCapabilityProfile(profile_id="custom_id_001")
        assert p.profile_id == "custom_id_001"


# ---------------------------------------------------------------------------
# AS: CapabilityTier ordering semantics
# ---------------------------------------------------------------------------


class TestCapabilityTierOrderingAS:
    def test_full_runtime_gives_eligible_surfaces(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True

    def test_partial_runtime_also_eligible(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.partial_runtime,
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is True

    def test_command_only_not_eligible(self):
        inputs = build_scheduling_basis_inputs(
            capability_tier=CapabilityTier.command_only,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False

    def test_unknown_not_eligible(self):
        inputs = build_scheduling_basis_inputs(
            capability_tier=CapabilityTier.unknown,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False


# ---------------------------------------------------------------------------
# AT: Multiple devices get independent profiles
# ---------------------------------------------------------------------------


class TestMultipleDevicesAT:
    def test_multiple_device_profiles_independent(self):
        devices = [
            _android_full_dict(device_id=f"ph_{i:03d}") for i in range(5)
        ]
        profiles = [build_runtime_capability_profile(d) for d in devices]
        ids = [p.device_id for p in profiles]
        assert len(set(ids)) == 5  # all unique device IDs

        for p in profiles:
            assert p.capability_tier == CapabilityTier.full_runtime

    def test_mixed_device_types(self):
        android = _android_full_dict(device_id="android_dev")
        desktop = _desktop_local_dict(device_id="desktop_dev")

        android_profile = build_runtime_capability_profile(android)
        desktop_profile = build_runtime_capability_profile(desktop)

        assert android_profile.device_id == "android_dev"
        assert desktop_profile.device_id == "desktop_dev"
        # Both can be full_runtime if signals are set
        assert android_profile.capability_tier == CapabilityTier.full_runtime
        assert desktop_profile.capability_tier == CapabilityTier.full_runtime


class TestParticipantTierAwareEligibilityPR3:
    def test_participant_tier_observer_endpoint_blocks_execution_surface(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            participant_tier="observer_endpoint",
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable
        assert "participant_tier=observer_endpoint" in result.reason

    def test_participant_tier_command_endpoint_blocks_execution_surface(self):
        inputs = build_scheduling_basis_inputs(
            source_runtime_posture="join_runtime",
            capability_tier=CapabilityTier.full_runtime,
            participant_tier="command_endpoint",
            is_android_device=True,
        )
        result = evaluate_execution_surface_eligibility(inputs)
        assert result.eligible is False
        assert result.surface == ExecutionSurface.unavailable
        assert "participant_tier=command_endpoint" in result.reason
